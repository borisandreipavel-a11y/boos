"""Documents, worked out from the notes apart from the kernel's code (docs/screen.md "Documents", docs/tools.md
`draw_table` and `open_document`, docs/notebook.md): the tool draw_table as it is offered where documents can be kept,
the tool open_document, what the model is told about the open document, the kernel's rows, the lines a document keeps,
the notebook's things for a document, what a start finds and says, and the panel of documents in the picture.
Nothing runs when this file is imported.

A document, as these tests follow it, is a dict: number, version, name (the title as kept, "" for none) and lines
(the newest version's lines as kept), and kind for a document of text and tables (KIND_TEXT, see
text_document_model.py); a table has none."""
import re
import struct

import table_model
from look_values import LOOKS
from picture import LETTER_HEIGHT, LETTER_WIDTH

NAME_MOST = 45
NOTE_FORM, KIND_TABLE, KIND_TEXT = 1, 1, 2

# ---------- The tools ----------

DOCUMENTS_TOLD = (" Every table is kept on the disk as a document, named by its title. "
                  "Begin a new table with the line document 0; to change a kept document, write its whole table again, "
                  "beginning with document and its number.")
EXAMPLE_LEAD = "The table, as lines, such as:\n"
assert table_model.EXAMPLE.startswith(EXAMPLE_LEAD)
EXAMPLE = EXAMPLE_LEAD + "document 0\n" + table_model.EXAMPLE[len(EXAMPLE_LEAD):]


def draw_table_tool(width=1280, height=800):
    """draw_table as it goes with a line where documents can be kept on a screen of this size, or None where the
    screen has no room for a table."""
    tool = table_model.tool_meant(width, height)
    if tool is None:
        return None
    function = tool["function"]
    function["description"] += DOCUMENTS_TOLD
    function["parameters"]["properties"]["table"]["description"] = EXAMPLE
    return tool


def open_document_tool(documents):
    """`documents`: (number, name as listed) of the kept documents, the one used last first."""
    told = ("Opens one of the kept documents in the frame on the screen, in place of what it shows; its lines then go with "
            "every line, so that it can be changed. The kept documents, by number: "
            + "; ".join("%d: %s" % (number, name) for number, name in documents) + ".")
    return {"type": "function", "function": {"name": "open_document", "description": told,
                                             "parameters": {"type": "object", "properties": {"document": {
                                                 "type": "integer", "enum": [number for number, _ in documents],
                                                 "description": "The number of the kept document"}},
                                                 "required": ["document"]}}}


def listed(document):
    """How a document is listed and shown: its name, or "document 3" without one."""
    return document["name"] or "document %d" % document["number"]


def called(document):
    """How the kernel calls a document in what it says."""
    if document["name"]:
        return 'document %d, "%s"' % (document["number"], document["name"])
    return "document %d" % document["number"]


def told(document):
    """What stands behind the instruction text while this document is open: for a document of text and tables (kind
    2, in the dict as "kind"), changed with write_document; for a table, with draw_table."""
    if document.get("kind") == KIND_TEXT:
        return ("\n\nThe document open on the screen is %s, a document of text and tables. To change it, write it whole again "
                "with write_document, beginning with the line document %d. Its lines now:\n%s" % (called(document), document["number"], document["lines"]))
    return ("\n\nThe document open on the screen is %s. To change it, write its whole table again with draw_table, "
            "beginning with the line document %d. Its lines now:\n%s" % (called(document), document["number"], document["lines"]))


# ---------- A description, as a document keeps it ----------

def first_word(line):
    line = line.strip(" \t\r")
    ends = [place for place in (line.find(" "), line.find("\t")) if place >= 0]
    word = table_model.lower(line[:min(ends)] if ends else line)
    return word[:-1] if word.endswith(":") else word


def lines_kept(text):
    """The lines a document keeps: every line as the model wrote it, but the `document` lines before the first row."""
    kept, rows_begun = [], False
    for line in text.split("\n"):
        word = first_word(line)
        rows_begun = rows_begun or word == "row"
        if not rows_begun and word == "document":
            continue
        kept.append(line)
    return "\n".join(kept)


def name_of(text):
    """A document's name: the title line as written (the later of two before the first row), every byte that is not a
    plain sign a dot, spaces at either end gone, at most 45 signs; "" without a title."""
    title = None
    for line in text.split("\n"):
        word = first_word(line)
        if word == "row":
            break
        if word == "title":
            stripped = line.strip(" \t\r")
            ends = [place for place in (stripped.find(" "), stripped.find("\t")) if place >= 0]
            title = stripped[min(ends):].lstrip(" \t") if ends else ""
    if title is None:
        return ""
    plain = "".join(chr(b) if 32 <= b <= 126 else "." for b in title.encode("utf-8"))
    return plain.strip()[:NAME_MOST].rstrip()


# ---------- What the kernel says ----------

def kept_row(said, number, changed=False):
    """The row about a table drawn and kept: table_model.drawn's row, and which document holds it."""
    return said + (" It is kept as document %d, in place of the one before." % number if changed else " It is kept as document %d." % number)


def not_kept_row(said):
    return said + " It is not kept."


def cut_change_row(number):
    return "Kernel: the new table for document %d was cut off, so I left the document as it was." % number


def closed_row(number):
    return ("Kernel: the model asked to change document %d, which was not open, so I did not change it; I opened it, "
            "and its lines go with the next ask." % number)


def no_such_change_row(number):
    return "Kernel: the model asked to change document %d, but no kept document has that number." % number


def opened_row(document, fit=""):
    return "Kernel: I opened %s%s." % (called(document), fit)


def no_such_open_row(number):
    return "Kernel: the model asked for document %d, but no kept document has that number." % number


CANNOT_READ_OPEN = "Kernel: the model asked to open a kept document, but I could not read which one."


def kept_line(number, version):
    """The terminal's line when a version is kept."""
    return "Documents: version %d of document %d is kept on the disk" % (version, number)


# ---------- The notebook ----------

def note(version, name, kind=KIND_TABLE):
    return bytes([NOTE_FORM, kind]) + struct.pack("<I", version) + name.encode()


def things(number, version, lines, name, kind=KIND_TABLE):
    """The things a version is kept as, in the order they are written: its lines, then the note."""
    return [("document %d v%d" % (number, version), lines), ("document %d" % number, note(version, name, kind))]


def documents_of(found):
    """The documents a start finds in a notebook's things ({name: (block, data)}): [(number, version, name, whole)],
    the one whose note was kept last first."""
    notes = []
    for thing, (block, data) in found.items():
        match = re.fullmatch(r"document ([1-9][0-9]{0,8})", thing)
        if not match or len(data) < 6 or data[0] != NOTE_FORM or data[1] not in (KIND_TABLE, KIND_TEXT):
            continue
        version = struct.unpack("<I", data[2:6])[0]
        if version == 0 or version > 999_999_999:
            continue
        name = "".join(chr(b) if 32 <= b <= 126 else "." for b in data[6:]).strip()[:NAME_MOST].rstrip()
        number = int(match.group(1))
        notes.append((block, number, version, name, "document %d v%d" % (number, version) in found))
    notes.sort(key=lambda found_note: -found_note[0])
    return [(number, version, name, whole) for _, number, version, name, whole in notes]


def start_lines(documents):
    """The lines that begin with "Documents:" at a start."""
    def call(number, name):
        return called(dict(number=number, name=name))
    listed_ones = [(number, name) for number, _, name, whole in documents if whole]
    lines = []
    if listed_ones:
        lines.append("Documents: %d %s kept on the disk:" % (len(listed_ones), "is" if len(listed_ones) == 1 else "are"))
        lines += ["Documents: %s" % call(number, name) for number, name in listed_ones]
    lines += ["Documents: %s: its lines are not whole, so it is left out" % call(number, name)
              for number, _, name, whole in documents if not whole]
    return lines


# ---------- The panel of documents ----------

PANEL = dict(left=40, width=600, frame=3, padding=10, size=2, gap=4, shown=5)
BOX_TOP, BOX_HEIGHT, BOX_GAP = 258, 60, 20


def panel_place(width, height):
    """(left, top, width, height) of the panel of documents, or None: 20 dots under the box with an app's text, as
    large as the panel of apps; none without room for the frame of a table, or nearer than 20 dots to the chat box."""
    if table_model.room(width, height) is None:
        return None
    p = PANEL
    row_height = p["size"] * LETTER_HEIGHT + p["gap"]
    panel_height = 2 * p["frame"] + 2 * p["padding"] + (p["shown"] + 1) * row_height
    assert panel_height == 158
    top = BOX_TOP + BOX_HEIGHT + BOX_GAP
    chat_top = height - table_model.CHAT_MARGIN - table_model.CHAT_HEIGHT
    if top + panel_height + BOX_GAP > chat_top:
        return None
    return p["left"], top, p["width"], panel_height


assert panel_place(1280, 800) == (40, 338, 600, 158) and panel_place(1024, 768) == (40, 338, 600, 158)
assert panel_place(1280, 720) is None and panel_place(800, 600) is None


def panel(picture, documents, open_number=None, look="Blue"):
    """Paints the panel of documents: nothing without documents; otherwise the frame, the inside, the row that says how
    many are kept, and the five used last, the open one marked "> " and the others "- ". `documents`: dicts, the one
    used last first."""
    place = panel_place(picture.width, picture.height)
    if not documents or place is None:
        return
    p = PANEL
    colours = LOOKS[look]
    left, top, width, height = place
    picture.rectangle(left, top, width, height, colours["panel_frame"])
    picture.rectangle(left + p["frame"], top + p["frame"], width - 2 * p["frame"], height - 2 * p["frame"], colours["panel_inside"])
    rows = ["Documents: %d kept" % len(documents)]
    rows += [("> " if document["number"] == open_number else "- ") + listed(document) for document in documents[:p["shown"]]]
    room = (width - 2 * p["frame"] - 2 * p["padding"]) // (p["size"] * (LETTER_WIDTH + 1))
    assert room == 47
    row_height = p["size"] * LETTER_HEIGHT + p["gap"]
    y = top + p["frame"] + p["padding"]
    for row in rows:
        picture.text(left + p["frame"] + p["padding"], y, row[:room], p["size"], colours["panel_text"])
        y += row_height


def screen(width, height, chat, requests, documents, open_number=None, page=0, panel_text="Hello from a Lua script!!!"):
    """The whole screen meant: apps_kept_model.screen's (the chat box, the box with an app's text, the table the chat
    model holds, the panel of apps), with the panel of documents."""
    import apps_kept_model
    picture = apps_kept_model.screen(width, height, chat, requests, page, panel_text)
    panel(picture, documents, open_number, getattr(chat, "look", "Blue"))
    return picture
