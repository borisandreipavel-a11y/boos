"""Documents of text and tables (docs/tools.md `write_document`), for test_text_documents.py: the stand-in's answers
about them, in the shape of document_cases.py, whose chain hands it every behaviour no other file knows (through
open_file_cases.py); and the documents these answers write. Every text is made up. Nothing runs when this file is
imported.

Behaviours: "write=guide:0" asks for write_document with the document "guide" of DOCUMENTS behind the line "document 0"
(any number); "writebare=fruit" with the document alone, without such a line; "writecut=moons:1" with the document
behind "document 1", cut off by the limit of tokens inside the line end behind CUT_LINES lines of it; "writelong" with a
new document longer than the bound on what the tool is given; "writekey" with a new document that holds the key the
request came with; "writebad" with inputs that hold no lines; "writeempty" with lines that hold nothing to write."""
import json

from chat_cases import body, call, good, message
from document_cases import PLANETS

# The bound on what write_document is given (docs/tools.md).
DOCUMENT_INPUTS_LONGEST = 8192

GUIDE = [
    "title Planets guide",
    "text The Sun has eight planets. The four nearest are small worlds of rock; the four farther out are giants of gas "
    "and ice, far larger and colder.",
    "text Mercury is the smallest planet and the nearest to the Sun. Its year lasts 88 days. Its days are hot enough to "
    "melt lead, and its nights are colder than any winter on Earth.",
    "text Venus is wrapped in thick clouds of acid and is the hottest planet. It turns backwards, so slowly that its day "
    "is longer than its year.",
    "text Earth is the only planet known to hold life, and the only one with seas of water on its face.",
    "text Mars is a cold desert, red with rust. Its air is thin, and it has the highest mountain of the planets, "
    "Olympus Mons, nearly three times as high as Everest.",
    "head Planet | Distance (AU) | Moons",
] + ["row %s | %s | %s" % planet for planet in PLANETS] + [
    "text Jupiter is the largest planet, more than twice as heavy as all the others together. Its Great Red Spot is a "
    "storm wider than Earth.",
    "text Saturn has the brightest rings, of ice and rock. Uranus rolls on its side, and Neptune has the fastest winds "
    "of the planets.",
]

MOONS = GUIDE + [
    "text Moons. Mercury and Venus have none, Earth has one, and Mars two small ones. The giants have many, and new ones "
    "are still found.",
    "head Planet | Largest moon | Wider than Mercury",
    "row Earth | Moon | no",
    "row Mars | Phobos | no",
    "row Jupiter | Ganymede | yes",
    "row Saturn | Titan | yes",
    "row Uranus | Titania | no",
    "row Neptune | Triton | no",
    "text Ganymede and Titan are wider than the planet Mercury, though lighter.",
]

DOCUMENTS = {
    # The thing this part is done by: a short guide to the planets, with paragraphs and a table, on more than one page.
    "guide": "\n".join(GUIDE),
    # The same guide written again with a section about moons, as a change by a wish writes it.
    "moons": "\n".join(MOONS),
    # Every rule of the notes in one document: a title with signs that are not plain and more than 45 signs; a word
    # longer than a row; an empty paragraph; runs of spaces and tabs; a capital word with a colon, and a return at a line's
    # end; a row after a paragraph, a table without a head, with a `|` at either end of its cells; a head of three cells
    # with rows of fewer and more; cells longer than their room; lines skipped after the first block (title, document,
    # colours, widths, a word that is no kind of line); and a table of twenty rows, which goes on to the next page under
    # its head.
    "odd": "\n".join([
        "title Notes on ünusual signs — and a title that goes on for long",
        "text A word longer than a row: " + "x" * 50 + " ends here.",
        "text",
        "text   spaces\tand\t\ttabs    between   words   ",
        "TEXT: A capital word with a colon, ending the Windows way.\r",
        "row | left | right |",
        "row 1 | 2",
        "colours head #ff0000",
        "head One | Two | Three",
        "row a",
        "row b | c | d | e",
        "title Not this one",
        "document 7",
        "widths 3 3 3",
        "note this line is skipped",
        "head Name | Description",
        "row Long | " + "a description far longer than its room in the frame",
        "text Twenty squares follow.",
        "head Number | Square",
    ] + ["row %d | %d" % (n, n * n) for n in range(1, 21)]),
    # Seven columns: six are drawn, and that goes back.
    "wide": "\n".join(["title Seven columns", "text A table wider than the frame takes.", "head a | b | c | d | e | f | g",
                       "row 1 | 2 | 3 | 4 | 5 | 6 | 7"]),
    # Many short paragraphs, eleven to a page: twelve pages, and a title cut to leave room for "page 12 of 12".
    "many": "\n".join(["title A document of many pages with a title that is long"] + ["text Note %d." % n for n in range(1, 126)]),
    # A small document without a title, named by its number.
    "fruit": "\n".join(["text Fruit and what it costs.", "head Fruit | Price", "row Apple | 0.40", "row Banana | 0.25"]),
    # A whole document between the table's bound and its own: some 7.5 KB as the tool is given it, kept in 17 pieces.
    "big": "\n".join(["title A long guide"] + ["text Paragraph %03d of a guide that is long, but whole and kept." % n for n in range(1, 116)]),
}

# Where "writecut" cuts what the model gives the tool: in the line end behind this many lines of the text it gives (the
# line "document 1" among them), between its backslash and its n, as the limit of tokens may.
CUT_LINES = 9


def text(name, number=None):
    """What the model gives write_document under `lines`: the document `name`, behind the line "document N" if a
    number is given."""
    return ("document %d\n" % number if number is not None else "") + DOCUMENTS[name]


def cut(name, number):
    """What the model gives write_document for `writecut`, and the text the kernel's reader takes out of it: the first
    CUT_LINES lines, the last without its line end."""
    whole = json.dumps({"lines": text(name, number)})
    at = -1
    for _ in range(CUT_LINES):
        at = whole.index("\\n", at + 1)
    return whole[:at + 1], "\n".join(text(name, number).split("\n")[:CUT_LINES])


# A new document longer than the bound: plain signs only, so that the JSON holds no backslash form but the line end's.
LONG = "\n".join(["document 0", "title A long one"] + ["text Line %03d of a document that goes on and on and on." % n for n in range(1, 201)])


def long_cut():
    """The text the kernel's reader takes out of what the model gives write_document for `writelong`: cut at the bound,
    as far as it goes."""
    whole = json.dumps({"lines": LONG})
    assert len(whole) > DOCUMENT_INPUTS_LONGEST and whole.startswith('{"lines": "') and "\\\\" not in whole
    taken = whole[:DOCUMENT_INPUTS_LONGEST][len('{"lines": "'):]
    if taken.endswith("\\"):
        taken = taken[:-1]
    return taken.replace("\\n", "\n")


# Lines with no paragraph, head or row in them ("writeempty").
EMPTY = "document 0\ntitle Nothing here\ncolours head #000000\nwidths 4"


def key_document(bearer):
    """A new document with the key the request came with in a paragraph and in a cell ("writekey")."""
    return "\n".join(["document 0", "title Keys", "text The key is " + bearer + " and nothing else.", "head Name | Value",
                      "row key | " + bearer, "row other | plain"])


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour about documents of text, or None if `kind` is none of these."""
    name, _, given = kind.partition("=")

    def asked(inputs, ending="tool_calls"):
        return good(body(message(None, [call("write_document", inputs)]), ending)), "goodbye"

    if name == "write":
        document, number = given.split(":")
        return asked({"lines": text(document, int(number))})
    if name == "writebare":
        return asked({"lines": text(given)})
    if name == "writecut":
        document, number = given.split(":")
        return asked(cut(document, int(number))[0], "length")
    if name == "writelong":
        return asked({"lines": LONG})
    if name == "writekey":
        return asked({"lines": key_document(bearer)})
    if name == "writebad":
        return asked({"text": "title Wrong\ntext The lines are under another name."})
    if name == "writeempty":
        return asked({"lines": EMPTY})
    return None
