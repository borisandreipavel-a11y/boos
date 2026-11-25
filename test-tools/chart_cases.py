"""Bar charts (docs/tools.md `draw_chart`), for test_chart_documents.py: the stand-in's answers about them, in the shape
of document_cases.py, reached through text_document_cases.py; and the charts these answers draw. Every chart is made up.
Nothing runs when this file is imported.

Behaviours: "chart=moons:0" asks for draw_chart with the chart "moons" of CHARTS behind the line "document 0" (any
number); "chartbare=fruit" with the chart alone; "chartcut=pluto:1" with the chart behind "document 1", cut off by the
limit of tokens inside the line end behind CUT_LINES lines of it; "chartlong" with a new chart longer than the bound on
what the tool is given; "chartkey" with a new chart that holds the key the request came with in a label; "chartbad" with
inputs that hold no chart."""
import json

from chat_cases import body, call, good, message

# The bound on what draw_chart is given, a table's (docs/tools.md).
CHART_INPUTS_LONGEST = 4096

MOONS = [("Mercury", 0), ("Venus", 0), ("Earth", 1), ("Mars", 2), ("Jupiter", 95), ("Saturn", 146), ("Uranus", 28), ("Neptune", 16)]
MOONS_LINES = ["title Moons of the planets", "colours bars #2e7d32"] + ["bar %s | %d" % moon for moon in MOONS]

CHARTS = {
    # The thing this part is done by: eight bars, in a colour of the model's.
    "moons": "\n".join(MOONS_LINES),
    # The same chart written again with a bar more, as a change by a wish writes it.
    "pluto": "\n".join(MOONS_LINES + ["bar Pluto | 5"]),
    # Numbers below zero, with decimals and commas, in a colour too faint on light grey (yellow), and a capital word
    # with a colon.
    "temperatures": "\n".join(["title Coldest days", "Colours: bars #ffeb3b", "bar Oslo | -12.5", "bar Rome | 3",
                               "bar Kiruna | -21", "bar Lagos | 21", "bar Bern | 0", "bar Quito | 1,0.5"]),
    # Every number below zero: the zero point at the right end.
    "frozen": "\n".join(["title Frozen", "bar Mars | -63", "bar Pluto | -229", "bar Europa | -171.5"]),
    # Every number zero: no bar has a length.
    "flat": "\n".join(["title Flat", "bar A | 0", "bar B | -0", "bar C | 0.00"]),
    # More bars than fit, and lines that are no bar or no number: 16 bars with numbers, 3 without; lines after the
    # first bar that are skipped (a title, a colour, a row); a title longer than the frame's room and labels longer than
    # 12 signs, with signs that are not plain; a number of 12 signs.
    "many": "\n".join(["title Many bars — more than fit in the frame, so some are left out", "bar No number | many"] + ["bar Bar number %d | %d" % (n, n * 7) for n in range(1, 9)]
                      + ["title Late", "colours bars #ff0000", "row x | 1", "bar Zürich | 1,000", "bar 95 moons | 95 moons", "bar Plain"]
                      + ["bar Long label of many signs %d | 12345678.901" % n for n in range(1, 8)]),
    # Long numbers at both ends of the scale: the two texts would meet, so only the right one is written.
    "wide": "\n".join(["title Wide", "bar Least label here | -999999999.9", "bar Most label here | 999999999.99"]),
    # Bars, but none with a number that reads.
    "none": "\n".join(["title Nothing to draw", "bar Apples | many", "bar Pears"]),
    # A small chart without a title, named by its number.
    "fruit": "\n".join(["bar Apple | 0.40", "bar Banana | 0.25", "bar Cherry | 2.80"]),
}

# Where "chartcut" cuts what the model gives the tool: in the line end behind this many lines of the text it gives
# (the line "document 1" among them), between its backslash and its n, as the limit of tokens may.
CUT_LINES = 6


def text(name, number=None):
    """What the model gives draw_chart under `chart`: the chart `name`, behind the line "document N" if a number is
    given."""
    return ("document %d\n" % number if number is not None else "") + CHARTS[name]


def cut(name, number):
    """What the model gives draw_chart for `chartcut`, and the text the kernel's reader takes out of it: the first
    CUT_LINES lines, the last without its line end."""
    whole = json.dumps({"chart": text(name, number)})
    at = -1
    for _ in range(CUT_LINES):
        at = whole.index("\\n", at + 1)
    return whole[:at + 1], "\n".join(text(name, number).split("\n")[:CUT_LINES])


# A new chart longer than the bound: plain signs only, so that the JSON holds no backslash form but the line end's.
LONG = "\n".join(["document 0", "title A long chart"] + ["bar Bar with a long label %03d | %d" % (n, n) for n in range(1, 151)])


def long_cut():
    """The text the kernel's reader takes out of what the model gives draw_chart for `chartlong`: cut at the bound, as
    far as it goes."""
    whole = json.dumps({"chart": LONG})
    assert len(whole) > CHART_INPUTS_LONGEST and whole.startswith('{"chart": "') and "\\\\" not in whole
    taken = whole[:CHART_INPUTS_LONGEST][len('{"chart": "'):]
    if taken.endswith("\\"):
        taken = taken[:-1]
    return taken.replace("\\n", "\n")


def key_chart(bearer):
    """A new chart with the key the request came with in a label ("chartkey")."""
    return "\n".join(["document 0", "title Keys", "bar " + bearer + " | 1", "bar other | 2"])


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour about charts, or None if `kind` is none of these."""
    name, _, given = kind.partition("=")

    def asked(inputs, ending="tool_calls"):
        return good(body(message(None, [call("draw_chart", inputs)]), ending)), "goodbye"

    if name == "chart":
        chart, number = given.split(":")
        return asked({"chart": text(chart, int(number))})
    if name == "chartbare":
        return asked({"chart": text(given)})
    if name == "chartcut":
        chart, number = given.split(":")
        return asked(cut(chart, int(number))[0], "length")
    if name == "chartlong":
        return asked({"chart": LONG})
    if name == "chartkey":
        return asked({"chart": key_chart(bearer)})
    if name == "chartbad":
        return asked({"table": "title Wrong\nbar The chart is under another name | 1"})
    return None
