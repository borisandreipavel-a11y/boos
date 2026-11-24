"""Anthropic as a second provider (docs/model.md, "Anthropic"; docs/chat.md, "The provider"): the question for the
provider before the key, each provider's key under a name of its own, and Anthropic's form for the key's try and
for lines, against the stand-in (model_server.py, which answers Anthropic's form through anthropic_cases.py) in the
stand-in copy of the project (net_copy.py). Every request the stand-in saw is checked: its provider's form, the
site it went to, the note that carried the key and the key itself. The notebook is read from outside, and a locked
key is opened from outside with its password. Made-up names, keys and passwords only.

  first     a fresh disk: the name, the provider (2), the key tried at Anthropic in its form, the password, the look;
            a line answered piece by piece in Anthropic's form. Then a restart: the password unlocks the Anthropic key,
            and lines go to Anthropic; `setup` picks OrcaRouter and its key is tried there and locked under its own
            name; `setup` picks Anthropic again, and Enter alone at the key asks for that key's password at once, so
            the next line goes to Anthropic with its key; `setup` keeping Anthropic, Enter alone keeps the key in memory.
  older     a disk from before the question: a name and a locked key, no provider: the start asks only the password,
            as before, and lines go to OrcaRouter.
  powercut  a disk that holds Anthropic as the provider but no key for it (the power went before the key was locked):
            the question offers Anthropic, and OrcaRouter's locked key is never used for it.
  keyword   `key` while Anthropic is in use: the key goes to Anthropic; a `setup` that picks OrcaRouter wipes it, so the
            next line is not sent at all.
  events    Anthropic's endings and pieces that OrcaRouter's form has no way to say, on lines: the provider's checks
            stopping the answer (with words; in the middle of a table, which is not drawn), the model's context reached,
            a kind of event and of block the kernel does not know, `overloaded_error` in the middle, an end mark without
            a word about how it ended; and today's ways (a piece that breaks the answer off, lines that only say the link
            is alive, thinking, counts read back from what was kept, a tool's inputs in pieces) in Anthropic's form; and
            `forget`, which takes no inputs, with one piece of its inputs, empty.

Usage: python test_anthropic.py [scenario ...]        (with none: all)
Environment: BOOS_PORT_BASE (43300 for this lane)."""
import json
import os
import sys
import time

os.environ["DIVIDED_DISK"] = ""

import anthropic_cases
import chat_cases
from anthropic_breaks import BREAKS
from conversation_model import FORGOT
from keyed_model import LOOK_QUESTION, stays
from keyref import unlock
from lockref import lock
from nb import newest, read_notebook
from net_copy import build
from picture import NO_KEY
from test_apps_kept import PORT, Run as KeptRun, answered_disk, failures, report

_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of anthropic_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def Run(tag, disk, behaviours=()):
    return KeptRun(tag, disk, behaviours=behaviours, kernel_file=kernel())

NAME = "Ada"
ANTHROPIC_KEY = "sk-ant-TEST-Quince_Lw7q/Rd2m+Hx9Kb4=="
ORCA_KEY = "sk-orca-TEST-Fennel_Pz3n/Ve8j+Ty5Ms1=="
ANTHROPIC_PASSWORD = "plum tree 7"
ORCA_PASSWORD = "oak door 4"

HELLO_FEW = "Kernel: hello! I do not know you yet, so I have a few questions before we begin."
NAME_QUESTION = 'Kernel: what should I call you? Type a name and press Enter. Enter alone keeps "%s".'
PROVIDER_QUESTION = "Kernel: your lines go to 1 OrcaRouter (api.orcarouter.ai) or 2 Anthropic (api.anthropic.com)."
PROVIDER_ENTER = "Kernel: type 1 or 2 and press Enter. Enter alone keeps %s."
NOT_ONE_OR_TWO = "Kernel: that is not 1 or 2. Type 1 or 2, or Enter alone to keep %s."
CHOSEN = "Kernel: your lines go to %s."
KEY_WHY = "Kernel: to ask the model I need your key. I lock it with a password and keep it on the disk."
KEY_QUESTION = "Kernel: type the key and press Enter. It shows as stars. Enter alone goes on without a key."
KEY_QUESTION_AGAIN = "Kernel: type a new key and press Enter. Enter alone keeps the one locked on the disk."
TRYING = "Kernel: I took a key of %d signs, and I am trying it with one question to the model."
ANSWERED = 'Kernel: the model answered "Hello there, how are you?".'
WORKS = "Kernel: the key works. Now choose a password of at least 4 signs to lock it with."
SAME_AGAIN = "Kernel: type the same password again and press Enter."
LOCKING = "Kernel: locking the key with your password. This takes a second or two."
LOCKED_ROW = "Kernel: the key is locked and kept on the disk. Each start will ask for the password."
WELCOME = "Kernel: welcome back, %s." % NAME
PASSWORD_QUESTION = "Kernel: type your password and press Enter to unlock the key. Enter alone goes on without it."
ANTHROPIC_PASSWORD_QUESTION = "Kernel: type your password and press Enter to unlock the Anthropic key. Enter alone goes on without it."
UNLOCKING = "Kernel: unlocking the key. This takes a second or two."
UNLOCKED = "Kernel: the key is unlocked, so your lines go to the model."
TYPE_A_LINE = " Type a line and press Enter."
NAME_STAYS = 'Kernel: your name stays "%s".' % NAME
KEY_STAYS = "Kernel: the key locked on the disk stays as it was."
ASKING = "Kernel: I am asking the model."
SHOWN = ("Kernel:", "Model:", NAME + ":", "You:", "Tokens:")
CHECKS = "Kernel: the provider's checks stopped the model's answer."
CHECKS_TOOL = "Kernel: the provider's checks stopped the model's answer, so I did not do what it asked for."
WINDOW = "Kernel: the model's answer was cut off, because the question and the answer grew larger than the model takes."
OVERLOADED = 'Kernel: the provider broke the model\'s answer off: "Overloaded".'
BROKEN = 'Kernel: the provider broke the model\'s answer off: "%s".' % chat_cases.BREAK_MESSAGE
THOUGHT_ALL = "Kernel: the model's answer was empty, because it spent all of its 4000 tokens thinking."
CUT_OFF = "Kernel: the model's answer was cut off at the limit of 4000 tokens."
FIRST_WORDS = "These are the first words."


def check(what, ok, detail=None):
    """Says how a check went: the detail only when it did not go as meant."""
    report(what, ok, None if ok else (detail or "NOT AS MEANT"))


def rows_since(run):
    return [line for line in run.since() if line.startswith(SHOWN)]


class Derailed(Exception):
    """A row waited for never came: the rest of the scenario would wait in vain at every step."""


def step(run, keys, last, meant, tag, timeout=90):
    """Types `keys`, waits for a row that begins with `last`, and compares the rows since with `meant`. When the row
    never comes, the scenario ends there (Derailed), after its failure is said."""
    run.mark()
    run.press(keys)
    found = run.wait_line(last, timeout=timeout)
    time.sleep(0.4)
    got = rows_since(run)
    check(tag, found is not None and got == meant, None if found and got == meant else "got %s\n      meant %s" % (got, meant))
    if found is None:
        raise Derailed(tag)


def line(run, said, words, tag, more=(), tokens=chat_cases.TOKENS_LINE):
    """Sends a line whose answer is `words` (or rows `more` in their place), and compares the rows it brought."""
    meant = ["%s: %s" % (NAME, said), ASKING] + (["Model: " + words] if words else []) + list(more) + ([tokens] if tokens else [])
    step(run, said + "\n", tokens or meant[-1], meant, tag)


def posts(run):
    if not os.path.exists(run.log):
        return []
    notes = [json.loads(text) for text in open(run.log, encoding="utf-8") if text.strip()]
    return [n for n in notes if n.get("first line", "").startswith("POST ")]


def check_posts(run, meant, tag):
    """`meant`: for each POST in turn, (provider, key, what it is: "try" or "line"). Every POST is checked in full:
    its form, its site, the note that carried the key, and the key."""
    seen = posts(run)
    check(tag + " requests", len(seen) == len(meant), "%d, meant %d" % (len(seen), len(meant)))
    for number, (note, (provider, key, kind)) in enumerate(zip(seen, meant)):
        where = "%s request %d" % (tag, number + 1)
        check(where + " provider", note.get("provider") == provider, note.get("provider"))
        if provider == "anthropic":
            check(where + " in Anthropic's form", note.get("anthropic form right") is True,
                   "%s %s" % (note.get("anthropic form problem"), {k: note.get(k) for k in ("key note", "version note", "host", "name asked for")}))
            check(where + " the first line", note.get("first line") == "POST /v1/messages HTTP/1.0", note.get("first line"))
            sent = note.get("sent body") or {}
            check(where + " the model", sent.get("model") == anthropic_cases.MODEL, sent.get("model"))
            if kind == "try":
                check(where + " the fixed question", note.get("body as meant") is True and "system" not in sent and sent.get("max_tokens") == 1000,
                       json.dumps(sent)[:200])
            else:
                tools = sent.get("tools") or []
                check(where + " the line with its tools", sent.get("stream") is True and sent.get("max_tokens") == 4000 and bool(tools)
                       and all(set(tool) == {"name", "description", "input_schema"} for tool in tools), json.dumps(sent)[:200])
        else:
            check(where + " in OrcaRouter's form", note.get("first line") == "POST /v1/chat/completions HTTP/1.0" and note.get("key note") == "authorization"
                   and note.get("host") == "api.orcarouter.ai" and note.get("name asked for") == "api.orcarouter.ai",
                   "%s %s" % (note.get("first line"), note.get("host")))
        check(where + " the key", note.get("key came as") == "Bearer " + key, "another key, or another note")


def entries(disk):
    return newest(read_notebook(disk)["entries"])


def key_locked(disk, name, password, key, tag):
    locked = entries(disk).get(name)
    check(tag, locked is not None and unlock(password.encode(), locked) == key.encode(), "the entry %r does not open to the key" % name)


def first_boot_rows(run):
    """The first start of a fresh disk, up to the look: the name, the provider (2), Anthropic's key and its password."""
    check("first the questions at the start", rows_since(run)[-2:] == [HELLO_FEW, NAME_QUESTION % "You"], rows_since(run)[-2:])
    step(run, NAME + "\n", PROVIDER_ENTER % "OrcaRouter",
         ["You: %s" % NAME, "Kernel: hello, %s. I will remember your name." % NAME, PROVIDER_QUESTION, PROVIDER_ENTER % "OrcaRouter"], "first name")
    step(run, "3\n", NOT_ONE_OR_TWO % "OrcaRouter", ["%s: 3" % NAME, NOT_ONE_OR_TWO % "OrcaRouter"], "first a provider that is not there")
    step(run, "2\n", KEY_QUESTION, ["%s: 2" % NAME, CHOSEN % "Anthropic", KEY_WHY, KEY_QUESTION], "first Anthropic chosen")
    step(run, ANTHROPIC_KEY + "\n", WORKS, [TRYING % len(ANTHROPIC_KEY), ANSWERED, WORKS], "first the key tried at Anthropic")
    step(run, ANTHROPIC_PASSWORD + "\n", SAME_AGAIN, [SAME_AGAIN], "first the password")
    step(run, ANTHROPIC_PASSWORD + "\n", "Kernel: pick a look", [LOCKING, LOCKED_ROW, LOOK_QUESTION], "first the key locked")
    step(run, "\n", "Kernel: look 1, Blue, stays", [stays("Blue")], "first the look")


def scenario_first():
    print("first: a fresh disk, Anthropic chosen; a restart; setup switching each way")
    disk, _ = answered_disk("anthropic-first", answers=())
    run = Run("anthropic-first", disk, behaviours=["good", "words=The Moon is our only natural satellite."])
    try:
        run.mark()
        run.wait_line("Kernel: what should I call you?", everything=True)
        time.sleep(0.5)
        run.at = 0
        first_boot_rows(run)
        line(run, "tell me about the moon", "The Moon is our only natural satellite.", "first a line to Anthropic")
    finally:
        run.end()
    check_posts(run, [("anthropic", ANTHROPIC_KEY, "try"), ("anthropic", ANTHROPIC_KEY, "line")], "first boot 1")
    kept = entries(disk)
    check("first the provider kept", kept.get("provider") == b"anthropic", kept.get("provider"))
    check("first no OrcaRouter key", "locked key" not in kept, sorted(kept))
    key_locked(disk, "locked key anthropic", ANTHROPIC_PASSWORD, ANTHROPIC_KEY, "first Anthropic's key locked under its own name")

    behaviours = ["words=Hello from Anthropic after a restart.", "good", "words=Hello from OrcaRouter.", "words=Hello from Anthropic again.",
                  "words=Still Anthropic."]
    run = Run("anthropic-first-2", disk, behaviours=behaviours)
    try:
        run.mark()
        run.wait_line(ANTHROPIC_PASSWORD_QUESTION, everything=True)
        time.sleep(0.5)
        start = [row for row in run.lines() if row.startswith(SHOWN)]
        check("first again the start", start[-2:] == [WELCOME, ANTHROPIC_PASSWORD_QUESTION], start[-2:])
        step(run, ANTHROPIC_PASSWORD + "\n", UNLOCKED, [UNLOCKING, UNLOCKED + TYPE_A_LINE], "first again the Anthropic key unlocked")
        line(run, "hello", "Hello from Anthropic after a restart.", "first again a line to Anthropic")

        # setup: OrcaRouter, whose key is typed, tried there, and locked under its own name.
        step(run, "setup\n", "Kernel: what should I call you?", ["%s: setup" % NAME, NAME_QUESTION % NAME], "first setup 1")
        step(run, "\n", PROVIDER_ENTER % "Anthropic", [NAME_STAYS, PROVIDER_QUESTION, PROVIDER_ENTER % "Anthropic"], "first setup 1 name")
        step(run, "1\n", KEY_QUESTION, ["%s: 1" % NAME, CHOSEN % "OrcaRouter", KEY_WHY, KEY_QUESTION], "first setup 1 OrcaRouter")
        step(run, ORCA_KEY + "\n", WORKS, [TRYING % len(ORCA_KEY), ANSWERED, WORKS], "first setup 1 the key tried at OrcaRouter")
        step(run, ORCA_PASSWORD + "\n", SAME_AGAIN, [SAME_AGAIN], "first setup 1 the password")
        step(run, ORCA_PASSWORD + "\n", "Kernel: pick a look", [LOCKING, LOCKED_ROW, LOOK_QUESTION], "first setup 1 the key locked")
        step(run, "\n", "Kernel: look 1, Blue, stays", [stays("Blue")], "first setup 1 the look")
        line(run, "hello there", "Hello from OrcaRouter.", "first setup 1 a line to OrcaRouter")

        # setup: Anthropic again; Enter alone keeps its locked key, which the change wiped from memory: its password now.
        step(run, "setup\n", "Kernel: what should I call you?", ["%s: setup" % NAME, NAME_QUESTION % NAME], "first setup 2")
        step(run, "\n", PROVIDER_ENTER % "OrcaRouter", [NAME_STAYS, PROVIDER_QUESTION, PROVIDER_ENTER % "OrcaRouter"], "first setup 2 name")
        step(run, "2\n", KEY_QUESTION_AGAIN, ["%s: 2" % NAME, CHOSEN % "Anthropic", KEY_QUESTION_AGAIN], "first setup 2 Anthropic")
        step(run, "\n", ANTHROPIC_PASSWORD_QUESTION, [ANTHROPIC_PASSWORD_QUESTION], "first setup 2 the password asked at once")
        step(run, ANTHROPIC_PASSWORD + "\n", "Kernel: pick a look", [UNLOCKING, UNLOCKED, LOOK_QUESTION], "first setup 2 the key unlocked")
        step(run, "\n", "Kernel: look 1, Blue, stays", [stays("Blue")], "first setup 2 the look")
        line(run, "and now", "Hello from Anthropic again.", "first setup 2 a line to Anthropic")

        # setup keeping Anthropic: Enter alone keeps the key, which is still in memory.
        step(run, "setup\n", "Kernel: what should I call you?", ["%s: setup" % NAME, NAME_QUESTION % NAME], "first setup 3")
        step(run, "\n", PROVIDER_ENTER % "Anthropic", [NAME_STAYS, PROVIDER_QUESTION, PROVIDER_ENTER % "Anthropic"], "first setup 3 name")
        step(run, "\n", KEY_QUESTION_AGAIN, [CHOSEN % "Anthropic", KEY_QUESTION_AGAIN], "first setup 3 Anthropic kept")
        step(run, "\n", "Kernel: pick a look", [KEY_STAYS, LOOK_QUESTION], "first setup 3 the key stays")
        step(run, "\n", "Kernel: look 1, Blue, stays", [stays("Blue")], "first setup 3 the look")
        line(run, "still there?", "Still Anthropic.", "first setup 3 a line to Anthropic")
    finally:
        run.end()
    check_posts(run, [("anthropic", ANTHROPIC_KEY, "line"), ("orcarouter", ORCA_KEY, "try"), ("orcarouter", ORCA_KEY, "line"),
                      ("anthropic", ANTHROPIC_KEY, "line"), ("anthropic", ANTHROPIC_KEY, "line")], "first boot 2")
    kept = entries(disk)
    check("first again the provider kept", kept.get("provider") == b"anthropic", kept.get("provider"))
    key_locked(disk, "locked key", ORCA_PASSWORD, ORCA_KEY, "first again OrcaRouter's key under its own name")
    key_locked(disk, "locked key anthropic", ANTHROPIC_PASSWORD, ANTHROPIC_KEY, "first again Anthropic's key unchanged")


def scenario_older():
    print("older: a disk from before the question: the password only, and OrcaRouter")
    locked = lock(ORCA_PASSWORD.encode(), ORCA_KEY.encode(), os.urandom(16), os.urandom(12), 600000)
    disk, _ = answered_disk("anthropic-older", answers=[("name", NAME.encode()), ("locked key", locked), ("look", b"")])
    run = Run("anthropic-older", disk, behaviours=["words=Hello from OrcaRouter, as before."])
    try:
        run.wait_line(PASSWORD_QUESTION, everything=True)
        time.sleep(0.5)
        start = [row for row in run.lines() if row.startswith(SHOWN)]
        check("older the start", start[-2:] == [WELCOME, PASSWORD_QUESTION], start[-2:])
        step(run, ORCA_PASSWORD + "\n", UNLOCKED, [UNLOCKING, UNLOCKED + TYPE_A_LINE], "older the key unlocked")
        line(run, "hello", "Hello from OrcaRouter, as before.", "older a line to OrcaRouter")
    finally:
        run.end()
    check_posts(run, [("orcarouter", ORCA_KEY, "line")], "older")
    check("older no provider written", "provider" not in entries(disk), sorted(entries(disk)))


def scenario_powercut():
    print("powercut: Anthropic kept as the provider, but no key for it")
    locked = lock(ORCA_PASSWORD.encode(), ORCA_KEY.encode(), os.urandom(16), os.urandom(12), 600000)
    answers = [("name", NAME.encode()), ("locked key", locked), ("provider", b"anthropic"), ("look", b"")]
    disk, _ = answered_disk("anthropic-powercut", answers=answers)
    run = Run("anthropic-powercut", disk, behaviours=[])
    try:
        run.wait_line(PROVIDER_ENTER % "Anthropic", everything=True)
        time.sleep(0.5)
        start = [row for row in run.lines() if row.startswith(SHOWN)]
        check("powercut the start", start[-3:] == [WELCOME, PROVIDER_QUESTION, PROVIDER_ENTER % "Anthropic"], start[-3:])
        step(run, "\n", KEY_QUESTION, [CHOSEN % "Anthropic", KEY_WHY, KEY_QUESTION], "powercut Anthropic kept")
        step(run, "\n", "Kernel: then no key", [NO_KEY_ROW], "powercut no key")
        step(run, "hello\n", NO_KEY, ["%s: hello" % NAME, NO_KEY], "powercut a line is not sent")
    finally:
        run.end()
    check_posts(run, [], "powercut")
    kept = entries(disk)
    check("powercut no key wanted for Anthropic", kept.get("locked key anthropic") == b"", kept.get("locked key anthropic"))
    check("powercut OrcaRouter's key as it was", kept.get("locked key") == locked, "changed")


NO_KEY_ROW = 'Kernel: then no key is kept. Send "setup" to give one later. Type a line and press Enter.'


def scenario_keyword():
    print("keyword: `key` while Anthropic is in use, then setup picking OrcaRouter")
    answers = [("name", NAME.encode()), ("provider", b"anthropic"), ("locked key anthropic", b""), ("look", b"")]
    disk, _ = answered_disk("anthropic-keyword", answers=answers)
    run = Run("anthropic-keyword", disk, behaviours=["words=Hello by the key of this start."])
    try:
        run.wait_line(WELCOME, everything=True)
        time.sleep(0.5)
        step(run, "key\n", "Kernel: type the secret", ["%s: key" % NAME, "Kernel: type the secret and press Enter. It shows as stars."], "keyword key")
        step(run, ANTHROPIC_KEY + "\n", "Kernel: I took a secret", ["Kernel: I took a secret of %d signs. It is kept in memory only." % len(ANTHROPIC_KEY)],
             "keyword the key taken")
        line(run, "hello", "Hello by the key of this start.", "keyword a line to Anthropic")
        step(run, "setup\n", "Kernel: what should I call you?", ["%s: setup" % NAME, NAME_QUESTION % NAME], "keyword setup")
        step(run, "\n", PROVIDER_ENTER % "Anthropic", [NAME_STAYS, PROVIDER_QUESTION, PROVIDER_ENTER % "Anthropic"], "keyword setup name")
        step(run, "1\n", KEY_QUESTION, ["%s: 1" % NAME, CHOSEN % "OrcaRouter", KEY_WHY, KEY_QUESTION], "keyword setup OrcaRouter")
        step(run, "\n", "Kernel: pick a look", ["Kernel: then no key is kept. Send \"setup\" to give one later.", LOOK_QUESTION], "keyword setup no key")
        step(run, "\n", "Kernel: look 1, Blue, stays", [stays("Blue")], "keyword setup the look")
        step(run, "hello again\n", NO_KEY, ["%s: hello again" % NAME, NO_KEY], "keyword the key of the start is gone")
    finally:
        run.end()
    check_posts(run, [("anthropic", ANTHROPIC_KEY, "line")], "keyword")


def scenario_events():
    print("events: Anthropic's endings and pieces, on lines")
    answers = [("name", NAME.encode()), ("provider", b"anthropic"), ("locked key anthropic", b""), ("look", b"")]
    disk, _ = answered_disk("anthropic-events", answers=answers)
    long_words = "words=These words break off in the middle, and only the first of them are ever said in the chat box."
    behaviours = ["a:refusal", "a:refusaltool", "a:window", "a:unknown", "a:overloaded", "a:stopnoend", "error:" + long_words,
                  "keepalive:words=Alive and well.", "thinkall", "cutwords", "routerusage", "nousage", "look=3", "a:forget"]
    run = Run("anthropic-events", disk, behaviours=behaviours)
    try:
        run.wait_line(WELCOME, everything=True)
        time.sleep(0.5)
        step(run, "key\n", "Kernel: type the secret", ["%s: key" % NAME, "Kernel: type the secret and press Enter. It shows as stars."], "events key")
        step(run, ANTHROPIC_KEY + "\n", "Kernel: I took a secret", ["Kernel: I took a secret of %d signs. It is kept in memory only." % len(ANTHROPIC_KEY)],
             "events the key taken")
        line(run, "one", FIRST_WORDS, "events checks after words", more=[CHECKS])
        line(run, "two", None, "events checks in a table", more=[CHECKS_TOOL])
        line(run, "three", FIRST_WORDS, "events the model's context", more=[WINDOW])
        line(run, "four", "Words after the unknown.", "events unknown kinds passed over")
        line(run, "five", FIRST_WORDS, "events overloaded", more=[OVERLOADED], tokens=chat_cases.NO_TOKENS_LINE)
        line(run, "six", FIRST_WORDS, "events no word about the end")
        broken = long_words[len("words="):]
        made = anthropic_cases.message_of(json.loads(chat_cases.body(chat_cases.message(broken))))
        half = anthropic_cases.sent_words(anthropic_cases.events(*made, ways=("error",)))
        line(run, "seven", half or None, "events a piece that breaks off", more=[BROKEN], tokens=chat_cases.NO_TOKENS_LINE)
        line(run, "eight", "Alive and well.", "events lines that say the link is alive")
        line(run, "nine", None, "events all of it thinking", more=[THOUGHT_ALL])
        line(run, "ten", "Here is the first part of", "events cut off at the limit", more=[CUT_OFF])
        line(run, "eleven", "Counted the router's way.", "events counts read back", tokens=chat_cases.TOKENS_ROUTER)
        line(run, "twelve", "No counts this time.", "events no counts", tokens=chat_cases.NO_TOKENS_LINE)
        # A tool, its inputs in pieces: the look is picked, and the row about it comes after the counts.
        step(run, "thirteen\n", "Kernel: this is look 3", ["%s: thirteen" % NAME, ASKING, chat_cases.TOKENS_LINE, "Kernel: this is look 3, Paper. It is kept on the disk."],
             "events a tool's inputs in pieces")
        # A tool that takes no inputs, whose one piece of them is empty: it is done, and the terminal names it alone.
        step(run, "fourteen\n", FORGOT, ["%s: fourteen" % NAME, ASKING, chat_cases.TOKENS_LINE, FORGOT], "events a tool with no inputs")
        tools = [text for text in run.since() if text.startswith("Tool:")]
        check("events the tool with no inputs in the terminal", tools == ["Tool: forget"], tools)
        check("events no table drawn", not any(text.startswith("Kernel: I drew") for text in run.lines()), "a table was drawn")
    finally:
        run.end()
    check_posts(run, [("anthropic", ANTHROPIC_KEY, "line")] * 14, "events")


SCENARIOS = {"first": scenario_first, "older": scenario_older, "powercut": scenario_powercut, "keyword": scenario_keyword,
             "events": scenario_events}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(SCENARIOS):
        try:
            SCENARIOS[name]()
        except Derailed as where:
            print("%s: the rest left out, after a row that never came (%s)" % (name, where))
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")
    sys.exit(1 if failures else 0)
