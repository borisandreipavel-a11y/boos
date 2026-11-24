"""A document of text and tables, which the model writes with the tool write_document, worked out from the notes apart
from the kernel's code (docs/screen.md "A document of text" and "Documents", docs/tools.md `write_document`): the tool
as it is offered, how the lines are read and laid out in pages, what the kernel says, the lines and the name a document
keeps, and the picture of a page in a look. Nothing runs when this file is imported, but the checks at its end, worked
out by hand from the notes.

A document as written and laid out is a dict: title (as drawn in the title's row), pages (each a list of what is drawn
on it, ("row", top, text) for a row of text and ("table", top, widths, head, rows) for a table or a piece of one, `top`
in dots below the top of the page, `head` None for a table without one), shown (the page shown, counted from 0) and
columns_left_out (whether a table had more columns than fit)."""
import re

import table_model
from app_cases import hide
from look_values import LOOKS
from picture import LETTER_HEIGHT

SIZE, SIGN, ROW, LINE, FRAME = table_model.SIZE, table_model.SIGN, table_model.ROW, table_model.LINE, table_model.FRAME
COLUMNS_MOST = table_model.COLUMNS_MOST
TEXT_ROW = SIZE * (LETTER_HEIGHT + 1)
assert TEXT_ROW == 20
NAME_MOST = 45
DOCUMENT_INPUTS_LONGEST = 8192


def room(width, height):
    """The table's room inside the frame (table_model.room), or None, with what a page of a document holds: the dots
    from below the title's row down to the bottom of the room inside (`height`), the rows of text in them, and the
    signs across."""
    found = table_model.room(width, height)
    if found is None:
        return None
    _, top, _, frame_height = found["place"]
    bottom = top + frame_height - FRAME - table_model.PADDING
    page = bottom - found["table_top"]
    return dict(found, height=page, rows_of_text=page // TEXT_ROW, signs=found["width"] // SIGN)


# ---------- The tool ----------

TOLD = ("Writes a document of text and tables in the frame on the screen, beside the panel of apps, in place of what it shows, "
        "and keeps it on the disk as a document, named by its title. "
        "Use it when the person wants something written down to keep or read: notes, a summary, a guide, with tables where they fit. "
        "The document is written as lines, one thing to a line, each beginning with the word that says what it is: "
        "title and the document's name; text and a paragraph; head and a table's head's cells; then row and a row's cells, one line for each row. "
        "Cells are parted by |, and a new head begins another table. "
        "Begin a new document with the line document 0; to change a kept document, write it whole again, beginning with document and its number. "
        "Keep it under 6000 signs. The screen shows it a page at a time, %d rows of %d signs, and the person turns the pages.")
EXAMPLE = ("The document, as lines, such as:\ndocument 0\ntitle The Moon\ntext The Moon is Earth's only natural satellite.\n"
           "head Fact | Value\nrow Distance | 384,400 km\nrow Diameter | 3,474 km")


def tool_meant(width=1280, height=800):
    """write_document as it goes with a line where documents can be kept on a screen of this size, or None where the
    screen has no room for the frame."""
    found = room(width, height)
    if found is None:
        return None
    return {"type": "function", "function": {"name": "write_document", "description": TOLD % (found["rows_of_text"], found["signs"]),
                                             "parameters": {"type": "object", "properties": {"lines": {"type": "string", "description": EXAMPLE}},
                                                            "required": ["lines"]}}}


# ---------- Reading the lines ----------

def line_parts(line):
    """A line's first word, its plain capitals made small and a colon right behind it left off, and the rest of the
    line; spaces, tabs and a return at either end of the line do not count."""
    line = line.strip(" \t\r")
    ends = [place for place in (line.find(" "), line.find("\t")) if place >= 0]
    end = min(ends) if ends else len(line)
    word, rest = table_model.lower(line[:end]), line[end:].lstrip(" \t")
    return (word[:-1] if word.endswith(":") else word), rest


def number_of(rest):
    """The number on a `document` line: a whole number of at most nine digits, or None for anything else."""
    if not rest or len(rest) > 9 or not all(sign in "0123456789" for sign in rest):
        return None
    return int(rest)


def read(text):
    """The lines read as the notes say: (the number on the `document` line or None, the title or None, the blocks),
    each block ["text", paragraph] or ["table", head or None, rows]. `document` and `title` count only before the first
    block, the later of two; any other line is skipped."""
    number, title, blocks = None, None, []
    for line in text.split("\n"):
        word, rest = line_parts(line)
        if word == "text":
            blocks.append(["text", rest])
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
            number = number_of(rest)
        elif word == "title":
            title = rest
    return number, title, blocks


def plain(text):
    """Byte by byte, every byte that is not a plain sign a dot."""
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in text.encode("utf-8"))


def rows_of(paragraph, across):
    """A paragraph set into rows of at most `across` signs: parted into words at runs of spaces and tabs, each word
    cleaned; as many whole words to a row as fit, parted by one space; a word longer than a row cut into pieces as long
    as a row, each on a row of its own; no words, one empty row."""
    rows, row = [], ""
    for word in re.split(r"[ \t]+", paragraph):
        if not word:
            continue
        word = plain(word)
        if len(word) > across:
            if row:
                rows.append(row)
                row = ""
            rows += [word[start:start + across] for start in range(0, len(word), across)]
        elif not row:
            row = word
        elif len(row) + 1 + len(word) <= across:
            row += " " + word
        else:
            rows.append(row)
            row = word
    if row or not rows:
        rows.append(row)
    return rows


# ---------- Pages ----------

def laid_out(blocks, found_room):
    """The blocks laid out in pages: (pages, whether a table had more columns than fit)."""
    height, across = found_room["height"], found_room["signs"]
    pages, used, left_out = [[]], 0, False

    def next_page():
        pages.append([])
        return 0

    for place, block in enumerate(blocks):
        # One empty row between two blocks when more than its 20 dots are left below the block before; else the next
        # block begins on the next page. None at the top of a page.
        if place > 0 and used > 0:
            used = used + TEXT_ROW if height - used > TEXT_ROW else next_page()
        if block[0] == "text":
            for row in rows_of(block[1], across):
                if used + TEXT_ROW > height:
                    used = next_page()
                pages[-1].append(("row", used, row))
                used += TEXT_ROW
            continue
        _, head, rows = block
        columns = len(head) if head is not None else len(rows[0])
        drawn_columns = min(columns, COLUMNS_MOST)
        left_out = left_out or columns > drawn_columns
        # Each column as wide as its longest cell, the head's among them, in all the rows of the table (bytes, as the
        # kernel counts signs), shared as when no widths are asked.
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
        # The table begins here if its head, its first row and the line below them fit; else on the next page.
        if used > 0 and used + head_height + (ROW if rows else 0) + LINE > height:
            used = next_page()
        start = 0
        while True:
            take = min(max(height - used - head_height - LINE, 0) // ROW, len(rows) - start)
            if take == 0 and start < len(rows) and used == 0:
                take = 1  # a page with no room for a single row still takes one
            pages[-1].append(("table", used, widths, head, rows[start:start + take]))
            used += head_height + take * ROW + LINE
            start += take
            if start >= len(rows):
                break
            used = next_page()
    return pages, left_out


def page_mark(shown, count):
    return "page %d of %d" % (shown + 1, count)


def counted(count, one, more):
    return "%d %s" % (count, one if count == 1 else more)


# ---------- What the kernel says ----------

CANNOT_READ = "Kernel: the model asked to write a document, but I could not read it."
NOTHING = "Kernel: the model asked to write a document, but it has nothing in it."
CUT_EARLY = "Kernel: the model asked to write a document, but it was cut off before any of its lines came whole."
NOT_HERE = "Kernel: the model asked to write a document, but documents cannot be kept on this machine."


def cut_change_row(number):
    return "Kernel: the new lines for document %d were cut off, so I left the document as it was." % number


def said_of(document, whole=True):
    """What the kernel says about a document it wrote: its title as drawn and its pages, what did not fit, and
    whether it was cut off."""
    pages = counted(len(document["pages"]), "page", "pages")
    said = ('I wrote the document "%s", %s' % (document["title"], pages)) if document["title"] else "I wrote a document of %s" % pages
    if document["columns_left_out"]:
        said += "; a table had more columns than fit, and only its first %d were drawn" % COLUMNS_MOST
    if not whole:
        said += "; it was cut off, so I wrote only the lines that came whole"
    return "Kernel: " + said + "."


def opened_fit(document):
    """What stands behind "I opened document 1, ..." for a document of text: its pages, and what did not fit."""
    fit = ", " + counted(len(document["pages"]), "page", "pages")
    if document["columns_left_out"]:
        fit += "; a table had more columns than fit, and only its first %d were drawn" % COLUMNS_MOST
    return fit


def written(text, whole=True, width=1280, height=800, key=""):
    """What the kernel makes of the text the model gave write_document (as the JSON reader gives it, and whether its
    closing quote came): (the document as laid out, its first page shown, or None when nothing is written; the row the
    kernel says, without what it says about keeping it; whether it was written whole, so that the line ends)."""
    found_room = room(width, height)
    if found_room is None:
        return None, NOT_HERE, False
    text = hide(text, key) if key else text
    if not whole:
        end = text.rfind("\n")
        text = text[:end] if end >= 0 else ""
    _, title, blocks = read(text)
    if not blocks:
        return None, NOTHING if whole else CUT_EARLY, False
    pages, left_out = laid_out(blocks, found_room)
    # The title is cut to leave room for the last page's mark and one sign more, when there is more than one page.
    mark_room = len(page_mark(len(pages) - 1, len(pages))) + 1 if len(pages) > 1 else 0
    drawn = table_model.shown(title, found_room["signs"] - mark_room) if title is not None else ""
    document = dict(title=drawn, pages=pages, shown=0, columns_left_out=left_out)
    return document, said_of(document, whole), whole and not left_out


def turned(document, forward):
    """The document after Page Down (`forward`) or Page Up: the next page or the one before; nothing at either end."""
    shown = document["shown"] + (1 if forward else -1)
    return dict(document, shown=shown) if 0 <= shown < len(document["pages"]) else document


# ---------- What a document keeps ----------

def lines_kept(text):
    """The lines a document of text keeps: every line as the model wrote it, but the `document` lines before the
    first paragraph or table."""
    kept, begun = [], False
    for line in text.split("\n"):
        word, _ = line_parts(line)
        begun = begun or word in ("text", "head", "row")
        if not begun and word == "document":
            continue
        kept.append(line)
    return "\n".join(kept)


def name_of(text):
    """A document's name: its title, cleaned, spaces at either end gone, at most 45 signs; "" without a title."""
    title = read(text)[1]
    return plain(title).strip(" ")[:NAME_MOST].rstrip(" ") if title is not None else ""


# ---------- The picture ----------

def grid(picture, left, top, widths, head, rows, colours):
    """A table's head, if it has one, and rows, in the look's colours (table_model.paint's way with a table whose
    colours the model left out), from `left` and `top`."""
    head_back, rows_back, lines = colours["panel_frame"], colours["panel_inside"], colours["panel_frame"]
    head_letters = table_model.readable(colours["panel_text"], head_back)
    letters = table_model.readable(colours["panel_text"], rows_back)
    cell_widths = [table_model.CELL_LEFT + width * SIGN + table_model.CELL_RIGHT for width in widths]
    every = ([(head, head_back, head_letters)] if head is not None else []) + [(row, rows_back, letters) for row in rows]
    picture.rectangle(left, top, LINE + sum(cell + LINE for cell in cell_widths), len(every) * ROW + LINE, lines)
    y = top
    for cells, back, front in every:
        x = left
        for cell, cell_width in zip(cells, cell_widths):
            picture.rectangle(x + LINE, y + LINE, cell_width, ROW - LINE, back)
            picture.text(x + LINE + table_model.CELL_LEFT, y + LINE + table_model.CELL_TOP, cell, SIZE, front)
            x += LINE + cell_width
        y += ROW


def paint(picture, document, look="Blue"):
    """Paints the frame, the title's row and the page shown into a picture.Picture, in the look with this name."""
    found = room(picture.width, picture.height)
    colours = LOOKS[look]
    left, top, width, height = found["place"]
    picture.rectangle(left, top, width, height, colours["panel_frame"])
    picture.rectangle(left + FRAME, top + FRAME, width - 2 * FRAME, height - 2 * FRAME, colours["panel_inside"])
    picture.text(found["left"], found["title_top"], document["title"], SIZE, colours["panel_text"])
    count = len(document["pages"])
    if count > 1:
        mark = page_mark(document["shown"], count)
        picture.text(found["left"] + (found["signs"] - len(mark)) * SIGN, found["title_top"], mark, SIZE, colours["panel_text"])
    for item in document["pages"][document["shown"]]:
        if item[0] == "row":
            picture.text(found["left"], found["table_top"] + item[1], item[2], SIZE, colours["panel_text"])
        else:
            _, at, widths, head, rows = item
            grid(picture, found["left"], found["table_top"] + at, widths, head, rows, colours)


# ---------- Checks, worked out by hand from the notes ----------

# QEMU's usual screen: below the title's row (rows 121 on) down to the bottom of the room inside (row 547), 426 dots: 21
# rows of text of 46 signs.
_ROOM = room(1280, 800)
assert (_ROOM["table_top"], _ROOM["height"], _ROOM["rows_of_text"], _ROOM["signs"]) == (121, 426, 21, 46)
assert room(800, 600) is None

# Words: one of 46 signs fills a row; 47 and 93 are cut into rows of 46; a row of words filled to exactly 46 signs.
assert rows_of("a" * 46, 46) == ["a" * 46]
assert rows_of("a" * 47, 46) == ["a" * 46, "a"]
assert rows_of("a" * 93, 46) == ["a" * 46, "a" * 46, "a"]
assert rows_of("abcd " * 9 + "a", 46) == ["abcd " * 9 + "a"] and len("abcd " * 9 + "a") == 46
assert rows_of("abcd " * 9 + "ab", 46) == [("abcd " * 9).rstrip(), "ab"]
assert rows_of("hi " + "b" * 50 + " yo", 46) == ["hi", "b" * 46, "bbbb", "yo"]
assert rows_of("", 46) == [""] and rows_of(" \t ", 46) == [""]
assert rows_of("  two\t\tspaces  ", 46) == ["two spaces"]
assert rows_of("x €\tz", 46) == ["x ... z"]  # the euro sign is three bytes: three dots

# Lines: `document` and `title` only before the first block, the later of two; `colours`, `widths` and anything else
# skipped; a row after a paragraph begins a table without a head; a head begins a new table.
_TEXT = "\n".join(["document 3", "Title: First", "TITLE second", "colours head #000000", "text One", "title Late", "document 9",
                   "row a | b", "row c | d", "head X | Y", "row 1 | 2", "widths 3 4", "text Two"])
assert read(_TEXT) == (3, "second", [["text", "One"], ["table", None, [["a", "b"], ["c", "d"]]], ["table", ["X", "Y"], [["1", "2"]]],
                                     ["text", "Two"]])
assert read("document 1\ndocument x\ntext a")[0] is None and read("document 0012\ntext a")[0] == 12
assert read("document 1234567890\ntext a")[0] is None
assert lines_kept(_TEXT) == "\n".join(_TEXT.split("\n")[1:])
assert lines_kept("document 0\n\ntitle T\ntext a\ndocument 2") == "\ntitle T\ntext a\ndocument 2"
assert name_of(_TEXT) == "second" and name_of("text a") == ""


def _tops(text):
    """Where each page's rows and tables stand: [[(kind, top, rows), ...] for each page]."""
    pages, _ = laid_out(read(text)[2], _ROOM)
    return [[(item[0], item[1], 1 if item[0] == "row" else len(item[4])) for item in page] for page in pages]


def _paragraph(rows):
    """A paragraph of this many rows of 46 signs."""
    return "text " + " ".join(["a" * 46] * rows)


# A paragraph of 21 rows fills a page; one of 22 goes on to a second page.
assert [len(page) for page in _tops(_paragraph(21))] == [21]
assert [len(page) for page in _tops(_paragraph(22))] == [21, 1]
# After 20 rows (400 dots) 26 dots are left: the empty row stands, and the next paragraph's row (440 > 426) goes to the
# top of the next page. After 21 rows (420 dots) only 6 are left: the next block begins on the next page.
assert _tops(_paragraph(20) + "\ntext b")[1] == [("row", 0, 1)]
assert _tops(_paragraph(21) + "\ntext b")[1] == [("row", 0, 1)]
assert _tops(_paragraph(19) + "\ntext b")[0][-1] == ("row", 400, 1)  # 380, the empty row, then 400
# A table just fits behind 17 rows (340 dots, the empty row, 360: 360 + 28 + 28 + 2 = 418), with one row on the page
# and the rest under its head on the next; behind 18 rows (380: 438 > 426) it begins on the next page.
_TABLE = "\nhead H | I\n" + "\n".join("row %d | x" % n for n in range(20))
assert _tops(_paragraph(17) + _TABLE)[0][-1] == ("table", 360, 1) and _tops(_paragraph(17) + _TABLE)[1] == [("table", 0, 14)]
assert _tops(_paragraph(17) + _TABLE)[2] == [("table", 0, 5)]
assert _tops(_paragraph(18) + _TABLE)[1][0] == ("table", 0, 14)
# A table at the top of a page: the head and 14 rows (28 + 14 * 28 + 2 = 422); without a head, 15 rows (422).
assert _tops(_TABLE.strip("\n"))[0] == [("table", 0, 14)]
assert _tops("\n".join("row %d" % n for n in range(20)))[0] == [("table", 0, 15)]
# A head without rows is drawn as a head alone: 28 dots and the line.
assert _tops("head A | B\ntext c") == [[("table", 0, 0), ("row", 50, 1)]]
# Seven columns: six are drawn, and that is said.
_WIDE, _SAID, _WHOLE = written("title Wide\nhead a | b | c | d | e | f | g\nrow 1 | 2 | 3 | 4 | 5 | 6 | 7")
assert len(_WIDE["pages"][0][0][2]) == 6 and not _WHOLE
assert _SAID == 'Kernel: I wrote the document "Wide", 1 page; a table had more columns than fit, and only its first 6 were drawn.'
# Empty paragraphs take a row and the empty row behind it: 11 to a page (tops 0, 40, ... 400; then 6 dots are left). A
# title on a document of 125 of them, 12 pages, leaves room for "page 12 of 12" and one sign more: 46 - 14 = 32 signs.
assert [len(page) for page in _tops("\n".join(["text"] * 23))] == [11, 11, 1]
_LONG, _SAID, _ = written("title " + "T" * 60 + "\n" + "\n".join(["text"] * 125))
assert len(_LONG["pages"]) == 12 and _LONG["title"] == "T" * 32 and _SAID.startswith('Kernel: I wrote the document "' + "T" * 32 + '", 12 pages')
assert written("title x")[1] == NOTHING and written("title x\ntext a", whole=False)[1] == CUT_EARLY
assert written("text a\ntext b", whole=False)[1] == "Kernel: I wrote a document of 1 page; it was cut off, so I wrote only the lines that came whole."
