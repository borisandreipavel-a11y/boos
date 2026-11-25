"""Bar charts in documents of text (docs/screen.md "Charts"), for test_chart_documents.py: the stand-in's answers that
write documents holding charts with write_document, in the shape of document_cases.py, reached through
text_document_cases.py; and those documents. Every document is made up. Nothing runs when this file is imported.

Behaviours: "chartdoc=guide:0" asks for write_document with the document "guide" of DOCUMENTS behind the line
"document 0" (any number); "chartdocbare=fruit" with the document alone; "chartdoccut=pluto:1:14" with the document
behind "document 1", cut off by the limit of tokens inside the line end behind 14 lines of it (the document line among
them); "chartdockey" with a new document whose chart has the key the request came with as a label."""
import json

from chat_cases import body, call, good, message

MOONS = [("Mercury", 0), ("Venus", 0), ("Earth", 1), ("Mars", 2), ("Jupiter", 95), ("Saturn", 146), ("Uranus", 28), ("Neptune", 16)]
MOON_BARS = ["bar %s | %d" % moon for moon in MOONS]
PLUTO_BAR = "bar Pluto | 5"
LARGEST = [("Earth", "Moon", "3,474"), ("Mars", "Phobos", "22"), ("Jupiter", "Ganymede", "5,268"), ("Saturn", "Titan", "5,150"),
           ("Uranus", "Titania", "1,578"), ("Neptune", "Triton", "2,707")]
TABLE = ["text The largest moon of each, two of them wider than the planet Mercury:", "head Planet | Largest moon | Across (km)"] + \
        ["row %s | %s | %s" % moon for moon in LARGEST]


def guide(with_pluto):
    return "\n".join(["title Moons of the planets",
                      "text The planets have moons of every size. Mercury and Venus have none; the giants have dozens each, "
                      "and new ones are still found.",
                      "chart Moons of each planet", "colours bars #2e7d32"] + MOON_BARS + ([PLUTO_BAR] if with_pluto else []) + TABLE)


# The lines a chart drawn alone with draw_chart was kept with (kind 3), before charts stood in documents: its first
# version, and its second with Pluto, as a person's run of that tool left them.
OLD_V1 = "\n".join(["title Moons of the planets", "colours bars #2e7d32"] + MOON_BARS)
OLD = OLD_V1 + "\n" + PLUTO_BAR

DOCUMENTS = {
    # The thing this part is done by: a paragraph, a chart in the model's green and a table; on two pages.
    "guide": guide(False),
    # The same guide written again with Pluto in its chart, as a change by a wish writes it.
    "pluto": guide(True),
    # The old chart written again as a document with a paragraph about the giants in front of it, as a change of it by a
    # wish may write it: the colour line, now behind the paragraph, waits for the chart its bars begin.
    "oldplus": "\n".join(["title Moons of the planets",
                          "text The giants hold almost all of the moons: Saturn and Jupiter alone have more than two hundred.",
                          "colours bars #2e7d32"] + MOON_BARS + [PLUTO_BAR]),
    # Four charts: numbers below zero, with decimals and commas, behind a capital word with a colon, in a yellow too faint
    # on light grey; every number below zero; every number zero; and numbers of 12 signs at both ends of the scale, where
    # only the right one is written. The second chart does not fit under the first, and begins on the next page.
    "numbers": "\n".join(["title Odd numbers",
                          "text Numbers below zero, with decimals and commas, all of them zero, and long ones at both ends.",
                          "chart Coldest days (C)", "Colours: bars #ffeb3b", "bar Oslo | -12.5", "bar Rome | 3", "bar Kiruna | -21",
                          "bar Lagos | 21", "bar Bern | 0", "bar Quito | 1,0.5",
                          "chart Frozen worlds (C)", "bar Mars | -63", "bar Pluto | -229", "bar Europa | -171.5",
                          "chart Flat", "bar A | 0", "bar B | -0", "bar C | 0.00",
                          "chart Wide", "bar Least label here | -999999999.9", "bar Most label here | 999999999.99"]),
    # More bars than a page holds under a title longer than the frame, labels longer than 12 signs and with signs that
    # are not plain, bars without a number; a colour after the chart's bars, which waits for the next chart; a bar after a
    # paragraph, which begins a chart without a title in that colour; and a chart with no bar that reads, left out.
    "many": "\n".join(["title Many bars",
                       "chart Many bars, and a title that runs on past the frame — so it is cut",
                       "bar No number | many"] + ["bar Bar number %d | %d" % (n, n * 7) for n in range(1, 9)]
                      + ["bar Zürich | 1,000", "bar 95 moons | 95 moons", "bar Plain"]
                      + ["bar Long label of many signs %d | 12345678.901" % n for n in range(1, 8)]
                      + ["colours bars #ff0000", "text Between the charts.", "bar Lone | 3", "bar Two | 4",
                         "chart Empty one", "bar Nothing | x"]),
    # Bars alone, without a title or a chart line: a document named by its number, holding one chart without a title; a
    # document line after the first bar is no block, and is kept with the lines.
    "fruit": "\n".join(["bar Apple | 0.40", "document 7", "bar Banana | 0.25", "bar Cherry | 2.80"]),
}


def text(name, number=None):
    """What the model gives write_document under `lines`: the document `name`, behind the line "document N" if a
    number is given."""
    return ("document %d\n" % number if number is not None else "") + DOCUMENTS[name]


def cut(name, number, lines):
    """What the model gives write_document for `chartdoccut`, and the text the kernel's reader takes out of it: the
    first `lines` lines, the last without its line end."""
    whole = json.dumps({"lines": text(name, number)})
    at = -1
    for _ in range(lines):
        at = whole.index("\\n", at + 1)
    return whole[:at + 1], "\n".join(text(name, number).split("\n")[:lines])


def key_document(bearer):
    """A new document whose chart has the key the request came with as a label ("chartdockey")."""
    return "\n".join(["document 0", "title Keys", "chart Keys", "bar " + bearer + " | 1", "bar other | 2"])


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour about charts in documents, or None if `kind` is none of
    these."""
    name, _, given = kind.partition("=")

    def asked(inputs, ending="tool_calls"):
        return good(body(message(None, [call("write_document", inputs)]), ending)), "goodbye"

    if name == "chartdoc":
        document, number = given.split(":")
        return asked({"lines": text(document, int(number))})
    if name == "chartdocbare":
        return asked({"lines": text(given)})
    if name == "chartdoccut":
        document, number, lines = given.split(":")
        return asked(cut(document, int(number), int(lines))[0], "length")
    if name == "chartdockey":
        return asked({"lines": key_document(bearer)})
    return None
