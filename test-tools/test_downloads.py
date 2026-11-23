"""Files fetched from the web and kept on the disk (docs/tools.md "download_file" and "remove_file", docs/network.md
"Fetching a file", docs/disk.md "The room for files"). Every scenario boots the stand-in copy of the project
(net_copy.py), in which every site's name leads to the stand-in on this computer (model_server.py), so no test reaches
a real site; the stand-in answers each line with the tool the scenario names (chat_cases.py) and each GET of a file as
download_cases.py says. What the kernel is meant to say comes from download_cases.py, written from the notes; every
GET the stand-in saw is compared with what the notes say is sent; the list of tools of every request for a line is
compared with chat_tools_model.py's; and the disk file is read from outside. Made-up key and made-up sites only.

  fetch     the thing this part is done by: a line asks for a file on a site not contacted before; the kernel asks;
            after "yes" the file comes through one redirect, is kept as file 1, and its note and its bytes on the disk
            are as the notes say; a second file from the same site asks nothing; after a restart the room's line
            counts both, and a third file from the same site asks nothing either.
  refusals  what is not fetched or not kept, each said in a sentence that goes back to the model: a packed file, one
            in pieces with their lengths, one too big by its length, a redirect to an address that is not encrypted,
            a loop, a sixth redirect, a 404, a web page, an unreadable length, a file cut short with and without a
            length, kinds that are not kept, addresses turned down before anything is sent, a site the person does
            not allow, a site that says nothing; then a redirect to a second site, asked about and allowed.
  remove    a kept file removed by a wish, after a "no" and then a "yes"; the next file takes its room; a file number
            that is not there.
  startlines  the room's line at a start: a part too small for it, a notebook that reaches into it, and a block where
            it begins that holds something else.
  full      a room with too little left in one piece for the file.

Usage: python test_downloads.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, download_breaks.py), BOOS_PORT_BASE (47300 for this lane)."""
import json
import os
import struct
import time
import zlib

os.environ["DIVIDED_DISK"] = ""

import chat_cases
import download_cases as cases
from apps_kept_model import read_things, write_notebook, ANSWERS
from chat_tools_model import tools_meant
from download_breaks import BREAKS
from net_copy import build
from nb import BLOCK, FIRST, LAST, put_block
from test_apps_kept import KEY, PORT, Run, answered_disk, count_line, failures, give_key, report

SITE, OTHER = cases.SITE, cases.OTHER
SHOWN = ("You:", "Kernel:", "Model:")
AGAIN = "Model: " + chat_cases.AGAIN_WORDS

# The room for files on the usual test disk: its head in the middle block of the kernel's part, files behind it up to
# the last but one block of the part (docs/disk.md).
PART = LAST - FIRST + 1
HEAD = PART // 2
ROOM_BLOCKS = (PART - 2) - HEAD

_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of download_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=(), network="open"):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel(), network=network)


def rows_since(run):
    return [line for line in run.since() if line.startswith(SHOWN)]


def wait_rows(run, meant, timeout):
    end = time.time() + timeout
    while time.time() < end and len(rows_since(run)) < len(meant):
        if run.m.process.poll() is not None:
            break
        time.sleep(0.05)
    # Whatever comes after the rows meant is wrong too.
    time.sleep(1.0)
    got = rows_since(run)
    report(run.tag + " %r" % meant[0][:44], got == meant, None if got == meant else "got %r, meant %r" % (got[-5:], meant[-5:]))


def line(run, text, rows, timeout=60):
    """Sends a line, which goes to the model, and compares the rows that follow with the person's row, the row said at
    once, and `rows`."""
    run.mark()
    run.press(text + "\n")
    wait_rows(run, ["You: " + text, "Kernel: I am asking the model."] + rows, timeout)


def answer(run, text, rows, timeout=60):
    """Answers a question of the kernel's, and compares the rows that follow."""
    run.mark()
    run.press(text + "\n")
    wait_rows(run, ["You: " + text] + rows, timeout)


def server_notes(run):
    with open(run.log) as handle:
        return [json.loads(text) for text in handle if text.strip()]


def check_gets(run, paths):
    """Every GET of a file the stand-in saw: in turn the paths meant, each to the site it names, asking for the file in
    HTTP/1.0 with exactly three notes: the site, the file unpacked, and the connection closed after it."""
    gets = [note for note in server_notes(run) if note.get("answered") == "a file"]
    seen = [note.get("first line") for note in gets]
    meant = ["GET %s HTTP/1.0" % path for _, path in paths]
    report(run.tag + " the GETs", seen == meant, None if seen == meant else "got %r, meant %r" % (seen, meant))
    for note, (site, path) in zip(gets, paths):
        notes = note.get("notes")
        wanted = {"host": site, "accept-encoding": "identity", "connection": "close"}
        good = notes == wanted and note.get("name asked for") == site
        report(run.tag + " GET %s" % path[:30], good, None if good else "got %r to %r" % (notes, note.get("name asked for")))


def check_tools(run, meant):
    """The list of tools of every request for a line, in turn: `meant` holds (whether anything is remembered, the kept
    files as the tool lists them) for each."""
    seen = [note for note in server_notes(run) if note.get("request for") == "a line" and note.get("tools offered")]
    report(run.tag + " requests with tools", len(seen) == len(meant), "%d seen, %d meant" % (len(seen), len(meant)))
    for number, (note, (remembered, files)) in enumerate(zip(seen, meant)):
        tools = (note.get("body") or {}).get("tools")
        wanted = tools_meant([], remembered=remembered, files=files)
        report(run.tag + " tools of request %d" % (number + 1), tools == wanted,
               None if tools == wanted else "got %r" % [tool["function"]["name"] for tool in tools or []])


def listed(number, name, kind, data):
    return (number, "%s, %s of %s" % (name, cases.KINDS[kind], cases.size_words(len(data))))


def head_block():
    body = b"boos files      " + struct.pack("<I", 1)
    return (body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)).ljust(BLOCK, b"\0")


def read_disk(disk, block, length):
    with open(disk, "rb") as handle:
        handle.seek((FIRST + block) * BLOCK)
        return handle.read(length)


def check_disk(tag, disk, files, sites, removed=()):
    """The disk file read from outside: the room's head, a note for each kept file as the notes say, its bytes where
    the note says, an empty note for each removed file, and the allowed sites in turn. Gives back where each file
    begins."""
    found = read_things(disk)["things"]
    report(tag + " the room's head", read_disk(disk, HEAD, BLOCK) == head_block())
    places = {}
    for number, (name, kind, data, address) in files.items():
        kept = found.get("file %d" % number)
        rows = kept[1].decode(errors="replace").split("\n") if kept else []
        blocks = -(-len(data) // BLOCK)
        try:
            first, count = [int(word) for word in rows[0].split(" ")[1:3]]
        except (IndexError, ValueError):
            first, count = None, None
        meant = ["blocks %s %d" % (first, blocks), "bytes %d" % len(data), "check %08x" % (zlib.crc32(data) & 0xFFFFFFFF),
                 "kind " + kind, "name " + name]
        good = (rows[:5] == meant and len(rows) == 8 and rows[5].startswith("date ") and rows[6] == "from " + address
                and rows[7] == "" and count == blocks and first is not None and HEAD < first and first + blocks - 1 <= PART - 2)
        report(tag + " note of file %d" % number, good, None if good else "got %r" % rows)
        if first is not None:
            places[number] = first
            on_disk = read_disk(disk, first, len(data))
            report(tag + " bytes of file %d" % number, on_disk == data)
    for number in removed:
        kept = found.get("file %d" % number)
        report(tag + " file %d removed" % number, kept is not None and kept[1] == b"")
    names = [found.get("site %d" % (place + 1), (None, None))[1] for place in range(len(sites))]
    meant = [site.encode() for site in sites]
    report(tag + " sites kept", names == meant and "site %d" % (len(sites) + 1) not in found, "got %r" % names)
    return places


def free_kb(datas, room=ROOM_BLOCKS):
    return (room - sum(-(-len(data) // BLOCK) for data in datas)) * BLOCK // 1024


def room_line(count, datas):
    kept = "1 file" if count == 1 else "%d files" % count
    return "Disk: the room for files holds %s and has room for %d KB more" % (kept, free_kb(datas))


def check_line(tag, lines, want):
    report(tag, want in lines, None if want in lines else "got %r" % [l for l in lines if l.startswith("Disk: ")])


# ---------- The scenarios ----------

def scenario_fetch():
    print("fetch: a file from a new site, asked about, through a redirect; a second and, after a restart, a third")
    disk, _ = answered_disk("dl-fetch")
    run = start("dl-fetch", disk, ["fetch=https://%s/go/a.pdf" % SITE, "fetch=https://%s/b.csv" % SITE])
    give_key(run)
    line(run, "get https://%s/go/a.pdf" % SITE, cases.new_site("a.pdf", SITE))
    answer(run, "yes", [cases.fetching("a.pdf", SITE), cases.kept("a.pdf", 1, "pdf", cases.PDF, SITE)])
    line(run, "get https://%s/b.csv" % SITE, [cases.fetching("b.csv", SITE), cases.kept("b.csv", 2, "csv", cases.CSV, SITE)])
    lines = run.end()
    check_line("fetch the notebook's room", lines, count_line(len(ANSWERS)))
    check_line("fetch the room's line", lines, room_line(0, []))
    hops = [l for l in lines if l.startswith("Download: ")]
    meant = ["Download: https://%s/go/a.pdf: sent on to ../a.pdf" % SITE,
             "Download: https://%s/a.pdf: the file, %d bytes, whole" % (SITE, len(cases.PDF)),
             "Download: https://%s/b.csv: the file, %d bytes, whole" % (SITE, len(cases.CSV))]
    report("fetch the terminal's lines about hops", hops == meant, None if hops == meant else "got %r" % hops)
    check_gets(run, [(SITE, "/go/a.pdf"), (SITE, "/a.pdf"), (SITE, "/b.csv")])
    check_tools(run, [(False, []), (True, [listed(1, "a.pdf", "pdf", cases.PDF)])])
    files = {1: ("a.pdf", "pdf", cases.PDF, "https://%s/a.pdf" % SITE), 2: ("b.csv", "csv", cases.CSV, "https://%s/b.csv" % SITE)}
    check_disk("fetch", disk, files, [SITE])

    again = start("dl-fetch-2", disk, ["fetch=https://%s/c.docx" % SITE])
    give_key(again)
    line(again, "get https://%s/c.docx" % SITE, [cases.fetching("c.docx", SITE), cases.kept("c.docx", 3, "docx", cases.DOCX, SITE)])
    lines = again.end()
    check_line("fetch restart the room's line", lines, room_line(2, [cases.PDF, cases.CSV]))
    check_tools(again, [(False, [listed(2, "b.csv", "csv", cases.CSV), listed(1, "a.pdf", "pdf", cases.PDF)])])
    check_gets(again, [(SITE, "/c.docx")])
    files[3] = ("c.docx", "docx", cases.DOCX, "https://%s/c.docx" % SITE)
    check_disk("fetch restart", disk, files, [SITE])


def scenario_refusals():
    print("refusals: what is not fetched or kept, and a redirect to a second site")
    disk, _ = answered_disk("dl-refusals", [("site 1", SITE)])
    behaviours = ["fetch=https://%s%s" % (SITE, path) for path, _ in cases.REFUSALS]
    behaviours += ["fetch=" + address for address, _ in cases.BAD_ADDRESSES]
    behaviours += ["fetch=https://%s/e.pdf" % OTHER, "fetch=https://%s/silent.pdf" % SITE, "fetch=https://%s/d.xlsx" % SITE]
    run = start("dl-refusals", disk, behaviours)
    give_key(run)
    gets = []
    for path, row in cases.REFUSALS:
        name = path.rsplit("/", 1)[1]
        line(run, "fetch " + path[:40], [cases.fetching(name, SITE), row(), AGAIN])
        if path == "/loop/1":
            gets += [(SITE, "/loop/1"), (SITE, "/loop/2")]
        elif path == "/hops/1":
            gets += [(SITE, "/hops/%d" % hop) for hop in range(1, 7)]
        else:
            gets.append((SITE, path))
    for address, why in cases.BAD_ADDRESSES:
        line(run, "fetch that one", [cases.address_refused(address, why), AGAIN])
    line(run, "fetch e from the other site", cases.new_site("e.pdf", OTHER))
    answer(run, "no", [cases.not_allowed(OTHER)])
    line(run, "fetch the silent one", [cases.fetching("silent.pdf", SITE),
                                       cases.not_fetched("silent.pdf", SITE, "no answer came: the site took too long"), AGAIN], timeout=60)
    gets.append((SITE, "/silent.pdf"))
    line(run, "fetch d", [cases.fetching("d.xlsx", SITE)] + cases.sent_to_new(SITE, OTHER))
    answer(run, "yes", [cases.kept("d.xlsx", 1, "xlsx", cases.XLSX, OTHER)])
    gets += [(SITE, "/d.xlsx"), (OTHER, "/sheets/d.xlsx")]
    run.end()
    check_gets(run, gets)
    # Every request: a line, and an ask again after each refusal; nothing kept until the last.
    asks = len(cases.REFUSALS) * 2 + len(cases.BAD_ADDRESSES) * 2 + 1 + 2 + 1
    check_tools(run, [(number > 0, []) for number in range(asks)])
    check_disk("refusals", disk, {1: ("d.xlsx", "xlsx", cases.XLSX, "https://%s/sheets/d.xlsx" % OTHER)}, [SITE, OTHER])


def scenario_remove():
    print("remove: a kept file removed after a no and a yes, its room taken by the next")
    disk, _ = answered_disk("dl-remove", [("site 1", SITE)])
    run = start("dl-remove", disk, ["fetch=https://%s/a.pdf" % SITE, "remove=1", "remove=1", "fetch=https://%s/c.docx" % SITE, "remove=7"])
    give_key(run)
    line(run, "get a", [cases.fetching("a.pdf", SITE), cases.kept("a.pdf", 1, "pdf", cases.PDF, SITE)])
    asked = 'Kernel: remove file 1, "a.pdf", for good? Type yes to remove it; anything else keeps it.'
    line(run, "remove it", [asked])
    answer(run, "no", ['Kernel: I kept file 1, "a.pdf".'])
    line(run, "remove it after all", [asked])
    answer(run, "yes", ['Kernel: I removed file 1, "a.pdf".'])
    line(run, "get c", [cases.fetching("c.docx", SITE), cases.kept("c.docx", 2, "docx", cases.DOCX, SITE)])
    line(run, "remove seven", ["Kernel: the model asked to remove file 7, but no kept file has that number.", AGAIN])
    run.end()
    a = listed(1, "a.pdf", "pdf", cases.PDF)
    c = listed(2, "c.docx", "docx", cases.DOCX)
    check_tools(run, [(False, []), (True, [a]), (True, [a]), (True, []), (True, [c]), (True, [c])])
    places = check_disk("remove", disk, {2: ("c.docx", "docx", cases.DOCX, "https://%s/c.docx" % SITE)}, [SITE], removed=[1])
    report("remove the next file takes the room", places.get(2) == HEAD + 1, "file 2 begins at %r" % places.get(2))
    again = start("dl-remove-2", disk, network=False)
    lines = again.end()
    check_line("remove restart the room's line", lines, room_line(1, [cases.DOCX]))


def scenario_startlines():
    print("startlines: no room for files, for three reasons")
    small = 4000
    disk, last = answered_disk("dl-small", blocks=small)
    lines = start("dl-small", disk, network=False).end()
    check_line("startlines a small part", lines, "Disk: no room for files, because my part is too small for it")
    check_line("startlines a small part's notebook", lines, count_line(len(ANSWERS), last))

    blocks = 4096
    filler = [("x %d" % number, b"") for number in range(blocks // 2 - 8 - len(ANSWERS))]
    disk, last = answered_disk("dl-reaches", filler, blocks=blocks)
    lines = start("dl-reaches", disk, network=False).end()
    check_line("startlines a notebook that reaches in", lines, "Disk: no room for files, because the notebook reaches into it")
    entries = len(ANSWERS) + len(filler)
    check_line("startlines its notebook keeps its room", lines,
               "Disk: the notebook holds %d entries and has room for %d more" % (entries, blocks - 2 - entries))

    disk, last = answered_disk("dl-other", blocks=blocks)
    put_block(disk, blocks // 2, b"something else".ljust(BLOCK, b"\0"))
    lines = start("dl-other", disk, network=False).end()
    check_line("startlines a block that holds something else", lines,
               "Disk: no room for files, because the block where it begins holds something I do not know")


def scenario_full():
    print("full: too little room left in one piece")
    free = 10
    taken = ROOM_BLOCKS - free
    big = "blocks %d %d\nbytes %d\ncheck 00000000\nkind pdf\nname big.pdf\ndate unknown\nfrom https://%s/big.pdf\n" % (
        HEAD + 1, taken, taken * BLOCK, SITE)
    disk, _ = answered_disk("dl-full", [("site 1", SITE), ("file 1", big)])
    put_block(disk, HEAD, head_block())
    run = start("dl-full", disk, ["fetch=https://%s/a.pdf" % SITE])
    give_key(run)
    why = "the room for files has %s free in one piece, and the file is %s" % (cases.size_words(free * BLOCK), cases.size_words(len(cases.PDF)))
    line(run, "get a", [cases.fetching("a.pdf", SITE), cases.not_kept("a.pdf", SITE, why), AGAIN])
    lines = run.end()
    check_line("full the room's line", lines, "Disk: the room for files holds 1 file and has room for %d KB more" % (free * BLOCK // 1024))
    report("full nothing written behind the big file", read_disk(disk, HEAD + 1 + taken, free * BLOCK) == bytes(free * BLOCK))


SCENARIOS = {
    "fetch": scenario_fetch,
    "refusals": scenario_refusals,
    "remove": scenario_remove,
    "startlines": scenario_startlines,
    "full": scenario_full,
}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
