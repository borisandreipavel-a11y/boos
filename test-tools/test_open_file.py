"""Files opened as documents (docs/tools.md `open_file`, docs/notebook.md): a kept CSV file's text goes to the model once,
with the next ask about the line, and the table the model draws from it is kept as a document that says which file it
came from. Every scenario boots the stand-in copy of the project (net_copy.py); the stand-in answers each line with the
tool the scenario names (open_file_cases.py, through document_cases.py and chat_cases.py) and serves made-up files
(download_cases.py). What the kernel is meant to say and send comes from open_file_model.py, documents_model.py and
chat_tools_model.py, written from the notes; every request for a line is compared whole, the disk file is read from
outside, and no request but the one ask that carries a file holds any of its text. Made-up key, sites and files only.

  open      the thing this part is done by: with a table of the planets open, a CSV fetched from a made-up site is
            opened; its text goes with the next ask only, behind the line; the model's table from it is kept as a new
            document whose note names the file, while the planets' note stays as it was; a change by a wish keeps
            saying so; after a restart, opening the file again opens that document, and sends nothing of the file.
  big       files put into the room from outside: a CSV over 64 KB sends its first 64 KB, cut behind a line end, and
            the table drawn from it goes back since rows did not fit, in a last ask that does not carry the file again;
            a CSV whose first line is longer than 64 KB, a PDF, bytes that are not plain text, a number that is not
            kept, and a number that cannot be read are each turned down; open_file lists only the CSV files; a CSV
            with a byte order mark, Windows line ends, quotes, letters beyond ASCII, a tab and a backslash goes to
            the model as it is.
  odd       a file opened for a line that drew no table is forgotten at the next line, whose new table is made from no
            file; a file opened in the second ask goes with the last one, without tools and without the words that
            ask for a table; an ask that carries a file and keeps no table from it still takes it, so that the last
            ask carries nothing of it.

Usage: python test_open_file.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, open_file_breaks.py), BOOS_PORT_BASE (45300 for this lane)."""
import json
import os

os.environ["DIVIDED_DISK"] = ""

import chat_cases
import document_cases
import download_cases
import open_file_cases as cases
from apps_kept_model import read_things
from chat_tools_model import ToolsChat, body_again, body_meant, model_row
from documents_model import kept_row, lines_kept, listed as document_listed, name_of, note, screen
from net_copy import build
from open_file_breaks import BREAKS
from open_file_model import (CANNOT_READ_FILE, file_part, listed, long_line_row, no_such_file_row, not_csv_row, not_plain_row,
                             note_from_file, put_files, reading_row, reopened_row)
from table_model import drawn
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import AGAIN, back, check_body, exchange, holds, no_key_in, posts

T = chat_cases.TOKENS_LINE
SITE = download_cases.SITE
_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of open_file_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=()):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel())


def new_chat(last_line=None):
    """The chat box at a start on an answered disk; after a restart, `last_line` is the line sent last before it."""
    return ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=last_line)


def document(number, version, written):
    """A document as these tests follow it, kept from the table text `written` (with its "document N" line)."""
    return dict(number=number, version=version, name=name_of(written), lines=lines_kept(written))


class Requests:
    """The requests for a line meant, in turn: each worked out once its ask goes, from the files kept, the documents
    listed and the one open then."""

    def __init__(self, chat):
        self.chat, self.bodies, self.agains = chat, [], 0

    def line(self, line, files, documents, open_one=None):
        self.bodies.append(body_meant(line, [], record=self.chat.records[-1], key=KEY, files=files,
                                      documents=[(one["number"], document_listed(one)) for one in documents], document=open_one))

    def again(self, line, files, documents, open_one=None, last=False):
        """The next ask about a line again; `line` is what goes as the person's message, the file behind it if any."""
        self.bodies.append(body_again(line, [], self.chat.agains[self.agains], last=last, key=KEY, files=files,
                                      documents=[(one["number"], document_listed(one)) for one in documents], document=open_one))
        self.agains += 1

    def check(self, tag, run):
        seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
        report(tag + " requests for a line", len(seen) == len(self.bodies), "%d, meant %d" % (len(seen), len(self.bodies)))
        for number, (note_, body) in enumerate(zip(seen, self.bodies)):
            check_body("%s request %d" % (tag, number + 1), note_, body)
        return seen


def carrying(run, mark):
    """The numbers (from 1) of the requests for a line whose body holds `mark` anywhere."""
    seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
    return [number + 1 for number, note_ in enumerate(seen) if mark in json.dumps(note_.get("body"), ensure_ascii=False)]


def check_notes(tag, disk, meant):
    """The disk read from outside: for each document number in `meant`, its note as meant, and its newest lines."""
    found = read_things(disk)["things"]
    for number, (note_bytes, version, lines) in meant.items():
        got = found.get("document %d" % number, (0, None))[1]
        report("%s note of document %d" % (tag, number), got == note_bytes, "got %r" % got)
        name = "document %d v%d" % (number, version)
        report("%s %s" % (tag, name), found.get(name, (0, None))[1] == lines.encode())
    return found


# ---------- The scenarios ----------

def scenario_open():
    print("open: a fetched CSV opened as a document, changed, and opened again after a restart")
    disk, _ = answered_disk("of-open", [("site 1", SITE)])
    behaviours = ["doc=planets:0", "fetch=https://%s/b.csv" % SITE, "openfile=1", "again:filetable=numbers", "filechange=doubled:2",
                  "words=Hello."]
    run = start("of-open", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # A table of the planets, kept as document 1 and open; it is made from no file.
    line = "show me the planets"
    written = document_cases.text("planets", 0)
    planets = document(1, 1, written)
    table, said, _ = drawn(written)
    exchange(run, chat, line, [T, kept_row(said, 1), holds(table)])
    meant.line(line, [], [])

    # The CSV from the made-up site, kept as file 1.
    line = "get b.csv"
    exchange(run, chat, line, [T, download_cases.fetching("b.csv", SITE), download_cases.kept("b.csv", 1, "csv", cases.FETCHED, SITE)])
    meant.line(line, [], [planets], planets)
    files = [listed(1, "b.csv", "csv", cases.FETCHED)]

    # Opened: the kernel reads it and asks the model again, with the file's text behind the line; the model's table
    # from it is a new document, number 2, open from then on.
    line = "open b.csv"
    written = cases.text("numbers", 0)
    numbers = document(2, 1, written)
    table, said, whole = drawn(written)
    report("open the numbers are meant whole", whole, said)
    exchange(run, chat, line, [T, reading_row(1, "b.csv", cases.FETCHED), AGAIN, T, kept_row(said, 2), holds(table)])
    meant.line(line, files, [planets], planets)
    meant.again(line + file_part(1, "b.csv", cases.FETCHED), files, [planets], planets)
    run.shot("opened", screen(1280, 800, chat, [], [numbers, planets], 2))

    # A change by a wish: the document's second version, still made from file 1.
    line = "double the counts"
    written = cases.text("doubled", 2)
    doubled = document(2, 2, written)
    table, said, _ = drawn(written)
    exchange(run, chat, line, [T, kept_row(said, 2, changed=True), holds(table)])
    meant.line(line, files, [numbers, planets], numbers)

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, files, [doubled, planets], doubled)
    lines = run.end()
    meant.check("open", run)
    carried = carrying(run, cases.MARK)
    report("open only the ask that carries the file holds its text", carried == [4], "got %r" % carried)
    check_notes("open", disk, {1: (note(1, "Planets"), 1, planets["lines"]),
                               2: (note_from_file(2, "Numbers", 1), 2, doubled["lines"])})
    no_key_in("open", lines)

    # After a restart, opening the file again opens its document: nothing of the file goes to the model, and the
    # opening goes back, as an opened document does.
    again = start("of-open-2", disk, ["openfile=1"])
    chat = new_chat(b"hello")
    give_key(again, chat)
    meant = Requests(chat)
    line = "open b.csv"
    table, _, _ = drawn(doubled["lines"])
    exchange(again, chat, line, [T, reopened_row(doubled, 1), holds(table)] + back())
    meant.line(line, files, [doubled, planets])
    meant.again(line, files, [doubled, planets], doubled)
    lines = again.end()
    meant.check("open restart", again)
    report("open restart no request holds the file's text", carrying(again, cases.MARK) == [], "got %r" % carrying(again, cases.MARK))
    no_key_in("open restart", lines)


def scenario_big():
    print("big: a file over 64 KB, and every file and number that is turned down")
    disk, _ = answered_disk("of-big")
    put_files(disk, [(1, "big.csv", "csv", cases.BIG), (2, "long.csv", "csv", cases.LONG_LINE), (3, "a.pdf", "pdf", download_cases.PDF),
                     (4, "odd.csv", "csv", cases.NOT_PLAIN), (5, "real.csv", "csv", cases.REAL)])
    files = [listed(5, "real.csv", "csv", cases.REAL), listed(4, "odd.csv", "csv", cases.NOT_PLAIN), listed(3, "a.pdf", "pdf", download_cases.PDF),
             listed(2, "long.csv", "csv", cases.LONG_LINE), listed(1, "big.csv", "csv", cases.BIG)]
    behaviours = ["openfile=1", "again:filetable=bigfirst", "openfile=2", "openfile=3", "openfile=4", "openfile=9", "openfilebad", "openfile=5"]
    run = start("of-big", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The first 64 KB go, cut behind a line end. The table drawn from them has more rows than fit, so it goes back,
    # in the last ask, which carries nothing of the file.
    line = "open big.csv"
    written = cases.text("bigfirst", 0)
    rows = document(1, 1, written)
    table, said, whole = drawn(written)
    report("big the rows are meant with some left out", not whole, said)
    exchange(run, chat, line, [T, reading_row(1, "big.csv", cases.BIG), AGAIN, T, kept_row(said, 1), holds(table)] + back())
    meant.line(line, files, [])
    meant.again(line + file_part(1, "big.csv", cases.BIG), files, [])
    meant.again(line, files, [rows], rows, last=True)
    # A measurement, with no verdict: how long the line with the 64 KB took, three asks, against one with two asks.
    print("time: 'open big.csv' (three asks, the second with 64 KB) answered after %.1f s" % run.answered_after)

    # Each turned down, and each goes back.
    for line, row in [("open the long one", long_line_row(2, "long.csv")), ("open the pdf", not_csv_row(3, "a.pdf", "pdf")),
                      ("open odd", not_plain_row(4, "odd.csv")), ("open file nine", no_such_file_row(9)), ("open that file", CANNOT_READ_FILE)]:
        exchange(run, chat, line, [T, row] + back())
        meant.line(line, files, [rows], rows)
        meant.again(line, files, [rows], rows)
        if line == "open the long one":
            print("time: 'open the long one' (two asks, no file) answered after %.1f s" % run.answered_after)

    # A CSV as real files often are: its byte order mark, Windows line ends, quotes, letters beyond ASCII, a tab and a
    # backslash go to the model as they are, the JSON way, compared whole; the model answers in words.
    line = "open real.csv"
    exchange(run, chat, line, [T, reading_row(5, "real.csv", cases.REAL)] + back())
    meant.line(line, files, [rows], rows)
    meant.again(line + file_part(5, "real.csv", cases.REAL), files, [rows], rows)
    lines = run.end()
    meant.check("big", run)
    last_row = cases.BIG_ROWS[-1][0]
    report("big the end of the file goes nowhere", carrying(run, ",".join(cases.BIG_ROWS[-1])) == [], last_row)
    check_notes("big", disk, {1: (note_from_file(1, "Rows", 1), 1, rows["lines"])})
    no_key_in("big", lines)


def scenario_odd():
    print("odd: a file opened for a line that drew no table, and a file opened in the second ask")
    disk, _ = answered_disk("of-odd")
    put_files(disk, [(1, "b.csv", "csv", cases.FETCHED)])
    files = [listed(1, "b.csv", "csv", cases.FETCHED)]
    run = start("of-odd", disk, ["openfile=1", "doc=fruit:0", "openfile=9", "again:openfile=1", "openfile=1", "again:openfile=9",
                                 "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The model answers the ask that carries the file in words: no table, and nothing is kept.
    line = "open b.csv"
    exchange(run, chat, line, [T, reading_row(1, "b.csv", cases.FETCHED)] + back())
    meant.line(line, files, [])
    meant.again(line + file_part(1, "b.csv", cases.FETCHED), files, [])

    # The next line's new table is made from no file.
    line = "fruit please"
    written = document_cases.text("fruit", 0)
    fruit = document(1, 1, written)
    table, said, _ = drawn(written)
    exchange(run, chat, line, [T, kept_row(said, 1), holds(table)])
    meant.line(line, files, [])

    # A file opened in the second ask goes with the third, the last: without tools, and without the words that ask
    # for a table.
    line = "open file nine then b"
    exchange(run, chat, line, [T, no_such_file_row(9), AGAIN, T, reading_row(1, "b.csv", cases.FETCHED)] + back())
    meant.line(line, files, [fruit], fruit)
    meant.again(line, files, [fruit], fruit)
    meant.again(line + file_part(1, "b.csv", cases.FETCHED, draw=False), files, [fruit], fruit, last=True)

    # The ask that carries the file is answered with a tool that goes back, and no table is kept from it: the last ask
    # carries nothing of the file, since the one before took it.
    line = "open b.csv then nine"
    exchange(run, chat, line, [T, reading_row(1, "b.csv", cases.FETCHED), AGAIN, T, no_such_file_row(9)] + back())
    meant.line(line, files, [fruit], fruit)
    meant.again(line + file_part(1, "b.csv", cases.FETCHED), files, [fruit], fruit)
    meant.again(line, files, [fruit], fruit, last=True)

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, files, [fruit], fruit)
    lines = run.end()
    meant.check("odd", run)
    carried = carrying(run, cases.MARK)
    report("odd only the asks that carry the file hold its text", carried == [2, 6, 8], "got %r" % carried)
    check_notes("odd", disk, {1: (note(1, "Fruit prices"), 1, fruit["lines"])})
    no_key_in("odd", lines)


SCENARIOS = {"open": scenario_open, "big": scenario_big, "odd": scenario_odd}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
