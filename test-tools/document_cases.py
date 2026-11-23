"""The stand-in's answers about documents (docs/tools.md, `draw_table` and `open_document`), in the shape of chat_cases.py,
which hands it every behaviour it does not know itself; and the tables these answers describe. Nothing runs when this
file is imported.

Behaviours: "doc=planets:0" asks for draw_table with the table "planets" of TABLES behind the line "document 0" (any
number); "docbare=planets" with the table alone, without such a line; "doccut=moons:1" with the table behind "document 1",
cut off by the limit of tokens inside the line end behind CUT_LINES lines of it; "open=1" asks for open_document with the
document 1, and "openbad" with a document that cannot be read; "dockey" asks for draw_table with a new table that holds the
key the request came with in a cell."""
import json

from chat_cases import body, call, good, message

PLANETS = [("Mercury", "0.39", "0"), ("Venus", "0.72", "0"), ("Earth", "1.00", "1"), ("Mars", "1.52", "2"),
           ("Jupiter", "5.20", "95"), ("Saturn", "9.58", "146"), ("Uranus", "19.2", "28"), ("Neptune", "30.1", "16")]

TABLES = {
    # A small table with colours and widths.
    "planets": "\n".join(["title Planets", "colours head #1a237e head-letters #ffffff", "widths 8 13",
                          "head Planet | Distance (AU)"] + ["row %s | %s" % (name, distance) for name, distance, _ in PLANETS]),
    # The same table with a column more, as a change by a wish writes it again.
    "moons": "\n".join(["title Planets", "colours head #1a237e head-letters #ffffff", "widths 8 13 5",
                        "head Planet | Distance (AU) | Moons"] + ["row %s | %s | %s" % planet for planet in PLANETS]),
    # Another small table, in the look's colours.
    "fruit": "\n".join(["title Fruit prices", "head Fruit | Price"] + ["row %s | %s" % pair for pair in
                                                                       [("Apple", "0.40"), ("Banana", "0.25"), ("Cherry", "2.80")]]),
    # More rows than fit: all of them are kept, and the open document's lines hold them all.
    "squares": "\n".join(["title Squares", "head Number | Square"] + ["row %d | %d" % (n, n * n) for n in range(1, 21)]),
    # No title: the document is named by its number.
    "untitled": "\n".join(["head A | B", "row 1 | 2", "row 3 | 4"]),
    # A title with signs that are not plain and more than 45 signs, and a second title line before the first row,
    # which counts.
    "odd": "\n".join(["title Not this one", "title Prices in € for the whole of the year two thousand and twenty six",
                      "head Item | Price", "row Bread | 2"]),
}

# Where "doccut" cuts what the model gives the tool: in the line end behind this many lines of the text it gives (the
# line "document 1" among them), between its backslash and its n, as the limit of tokens may.
CUT_LINES = 7


def text(name, number=None):
    """What the model gives draw_table under `table`: the table `name`, behind the line "document N" if a number is
    given."""
    return ("document %d\n" % number if number is not None else "") + TABLES[name]


def cut(name, number):
    """What the model gives draw_table for `doccut`, and the text the kernel's reader takes out of it: the first
    CUT_LINES lines, the last without its line end."""
    whole = json.dumps({"table": text(name, number)})
    at = -1
    for _ in range(CUT_LINES):
        at = whole.index("\\n", at + 1)
    return whole[:at + 1], "\n".join(text(name, number).split("\n")[:CUT_LINES])


def key_table(bearer):
    """A new table with the key the request came with in a cell ("dockey")."""
    return "\n".join(["document 0", "title Keys", "head Name | Value", "row key | " + bearer, "row other | plain"])


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour about documents, or None if `kind` is none of these."""
    name, _, given = kind.partition("=")
    if name == "dockey":
        return good(body(message(None, [call("draw_table", {"table": key_table(bearer)})]), "tool_calls")), "goodbye"
    if name == "doc":
        table, number = given.split(":")
        return good(body(message(None, [call("draw_table", {"table": text(table, int(number))})]), "tool_calls")), "goodbye"
    if name == "docbare":
        return good(body(message(None, [call("draw_table", {"table": text(given)})]), "tool_calls")), "goodbye"
    if name == "doccut":
        table, number = given.split(":")
        return good(body(message(None, [call("draw_table", cut(table, int(number))[0])]), "length")), "goodbye"
    if name == "open":
        return good(body(message(None, [call("open_document", {"document": int(given)})]), "tool_calls")), "goodbye"
    if name == "openbad":
        return good(body(message(None, [call("open_document", {"document": "the planets"})]), "tool_calls")), "goodbye"
    return None
