"""Documents (docs/screen.md "Documents", docs/tools.md `draw_table` and `open_document`, docs/notebook.md): tables the
model describes, kept on the disk as their lines, opened again and changed by a wish. Every scenario boots the stand-in
copy of the project (net_copy.py); the stand-in answers each line with the tool the scenario names (document_cases.py,
through chat_cases.py). What the kernel is meant to say, send and show comes from documents_model.py, table_model.py and
chat_tools_model.py, written from the notes; every request for a line is compared whole, every picture dot for dot, and
the disk file is read from outside. Made-up key only.

  keep      the thing this part is done by: a table of the planets is drawn and kept as document 1, and the panel of
            documents shows it open; "add a column with their moons" goes with its lines, and the model's whole new table
            is kept as its second version, in one ask; a table of fruit prices is document 2; after a restart nothing is
            open and the panel lists both; "open the planets" draws the second version and goes back; `setup` empties the
            frame, and the panel still lists both.
  cut       a change cut off at the limit of tokens is not drawn, and the document stays as it was on the screen and on
            the disk; a table without a document line is a new document; a change asked for a document that is not open
            opens it instead, and the change comes with the next ask; a new table cut off is drawn as far as it came and
            not kept, and nothing is open then; a table with the key in a cell is kept with stars, on the disk and in
            every request; `forget` leaves the open document open, and the next line goes with its lines and no record.
  odd       a table without a title, named by its number; a title with signs that are not plain and more than 45 signs;
            more rows than fit, all kept; a change and an open for documents that are not there, and an open that cannot
            be read; after a restart, a document whose lines are not whole is left out with a line of its own and keeps
            its number, and the rest are found, the one changed last first.
  broken    answers that break off on their way (the stand-in ends the connection in the middle of the table): a change
            of a kept document is not drawn, the document stays as it was, and the line ends; a new table draws its rows
            that came whole and is not kept.

Usage: python test_documents.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, documents_breaks.py), BOOS_PORT_BASE (46300 for this lane)."""
import json
import os

os.environ["DIVIDED_DISK"] = ""

import chat_cases
import document_cases as cases
from app_cases import hide
from apps_kept_model import block_of, read_things
from chat_tools_model import CUT_OFF, FORGOT, ToolsChat, body_again, body_meant, key_pieces, model_row
from documents_breaks import BREAKS
from documents_model import (CANNOT_READ_OPEN, closed_row, cut_change_row, documents_of, kept_line, kept_row, lines_kept, listed,
                             name_of, no_such_change_row, no_such_open_row, not_kept_row, note, opened_row, screen, start_lines)
from nb import put_block
from net_copy import build
from table_model import drawn
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import AGAIN, BROKE, back, check_body, exchange, holds, no_key_in, pieces_of, posts, rounds_since, text_unfinished

T = chat_cases.TOKENS_LINE
_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of documents_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=()):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel())


def new_chat(last_line=None):
    """The chat box at a start on an answered disk; after a restart, `last_line` is the line sent last before it, which
    the kernel says again."""
    return ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=last_line)


def document(number, version, table, number_line=None):
    """A document as these tests follow it: kept from the table `table` of document_cases.py, written with the line
    "document N" in front when `number_line` is given."""
    written = cases.text(table, number_line)
    return dict(number=number, version=version, name=name_of(written), lines=lines_kept(written))


def shown(documents):
    """The kept documents as open_document lists them, the one used last first."""
    return [(one["number"], listed(one)) for one in documents]


def documents_lines(lines):
    return [line for line in lines if line.startswith("Documents:")]


def start_documents_lines(lines):
    """The lines that begin with "Documents:" from the start, before the prompt."""
    hint = next((place for place, line in enumerate(lines) if line.startswith("The processor rested")), len(lines))
    return documents_lines(lines[:hint])


class Requests:
    """The requests for a line meant, in turn: each worked out once its line is sent, from the documents listed and
    the one open when it went."""

    def __init__(self, chat):
        self.chat, self.bodies = chat, []

    def line(self, line, documents, open_one=None):
        self.bodies.append(body_meant(line, [], record=self.chat.records[-1], key=KEY, documents=shown(documents), document=open_one))

    def again(self, line, place, documents, open_one=None):
        self.bodies.append(body_again(line, [], self.chat.agains[place], key=KEY, documents=shown(documents), document=open_one))

    def check(self, tag, run):
        seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
        report(tag + " requests for a line", len(seen) == len(self.bodies), "%d, meant %d" % (len(seen), len(self.bodies)))
        for number, (note_, body) in enumerate(zip(seen, self.bodies)):
            check_body("%s request %d" % (tag, number + 1), note_, body)


def check_things(tag, disk, documents, versions=()):
    """The disk read from outside: for each document its note, naming its newest version and its name, and the lines of
    that version; and for each (number, version, lines) in `versions`, those lines too."""
    found = read_things(disk)["things"]
    for one in documents:
        got = found.get("document %d" % one["number"], (0, None))[1]
        report("%s note of document %d" % (tag, one["number"]), got == note(one["version"], one["name"]), "got %r" % got)
        name = "document %d v%d" % (one["number"], one["version"])
        report("%s %s" % (tag, name), found.get(name, (0, None))[1] == one["lines"].encode())
    for number, version, lines in versions:
        name = "document %d v%d" % (number, version)
        report("%s %s" % (tag, name), found.get(name, (0, None))[1] == lines.encode())
    return found


# ---------- The scenarios ----------

def scenario_keep():
    print("keep: a table kept as a document, changed by a wish, a second one, a restart, an open, and setup")
    disk, _ = answered_disk("doc-keep")
    run = start("doc-keep", disk, ["doc=planets:0", "doc=moons:1", "doc=fruit:0"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # A new table, drawn whole: kept as document 1, which is open; the line ends there.
    line = "show me a table of the planets"
    planets = document(1, 1, "planets", 0)
    table, said, whole = drawn(cases.text("planets", 0))
    report("keep the planets are meant whole", whole, said)
    exchange(run, chat, line, [T, kept_row(said, 1), holds(table)])
    meant.line(line, [])
    run.shot("planets", screen(1280, 800, chat, [], [planets], 1))

    # A change by a wish: the line goes with the open document's lines; the model writes the whole table again,
    # beginning with "document 1", and it is kept as the document's second version, in one ask.
    line = "add a column with their moons"
    moons = document(1, 2, "moons", 1)
    table, said, _ = drawn(cases.text("moons", 1))
    exchange(run, chat, line, [T, kept_row(said, 1, changed=True), holds(table)])
    meant.line(line, [planets], planets)
    run.shot("moons", screen(1280, 800, chat, [], [moons], 1))

    # Another new table: document 2, at the top of the panel and open.
    line = "now a table of fruit prices"
    fruit = document(2, 1, "fruit", 0)
    table, said, _ = drawn(cases.text("fruit", 0))
    exchange(run, chat, line, [T, kept_row(said, 2), holds(table)])
    meant.line(line, [moons], moons)
    run.shot("fruit", screen(1280, 800, chat, [], [fruit, moons], 2))
    lines = run.end()
    kept = [kept_line(1, 1), kept_line(1, 2), kept_line(2, 1)]
    report("keep the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("keep", run)
    found = check_things("keep", disk, [moons, fruit], versions=[(1, 1, planets["lines"])])
    no_key_in("keep", lines)

    # After a restart nothing is open and the frame is empty; the panel lists both, the one changed last first. Opening
    # the planets draws their second version, and goes back to the model, which answers in words.
    again = start("doc-keep-2", disk, ["open=1"])
    chat = new_chat(b"now a table of fruit prices")
    give_key(again, chat)
    meant = Requests(chat)
    got = start_documents_lines(again.lines())
    report("keep restart the lines about documents", got == start_lines(documents_of(found)), "got %r" % got)
    again.shot("restart", screen(1280, 800, chat, [], [fruit, moons], None))
    line = "open the planets"
    table, _, _ = drawn(moons["lines"])
    exchange(again, chat, line, [T, opened_row(moons), holds(table)] + back())
    meant.line(line, [fruit, moons])
    meant.again(line, 0, [moons, fruit], moons)
    again.shot("opened", screen(1280, 800, chat, [], [moons, fruit], 1))

    # `setup`: the open document is closed and the frame empties; the documents stay listed.
    again.mark()
    again.press("setup\n", chat)
    asked = again.wait_line("Kernel: what should I call you?", timeout=30)
    report("keep setup asks for the name", asked is not None, None if asked else "the question never came")
    chat.table = None
    again.shot("setup", screen(1280, 800, chat, [], [moons, fruit], None))
    lines = again.end()
    meant.check("keep restart", again)
    no_key_in("keep restart", lines)


def scenario_cut():
    print("cut: a change cut off, a table without a document line, a change for a closed document, a new table cut off")
    disk, _ = answered_disk("doc-cut")
    behaviours = ["doc=planets:0", "doccut=moons:1", "docbare=fruit", "doc=moons:1", "again:doc=moons:1", "doccut=squares:0",
                  "words=Hello.", "dockey", "forget", "words=Hello again."]
    run = start("doc-cut", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    line = "the planets please"
    planets = document(1, 1, "planets", 0)
    table, said, _ = drawn(cases.text("planets", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds(table)])
    meant.line(line, [])

    # A change that the limit of tokens cut off: not drawn, and that goes back; the planets stay as they were.
    line = "add their moons"
    exchange(run, chat, line, [CUT_OFF, T, cut_change_row(1)] + back())
    meant.line(line, [planets], planets)
    meant.again(line, 0, [planets], planets)
    run.shot("cut-change", screen(1280, 800, chat, [], [planets], 1))

    # A table without a document line: a new document, open from then on.
    line = "fruit too"
    fruit = document(2, 1, "fruit")
    table, said, _ = drawn(cases.text("fruit"))
    exchange(run, chat, line, [T, kept_row(said, 2), holds(table)])
    meant.line(line, [planets], planets)

    # A change asked for document 1 while document 2 is open: document 1 is opened, not changed, and that goes back;
    # the next ask goes with its lines, and the change it brings is kept.
    line = "add moons to the planets"
    moons = document(1, 2, "moons", 1)
    opened, _, _ = drawn(planets["lines"])
    table, said, _ = drawn(cases.text("moons", 1))
    exchange(run, chat, line, [T, closed_row(1), holds(opened), AGAIN, T, kept_row(said, 1, changed=True), holds(table)])
    meant.line(line, [fruit, planets], fruit)
    meant.again(line, 1, [planets, fruit], planets)
    run.shot("closed", screen(1280, 800, chat, [], [moons, fruit], 1))

    # A new table cut off: drawn as far as it came, not kept, and nothing is open: the next line goes with no lines.
    line = "all twenty squares"
    table, said, _ = drawn(cases.cut("squares", 0)[1], whole=False)
    exchange(run, chat, line, [CUT_OFF, T, not_kept_row(said), holds(table)] + back())
    meant.line(line, [moons, fruit], moons)
    meant.again(line, 2, [moons, fruit])
    run.shot("cut-new", screen(1280, 800, chat, [], [moons, fruit], None))
    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [moons, fruit])

    # A table with the key in a cell: starred where it came in, so the document's lines hold stars, on the disk and in
    # every request they go with.
    line = "a table of my keys"
    written = hide(cases.key_table(KEY), KEY)
    keys = dict(number=3, version=1, name="Keys", lines=lines_kept(written))
    table, said, _ = drawn(cases.key_table(KEY), key=KEY)
    exchange(run, chat, line, [T, kept_row(said, 3), holds(table)])
    meant.line(line, [moons, fruit])

    # `forget` leaves the open document open: the next line goes with its lines, and with no record.
    line = "forget all that"
    exchange(run, chat, line, [T, FORGOT])
    meant.line(line, [keys, moons, fruit], keys)
    line = "hello again"
    exchange(run, chat, line, [model_row("Hello again."), T])
    meant.line(line, [keys, moons, fruit], keys)
    report("cut the line after forget goes with no record", chat.records[-1] == "", "got %r" % chat.records[-1])
    lines = run.end()
    kept = [kept_line(1, 1), kept_line(2, 1), kept_line(1, 2), kept_line(3, 1)]
    report("cut the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("cut", run)
    found = check_things("cut", disk, [moons, fruit, keys], versions=[(1, 1, planets["lines"])])
    names = sorted(name for name in found if name.startswith("document"))
    report("cut nothing more kept", names == ["document 1", "document 1 v1", "document 1 v2", "document 2", "document 2 v1", "document 3",
                                              "document 3 v1"], "got %r" % names)
    report("cut no piece of the key in the document's lines",
           not key_pieces(found.get("document 3 v1", (0, b""))[1].decode(errors="replace"), KEY))
    everything = "\n".join(json.dumps(note_.get("body")) for note_ in posts(run))
    report("cut no piece of the key in any request", not key_pieces(everything, KEY))
    no_key_in("cut", lines)


def scenario_odd():
    print("odd: no title, an odd title, more rows than fit, documents that are not there, and lines not whole at a start")
    disk, _ = answered_disk("doc-odd")
    behaviours = ["doc=untitled:0", "doc=odd:0", "doc=squares:0", "doc=moons:7", "open=9", "openbad"]
    run = start("doc-odd", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    kept = []

    def new(line, number, table_name, more=()):
        one = document(number, 1, table_name, 0)
        table, said, _ = drawn(cases.text(table_name, 0))
        exchange(run, chat, line, [T, kept_row(said, number), holds(table)] + list(more))
        meant.line(line, kept, kept[0] if kept else None)
        kept.insert(0, one)
        return one

    untitled = new("a table without a title", 1, "untitled")
    report("odd the untitled one is named by its number", untitled["name"] == "" and listed(untitled) == "document 1")
    odd = new("prices in euros", 2, "odd")
    report("odd the odd title is cleaned and cut", odd["name"] == "Prices in ... for the whole of the year two t", "got %r" % odd["name"])
    # More rows than fit: drawn with rows left out, which goes back; all of them are kept.
    squares = new("twenty squares", 3, "squares", back())
    meant.again("twenty squares", 0, kept, squares)
    run.shot("squares", screen(1280, 800, chat, [], kept, 3))

    # A change for a document that is not there, an open for one that is not there, and one that cannot be read: each
    # turned down, and each goes back.
    for place, (line, row) in enumerate([("change document seven", no_such_change_row(7)), ("open document nine", no_such_open_row(9)),
                                         ("open the planets", CANNOT_READ_OPEN)]):
        exchange(run, chat, line, [T, row] + back())
        meant.line(line, kept, squares)
        meant.again(line, place + 1, kept, squares)
    lines = run.end()
    meant.check("odd", run)
    no_key_in("odd", lines)

    # A note written from outside behind the notebook's end, for a document whose lines are not there: it is left out at
    # a start, with a line of its own, and keeps its number; the rest are found, the one changed last first.
    end = read_things(disk)["end"]
    put_block(disk, end, block_of(end, "document 4", note(1, "Ghost")))
    found = read_things(disk)["things"]
    again = start("doc-odd-2", disk, ["docbare=fruit"])
    chat = new_chat(b"open the planets")
    give_key(again, chat)
    meant = Requests(chat)
    got, wanted = start_documents_lines(again.lines()), start_lines(documents_of(found))
    report("odd restart the lines about documents", got == wanted, "got %r, meant %r" % (got, wanted))
    # The next new document takes the number after the highest, the one left out among them.
    line = "fruit please"
    table, said, _ = drawn(cases.text("fruit"))
    exchange(again, chat, line, [T, kept_row(said, 5), holds(table)])
    meant.line(line, kept)
    fruit = document(5, 1, "fruit")
    again.shot("restart", screen(1280, 800, chat, [], [fruit] + kept, 5))
    again.end()
    meant.check("odd restart", again)


def scenario_broken():
    print("broken: answers that break off on their way: a change of a kept document, and a new table")
    disk, _ = answered_disk("doc-broken")
    run = start("doc-broken", disk, ["doc=planets:0", "cut:doc=moons:1", "cut:doc=squares:0", "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    none = chat_cases.NO_TOKENS_LINE

    line = "the planets please"
    planets = document(1, 1, "planets", 0)
    table, said, _ = drawn(cases.text("planets", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds(table)])
    meant.line(line, [])

    # A change in an answer that broke off: not drawn, and the planets stay as they were; the line ends there.
    line = "add their moons"
    given = chat_cases.stream_sent(pieces_of("cut:doc=moons:1"))[1]
    report("broken the change's document line came", text_unfinished(given).startswith("document 1\n"), "got %r" % given[:40])
    exchange(run, chat, line, [BROKE, none, cut_change_row(1)])
    meant.line(line, [planets], planets)
    report("broken a broken change does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    run.shot("change", screen(1280, 800, chat, [], [planets], 1))

    # A new table in an answer that broke off: its rows that came whole are drawn, it is not kept, and nothing is
    # open then; the line ends there.
    line = "twenty squares"
    given = chat_cases.stream_sent(pieces_of("cut:doc=squares:0"))[1]
    table, said, whole = drawn(text_unfinished(given), whole=False)
    report("broken the squares are meant with some rows", not whole and "it was cut off" in said, said)
    exchange(run, chat, line, [BROKE, none, not_kept_row(said), holds(table)])
    meant.line(line, [planets], planets)
    run.shot("new", screen(1280, 800, chat, [], [planets], None))

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [planets])
    lines = run.end()
    meant.check("broken", run)
    found = check_things("broken", disk, [planets])
    names = sorted(name for name in found if name.startswith("document"))
    report("broken nothing more kept", names == ["document 1", "document 1 v1"], "got %r" % names)
    no_key_in("broken", lines)


SCENARIOS = {"keep": scenario_keep, "cut": scenario_cut, "odd": scenario_odd, "broken": scenario_broken}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
