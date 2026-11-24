"""PDFs opened as documents of text and tables (docs/tools.md `open_file`, docs/model.md): a kept PDF goes to Anthropic,
which fetches it from the address the file was fetched from, at the person's yes to its price, and the model writes it as
a document of text and tables, kept as the PDF's. Every scenario boots the stand-in copy of the project (net_copy.py)
with every line going to Anthropic (BOOS_PROVIDER=anthropic), but `orca`, which runs with OrcaRouter; the stand-in
answers in Anthropic's form, writes each request back in OrcaRouter's (anthropic_cases.back, the PDF's address as a part
of its own) and never fetches a PDF. What the kernel is meant to say and send comes from pdf_model.py,
text_document_model.py, documents_model.py and chat_tools_model.py, written from the notes; every request for a line is
compared whole, and the disk is read from outside. Every site, file and key is made up.

  open      the thing this part is done by: a.pdf fetched through a redirect and kept; "open the report": the question,
            with its size and price, naming the site; yes: the next ask carries the PDF's address after the redirect, and
            the model writes its text and table with write_document, kept as document 1 made from file 1; opened again:
            its document, and nothing of the PDF sent.
  no        no sends nothing and goes back; a yes answered in words keeps nothing, and the next opening asks again; a PDF
            opened on a line's second ask is turned down before the question; a PDF whose note keeps no address that
            could be fetched is not listed, and turned down.
  refused   Anthropic cannot fetch the address: its 400 said word for word, the line ends, and nothing is kept.
  wait      the ask that carries a PDF waits longer than a minute for its answer, and takes it.
  orca      with OrcaRouter, open_file lists no PDF and keeps its CSV sentence; a PDF asked for anyway is turned down.

Usage: python test_pdf_documents.py [scenario ...]   (with none: every scenario but orca with BOOS_PROVIDER=anthropic,
                                                       orca without)
Environment: BREAK (a break on purpose, pdf_breaks.py), BOOS_PORT_BASE, BOOS_PROVIDER."""
import json
import os
import struct
import time

os.environ["DIVIDED_DISK"] = ""

import chat_cases
import chat_tools_model
import download_cases
import pdf_model
import text_document_cases as cases
import text_document_model as model
from apps_kept_model import block_of, read_things
from chat_tools_model import ANTHROPIC, model_row
from documents_model import KIND_TEXT, called, kept_row
from nb import put_block
from net_copy import build
from open_file_model import listed, pdf_not_here_row, put_files
from pdf_breaks import BREAKS
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import AGAIN, back, exchange, no_key_in, posts, rounds_since, shown_since
from test_open_file import Requests
from test_text_documents import holds_text, meant_screen, new_chat

T = chat_cases.TOKENS_LINE
SITE = download_cases.SITE
PDF = download_cases.PDF
ADDRESS = "https://%s/a.pdf" % SITE
LOOK_NINE = "Kernel: the model asked for look 9, but there are only 4 looks."
# Words long enough for the stand-in to hold its answer after them (chat_cases.HOLD_SIGNS).
HELD_WORDS = ("The report is short: sales rose in every region this quarter, most of all in the north, and a little less in "
              "the south and the west, where the year began slowly.")
_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of pdf_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=()):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel())


def needs(anthropic, tag):
    """Whether the scenario runs with the provider it is written for; says so when not."""
    ok = ANTHROPIC == anthropic
    report(tag + " runs with " + ("Anthropic" if anthropic else "OrcaRouter"), ok,
           None if ok else "set BOOS_PROVIDER=anthropic for it" if anthropic else "run it without BOOS_PROVIDER")
    return ok


def text_document(number, version, name, number_line=None):
    """A document of text kept from the document `name` of text_document_cases.py."""
    written = cases.text(name, number_line)
    return dict(number=number, version=version, name=model.name_of(written), lines=model.lines_kept(written), kind=KIND_TEXT)


def note_from_file(version, name, file):
    """The note of a document of text made from a kept file: form 2, kind 2, the version, the file's number, the name."""
    return bytes([2, KIND_TEXT]) + struct.pack("<I", version) + struct.pack("<I", file) + name.encode()


def reopened_row(document, file, laid):
    """Opening a file that a document of text was made from before: that document opens, with its pages."""
    return "Kernel: I opened %s, made from file %d before%s." % (called(document), file, model.opened_fit(laid))


class PdfRequests(Requests):
    """test_open_file.Requests, where `opens` names the files open_file lists when not every kept PDF opens (a note
    without an address), and `pdf` sends the next ask with the PDF's address before the line."""

    def __init__(self, chat, opens=None):
        super().__init__(chat)
        self.opens = opens

    def _mend(self):
        body = self.bodies[-1]
        if self.opens is not None:
            for place, tool in enumerate(body.get("tools") or []):
                if tool["function"]["name"] == "open_file":
                    body["tools"][place] = chat_tools_model.open_file_tool(self.opens)

    def line(self, line, files, documents, open_one=None):
        super().line(line, files, documents, open_one)
        self._mend()

    def again(self, line, files, documents, open_one=None, last=False, pdf=None):
        super().again(line, files, documents, open_one, last)
        self._mend()
        if pdf:
            pdf_model.with_pdf(self.bodies[-1], pdf)


def answer(run, chat, text, after, timeout=90, meanwhile=None):
    """The person's answer to a question of the kernel's: shown as their row, not remembered and not sent to the model;
    then the rows in `after` (rows and steps, as for exchange)."""
    run.mark()
    run.press(text + "\n")
    pressed = time.time()
    if meanwhile:
        meanwhile()
    mine = "You: " + text
    chat.said.append(mine)
    chat.add("person", mine)
    rows = [item for item in after if isinstance(item, str)]
    meant = [mine] + rows
    wanted = rows[-1] if rows else mine
    end = time.time() + timeout
    while time.time() < end and (wanted not in run.since() or len(shown_since(run)) < len(meant)):
        time.sleep(0.02)
    run.answered_after = time.time() - pressed
    time.sleep(0.6)
    got = shown_since(run)
    report(run.tag + " answer %r" % text, got == meant, None if got == meant else "got %r, meant %r" % (got[-8:], meant[-8:]))
    for item in after:
        if not isinstance(item, str):
            item(chat)
        elif item.startswith(("Kernel:", "Model:")):
            chat.row(item)


def carrying(run, mark):
    """The numbers (from 1) of the requests for a line whose body holds `mark` anywhere."""
    seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
    return [number + 1 for number, note_ in enumerate(seen) if mark in json.dumps(note_.get("body"))]


def documents_kept(disk):
    return sorted(name for name in read_things(disk)["things"] if name.startswith("document"))


# ---------- The scenarios ----------

def scenario_open():
    print("open: a PDF fetched through a redirect, opened at a yes, written as a document of text, and opened again")
    if not needs(True, "open"):
        return
    disk, _ = answered_disk("pdf-open", [("site 1", SITE)])
    run = start("pdf-open", disk, ["fetch=https://%s/go/a.pdf" % SITE, "openfile=1", "again:write=report:0", "openfile=1", "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = PdfRequests(chat)

    # The PDF, through a redirect from /go/a.pdf to /a.pdf, kept as file 1, its note keeping the address it came from.
    line = "get the report"
    exchange(run, chat, line, [T, download_cases.fetching("a.pdf", SITE), download_cases.kept("a.pdf", 1, "pdf", PDF, SITE)])
    meant.line(line, [], [])
    files = [listed(1, "a.pdf", "pdf", PDF)]

    # Opened: the question first, with its size and price, naming the site; the line waits for the answer.
    line = "open the report"
    exchange(run, chat, line, [T, pdf_model.question_row(1, "a.pdf", PDF, ADDRESS)])
    meant.line(line, files, [])
    report("open the question asks nothing of the model yet", rounds_since(run) == [], "got %r" % rounds_since(run))

    # Yes: the next ask carries the PDF's address before the line, and the lead behind it; the model writes the PDF as
    # a document of text and tables, kept as document 1, made from file 1.
    report_document = text_document(1, 1, "report", 0)
    laid, said, whole = model.written(cases.text("report", 0))
    report("open the report is meant whole", whole, said)
    answer(run, chat, "yes", [pdf_model.goes_row(1, "a.pdf"), AGAIN, T, kept_row(said, 1), holds_text(laid)])
    meant.again(line + pdf_model.pdf_part(1, "a.pdf", PDF), files, [], pdf=ADDRESS)
    run.shot("report", meant_screen(chat, [report_document], 1))

    # Opened again: the document made from it opens, nothing of the PDF goes, and that goes back.
    line = "open the report again"
    exchange(run, chat, line, [T, reopened_row(report_document, 1, laid), holds_text(laid)] + back())
    meant.line(line, files, [report_document], report_document)
    meant.again(line, files, [report_document], report_document)

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, files, [report_document], report_document)
    lines = run.end()
    meant.check("open", run)
    carried = carrying(run, ADDRESS)
    report("open only the ask that carries the PDF holds its address", carried == [3], "got %r" % carried)
    found = read_things(disk)["things"]
    file_note = found.get("file 1", (0, b""))[1]
    report("open the file's note keeps the address after the redirect", ("\nfrom %s\n" % ADDRESS).encode() in file_note, "got %r" % file_note[-60:])
    got = found.get("document 1", (0, None))[1]
    wanted = note_from_file(1, "Quarterly report", 1)
    report("open the document's note: a document of text made from file 1", got == wanted, "got %r, meant %r" % (got, wanted))
    report("open the document's lines", found.get("document 1 v1", (0, None))[1] == report_document["lines"].encode())
    no_key_in("open", lines)


def scenario_no():
    print("no: a no, a yes answered in words, a PDF opened on a line's second ask, and a PDF without an address")
    if not needs(True, "no"):
        return
    disk, _ = answered_disk("pdf-no")
    put_files(disk, [(1, "a.pdf", "pdf", PDF), (2, "b.pdf", "pdf", PDF)])
    # b.pdf's note again, behind the notebook's end: its address is not one that could have been fetched (http://).
    found = read_things(disk)
    note_two = found["things"]["file 2"][1].replace(b"from https://", b"from http://")
    put_block(disk, found["end"], block_of(found["end"], "file 2", note_two))
    behaviours = ["openfile=1", "openfile=1", "again:words=It is a short report about sales.", "openfile=1", "look=9", "again:openfile=1",
                  "openfile=2"]
    run = start("pdf-no", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    files = [listed(2, "b.pdf", "pdf", PDF), listed(1, "a.pdf", "pdf", PDF)]
    meant = PdfRequests(chat, opens=[listed(1, "a.pdf", "pdf", PDF)])

    # No: nothing is sent, and that goes back to the model.
    line = "open the pdf"
    exchange(run, chat, line, [T, pdf_model.question_row(1, "a.pdf", PDF, ADDRESS)])
    meant.line(line, files, [])
    answer(run, chat, "no", [pdf_model.not_sent_row(1, "a.pdf")] + back())
    meant.again(line, files, [])

    # Yes, and the model answers in words: nothing is kept.
    line = "what does the pdf say"
    exchange(run, chat, line, [T, pdf_model.question_row(1, "a.pdf", PDF, ADDRESS)])
    meant.line(line, files, [])
    answer(run, chat, "yes", [pdf_model.goes_row(1, "a.pdf"), AGAIN, model_row("It is a short report about sales."), T])
    meant.again(line + pdf_model.pdf_part(1, "a.pdf", PDF), files, [], pdf=ADDRESS)

    # So the next opening asks again.
    line = "open it once more"
    exchange(run, chat, line, [T, pdf_model.question_row(1, "a.pdf", PDF, ADDRESS)])
    meant.line(line, files, [])
    answer(run, chat, "no", [pdf_model.not_sent_row(1, "a.pdf")] + back())
    meant.again(line, files, [])

    # Opened on the line's second ask, it would go with the third, which offers no tools: turned down, and not asked.
    line = "open it in the end"
    exchange(run, chat, line, [T, LOOK_NINE, AGAIN, T, pdf_model.late_row(1, "a.pdf")] + back())
    meant.line(line, files, [])
    meant.again(line, files, [])
    meant.again(line, files, [], last=True)

    # A PDF whose note keeps no address that could be fetched: open_file does not list it, and it is turned down.
    line = "open the other one"
    exchange(run, chat, line, [T, pdf_model.no_address_row(2, "b.pdf")] + back())
    meant.line(line, files, [])
    meant.again(line, files, [])
    lines = run.end()
    meant.check("no", run)
    carried = carrying(run, ADDRESS)
    report("no only the ask after the yes holds the address", carried == [4], "got %r" % carried)
    report("no nothing kept", documents_kept(disk) == [], "got %r" % documents_kept(disk))
    no_key_in("no", lines)


def scenario_refused():
    print("refused: Anthropic cannot fetch the PDF's address, and says so")
    if not needs(True, "refused"):
        return
    disk, _ = answered_disk("pdf-refused")
    put_files(disk, [(1, "a.pdf", "pdf", PDF)])
    run = start("pdf-refused", disk, ["openfile=1", "again:pdfrefused", "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    files = [listed(1, "a.pdf", "pdf", PDF)]
    meant = PdfRequests(chat)

    line = "open the pdf"
    exchange(run, chat, line, [T, pdf_model.question_row(1, "a.pdf", PDF, ADDRESS)])
    meant.line(line, files, [])
    # Anthropic's 400 before any piece, said word for word; the line ends there.
    answer(run, chat, "yes", [pdf_model.goes_row(1, "a.pdf"), AGAIN, pdf_model.refused_row(400, pdf_model.UNFETCHABLE)])
    meant.again(line + pdf_model.pdf_part(1, "a.pdf", PDF), files, [], pdf=ADDRESS)

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, files, [])
    lines = run.end()
    meant.check("refused", run)
    report("refused nothing kept", documents_kept(disk) == [], "got %r" % documents_kept(disk))
    no_key_in("refused", lines)


def scenario_wait():
    print("wait: the ask that carries a PDF takes its answer after more than a minute")
    if not needs(True, "wait"):
        return
    disk, _ = answered_disk("pdf-wait")
    put_files(disk, [(1, "a.pdf", "pdf", PDF)])
    run = start("pdf-wait", disk, ["openfile=1", "again:hold:words=" + HELD_WORDS])
    chat = new_chat()
    give_key(run, chat)
    files = [listed(1, "a.pdf", "pdf", PDF)]
    meant = PdfRequests(chat)

    line = "open the pdf"
    exchange(run, chat, line, [T, pdf_model.question_row(1, "a.pdf", PDF, ADDRESS)])
    meant.line(line, files, [])

    def later():
        """The stand-in holds the answer after its first words; it goes on 70 seconds after the yes."""
        begun = time.time()
        while time.time() < begun + 60 and not os.path.exists(run.log + ".held"):
            time.sleep(0.05)
        report("wait the stand-in holds the answer", os.path.exists(run.log + ".held"))
        while time.time() < begun + 70:
            time.sleep(0.2)
        open(run.log + ".go", "w").close()

    answer(run, chat, "yes", [pdf_model.goes_row(1, "a.pdf"), AGAIN, model_row(HELD_WORDS), T], timeout=150, meanwhile=later)
    report("wait the answer came after more than a minute", run.answered_after > 65, "after %.1f s" % run.answered_after)
    meant.again(line + pdf_model.pdf_part(1, "a.pdf", PDF), files, [], pdf=ADDRESS)
    lines = run.end()
    meant.check("wait", run)
    no_key_in("wait", lines)


def scenario_orca():
    print("orca: with OrcaRouter, a PDF is not listed and is turned down")
    if not needs(False, "orca"):
        return
    disk, _ = answered_disk("pdf-orca")
    put_files(disk, [(1, "b.csv", "csv", download_cases.CSV), (2, "a.pdf", "pdf", PDF)])
    run = start("pdf-orca", disk, ["openfile=2"])
    chat = new_chat()
    give_key(run, chat)
    files = [listed(2, "a.pdf", "pdf", PDF), listed(1, "b.csv", "csv", download_cases.CSV)]
    meant = PdfRequests(chat)

    line = "open the pdf"
    exchange(run, chat, line, [T, pdf_not_here_row(2, "a.pdf")] + back())
    meant.line(line, files, [])
    meant.again(line, files, [])
    lines = run.end()
    meant.check("orca", run)
    no_key_in("orca", lines)


SCENARIOS = {"open": scenario_open, "no": scenario_no, "refused": scenario_refused, "wait": scenario_wait, "orca": scenario_orca}


def main():
    import sys
    names = sys.argv[1:] or ([name for name in SCENARIOS if name != "orca"] if ANTHROPIC else ["orca"])
    for name in names:
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
