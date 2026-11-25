"""A bar chart in a document of text, worked out from the notes apart from the kernel's code (docs/screen.md "Charts"
under "A document of text", and "A bar chart"): how a bar and its number are read, exactly; the bars' places and
lengths in whole numbers; the bars' colour in a look; and the picture of a chart's bars at its place on a page.
text_document_model.py reads the chart lines among a document's other lines and lays the chart out on a page. Nothing
runs when this file is imported, but the checks at its end, worked out by hand from the notes.

A bar, as read, is a dict: label and written (as the model wrote them), negative, digits (the number's digits as one
whole number) and decimals."""
import re

import table_model
from look_values import LOOKS

SIZE, SIGN, ROW, LINE = table_model.SIZE, table_model.SIGN, table_model.ROW, table_model.LINE
SIGNS_MOST = 12
DIGITS_MOST = 15
BAR_HEIGHT, BAR_TOP, LETTERS_TOP, GAP = 20, 4, 5, 12
FLARE = table_model.FLARE


# ---------- Reading ----------

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


def bar_of(rest):
    """A `bar` line behind its word: the label before the first |, the number after it, each without spaces and tabs
    at either end; None without a | or with a number that cannot be read."""
    label, bar, number_text = rest.partition("|")
    found = number_read(number_text.strip(" \t")) if bar else None
    if found is None:
        return None
    negative, digits, decimals = found
    return dict(label=label.strip(" \t"), written=number_text.strip(" \t"), negative=negative, digits=digits, decimals=decimals)


def bars_colour(rest):
    """The colour a colours line gives bars: the word bars and a colour behind it, parted by spaces, tabs, commas,
    colons or equals signs; other parts passed over; the later of two. None when it gives bars no colour."""
    words = [word for word in re.split(r"[ \t,:=]", rest) if word]
    found, at = None, 0
    while at < len(words):
        if table_model.lower(words[at]) == "bars" and at + 1 < len(words) and table_model.colour_read(words[at + 1]) is not None:
            found = table_model.colour_read(words[at + 1])
            at += 2
            continue
        at += 1
    return found


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


def laid(bars, left, width):
    """Where the bars stand across a room from `left`, `width` dots wide: bars_left, bars_right, the zero point, and
    for each bar (label as shown, its left, its length, the number's left, the number as written)."""
    right = left + width
    labels = max(len(plain(bar["label"])[:SIGNS_MOST]) for bar in bars)
    numbers = max(len(bar["written"]) for bar in bars)
    bars_left = left + labels * SIGN + GAP
    bars_right = right - numbers * SIGN - GAP
    room_width = bars_right - bars_left
    decimals, most_negative, largest, from_text, to_text = scale_of(bars)
    span = most_negative + largest
    zero = bars_left + dots(most_negative, room_width, span)
    rows = []
    for bar in bars:
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


# ---------- The picture ----------

def paint(picture, left, top, width, asked, bars, look="Blue"):
    """Paints a chart's bars from `top` down, across the room from `left`, `width` dots wide: each row's label, bar
    and number, the axis at the zero point over the bars, and the scale's ends in the row below, in the look with this
    name. The page under it is painted already."""
    colours = LOOKS[look]
    places = laid(bars, left, width)
    colour = bar_colour(asked, look)
    row_top = top
    for label, bar_left, length, number_left, number in places["rows"]:
        picture.text(left, row_top + LETTERS_TOP, label, SIZE, colours["panel_text"])
        picture.rectangle(bar_left, row_top + BAR_TOP, length, BAR_HEIGHT, colour)
        picture.text(number_left, row_top + LETTERS_TOP, number, SIZE, colours["panel_text"])
        row_top += ROW
    picture.rectangle(places["zero"], top, LINE, row_top - top, colours["panel_text"])
    to_left = places["bars_right"] - len(places["to_text"]) * SIGN
    if places["bars_left"] + (len(places["from_text"]) + 1) * SIGN <= to_left:
        picture.text(places["bars_left"], row_top + LETTERS_TOP, places["from_text"], SIZE, colours["panel_text"])
    picture.text(to_left, row_top + LETTERS_TOP, places["to_text"], SIZE, colours["panel_text"])


# ---------- Checks, worked out by hand from the notes ----------

# Numbers.
assert number_read("95") == (False, 95, 0) and number_read("-3.25") == (True, 325, 2) and number_read("+1,234.5") == (False, 12345, 1)
assert number_read("-0") == (False, 0, 0) and number_read("0.0") == (False, 0, 1)
for _bad in ["95 moons", "1e3", ".5", "5.", "1,,0", "1,0,", "", "+", "-", "1.2.3", "1,0.5,0", "1234567890123", "1 000"]:
    assert number_read(_bad) is None, _bad
assert number_read("123456789012") == (False, 123456789012, 0)  # 12 signs, 12 digits
assert bar_of("Mars | 2")["written"] == "2" and bar_of("Mars 2") is None and bar_of(" a b |  -1,5  ")["label"] == "a b"
assert bars_colour("rows #000000 bars #2e7d32") == (0x2E, 0x7D, 0x32) and bars_colour("head #000000") is None
assert bars_colour("bars=#000000, bars: #ff0000") == (255, 0, 0)


def _bars(*written):
    return [dict(label="b%d" % place, written=text, **dict(zip(("negative", "digits", "decimals"), number_read(text))))
            for place, text in enumerate(written)]


# The room on 1280 by 800 is 554 dots wide from column 673. With labels of 2 signs and numbers of 3: 554 - 24 - 12 - 12 -
# 36 = 470 dots for the bars.
_LEFT, _WIDTH = 673, 554
assert (table_model.room(1280, 800)["left"], table_model.room(1280, 800)["width"]) == (_LEFT, _WIDTH)
_PLACES = laid(_bars("100", "50", "25"), _LEFT, _WIDTH)
assert _PLACES["width"] == 470 and _PLACES["zero"] == _PLACES["bars_left"] == _LEFT + 36
assert [row[2] for row in _PLACES["rows"]] == [470, 235, 117]           # the largest bar the whole room; 25 × 470 / 100 = 117.5
# Mixed: -50 and 150 over 470 dots: the zero point 50 × 470 / 200 = 117 in; 150 is 352, -50 is 117 to the left.
_PLACES = laid(_bars("-50", "150", "0.5"), _LEFT, _WIDTH)
assert _PLACES["width"] == 470 and _PLACES["zero"] - _PLACES["bars_left"] == 117
assert [row[2] for row in _PLACES["rows"]] == [117, 352, 1]               # 0.5 at one decimal: 5 × 470 / 2000 = 1.175
assert _PLACES["rows"][0][1] == _PLACES["zero"] - 117 and (_PLACES["from_text"], _PLACES["to_text"]) == ("-50", "150")
# All below zero: the zero point at the right end; all zero: no lengths.
_PLACES = laid(_bars("-4", "-2"), _LEFT, _WIDTH)
assert _PLACES["zero"] == _PLACES["bars_right"] and [row[2] for row in _PLACES["rows"]] == [_PLACES["width"], _PLACES["width"] // 2]
assert (_PLACES["from_text"], _PLACES["to_text"]) == ("-4", "0")
_PLACES = laid(_bars("0", "0.00"), _LEFT, _WIDTH)
assert [row[2] for row in _PLACES["rows"]] == [0, 0] and (_PLACES["from_text"], _PLACES["to_text"]) == ("0", "0")
# Equal numbers written differently: the first written gives the scale's text.
assert laid(_bars("5.0", "5"), _LEFT, _WIDTH)["to_text"] == "5.0"

# Colours: Blue's frame (orange on light grey, 1.92) fails, so the letters' colour; Night's frame passes (3.71).
assert bar_colour(None, "Blue") == LOOKS["Blue"]["panel_text"] and bar_colour(None, "Night") == LOOKS["Night"]["panel_frame"]
assert bar_colour((46, 125, 50), "Blue") == (46, 125, 50)                # a dark green on light grey stands out
assert bar_colour((46, 125, 50), "Night") != (46, 125, 50)               # but not on Night's dark grey
assert bar_colour((255, 0, 0), "Blue") == (255, 0, 0)                    # red on light grey: 3.35
assert bar_colour((0xFF, 0xEB, 0x3B), "Blue") == LOOKS["Blue"]["panel_text"]  # yellow on light grey: far below 3
