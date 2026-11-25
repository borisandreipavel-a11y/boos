"""Pictures in documents (docs/screen.md "A document of text", "Pictures"; docs/tools.md `download_file`, `open_file`
and `write_document`; docs/pictures.md): a PNG picture fetched from a made-up site and kept, opened in the frame as a
document of its own and nothing of it sent, `picture` lines in documents of text, shrunk to fit a page and painted over
the look's colour, and kept files that cannot be shown. Every scenario boots the stand-in copy of the project
(net_copy.py); the stand-in answers each line with the tool the scenario names (picture_document_cases.py, through
chat_cases.py) and serves made-up pictures (picture_files.py, through download_cases.py). What the kernel is meant to say,
send and show comes from picture_document_model.py, documents_model.py and chat_tools_model.py, written from the notes;
every request for a line is compared whole, every picture of the screen dot for dot, and the disk is read from outside.
Made-up key, site and pictures only.

  fetch     the thing this part is done by: a PNG picture fetched from the made-up site and kept as file 1; "show me the
            picture" opens it in the frame as document 1, shrunk to fit, see-through by every amount in its lower half,
            and the line ends; a caption and a paragraph by a wish keep its second version; F1 and a key paint it again;
            another look paints it over that look's colour; Page Down changes nothing. After a restart on the same disk,
            whose file and notes the kernel wrote itself, the picture's document is listed, and opening the picture
            again opens it in the look kept and ends the line; `setup` empties the frame.
  reopen    a disk with a picture's document and a removed file, put there from outside: the start lists both
            documents; opening the file again opens its document and ends the line; another document that names the
            removed file says so on its page and in the row, and goes back; its second page holds the picture.
  kinds     eight small pictures of most kinds a PNG has (grey of 1 and 16 bits with a key, grey with alpha, colour
            of 16 bits with a key, colour and alpha of 16 bits, palettes of 4 and 8 bits with alphas, interlaced, packed
            dots in pieces of 7 bytes), four to a document, each at its own size, dot for dot; then the look Contrast.
  layout    a document whose wide picture follows a paragraph, whose tall picture takes a page of its own, and whose
            pictures of a number never kept, of a CSV file and past the fourth say why in their place; it goes back;
            Page Down shows each page.
  broken    damaged pictures put on the disk from outside, each turned down with the reader's reason, the frame and the
            open document as they were; then a good one opens.
  photos    JPEG photos: a baseline one fetched from the made-up site and kept, by its first bytes, as a JPEG photo;
            opened in the frame, shrunk to fit; a document of a progressive and a grey photo put on the disk, a PNG
            picture, and a photo whose Exif note says it was taken turned, turned back, with write_document naming
            both kinds; F1 and a key, and another look; photos that must be turned down, each with the reader's
            reason; after a restart, the photo opened again.

Usage: python test_picture_documents.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, picture_document_breaks.py), BOOS_PORT_BASE, BOOS_PROVIDER ("anthropic": every
line goes to Anthropic, in Anthropic's form; the rows, pictures and requests meant are the same)."""
import os

os.environ["DIVIDED_DISK"] = ""

import chat_cases
import documents_model
import download_cases
import picture_document_cases as cases
import picture_document_model as model
import picture_files
from apps_kept_model import block_of, read_things
from chat_tools_model import ToolsChat, body_again, body_meant
from documents_model import KIND_TEXT, called, kept_row, opened_row
from net_copy import build
from nb import put_block
from open_file_model import listed, put_files
from picture_document_breaks import BREAKS
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import back, check_body, exchange, no_key_in, posts, rounds_since
from test_documents import start_documents_lines
from text_document_model import turned

T = chat_cases.TOKENS_LINE
SITE = download_cases.SITE
NIGHT = "Kernel: this is look 2, Night. It is kept on the disk."
CONTRAST = "Kernel: this is look 4, Contrast. It is kept on the disk."
_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of picture_document_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=()):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel())


def new_chat(last_line=None, kept_look=b""):
    """The chat box at a start on an answered disk; after a restart, `last_line` is the line sent last before it, which
    the kernel says again, and `kept_look` the look kept then."""
    return ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=kept_look, last_line=last_line)


def document(number, version, written, name=None):
    """A document of text as these tests follow it, kept from the lines `written` (with any "document N" line)."""
    from text_document_model import name_of
    return dict(number=number, version=version, name=name if name is not None else name_of(written), lines=model.lines_kept(written),
                kind=KIND_TEXT)


class Requests:
    """The requests for a line meant, in turn: each worked out once its ask goes, from the files kept, the documents
    listed and the one open then."""

    def __init__(self, chat):
        self.chat, self.bodies, self.agains = chat, [], 0

    def line(self, line, files, documents, open_one=None):
        self.bodies.append(body_meant(line, [], record=self.chat.records[-1], key=KEY, files=files,
                                      documents=[(one["number"], documents_model.listed(one)) for one in documents], document=open_one))

    def again(self, line, files, documents, open_one=None, last=False):
        self.bodies.append(body_again(line, [], self.chat.agains[self.agains], last=last, key=KEY, files=files,
                                      documents=[(one["number"], documents_model.listed(one)) for one in documents], document=open_one))
        self.agains += 1

    def check(self, tag, run):
        seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
        report(tag + " requests for a line", len(seen) == len(self.bodies), "%d, meant %d" % (len(seen), len(self.bodies)))
        for number, (note_, body) in enumerate(zip(seen, self.bodies)):
            check_body("%s request %d" % (tag, number + 1), note_, body)


def holds(laid):
    """A step for `exchange`: from then on the frame shows this document of text with pictures (picture_document_model)."""
    def step(chat):
        chat.text, chat.table = laid, None
    return step


def meant_screen(chat, documents, open_number):
    """The whole screen meant: documents_model.screen's, with the page shown of the document the chat model holds."""
    picture = documents_model.screen(1280, 800, chat, [], documents, open_number)
    if getattr(chat, "text", None) is not None:
        model.paint(picture, chat.text, getattr(chat, "look", "Blue"))
    return picture


def turn(run, chat, key, tag, documents, open_number):
    """Page Down ("pgdn") or Page Up ("pgup"): the page meant at once, and nothing asked or said."""
    asked = len(posts(run))
    run.mark()
    run.m.named_key(key, pause=0.5)
    if getattr(chat, "text", None) is not None:
        chat.text = turned(chat.text, key == "pgdn")
    run.shot(tag, meant_screen(chat, documents, open_number))
    said = [line for line in run.since() if line.startswith(("You:", "Kernel:", "Model:", "Tokens:", "Round "))]
    quiet = len(posts(run)) == asked and said == []
    report(run.tag + " " + tag + " asks and says nothing", quiet, None if quiet else "got %r" % said[-3:])


def ends(run, tag):
    """The line ended with the tool: no ask about it again."""
    report(tag + " the line ends", rounds_since(run) == [], None if rounds_since(run) == [] else "got %r" % rounds_since(run))


def check_notes(tag, disk, meant):
    """The disk read from outside: for each document number in `meant`, its note as meant, and its newest lines."""
    found = read_things(disk)["things"]
    for number, (note_bytes, version, lines) in meant.items():
        got = found.get("document %d" % number, (0, None))[1]
        report("%s note of document %d" % (tag, number), got == note_bytes, None if got == note_bytes else "got %r" % got)
        name = "document %d v%d" % (number, version)
        report("%s %s" % (tag, name), found.get(name, (0, None))[1] == lines.encode())
    return found


def put_removed(disk, number):
    """The note of a removed file, put behind the notebook's end from outside: empty, as the kernel leaves it."""
    end = read_things(disk)["end"]
    put_block(disk, end, block_of(end, "file %d" % number, b""))


# ---------- The scenarios ----------

def scenario_fetch():
    print("fetch: a picture fetched and kept, opened in the frame, a caption by a wish, F1, another look, setup")
    disk, _ = answered_disk("pd-fetch", [("site 1", SITE)])
    harbour = picture_files.picture("harbour")
    behaviours = ["fetch=https://%s/pictures/harbour.png" % SITE, "openfile=1", "picdoc=caption:1", "look=2", "words=Hello."]
    run = start("pd-fetch", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The picture from the made-up site: kept as file 1, a PNG picture, by its first eight bytes.
    line = "get the harbour picture"
    kept = download_cases.kept("harbour.png", 1, "png", harbour, SITE)
    got = exchange(run, chat, line, [T, download_cases.fetching("harbour.png", SITE), kept], timeout=180)
    meant.line(line, [], [])
    if kept not in got:
        # Without the picture kept, every line after this one would only wait in vain: the scenario ends here.
        run.end()
        return
    files = [listed(1, "harbour.png", "png", harbour)]
    kept_files = {1: ("png", harbour)}

    # Opened: shown in the frame as document 1, kept as made from file 1. Nothing of it goes to the model, and the
    # line ends.
    line = "show me the picture"
    lines = model.picture_lines(1, "harbour.png")
    laid, _, whole = model.written(lines, kept_files, 2)
    report("fetch the picture is meant whole, shrunk to 554 by 416", whole and laid["pages"][0][0][2:4] == (554, 416),
           "%r" % (laid["pages"][0][0][:4],))
    opened = dict(number=1, version=1, name="harbour.png", lines=lines, kind=KIND_TEXT)
    exchange(run, chat, line, [T, model.opened_row(1, "harbour.png", 640, 480, 1), holds(laid)])
    ends(run, "fetch open")
    meant.line(line, files, [])
    run.shot("opened", meant_screen(chat, [opened], 1))

    # A caption and a paragraph by a wish: the whole document written again, its second version.
    line = "put a caption under it"
    written = cases.text("caption", 1)
    laid, said, whole = model.written(written, kept_files, 2)
    captioned = document(1, 2, written)
    exchange(run, chat, line, [T, kept_row(said, 1, changed=True), holds(laid)])
    ends(run, "fetch caption")
    meant.line(line, files, [opened], opened)
    run.shot("caption", meant_screen(chat, [captioned], 1))

    # The kernel's own lines over the screen (F1), and a key that brings the usual picture back: the picture is painted
    # again from the dots kept.
    run.m.named_key("f1", pause=1)
    run.m.named_key("backspace", pause=1)
    run.shot("after-f1", meant_screen(chat, [captioned], 1))

    # Another look: the see-through half shows the new look's colour.
    line = "make it dark"
    exchange(run, chat, line, [T, NIGHT])
    chat.look, chat.look_kept = "Night", "Night"
    meant.line(line, files, [captioned], captioned)
    run.shot("night", meant_screen(chat, [captioned], 1))
    turn(run, chat, "pgdn", "page-down-one-page", [captioned], 1)
    lines_seen = run.end()
    meant.check("fetch", run)
    no_key_in("fetch", lines_seen)

    # After a restart, on the same disk, whose file and notes the kernel wrote itself: the picture's document is
    # listed, nothing is open, and the look kept is Night. Opening the picture again opens its document, read from the
    # file kept, and the line ends.
    again = start("pd-fetch-2", disk, ["openfile=1"])
    chat = new_chat(b"make it dark", kept_look=b"Night")
    give_key(again, chat)
    meant = Requests(chat)
    got = start_documents_lines(again.lines())
    wanted = ["Documents: 1 is kept on the disk:", "Documents: %s" % called(captioned)]
    report("fetch restart the start lists the picture's document", got == wanted, None if got == wanted else "got %r" % got)
    again.shot("restart", meant_screen(chat, [captioned], None))
    line = "open the picture again"
    laid, _, _ = model.written(captioned["lines"], kept_files, 2)
    exchange(again, chat, line, [T, model.reopened_row(captioned, 1, laid), holds(laid)])
    ends(again, "fetch restart open")
    meant.line(line, files, [captioned])
    again.shot("reopened", meant_screen(chat, [captioned], 1))

    # `setup`: the frame empties, and the first look comes back at once (docs/look.md).
    again.mark()
    again.press("setup\n", chat)
    asked = again.wait_line("Kernel: what should I call you?", timeout=30)
    report("fetch setup asks for the name", asked is not None, None if asked else "the question never came")
    chat.text = chat.table = None
    chat.look = "Blue"
    again.shot("setup", meant_screen(chat, [captioned], None))
    lines_seen = again.end()
    meant.check("fetch restart", again)
    check_notes("fetch", disk, {1: (model.note_from_picture(2, "Harbour", 1), 2, captioned["lines"])})
    found = read_things(disk)["things"]
    report("fetch document 1 v1", found.get("document 1 v1", (0, None))[1] == lines.encode())
    no_key_in("fetch restart", lines_seen)


def scenario_reopen():
    print("reopen: a picture's document opened again by its file, and a document that names a removed file")
    harbour = picture_files.picture("harbour")
    first = model.picture_lines(1, "harbour.png")
    second = ("title Pictures and a gap\ntext Two pictures follow; the file of the first was removed.\npicture 2 | removed\n"
              "picture 1 | The harbour, again")
    items = [("document 1 v1", first), ("document 1", model.note_from_picture(1, "harbour.png", 1)),
             ("document 2 v1", second), ("document 2", documents_model.note(1, "Pictures and a gap", KIND_TEXT))]
    disk, _ = answered_disk("pd-reopen", items)
    put_files(disk, [(1, "harbour.png", "png", harbour)])
    put_removed(disk, 2)
    run = start("pd-reopen", disk, ["openfile=1", "open=2"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    one = dict(number=1, version=1, name="harbour.png", lines=first, kind=KIND_TEXT)
    two = dict(number=2, version=1, name="Pictures and a gap", lines=second, kind=KIND_TEXT)
    got = start_documents_lines(run.lines())
    wanted = ["Documents: 2 are kept on the disk:", "Documents: %s" % called(two), "Documents: %s" % called(one)]
    report("reopen the start lists both documents", got == wanted, None if got == wanted else "got %r" % got)
    files = [listed(1, "harbour.png", "png", harbour)]
    kept_files = {1: ("png", harbour)}

    # The file opened again: its document opens, nothing goes to the model, and the line ends.
    line = "show me the harbour picture"
    laid, _, _ = model.written(first, kept_files, 3)
    exchange(run, chat, line, [T, model.reopened_row(one, 1, laid), holds(laid)])
    ends(run, "reopen file")
    meant.line(line, files, [two, one])
    run.shot("reopened", meant_screen(chat, [one, two], 1))

    # The other document: its picture of the removed file says so in its place and in the row, and it goes back.
    line = "open the other document"
    laid, _, whole = model.written(second, kept_files, 3)
    report("reopen the second document is meant on two pages, not whole", len(laid["pages"]) == 2 and not whole, "%d pages" % len(laid["pages"]))
    exchange(run, chat, line, [T, opened_row(two, model.opened_fit(laid)), holds(laid)] + back())
    meant.line(line, files, [one, two], one)
    meant.again(line, files, [two, one], two)
    run.shot("removed", meant_screen(chat, [two, one], 2))
    turn(run, chat, "pgdn", "second-page", [two, one], 2)
    lines_seen = run.end()
    meant.check("reopen", run)
    no_key_in("reopen", lines_seen)


def scenario_kinds():
    print("kinds: eight small pictures of most kinds a PNG has, four to a document, and another look")
    names = ["grey16", "pal4", "rgba16", "lace", "grey1", "greya8", "rgb16", "pieces"]
    disk, _ = answered_disk("pd-kinds")
    put_files(disk, [(number + 1, name + ".png", "png", picture_files.picture(name)) for number, name in enumerate(names)])
    kept_files = {number + 1: ("png", picture_files.picture(name)) for number, name in enumerate(names)}
    files = [listed(number + 1, name + ".png", "png", picture_files.picture(name)) for number, name in enumerate(names)][::-1]
    run = start("pd-kinds", disk, ["picdoc=kinds1:0", "picdoc=kinds2:0", "look=4"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    documents = []
    for number, (line, name) in enumerate([("show the first four kinds", "kinds1"), ("now the other four", "kinds2")], 1):
        written = cases.text(name, 0)
        laid, said, whole = model.written(written, kept_files, 9)
        report("kinds %s is meant whole on one page" % name, whole and len(laid["pages"]) == 1, said)
        kept = document(number, 1, written)
        exchange(run, chat, line, [T, kept_row(said, number), holds(laid)])
        ends(run, "kinds " + name)
        meant.line(line, files, documents, documents[0] if documents else None)
        documents.insert(0, kept)
        run.shot(name, meant_screen(chat, documents, number))

    line = "high contrast please"
    exchange(run, chat, line, [T, CONTRAST])
    chat.look, chat.look_kept = "Contrast", "Contrast"
    meant.line(line, files, documents, documents[0])
    run.shot("contrast", meant_screen(chat, documents, 2))
    lines_seen = run.end()
    meant.check("kinds", run)
    no_key_in("kinds", lines_seen)


def scenario_layout():
    print("layout: a wide picture after a paragraph, a tall one on a page of its own, and pictures that cannot be shown")
    tall, wide, small = (picture_files.picture(name) for name in ("tall", "wide", "small"))
    disk, _ = answered_disk("pd-layout")
    put_files(disk, [(1, "tall.png", "png", tall), (2, "wide.png", "png", wide), (4, "small.png", "png", small),
                     (5, "b.csv", "csv", download_cases.CSV)])
    kept_files = {1: ("png", tall), 2: ("png", wide), 4: ("png", small), 5: ("csv", download_cases.CSV)}
    files = [listed(5, "b.csv", "csv", download_cases.CSV), listed(4, "small.png", "png", small), listed(2, "wide.png", "png", wide),
             listed(1, "tall.png", "png", tall)]
    run = start("pd-layout", disk, ["picdoc=layout:0"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    line = "lay some pictures out"
    written = cases.text("layout", 0)
    laid, said, whole = model.written(written, kept_files, 6)
    report("layout is meant on three pages, three pictures not shown", len(laid["pages"]) == 3 and len(laid["not_shown"]) == 3 and not whole,
           said)
    kept = document(1, 1, written)
    exchange(run, chat, line, [T, kept_row(said, 1), holds(laid)] + back())
    meant.line(line, files, [])
    meant.again(line, files, [kept], kept)
    run.shot("page-1", meant_screen(chat, [kept], 1))
    turn(run, chat, "pgdn", "page-2", [kept], 1)
    turn(run, chat, "pgdn", "page-3", [kept], 1)
    turn(run, chat, "pgup", "page-2-again", [kept], 1)
    lines_seen = run.end()
    meant.check("layout", run)
    check_notes("layout", disk, {1: (documents_model.note(1, "Layout of pictures", KIND_TEXT), 1, kept["lines"])})
    no_key_in("layout", lines_seen)


def scenario_broken():
    print("broken: damaged pictures turned down with the reader's reasons, the frame as it was; then a good one")
    broken = list(picture_files.REFUSED)
    names = ["small"] + broken + ["pal4"]
    disk, _ = answered_disk("pd-broken")
    put_files(disk, [(number + 1, name + ".png", "png", picture_files.picture(name)) for number, name in enumerate(names)])
    kept_files = {number + 1: ("png", picture_files.picture(name)) for number, name in enumerate(names)}
    files = [listed(number + 1, name + ".png", "png", picture_files.picture(name)) for number, name in enumerate(names)][::-1]
    behaviours = ["openfile=%d" % (number + 1) for number in range(len(names))]
    run = start("pd-broken", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    line = "open the small one"
    lines = model.picture_lines(1, "small.png")
    laid, _, _ = model.written(lines, kept_files, len(names) + 1)
    small = dict(number=1, version=1, name="small.png", lines=lines, kind=KIND_TEXT)
    exchange(run, chat, line, [T, model.opened_row(1, "small.png", 20, 20, 1), holds(laid)])
    meant.line(line, files, [])

    # Each damaged picture: turned down with the reader's reason, and back to the model; the frame and the open
    # document stay as they were.
    for number, name in enumerate(broken, 2):
        line = "open %s" % name
        refused = model.not_opened_row(number, name + ".png", picture_files.REFUSED[name])
        got = exchange(run, chat, line, [T, refused] + back())
        meant.line(line, files, [small], small)
        meant.again(line, files, [small], small)
        if refused not in got:
            # A refusal that did not come leaves the stand-in's answers out of step with the lines, so every line
            # after it would only wait in vain: the scenario ends here.
            run.end()
            return
        if number == 2:
            run.shot("refused", meant_screen(chat, [small], 1))
    run.shot("all-refused", meant_screen(chat, [small], 1))

    # A good one after them all.
    number = len(names)
    line = "open the palette one"
    lines = model.picture_lines(number, "pal4.png")
    laid, _, _ = model.written(lines, kept_files, number + 1)
    pal = dict(number=2, version=1, name="pal4.png", lines=lines, kind=KIND_TEXT)
    exchange(run, chat, line, [T, model.opened_row(number, "pal4.png", 33, 21, 2), holds(laid)])
    meant.line(line, files, [small], small)
    run.shot("good-after", meant_screen(chat, [pal, small], 2))
    lines_seen = run.end()
    meant.check("broken", run)
    check_notes("broken", disk, {1: (model.note_from_picture(1, "small.png", 1), 1, model.picture_lines(1, "small.png")),
                                 2: (model.note_from_picture(1, "pal4.png", number), 1, lines)})
    no_key_in("broken", lines_seen)


def scenario_photos():
    print("photos: a JPEG photo fetched and kept, opened in the frame; photos and a PNG picture in a document; F1, another"
          " look; damaged photos turned down; after a restart with photos alone kept, the photo opened again")
    outside = ([("photoprog", "jpeg"), ("photogrey", "jpeg"), ("small", "png"), ("phototurned", "jpeg")]
               + [(name, "jpeg") for name in picture_files.PHOTOS_REFUSED])
    first_refused = 5
    names = [name + (".png" if kind == "png" else ".jpg") for name, kind in outside]
    disk, _ = answered_disk("pd-photos", [("site 1", SITE)])
    put_files(disk, [(number + 1, names[number], kind, picture_files.picture(name)) for number, (name, kind) in enumerate(outside)])
    kept_files = {number + 1: (kind, picture_files.picture(name)) for number, (name, kind) in enumerate(outside)}
    files = [listed(number + 1, names[number], kind, picture_files.picture(name)) for number, (name, kind) in enumerate(outside)][::-1]
    photo = picture_files.picture("photo")
    fetched = len(outside) + 1
    refused = list(picture_files.PHOTOS_REFUSED)
    behaviours = (["fetch=https://%s/pictures/photo.jpg" % SITE, "openfile=%d" % fetched, "picdoc=photos:0", "look=2"]
                  + ["openfile=%d" % (first_refused + place) for place in range(len(refused))])
    run = start("pd-photos", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The photo from the made-up site: kept as a JPEG photo, by its first bytes.
    line = "get the photo"
    kept = download_cases.kept("photo.jpg", fetched, "jpeg", photo, SITE)
    got = exchange(run, chat, line, [T, download_cases.fetching("photo.jpg", SITE), kept], timeout=180)
    meant.line(line, files, [])
    if kept not in got:
        # Without the photo kept, every line after this one would only wait in vain: the scenario ends here.
        run.end()
        return
    files = [listed(fetched, "photo.jpg", "jpeg", photo)] + files
    kept_files[fetched] = ("jpeg", photo)

    # Opened: shown in the frame as document 1, shrunk to fit, and the line ends.
    line = "show me the photo"
    lines = model.picture_lines(fetched, "photo.jpg")
    laid, _, whole = model.written(lines, kept_files, fetched + 1)
    report("photos the photo is meant whole, shrunk to 554 by 416", whole and laid["pages"][0][0][2:4] == (554, 416),
           "%r" % (laid["pages"][0][0][:4],))
    opened = dict(number=1, version=1, name="photo.jpg", lines=lines, kind=KIND_TEXT)
    exchange(run, chat, line, [T, model.opened_row(fetched, "photo.jpg", 1200, 900, 1, "a JPEG photo"), holds(laid)])
    ends(run, "photos open")
    meant.line(line, files, [])
    run.shot("opened", meant_screen(chat, [opened], 1))

    # A document of photos and a PNG picture: write_document names both kinds, and each is shown at its own size.
    line = "lay the photos out"
    written = cases.text("photos", 0)
    laid, said, whole = model.written(written, kept_files, fetched + 1)
    report("photos the document is meant whole", whole, said)
    laidout = document(2, 1, written)
    exchange(run, chat, line, [T, kept_row(said, 2), holds(laid)])
    ends(run, "photos document")
    meant.line(line, files, [opened], opened)
    run.shot("document", meant_screen(chat, [laidout, opened], 2))
    # Its other pages, the turned photo among them.
    for page in range(2, len(laid["pages"]) + 1):
        turn(run, chat, "pgdn", "document-page-%d" % page, [laidout, opened], 2)

    # F1 and a key: painted again from the dots kept; then another look.
    run.m.named_key("f1", pause=1)
    run.m.named_key("backspace", pause=1)
    run.shot("after-f1", meant_screen(chat, [laidout, opened], 2))
    line = "make it dark"
    exchange(run, chat, line, [T, NIGHT])
    chat.look, chat.look_kept = "Night", "Night"
    meant.line(line, files, [laidout, opened], laidout)
    run.shot("night", meant_screen(chat, [laidout, opened], 2))

    # Each damaged photo: turned down with the reader's reason, and back to the model; the frame and the open
    # document stay as they were.
    for place, name in enumerate(refused):
        line = "open %s" % name
        row = model.not_opened_row(first_refused + place, name + ".jpg", picture_files.PHOTOS_REFUSED[name])
        got = exchange(run, chat, line, [T, row] + back())
        meant.line(line, files, [laidout, opened], laidout)
        meant.again(line, files, [laidout, opened], laidout)
        if row not in got:
            # A refusal that did not come leaves the stand-in's answers out of step with the lines: the scenario ends.
            run.end()
            return
    run.shot("refused", meant_screen(chat, [laidout, opened], 2))
    lines_seen = run.end()
    meant.check("photos", run)
    no_key_in("photos", lines_seen)

    # After a restart on the same disk, the PNG picture (file 3) removed from outside, so that photos alone are kept:
    # open_file and write_document then say their words for photos alone; the photo opened again opens its document,
    # read from the file kept.
    put_removed(disk, 3)
    files = [(number, words) for number, words in files if number != 3]
    del kept_files[3]
    again = start("pd-photos-2", disk, ["openfile=%d" % fetched])
    chat = new_chat(("open %s" % refused[-1]).encode(), kept_look=b"Night")
    give_key(again, chat)
    meant = Requests(chat)
    line = "open the photo again"
    laid, _, _ = model.written(lines, kept_files, fetched + 1)
    exchange(again, chat, line, [T, model.reopened_row(opened, fetched, laid), holds(laid)])
    ends(again, "photos restart open")
    meant.line(line, files, [laidout, opened])
    again.shot("reopened", meant_screen(chat, [opened, laidout], 1))
    lines_seen = again.end()
    meant.check("photos restart", again)
    check_notes("photos", disk, {1: (model.note_from_picture(1, "photo.jpg", fetched), 1, lines),
                                 2: (documents_model.note(1, "Photos", KIND_TEXT), 1, laidout["lines"])})
    no_key_in("photos restart", lines_seen)


SCENARIOS = {
    "fetch": scenario_fetch,
    "reopen": scenario_reopen,
    "kinds": scenario_kinds,
    "layout": scenario_layout,
    "broken": scenario_broken,
    "photos": scenario_photos,
}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
