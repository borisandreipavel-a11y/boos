"""A bar chart, which the model draws with the tool draw_chart, worked out from the notes apart from the kernel's code
(docs/screen.md "A bar chart" and "Documents", docs/tools.md `draw_chart`): the tool as it is offered, how the lines are
read, a number read exactly, the bars' places and lengths in whole numbers, the bars' colour, what the kernel says, the
lines and the name a chart keeps, and the picture of the frame in a look. Nothing runs when this file is imported, but
the checks at its end, worked out by hand from the notes.

A chart, as drawn and kept, is a dict: title (as drawn), colour (the colour asked for its bars, an (r, g, b), or None)
and bars (the bars drawn, each a dict: label and written as the model wrote them, negative, digits and decimals)."""
import table_model
from app_cases import hide
from look_values import LOOKS
from text_document_model import line_parts, number_of

SIZE, SIGN, ROW, LINE, FRAME = table_model.SIZE, table_model.SIGN, table_model.ROW, table_model.LINE, table_model.FRAME
SIGNS_MOST = 12
DIGITS_MOST = 15
BAR_HEIGHT, BAR_TOP, LETTERS_TOP, GAP = 20, 4, 5, 12
NAME_MOST = 45
FLARE = table_model.FLARE


def room(width, height):
    """The table's room inside the frame (table_model.room), or None, with how many bars fit: rows of 28 dots from
    below the title's row, above a last row of 28 dots for the scale."""
    found = table_model.room(width, height)
    if found is None:
        return None
    _, top, _, frame_height = found["place"]
    bottom = top + frame_height - FRAME - table_model.PADDING
    return dict(found, bottom=bottom, bars=(bottom - found["table_top"] - ROW) // ROW)


# ---------- The tool ----------

TOLD = ("Draws a bar chart in the frame on the screen, beside the panel of apps, in place of what it shows, "
        "and keeps it on the disk as a document, named by its title. Use it when the person wants numbers shown as a chart. "
        "The chart is written as lines, one thing to a line, each beginning with the word that says what it is: "
        "title and the chart's name; colours bars and a colour as # and six hex digits, picked to fit the wish; "
        "then bar and a bar's label and its number, parted by |, one line for each bar. "
        "A number is plain, with no unit: a sign, digits, commas and a point; put the unit in the title. "
        "Begin a new chart with the line document 0; to change a kept document, write it whole again, beginning with document and its number. "
        "This screen has room for %d bars, with labels of %d signs; bars that do not fit are left out.")
EXAMPLE = ("The chart, as lines, such as:\ndocument 0\ntitle Moons of the planets\ncolours bars #2e7d32\n"
           "bar Earth | 1\nbar Mars | 2\nbar Jupiter | 95")


def tool_meant(width=1280, height=800):
    """draw_chart as it goes with a line where documents can be kept on a screen of this size, or None where the
    screen has no room for the frame."""
    found = room(width, height)
    if found is None:
        return None
    return {"type": "function", "function": {"name": "draw_chart", "description": TOLD % (found["bars"], SIGNS_MOST),
                                             "parameters": {"type": "object", "properties": {"chart": {"type": "string", "description": EXAMPLE}},
                                                            "required": ["chart"]}}}


# ---------- Reading the lines ----------

def number_read(text):
    """A bar's number, read exactly: an optional + or -, digits that single commas may part, at most one point with
    digits behind it; at most 15 digits and 12 signs. (negative, digits as one whole number, decimals), or None. Minus
    zero is zero."""
    if not text or len(text) > SIGNS_MOST:
        return None
    at = 1 if text[0] in "+-" else 0
    negative = text[0] == "-"
    digits, count, decimals, point, after_digit = 0, 0, 0, False, False
    while at < len(text):
        sign = text[at]
        next_is_digit = at + 1 < len(text) and text[at + 1] in "0123456789"
        if sign in "0123456789":
            digits = digits * 10 + int(sign)
            count += 1
            decimals += 1 if point else 0
            after_digit = True
        elif sign == "," and not point and after_digit and next_is_digit:
            after_digit = False
        elif sign == "." and not point and after_digit and next_is_digit:
            point, after_digit = True, False
        else:
            return None
        at += 1
    if count == 0 or count > DIGITS_MOST:
        return None
    return negative and digits > 0, digits, decimals


def bars_colour(rest):
    """The colour a colours line gives the bars: the word bars and a colour behind it, parted by spaces, tabs, commas,
    colons or equals signs; other parts passed over; the later of two."""
    import re
    words = [word for word in re.split(r"[ \t,:=]", rest) if word]
    found, at = None, 0
    while at < len(words):
        if table_model.lower(words[at]) == "bars" and at + 1 < len(words) and table_model.colour_read(words[at + 1]) is not None:
            found = table_model.colour_read(words[at + 1])
            at += 2
            continue
        at += 1
    return found


def read(text):
    """The lines read as the notes say: (the document line's number or None, the title or None, the bars' colour or
    None, the bars whose number reads, how many do not). Everything but the bars counts only before the first bar line,
    the later of two."""
    number, title, colour, bars, unread, begun = None, None, None, [], 0, False
    for line in text.split("\n"):
        word, rest = line_parts(line)
        if word == "bar":
            begun = True
            label, bar, number_text = rest.partition("|")
            found = number_read(number_text.strip(" \t")) if bar else None
            if found is None:
                unread += 1
            else:
                negative, digits, decimals = found
                bars.append(dict(label=label.strip(" \t"), written=number_text.strip(" \t"), negative=negative, digits=digits, decimals=decimals))
        elif begun:
            continue
        elif word == "document":
            number = number_of(rest)
        elif word == "title":
            title = rest
        elif word in ("colours", "colors"):
            colour = bars_colour(rest) or colour
    return number, title, colour, bars, unread


# ---------- The scale and the bars ----------

def plain(text):
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in text.encode("utf-8"))


def scale_of(bars):
    """The bars' numbers at the most decimals any has, as whole numbers: (decimals, the most negative's size, the
    largest above zero, the scale's left text, its right text); the first written of two equal ones."""
    decimals = max(bar["decimals"] for bar in bars)
    most_negative, largest, left, right = 0, 0, "0", "0"
    for bar in bars:
        value = bar["digits"] * 10 ** (decimals - bar["decimals"])
        if bar["negative"] and value > most_negative:
            most_negative, left = value, bar["written"]
        elif not bar["negative"] and value > largest:
            largest, right = value, bar["written"]
    return decimals, most_negative, largest, left, right


def dots(size, width, span):
    """size × width / span, rounded down; nothing when every number is zero."""
    return 0 if span == 0 else size * width // span


def laid(chart, width=1280, height=800):
    """Where everything of the chart stands: bars_left, bars_right, the zero point, and for each bar (label, its left,
    its length, the number's left)."""
    found = room(width, height)
    left, right = found["left"], found["left"] + found["width"]
    labels = max(len(plain(bar["label"])[:SIGNS_MOST]) for bar in chart["bars"])
    numbers = max(len(bar["written"]) for bar in chart["bars"])
    bars_left = left + labels * SIGN + GAP
    bars_right = right - numbers * SIGN - GAP
    room_width = bars_right - bars_left
    decimals, most_negative, largest, from_text, to_text = scale_of(chart["bars"])
    span = most_negative + largest
    zero = bars_left + dots(most_negative, room_width, span)
    rows = []
    for bar in chart["bars"]:
        length = dots(bar["digits"] * 10 ** (decimals - bar["decimals"]), room_width, span)
        rows.append((plain(bar["label"])[:SIGNS_MOST], zero - length if bar["negative"] else zero, length,
                     right - len(bar["written"]) * SIGN, bar["written"]))
    return dict(bars_left=bars_left, bars_right=bars_right, width=room_width, zero=zero, rows=rows, from_text=from_text, to_text=to_text)


def stands_out(colour, inside):
    """Whether a colour stands out from the inside by a contrast ratio of at least 3, in whole numbers."""
    one, other = table_model.brightness(colour), table_model.brightness(inside)
    lighter, darker = max(one, other), min(one, other)
    return lighter + FLARE >= 3 * (darker + FLARE)


def bar_colour(asked, look):
    """The bars' colour in a look: the one asked for when it stands out from the look's inside by 3, else the look's
    frame colour when that does, else the look's letters' colour."""
    colours = LOOKS[look]
    if asked is not None and stands_out(asked, colours["panel_inside"]):
        return asked
    if stands_out(colours["panel_frame"], colours["panel_inside"]):
        return colours["panel_frame"]
    return colours["panel_text"]


# ---------- What the kernel says ----------

NOT_HERE = "Kernel: the model asked to draw a chart, but documents cannot be kept on this machine."
CANNOT_READ = "Kernel: the model asked to draw a chart, but I could not read it."
NOTHING = "Kernel: the model asked to draw a chart, but it has no bar with a number I could read."
CUT_EARLY = "Kernel: the model asked to draw a chart, but it was cut off before any of its bars came whole."


def cut_change_row(number):
    return "Kernel: the new chart for document %d was cut off, so I left the document as it was." % number


def counted(count, one, more):
    return "%d %s" % (count, one if count == 1 else more)


def left_out_said(left_out, unread):
    said = ""
    if left_out:
        said += "; %d more %s not fit and %s left out" % (left_out, "bar did" if left_out == 1 else "bars did", "was" if left_out == 1 else "were")
    if unread:
        said += "; %d %s no number I could read and %s left out" % (unread, "bar had" if unread == 1 else "bars had", "was" if unread == 1 else "were")
    return said


def drawn(text, whole=True, width=1280, height=800, key=""):
    """What the kernel makes of the text the model gave draw_chart (as the JSON reader gives it, and whether its
    closing quote came): (the chart as drawn and kept, or None; the row the kernel says, without what it says about
    keeping it; whether it was drawn whole, so that the line ends)."""
    found_room = room(width, height)
    text = hide(text, key) if key else text
    if not whole:
        end = text.rfind("\n")
        text = text[:end] if end >= 0 else ""
    _, title, colour, bars, unread = read(text)
    if not bars:
        return None, NOTHING if whole else CUT_EARLY, False
    left_out = max(len(bars) - found_room["bars"], 0)
    bars = bars[:found_room["bars"]]
    shown = plain(title)[:found_room["width"] // SIGN] if title is not None else ""
    _, _, _, from_text, to_text = scale_of(bars)
    many = counted(len(bars), "bar", "bars")
    said = ('I drew the chart "%s", with %s from %s to %s' % (shown, many, from_text, to_text) if shown
            else "I drew a chart with %s from %s to %s" % (many, from_text, to_text))
    said += left_out_said(left_out, unread)
    if not whole:
        said += "; it was cut off, so I drew only the bars that came whole"
    chart = dict(title=shown, colour=colour, bars=bars, left_out=left_out, unread=unread)
    return chart, "Kernel: " + said + ".", whole and left_out == 0 and unread == 0


def opened_fit(chart):
    """What stands behind "I opened document 3, ..." for a chart: its bars, and what was left out."""
    return ", with %s%s" % (counted(len(chart["bars"]), "bar", "bars"), left_out_said(chart["left_out"], chart["unread"]))


# ---------- What a chart keeps ----------

def lines_kept(text):
    """The lines a chart keeps: every line as the model wrote it, but the document lines before the first bar line."""
    kept, begun = [], False
    for line in text.split("\n"):
        word, _ = line_parts(line)
        begun = begun or word == "bar"
        if not begun and word == "document":
            continue
        kept.append(line)
    return "\n".join(kept)


def name_of(text):
    """A chart's name: its title, cleaned, spaces at either end gone, at most 45 signs; "" without a title."""
    title = read(text)[1]
    return plain(title).strip(" ")[:NAME_MOST].rstrip(" ") if title is not None else ""


# ---------- The picture ----------

def paint(picture, chart, look="Blue"):
    """Paints the frame, the title and the chart into a picture.Picture, in the look with this name."""
    found = room(picture.width, picture.height)
    colours = LOOKS[look]
    left, top, width, height = found["place"]
    picture.rectangle(left, top, width, height, colours["panel_frame"])
    picture.rectangle(left + FRAME, top + FRAME, width - 2 * FRAME, height - 2 * FRAME, colours["panel_inside"])
    picture.text(found["left"], found["title_top"], chart["title"], SIZE, colours["panel_text"])
    places = laid(chart, picture.width, picture.height)
    colour = bar_colour(chart["colour"], look)
    row_top = found["table_top"]
    for label, bar_left, length, number_left, number in places["rows"]:
        picture.text(found["left"], row_top + LETTERS_TOP, label, SIZE, colours["panel_text"])
        picture.rectangle(bar_left, row_top + BAR_TOP, length, BAR_HEIGHT, colour)
        picture.text(number_left, row_top + LETTERS_TOP, number, SIZE, colours["panel_text"])
        row_top += ROW
    picture.rectangle(places["zero"], found["table_top"], LINE, row_top - found["table_top"], colours["panel_text"])
    to_left = places["bars_right"] - len(places["to_text"]) * SIGN
    if places["bars_left"] + (len(places["from_text"]) + 1) * SIGN <= to_left:
        picture.text(places["bars_left"], row_top + LETTERS_TOP, places["from_text"], SIZE, colours["panel_text"])
    picture.text(to_left, row_top + LETTERS_TOP, places["to_text"], SIZE, colours["panel_text"])


# ---------- Checks, worked out by hand from the notes ----------

# QEMU's usual screen: 426 dots below the title's row; 14 rows of 28 for bars above a last row of 28 for the scale.
assert room(1280, 800)["bars"] == 14 and room(800, 600) is None

# Numbers.
assert number_read("95") == (False, 95, 0) and number_read("-3.25") == (True, 325, 2) and number_read("+1,234.5") == (False, 12345, 1)
assert number_read("-0") == (False, 0, 0) and number_read("0.0") == (False, 0, 1)
for bad in ["95 moons", "1e3", ".5", "5.", "1,,0", "1,0,", "", "+", "-", "1.2.3", "1,0.5,0", "1234567890123", "1 000"]:
    assert number_read(bad) is None, bad
assert number_read("123456789012") == (False, 123456789012, 0)  # 12 signs, 12 digits

# Lines: everything but the bars before the first bar line, read or not; the later of two; a line without | reads no
# number.
_LINES = "\n".join(["document 2", "title First", "Title: Second", "colours rows #000000 bars #2e7d32", "colors bars #ff0000",
                    "bar No number | many", "title Late", "colours bars #000000", "bar Mars | 2", "bar Earth", "row x | 1", "bar Venus | 0"])
assert read(_LINES)[:3] == (2, "Second", (255, 0, 0)) and len(read(_LINES)[3]) == 2 and read(_LINES)[4] == 2
assert lines_kept(_LINES) == "\n".join(_LINES.split("\n")[1:]) and name_of(_LINES) == "Second"


def _bars(*written):
    return [dict(label="b%d" % place, written=text, **dict(zip(("negative", "digits", "decimals"), number_read(text))))
            for place, text in enumerate(written)]


# The bars' room on 1280 by 800 with labels of 2 signs and numbers of 3: 554 - 24 - 12 - 12 - 36 = 470 dots.
_CHART = dict(title="", colour=None, bars=_bars("100", "50", "25"))
_PLACES = laid(_CHART)
assert _PLACES["width"] == 470 and _PLACES["zero"] == _PLACES["bars_left"]
assert [row[2] for row in _PLACES["rows"]] == [470, 235, 117]           # the largest bar the whole room; 25 × 470 / 100 = 117.5
# Mixed: -50 and 150 over 470 dots: the zero point 50 × 470 / 200 = 117 in; 150 is 352, -50 is 117 to the left.
_PLACES = laid(dict(title="", colour=None, bars=_bars("-50", "150", "0.5")))
assert _PLACES["width"] == 470 and _PLACES["zero"] - _PLACES["bars_left"] == 117
assert [row[2] for row in _PLACES["rows"]] == [117, 352, 1]               # 0.5 at one decimal: 5 × 470 / 2000 = 1.175
assert _PLACES["rows"][0][1] == _PLACES["zero"] - 117 and (_PLACES["from_text"], _PLACES["to_text"]) == ("-50", "150")
# All below zero: the zero point at the right end; all zero: no lengths.
_PLACES = laid(dict(title="", colour=None, bars=_bars("-4", "-2")))
assert _PLACES["zero"] == _PLACES["bars_right"] and [row[2] for row in _PLACES["rows"]] == [_PLACES["width"], _PLACES["width"] // 2]
assert (_PLACES["from_text"], _PLACES["to_text"]) == ("-4", "0")
_PLACES = laid(dict(title="", colour=None, bars=_bars("0", "0.00")))
assert [row[2] for row in _PLACES["rows"]] == [0, 0] and (_PLACES["from_text"], _PLACES["to_text"]) == ("0", "0")
# Equal numbers written differently: the first written gives the scale's text.
assert laid(dict(title="", colour=None, bars=_bars("5.0", "5")))["to_text"] == "5.0"

# Colours: Blue's frame (orange on light grey, 1.92) fails, so the letters' colour; Night's frame passes (3.71).
assert bar_colour(None, "Blue") == LOOKS["Blue"]["panel_text"] and bar_colour(None, "Night") == LOOKS["Night"]["panel_frame"]
assert bar_colour((46, 125, 50), "Blue") == (46, 125, 50)                # a dark green on light grey stands out
assert bar_colour((46, 125, 50), "Night") != (46, 125, 50)               # but not on Night's dark grey

# Saying: 16 bars with numbers and one without: 14 drawn, 2 left out, 1 without a number.
_SIXTEEN = "\n".join(["title Many"] + ["bar n%d | %d" % (n, n) for n in range(1, 17)] + ["bar bad | x"])
assert drawn(_SIXTEEN)[1] == ('Kernel: I drew the chart "Many", with 14 bars from 0 to 14; 2 more bars did not fit and were left out; '
                              "1 bar had no number I could read and was left out.")
assert drawn("title Nothing\nbar a | x")[1] == NOTHING and drawn("title x\nbar a | 1", whole=False)[1] == CUT_EARLY
