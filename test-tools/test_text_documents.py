"""Documents of text and tables (docs/screen.md "A document of text" and "Documents", docs/tools.md `write_document`):
documents the model writes, laid out in pages and shown one page at a time, turned with Page Down and Page Up, kept on
the disk as their lines, opened again and changed by a wish. Every scenario boots the stand-in copy of the project
(net_copy.py); the stand-in answers each line with the tool the scenario names (text_document_cases.py, through
chat_cases.py). What the kernel is meant to say, send and show comes from text_document_model.py, documents_model.py and
chat_tools_model.py, written from the notes; every request for a line is compared whole, every picture dot for dot,
and the disk file is read from outside. Made-up key only.

  write     the thing this part is done by: "write me a short guide to the planets as a document" writes a guide of
            three pages, kept as document 1, a document of text; Page Down shows page 2 at once, with no ask and nothing
            said; with half a line typed, Page Down and Page Up turn the pages (at the last page nothing changes), and
            the line then goes out whole; "add a section about moons" goes with the guide's lines and is kept as its
            second version, shown from its first page; a table of fruit prices takes the frame, and Page Down then
            changes nothing; after a restart the panel lists both, Page Down changes nothing in an empty frame, and
            "open the planets guide" shows its first page and goes back; Page Down in the middle of a key typed after
            `key` turns the page and leaves the key whole; F1 and a key bring back the page shown; `setup` empties the
            frame.
  cut       a change cut off at the limit of tokens, not drawn, the document as it was; a new document longer than the
            bound on what the tool is given, drawn as far as its lines came whole and not kept; one with the key in it,
            kept with stars; one of seven columns, six drawn, which goes back; inputs without lines, and lines with
            nothing to write, turned down; a document without a document line, kept as a new one; a change asked for a
            document that is not open, which opens it, and the change that comes with the next ask; a whole document of
            7.5 KB, between the table's bound and its own, kept, and its lines sent with the next line.
  odd       a document with every rule of the notes in it, page by page; one of twelve pages, whose title leaves room
            for "page 12 of 12", where Page Up at the first page and Page Down at the last change nothing; another look,
            which paints the page shown again; a table changed into a document of text by write_document, and back into
            a table by draw_table, whose lines then go with the next line as a table's.
  broken    answers that break off on their way: a change of a kept document is not drawn and the document stays as it
            was; a new document draws its lines that came whole and is not kept; the line ends there.
  nodocs    a disk without a notebook: documents cannot be kept, so write_document is not offered, and asked for anyway
            it is turned down.

Usage: python test_text_documents.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, text_document_breaks.py), BOOS_PORT_BASE, BOOS_PROVIDER ("anthropic": every
line goes to Anthropic, in Anthropic's form; the rows, pictures and requests meant are the same)."""
import json
import os

os.environ["DIVIDED_DISK"] = ""

import chat_cases
import document_cases
import documents_model
import text_document_cases as cases
import text_document_model as model
from app_cases import hide
from apps_kept_model import read_things
from chat_tools_model import CUT_OFF, ToolsChat, body_again, body_meant, key_pieces, model_row
from disk_helpers import make
from documents_model import KIND_TEXT, closed_row, documents_of, kept_line, kept_row, not_kept_row, note, opened_row, start_lines
from net_copy import build
from table_model import drawn
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import AGAIN, BROKE, back, check_body, exchange, no_key_in, pieces_of, posts, rounds_since
from test_documents import Requests, documents_lines, new_chat, start_documents_lines
from text_document_breaks import BREAKS

T = chat_cases.TOKENS_LINE
NIGHT = "Kernel: this is look 2, Night. It is kept on the disk."
_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of text_document_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=()):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel())


def document(number, version, name, number_line=None):
    """A document of text as these tests follow it: kept from the document `name` of text_document_cases.py, written
    with the line "document N" in front when `number_line` is given."""
    written = cases.text(name, number_line)
    return dict(number=number, version=version, name=model.name_of(written), lines=model.lines_kept(written), kind=KIND_TEXT)


def table_document(number, version, name):
    """A table of document_cases.py kept as a document, written behind the line "document 0"."""
    written = document_cases.text(name, 0)
    return dict(number=number, version=version, name=documents_model.name_of(written), lines=documents_model.lines_kept(written))


def holds_text(laid):
    """A step for `exchange`: from then on the frame shows this document of text (text_document_model.py)."""
    def step(chat):
        chat.text, chat.table = laid, None
    return step


def holds_table(table):
    """A step for `exchange`: from then on the frame shows this table (table_model.py)."""
    def step(chat):
        chat.table, chat.text = table, None
    return step


def meant_screen(chat, documents, open_number):
    """The whole screen meant: documents_model.screen's, with the page shown of the document of text the chat model
    holds painted over the frame (nothing else lies there)."""
    picture = documents_model.screen(1280, 800, chat, [], documents, open_number)
    if getattr(chat, "text", None) is not None:
        model.paint(picture, chat.text, getattr(chat, "look", "Blue"))
    return picture


def turn(run, chat, key, tag, documents, open_number, times=1):
    """Page Down ("pgdn") or Page Up ("pgup"), `times` times: the frame shows the page meant at once, and nothing is
    asked or said."""
    asked = len(posts(run))
    run.mark()
    for _ in range(times):
        run.m.named_key(key, pause=0.3)
        if getattr(chat, "text", None) is not None:
            chat.text = model.turned(chat.text, key == "pgdn")
    run.shot(tag, meant_screen(chat, documents, open_number))
    said = [line for line in run.since() if line.startswith(("You:", "Kernel:", "Model:", "Tokens:", "Tool:", "Round ", "Documents:"))]
    quiet = len(posts(run)) == asked and said == []
    report(run.tag + " " + tag + " asks and says nothing", quiet, None if quiet else "got %r" % said[-3:])


def check_things(tag, disk, documents, versions=()):
    """The disk read from outside: for each document its note, naming its newest version, its kind and its name, and
    the lines of that version; and for each (number, version, lines) in `versions`, those lines too."""
    found = read_things(disk)["things"]
    for one in documents:
        got = found.get("document %d" % one["number"], (0, None))[1]
        wanted = note(one["version"], one["name"], one.get("kind", documents_model.KIND_TABLE))
        report("%s note of document %d" % (tag, one["number"]), got == wanted, "got %r, meant %r" % (got, wanted))
        name = "document %d v%d" % (one["number"], one["version"])
        report("%s %s" % (tag, name), found.get(name, (0, None))[1] == one["lines"].encode())
    for number, version, lines in versions:
        name = "document %d v%d" % (number, version)
        report("%s %s" % (tag, name), found.get(name, (0, None))[1] == lines.encode())
    return found


def unfinished(given, name="lines"):
    """What the kernel's JSON reader takes out of a text cut off before its closing quote (`given`, what the model gave
    the tool so far, the text under `name`): the text as far as it goes, a backslash form cut in two left out."""
    lead = '"%s": "' % name
    rest = given[given.index(lead) + len(lead):]
    out, at = [], 0
    while at < len(rest) and rest[at] != '"':
        if rest[at] != "\\":
            out.append(rest[at])
            at += 1
            continue
        if at + 1 >= len(rest) or (rest[at + 1] == "u" and at + 6 > len(rest)):
            break
        if rest[at + 1] == "u":
            out.append(chr(int(rest[at + 2:at + 6], 16)))
            at += 6
        else:
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(rest[at + 1], rest[at + 1]))
            at += 2
    return "".join(out)


# ---------- The scenarios ----------

def scenario_write():
    print("write: a guide written as a document of text, its pages turned, changed by a wish, a table after it, a restart, "
          "an open, F1, and setup")
    disk, _ = answered_disk("text-write")
    run = start("text-write", disk, ["write=guide:0", "write=moons:1", "doc=fruit:0"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The guide, written whole on three pages: kept as document 1, which is open, its first page shown; the line ends.
    line = "write me a short guide to the planets as a document"
    guide = document(1, 1, "guide", 0)
    laid, said, whole = model.written(cases.text("guide", 0))
    report("write the guide is meant whole, on three pages", whole and len(laid["pages"]) == 3, said)
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(laid)])
    report("write a document written whole does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    meant.line(line, [])
    run.shot("guide", meant_screen(chat, [guide], 1))

    # Page Down: page 2, at once. With half of the next line typed, the keys turn the pages and type nothing: at the
    # last page Page Down changes nothing.
    turn(run, chat, "pgdn", "page-2", [guide], 1)
    run.press("add a sec", chat)
    turn(run, chat, "pgdn", "typing-page-3", [guide], 1)
    turn(run, chat, "pgdn", "typing-last-page", [guide], 1)
    turn(run, chat, "pgup", "typing-page-2", [guide], 1)

    # The rest of the line: it goes out whole, with the guide's lines; the model writes the whole guide again,
    # beginning with "document 1", and it is kept as the document's second version, shown from its first page.
    line = "add a section about moons"
    moons = document(1, 2, "moons", 1)
    laid, said, _ = model.written(cases.text("moons", 1))
    exchange(run, chat, line[len("add a sec"):], [T, kept_row(said, 1, changed=True), holds_text(laid)])
    meant.line(line, [guide], guide)
    run.shot("moons", meant_screen(chat, [moons], 1))

    # A table takes the frame: document 2, open; Page Down then changes nothing.
    line = "now a table of fruit prices"
    fruit = table_document(2, 1, "fruit")
    table, said, _ = drawn(document_cases.text("fruit", 0))
    exchange(run, chat, line, [T, kept_row(said, 2), holds_table(table)])
    meant.line(line, [moons], moons)
    run.shot("fruit", meant_screen(chat, [fruit, moons], 2))
    turn(run, chat, "pgdn", "fruit-page-down", [fruit, moons], 2)
    lines = run.end()
    kept = [kept_line(1, 1), kept_line(1, 2), kept_line(2, 1)]
    report("write the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("write", run)
    found = check_things("write", disk, [moons, fruit], versions=[(1, 1, guide["lines"])])
    no_key_in("write", lines)

    # After a restart nothing is open and the frame is empty; the panel lists both, the one changed last first. Opening
    # the guide shows its first page, and goes back to the model, which answers in words.
    again = start("text-write-2", disk, ["open=1"])
    chat = new_chat(b"now a table of fruit prices")
    give_key(again, chat)
    meant = Requests(chat)
    got = start_documents_lines(again.lines())
    report("write restart the lines about documents", got == start_lines(documents_of(found)), "got %r" % got)
    again.shot("restart", meant_screen(chat, [fruit, moons], None))
    turn(again, chat, "pgdn", "empty-frame-page-down", [fruit, moons], None)
    line = "open the planets guide"
    laid, _, _ = model.written(moons["lines"])
    exchange(again, chat, line, [T, opened_row(moons, model.opened_fit(laid)), holds_text(laid)] + back())
    meant.line(line, [fruit, moons])
    meant.again(line, 0, [moons, fruit], moons)
    again.shot("opened", meant_screen(chat, [moons, fruit], 1))

    # Page Down while a key is typed after `key`: the page turns, and the key typed around it is taken whole.
    again.press("key\n", chat)
    again.press(KEY[:12], chat)
    turn(again, chat, "pgdn", "key-page-2", [moons, fruit], 1)
    again.press(KEY[12:] + "\n", chat)
    taken = again.wait_line("Kernel: I took a secret of", timeout=30)
    meant_taken = "Kernel: I took a secret of %d signs." % len(KEY)
    key_whole = (taken or "").startswith(meant_taken)
    report("write restart the key typed around Page Down is whole", key_whole, None if key_whole else "got %r" % taken)

    # The kernel's own lines over the screen (F1), and a key that brings the usual picture back, with the page shown
    # (Backspace, which takes nothing away from an empty line).
    again.shot("key-taken", meant_screen(chat, [moons, fruit], 1))
    again.m.named_key("f1", pause=1)
    again.m.named_key("backspace", pause=0.5)
    again.shot("after-f1", meant_screen(chat, [moons, fruit], 1))

    # `setup`: the open document is closed and the frame empties; the documents stay listed.
    again.mark()
    again.press("setup\n", chat)
    asked = again.wait_line("Kernel: what should I call you?", timeout=30)
    report("write setup asks for the name", asked is not None, None if asked else "the question never came")
    chat.text = chat.table = None
    again.shot("setup", meant_screen(chat, [moons, fruit], None))
    lines = again.end()
    meant.check("write restart", again)
    no_key_in("write restart", lines)


def scenario_cut():
    print("cut: a change cut off, a document past the bound, the key, seven columns, refusals, no document line, and a "
          "change for a closed document")
    disk, _ = answered_disk("text-cut")
    behaviours = ["write=guide:0", "writecut=moons:1", "writelong", "writekey", "write=wide:0", "writebad", "writeempty",
                  "writebare=fruit", "write=moons:1", "again:write=moons:1", "write=big:0", "words=Hello."]
    run = start("text-cut", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    line = "a guide please"
    guide = document(1, 1, "guide", 0)
    guide_laid, said, _ = model.written(cases.text("guide", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(guide_laid)])
    meant.line(line, [])

    # A change that the limit of tokens cut off: not drawn, and that goes back; the guide stays as it was.
    line = "add the moons"
    exchange(run, chat, line, [CUT_OFF, T, model.cut_change_row(1)] + back())
    meant.line(line, [guide], guide)
    meant.again(line, 0, [guide], guide)
    run.shot("cut-change", meant_screen(chat, [guide], 1))

    # A new document longer than the bound on what the tool is given: cut there, its lines that came whole drawn, not
    # kept, and nothing is open then; that goes back.
    line = "a very long one"
    long_laid, said, whole = model.written(cases.long_cut(), whole=False)
    report("cut the long one is meant cut off", not whole and said.endswith("it was cut off, so I wrote only the lines that came whole."), said)
    exchange(run, chat, line, [T, not_kept_row(said), holds_text(long_laid)] + back())
    meant.line(line, [guide], guide)
    meant.again(line, 1, [guide])
    run.shot("long", meant_screen(chat, [guide], None))

    # A document with the key in it: starred where it came in, on the screen, on the disk and in every request.
    line = "a document with my key"
    keys = dict(number=2, version=1, name="Keys", lines=model.lines_kept(hide(cases.key_document(KEY), KEY)), kind=KIND_TEXT)
    laid, said, _ = model.written(cases.key_document(KEY), key=KEY)
    exchange(run, chat, line, [T, kept_row(said, 2), holds_text(laid)])
    meant.line(line, [guide])
    run.shot("key", meant_screen(chat, [keys, guide], 2))

    # Seven columns: six drawn, kept, and that goes back.
    line = "seven columns please"
    wide = document(3, 1, "wide", 0)
    laid, said, whole = model.written(cases.text("wide", 0))
    report("cut the wide one is meant with columns left out", not whole and "only its first 6 were drawn" in said, said)
    exchange(run, chat, line, [T, kept_row(said, 3), holds_text(laid)] + back())
    meant.line(line, [keys, guide], keys)
    meant.again(line, 2, [wide, keys, guide], wide)
    run.shot("wide", meant_screen(chat, [wide, keys, guide], 3))

    # Inputs that hold no lines, and lines that hold nothing to write: turned down, the frame as it was; each goes back.
    for place, (line, row) in enumerate([("the wrong name", model.CANNOT_READ), ("an empty one", model.NOTHING)]):
        exchange(run, chat, line, [T, row] + back())
        meant.line(line, [wide, keys, guide], wide)
        meant.again(line, 3 + place, [wide, keys, guide], wide)
    run.shot("refused", meant_screen(chat, [wide, keys, guide], 3))

    # A document without a document line: a new one, without a title, named by its number.
    line = "fruit as text"
    fruit = document(4, 1, "fruit")
    laid, said, _ = model.written(cases.text("fruit"))
    exchange(run, chat, line, [T, kept_row(said, 4), holds_text(laid)])
    meant.line(line, [wide, keys, guide], wide)
    report("cut the untitled one is named by its number", fruit["name"] == "" and documents_model.listed(fruit) == "document 4")

    # A change asked for document 1 while document 4 is open: document 1 is opened, not changed, and that goes back;
    # the next ask goes with its lines, and the change it brings is kept, shown from its first page.
    line = "add moons to the guide"
    moons = document(1, 2, "moons", 1)
    laid, said, _ = model.written(cases.text("moons", 1))
    exchange(run, chat, line, [T, closed_row(1), holds_text(guide_laid), AGAIN, T, kept_row(said, 1, changed=True), holds_text(laid)])
    meant.line(line, [fruit, wide, keys, guide], fruit)
    meant.again(line, 5, [guide, fruit, wide, keys], guide)
    run.shot("closed", meant_screen(chat, [moons, fruit, wide, keys], 1))

    # A whole document between the table's bound and its own: kept whole, read back from outside, and its lines go
    # with the next line.
    line = "a long guide please"
    big = document(5, 1, "big", 0)
    given = json.dumps({"lines": cases.text("big", 0)})
    report("cut the long guide is meant between the two bounds", 4096 < len(given) <= cases.DOCUMENT_INPUTS_LONGEST, "%d bytes" % len(given))
    laid, said, whole = model.written(cases.text("big", 0))
    report("cut the long guide is meant whole", whole, said)
    exchange(run, chat, line, [T, kept_row(said, 5), holds_text(laid)])
    meant.line(line, [moons, fruit, wide, keys], moons)
    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [big, moons, fruit, wide, keys], big)
    run.shot("big", meant_screen(chat, [big, moons, fruit, wide, keys], 5))
    lines = run.end()

    kept = [kept_line(1, 1), kept_line(2, 1), kept_line(3, 1), kept_line(4, 1), kept_line(1, 2), kept_line(5, 1)]
    report("cut the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("cut", run)
    found = check_things("cut", disk, [moons, keys, wide, fruit, big], versions=[(1, 1, guide["lines"])])
    names = sorted(name for name in found if name.startswith("document"))
    report("cut nothing more kept", names == ["document 1", "document 1 v1", "document 1 v2", "document 2", "document 2 v1", "document 3",
                                              "document 3 v1", "document 4", "document 4 v1", "document 5", "document 5 v1"],
           "got %r" % names)
    report("cut no piece of the key in the document's lines",
           not key_pieces(found.get("document 2 v1", (0, b""))[1].decode(errors="replace"), KEY))
    everything = "\n".join(json.dumps(note_.get("body")) for note_ in posts(run))
    report("cut no piece of the key in any request", not key_pieces(everything, KEY))
    no_key_in("cut", lines)


def scenario_odd():
    print("odd: every rule of the notes, twelve pages, another look, and a table changed into a document of text")
    disk, _ = answered_disk("text-odd")
    run = start("text-odd", disk, ["write=odd:0", "write=many:0", "look=2", "doc=fruit:0", "write=fruit:3", "doc=fruit:3", "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # A document with every rule in it: three pages, each dot for dot.
    line = "the odd one"
    odd = document(1, 1, "odd", 0)
    laid, said, whole = model.written(cases.text("odd", 0))
    report("odd the odd one is meant whole, on three pages", whole and len(laid["pages"]) == 3, said)
    report("odd its name is cleaned and cut", odd["name"] == "Notes on ..nusual signs ... and a title that", "got %r" % odd["name"])
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(laid)])
    meant.line(line, [])
    run.shot("odd-1", meant_screen(chat, [odd], 1))
    turn(run, chat, "pgdn", "odd-2", [odd], 1)
    turn(run, chat, "pgdn", "odd-3", [odd], 1)

    # Twelve pages: the title cut to leave room for "page 12 of 12"; Page Up at the first page and Page Down at the last
    # change nothing.
    line = "many pages"
    many = document(2, 1, "many", 0)
    laid, said, _ = model.written(cases.text("many", 0))
    report("odd the long one is meant on twelve pages", len(laid["pages"]) == 12 and len(laid["title"]) == 32, said)
    exchange(run, chat, line, [T, kept_row(said, 2), holds_text(laid)])
    meant.line(line, [odd], odd)
    run.shot("many-1", meant_screen(chat, [many, odd], 2))
    turn(run, chat, "pgup", "many-first-page", [many, odd], 2)
    turn(run, chat, "pgdn", "many-12", [many, odd], 2, times=11)
    turn(run, chat, "pgdn", "many-last-page", [many, odd], 2)

    # Another look paints the whole screen again: the page shown with it, in the new look's colours, the head's letters
    # made black in Night.
    line = "make it night"
    exchange(run, chat, line, [T, NIGHT])
    chat.look, chat.look_kept = "Night", "Night"
    meant.line(line, [many, odd], many)
    run.shot("night", meant_screen(chat, [many, odd], 2))

    # A table, then the same document written again with write_document: its second version is a document of text, and
    # its lines go with the next line as a document of text's.
    line = "fruit prices as a table"
    table = table_document(3, 1, "fruit")
    drawn_table, said, _ = drawn(document_cases.text("fruit", 0))
    exchange(run, chat, line, [T, kept_row(said, 3), holds_table(drawn_table)])
    meant.line(line, [many, odd], many)
    line = "write the fruit as a document"
    fruit = document(3, 2, "fruit", 3)
    laid, said, _ = model.written(cases.text("fruit", 3))
    exchange(run, chat, line, [T, kept_row(said, 3, changed=True), holds_text(laid)])
    meant.line(line, [table, many, odd], table)
    run.shot("fruit-text", meant_screen(chat, [fruit, many, odd], 3))

    # And back: drawn again with draw_table, its third version is a table once more, and the next line goes with its
    # lines as a table's.
    line = "make it a table again"
    table_again = table_document(3, 3, "fruit")
    drawn_again, said, _ = drawn(document_cases.text("fruit", 3))
    exchange(run, chat, line, [T, kept_row(said, 3, changed=True), holds_table(drawn_again)])
    meant.line(line, [fruit, many, odd], fruit)
    run.shot("fruit-table-again", meant_screen(chat, [table_again, many, odd], 3))
    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [table_again, many, odd], table_again)
    lines = run.end()
    meant.check("odd", run)
    check_things("odd", disk, [odd, many, table_again], versions=[(3, 1, table["lines"]), (3, 2, fruit["lines"])])
    no_key_in("odd", lines)


def scenario_broken():
    print("broken: answers that break off on their way: a change of a kept document, and a new document")
    disk, _ = answered_disk("text-broken")
    run = start("text-broken", disk, ["write=guide:0", "cut:write=moons:1", "cut:write=odd:0", "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    none = chat_cases.NO_TOKENS_LINE

    line = "a guide please"
    guide = document(1, 1, "guide", 0)
    laid, said, _ = model.written(cases.text("guide", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(laid)])
    meant.line(line, [])

    # A change in an answer that broke off: not drawn, and the guide stays as it was; the line ends there.
    line = "add the moons"
    given = chat_cases.stream_sent(pieces_of("cut:write=moons:1"))[1]
    report("broken the change's document line came", unfinished(given).startswith("document 1\n"), "got %r" % given[:40])
    exchange(run, chat, line, [BROKE, none, model.cut_change_row(1)])
    meant.line(line, [guide], guide)
    report("broken a broken change does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    run.shot("change", meant_screen(chat, [guide], 1))

    # A new document in an answer that broke off: its lines that came whole are drawn, it is not kept, and nothing is
    # open then; the line ends there.
    line = "the odd one"
    given = chat_cases.stream_sent(pieces_of("cut:write=odd:0"))[1]
    laid, said, whole = model.written(unfinished(given), whole=False)
    report("broken the odd one is meant with some of its lines", laid is not None and not whole, said)
    exchange(run, chat, line, [BROKE, none] + ([not_kept_row(said), holds_text(laid)] if laid else [said]))
    meant.line(line, [guide], guide)
    run.shot("new", meant_screen(chat, [guide], None))

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [guide])
    lines = run.end()
    meant.check("broken", run)
    found = check_things("broken", disk, [guide])
    names = sorted(name for name in found if name.startswith("document"))
    report("broken nothing more kept", names == ["document 1", "document 1 v1"], "got %r" % names)
    no_key_in("broken", lines)


def scenario_nodocs():
    print("nodocs: a disk without a notebook, where documents cannot be kept: write_document is not offered, nor done")
    disk = make("text-nodocs.img", "16M")
    run = Run("text-nodocs", disk, behaviours=["write=guide:0"], kernel_file=kernel())
    chat = ToolsChat(1280, notebook=None, kept_look=None)
    give_key(run, chat)
    line = "write a guide"
    exchange(run, chat, line, [T, model.NOT_HERE] + back())
    run.shot("nodocs", documents_model.screen(1280, 800, chat, [], []))
    meant_bodies = [body_meant(line, [], record=chat.records[-1], key=KEY, files=None),
                    body_again(line, [], chat.agains[0], key=KEY, files=None)]
    lines = run.end()
    seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
    report("nodocs requests for a line", len(seen) == len(meant_bodies), "%d, meant %d" % (len(seen), len(meant_bodies)))
    for number, (note_, body) in enumerate(zip(seen, meant_bodies)):
        check_body("nodocs request %d" % (number + 1), note_, body)
    no_key_in("nodocs", lines)


SCENARIOS = {"write": scenario_write, "cut": scenario_cut, "odd": scenario_odd, "broken": scenario_broken, "nodocs": scenario_nodocs}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
