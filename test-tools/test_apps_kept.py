"""Apps kept on the disk, and the panel of apps (docs/apps.md, "Keeping an app" and "The panel of apps";
docs/notebook.md, "A thing in pieces"). Every scenario boots the stand-in copy of the project (net_copy.py), so that a
break on purpose (apps_kept_breaks.py, through BREAK) reaches all of them; the copy's edits point its network at the
stand-in and touch neither the notebook nor the apps. What is meant comes from apps_kept_model.py, written from the
notes, and the disk file is read from outside with Python's own CRC-32. Made-up key only. Every line goes to the model
(docs/tools.md): the stand-in (model_server.py) answers a line such as "make a dice" with the tool make_app and the
request that follows "make ", and then the request for the app with the kind of answer the scenario names.

  first     as a person's first run in a new folder goes: a fresh disk, the questions of the onboarding (a name,
            Enter alone at the key and at the look), `key`, `make`, and a restart: its lines and every dot.
  make      apps made with `make` are kept: the rows, the terminal, a picture with the panel once the first is kept,
            and the notebook read from outside, byte for byte; an app that was stopped is not kept; the same request
            again takes the kept one's place. Then a restart: the lines, and every dot of the panel.
  echo      an app whose script holds the key: kept with stars; no piece of the key on the disk or in the terminal.
  outside   a notebook written from outside: apps in one entry and in pieces at every edge (448, 449, 896, 897 and
            32768 bytes), two pages of them, and things that must not count, each under an app's note; the lines, the
            panel, and the count of entries, which pieces never change.
  requests  notes from outside with signs that are not plain, a long request, another form, no request, names that
            belong to no app, and the highest number: a new app then cannot be numbered, while an app made for the
            request of a note without a script takes that note's number.
  look      the panel in a kept look, painted again when the model picks another look, and in that look after a restart.
  small     a screen of 800 by 600 dots.
  damaged   a damaged notebook: its apps are listed, nothing is written.
  full      a part with room for the script but not for the note, and one without room for the script.
  failing   a disk that refuses to write the third piece: the row, and the next line is not written over a piece.
  cut       QEMU killed at a random moment while a long app is kept, round after round on one disk.
  older     the kernel from before pieces (commit OLDER) on a disk with kept apps: it opens the notebook, greets and
            keeps a line; then this kernel lists the apps as before.
  times     how long keeping takes, for one entry and for 74 pieces, and how long opening a notebook with many pieces
            and the start up to the prompt take, against as many entries of one block each.

Usage: python test_apps_kept.py [scenario ...]        (with none: all but "older" and "times")
Environment: BREAK (a break on purpose, apps_kept_breaks.py), BOOS_PORT_BASE (47300 for this lane)."""
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile
import time

# Every disk is made here and given to QEMU with disk=False; no tool may make a divided one by itself.
os.environ["DIVIDED_DISK"] = ""

import app_cases
import chat_cases
from apps_kept_breaks import BREAKS
from chat_tools_breaks import BREAKS as TOOL_BREAKS
from chat_tools_model import NO_KEY, ToolsChat, making
from apps_kept_model import (ANSWERS, MakeChat, app_things, apps_of, kept_line, kept_script, not_kept_row, note,
                             pieces_of, raw, read_things, screen, start_lines, write_notebook, crc)
from boot import HERE, PROJECT, RUNS, Machine
from certs import test_keys
from disk_helpers import make, one_disk
from gpt import BOOS, build as divide
from keyed_model import KeyedChat
from nb import BLOCK, FIRST, LAST
from net_copy import build
from onboard_model import name_of
from picture import compare, to_png
from places import WASM
from ports import standin_port
from verdict import Failures

PORT = standin_port(5)
KEY = "sk-orca-TEST_Kp4m/Wz7+Qa2Rt8Vc5Nx3=="
OLDER = "7f3ac2e"          # the kernel from before things in pieces and kept apps
SCRIPT = app_cases.SCRIPT.strip().encode()
EXACT = app_cases.EXACT.encode()
failures = Failures()
_copy = []


def report(what, ok, text=None):
    print("  %-46s %s" % (what, text if text is not None else ("as meant" if ok else "NOT AS MEANT")), flush=True)
    if not ok:
        failures.append(what)


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of apps_kept_breaks.py or
    chat_tools_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        catalogue = dict(BREAKS, **TOOL_BREAKS)
        _copy.append(build(PORT, roots=["a"], more=catalogue[name] if name else None))
    return _copy[0]


def answered_disk(tag, items=(), blocks=None, answers=ANSWERS):
    """A divided test disk whose notebook holds the answers about the name, the key and the look, so that a start
    asks nothing, and then `items` (see apps_kept_model.write_notebook). `blocks`: the size of the kernel's part,
    when it is not the usual. Gives back the disk file's path and the part's last block."""
    path = make(tag + ".img", "16M")
    last = LAST if blocks is None else FIRST + blocks - 1
    divide(path, parts=None if blocks is None else [(BOOS, FIRST, last, "boos")])
    write_notebook(path, list(answers) + list(items))
    return path, last


class Run:
    """One start of the stand-in copy (or of `kernel_file`) with a disk of its own. With network "open" the stand-in
    answers the questions to the model with `behaviours`, in turn."""

    def __init__(self, tag, disk, behaviours=(), width=1280, height=800, extra=None, kernel_file=None, network="open", drive=None):
        self.tag, self.width, self.height = tag, width, height
        self.server = None
        if network == "open":
            tls = test_keys()
            self.log = os.path.join(RUNS, tag + "-server.log")
            if os.path.exists(self.log):
                os.remove(self.log)
            self.server = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT),
                                            os.path.join(tls, "a", "both-chain.pem"), os.path.join(tls, "a", "both.key"), self.log,
                                            json.dumps(list(behaviours))], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE)
            assert self.server.stdout.readline().strip() == "ready"
        try:
            self.m = Machine(tag, extra=(drive if drive is not None else one_disk(disk)) + (extra or []), disk=False, network=network,
                             kernel=kernel_file or kernel())
        except Exception:
            # A stand-in left behind would answer the next run on the same ports.
            if self.server:
                self.server.kill()
            raise
        self.at = 0
        if not self.m.wait_for(b"repeated here:", 200):
            print(self.m.serial().decode(errors="replace")[-3000:])
            self.end()
            report(tag + " start", False, "THE PROMPT NEVER CAME")
            print("FAILURES: %s" % failures)
            raise SystemExit(1)
        if network == "open" and not self.wait_line("Network: this machine was given the address", timeout=60, everything=True):
            report(tag + " address", False, "NO ADDRESS")

    def lines(self):
        """The kernel's whole lines so far."""
        raw_bytes = self.m.serial()
        begin = raw_bytes.find(b"Hello from my kernel!")
        return raw_bytes[max(begin, 0):].decode(errors="replace").split("\r\n")[:-1]

    def mark(self):
        self.at = len(self.lines())

    def since(self):
        return self.lines()[self.at:]

    def wait_line(self, *starts, timeout=90, everything=False):
        """Waits for a line that begins with one of `starts`, after the mark (or anywhere); gives it back, or None."""
        end = time.time() + timeout
        while time.time() < end:
            for line in (self.lines() if everything else self.since()):
                if line.startswith(starts):
                    return line
            if self.m.process.poll() is not None:
                break
            time.sleep(0.05)
        return None

    def press(self, text, chat=None):
        for sign in text:
            name = name_of(sign)
            self.m.command("sendkey %s 20" % name)
            time.sleep(0.25 if name.startswith("shift-") else 0.2)
            if chat is not None:
                chat.key(sign)

    def shot(self, name, meant):
        """A picture compared dot for dot; saved again, up to four more times half a second apart, in case it was
        taken in the middle of painting."""
        time.sleep(0.7)
        wrong, places, path = -1, [], None
        for _ in range(5):
            path = self.m.shot(name)
            wrong, places = compare(path, meant)
            if wrong == 0:
                break
            time.sleep(0.5)
        report(self.tag + " " + name, wrong == 0, "every dot right" if wrong == 0 else "%s dots wrong %s" % (wrong, places[:2]))
        if wrong:
            to_png(path, path[:-4] + ".png")

    def end(self, kill=False):
        """Ends the machine and the stand-in. Gives back the kernel's lines; reports bytes that are not plain text, a
        panic and a fault."""
        if kill:
            self.m.process.kill()
            self.m.process.wait()
            try:
                self.m.monitor.close()
            except OSError:
                pass
            raw_bytes = self.m.serial()
        else:
            raw_bytes = self.m.quit()
        if self.server:
            self.server.kill()
        ours = raw_bytes[max(raw_bytes.find(b"Hello from my kernel!"), 0):]
        lines = ours.decode(errors="replace").split("\r\n")
        odd = [b for b in ours if not (32 <= b <= 126 or b in (13, 10))]
        bare = ours.replace(b"\r\n", b"")
        if odd or b"\r" in bare or b"\n" in bare:
            report(self.tag + " plain text", False, "bytes that are not plain text, or stray line ends")
        if any(l.startswith(("Kernel panic", "CPU fault")) for l in lines):
            report(self.tag + " panic", False, "A PANIC OR A FAULT: %s" % [l for l in lines if l.startswith(("Kernel panic", "CPU fault"))][:1])
        return lines


def apps_lines(lines):
    """The lines that begin with "Apps:" from the start, before the prompt."""
    hint = next((i for i, l in enumerate(lines) if l.startswith("The processor rested")), len(lines))
    return [l for l in lines[:hint] if l.startswith("Apps:")]


def count_line(entries, last=LAST):
    room = (last - FIRST + 1) - 2 + 1 - (entries + 1)
    return "Disk: the notebook holds %d %s and has room for %d more" % (entries, "entry" if entries == 1 else "entries", room)


def check_start(tag, lines, things, last=LAST, entries=None, damaged=False):
    """The lines of a start about the notebook and the apps, against the notebook read from outside."""
    meant = start_lines(apps_of(things))
    got = apps_lines(lines)
    report(tag + " lines about apps", got == meant, None if got == meant else "got %r, meant %r" % (got[:6], meant[:6]))
    if entries is not None:
        if damaged:
            want = "Disk: the notebook holds %d %s and is damaged behind that; nothing is added to it" % (entries, "entry" if entries == 1 else "entries")
        else:
            want = count_line(entries, last)
        report(tag + " count of entries", want in lines, None if want in lines else "meant %r, got %r" % (want, [l for l in lines if l.startswith("Disk: the notebook")]))
    # The lines about apps come after the rows of the chat box, before the prompt.
    if got:
        place = lines.index(got[0])
        rows = [i for i, l in enumerate(lines[:place]) if l.startswith("Kernel:")]
        disk = [i for i, l in enumerate(lines) if l.startswith("Disk:")]
        report(tag + " lines in place", bool(disk) and place > max(disk) and (not rows or place > max(rows)))
    return [request for _, request, whole in apps_of(things) if whole]


def run_row(kind):
    return "Kernel: " + app_cases.run_expect(kind, KEY)[0]


def answer_row(kind):
    return "Kernel: " + app_cases.outcome(kind, KEY)[0]


def give_key(run, chat=None):
    run.mark()
    run.press("key\n", chat)
    run.press(KEY + "\n", chat)
    if not run.wait_line("Kernel: I took a secret of", timeout=30):
        report(run.tag + " key", False, "the key was not taken")


def asked_again(run, chat=None, timeout=60):
    """Waits for the model's words after a new app: what came of it goes back to the model, which is asked about the
    line again (docs/tools.md), and the stand-in answers with chat_cases.AGAIN_WORDS. A next line must wait for them,
    or it is turned away. The chat model gets the row; what the kernel remembers is not followed here, since no
    request for a line is judged in this file (test_chat_tools.py judges them)."""
    words = "Model: " + chat_cases.AGAIN_WORDS
    found = run.wait_line(words, timeout=timeout)
    report(run.tag + " asked again", found == words, None if found == words else "the words of the second ask never came")
    if chat is not None:
        chat.row(words)


def make_app(run, request, kind, kept, chat=None):
    """Sends "make" and a request as a line; the stand-in answers it with the tool make_app and that request. Waits
    for the row about asking for the app, the rows of the answer and the run, for the line that says the app is
    kept, or for none, and for the model's words when it is asked about the line again. Gives back the App lines of
    the run."""
    run.mark()
    run.press("make " + request + "\n", chat)
    asked = run.wait_line("Kernel: I am asking the model to make", "Kernel: I cannot ask", "Kernel: the model asked", timeout=90)
    report(run.tag + " tool for %r" % request[:20], asked == making(request), None if asked == making(request) else "got %r" % asked)
    first = run.wait_line("Kernel: the model", "Kernel: the provider", "Kernel: no answer", timeout=120)
    report(run.tag + " answer to %r" % request[:20], first == answer_row(kind), None if first == answer_row(kind) else "got %r" % first)
    second = run.wait_line("Kernel: the app ", timeout=30)
    report(run.tag + " run of %r" % request[:20], second == run_row(kind), None if second == run_row(kind) else "got %r" % second)
    if kept:
        line = run.wait_line("Apps: ", timeout=30)
        report(run.tag + " kept %r" % request[:20], line == kept_line(request), None if line == kept_line(request) else "got %r" % line)
    else:
        time.sleep(2.5)
        extra = [l for l in run.since() if l.startswith("Apps: ") or l.startswith("Kernel: I could not keep the app")]
        report(run.tag + " not kept %r" % request[:20], not extra, None if not extra else "got %r" % extra)
    if chat is not None:
        chat.row(making(request))
        chat.say(app_cases.outcome(kind, KEY)[0])
        chat.say(app_cases.run_expect(kind, KEY)[0])
    asked_again(run, chat)
    return [l for l in run.since() if l.startswith("App: ")]


def check_notebook(tag, disk, before, added, last=LAST):
    """The notebook read from outside: the entries that were there are unchanged, the ones added are `added` (names,
    in order), and nothing lies behind the end. Gives back what was read."""
    after = read_things(disk, last=last)
    old = before["entries"]
    same = after["entries"][:len(old)] == old
    names = [e[0] for e in after["entries"][len(old):]]
    report(tag + " earlier entries unchanged", same)
    report(tag + " entries added", names == added, None if names == added else "got %r, meant %r" % (names[:12], added[:12]))
    report(tag + " nothing behind the end", not after["behind"], None if not after["behind"] else "%r" % after["behind"][:4])
    return after


# ---------- Scenarios ----------

MAKES = [  # (request, the stand-in's answer, whether the app is kept)
    ("a dice that rolls", "app", True),
    ("the real dice of the model", "runreal", True),
    ("a long app of comments", "appexact", True),
    ("an app with a mistake", "runmistake", False),
    ("a dice that rolls", "runshow", True),
]


FIRST_NAME = "Ada"


def scenario_first():
    print("first: as a person's first run in a new folder goes, then a restart")
    disk = make("kept-first.img", "16M")
    divide(disk)
    run = Run("kept-first", disk, behaviours=["app"])
    run.mark()
    run.press(FIRST_NAME + "\n")
    report("first question for the key", run.wait_line("Kernel: type the key and press Enter.", timeout=30) is not None)
    run.press("\n")
    report("first no key kept", run.wait_line("Kernel: then no key is kept.", timeout=30) is not None)
    report("first question for a look", run.wait_line("Kernel: pick a look by number", timeout=30) is not None)
    run.press("\n")
    report("first look 1 stays", run.wait_line("Kernel: look 1, Blue, stays.", timeout=30) is not None)
    give_key(run)
    make_app(run, "a dice that rolls", "app", True)
    run.end()
    after = read_things(disk)
    things = after["things"]
    report("first script byte for byte", things.get("app 1 script", (0, b""))[1] == kept_script("app", KEY))
    report("first note", things.get("app 1", (0, b""))[1] == note("a dice that rolls"))
    again = Run("kept-first-again", disk)
    chat = KeyedChat(1280, kept_name=FIRST_NAME.encode(), key_entry=b"", kept_look=b"", last_line=b"make a dice that rolls")
    again.shot("start", screen(1280, 800, chat, ["a dice that rolls"]))
    lines = again.end()
    check_start("first restart", lines, things, entries=after["end"] - 1)


def scenario_make():
    print("make: apps made with `make` are kept, and listed after a restart")
    disk, last = answered_disk("kept-make")
    before = read_things(disk)
    run = Run("kept-make", disk, behaviours=[kind for _, kind, _ in MAKES])
    chat = MakeChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    added = ["last line"]
    numbers = {}
    for place, (request, kind, kept) in enumerate(MAKES):
        app_lines = make_app(run, request, kind, kept, chat)
        added.append("last line")
        if kept:
            new = request not in numbers
            number = numbers.setdefault(request, len(numbers) + 1)
            script = kept_script(kind, KEY)
            added += ["app %d script" % number] * (1 if len(script) <= 448 else -(-len(script) // 448))
            if new:
                added.append("app %d" % number)
        if place == 0:
            # The first app kept: the panel appears, with the dice the app showed in the box in the middle.
            shown = app_cases.run_expect(kind, KEY)[2](app_lines)
            run.shot("first-kept", screen(1280, 800, chat, ["a dice that rolls"], panel_text=shown[0] if shown else ""))
    run.end()
    after = check_notebook("make", disk, before, added)
    things = after["things"]
    for request, kind, kept in MAKES:
        if not kept:
            continue
        number = numbers[request]
        meant_script = kept_script("runshow" if request == "a dice that rolls" else kind, KEY)
        got = things.get("app %d script" % number, (0, b""))[1]
        report("make script of app %d, byte for byte" % number, got == meant_script, None if got == meant_script else "%d bytes, meant %d" % (len(got), len(meant_script)))
        got_note = things.get("app %d" % number, (0, b""))[1]
        report("make note of app %d" % number, got_note == note(request))
    report("make the longest script in 74 pieces", sum(1 for e in after["entries"] if e[0] == "app 3 script") == 74)
    apps = apps_of(things)
    meant_apps = [(1, "a dice that rolls", True), (3, "a long app of comments", True), (2, "the real dice of the model", True)]
    report("make the outside reader's apps", apps == meant_apps, None if apps == meant_apps else "%r" % apps)

    again = Run("kept-make-again", disk)
    chat2 = KeyedChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=b"make a dice that rolls")
    again.shot("start", screen(1280, 800, chat2, [r for _, r, w in apps if w]))
    lines = again.end()
    check_start("make restart", lines, things, entries=after["end"] - 1)
    third = read_things(disk)
    report("make restart wrote nothing", third["entries"] == after["entries"])


def scenario_echo():
    print("echo: an app whose script holds the key")
    disk, last = answered_disk("kept-echo")
    run = Run("kept-echo", disk, behaviours=["appecho"])
    give_key(run)
    make_app(run, "an app that knows the key", "appecho", True)
    raw_bytes = "\n".join(run.end())
    things = read_things(disk)["things"]
    script = things.get("app 1 script", (0, b""))[1]
    report("echo script kept with stars", script == kept_script("appecho", KEY) and b"*" * len(KEY) in script)
    pieces = [KEY[i:i + 6].encode() for i in range(len(KEY) - 5)]
    data = open(disk, "rb").read()
    report("echo no piece of the key on the disk", not any(p in data for p in pieces))
    report("echo no piece of the key in the terminal", not any(p.decode() in raw_bytes for p in pieces))


def edge(length, mark):
    """A script of exactly `length` bytes: a comment, then a show."""
    tail = '\nshow("%s")' % mark
    return ("-- " + "x" * length)[:length - len(tail)].encode() + tail.encode()


def outside_items():
    """Apps from outside at every edge, and things in pieces that must not count, each under an app's note."""
    s448, s449, s896, s897 = edge(448, "a"), edge(449, "b"), edge(896, "c"), edge(897, "d")
    items = []
    for number, (request, script) in enumerate([("exactly one entry", s448), ("one byte more", s449), ("two full pieces", s896),
                                                ("three pieces", s897), ("the longest script", EXACT), ("a small app", SCRIPT),
                                                ("a seventh app", b'show("7")')], 1):
        items += app_things(number, request, script)

    def as_pieces(name, data, order=None, change=None):
        parts = pieces_of(data)
        if order:
            parts = [parts[i] for i in order]
        return [raw(name, chunk, *(change(piece, pieces, whole) if change else (piece, pieces, whole))) for piece, pieces, whole, chunk in parts]

    odd = []
    # 8: the last piece missing.
    odd.append((8, "a piece missing", [as_pieces("app 8 script", s896)[0]]))
    # 9: a check value of the whole that does not fit.
    odd.append((9, "a wrong check value", as_pieces("app 9 script", s897, change=lambda a, b, w: (a, b, w ^ 1))))
    # 10: the pieces out of order.
    odd.append((10, "pieces out of order", as_pieces("app 10 script", s896, order=[1, 0])))
    # 11: an entry of another name between two pieces.
    eleven = as_pieces("app 11 script", edge(1344, "e"))
    odd.append((11, "a stranger between pieces", [eleven[0], raw("between", b"in between"), eleven[1], eleven[2]]))
    # 12: one piece of one.
    small = b'show("one of one")'
    odd.append((12, "one piece of one", [raw("app 12 script", small, 1, 1, crc(small))]))
    # 13: a piece numbered 0.
    odd.append((13, "a piece numbered 0", as_pieces("app 13 script", s896, change=lambda a, b, w: (0 if a == 1 else a, b, w))))
    # 14: a piece past the count.
    odd.append((14, "a piece past the count", as_pieces("app 14 script", s896, change=lambda a, b, w: (3 if a == 2 else a, b, w))))
    # 15: a piece before the last that is not full.
    s500 = edge(500, "f")
    odd.append((15, "a short piece in front", [raw("app 15 script", s500[:400], 1, 2, crc(s500)), raw("app 15 script", s500[400:], 2, 2, crc(s500))]))
    # 16: an empty last piece.
    odd.append((16, "an empty last piece", [raw("app 16 script", s448, 1, 2, crc(s448)), raw("app 16 script", b"", 2, 2, crc(s448))]))
    # 17: 75 pieces, all full, the check value fitting.
    odd.append((17, "seventy-five pieces", as_pieces("app 17 script", b"y" * (75 * 448))))
    # 18: 74 pieces that hold more than 32 KB.
    odd.append((18, "more than 32 KB", as_pieces("app 18 script", b"z" * (73 * 448 + 100))))
    # 19: four pieces whose data lies in its right order, but the second and third say they are the third and the
    # second: put together as they lie, the check value of the whole fits, and only the numbers show the fault.
    odd.append((19, "pieces numbered out of order", as_pieces("app 19 script", edge(1500, "h"), change=lambda a, b, w: ({2: 3, 3: 2}.get(a, a), b, w))))
    for number, request, blocks in odd:
        items += [blocks, ("app %d" % number, note(request))]
    # 20: an older whole script, then a newer one that never got finished: the older counts.
    items += [("app 20 script", s500), ("app 20", note("the older version counts")), [as_pieces("app 20 script", edge(900, "g"))[0]]]
    return items


def scenario_outside():
    print("outside: a notebook written from outside, with apps and things in pieces that must not count")
    disk, last = answered_disk("kept-outside", outside_items())
    before = read_things(disk)
    things = before["things"]
    apps = apps_of(things)
    listed = [r for _, r, w in apps if w]
    meant = ["the older version counts", "a seventh app", "a small app", "the longest script", "three pieces", "two full pieces",
             "one byte more", "exactly one entry"]
    report("outside the outside reader's apps", listed == meant, None if listed == meant else "%r" % listed)
    report("outside the outside reader's left out", [r for _, r, w in apps if not w] ==
           ["a piece missing", "a wrong check value", "pieces out of order", "a stranger between pieces", "one piece of one",
            "a piece numbered 0", "a piece past the count", "a short piece in front", "an empty last piece", "seventy-five pieces",
            "more than 32 KB", "pieces numbered out of order"])
    run = Run("kept-outside", disk)
    chat = KeyedChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    run.shot("start", screen(1280, 800, chat, listed))
    lines = run.end()
    check_start("outside", lines, things, entries=before["end"] - 1)
    after = read_things(disk)
    report("outside nothing written", after["entries"] == before["entries"])


def scenario_requests():
    print("requests: notes from outside, and the highest number")
    items = []
    for name, data in [("app 1", b"\x01caf\xc3\xa9 \x1b[31mred\x07 and more"), ("app 2", note("r" * 60)), ("app 3", b"\x02another form"),
                       ("app 4", b"\x01"), ("app 5", b""), ("app 0", note("number zero")), ("app 01", note("a zero in front")),
                       ("app 1234567890", note("ten digits")), ("app x", note("not a number")), ("app 7 ", note("a space behind"))]:
        items += [(name + " script", SCRIPT), (name, data)]
    items += [("apps 6", note("not the name of an app")), ("app 8", note("no script at all"))]
    items += app_things(999999999, "nine digits", SCRIPT)
    disk, last = answered_disk("kept-requests", items)
    before = read_things(disk)
    apps = apps_of(before["things"])
    listed = [r for _, r, w in apps if w]
    meant = ["nine digits", "r" * 45, "caf.. .[31mred. and more"]
    report("requests the outside reader's apps", listed == meant, None if listed == meant else "%r" % listed)
    run = Run("kept-requests", disk, behaviours=["app", "app"])
    chat = MakeChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    run.shot("start", screen(1280, 800, chat, listed))
    give_key(run, chat)
    # A new app would need the number after 999999999.
    run.mark()
    run.press("make one more app\n", chat)
    run.wait_line("Kernel: the app ", timeout=120)
    trouble = run.wait_line("Kernel: I could not keep", timeout=20)
    meant_row = not_kept_row("the numbers for apps have run out")
    report("requests no number left", trouble == meant_row, None if trouble == meant_row else "got %r" % trouble)
    asked_again(run)
    # The note of app 8 has no script: an app made for its request takes its number, and its note is not written again.
    run.mark()
    run.press("make no script at all\n")
    run.wait_line("Kernel: the app ", timeout=120)
    line = run.wait_line("Apps: ", timeout=30)
    meant_line = kept_line("no script at all")
    report("requests the note without a script", line == meant_line, None if line == meant_line else "got %r" % line)
    asked_again(run)
    lines = run.end()
    check_start("requests", lines, before["things"], entries=before["end"] - 1)
    after = read_things(disk)
    added = [e[0] for e in after["entries"][len(before["entries"]):]]
    meant_added = ["last line", "last line", "last line", "app 8 script"]
    report("requests entries added", added == meant_added, None if added == meant_added else "got %r" % added)
    report("requests the script of app 8", after["things"].get("app 8 script", (0, b""))[1] == kept_script("app", KEY))
    again = Run("kept-requests-again", disk)
    lines = again.end()
    check_start("requests restart", lines, after["things"], entries=after["end"] - 1)


def scenario_look():
    print("look: the panel in a kept look, painted again when the model picks another, and after a restart")
    items = app_things(1, "a dice that rolls", SCRIPT) + app_things(2, "a coin to flip", b'show("heads")')
    disk, last = answered_disk("kept-look", items, answers=[("name", b""), ("locked key", b""), ("look", b"Night")])
    run = Run("kept-look", disk, behaviours=["look=3"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"Night")
    listed = ["a coin to flip", "a dice that rolls"]
    run.shot("night", screen(1280, 800, chat, listed))
    give_key(run, chat)
    run.mark()
    run.press("paper please\n", chat)
    row = run.wait_line("Kernel: this is look", "Kernel: the model", timeout=60)
    chat.pick(3)
    report("look picked by the model", row == chat.said[-1], None if row == chat.said[-1] else "got %r" % row)
    run.shot("paper", screen(1280, 800, chat, listed))
    run.end()
    again = Run("kept-look-again", disk)
    chat2 = KeyedChat(1280, kept_name=b"", key_entry=b"", kept_look=b"Paper", last_line=b"paper please")
    again.shot("paper-kept", screen(1280, 800, chat2, listed))
    again.end()


def scenario_small():
    print("small: a screen of 800 by 600 dots")
    items = []
    for number in range(1, 7):
        items += app_things(number, "app number %d of six" % number, SCRIPT)
    disk, last = answered_disk("kept-small", items)
    run = Run("kept-small", disk, width=800, height=600, extra=["-vga", "cirrus"])
    chat = KeyedChat(800, kept_name=b"", key_entry=b"", kept_look=b"")
    run.shot("start", screen(800, 600, chat, ["app number %d of six" % n for n in range(6, 0, -1)]))
    run.end()


def scenario_damaged():
    print("damaged: a damaged notebook with apps")
    items = app_things(1, "a dice that rolls", SCRIPT) + app_things(2, "a long app", EXACT)
    items += [[lambda number: bytes(BLOCK)], [raw("last line", b"behind the gap")]]
    disk, last = answered_disk("kept-damaged", items)
    before = read_things(disk)
    run = Run("kept-damaged", disk)
    run.mark()
    run.press("hello\n")
    said = run.wait_line(NO_KEY, timeout=20)
    report("damaged line answered", said is not None)
    lines = run.end()
    check_start("damaged", lines, before["things"], entries=before["end"] - 1, damaged=True)
    after = read_things(disk)
    report("damaged nothing written", after["entries"] == before["entries"] and after["behind"] == before["behind"])


def scenario_full():
    print("full: no room for the script, or none for the note")
    for blocks, what in [(80, "script"), (81, "note")]:
        tag = "kept-full-" + what
        disk, last = answered_disk(tag, blocks=blocks)
        before = read_things(disk, last=last)
        run = Run(tag, disk, behaviours=["appexact"])
        give_key(run)
        run.mark()
        run.press("make a long app of comments\n")
        run.wait_line("Kernel: the app ", timeout=120)
        trouble = run.wait_line("Kernel: I could not keep", timeout=30)
        report(tag + " row", trouble == not_kept_row("the notebook is full"), None if trouble == not_kept_row("the notebook is full") else "got %r" % trouble)
        run.end()
        added = ["last line", "last line"] + (["app 1 script"] * 74 if what == "note" else [])
        after = check_notebook(tag, disk, before, added, last=last)
        again = Run(tag + "-again", disk)
        lines = again.end()
        check_start(tag + " restart", lines, after["things"], last=last, entries=after["end"] - 1)
        report(tag + " start counted", "Disk: this is start number 2" in lines)


def scenario_failing():
    print("failing: a disk that refuses to write the third piece")
    disk, last = answered_disk("kept-failing")
    before = read_things(disk)
    # The answers are entries 1 to 3, the lines "key" and "make ..." 4 and 5, so the pieces begin at block 6 and the
    # third lies in block 8 of the part.
    rules = os.path.join(RUNS, "kept-failing.cfg")
    open(rules, "w").write('[inject-error]\nevent = "write_aio"\nerrno = "5"\niotype = "write"\nsector = "%d"\n' % (FIRST + 8))
    home = os.getcwd()
    os.chdir(RUNS)     # blkdebug's two paths must be without a colon
    try:
        drive = ["-device", "ich9-ahci,id=ahci0", "-drive", "if=none,id=d0,format=raw,file=blkdebug:%s:%s" % (os.path.basename(rules), os.path.basename(disk)),
                 "-device", "ide-hd,drive=d0,bus=ahci0.0"]
        run = Run("kept-failing", disk, behaviours=["appexact"], drive=drive)
        give_key(run)
        run.mark()
        run.press("make a long app of comments\n")
        run.wait_line("Kernel: the app ", timeout=120)
        trouble = run.wait_line("Kernel: I could not keep", timeout=30)
        meant = not_kept_row("the disk reported that it could not do what was asked")
        report("failing row", trouble == meant, None if trouble == meant else "got %r" % trouble)
        asked_again(run)
        run.mark()
        run.press("after\n")
        line = run.wait_line("Kernel: I could not keep that line", timeout=20)
        report("failing the next line not kept", line == "Kernel: I could not keep that line, because the disk reported that it could not do what was asked",
               None if line else "no row: the line was written somewhere")
        run.end()
    finally:
        os.chdir(home)
    after = check_notebook("failing", disk, before, ["last line", "last line", "app 1 script", "app 1 script"])
    again = Run("kept-failing-again", disk)
    lines = again.end()
    check_start("failing restart", lines, after["things"], entries=after["end"] - 1)


def run_row_soon(run, timeout=120):
    """Waits for the row about an app's run, looking every 2 thousandths of a second, so that what follows it can
    be timed. Gives back the moment it was seen, or None."""
    end = time.time() + timeout
    while time.time() < end:
        if any(l.startswith("Kernel: the app ") for l in run.since()):
            return time.time()
        time.sleep(0.002)
    return None


def keep_time(run, request, kind):
    """Sends `make`, and gives back the seconds from the row about the run to the line that says the app is kept."""
    run.mark()
    run.press("make " + request + "\n")
    began = run_row_soon(run)
    if began is None:
        return None
    while time.time() - began < 30:
        if any(l.startswith("Apps: the app made for") for l in run.since()):
            return time.time() - began
        time.sleep(0.002)
    return None


def scenario_cut(rounds=10):
    print("cut: QEMU killed at a random moment while a long app is kept, %d times on one disk" % rounds)
    disk, last = answered_disk("kept-cut", app_things(1, "a small app", SCRIPT))
    run = Run("kept-cut-0", disk, behaviours=["appexact"])
    give_key(run)
    took = keep_time(run, "a long app number 0", "appexact")
    run.end()
    report("cut keeping a long app took %.3f s" % (took or 0), took is not None)
    took = took or 0.5
    kinds = {"before keeping": 0, "inside the script": 0, "between script and note": 0, "kept whole": 0}
    for number in range(1, rounds + 1):
        before = read_things(disk)
        # A new request every round, so that a round that gets as far as the note writes one.
        run = Run("kept-cut-%d" % number, disk, behaviours=["appexact"])
        give_key(run)
        run.mark()
        run.press("make a long app number %d\n" % number)
        seen = run_row_soon(run)
        wait = random.uniform(0, took)
        time.sleep(max(0.0, wait - (time.time() - seen)) if seen else wait)
        run.end(kill=True)
        after = read_things(disk)
        ok = after["entries"][:len(before["entries"])] == before["entries"] and not after["behind"]
        # What the kill cut: the entries this round added after its two lines, read from outside.
        added = after["entries"][len(before["entries"]):]
        pieces = [(place, e) for place, e in enumerate(added) if e[0].endswith(" script")]
        notes = [e for e in added if e[0].startswith("app ") and not e[0].endswith(" script")]
        if not pieces:
            kind = "before keeping"
        else:
            name = pieces[0][1][0]
            first_block = len(before["entries"]) + pieces[0][0] + 1
            whole = after["things"].get(name, (None,))[0] == first_block
            kind = "kept whole" if whole and notes else ("between script and note" if whole else "inside the script")
        kinds[kind] += 1
        report("cut round %d, killed %.3f s after the row: %s, %d entries" % (number, wait, kind, after["end"] - 1), ok)
    print("    rounds: %s" % ", ".join("%s %d" % item for item in kinds.items()))
    report("cut at least one kill while the app was kept", kinds["inside the script"] + kinds["between script and note"] > 0)
    final = read_things(disk)
    run = Run("kept-cut-last", disk)
    lines = run.end()
    check_start("cut at the end", lines, final["things"], entries=final["end"] - 1)


def older_kernel():
    """The kernel of commit OLDER, built from a clean export of it, with this project's interpreter (which did not
    change since)."""
    folder = os.path.join(RUNS, "older-kernel")
    built = os.path.join(folder, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
    if os.path.exists(built):
        return built
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    archive = subprocess.run(["git", "archive", "--format=tar", OLDER], cwd=PROJECT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        try:
            tar.extractall(folder, filter="data")
        except TypeError:
            tar.extractall(folder)
    os.makedirs(os.path.dirname(os.path.join(folder, WASM)), exist_ok=True)
    shutil.copyfile(os.path.join(PROJECT, WASM), os.path.join(folder, WASM))
    done = subprocess.run(["cargo", "build"], cwd=folder, capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stderr[-2000:])
        raise SystemExit("THE OLDER KERNEL DID NOT BUILD")
    return built


def scenario_older():
    print("older: the kernel from before pieces, on a disk with kept apps")
    disk, last = answered_disk("kept-older", app_things(1, "a dice that rolls", SCRIPT) + app_things(2, "a long app of comments", EXACT))
    before = read_things(disk)
    # Fenced network: the older kernel fetches its page from the real site, which it must not reach.
    run = Run("kept-older-1", disk, kernel_file=older_kernel(), network=True)
    run.mark()
    run.press("hello from before\n")
    said = run.wait_line('Kernel: you said "hello from before"', timeout=20)
    lines = run.end()
    report("older line answered", said is not None)
    want = count_line(before["end"] - 1)
    report("older count of entries", want in lines, None if want in lines else "%r" % [l for l in lines if l.startswith("Disk: the notebook")])
    report("older says nothing about apps", not [l for l in lines if l.startswith("Apps:")])
    after = check_notebook("older", disk, before, ["last line"])
    report("older things unchanged", all(after["things"].get(n) == t for n, t in before["things"].items()))
    again = Run("kept-older-2", disk)
    lines = again.end()
    check_start("older then this kernel", lines, after["things"], entries=after["end"] - 1)
    report("older then this kernel recalls the line", 'Kernel: last time you said "hello from before"' in lines)


def scenario_times():
    print("times: keeping, and opening with many pieces")
    disk, last = answered_disk("kept-times")
    run = Run("kept-times", disk, behaviours=["app", "appexact"])
    give_key(run)
    one = keep_time(run, "a dice that rolls", "app")
    asked_again(run)
    long = keep_time(run, "a long app of comments", "appexact")
    run.end()
    print("    keeping one entry took %s s, and 74 pieces %s s (from the row about the run to the line about keeping)"
          % ("%.3f" % one if one is not None else "?", "%.3f" % long if long is not None else "?"))
    # Opening: ten scripts of 74 pieces, against as many entries of one block each, by turns, three times each.
    pieces = []
    for number in range(1, 11):
        pieces += app_things(number, "a long app number %d" % number, EXACT)
    plain = [("line %d" % number, b"x" * 448) for number in range(750)]
    for round_number in range(1, 4):
        for what, items in [("ten scripts of 74 pieces", pieces), ("entries of one block each", plain)]:
            tag = "kept-times-open-%d-%s" % (round_number, what.split()[0])
            disk, last = answered_disk(tag, items)
            m = Machine(tag, extra=one_disk(disk), disk=False, network=True, kernel=kernel())
            stamps = {}
            began = time.time()
            marks = ("Disk: my own part", "Disk: the notebook holds", "repeated here:")
            while time.time() - began < 120 and len(stamps) < len(marks):
                text = m.serial().decode(errors="replace")
                for start in marks:
                    if start in text and start not in stamps:
                        stamps[start] = time.time()
                time.sleep(0.002)
            m.quit()
            if len(stamps) == len(marks):
                print("    a notebook of %d entries (%s): opening took %.2f s, and the start up to the prompt %.2f s from the part's line"
                      % (read_things(disk)["end"] - 1, what, stamps[marks[1]] - stamps[marks[0]], stamps[marks[2]] - stamps[marks[0]]))


SCENARIOS = {"first": scenario_first, "make": scenario_make, "echo": scenario_echo, "outside": scenario_outside, "requests": scenario_requests,
             "look": scenario_look, "small": scenario_small, "damaged": scenario_damaged, "full": scenario_full,
             "failing": scenario_failing, "cut": scenario_cut, "older": scenario_older, "times": scenario_times}


def main():
    names = sys.argv[1:] or [n for n in SCENARIOS if n not in ("older", "times")]
    for name in names:
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
