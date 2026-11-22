"""Asking the model for an app, and running it, against the stand-in for the provider on this computer. The edits
that point the kernel at the stand-in (and add a trusted test root) are made in a copy of the project only
(net_copy.py). A made-up key is typed through QEMU's keys. Then a line that asks for an app ("make " and a
request) is sent once for each behaviour of the stand-in. Every line goes to the model (docs/tools.md): the stand-in
answers it with the tool make_app and the request, and then the request for the app with the behaviour; a
behaviour of model_server.py's own (OTHER below) is given to it with "app:" in front, so that it too answers the
request for the app and not the line. The kernel's rows, the script it shows in the terminal and every dot of the
screen are compared with what is meant (app_cases.py, written apart from the kernel). A script that is taken is
run: the lines it prints, the row that says how the run went, and the text the box in the middle shows are
compared too. A line before a key is kept, lines while an answer is awaited, and at the end one line that the model
answers in words are part of every run; so is every request the stand-in saw, compared with what the notes say.

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

# A test disk that is not divided: no notebook is opened, so nothing is asked at the start, no app is kept, and the
# request for a line offers no kept app. Set before interp_helpers is imported, which would otherwise ask for a
# divided one.
os.environ["DIVIDED_DISK"] = ""

import app_cases
from app_cases import INSTRUCTIONS, LEAD, clean, hide, outcome
from boot import HERE, RUNS, Machine
from certs import test_keys
from chat_cases import AGAIN_WORDS
from chat_tools_model import body_again, body_meant, left_on_screen, making, model_row, request_cleaned, terminal_says
from interp_helpers import odd_bytes
from net_copy import build
from picture import Chat, compare, expected
from ports import standin_port
from verdict import Failures

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
LINE = "hello"  # the last line, which the model answers in words
LAST_WORDS = "Hello there, how are you?"  # model_server.py's "good"


def W(words):
    """Words from outside, as the kernel is meant to say them."""
    return Q + hide(clean(words), KEY)[:300] + Q


def B(body):
    return Q + hide(clean(body), KEY)[:160] + Q


# What the kernel is meant to say when the request for an app gets an answer that is not a good one: exactly what it
# says to such an answer to a line.
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


# The behaviours whose answer to the request for an app is no good one (anything but 200): the line ends there. After
# every other, what came of the app goes back to the model, which is asked about the line again (docs/tools.md); the
# stand-in answers that with its words (chat_cases.AGAIN_WORDS).
NO_GOOD_ANSWER = {"realrefusal", "upstream", "upstreambare", "huge", "nothttp", "silent"}


def standin_kind(behaviour):
    """The behaviour as the stand-in is given it: one of its own with "app:" in front, so that it answers the request
    for the app; a line before it gets the tool make_app (model_server.py)."""
    return "app:" + behaviour if behaviour in OTHER else behaviour


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


def tool_rows(lines):
    """The kernel's rows that say it asks the model for an app, when the model asked for one with make_app."""
    return [line for line in lines if line.startswith("Kernel: I am asking the model to make ")]


def listing_after(lines, place):
    """The script's lines that follow the row at `place`, after the terminal's line about the answer's tokens, and
    where the lines after them begin."""
    at = place + 1
    if at < len(lines) and lines[at].startswith("Tokens:"):
        at += 1
    out = []
    while at < len(lines) and lines[at].startswith("Script "):
        out.append(lines[at])
        at += 1
    return out, at


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
    """A machine without a network card: a line that asks for an app is turned away at once, as every line is."""
    machine = Machine("app-nocard", network=False)
    chat = Chat(1280)
    chat.network = "none"
    failures = Failures()
    try:
        machine.wait_for(b"repeated here:")
        time.sleep(1.5)
        press(machine, chat, "make a dice" + ENTER)
        press(machine, chat, "key" + ENTER)
        press(machine, chat, KEY + ENTER)
        press(machine, chat, "make a dice" + ENTER)
        press(machine, chat, LINE + ENTER)
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
                               os.path.join(tls, "a", "both.key"), log, ",".join([standin_kind(b) for b in behaviours] + ["good"])],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE)
    assert server.stdout.readline().strip() == "ready"
    machine = Machine("app", network="open", kernel=kernel)
    chat = Chat(1280)
    failures = Failures()
    asked = []  # what each request for an app that reached the stand-in asked for, in order
    sent = []  # each line that reached the stand-in, in order
    line_bodies = []  # each request for a line meant, in order: a line's first ask, and the ask about it again
    line_labels = []  # what each of them is, for the report
    again_words = model_row(AGAIN_WORDS, KEY)
    print("the made-up key is %d signs long" % len(KEY))
    try:
        machine.wait_for(b"repeated here:")
        time.sleep(1.5)
        # A line that asks for an app before any key is kept: turned away, as every line is.
        press(machine, chat, "make a dice" + ENTER)
        print("%-12s | %s" % ("before a key", look(machine, chat, "before-key", failures)[0]))
        press(machine, chat, "key" + ENTER)
        press(machine, chat, KEY + ENTER)
        panel = "Hello from a Lua script!!!"  # what the box in the middle shows, as far as the test knows
        randoms = []
        for number, behaviour in enumerate(behaviours):
            request = REQUESTS[number % len(REQUESTS)]
            started = time.time()
            words_before = sum(1 for line in terminal_lines(machine) if line.startswith("Model: "))
            press(machine, chat, "make " + request + ENTER)
            sent.append("make " + request)
            asked.append(request)
            line_bodies.append(body_meant("make " + request, [], record=chat.records[-1], key=KEY))
            line_labels.append("make " + request)
            # The line's answer is the tool make_app: the kernel says so, and asks for the app.
            end = time.time() + 40
            while time.time() < end and len(tool_rows(terminal_lines(machine))) <= number:
                time.sleep(0.1)
            tools = tool_rows(terminal_lines(machine))
            tool_row = tools[number] if len(tools) > number else "(no row came)"
            chat.row(tool_row)
            if tool_row != making(request_cleaned(request)):
                failures.append(behaviour + ": tool row")
            if behaviour == "slowapp":
                # Lines sent while the app is awaited: both are turned away.
                chat.network = "busy"
                press(machine, chat, "make another one" + ENTER)
                press(machine, chat, LINE + ENTER)
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
            goes_back = behaviour not in NO_GOOD_ANSWER
            if goes_back:
                # What came of the app goes back to the model: the words of the second ask come before the picture.
                end = time.time() + 40
                while time.time() < end and sum(1 for line in terminal_lines(machine) if line.startswith("Model: ")) <= words_before:
                    time.sleep(0.1)
                time.sleep(0.3)
            lines = terminal_lines(machine)
            places = answers(lines)
            said = lines[places[number]][len("Kernel: "):] if len(places) > number else "(no row came)"
            listing, after = listing_after(lines, places[number]) if len(places) > number else ([], 0)
            # The run's own lines (App: ...) and its row, after the script's lines.
            app_lines, run_row = [], None
            if len(places) > number:
                for line in lines[after:]:
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
            shown_now = False  # whether the run showed a text, which then goes back to the model
            mistake_line = None  # the interpreter's line about a mistake, which goes back too
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
                    shown_now = bool(giver(app_lines))
                    if want_row == app_cases.MISTAKE and app_lines:
                        mistake_line = app_lines[-1][len("App: "):]
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
            if goes_back:
                # The words of the second ask stand in the chat box below the rows about the app, for the picture...
                chat.said.append(again_words)
                chat.add("kernel", again_words)
            picture, matched = look(machine, chat, "after-%d-%s" % (number, behaviour), failures, candidates)
            if matched is not None:
                panel = matched
            if goes_back:
                # ...and are remembered after what the app left behind, which went back to the model with that ask: the
                # text it showed (which of the texts the picture says) and its mistake.
                if shown_now:
                    chat.remember(hide(left_on_screen(matched if matched is not None else candidates[0]), KEY))
                if mistake_line is not None:
                    chat.remember(hide(terminal_says(mistake_line), KEY))
                chat.again()
                line_bodies.append(body_again("make " + request, [], chat.agains[-1], key=KEY))
                line_labels.append("make " + request + ", again")
                chat.memory.answered(again_words)
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
        # A last line, which the model answers in words: a row of their own.
        words_before = sum(1 for line in terminal_lines(machine) if line.startswith("Model: "))
        press(machine, chat, LINE + ENTER)
        sent.append(LINE)
        line_bodies.append(body_meant(LINE, [], record=chat.records[-1], key=KEY))
        line_labels.append(LINE)
        end = time.time() + 40
        while time.time() < end and sum(1 for line in terminal_lines(machine) if line.startswith("Model: ")) <= words_before:
            time.sleep(0.1)
        words = [line for line in terminal_lines(machine) if line.startswith("Model: ")]
        said = words[-1] if words else "(no row came)"
        chat.row(said)
        last_right = said == model_row(LAST_WORDS, KEY)
        if not last_right:
            failures.append("last line: row")
        print("%-12s       | row %s | picture: %s" % ("last line", "as meant" if last_right else "NOT AS MEANT",
                                                     look(machine, chat, "after-last-line", failures, [panel])[0]))
        print("             " + said[:160])
        if dump:
            with machine.memory("after") as data:
                pieces = [KEY[i:i + 6].encode() for i in range(len(KEY) - 5)]
                print("memory after the last answer: the key whole %d times; pieces of it at %d places" % (
                    data.count(KEY.encode()), sum(data.count(piece) for piece in pieces)))
    finally:
        raw = machine.quit()
        server.kill()
    whole = raw[raw.find(b"Hello from my kernel!"):]
    key_in_terminal = sum(whole.count(KEY[i:i + 6].encode()) for i in range(len(KEY) - 5))
    said_lines = [l for l in raw[raw.find(b"repeated here:"):].decode(errors="replace").split(chr(13) + chr(10)) if l.startswith(("You:", "Kernel:", "Model:"))]
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
    # What the stand-in saw: every line with the request the notes say a line is sent with (no kept app, on a disk
    # that is not divided), and every request for an app with the instruction text and the request the model gave.
    notes = [json.loads(line) for line in open(log).read().splitlines()]
    posts = [note for note in notes if not note.get("first line", "").startswith("GET")]
    lines_seen = [note for note in posts if note.get("request for") == "a line"]
    apps_seen = [note for note in posts if note.get("request for") != "a line"]
    print("the stand-in's notes: %d requests for a line, %d for an app" % (len(lines_seen), len(apps_seen)))

    def judged(note, want, label, what):
        right = want is not None and note.get("body") == want
        whole_key = note.get("key came as") == "Bearer " + KEY
        ok = right and note.get("length note right") and whole_key and note.get("first line") == "POST /v1/chat/completions HTTP/1.0"
        if not ok:
            failures.append(label)
        print("   %-17s %-24s | body as meant %s | %5s bytes | length note right %s | key came whole %s | name %s%s" % (
            label, what[:24], right, note.get("body bytes"), note.get("length note right"), whole_key, note.get("name asked for"),
            " | problem: " + note["problem"] if "problem" in note else ""))

    for number, note in enumerate(apps_seen):
        want = None
        if number < len(asked):
            want = {"model": MODEL, "messages": [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": LEAD + asked[number]}],
                    "max_tokens": 4000, "stream": False}
        judged(note, want, "request %d" % (number + 1), behaviours[number] if number < len(behaviours) else "?")
    # Each line goes with the record of the lines before it and what they brought, which the chat model kept; each ask
    # about a line again with what the line brought so far.
    for number, note in enumerate(lines_seen):
        want = line_bodies[number] if number < len(line_bodies) else None
        judged(note, want, "line request %d" % (number + 1), line_labels[number] if number < len(line_labels) else "?")
    if len(apps_seen) != len(behaviours):
        failures.append("%d requests for an app reached the stand-in, meant %d" % (len(apps_seen), len(behaviours)))
    if len(lines_seen) != len(line_bodies):
        failures.append("%d requests for a line reached the stand-in, meant %d" % (len(lines_seen), len(line_bodies)))
    print("FAILURES: %s" % failures if failures else "all as meant")


main()
