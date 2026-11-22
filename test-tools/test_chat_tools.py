"""Every line to the model (docs/tools.md, docs/chat.md, docs/model.md): each line typed in the chat box but `key`
and `setup` goes to the model with the list of tools, and the kernel says the model's words or does the tool it
asked for. Every scenario boots the stand-in copy of the project (net_copy.py), so that a break on purpose
(chat_tools_breaks.py, through BREAK) reaches all of them; the stand-in is model_server.py, with the answers of
chat_cases.py for a line. What is meant comes from chat_tools_model.py and apps_kept_model.py, written from the notes; every
request the stand-in saw is compared with what the notes say is sent, and the disk file is read from outside.
Made-up key only.

  nokey     no key kept: lines, the words that retired among them, get the row that no key is kept; nothing is sent.
  words     the model's words as rows of their own; the terminal's line about the tokens, in both places a provider
            gives them and when it gives none; an answer cut off, one spent on thinking, one with the key in it, a
            refusal, and a good answer without words or a tool.
  dice      the thing this part is done by: a line asks for an app, the model asks for make_app, the app is made, runs
            and is kept, and what it left on the screen goes back to the model; after a restart "roll the dice" runs
            the kept app without asking for it to be made again, in one request.
  pages     seven kept apps: the tool that turns the panel's page is offered, and turns it; a kept app by number; a
            page that is not there, which goes back to the model.
  odd       what the model may send that must not be believed: words beside a tool, two tools, a tool the kernel does
            not have, an odd name, inputs that cannot be read, numbers as text, numbers that fit nothing, and
            requests for an app that are long, odd, empty or hold the key; each that is turned down goes back.
  busy      a line sent while the answer to the one before is awaited.
  nocard    a machine without a network card.
  nodisk    a disk that is not divided: no notebook, so a look picked by the model lasts until the machine is off.
  remember  the thing remembering is done by: "I would like a dice to roll", then "make it roll two dice", which goes
            with the first line and what came of it, and nothing else.
  forgetting  what is not remembered and what forgets: with a name kept and a key unlocked by a password, the line
            `key` and its secret, a line that holds the key (starred), a line turned away while an answer is awaited,
            the tool `forget`, and `setup`, sent while an answer is awaited; every body searched for the name, the
            password and the key.
  bound     the bound on what is remembered: 10 lines, then 8,000 bytes when the rows are long.
  rounds    what a tool did goes back to the model: a new app that stops at a mistake goes back, and the model's fix
            is made, runs and is kept; a model that keeps asking gets three asks, the last without tools, and a tool
            in its last answer is not done; a look that is picked does not go back; a second tool goes back, and the
            same tool is not done twice for a line; an ask again that the provider turns down ends the line; an app
            that puts the key together goes back starred; `setup` while a new app is awaited stops the asks.

Usage: python test_chat_tools.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, chat_tools_breaks.py), BOOS_PORT_BASE (47300 for this lane)."""
import json
import os
import time

os.environ["DIVIDED_DISK"] = ""

import app_cases
import chat_cases
from apps_kept_model import app_things, kept_line, kept_script, note, read_things, screen
from chat_tools_model import (ASKING, BUSY, CANNOT_READ, CUT_OFF, FORGOT, MORE, NO_ADDRESS, NO_KEY, NO_REQUEST, NO_TOOL_LAST, NOT_TWICE,
                              THOUGHT_ALL, ToolsChat, body_again, body_meant, cannot_do, key_pieces, left_on_screen, making,
                              model_row, no_page_row, no_such_app, page_row, refused_row, request_cleaned, round_line, running,
                              terminal_says, words_cut)
from conversation_model import BYTES_REMEMBERED, LINES_REMEMBERED
from disk_helpers import make
from keyed_model import LOCKED
from lockref import lock
from test_apps_kept import (KEY, SCRIPT, Run, answer_row, answered_disk, failures, give_key, report, run_row)

SHOWN = ("You:", "Kernel:", "Model:", "Tokens:", "Apps:")
# Another made-up key, which shares no six signs with KEY, given in the middle of a scenario.
OTHER_KEY = "pk-test-QUILL/Rm6Hv9Tc3Wd8Yn2Lf5=="
# The check of JSON at startup, with its six checks of whole numbers (docs/json.md).
JSON_LINE = "JSON: 19 of 19 checks of making and reading it are right"
APP_BODY = {"model": "deepseek/deepseek-v4.1-flash-1017",
            "messages": [{"role": "system", "content": app_cases.INSTRUCTIONS}, {"role": "user", "content": None}],
            "max_tokens": app_cases.TOKENS, "stream": False}


def app_body(request):
    body = json.loads(json.dumps(APP_BODY))
    body["messages"][1]["content"] = app_cases.LEAD + request
    return body


def posts(run):
    """What the stand-in noted about each request to the model, in turn."""
    if not os.path.exists(run.log):
        return []
    notes = [json.loads(line) for line in open(run.log, encoding="utf-8") if line.strip()]
    return [n for n in notes if n.get("first line", "").startswith("POST ")]


def shown_since(run, shown=SHOWN):
    return [line for line in run.since() if line.startswith(shown)]


def exchange(run, chat, line, after, last=None, timeout=90, shown=SHOWN):
    """Sends `line` (the chat model takes it too), waits for the last line meant, and compares what the terminal
    showed since with the person's row, the row said at once, and the rows in `after`. Rows in `after` that belong in
    the chat box are added to the chat model, in turn with its other items: steps of the chat model's own (see
    remembered and AGAIN below), which the terminal does not show. `shown`: how the terminal's lines that count begin
    (the person's rows begin with their name when one is kept)."""
    run.mark()
    run.press(line + "\n", chat)
    pressed = time.time()
    rows = [item for item in after if isinstance(item, str)]
    meant = chat.said[-2:] + rows
    wanted = last or (rows[-1] if rows else meant[-1])
    # The last row meant may stand earlier too (the line about tokens does), so the wait is also for as many rows.
    end = time.time() + timeout
    while time.time() < end and (wanted not in run.since() or len(shown_since(run, shown)) < len(meant)):
        time.sleep(0.02)
    # How long the last line meant took to come after Enter, for a measurement (no verdict).
    run.answered_after = time.time() - pressed
    time.sleep(0.6)
    got = shown_since(run, shown)
    report(run.tag + " %r" % line[:24], got == meant, None if got == meant else "got %r, meant %r" % (got[-8:], meant[-8:]))
    for item in after:
        if not isinstance(item, str):
            item(chat)
        elif item.startswith(("Kernel:", "Model:")):
            chat.row(item)
    return got


def remembered(text):
    """A step for `exchange`: the kernel remembers a sentence with the line without saying it, such as what an app left
    behind when what it did goes back to the model. `text` may be a function that gives it, called when the step is
    taken, after the wait, for what is known only once the app has run (the number a dice rolled)."""
    return lambda chat: chat.remember(text() if callable(text) else text)


def AGAIN(chat):
    """A step for `exchange`: the kernel asks the model about the line again, with what came of it so far."""
    chat.again()


def rounds_since(run):
    """The terminal's lines about asking the model again, since the mark."""
    return [line for line in run.since() if line.startswith("Round ")]


def check_body(tag, note_, meant):
    body = note_.get("body") if note_ else None
    report(tag, body == meant, None if body == meant else "got %s" % json.dumps(body)[:300])
    if note_:
        report(tag + " key", note_.get("key came as") == "Bearer " + KEY)


def app_after(request, kind="app", kept=True):
    """What the terminal shows after the model asked for make_app with `request`, up to the line about keeping."""
    rows = [chat_cases.TOKENS_LINE, making(request), answer_row(kind), "Tokens: 12 in; 1000 out", run_row(kind)]
    return rows + ([kept_line(request)] if kept else [])


def back(words=chat_cases.AGAIN_WORDS):
    """What follows when what a tool did goes back to the model: it is asked about the line again (by the stand-in's
    default, answered with words), and the words come, with their tokens."""
    return [AGAIN, model_row(words), chat_cases.TOKENS_LINE]


def dice_left(run):
    """What a new dice app left on the screen, as the kernel remembers it: known once the app has run (see
    `remembered`)."""
    def left():
        found = app_lines_since(run, "You rolled a ")
        return left_on_screen("Dice: " + found[-1][len("You rolled a "):] if found else "(no dice line)")
    return left


def dice_back(run, words=chat_cases.AGAIN_WORDS):
    """What follows a new dice app's run, which goes back to the model with what the app left on the screen."""
    return [remembered(dice_left(run))] + back(words)


def app_lines_since(run, start):
    """The App lines since the mark that begin with `start`, without "App: "."""
    return [line[len("App: "):] for line in run.since() if line.startswith("App: " + start)]


def no_key_in(tag, lines):
    found = [line for line in lines if key_pieces(line, KEY)]
    report(tag + " no piece of the key in the terminal", not found, None if not found else "%r" % found[:2])


# ---------- The scenarios ----------

def scenario_nokey():
    print("nokey: no key kept, so nothing is sent")
    disk, _ = answered_disk("tools-nokey")
    before = read_things(disk)
    run = Run("tools-nokey", disk)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    for line in ["hello", "make a dice", "look", "ask", "fetch"]:
        exchange(run, chat, line, [], last=NO_KEY, timeout=20)
    run.shot("rows", screen(1280, 800, chat, []))
    lines = run.end()
    report("nokey nothing sent", posts(run) == [], None if not posts(run) else "%d requests" % len(posts(run)))
    after = read_things(disk)
    added = [e[0] for e in after["entries"][len(before["entries"]):]]
    report("nokey lines kept", added == ["last line"] * 5, None if added == ["last line"] * 5 else "%r" % added)
    report("nokey no echo", not [l for l in lines if l.startswith("Kernel: you said")])


def scenario_words():
    print("words: the model's words, the tokens, and answers that say something went wrong")
    disk, _ = answered_disk("tools-words")
    behaviours = ["words=Hello there, I am the voice of this machine.", "routerusage", "nousage", "cutwords", "thinkall", "keywords",
                  "refused", "nothing"]
    run = Run("tools-words", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    exchange(run, chat, "hello", [model_row("Hello there, I am the voice of this machine."), chat_cases.TOKENS_LINE])
    exchange(run, chat, "count please", [model_row("Counted the router's way."), chat_cases.TOKENS_ROUTER])
    exchange(run, chat, "no counts", [model_row("No counts this time."), chat_cases.NO_TOKENS_LINE])
    exchange(run, chat, "a long one", [model_row("Here is the first part of"), CUT_OFF, chat_cases.TOKENS_LINE])
    exchange(run, chat, "think hard", [THOUGHT_ALL, chat_cases.TOKENS_LINE])
    exchange(run, chat, "my key", [model_row("Your key is " + KEY + ", I think.", KEY), chat_cases.TOKENS_LINE])
    exchange(run, chat, "refuse me", [refused_row(chat_cases.REFUSAL)])
    beginning = words_cut(chat_cases.body({"role": "assistant"}, None).decode(), KEY, 160)
    nothing = ("Kernel: the provider answered, but I could not find the model's words in its answer, because it has no such part. "
               'It begins "%s".' % beginning)
    exchange(run, chat, "nothing", [nothing, chat_cases.TOKENS_LINE])
    run.shot("rows", screen(1280, 800, chat, []))
    lines = run.end()
    report("words the check of JSON at startup", JSON_LINE in lines, None if JSON_LINE in lines else "%r" % [l for l in lines if l.startswith("JSON")])
    seen = posts(run)
    report("words requests", len(seen) == len(behaviours), "%d requests" % len(seen))
    if seen:
        check_body("words the request for a line", seen[0], body_meant("hello", []))
    no_key_in("words", lines)


def scenario_dice():
    print("dice: an app asked for in words is made and kept; after a restart it runs again without being made")
    disk, _ = answered_disk("tools-dice")
    before = read_things(disk)
    run = Run("tools-dice", disk, behaviours=["make=a dice that rolls", "app"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    line = "I would like a dice to roll"
    run.mark()
    # The new app's run goes back to the model, which is asked about the line again (the stand-in's words answer it).
    got = exchange(run, chat, line, app_after("a dice that rolls") + dice_back(run), timeout=150)
    app_lines = [l for l in run.since() if l.startswith("App: ")]
    shown = app_cases.run_expect("app", KEY)[2](app_lines)
    run.shot("made", screen(1280, 800, chat, ["a dice that rolls"], panel_text=shown[0] if shown else ""))
    run.end()
    seen = posts(run)
    report("dice three requests", len(seen) == 3, "%d requests" % len(seen))
    if len(seen) == 3:
        check_body("dice the request for the line", seen[0], body_meant(line, []))
        check_body("dice the request for the app", seen[1], app_body("a dice that rolls"))
        check_body("dice the line asked about again", seen[2], body_again(line, [(1, "a dice that rolls")], chat.agains[0], key=KEY))
    after = read_things(disk)
    things = after["things"]
    report("dice script byte for byte", things.get("app 1 script", (0, b""))[1] == kept_script("app", KEY))
    report("dice note", things.get("app 1", (0, b""))[1] == note("a dice that rolls"))

    # The restart: the kept app, asked for in other words, runs as it was kept. The answer comes in the fuller
    # shape a real one may have, with thinking before the tool call (chat_cases.full_body).
    again = Run("tools-dice-again", disk, behaviours=["fullrun=1"])
    chat2 = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=line.encode())
    give_key(again, chat2)
    again.mark()
    exchange(again, chat2, "roll the dice", [chat_cases.TOKENS_LINE, running("a dice that rolls"), run_row("app")])
    app_lines = [l for l in again.since() if l.startswith("App: ")]
    shown = app_cases.run_expect("app", KEY)[2](app_lines)
    report("dice the kept app ran", bool(shown), None if shown else "no App line")
    again.shot("ran", screen(1280, 800, chat2, ["a dice that rolls"], panel_text=shown[0] if shown else ""))
    again.end()
    seen = posts(again)
    report("dice after the restart one request only", len(seen) == 1, "%d requests: %r" % (len(seen), [n.get("request for") for n in seen]))
    if seen:
        check_body("dice the request with the kept app", seen[0], body_meant("roll the dice", [(1, "a dice that rolls")]))
    third = read_things(disk)
    added = [e[0] for e in third["entries"][len(after["entries"]):]]
    report("dice nothing made again", added == ["last line", "last line"], None if added == ["last line", "last line"] else "%r" % added)


def scenario_pages():
    print("pages: seven kept apps, the panel's page turned by the model, and a kept app by number")
    items = []
    for number in range(1, 8):
        items += app_things(number, "app number %d of seven" % number, SCRIPT)
    disk, _ = answered_disk("tools-pages", items)
    apps = [(n, "app number %d of seven" % n) for n in range(7, 0, -1)]
    run = Run("tools-pages", disk, behaviours=["turn=2", "run=3", "turn=5"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    exchange(run, chat, "show me the next page", [chat_cases.TOKENS_LINE, page_row(2, 2)])
    run.shot("page-2", screen(1280, 800, chat, [r for _, r in apps], page=1))
    exchange(run, chat, "run the third one", [chat_cases.TOKENS_LINE, running("app number 3 of seven"), run_row("app")])
    # A page that is not there: the kernel turns it down, which goes back to the model.
    exchange(run, chat, "page five", [chat_cases.TOKENS_LINE, no_page_row(5, 2)] + back())
    run.end()
    seen = posts(run)
    report("pages requests", len(seen) == 4, "%d requests" % len(seen))
    if len(seen) == 4:
        check_body("pages the first request", seen[0], body_meant("show me the next page", apps, shown=1))
        # The second line goes with the first and what came of it (docs/tools.md, "What the model remembers").
        check_body("pages the second request", seen[1], body_meant("run the third one", apps, shown=2, record=chat.records[1]))
        check_body("pages the third line asked about again", seen[3], body_again("page five", apps, chat.agains[0], shown=2, key=KEY))


def scenario_odd():
    print("odd: what the model may send that must not be believed")
    disk, _ = answered_disk("tools-odd", app_things(1, "a dice that rolls", SCRIPT))
    behaviours = ["wordsrun=1", "two", "unknown", "oddname", "badinputs", "noinputs", "biginputs", "runtext=1", "run=7", "look=9",
                  "turn=3", "keyrequest", "app", "longrequest", "app", "oddrequest", "app", "emptyrequest"]
    run = Run("tools-odd", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    t = chat_cases.TOKENS_LINE
    # A kept app that runs to its end ends the line; everything the kernel turns down, a second tool and a new app go
    # back to the model, which is asked about the line again (the stand-in's words answer it).
    exchange(run, chat, "roll it", [model_row("Rolling it for you."), t, running("a dice that rolls"), run_row("app")])
    exchange(run, chat, "two looks", [t, MORE, "Kernel: this is look 3, Paper. It is kept on the disk."] + back())
    chat.look, chat.look_kept = "Paper", "Paper"
    exchange(run, chat, "format it", [t, cannot_do("format_disk")] + back())
    exchange(run, chat, "odd name", [t, cannot_do("\u0007" + chat_cases.LONG_NAME)] + back())
    exchange(run, chat, "which", [t, CANNOT_READ["run_app"]] + back())
    exchange(run, chat, "no inputs", [t, CANNOT_READ["pick_look"]] + back())
    exchange(run, chat, "too much", [t, CANNOT_READ["make_app"]] + back())
    exchange(run, chat, "as text", [t, running("a dice that rolls"), run_row("app")])
    exchange(run, chat, "app seven", [t, no_such_app(7)] + back())
    exchange(run, chat, "look nine", [t, "Kernel: the model asked for look 9, but there are only 4 looks."] + back())
    exchange(run, chat, "page three", [t, no_page_row(3, 1)] + back())
    keyed = request_cleaned(app_cases.hide("an app about " + KEY, KEY))
    exchange(run, chat, "an app with my key", app_after(keyed) + dice_back(run), timeout=150)
    long_request = request_cleaned(chat_cases.LONG_REQUEST)
    exchange(run, chat, "a long request", app_after(long_request) + dice_back(run), timeout=150)
    odd_request = request_cleaned(chat_cases.ODD_REQUEST)
    exchange(run, chat, "an odd request", app_after(odd_request) + dice_back(run), timeout=150)
    exchange(run, chat, "an empty request", [t, NO_REQUEST] + back())
    lines = run.end()
    seen = posts(run)
    again = [n for n in seen if n.get("asked again")]
    report("odd requests", len(seen) == len(behaviours) + 13 and len(again) == 13, "%d requests, %d of them again" % (len(seen), len(again)))
    apps_asked = [n["body"]["messages"][1]["content"] for n in seen if n.get("request for") == "an app"]
    meant = [app_cases.LEAD + r for r in (keyed, long_request, odd_request)]
    report("odd the requests for apps as sent", apps_asked == meant, None if apps_asked == meant else "%r" % apps_asked)
    no_key_in("odd", lines)
    things = read_things(disk)["things"]
    report("odd no piece of the key on the disk", not any(key_pieces(data.decode("latin-1"), KEY) for _, data in things.values()))


def scenario_busy():
    print("busy: a line while the answer to the one before is awaited")
    disk, _ = answered_disk("tools-busy")
    run = Run("tools-busy", disk, behaviours=["slowwords=At last."])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    run.mark()
    run.press("first\n", chat)
    chat.network = "busy"
    run.press("second\n", chat)
    chat.network = "ready"
    meant = chat.said[-4:] + [model_row("At last."), chat_cases.TOKENS_LINE]
    end = time.time() + 40
    while time.time() < end and chat_cases.TOKENS_LINE not in run.since():
        time.sleep(0.2)
    got = shown_since(run)
    report("busy rows", got == meant, None if got == meant else "got %r" % got)
    run.end()
    report("busy one request", len(posts(run)) == 1, "%d requests" % len(posts(run)))


def scenario_nocard():
    print("nocard: a machine without a network card")
    disk, _ = answered_disk("tools-nocard")
    run = Run("tools-nocard", disk, network=False)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    chat.network = "none"
    give_key(run, chat)
    exchange(run, chat, "hello", [], last=NO_ADDRESS, timeout=20)
    run.end()


def scenario_nodisk():
    print("nodisk: no notebook, so a look picked by the model lasts until the machine is switched off")
    disk = make("tools-nodisk.img", "16M")
    run = Run("tools-nodisk", disk, behaviours=["look=2"])
    chat = ToolsChat(1280, notebook=None, kept_look=None)
    give_key(run, chat)
    exchange(run, chat, "dark please", [chat_cases.TOKENS_LINE,
                                        "Kernel: this is look 2, Night. It lasts until the machine is switched off, because there is no notebook to keep it in."])
    chat.look = "Night"
    run.shot("night", screen(1280, 800, chat, []))
    run.end()


def bodies_meant(tag, run, chat, lines, apps=()):
    """Every request for a line the stand-in saw, against the request the notes say it goes with: `lines` are the
    lines that went to the model, in turn; each goes with the record the chat model kept for it, and with the key
    starred in the line and the record. Gives back the requests for a line."""
    seen = [n for n in posts(run) if n.get("request for") == "a line"]
    report(tag + " requests for a line", len(seen) == len(lines) == len(chat.records),
           "%d requests, %d lines meant, %d records kept" % (len(seen), len(lines), len(chat.records)))
    for number, (note_, line) in enumerate(zip(seen, lines)):
        record = chat.records[number] if number < len(chat.records) else ""
        check_body("%s line %d" % (tag, number + 1), note_, body_meant(line, list(apps), record=record, key=KEY))
    return seen


def record_of(note_):
    """The record a request went with: what stands behind the instructions in its system message."""
    told = note_["body"]["messages"][0]["content"] if note_ and note_.get("body") else ""
    _, lead, record = told.partition("\n\nWhat was said before the newest line, oldest first. ")
    return record.split("\n", 1)[1] if lead else ""


def scenario_remember():
    print("remember: a second line that only makes sense with the first goes together with the first")
    disk, _ = answered_disk("tools-remember")
    run = Run("tools-remember", disk, behaviours=["make=a dice that rolls", "app", "words=Two dice it is."])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    first, second = "I would like a dice to roll", "make it roll two dice"
    exchange(run, chat, first, app_after("a dice that rolls") + dice_back(run), timeout=150)
    rolled = app_lines_since(run, "You rolled a ")
    exchange(run, chat, second, [model_row("Two dice it is."), chat_cases.TOKENS_LINE])
    lines = run.end()
    seen = posts(run)
    report("remember four requests", len(seen) == 4, "%d requests" % len(seen))
    # What the second line is meant to go with, written out from the notes: the first line as the person's, the
    # kernel's three rows about it, what the app left on the screen, which went back to the model, and the model's
    # words when it was asked about the line again; not the row said at once, not the terminal's lines, not the script.
    left = left_on_screen("Dice: " + rolled[-1][len("You rolled a "):] if rolled else "(no dice line)")
    meant = "\n".join(["Person: " + first, making("a dice that rolls"), answer_row("app"), run_row("app"), "Kernel: " + left,
                       model_row(chat_cases.AGAIN_WORDS)])
    report("remember the chat model keeps the same record", chat.records == ["", meant], "%r" % chat.records)
    if len(seen) == 4:
        check_body("remember the first request", seen[0], body_meant(first, []))
        check_body("remember the first line asked about again", seen[2],
                   body_again(first, [(1, "a dice that rolls")], ("", "\n".join(meant.split("\n")[1:-1]))))
        check_body("remember the second request goes with the first", seen[3],
                   body_meant(second, [(1, "a dice that rolls")], record=meant))
        got = record_of(seen[3])
        report("remember exactly the remembered rows", got == meant, None if got == meant else "got %r" % got)
    no_key_in("remember", lines)


def scenario_forgetting():
    print("forgetting: what is never remembered, and what forgets")
    name, password = "Quillon", "Pw door 7"
    locked = lock(password.encode(), KEY.encode(), os.urandom(16), os.urandom(12), 600000)
    disk, _ = answered_disk("tools-forgetting", answers=[("name", name.encode()), ("locked key", locked), ("look", b"")])
    behaviours = ["words=Hello.", "words=Noted.", "slowwords=At last.", "words=You said hello.", "forget", "words=Fresh.",
                  "words=Still fresh.", "slowwords=Late words.", "words=Hello again."]
    run = Run("tools-forgetting", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=name.encode(), key_entry=LOCKED, password=password, kept_look=b"")
    chat.memory.key = KEY    # a line below holds the key: it goes, and is remembered, starred
    shown = SHOWN + (name + ":",)
    t = chat_cases.TOKENS_LINE
    sent = []

    def say(line, after, **more):
        exchange(run, chat, line, after, shown=shown, **more)
        sent.append(line)

    def steps(keys, last, tag):
        """Keys that answer the kernel's questions: what the terminal shows since, against the chat model."""
        run.mark()
        before = len(chat.said)
        run.press(keys, chat)
        end = time.time() + 30
        while time.time() < end and last not in "\n".join(run.since()):
            time.sleep(0.1)
        time.sleep(0.6)
        got, meant = shown_since(run, shown), chat.said[before:]
        report("forgetting " + tag, got == meant, None if got == meant else "got %r, meant %r" % (got[-6:], meant[-6:]))

    steps(password + "\n", "Kernel: the key is unlocked", "the password unlocks the key")
    say("hello there", [model_row("Hello."), t])
    run.mark()
    run.press("key\n" + KEY + "\n", chat)
    run.wait_line("Kernel: I took a secret of", timeout=30)
    say("key " + KEY, [model_row("Noted."), t])
    # A line sent while the answer to the one before is awaited is turned away, and not remembered.
    run.mark()
    run.press("slow one\n", chat)
    chat.network = "busy"
    run.press("while waiting\n", chat)
    chat.network = "ready"
    sent.append("slow one")
    end = time.time() + 40
    while time.time() < end and t not in run.since():
        time.sleep(0.2)
    time.sleep(0.6)
    meant = chat.said[-4:] + [model_row("At last."), t]
    got = shown_since(run, shown)
    report("forgetting busy rows", got == meant, None if got == meant else "got %r" % got)
    chat.row(model_row("At last."))
    say("what did I say?", [model_row("You said hello."), t])
    say("please start over", [t, FORGOT])
    say("first after forgetting", [model_row("Fresh."), t])
    say("second after forgetting", [model_row("Still fresh."), t])
    # `setup`, sent while the answer to a line is awaited: that line belongs to what is forgotten, so its answer, which
    # comes while the question for the name waits, is said and not remembered.
    run.mark()
    before = len(chat.said)
    run.press("slow again\n", chat)
    sent.append("slow again")
    run.press("setup\n", chat)
    end = time.time() + 40
    while time.time() < end and t not in run.since():
        time.sleep(0.2)
    time.sleep(0.6)
    chat.row(model_row("Late words."))
    got = [line for line in shown_since(run, shown) if not line.startswith("Tokens:")]
    meant = chat.said[before:]
    report("forgetting setup while an answer is awaited", got == meant, None if got == meant else "got %r, meant %r" % (got, meant))
    # The rest of `setup`: the name stays (Enter alone), the locked key stays (Enter alone), the first look stays.
    steps("\n", "Enter alone keeps the one locked", "setup asks for a key")
    steps("\n", "Kernel: pick a look by number", "setup asks for a look")
    steps("\n", "Type a line and press Enter.", "setup is over")
    say("after setup", [model_row("Hello again."), t])
    run.end()
    seen = bodies_meant("forgetting", run, chat, sent)
    records = [record_of(n) for n in seen]
    # sent[5] is the first line after `forget`, and sent[8] the line after `setup`: neither goes with anything, not
    # even with sent[7], whose answer came after `setup`.
    for place in (5, 8):
        if place < len(records):
            report("forgetting nothing remembered for %r" % sent[place], records[place] == "", "got %r" % records[place])
    if len(records) == len(sent):
        report("forgetting the line after the first after forgetting", records[6] == "Person: first after forgetting\n" + model_row("Fresh."),
               "got %r" % records[6])
        everything = "\n".join(json.dumps(n.get("body")) for n in seen)
        report("forgetting the name in no request", name not in everything)
        report("forgetting the password in no request", password not in everything)
        report("forgetting no piece of the key in any request", not key_pieces(everything, KEY))
        rows = [row for record in records for row in record.split("\n")]
        report("forgetting no line `key`, `setup` or turned away remembered",
               not any(row in ("Person: key", "Person: setup", "Person: while waiting") for row in rows))
        report("forgetting the line with the key went starred", seen[1]["body"]["messages"][1]["content"] == "key " + "*" * len(KEY),
               "got %r" % seen[1]["body"]["messages"][1]["content"])
        report("forgetting the line with the key remembered starred", ("Person: key " + "*" * len(KEY)) in records[2], "got %r" % records[2])


def scenario_bound():
    print("bound: 10 lines remembered, and never more than 8,000 bytes")
    disk, _ = answered_disk("tools-bound")
    shorts = ["line %d" % number for number in range(1, 13)]
    # Short lines whose answers bring the longest rows: typing a long line takes time and adds little.
    longs = ["long %02d" % number for number in range(1, 10)]
    behaviours = ["words=Ok %d." % number for number in range(1, 13)] + ["longall", "app:longrefusal"] * len(longs) + ["words=Done."]
    run = Run("tools-bound", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    t = chat_cases.TOKENS_LINE
    took = []    # seconds from Enter to the model's words, with the bytes of the record the line went with
    for number, line in enumerate(shorts):
        exchange(run, chat, line, [model_row("Ok %d." % (number + 1)), t], last=model_row("Ok %d." % (number + 1)))
        took.append((run.answered_after, len(chat.records[-1])))
    refusal = refused_row(words_cut(chat_cases.LONG_REASON, KEY, 300))
    for line in longs:
        exchange(run, chat, line, [model_row(chat_cases.LONG_WORDS, KEY), CUT_OFF, t, MORE, making(chat_cases.REQUEST_45), refusal],
                 timeout=120)
    exchange(run, chat, "the last one", [model_row("Done."), t], last=model_row("Done."))
    took.append((run.answered_after, len(chat.records[-1])))
    lines = run.end()
    # A measurement, not a verdict: the stand-in answers at once, so what grows with the record is what the kernel
    # takes to put the request together and hand it to the connection, 512 bytes at a time.
    print("  bound from Enter to the model's words: %s" % ", ".join("%.2f s with a record of %d bytes" % pair for pair in
                                                                 (took[0], took[len(shorts) - 1], took[-1])))
    seen = bodies_meant("bound", run, chat, shorts + longs + ["the last one"])
    if len(seen) == len(shorts) + len(longs) + 1:
        people = [row for row in record_of(seen[len(shorts) - 1]).split("\n") if row.startswith("Person: ")]
        meant = ["Person: " + line for line in shorts[1:len(shorts) - 1]]
        report("bound the 12th line goes with the 10 before it", people == meant and len(meant) == LINES_REMEMBERED, "got %r" % people)
        last = record_of(seen[-1])
        size = sum(len(row.encode()) + 1 for row in last.split("\n"))
        people = [row for row in last.split("\n") if row.startswith("Person: ")]
        report("bound the last line goes with at most %d bytes" % BYTES_REMEMBERED, size <= BYTES_REMEMBERED, "%d bytes" % size)
        report("bound the oldest long lines went first", people == ["Person: " + line for line in longs[1:]], "got %r" % people)
    no_key_in("bound", lines)


def scenario_rounds():
    print("rounds: what a tool did goes back to the model, at most three asks a line, the last without tools")
    disk, _ = answered_disk("tools-rounds")
    behaviours = [
        # A new app that stops at a mistake goes back; the model's fix, a new app with another request, runs, is
        # kept and goes back too; the third ask has no tools, and is answered in words.
        "runmistake", "again:make=a dice that rolls", "app", "again:words=Here is your dice.",
        # A model that keeps asking: a look that is not there, a page that is not there, and in its last answer a tool
        # again, which is not done.
        "look=9", "again:turn=4", "again:look=2",
        # A look that is picked ends the line: one ask.
        "look=3",
        # Two tools at once: the second, not done, goes back; asked for the first again, the kernel does not do it twice.
        "two", "again:look=3", "again:words=Paper it is.",
        # A look that is not there goes back, and the provider turns that ask down: the line ends there.
        "look=9", "again:refused",
        # An app that puts the key together and shows it: what it left goes back starred (the stand-in's words answer
        # that ask); after another key is given, the next line goes with it, still starred.
        "keyapp", "words=Hello again.",
        # `setup`, sent while a new app is awaited: the app comes, runs and is kept, and the model is not asked again.
        "slowapp",
    ]
    run = Run("tools-rounds", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    t = chat_cases.TOKENS_LINE
    tokens_app = "Tokens: 12 in; 1000 out"
    lines_meant, apps_meant = [], []    # every request meant, for a line and for an app, in turn
    dice = "a dice that rolls"
    kept = [(1, dice)]

    def mistake():
        found = app_lines_since(run, "Lua stopped: ")
        return terminal_says(found[0] if found else "(no line about the mistake)")

    def rolled():
        found = app_lines_since(run, "You rolled a ")
        return left_on_screen("Dice: " + found[0][len("You rolled a "):] if found else "(no dice line)")

    line = "make a dice"
    exchange(run, chat, line, [t, making("a dice"), answer_row("runmistake"), tokens_app, run_row("runmistake"), remembered(mistake), AGAIN,
                               t, making(dice), answer_row("app"), tokens_app, run_row("app"), kept_line(dice), remembered(rolled), AGAIN,
                               model_row("Here is your dice."), t], timeout=150)
    report("rounds the fix: two asks again", rounds_since(run) == [round_line(2), round_line(3)], "got %r" % rounds_since(run))
    rolls = app_lines_since(run, "You rolled a ")
    run.shot("fixed", screen(1280, 800, chat, [dice], panel_text="Dice: " + rolls[0][len("You rolled a "):] if rolls else ""))
    lines_meant += [body_meant(line, [], record=chat.records[-1], key=KEY), body_again(line, [], chat.agains[0], key=KEY),
                    body_again(line, kept, chat.agains[1], last=True, key=KEY)]
    apps_meant += [app_body("a dice"), app_body(dice)]

    line = "pick a look"
    exchange(run, chat, line, [t, "Kernel: the model asked for look 9, but there are only 4 looks.", AGAIN, t, no_page_row(4, 1), AGAIN,
                               t, NO_TOOL_LAST])
    report("rounds the model that keeps asking: two asks again", rounds_since(run) == [round_line(2), round_line(3)], "got %r" % rounds_since(run))
    lines_meant += [body_meant(line, kept, record=chat.records[-1], key=KEY), body_again(line, kept, chat.agains[2], key=KEY),
                    body_again(line, kept, chat.agains[3], last=True, key=KEY)]

    line = "make it paper"
    exchange(run, chat, line, [t, "Kernel: this is look 3, Paper. It is kept on the disk."])
    chat.look, chat.look_kept = "Paper", "Paper"
    report("rounds a look that is picked does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    run.shot("paper", screen(1280, 800, chat, [dice], panel_text="Dice: " + rolls[0][len("You rolled a "):] if rolls else ""))
    lines_meant += [body_meant(line, kept, record=chat.records[-1], key=KEY)]

    line = "two looks at once"
    exchange(run, chat, line, [t, MORE, "Kernel: this is look 3, Paper, which is kept on the disk already.", AGAIN, t, NOT_TWICE, AGAIN,
                               model_row("Paper it is."), t])
    lines_meant += [body_meant(line, kept, record=chat.records[-1], key=KEY), body_again(line, kept, chat.agains[4], key=KEY),
                    body_again(line, kept, chat.agains[5], last=True, key=KEY)]

    # An ask about a line again that the provider turns down says why, and ends the line: nothing more is asked.
    line = "look nine again"
    exchange(run, chat, line, [t, "Kernel: the model asked for look 9, but there are only 4 looks.", AGAIN, refused_row(chat_cases.REFUSAL)])
    time.sleep(2)
    report("rounds a refused ask ends the line", rounds_since(run) == [round_line(2)], "got %r" % rounds_since(run))
    lines_meant += [body_meant(line, kept, record=chat.records[-1], key=KEY), body_again(line, kept, chat.agains[6], key=KEY)]

    # The key, put together by an app and shown: starred when it is remembered, so that it stays starred when it goes
    # with a line after another key is given (the stars of the request are then for the other key only).
    line = "make a key app"
    exchange(run, chat, line, [t, making("a key app"), "Kernel: the model wrote an app of 1 line. It is shown in the terminal.", tokens_app,
                               "Kernel: the app ran to its end.", kept_line("a key app"), remembered(app_cases.hide(left_on_screen(KEY), KEY))]
             + back(), timeout=150)
    kept = [(2, "a key app")] + kept
    lines_meant += [body_meant(line, kept[1:], record=chat.records[-1], key=KEY), body_again(line, kept, chat.agains[7], key=KEY)]
    apps_meant += [app_body("a key app")]
    run.mark()
    run.press("key\n" + OTHER_KEY + "\n", chat)
    run.wait_line("Kernel: I took a secret of", timeout=30)
    line = "hello again"
    exchange(run, chat, line, [model_row("Hello again."), t])
    lines_meant += [(body_meant(line, kept, record=chat.records[-1], key=OTHER_KEY), OTHER_KEY)]

    # `setup` while the slow app is awaited: what came of it is not asked about, and the line goes nowhere again.
    line = "make a slow one"
    run.mark()
    run.press(line + "\n", chat)
    lines_meant += [(body_meant(line, kept, record=chat.records[-1], key=OTHER_KEY), OTHER_KEY)]
    apps_meant += [(app_body("a slow one"), OTHER_KEY)]
    asked = run.wait_line("Kernel: I am asking the model to make", timeout=60)
    report("rounds the slow app is asked for", asked == making("a slow one"), "got %r" % asked)
    run.press("setup\n")
    came = run.wait_line("Apps: ", timeout=60)
    report("rounds the slow app is kept after setup", came == kept_line("a slow one"), "got %r" % came)
    time.sleep(5)
    report("rounds setup stops the asks", rounds_since(run) == [], "got %r" % rounds_since(run))
    lines = run.end()

    seen = posts(run)
    lines_seen = [n for n in seen if n.get("request for") == "a line"]
    apps_seen = [n for n in seen if n.get("request for") == "an app"]
    report("rounds requests for a line", len(lines_seen) == len(lines_meant), "%d, meant %d" % (len(lines_seen), len(lines_meant)))
    report("rounds requests for an app", len(apps_seen) == len(apps_meant), "%d, meant %d" % (len(apps_seen), len(apps_meant)))
    # Each request meant, with the key it goes with (the other key after it was given).
    for kind, got, wanted in (("line", lines_seen, lines_meant), ("app", apps_seen, apps_meant)):
        for number, (note_, meant) in enumerate(zip(got, wanted)):
            body, key = meant if isinstance(meant, tuple) else (meant, KEY)
            tag = "rounds %s request %d" % (kind, number + 1)
            report(tag, note_.get("body") == body, None if note_.get("body") == body else "got %s" % json.dumps(note_.get("body"))[:300])
            report(tag + " key", note_.get("key came as") == "Bearer " + key)
    # The third ask about a line goes without tools, and only that one.
    offered = [n.get("tools offered") for n in lines_seen]
    meant_offered = [True, True, False, True, True, False, True, True, True, False, True, True, True, True, True, True]
    report("rounds tools offered", offered == meant_offered, "got %r" % offered)
    everything = "\n".join(json.dumps(n.get("body")) for n in seen)
    report("rounds no piece of either key in any request", not key_pieces(everything, KEY) and not key_pieces(everything, OTHER_KEY))
    # The fix: the mistake went back with the second ask, and the app the model asked for then was made and kept.
    if len(lines_seen) > 1:
        told = lines_seen[1]["body"]["messages"][0]["content"]
        report("rounds the mistake went back", "Kernel: the terminal says: \"Lua stopped: [string \"app\"]:3:" in told, "got %r" % told[-300:])
    things = read_things(disk)["things"]
    report("rounds the fix is kept", things.get("app 1 script", (0, b""))[1] == kept_script("app", KEY) and
           things.get("app 1", (0, b""))[1] == note(dice))
    no_key_in("rounds", lines)


SCENARIOS = {"nokey": scenario_nokey, "words": scenario_words, "dice": scenario_dice, "pages": scenario_pages, "odd": scenario_odd,
             "busy": scenario_busy, "nocard": scenario_nocard, "nodisk": scenario_nodisk, "remember": scenario_remember,
             "forgetting": scenario_forgetting, "bound": scenario_bound, "rounds": scenario_rounds}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
