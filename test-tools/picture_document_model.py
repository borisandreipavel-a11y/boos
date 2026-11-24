"""Pictures in documents of text, worked out from the notes apart from the kernel's code (docs/screen.md "A document of
text", docs/tools.md `open_file` and `write_document`, docs/pictures.md): how a `picture` line is read, how a picture
is laid out on a page, shrunk and painted over the look's colour, what the kernel says, and what the document of a
picture keeps. The dots come from png_reference.py, the second reader, and its shrinking; text and tables are laid
out as text_document_model.py has them. Nothing runs when this file is imported, but the checks at its end, worked out
by hand from the notes.

A document as laid out is text_document_model's dict, with one more kind of thing on a page, ("picture", top, width,
height, dots) for a picture as shown (dots: four bytes each, red, green, blue and alpha), and two more keys: pictures,
the pictures shown, each (file, its own width, its own height), and not_shown, each (file, why).

The files a document may name are a dict, number -> (kind, data): the kind as a file's note keeps it ("png", "csv",
...). A number below `next_number` that is not in it was removed."""
import struct

import png_reference
import table_model
import text_document_model as text_model
from documents_model import KIND_TEXT, called
from download_cases import KINDS
from look_values import LOOKS

SIZE, SIGN, FRAME, ROW, LINE = text_model.SIZE, text_model.SIGN, text_model.FRAME, text_model.ROW, text_model.LINE
TEXT_ROW = text_model.TEXT_ROW
COLUMNS_MOST = text_model.COLUMNS_MOST
PICTURES_MOST = 4
FILE_MOST = 4 * 1024 * 1024
NOTE_FORM_FILE = 2


# ---------- Reading the lines ----------

def picture_line(rest):
    """The rest of a `picture` line: (the file's number, the caption or None), or None when the number cannot be read:
    the number as on a `document` line, and behind a `|` the caption, spaces and tabs at either end of each not
    counting, an empty caption none."""
    number, bar, caption = rest.partition("|")
    file = text_model.number_of(number.strip(" \t"))
    if file is None:
        return None
    caption = caption.strip(" \t") if bar else ""
    return file, (caption or None)


def read(text):
    """The lines read as the notes say: text_document_model.read's, with ["picture", file, caption or None] blocks; a
    `picture` line without a number is skipped, and a `row` after a picture begins a table without a head."""
    number, title, blocks = None, None, []
    for line in text.split("\n"):
        word, rest = text_model.line_parts(line)
        if word == "text":
            blocks.append(["text", rest])
        elif word == "picture":
            found = picture_line(rest)
            if found is not None:
                blocks.append(["picture", found[0], found[1]])
        elif word == "head":
            blocks.append(["table", table_model.cells(rest), []])
        elif word == "row":
            if blocks and blocks[-1][0] == "table":
                blocks[-1][2].append(table_model.cells(rest))
            else:
                blocks.append(["table", None, [table_model.cells(rest)]])
        elif blocks:
            continue
        elif word == "document":
            number = text_model.number_of(rest)
        elif word == "title":
            title = rest
    return number, title, blocks


def lines_kept(text):
    """The lines a document of text keeps: every line, but the `document` lines before the first paragraph, table or
    picture (a `picture` line counts only with a number)."""
    kept, begun = [], False
    for line in text.split("\n"):
        word, rest = text_model.line_parts(line)
        begun = begun or word in ("text", "head", "row") or (word == "picture" and picture_line(rest) is not None)
        if not begun and word == "document":
            continue
        kept.append(line)
    return "\n".join(kept)


# ---------- A picture from a kept file ----------

def picture_of(file, files, next_number, room_width, room_height, reasons=None):
    """File `file`'s picture as the kernel shows it in a room of this size: (its own width and height, the width and
    height shown, the dots shown), or why it is not shown, in words to stand after "because". `reasons`: number -> the
    reader's words, for the damaged files of a test (the crate's own words, docs/pictures.md)."""
    if file not in files:
        return "it was removed" if 0 < file < next_number else "no kept file has that number"
    kind, data = files[file]
    if kind != "png":
        return "it is %s, not a picture" % KINDS[kind]
    if len(data) > FILE_MOST:
        return "it is larger than the 4 MB I take"
    if reasons and file in reasons:
        return reasons[file]
    width, height, rgba = png_reference.png_read(data)
    shown_width, shown_height, dots = png_reference.shrink(width, height, rgba, room_width, room_height)
    return width, height, shown_width, shown_height, dots


# ---------- Pages ----------

def laid_out(blocks, found_room, files, next_number, reasons=None):
    """The blocks laid out in pages: (pages, whether a table had more columns than fit, the pictures shown, the
    pictures not shown). A picture with its caption never splits: it begins on the page where it stands if it fits there
    whole, else at the top of the next; its room is the room's width by a page's height, less a row for a caption. The
    first PICTURES_MOST picture lines are read; a picture not shown is rows of text that say why, as a paragraph's,
    with the caption under them."""
    height, across = found_room["height"], found_room["signs"]
    pages, used, left_out = [[]], 0, False
    shown, not_shown, tried = [], [], 0

    def next_page():
        pages.append([])
        return 0

    def rows_laid(rows, used):
        for row in rows:
            if used + TEXT_ROW > height:
                used = next_page()
            pages[-1].append(("row", used, row))
            used += TEXT_ROW
        return used

    for place, block in enumerate(blocks):
        if place > 0 and used > 0:
            used = used + TEXT_ROW if height - used > TEXT_ROW else next_page()
        if block[0] == "text":
            used = rows_laid(text_model.rows_of(block[1], across), used)
            continue
        if block[0] == "picture":
            _, file, caption = block
            caption_rows = [table_model.shown(caption, across)] if caption is not None else []
            caption_height = TEXT_ROW * len(caption_rows)
            tried += 1
            if tried > PICTURES_MOST:
                got = "a document shows at most %d pictures" % PICTURES_MOST
            else:
                got = picture_of(file, files, next_number, found_room["width"], height - caption_height, reasons)
            if isinstance(got, str):
                used = rows_laid(text_model.rows_of("picture of file %d: %s" % (file, got), across) + caption_rows, used)
                not_shown.append((file, got))
                continue
            width, tall, shown_width, shown_height, dots = got
            if used > 0 and used + shown_height + caption_height > height:
                used = next_page()
            pages[-1].append(("picture", used, shown_width, shown_height, dots))
            used = rows_laid(caption_rows, used + shown_height)
            shown.append((file, width, tall))
            continue
        # A table, as text_document_model lays one out.
        _, head, rows = block
        columns = len(head) if head is not None else len(rows[0])
        drawn_columns = min(columns, COLUMNS_MOST)
        left_out = left_out or columns > drawn_columns
        longest = [0] * drawn_columns
        for cells in ([head] if head is not None else []) + rows:
            for at, cell in enumerate(cells[:drawn_columns]):
                longest[at] = max(longest[at], len(cell.encode("utf-8")))
        widths = table_model.worked_out(None, longest, table_model.across(found_room["width"], drawn_columns))

        def fitted(cells):
            return [table_model.shown(cells[at] if at < len(cells) else "", width) for at, width in enumerate(widths)]

        head = fitted(head) if head is not None else None
        rows = [fitted(row) for row in rows]
        head_height = ROW if head is not None else 0
        if used > 0 and used + head_height + (ROW if rows else 0) + LINE > height:
            used = next_page()
        start = 0
        while True:
            take = min(max(height - used - head_height - LINE, 0) // ROW, len(rows) - start)
            if take == 0 and start < len(rows) and used == 0:
                take = 1
            pages[-1].append(("table", used, widths, head, rows[start:start + take]))
            used += head_height + take * ROW + LINE
            start += take
            if start >= len(rows):
                break
            used = next_page()
    return pages, left_out, shown, not_shown


# ---------- What the kernel says ----------

def fit(document):
    """What stands behind what the kernel wrote or opened: columns left out, and each picture not shown, with why."""
    said = "; a table had more columns than fit, and only its first %d were drawn" % COLUMNS_MOST if document["columns_left_out"] else ""
    for file, why in document["not_shown"]:
        said += "; the picture of file %d is not shown, because %s" % (file, why)
    return said


def said_of(document, whole=True):
    pages = text_model.counted(len(document["pages"]), "page", "pages")
    said = ('I wrote the document "%s", %s' % (document["title"], pages)) if document["title"] else "I wrote a document of %s" % pages
    said += fit(document)
    if not whole:
        said += "; it was cut off, so I wrote only the lines that came whole"
    return "Kernel: " + said + "."


def opened_fit(document):
    """What stands behind "I opened document 1, ..." for a document of text: its pages, and what did not fit."""
    return ", " + text_model.counted(len(document["pages"]), "page", "pages") + fit(document)


def written(text, files, next_number, reasons=None, width=1280, height=800):
    """What the kernel makes of a document of text with pictures, written whole: (the document as laid out, its first page
    shown; the row the kernel says, without what it says about keeping it; whether it was drawn whole, so that the line
    ends: every column, and every picture shown)."""
    found_room = text_model.room(width, height)
    _, title, blocks = read(text)
    pages, left_out, shown, not_shown = laid_out(blocks, found_room, files, next_number, reasons)
    mark_room = len(text_model.page_mark(len(pages) - 1, len(pages))) + 1 if len(pages) > 1 else 0
    drawn = table_model.shown(title, found_room["signs"] - mark_room) if title is not None else ""
    document = dict(title=drawn, pages=pages, shown=0, columns_left_out=left_out, pictures=shown, not_shown=not_shown)
    return document, said_of(document), not left_out and not not_shown


# ---------- A picture opened with open_file ----------

def picture_lines(file, name):
    """The lines of the document a picture opens into: its title, the file's name, and one picture line."""
    return "title %s\npicture %d" % (name, file)


def opened_row(file, name, width, height, number):
    return 'Kernel: I opened file %d, "%s", a PNG picture of %d by %d dots, as document %d.' % (file, name, width, height, number)


def not_opened_row(file, name, why):
    return 'Kernel: I did not open file %d, "%s", because %s.' % (file, name, why)


def reopened_row(document, file, laid):
    """The row when a picture that a document was made from before is opened again: that document, with its pages."""
    return "Kernel: I opened %s, made from file %d before%s." % (called(document), file, opened_fit(laid))


def note_from_picture(version, name, file):
    """The note of a document made from a kept file, of text: form 2, kind 2, the version, the file's number, the name."""
    return bytes([NOTE_FORM_FILE, KIND_TEXT]) + struct.pack("<I", version) + struct.pack("<I", file) + name.encode()


# ---------- The picture of the screen ----------

def over(colour, alpha, back):
    """One of red, green and blue painted over the look's colour as much as alpha says, rounded to the nearest."""
    return (colour * alpha + back * (255 - alpha) + 127) // 255


def dots_paint(picture, left, top, width, height, dots, back):
    """A picture's dots into a picture.Picture, each over `back`."""
    for y in range(height):
        row = bytearray()
        for x in range(width):
            red, green, blue, alpha = dots[(y * width + x) * 4:(y * width + x) * 4 + 4]
            row += bytes((over(red, alpha, back[0]), over(green, alpha, back[1]), over(blue, alpha, back[2])))
        start = ((top + y) * picture.width + left) * 3
        picture.dots[start:start + len(row)] = row


def paint(picture, document, look="Blue"):
    """Paints the frame, the title's row and the page shown, with its pictures, into a picture.Picture."""
    found = text_model.room(picture.width, picture.height)
    colours = LOOKS[look]
    left, top, width, height = found["place"]
    picture.rectangle(left, top, width, height, colours["panel_frame"])
    picture.rectangle(left + FRAME, top + FRAME, width - 2 * FRAME, height - 2 * FRAME, colours["panel_inside"])
    picture.text(found["left"], found["title_top"], document["title"], SIZE, colours["panel_text"])
    count = len(document["pages"])
    if count > 1:
        mark = text_model.page_mark(document["shown"], count)
        picture.text(found["left"] + (found["signs"] - len(mark)) * SIGN, found["title_top"], mark, SIZE, colours["panel_text"])
    for item in document["pages"][document["shown"]]:
        if item[0] == "row":
            picture.text(found["left"], found["table_top"] + item[1], item[2], SIZE, colours["panel_text"])
        elif item[0] == "picture":
            _, at, shown_width, shown_height, dots = item
            dots_paint(picture, found["left"], found["table_top"] + at, shown_width, shown_height, dots, colours["panel_inside"])
        else:
            _, at, widths, head, rows = item
            text_model.grid(picture, found["left"], found["table_top"] + at, widths, head, rows, colours)


# ---------- Checks, worked out by hand from the notes ----------

# The room of a picture on QEMU's usual screen: the room's 554 dots across by a page's 426, 406 with a caption.
_ROOM = text_model.room(1280, 800)
assert (_ROOM["width"], _ROOM["height"]) == (554, 426)
assert png_reference.fitted_size(1600, 1200, 554, 426) == (554, 416)
assert png_reference.fitted_size(1600, 1200, 554, 406) == (541, 406)
# The line read: a number and a caption; spaces round both; an empty caption is none; no number, no picture.
assert picture_line("3") == (3, None) and picture_line(" 3 | The harbour ") == (3, "The harbour") and picture_line("3 |  ") == (3, None)
assert picture_line("3 2") is None and picture_line("") is None and picture_line("| caption") is None and picture_line("1234567890") is None
# The blend: wholly there, not at all, and half of white over black, rounded to the nearest.
assert over(200, 255, 7) == 200 and over(200, 0, 7) == 7 and over(255, 128, 0) == 128 and over(255, 127, 0) == 127
