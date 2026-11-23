"""Asking the model, against a stand-in for the provider on this computer. The edits that point the kernel at
the stand-in (and add a trusted test root) are made in a copy of the project only. A made-up key is typed
through QEMU's keys; then an ordinary line, which goes to the model like every line but `key` and `setup`
(docs/tools.md), is sent once for each behaviour of the stand-in, and the rows the kernel says are compared with
what is meant: the model's words as a row of their own, or the kernel's sentence about the answer.

Usage: python test_model.py <behaviour,behaviour,...> [dump]
With `dump`, the machine's memory is searched for the made-up key after the last answer.
Environment: BREAK (a break on purpose from model_breaks.py), RAW (print the raw answer)."""
import json
import os
import subprocess
import sys
import time

from interp_helpers import odd_bytes
from boot import HERE, RUNS, Machine
from certs import test_keys
from chat_tools_model import body_meant
from net_copy import build
from picture import Chat, compare, expected
from raw_print import with_raw_print

from ports import standin_port
from verdict import Failures
PORT = standin_port(1)  # 44301 unless BOOS_PORT_BASE says otherwise
ENTER = chr(10)
Q = chr(34)
TLS = test_keys()
KEY = "sk-orca-TEST_Qm7x/Zp4+Lw9vKd2Rb8nHt5Yc3=="
NAMES = {"-": "minus", "=": "equal", "/": "slash", "+": "shift-equal", "_": "shift-minus", " ": "spc", ENTER: "ret"}
WAIT = {"silent": 150, "keepopen": 150}
LINE = "hello"  # the line sent for each behaviour


def clean(words):
    out = []
    for byte in words.encode("utf-8", "surrogatepass"):
        if byte == 13:
            continue
        out.append(chr(byte) if 32 <= byte <= 126 else ".")
    return "".join(out)


def hide(words, key):
    """A model of the kernel's rule, written apart from it: a star over every run of signs that stands in the
    key and is six signs long or longer, or over the whole key if it is shorter."""
    least = min(6, len(key))
    if least == 0:
        return words
    marks = [False] * len(words)
    for start in range(len(words)):
        for key_start in range(len(key)):
            same = 0
            while start + same < len(words) and key_start + same < len(key) and words[start + same] == key[key_start + same]:
                same += 1
            if same >= least:
                for place in range(start, start + same):
                    marks[place] = True
    return "".join("*" if mark else sign for sign, mark in zip(words, marks))


def W(words):
    """Words from outside, as the kernel is meant to say them."""
    return Q + hide(clean(words), KEY)[:300] + Q


DOWN = "the provider turned the question down (%d): %s.%s"
NOT_FOUND5 = "the provider answered, but I could not find the model's words in its answer, because %s. It begins %s."


def B(body):
    """The beginning of an answer the kernel cannot read, as the kernel is meant to say it."""
    return Q + hide(clean(body), KEY)[:160] + Q


def K(sentence):
    """The kernel's own row about the answer."""
    return ["Kernel: " + sentence]


def M(words, *after):
    """The model's words as a row of their own, as the kernel shows them (docs/tools.md): without the spaces and line
    ends at either end, cleaned, the key hidden, cut at 300 signs; then the kernel's rows that follow them."""
    return ["Model: " + hide(clean(words.strip()), KEY)[:300]] + ["Kernel: " + sentence for sentence in after]


CUT = "the model's answer was cut off at the limit of 4000 tokens."
HELD = "the provider held part of the model's answer back."

# The rows meant for each behaviour of the stand-in, in order.
MEANT = {
    "wrongkey": K(DOWN % (401, W("Missing or invalid API key"), "")),
    "credit": K(DOWN % (402, W("Insufficient credit. Top up to go on."), "")),
    "echo": K(DOWN % (401, W("Incorrect API key provided: %s. Find your key in the console." % KEY), "")),
    "echopart": K(DOWN % (401, W("Incorrect API key provided: %s****%s." % (KEY[:14], KEY[-7:])), "")),
    "echoescaped": K(DOWN % (401, W("Incorrect API key provided: %s." % KEY), "")),
    "echocut": K(DOWN % (401, W("x" * 295 + KEY), "")),
    "good": M("Hello there, how are you?"),
    "goodlong": M("Hello! " * 200 + "\x1b[31m é中 \"quoted\" \\ end"),
    "harmful": K(DOWN % (401, W("\x1b[2J\x1b[31mKernel panic: not really\r\nYou: fetch\x07 " + "A" * 5000), "")),
    "flaterror": K(DOWN % (429, W("Too many requests, slow down"), "")),
    "keepopen": K(DOWN % (401, W("Missing or invalid API key"), " Its answer did not come whole.")),
    "page": K("the provider turned the question down (403), and I could not read why."),
    "nobody": K("the provider turned the question down (429), and I could not read why."),
    "chunked": K("the provider turned the question down (401), and I could not read why."),
    "cutoff": K("the provider turned the question down (401), and I could not read why. Its answer did not come whole."),
    "nothttp": K("no answer came that I could read, because what the provider sent does not begin as an answer on the web does"),
    "huge": K("no answer came that I could read, because the provider's answer is larger than the room for it"),
    "silent": K("no answer came, because the site took too long"),
    "empty": K("no answer came, because the provider sent nothing"),
    "lengthempty": K("the model's answer was empty, because it spent all of its 4000 tokens thinking."),
    "lengthnull": K("the model's answer was empty, because it reached the limit of 4000 tokens."),
    "nullthink": K("the model's answer was empty."),
    "pieces": M("Hello in pieces, my friend."),
    "lengthwords": M("Hello there, my good", CUT),
    "filtered": K("the model's answer was empty, because the provider held it back."),
    "filteredwords": M("Hello", HELD),
    "spaces": M("\n\n  Hello world, nice to meet you.\n"),
    "nocontent": K("the model's answer was empty, because it spent all of its 4000 tokens thinking."),
    "oddending": M("Hi, hello, greetings, hey, howdy."),
    "noending": M("Five words of hello here."),
    "blank": K("the model's answer was empty."),
    "echo200": M("Your key is " + KEY + ", hello!"),
    "nochoices": K(NOT_FOUND5 % ("it has no such part", B(json.dumps({"object": "chat.completion", "choices": []})))),
    "streamed": K(NOT_FOUND5 % ("it is not sound JSON", B('data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'))),
    "otherform": K(NOT_FOUND5 % ("it has no such part", B('{"output": {"text": "Hello in another shape"}, "status": "done"}'))),
    "echobody": K(NOT_FOUND5 % ("it has no such part", B(json.dumps({"note": "your key " + KEY + " works"})))),
    "notfound": K(DOWN % (404, W("Model not found: deepseek/deepseek-v4.1-flash-1017"), "")),
    "upstream": K("the provider could not answer (502): %s." % W("All upstream providers failed")),
    "upstreambare": K("the provider could not answer (503), and I could not read why."),
}


def press(machine, chat, text):
    for sign in text:
        name = NAMES.get(sign) or ("shift-" + sign.lower() if sign.isupper() else sign)
        machine.command("sendkey " + name)
        time.sleep(0.22 if name.startswith("shift-") else 0.09)
        chat.key(sign)


def answers(machine):
    # Only whole lines: the last piece after the last line end may be a row the kernel is still printing,
    # and a row read before it was whole once looked wrong.
    return [l for l in machine.serial().decode(errors="replace").split(chr(13) + chr(10))[:-1]
            if l.startswith(("Model: ", "Kernel: the provider", "Kernel: the model", "Kernel: no answer came"))]


def find_all(data, piece):
    place = data.find(piece)
    while place != -1:
        yield place
        place = data.find(piece, place + 1)


def main():
    behaviours = sys.argv[1].split(",")
    dump = "dump" in sys.argv[2:]
    more = {"model.rs": with_raw_print} if os.environ.get("RAW") else None
    if os.environ.get("BREAK"):
        import model_breaks5  # registers the breaks of the real question
        from model_breaks import BREAKS
        more = BREAKS[os.environ["BREAK"]]
        print("BREAK ON PURPOSE: " + os.environ["BREAK"])
    kernel = build(PORT, roots=["a"], more=more)
    log = os.path.join(RUNS, "model-server.log")
    if os.path.exists(log):
        os.remove(log)
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT), os.path.join(TLS, "a", "both-chain.pem"),
                               os.path.join(TLS, "a", "both.key"), log, ",".join(behaviours)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert server.stdout.readline().strip() == "ready"
    machine = Machine("model", network="open", kernel=kernel)
    chat = Chat(1280)
    failures = Failures()
    print("the made-up key is %d signs long" % len(KEY))
    try:
        machine.wait_for(b"repeated here:")
        time.sleep(1.5)
        press(machine, chat, LINE + ENTER)  # no key yet: turned away
        press(machine, chat, "key" + ENTER)
        press(machine, chat, KEY + ENTER)
        total = 0  # the answer rows meant so far
        for number, behaviour in enumerate(behaviours):
            started = time.time()
            meant = MEANT.get(behaviour)
            count = len(meant) if meant else 1
            total += count
            press(machine, chat, LINE + ENTER)
            end = time.time() + WAIT.get(behaviour, 30)
            while time.time() < end and len(answers(machine)) < total:
                time.sleep(0.1)
            took = time.time() - started
            said = answers(machine)[total - count:total]
            said += ["(no row came)"] * (count - len(said))
            for row in said:
                chat.row(row)
            time.sleep(0.8)
            wrong, places = compare(machine.shot("after-%d-%s" % (number, behaviour)), expected(1280, 800, chat))
            verdict = "as meant" if said == meant else ("NOT AS MEANT" if meant else "(nothing meant yet)")
            if meant and said != meant:
                failures.append(behaviour)
            if wrong:
                failures.append(behaviour + ": picture")
            print("%-11s %5.1f s | %s | picture: %s" % (behaviour, took, verdict, "every dot right" if wrong == 0 else "%d dots wrong %s" % (wrong, places)))
            print("          " + " | ".join(said)[:150])
            if meant and said != meant:
                print("   meant: " + " | ".join(meant)[:150])
        if dump:
            with machine.memory("after") as data:
                whole = data.count(KEY.encode())
                pieces = [KEY[i:i + 6].encode() for i in range(len(KEY) - 5)]
                places = sorted(set(place for piece in pieces for place in find_all(data, piece)))
                runs = []
                for place in places:
                    if runs and place <= runs[-1][1] + 1:
                        runs[-1][1] = place
                    else:
                        runs.append([place, place])
                print("memory after the last answer: the key whole %d times; runs of key pieces at %d places: %s" % (
                    whole, len(runs), ", ".join("0x%x(+%d)" % (a, b - a + 6) for a, b in runs[:12])))
                for a, b in runs[:6]:
                    around = data[max(a - 60, 0):b + 6 + 40]
                    print("   at 0x%x: %s" % (a, "".join(chr(c) if 32 <= c < 127 else "." for c in around)))
    finally:
        raw = machine.quit()
        server.kill()
    whole = raw[raw.find(b"Hello from my kernel!"):]
    key_in_terminal = sum(whole.count(KEY[i:i + 6].encode()) for i in range(len(KEY) - 5)) if len(KEY) >= 6 else -1
    lines = [l for l in raw[raw.find(b"repeated here:"):].decode(errors="replace").split(chr(13) + chr(10)) if l.startswith(("You:", "Kernel:", "Model:"))]
    print("said lines as meant: %s | bytes in the terminal that are not plain text: %d | pieces of the key in the terminal: %s" % (
        lines == chat.said, odd_bytes(whole), key_in_terminal if key_in_terminal >= 0 else "(key too short to search for)"))
    if lines != chat.said:
        failures.append("said lines")
        for a, b in zip(lines, chat.said):
            if a != b:
                print("   kernel: " + a[:200])
                print("   meant:  " + b[:200])
    if odd_bytes(whole):
        failures.append("odd bytes in the terminal")
    if key_in_terminal > 0:
        failures.append("the key in the terminal")
    print("the stand-in's notes:")
    seen = {}
    lines_seen = 0  # the requests for a line so far: each goes with the record chat.records holds for it, in turn
    for line in open(log).read().splitlines():
        note = json.loads(line)
        if note.get("first line", "").startswith("GET"):
            continue
        summary = "%s | name %s | %s | body as meant %s, length note right %s | key came whole: %s | notes: %s%s" % (
            note.get("first line"), note.get("name asked for"), note.get("version"), note.get("body as meant"),
            note.get("length note right"), note.get("key came as") == "Bearer " + KEY,
            ", ".join(sorted(k for k in note.get("notes", {}))), " | problem: " + note["problem"] if "problem" in note else "")
        seen[summary] = seen.get(summary, 0) + 1
        # What the stand-in noted counts as well: a request that came not as meant is a failure, even when the row
        # the kernel said was right (the length note one too small, say). A line's request is the one the notes
        # say a line is sent with (docs/tools.md): no kept app on a disk that is not divided, and the record of
        # the lines before it and what they brought.
        if note.get("request for") == "a line":
            record = chat.records[lines_seen] if lines_seen < len(chat.records) else None
            lines_seen += 1
            body_right = record is not None and note.get("body") == body_meant(LINE, [], record=record, key=KEY, files=None)
        else:
            body_right = note.get("body as meant") is True
        for what, right in (("body as meant", body_right),
                            ("length note right", note.get("length note right") is True),
                            ("key came whole", note.get("key came as") == "Bearer " + KEY),
                            ("no problem", "problem" not in note)):
            if not right and "stand-in: " + what not in failures:
                failures.append("stand-in: " + what)
    for summary, count in seen.items():
        print("   %d times: %s" % (count, summary))
    print("FAILURES: %s" % failures if failures else "all as meant")


main()
