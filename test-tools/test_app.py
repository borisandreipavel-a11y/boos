"""Asking the model for an app, and running it, against the stand-in for the provider on this computer. The edits
that point the kernel at the stand-in (and add a trusted test root) are made in a copy of the project only
(net_copy.py). A made-up key is typed through QEMU's keys. Then `make` and a request are sent once for each
behaviour of the stand-in, and the row the kernel says, the script it shows in the terminal and every dot of the
screen are compared with what is meant (app_cases.py, written apart from the kernel). A script that is taken is
run: the lines it prints, the row that says how the run went, and the text the box in the middle shows are
compared too. The lines that must not count as a request, the refusals before a key is kept and while an answer
is awaited, and at the end one `ask`, which must still send the fixed question as before, are part of every run.

Usage: python test_app.py <behaviour,behaviour,...> [dump]      (behaviours: the kinds in app_cases.py and
                                                                some of model_server.py's, see OTHER below)
       python test_app.py nocard                                 (a machine without a network card)
With `dump`, the machine's memory is searched for the made-up key after the last answer.
Environment: BREAK (a break on purpose from app_breaks.py)."""
import json
import os
import subprocess
import sys
import time

# A test disk that is not divided: no notebook is opened, so nothing is asked at the start and `key`, `ask` and
# `make` are ordinary lines. Set before interp_helpers is imported, which would otherwise ask for a divided one.
os.environ["DIVIDED_DISK"] = ""

import app_cases
from app_cases import INSTRUCTIONS, LEAD, clean, hide, outcome
from boot import HERE, RUNS, Machine
from certs import test_keys
from interp_helpers import odd_bytes
from net_copy import build
from picture import Chat, compare, expected
from ports import standin_port

PORT = standin_port(3)  # 44303 unless BOOS_PORT_BASE says otherwise
ENTER = chr(10)
Q = chr(34)
KEY = "sk-orca-TEST_Wq8j/Rx3+Mv6tPe9Lc2Kg7Hf4=="
NAMES = {"-": "minus", "=": "equal", "/": "slash", "+": "shift-equal", "_": "shift-minus", " ": "spc", ENTER: "ret",
         Q: "shift-apostrophe", "\\": "backslash", ".": "dot", ",": "comma", "'": "apostrophe", "\b": "backspace"}
REQUESTS = ["a dice", "a clock that says hello", 'a "quoted" \\ app', "a times table for 7", "a joke", "a counter to ten",
            "a coin to flip", "a fortune cookie", "a word that is reversed", "a list of three colours"]
WAIT = {"silent": 150}
MODEL = "deepseek/deepseek-v4.1-flash-1017"


def W(words):
    """Words from outside, as the kernel is meant to say them."""
    return Q + hide(clean(words), KEY)[:300] + Q


def B(body):
    return Q + hide(clean(body), KEY)[:160] + Q


# What the kernel is meant to say to answers that are not good ones: exactly what it says to `ask`.
OTHER = {
    "realrefusal": "the provider turned the question down (401): %s." % W("Invalid API key (request id: 20261119120000123456789TEST)"),
    "upstream": "the provider could not answer (502): %s." % W("All upstream providers failed"),
    "upstreambare": "the provider could not answer (503), and I could not read why.",
    "huge": "no answer came that I could read, because the provider's answer is larger than the room for it",
    "nothttp": "no answer came that I could read, because what the provider sent does not begin as an answer on the web does",
    "silent": "no answer came, because the site took too long",
    "otherform": "the provider answered, but I could not find the model's words in its answer, because it has no such part. It begins %s."
                 % B('{"output": {"text": "Hello in another shape"}, "status": "done"}'),
    "streamed": "the provider answered, but I could not find the model's words in its answer, because it is not sound JSON. It begins %s."
                % B('data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'),
}


def meant(behaviour):
    if behaviour == "slowapp":
        return outcome("app", KEY)
    if app_cases.answer(behaviour, KEY) is not None:
        return outcome(behaviour, KEY)
    return OTHER.get(behaviour), []


def wanted_of(line):
    """The model of the rule for a request: the word alone, or the word, a space and what to make."""
    if not line.startswith("make"):
        return None
    rest = line[4:]
    return rest.strip() if rest == "" or rest.startswith(" ") else None


class AppChat(Chat):
    """The chat box with the line `make` added, from the design."""

    def key(self, sign):
        if not self.secret_asked and sign == ENTER and self.line and wanted_of(self.line) is not None:
            wanted = wanted_of(self.line)
            mine = self.person() + ": " + self.line
            if wanted == "":
                answer = 'Kernel: write what app to make after the word, such as "make a dice".'
            elif not self.secret_held:
                answer = 'Kernel: I cannot ask the model for an app, because no key is kept. Send the line "key" first.'
            else:
                answer = {"ready": 'Kernel: I am asking the model to make "%s".' % wanted,
                          "none": "Kernel: I cannot ask the model for an app, because this machine has no address on the network",
                          "busy": "Kernel: I cannot ask the model for an app, because the answer to what I asked before has not come yet"}[self.network]
            self.said += [mine, answer]
            self.add("person", mine)
            self.add("kernel", answer)
            self.line = ""
            return
        super().key(sign)


def press(machine, chat, text):
    for sign in text:
        name = NAMES.get(sign) or ("shift-" + sign.lower() if sign.isupper() else sign)
        machine.command("sendkey " + name)
        time.sleep(0.22 if name.startswith("shift-") else 0.09)
        chat.key(sign)


def terminal_lines(machine):
    # Only whole lines: the last piece after the last line end may be a row the kernel is still printing.
    return machine.serial().decode(errors="replace").split(chr(13) + chr(10))[:-1]


def answers(lines):
    return [place for place, line in enumerate(lines)
            if line.startswith(("Kernel: the provider", "Kernel: the model", "Kernel: no answer came"))]


def listing_after(lines, place):
    out = []
    for line in lines[place + 1:]:
        if not line.startswith("Script "):
            break
        out.append(line)
    return out


def look(machine, chat, name, failures, panel_texts=("Hello from a Lua script!!!",)):
    """Saves a picture and compares it with the picture meant for each text the box may show; the first that is
    right in every dot counts. Gives back (what to report, the text that was right, or None)."""
    time.sleep(0.8)
    path = machine.shot(name)
    best = None
    for text in panel_texts:
        wrong, places = compare(path, expected(1280, 800, chat, panel_text=text))
        if wrong == 0:
            return "every dot right", text
        if best is None or wrong < best[0]:
            best = (wrong, places)
    failures.append(name + ": picture")
    return "%d dots wrong %s" % best, None


def no_card():
    """A machine without a network card: a request for an app is turned away at once, as `ask` is."""
    machine = Machine("app-nocard", network=False)
    chat = AppChat(1280)
    chat.network = "none"
    failures = []
    try:
        machine.wait_for(b"repeated here:")
        time.sleep(1.5)
        press(machine, chat, "make a dice" + ENTER)
        press(machine, chat, "key" + ENTER)
        press(machine, chat, KEY + ENTER)
        press(machine, chat, "make a dice" + ENTER)
        press(machine, chat, "ask" + ENTER)
        print("no card     | picture: %s" % look(machine, chat, "nocard", failures)[0])
    finally:
        raw = machine.quit()
    said_lines = [l for l in raw[raw.find(b"repeated here:"):].decode(errors="replace").split(chr(13) + chr(10)) if l.startswith(("You:", "Kernel:"))]
    if said_lines != chat.said:
        failures.append("said lines")
    for line in said_lines[-4:]:
        print("   " + line)
    print("said lines as meant: %s" % (said_lines == chat.said))
    print("FAILURES: %s" % failures if failures else "all as meant")


def main():
    if sys.argv[1] == "nocard":
        no_card()
        return
    behaviours = sys.argv[1].split(",")
    dump = "dump" in sys.argv[2:]
    more = None
    if os.environ.get("BREAK"):
        from app_breaks import BREAKS
        more = BREAKS[os.environ["BREAK"]]
        print("BREAK ON PURPOSE: " + os.environ["BREAK"])
    kernel = build(PORT, roots=["a"], more=more)
    tls = test_keys()
    log = os.path.join(RUNS, "app-server.log")
    if os.path.exists(log):
        os.remove(log)
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT), os.path.join(tls, "a", "both-chain.pem"),
                               os.path.join(tls, "a", "both.key"), log, ",".join(behaviours + ["good"])], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, cwd=HERE)
    assert server.stdout.readline().strip() == "ready"
    machine = Machine("app", network="open", kernel=kernel)
    chat = AppChat(1280)
    failures = []
    asked = []  # what each request that reached the stand-in asked for, in order
    print("the made-up key is %d signs long" % len(KEY))
    try:
        machine.wait_for(b"repeated here:")
        time.sleep(1.5)
        # Lines that are no request, and a request before any key is kept.
        for line in ["make a dice", "make", "make   ", "makes sense", "Make a dice", "maker x"]:
            press(machine, chat, line + ENTER)
        print("%-12s | %s" % ("before a key", look(machine, chat, "before-key", failures)[0]))
        press(machine, chat, "key" + ENTER)
        press(machine, chat, KEY + ENTER)
        panel = "Hello from a Lua script!!!"  # what the box in the middle shows, as far as the test knows
        randoms = []
        for number, behaviour in enumerate(behaviours):
            request = REQUESTS[number % len(REQUESTS)]
            started = time.time()
            press(machine, chat, "make " + request + ENTER)
            asked.append(request)
            if behaviour == "slowapp":
                # Asked again while the answer is awaited: both are turned away.
                chat.network = "busy"
                press(machine, chat, "make another one" + ENTER)
                press(machine, chat, "ask" + ENTER)
                chat.network = "ready"
            end = time.time() + WAIT.get(behaviour, 40)
            while time.time() < end and len(answers(terminal_lines(machine))) <= number:
                time.sleep(0.1)
            took = time.time() - started
            row_seen = time.time()
            run_took = None
            sentence, listing_wanted = meant(behaviour)
            runs = sentence is not None and sentence.startswith("the model wrote an app")
            if behaviour == "runslow":
                # Typed while the app runs: the keys wait in the keyboard's line and are taken afterwards.
                press(machine, chat, "abc")
            if runs:
                # The run follows the script's lines; its row comes when it has ended.
                end = time.time() + 20
                while time.time() < end:
                    lines = terminal_lines(machine)
                    places = answers(lines)
                    if len(places) > number and any(line.startswith("Kernel: the app ") for line in lines[places[number] + 1:]):
                        run_took = time.time() - row_seen
                        break
                    time.sleep(0.05)
            time.sleep(0.5)  # the script's lines follow the row
            lines = terminal_lines(machine)
            places = answers(lines)
            said = lines[places[number]][len("Kernel: "):] if len(places) > number else "(no row came)"
            listing = listing_after(lines, places[number]) if len(places) > number else []
            # The run's own lines (App: ...) and its row, after the script's lines.
            app_lines, run_row = [], None
            if len(places) > number:
                for line in lines[places[number] + 1 + len(listing):]:
                    if line.startswith("Kernel: the app "):
                        run_row = line[len("Kernel: "):]
                        break
                    if line.startswith("Kernel: ") or line.startswith("You: "):
                        break
                    if line.startswith("App: "):
                        app_lines.append(line)
            chat.say(said)
            if run_row is not None:
                chat.say(run_row)
            row_right = sentence is not None and said == sentence
            listing_right = listing == listing_wanted
            run_note = ""
            candidates = [panel]
            if runs:
                expect = app_cases.run_expect(behaviour, KEY)
                if expect is None:
                    failures.append(behaviour + ": no outcome meant for its run")
                    run_note = " | run: (nothing meant)"
                else:
                    want_row, judge, giver = expect
                    run_right = run_row == want_row
                    lines_right = judge is None or judge(app_lines)
                    if not run_right:
                        failures.append(behaviour + ": run row")
                    if not lines_right:
                        failures.append(behaviour + ": app lines")
                    candidates = giver(app_lines) or [panel]
                    run_note = " | run: row %s, %d app lines %s, its row %s s after the first" % (
                        "as meant" if run_right else "NOT AS MEANT", len(app_lines), "as meant" if lines_right else "NOT AS MEANT",
                        "%.2f" % run_took if run_took is not None else "?")
                    if not run_right:
                        run_note += "\n      run row: %s\n        meant: %s" % (run_row, want_row)
                    if not lines_right:
                        run_note += "\n      app lines: %s" % app_lines[:4]
            elif run_row is not None:
                failures.append(behaviour + ": a run that was not meant")
            picture, matched = look(machine, chat, "after-%d-%s" % (number, behaviour), failures, candidates)
            if matched is not None:
                panel = matched
            if behaviour == "runrandom":
                randoms.append(tuple(app_lines))
            if behaviour == "runslow":
                press(machine, chat, "\b\b\b")
            if not row_right:
                failures.append(behaviour + ": row")
            if not listing_right:
                failures.append(behaviour + ": script lines")
            print("%-12s %5.1f s | row %s | script lines %s (%d) | picture: %s%s" % (
                behaviour, took, "as meant" if row_right else "NOT AS MEANT", "as meant" if listing_right else "NOT AS MEANT",
                len(listing), picture, run_note))
            print("             " + said[:160] + (" / " + run_row if run_row else ""))
            if not row_right:
                print("      meant: " + (sentence or "(nothing meant)")[:160])
            if not listing_right:
                for got, want in zip(listing + ["(none)"] * 3, listing_wanted + ["(none)"] * 3):
                    if got != want:
                        print("      line: " + got[:120])
                        print("     meant: " + want[:120])
                        break
                print("      lines: %d, meant %d" % (len(listing), len(listing_wanted)))
        if len(randoms) >= 2:
            print("random numbers of the runs: %s" % [r[0] if r else "(none)" for r in randoms])
            if len(set(randoms)) != len(randoms):
                failures.append("random numbers repeat from run to run")
        # The fixed question, once more: it must be asked as before.
        press(machine, chat, "ask" + ENTER)
        end = time.time() + 40
        while time.time() < end and len(answers(terminal_lines(machine))) <= len(behaviours):
            time.sleep(0.1)
        lines = terminal_lines(machine)
        places = answers(lines)
        said = lines[places[len(behaviours)]][len("Kernel: "):] if len(places) > len(behaviours) else "(no row came)"
        chat.say(said)
        ask_right = said == "the model answered %s." % W("Hello there, how are you?")
        if not ask_right:
            failures.append("ask: row")
        print("%-12s       | row %s | picture: %s" % ("ask", "as meant" if ask_right else "NOT AS MEANT", look(machine, chat, "after-ask", failures, [panel])[0]))
        print("             " + said[:160])
        if dump:
            path = os.path.join(machine.folder, "after.mem")
            machine.command("pmemsave 0 0x10000000 " + path.replace(chr(92), "/"))
            last = -1
            for _ in range(100):
                time.sleep(0.3)
                size = os.path.getsize(path) if os.path.exists(path) else 0
                if size == 0x10000000 and size == last:
                    break
                last = size
            data = open(path, "rb").read()
            os.remove(path)
            pieces = [KEY[i:i + 6].encode() for i in range(len(KEY) - 5)]
            print("memory after the last answer: the key whole %d times; pieces of it at %d places" % (
                data.count(KEY.encode()), sum(data.count(piece) for piece in pieces)))
    finally:
        raw = machine.quit()
        server.kill()
    whole = raw[raw.find(b"Hello from my kernel!"):]
    key_in_terminal = sum(whole.count(KEY[i:i + 6].encode()) for i in range(len(KEY) - 5))
    said_lines = [l for l in raw[raw.find(b"repeated here:"):].decode(errors="replace").split(chr(13) + chr(10)) if l.startswith(("You:", "Kernel:"))]
    odd = odd_bytes(whole)
    print("said lines as meant: %s | bytes in the terminal that are not plain text: %d | pieces of the key in the terminal: %d" % (
        said_lines == chat.said, odd, key_in_terminal))
    if said_lines != chat.said:
        failures.append("said lines")
        for a, b in zip(said_lines + ["(none)"], chat.said + ["(none)"]):
            if a != b:
                print("   kernel: " + a[:200])
                print("   meant:  " + b[:200])
                break
    if odd:
        failures.append("odd bytes")
    if key_in_terminal:
        failures.append("key in the terminal")
    # What the stand-in saw: every request for an app must carry the instruction text and the request, and the
    # fixed question must be as before.
    notes = [json.loads(line) for line in open(log).read().splitlines()]
    posts = [note for note in notes if not note.get("first line", "").startswith("GET")]
    print("the stand-in's notes: %d requests" % len(posts))
    for number, note in enumerate(posts):
        if number < len(asked):
            want = {"model": MODEL, "messages": [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": LEAD + asked[number]}],
                    "max_tokens": 4000, "stream": False}
            right = note.get("body") == want
        else:
            right = note.get("body as meant") is True
        whole_key = note.get("key came as") == "Bearer " + KEY
        ok = right and note.get("length note right") and whole_key and note.get("first line") == "POST /v1/chat/completions HTTP/1.0"
        if not ok:
            failures.append("request %d" % (number + 1))
        print("   %2d %-12s | body as meant %s | %5s bytes | length note right %s | key came whole %s | name %s%s" % (
            number + 1, (behaviours + ["ask"])[number] if number < len(behaviours) + 1 else "?", right, note.get("body bytes"),
            note.get("length note right"), whole_key, note.get("name asked for"), " | problem: " + note["problem"] if "problem" in note else ""))
    if len(posts) != len(behaviours) + 1:
        failures.append("%d requests reached the stand-in, meant %d" % (len(posts), len(behaviours) + 1))
    print("FAILURES: %s" % failures if failures else "all as meant")


main()
