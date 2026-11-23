"""The table the model describes with the tool draw_table, worked out from the notes apart from the kernel's code
(docs/screen.md, "The table"; docs/tools.md, `draw_table`): where the frame sits and how much room it has, the tool
as it is offered, how a description is read, what the kernel says about it, and the picture of the frame and the
table in a look. Nothing runs when this file is imported.

A table, as drawn and kept, is a dict: title, colours (five, each an (r, g, b) or None, in the order of PARTS),
widths (signs per column), head (a list of cells, or None) and rows (lists of cells), every cell as shown."""
import re

from app_cases import hide
from look_values import LOOKS
from picture import LETTER_HEIGHT, LETTER_WIDTH

# The places the frame is worked out from: the panel of apps (docs/apps.md: 40 dots from the left, 80 from the
# top, 600 across, 158 high, on every screen) and the chat box (docs/chat.md: 40 dots from the left, right and
# bottom edges, 180 high).
APPS_LEFT, APPS_TOP, APPS_WIDTH, APPS_HEIGHT = 40, 80, 600, 158
CHAT_MARGIN, CHAT_HEIGHT = 40, 180

# The table's sizes (docs/screen.md, "The table").
GAP = 20
FRAME = 3
PADDING = 10
SIZE = 2
LINE = 2
CELL_LEFT, CELL_RIGHT, CELL_TOP, CELL_BOTTOM = 5, 3, 4, 4
COLUMNS_MOST = 6
NARROWEST = 1000
SIGN = SIZE * (LETTER_WIDTH + 1)
ROW = LINE + CELL_TOP + SIZE * LETTER_HEIGHT + CELL_BOTTOM
assert (SIGN, ROW) == (12, 28)

PARTS = ["head", "head-letters", "rows", "letters", "lines"]
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def frame_place(width, height):
    """(left, top, width, height) of the frame on a screen of this size, or None: beside the panel of apps, 20 dots
    from it, level with its top, to the chat box's right edge and 20 dots above the chat box; none on a screen
    narrower than 1000 dots or without one."""
    if not width or width < NARROWEST:
        return None
    left = APPS_LEFT + APPS_WIDTH + GAP
    right = width - CHAT_MARGIN
    bottom = height - CHAT_MARGIN - CHAT_HEIGHT - GAP
    if right <= left or bottom <= APPS_TOP:
        return None
    return left, APPS_TOP, right - left, bottom - APPS_TOP


def across(room_width, columns):
    """How many signs fit across a table `room_width` dots wide with this many columns, all together."""
    return max(room_width - LINE - columns * (LINE + CELL_LEFT + CELL_RIGHT), 0) // SIGN


def room(width, height):
    """The room inside the frame, or None when there is no frame or no room for the head and a row, or for a sign in
    each of the most columns."""
    place = frame_place(width, height)
    if place is None:
        return None
    left, top, frame_width, frame_height = place
    inner = FRAME + PADDING
    title_top = top + inner
    table_top = title_top + ROW
    room_width = frame_width - 2 * inner
    rows = max(top + frame_height - inner - table_top - LINE, 0) // ROW
    if rows < 2 or across(room_width, COLUMNS_MOST) < COLUMNS_MOST:
        return None
    return dict(place=place, left=left + inner, title_top=title_top, table_top=table_top, width=room_width, rows=rows)


# What the notes give for QEMU's usual screen: a frame of 580 by 480 dots from column 660, row 80; the head and 14
# rows; 41 signs across with six columns.
assert frame_place(1280, 800) == (660, 80, 580, 480)
assert room(1280, 800)["rows"] == 15 and across(room(1280, 800)["width"], 6) == 41
assert room(800, 600) is None and room(None, None) is None


# ---------- The tool ----------

TOLD = ("Draws a table in a frame on the screen, beside the panel of apps, in place of the table shown before. "
        "Use it when the person wants something shown as a table. "
        "The table is written as lines, one thing to a line, each beginning with the word that says what it is: "
        "title and the table's name; "
        "colours and any of head, head-letters, rows, letters and lines (the head's background and letters, the rows' background and letters, and the lines between the cells), "
        "each followed by its colour as # and six hex digits, picked to fit the wish; "
        "widths and the number of signs each column needs; head and the head's cells; then row and a row's cells, one line for each row. "
        "Cells are parted by |. Everything but the rows comes before the first row. "
        "This screen has room for the head and %d rows, at most %d columns, and %d signs across all columns together; "
        "longer cells are cut, and rows that do not fit are left out.")
EXAMPLE = ("The table, as lines, such as:\ntitle Fruit\ncolours head #2e7d32 head-letters #ffffff\nwidths 10 12\n"
           "head Fruit | Colour\nrow Apple | red\nrow Banana | yellow")


def tool_meant(width=1280, height=800):
    """The tool draw_table as it goes with a line on a screen of this size, or None where it is not offered."""
    found = room(width, height)
    if found is None:
        return None
    told = TOLD % (found["rows"] - 1, COLUMNS_MOST, across(found["width"], COLUMNS_MOST))
    return {"type": "function", "function": {"name": "draw_table", "description": told,
                                             "parameters": {"type": "object", "properties": {"table": {"type": "string", "description": EXAMPLE}},
                                                            "required": ["table"]}}}


# ---------- Reading a description ----------

def lower(word):
    """A word with its plain capitals made small, and nothing else changed."""
    return "".join(chr(ord(sign) + 32) if "A" <= sign <= "Z" else sign for sign in word)


def cells(rest):
    rest = rest.strip(" \t")
    if rest.startswith("|"):
        rest = rest[1:]
    if rest.endswith("|"):
        rest = rest[:-1]
    return [cell.strip(" \t") for cell in rest.split("|")]


def widths(rest):
    asked = []
    for given in re.split(r"[ \t,]", rest):
        if not given:
            continue
        if not all(sign in "0123456789" for sign in given):
            return None
        digits = given.lstrip("0")
        number = 999 if len(digits) > 3 else int(digits or "0")
        if number == 0:
            return None
        asked.append(number)
    return asked or None


def colour_read(given):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", given):
        return None
    return tuple(int(given[place:place + 2], 16) for place in (1, 3, 5))


def colours(rest, found):
    words = [word for word in re.split(r"[ \t,:=]", rest) if word]
    at = 0
    while at < len(words):
        part = PARTS.index(lower(words[at])) if lower(words[at]) in PARTS else None
        colour = colour_read(words[at + 1]) if at + 1 < len(words) else None
        if part is not None and colour is not None:
            found[part] = colour
            at += 2
        else:
            at += 1


def described(text):
    """The description read line by line, as the notes say: the first word says what a line is, in capitals or not,
    and a colon right behind it does not count; shape lines count only before the first row; any other line is
    skipped."""
    found = dict(title=None, colours=[None] * 5, widths=None, head=None, rows=[])
    for line in text.split("\n"):
        line = line.strip(" \t\r")
        ends = [place for place in (line.find(" "), line.find("\t")) if place >= 0]
        end = min(ends) if ends else len(line)
        word, rest = lower(line[:end]), line[end:].lstrip(" \t")
        word = word[:-1] if word.endswith(":") else word
        if word == "row":
            found["rows"].append(cells(rest))
        elif found["rows"]:
            continue
        elif word == "title":
            found["title"] = rest
        elif word == "head":
            found["head"] = cells(rest)
        elif word == "widths":
            found["widths"] = widths(rest)
        elif word in ("colours", "colors"):
            colours(rest, found["colours"])
    return found


def shown(text, room_signs):
    """A text from the model as shown: byte for byte, every byte that is not a plain sign a dot, cut to fit."""
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in text.encode("utf-8")[:room_signs])


def worked_out(asked, longest, signs):
    """The signs of each column, as the notes say: what each column wants (its longest cell, or the width asked if
    that is more, with a width asked for every column; at least 1) if all of that fits across; if not, what it wants
    up to an equal share, and the signs left shared in proportion to how many more each wants, rounded down."""
    columns = len(longest)
    asked = asked if asked is not None and len(asked) >= columns else None
    wanted = [max(longest[place], asked[place] if asked else 0, 1) for place in range(columns)]
    if sum(wanted) <= signs:
        return wanted
    share = signs // columns
    given = [min(want, share) for want in wanted]
    left = max(signs - sum(given), 0)
    more = sum(want - got for want, got in zip(wanted, given))
    return [got + left * (want - got) // max(more, 1) for want, got in zip(wanted, given)]


NO_ROOM = "Kernel: the model asked to draw a table, but this screen has no room for one."
CANNOT_READ_TABLE = "Kernel: the model asked to draw a table, but I could not read it."
NOTHING = "Kernel: the model asked to draw a table, but it has no head and no rows."
CUT_EARLY = "Kernel: the model asked to draw a table, but it was cut off before any of its rows came whole."


def counted(count, one, more):
    return "%d %s" % (count, one if count == 1 else more)


def drawn(text, whole=True, width=1280, height=800, key=""):
    """What the kernel makes of the text the model gave draw_table (as the JSON reader gives it, and whether its
    closing quote came): (the table as drawn and kept, or None when nothing is drawn; the row the kernel says;
    whether the table was drawn whole, so that the line ends)."""
    found_room = room(width, height)
    if found_room is None:
        return None, NO_ROOM, False
    text = hide(text, key) if key else text
    if not whole:
        end = text.rfind("\n")
        text = text[:end] if end >= 0 else ""
    found = described(text)
    if found["head"] is not None:
        columns = len(found["head"])
    else:
        columns = len(found["rows"][0]) if found["rows"] else 0
    if columns == 0:
        return None, NOTHING if whole else CUT_EARLY, False
    drawn_columns = min(columns, COLUMNS_MOST)
    fit = found_room["rows"] - (1 if found["head"] is not None else 0)
    drawn_rows = min(len(found["rows"]), fit)
    left_out = len(found["rows"]) - drawn_rows
    # The signs of each column's longest cell, the head's among them, in the rows drawn: a byte is a sign.
    longest = [0] * drawn_columns
    for row in ([found["head"]] if found["head"] is not None else []) + found["rows"][:drawn_rows]:
        for place, cell in enumerate(row[:drawn_columns]):
            longest[place] = max(longest[place], len(cell.encode("utf-8")))
    column_widths = worked_out(found["widths"], longest, across(found_room["width"], drawn_columns))

    def fitted(row):
        return [shown(row[place] if place < len(row) else "", w) for place, w in enumerate(column_widths)]

    title = shown(found["title"], found_room["width"] // SIGN) if found["title"] is not None else ""
    table = dict(title=title, colours=list(found["colours"]), widths=column_widths,
                 head=fitted(found["head"]) if found["head"] is not None else None, rows=[fitted(row) for row in found["rows"][:drawn_rows]])
    size = "%s and %s" % (counted(drawn_columns, "column", "columns"), "no rows" if drawn_rows == 0 else counted(drawn_rows, "row", "rows"))
    said = ("I drew the table \"%s\", with %s" % (title, size)) if title else "I drew a table with %s" % size
    if left_out:
        said += "; %d more %s not fit and %s left out" % (left_out, "row did" if left_out == 1 else "rows did", "was" if left_out == 1 else "were")
    if columns > drawn_columns:
        said += "; only the first %d of its %d columns fit" % (drawn_columns, columns)
    if not whole:
        said += "; it was cut off, so I drew only the rows that came whole"
    return table, "Kernel: " + said + ".", left_out == 0 and columns == drawn_columns and whole


# ---------- Letters that can be read ----------

def linear(value):
    """An amount of light (0 to 255) made linear, as WCAG 2 has it, in millionths, rounded to the nearest."""
    c = value / 255
    made = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return int(made * 1_000_000 + 0.5)


LINEAR = [linear(value) for value in range(256)]
FLARE = 500_000_000


def brightness(colour):
    return 2126 * LINEAR[colour[0]] + 7152 * LINEAR[colour[1]] + 722 * LINEAR[colour[2]]


def readable(letters, back):
    """The colour letters are painted in on `back`: as asked, if the two stand out from each other by a ratio of at
    least 4.5, worked out in whole numbers as the notes say; otherwise white if it stands out more than black."""
    one, other = brightness(letters), brightness(back)
    lighter, darker = max(one, other), min(one, other)
    if 2 * (lighter + FLARE) >= 9 * (darker + FLARE):
        return letters
    return WHITE if (brightness(WHITE) + FLARE) * FLARE > (other + FLARE) ** 2 else BLACK


# ---------- The picture ----------

def paint(picture, table, look="Blue"):
    """Paints the frame, the title and the table into a picture.Picture, in the look with this name."""
    found = room(picture.width, picture.height)
    colours = LOOKS[look]
    left, top, width, height = found["place"]
    picture.rectangle(left, top, width, height, colours["panel_frame"])
    picture.rectangle(left + FRAME, top + FRAME, width - 2 * FRAME, height - 2 * FRAME, colours["panel_inside"])
    picture.text(found["left"], found["title_top"], table["title"], SIZE, colours["panel_text"])

    def picked(part, otherwise):
        return table["colours"][part] or otherwise

    head_back = picked(0, colours["panel_frame"])
    head_letters = readable(picked(1, colours["panel_text"]), head_back)
    rows_back = picked(2, colours["panel_inside"])
    letters = readable(picked(3, colours["panel_text"]), rows_back)
    lines = picked(4, colours["panel_frame"])
    cell_widths = [CELL_LEFT + w * SIGN + CELL_RIGHT for w in table["widths"]]
    every = ([(table["head"], head_back, head_letters)] if table["head"] is not None else []) + [(row, rows_back, letters) for row in table["rows"]]
    picture.rectangle(found["left"], found["table_top"], LINE + sum(cell + LINE for cell in cell_widths), len(every) * ROW + LINE, lines)
    y = found["table_top"]
    for row, back, front in every:
        x = found["left"]
        for cell, cell_width in zip(row, cell_widths):
            picture.rectangle(x + LINE, y + LINE, cell_width, ROW - LINE, back)
            picture.text(x + LINE + CELL_LEFT, y + LINE + CELL_TOP, cell, SIZE, front)
            x += LINE + cell_width
        y += ROW
    # Nothing of it may lie over the chat box or the panel of apps.
    assert left >= APPS_LEFT + APPS_WIDTH and top + height <= picture.height - CHAT_MARGIN - CHAT_HEIGHT, "the frame overlaps"
