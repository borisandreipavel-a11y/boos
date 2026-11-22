"""Every line to the model (docs/tools.md, docs/chat.md, docs/model.md): each line typed in the chat box but `key`
and `setup` goes to the model with the list of tools, and the kernel says the model's words or does the tool it
asked for. Every scenario boots the stand-in copy of the project (net_copy.py), so that a break on purpose
(chat_tools_breaks.py, through BREAK) reaches all of them; the stand-in is model_server.py, with the answers of
chat_cases.py for a line. What is meant comes from chat_tools_model.py and apps_kept_model.py, written from the notes; every
request the stand-in saw is compared with what the notes say is sent, and the disk file is read from outside.
Made-up key only.

  nokey     no key kept: lines, the words that retired among them, get the row that no key is kept; nothing is sent.
  streaming live words and complete table rows, then a failed stream and a truncated rename.
  words     the model's words as rows of their own; the terminal's line about the tokens, in both places a provider
            gives them and when it gives none; an answer cut off, one spent on thinking, one with the key in it, a
            refusal, and a good answer without words or a tool.
  dice      the thing this part is done by: a line asks for an app, the model asks for make_app, the app is made, runs
            and is kept; after a restart "roll the dice" runs the kept app without asking for it to be made again.
  pages     seven kept apps: the tool that turns the panel's page is offered, and turns it; a kept app by number.
  odd       what the model may send that must not be believed: words beside a tool, two tools, a tool the kernel does
            not have, an odd name, inputs that cannot be read, numbers as text, numbers that fit nothing, and
            requests for an app that are long, odd, empty or hold the key.
  results   a failed app corrected, repeated inputs, a failed follow-up and the final round without tools.
  drawing   a table beside the apps, then changing one amount and repainting in another look.
  chart     a signed bar chart from the open saved table, with a look change and return to the table.
  diagram   a streamed flowchart, an edited label, edge strokes and dismissal.
  document_keys         local cell editing in a draft and a saved table, including cancel and restart.
  document_keys_full    a failed keyboard save retains both the saved value and the pending replacement.
  table_cut complete rows from a cut answer, bounds on text and rows, and refusal of malformed input.
  table_medium the smaller frame and key masking inside an escaped description.
  table_small the tool is absent on narrow screens and machines without a screen.
  cancel    a stopped kept app, its key-starred output, and setup during the follow-up.
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

Usage: python test_chat_tools.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, chat_tools_breaks.py), BOOS_PORT_BASE (47300 for this lane)."""
import json
import os
import time
from copy import copy

os.environ["DIVIDED_DISK"] = ""

import app_cases
import chat_cases
from apps_kept_model import app_things, kept_line, kept_script, note, read_things, screen
from chat_tools_model import (ASKING, BUSY, CANNOT_READ, CUT_OFF, FORGOT, MORE, NO_ADDRESS, NO_KEY, NO_REQUEST, THOUGHT_ALL,
                              ToolsChat, body_meant, cannot_do, key_pieces, making, model_row, no_page_row, no_such_app,
                              page_row, refused_row, request_cleaned, running, words_cut)
from conversation_model import BYTES_REMEMBERED, LINES_REMEMBERED
from disk_helpers import make
from drawing_model import bar_chart, diagram_picture, documents_panel, named_document, table
from keyed_model import LOCKED
from lockref import lock
from test_apps_kept import (KEY, SCRIPT, Run, answer_row, answered_disk, failures, give_key, report, run_row)

SHOWN = ("You:", "Kernel:", "Model:", "Tokens:", "Apps:")
# The check of JSON at startup, with its six checks of whole numbers (docs/json.md).
FOLLOW = [model_row("Done."), chat_cases.TOKENS_LINE]
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


def exchange(run, chat, line, after, last=None, timeout=90, shown=SHOWN, during=None):
    """Sends `line` (the chat model takes it too), waits for the last line meant, and compares what the terminal
    showed since with the person's row, the row said at once, and `after`. Rows in `after` that belong in the chat
    box are added to the chat model. `shown`: how the terminal's lines that count begin (the person's rows begin
    with their name when one is kept)."""
    run.mark()
    run.press(line + "\n", chat)
    pressed = time.time()
    if during is not None:
        during()
    meant = chat.said[-2:] + after
    wanted = last or (after[-2] if after[-2:] == FOLLOW else meant[-1])
    end = time.time() + timeout
    while time.time() < end and wanted not in run.since():
        time.sleep(0.02)
    # How long the last line meant took to come after Enter, for a measurement (no verdict).
    run.answered_after = time.time() - pressed
    time.sleep(0.6)
    got = shown_since(run, shown)
    report(run.tag + " %r" % line[:24], got == meant, None if got == meant else "got %r, meant %r" % (got[-8:], meant[-8:]))
    for row in after:
        if row == FOLLOW[0] and run_row("app") in after and any(r.startswith("Kernel: I am asking the model to make") for r in after):
            app_lines = [l for l in run.since() if l.startswith("App: ")]
            for detail in dice_output(app_lines):
                chat.memory.row(detail)
        if row.startswith(("Kernel:", "Model:")):
            chat.row(row)
    return got


def dice_output(lines):
    shown = app_cases.run_expect("app", KEY)[2](lines)
    return ["App showed: " + shown[0]] if shown else []


def check_body(tag, note_, meant):
    body = note_.get("body") if note_ else None
    report(tag, body == meant, None if body == meant else "got %s" % json.dumps(body)[:300])
    if note_:
        report(tag + " key", note_.get("key came as") == "Bearer " + KEY)


def app_after(request, kind="app", kept=True):
    """What the terminal shows after the model asked for make_app with `request`, up to the line about keeping."""
    rows = [chat_cases.TOKENS_LINE, making(request), answer_row(kind), "Tokens: 12 in; 1000 out", run_row(kind)]
    return rows + ([kept_line(request)] if kept else []) + FOLLOW


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


def scenario_streaming():
    print("streaming: words and table rows appear before the answer is whole")
    original = "head Item|Count\nrow Soup|2"
    disk, _ = answered_disk("tools-streaming", [("document 1", named_document("Budget", original))])
    run = Run("tools-streaming", disk, behaviours=["stream-chat", "stream-table", "stream-error", "stream-truncated"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    names = ["Budget"]
    gate = run.log + ".stream-next"
    if os.path.exists(gate):
        os.remove(gate)
    give_key(run, chat)

    def picture(model=chat):
        return documents_panel(screen(1280, 800, model, []), model, names)

    def advance():
        report("streaming preview had no committed reply", not any(
            row.startswith(("Model:", "Tokens:", "Kernel: I drew")) for row in run.since()))
        with open(gate, "w"):
            pass

    def live_words():
        live = copy(chat)
        live.rows = list(chat.rows)
        live.add("kernel", "Model: The balance is ready. ")
        run.shot("words-before-done", picture(live))
        advance()

    exchange(run, chat, "show the balance",
             [model_row("The balance is ready. " + KEY + " is private.", KEY), chat_cases.TOKENS_LINE],
             timeout=12, during=live_words)

    fruit_rows = [["Pear", "3"], ["Plum", "4"], ["Fig", "2"]]

    def fruit(count):
        return table(picture(), chat, "Fruit", [4, 5], ["Item", "Count"], fruit_rows[:count])

    def live_table():
        run.shot("first-complete-row", fruit(1))
        advance()
        run.shot("second-complete-row", fruit(2))
        advance()

    exchange(run, chat, "draw a fruit table", [chat_cases.TOKENS_LINE, "Kernel: I drew the table."],
             timeout=12, during=live_table)
    run.shot("final-row", fruit(3))

    def error_preview():
        width = 45
        run.shot("preview-before-error", table(picture(), chat, "", [width], ["Item"], [["Preview"]]))
        advance()

    exchange(run, chat, "draw another table",
             ["Kernel: the provider's stream ended with an error: Upstream stopped.", chat_cases.NO_TOKENS_LINE],
             timeout=12, during=error_preview)
    run.shot("restored-after-error", fruit(3))
    exchange(run, chat, "rename budget",
             ["Kernel: the provider's stream ended before the answer was complete.", chat_cases.NO_TOKENS_LINE],
             timeout=12)
    run.shot("name-unchanged", fruit(3))
    no_key_in("streaming", run.end())
    saved = read_things(disk)["things"]
    report("streaming the incomplete rename did not write the document",
           saved.get("document 1", (0, b""))[1] == named_document("Budget", original))
    seen = posts(run)
    report("streaming one request per line", len(seen) == 4)
    if len(seen) == 4:
        check_body("streaming asked for events and usage", seen[0], body_meant("show the balance", [], documents=(1, 1, names)))
        report("streaming chat uses HTTP/1.1", all(
            entry.get("first line") == "POST /v1/chat/completions HTTP/1.1" for entry in seen))
        report("streaming a final table is in the next request",
               seen[-1]["body"]["messages"][0]["content"].endswith("row Fig|2"))


def scenario_dice():
    print("dice: an app asked for in words is made and kept; after a restart it runs again without being made")
    disk, _ = answered_disk("tools-dice")
    before = read_things(disk)
    run = Run("tools-dice", disk, behaviours=["make=a dice that rolls", "app"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    line = "I would like a dice to roll"
    run.mark()
    got = exchange(run, chat, line, app_after("a dice that rolls"), timeout=150)
    app_lines = [l for l in run.since() if l.startswith("App: ")]
    shown = app_cases.run_expect("app", KEY)[2](app_lines)
    run.shot("made", screen(1280, 800, chat, ["a dice that rolls"], panel_text=shown[0] if shown else ""))
    run.end()
    seen = posts(run)
    report("dice three requests", len(seen) == 3, "%d requests" % len(seen))
    if len(seen) == 3:
        check_body("dice the request for the line", seen[0], body_meant(line, []))
        check_body("dice the request for the app", seen[1], app_body("a dice that rolls"))
        body = seen[2]["body"]
        result = body["messages"][0]["content"]
        report("dice sends the actual roll", bool(shown) and "App showed: " + shown[0] in result)
        report("dice follows the same line with the new app available",
               body["messages"][1] == {"role": "user", "content": line} and
               "run_app" in [tool["function"]["name"] for tool in body["tools"]])
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
    exchange(run, chat, "page five", [chat_cases.TOKENS_LINE, no_page_row(5, 2)] + FOLLOW)
    run.end()
    seen = posts(run)
    report("pages requests", len(seen) == 4, "%d requests" % len(seen))
    if len(seen) == 4:
        check_body("pages the first request", seen[0], body_meant("show me the next page", apps, shown=1))
        # The second line goes with the first and what came of it (docs/tools.md, "What the model remembers").
        check_body("pages the second request", seen[1], body_meant("run the third one", apps, shown=2, record=chat.records[1]))


def scenario_odd():
    print("odd: what the model may send that must not be believed")
    disk, _ = answered_disk("tools-odd", app_things(1, "a dice that rolls", SCRIPT))
    behaviours = ["wordsrun=1", "two", "unknown", "oddname", "badinputs", "noinputs", "biginputs", "runtext=1", "run=7", "look=9",
                  "turn=3", "keyrequest", "app", "longrequest", "app", "oddrequest", "app", "emptyrequest"]
    run = Run("tools-odd", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    t = chat_cases.TOKENS_LINE
    exchange(run, chat, "roll it", [model_row("Rolling it for you."), t, running("a dice that rolls"), run_row("app")])
    exchange(run, chat, "two looks", [t, MORE, "Kernel: this is look 3, Paper. It is kept on the disk."] + FOLLOW)
    chat.look, chat.look_kept = "Paper", "Paper"
    exchange(run, chat, "format it", [t, cannot_do("format_disk")] + FOLLOW)
    exchange(run, chat, "odd name", [t, cannot_do("\u0007" + chat_cases.LONG_NAME)] + FOLLOW)
    exchange(run, chat, "which", [t, CANNOT_READ["run_app"]] + FOLLOW)
    exchange(run, chat, "no inputs", [t, CANNOT_READ["pick_look"]] + FOLLOW)
    exchange(run, chat, "too much", [t, CANNOT_READ["make_app"]] + FOLLOW)
    exchange(run, chat, "as text", [t, running("a dice that rolls"), run_row("app")])
    exchange(run, chat, "app seven", [t, no_such_app(7)] + FOLLOW)
    exchange(run, chat, "look nine", [t, "Kernel: the model asked for look 9, but there are only 4 looks."] + FOLLOW)
    exchange(run, chat, "page three", [t, no_page_row(3, 1)] + FOLLOW)
    keyed = request_cleaned(app_cases.hide("an app about " + KEY, KEY))
    exchange(run, chat, "an app with my key", app_after(keyed), timeout=150)
    long_request = request_cleaned(chat_cases.LONG_REQUEST)
    exchange(run, chat, "a long request", app_after(long_request), timeout=150)
    odd_request = request_cleaned(chat_cases.ODD_REQUEST)
    exchange(run, chat, "an odd request", app_after(odd_request), timeout=150)
    exchange(run, chat, "an empty request", [t, NO_REQUEST] + FOLLOW)
    lines = run.end()
    seen = posts(run)
    report("odd requests", len(seen) == len(behaviours) + 13, "%d requests" % len(seen))
    apps_asked = [n["body"]["messages"][1]["content"] for n in seen if n.get("request for") == "an app"]
    meant = [app_cases.LEAD + r for r in (keyed, long_request, odd_request)]
    report("odd the requests for apps as sent", apps_asked == meant, None if apps_asked == meant else "%r" % apps_asked)
    no_key_in("odd", lines)
    things = read_things(disk)["things"]
    report("odd no piece of the key on the disk", not any(key_pieces(data.decode("latin-1"), KEY) for _, data in things.values()))


def scenario_results():
    print("results: fix a failed app, refuse a repeated action, and stop at the last answer")
    disk, _ = answered_disk("tools-results")
    behaviours = ["make=first try", "runmistake", "follow:make=fixed app", "runshow", "follow:words=It works.",
                  "run=99", "follow:runtext=99", "follow:look=3", "unknown", "follow:wrongkey", "look=2"]
    run = Run("tools-results", disk, behaviours=behaviours)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    for line, ending in [("make a greeting", "Model: It works."),
                         ("try twice", "Kernel: the model asked for another tool on its last answer"),
                         ("missing tool", "Kernel: the provider turned the question down"),
                         ("change look", "Kernel: this is look 2")]:
        run.mark()
        run.press(line + "\n")
        report("results " + line, run.wait_line(ending, timeout=60) is not None)
    lines = run.end()
    seen = posts(run)
    kinds = [n.get("request for") for n in seen]
    report("results requests in order", kinds == ["a line", "an app", "a follow-up", "an app", "a follow-up",
           "a line", "a follow-up", "a follow-up", "a line", "a follow-up", "a line"], str(kinds))
    if len(seen) == 11:
        bodies = [n["body"] for n in seen]
        told = [b["messages"][0]["content"] for b in bodies]
        report("results actual Lua error and corrected output",
               'App error: Lua stopped: [string "app"]:3:' in told[2] and "App showed: Hello from the app" in told[4])
        report("results three asks repeat the typed line",
               all(bodies[n]["messages"][1]["content"] == "make a greeting" for n in (0, 2, 4)))
        report("results last ask has no tools", "tools" in bodies[2] and "tools" not in bodies[4] and "tools" not in bodies[7])
        report("results single memory entry", told[5].count("Person: make a greeting") == 1 and "Model: It works." in told[5])
        report("results same effective inputs refused", "same tool with the same inputs" in told[7] and
               lines.count("Kernel: the model asked for app 99, but no kept app has that number.") == 1)
        report("results failed follow-up remembered", "provider turned the question down" in told[10])
    report("results terminal names each follow-up round", lines.count("Model round: 2 of 3.") == 3 and lines.count("Model round: 3 of 3.") == 2)
    report("results only corrected app kept", kept_script("runshow", KEY) == read_things(disk)["things"].get("app 1 script", (0, b""))[1])
    report("results final tool did not run", not any(l.startswith("Kernel: this is look 3") for l in lines))


def scenario_cancel():
    print("cancel: a stopped kept app reports its own output, and setup ends its pending follow-up")
    piece = KEY[8:16]
    numbers = ",".join(str(ord(c)) for c in piece)
    script = ('local s = string.char(%s)\nshow(s)\nerror("bad value " .. s)' % numbers).encode()
    disk, _ = answered_disk("tools-cancel", app_things(1, "a stopped app", script))
    run = Run("tools-cancel", disk, behaviours=["run=1", "follow:slowwords=Old answer."])
    give_key(run)
    run.mark()
    run.press("try it\n")
    report("cancel started the follow-up", run.wait_line("Model round: 2 of 3.") is not None)
    run.press("busy\n")
    report("cancel turned away the other line", BUSY in run.since())
    run.press("setup\n")
    deadline = time.time() + 30
    while time.time() < deadline and len(posts(run)) < 2:
        time.sleep(0.1)
    time.sleep(1)
    lines = run.end()
    seen = posts(run)
    report("cancel only the pending follow-up reached the server", [n.get("request for") for n in seen] == ["a line", "a follow-up"])
    if len(seen) == 2:
        told = seen[1]["body"]["messages"][0]["content"]
        report("cancel reported the failed kept app without the key", "App showed: ********" in told and
               "App error: Lua stopped:" in told and not key_pieces(told, KEY))
    report("cancel dropped the late answer", "Model: Old answer." not in lines)


def scenario_drawing():
    print("drawing: a table beside a kept app, and the same table in another look")
    apps = [(1, "an older app")]
    disk, _ = answered_disk("tools-drawing", app_things(1, apps[0][1], SCRIPT))
    description = ("title Fruit\nwidths 4 5\n"
                   "colours head #eeeeee head-letters #fefefe rows #102030 letters #101010 lines #445566\n"
                   "head Name | Count\nrow Pear | 3\nrow Plum")
    run = Run("tools-drawing", disk, behaviours=["table=" + description, "edit-pear", "look=3"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    line = "draw a fruit table"
    exchange(run, chat, line, [chat_cases.TOKENS_LINE, "Kernel: I drew the table."])
    colours = dict(head=(238, 238, 238), head_ink=(0, 0, 0), rows=(16, 32, 48),
                   ink=(255, 255, 255), lines=(68, 85, 102))

    def meant(amount):
        return table(screen(1280, 800, chat, [apps[0][1]]), chat,
                     "Fruit", [4, 5], ["Name", "Count"], [["Pear", amount], ["Plum", ""]], colours)

    run.shot("fruit", meant("3"))
    edit = "change pear to 7"
    exchange(run, chat, edit, [chat_cases.TOKENS_LINE, "Kernel: I drew the table."], timeout=20)
    run.shot("fruit-edited", meant("7"))
    look_line = "change the look"
    exchange(run, chat, look_line,
             [chat_cases.TOKENS_LINE, "Kernel: this is look 3, Paper. It is kept on the disk."])
    chat.look, chat.look_kept = "Paper", "Paper"
    run.shot("paper", meant("7"))
    run.end()
    seen = posts(run)
    report("drawing edit and look needed one request each", len(seen) == 3, "%d requests" % len(seen))
    if len(seen) == 3:
        check_body("drawing description of this screen's room", seen[0], body_meant(line, apps))
        original = ("title Fruit\ncolours head #eeeeee head-letters #fefefe rows #102030 letters #101010 lines #445566\n"
                    "widths 4 5\nhead Name|Count\nrow Pear|3\nrow Plum")
        check_body("drawing sends the displayed table to the edit", seen[1],
                   body_meant(edit, apps, record=chat.records[1], table=original))
        check_body("drawing sends the updated amount thereafter", seen[2],
                   body_meant(look_line, apps, record=chat.records[2], table=original.replace("Pear|3", "Pear|7")))

    again = Run("tools-drawing-again", disk)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"Paper", last_line=b"change the look")
    again.shot("no-table", screen(1280, 800, chat, [apps[0][1]]))
    again.end()


def scenario_diagram():
    print("diagram: a streamed flowchart stays in the frame and can be revised or closed")
    description = "widths 4 5\nhead Item|Count\nrow Pear|3"
    original = named_document("Budget", description)
    disk, _ = answered_disk("tools-diagram", [("document 1", original)])
    flowchart = chat_cases.FLOWCHART
    edited = flowchart.replace("Review", "Check") + "\nline 292 416 297 421\narrow 297 365 297 392"
    invalid = "line 0 0 5 5\nrect 297 421 2 2"
    extra = ["-vga", "std", "-global", "VGA.xres=1024", "-global", "VGA.yres=768"]
    run = Run("tools-diagram", disk, width=1024, height=768, extra=extra, behaviours=[
        "stream-flowchart", "draw_diagram=" + json.dumps({"drawing": edited}),
        "draw_diagram=" + json.dumps({"drawing": invalid}),
        'open_table={"name":"Budget"}', "draw_diagram=" + json.dumps({"drawing": flowchart}),
    ])
    chat = ToolsChat(1024, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    drawn = "Kernel: I drew the diagram. Press Esc to close it."

    def picture(active=None):
        return documents_panel(screen(1024, 768, chat, []), chat, ["Budget"], active=active)

    def wait_for_rest():
        run.shot("incomplete-drawing", picture())
        with open(run.log + ".stream-next", "w"):
            pass

    gate = run.log + ".stream-next"
    if os.path.exists(gate):
        os.remove(gate)
    exchange(run, chat, "draw a three step flowchart", [tokens, drawn], timeout=20, during=wait_for_rest)
    run.shot("three-steps", diagram_picture(picture(), chat))
    exchange(run, chat, "rename review to check", [tokens, drawn], timeout=20)
    run.shot("edited-at-the-edge", diagram_picture(picture(), chat, edited=True))
    run.m.named_key("f1")
    run.m.named_key("f2")
    run.shot("repaint-after-kernel-lines", diagram_picture(picture(), chat, edited=True))
    exchange(run, chat, "try drawing outside",
             [tokens, "Kernel: diagram line 2 has invalid inputs or goes outside the frame."] + FOLLOW, timeout=20)
    run.shot("outside-rejected", diagram_picture(picture(), chat, edited=True))
    run.m.named_key("esc")
    run.shot("cleared-diagram", picture())
    exchange(run, chat, "open budget", [tokens, 'Kernel: I opened "Budget".'], timeout=20)
    exchange(run, chat, "draw the flowchart again", [tokens, drawn], timeout=20)
    run.shot("diagram-over-table", diagram_picture(picture(active="Budget"), chat))
    run.m.named_key("esc")
    run.shot("source-table-restored", table(picture(active="Budget"), chat, "", [4, 5], ["Item", "Count"], [["Pear", "3"]]))
    run.end()
    saved = read_things(disk)["things"]
    report("diagram kept the original document", saved.get("document 1", (0, b""))[1] == original)
    seen = posts(run)
    report("diagram five lines and one tool refusal follow-up", len(seen) == 6)
    if len(seen) == 6:
        check_body("diagram offered inside the screen room", seen[0],
                   body_meant("draw a three step flowchart", [], width=1024, height=768, documents=(1, 1, ["Budget"])))
        check_body("diagram follow-up edit got the complete description", seen[1],
                   body_meant("rename review to check", [], width=1024, height=768, documents=(1, 1, ["Budget"]),
                             record=chat.records[1], diagram=flowchart))
        check_body("diagram dismissal clears its context", seen[4],
                   body_meant("open budget", [], width=1024, height=768, documents=(1, 1, ["Budget"]), record=chat.records[3]))


def scenario_chart():
    print("chart: the first bars use full signed values, keep the table, and follow the look")
    rows = [("Loss", "-5.5"), ("Flat", "0"), ("Gain", "12.25")] + [(f"R{i}", str(i)) for i in range(3, 14)]
    description = "title Budget\nwidths 5 4 4\nhead Item|Cash|Note\n" + "\n".join(f"row {name}|{value}|None" for name, value in rows)
    original = named_document("Budget", description)
    disk, _ = answered_disk("tools-chart", [("document 1", original)])
    extra = ["-vga", "std", "-global", "VGA.xres=1024", "-global", "VGA.yres=768"]
    run = Run("tools-chart", disk, width=1024, height=768, extra=extra, behaviours=[
        'open_table={"name":"Budget"}', "stream-chart",
        'chart_table={"label_column":1,"value_column":3}', "look=2",
        "table=head Item|Cash\nrow Rent|-10\nrow Food|-4.25", "stream-chart",
    ])
    chat = ToolsChat(1024, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    exchange(run, chat, "open budget", [tokens, 'Kernel: I opened "Budget". Only part of the full document fits on this screen.'])
    exchange(run, chat, "chart the budget", [tokens, "Kernel: I drew a bar chart from the open table. Showing the first 13 of 14 rows."])

    def picture(active="Budget"):
        return documents_panel(screen(1024, 768, chat, []), chat, ["Budget"], active=active)

    def chart_picture():
        return bar_chart(picture(), chat, "Cash by Item", rows[:13])

    run.shot("signed-amounts", chart_picture())
    exchange(run, chat, "chart the notes", [tokens, "Kernel: row 1 needs a plain number in column 3 for the bar chart."] + FOLLOW)
    run.shot("invalid-column-keeps-chart", chart_picture())
    exchange(run, chat, "switch to night", [tokens, "Kernel: this is look 2, Night. It is kept on the disk."])
    chat.look, chat.look_kept = "Night", "Night"
    run.shot("chart-in-night", chart_picture())
    run.m.named_key("tab")
    visible = [[name, value[:4], "None"] for name, value in rows[:13]]
    run.shot("return-to-table", table(picture(), chat, "Budget", [5, 4, 4], ["Item", "Cash", "Note"], visible,
                                      colours=dict(head_ink=(0, 0, 0))))

    exchange(run, chat, "draw a draft table", [tokens, "Kernel: I drew the table."])
    exchange(run, chat, "chart the draft", [tokens, "Kernel: I drew a bar chart from the open table."])
    run.shot("chart-of-draft", bar_chart(picture(active=None), chat, "Cash by Item", [("Rent", "-10"), ("Food", "-4.25")]))
    run.end()
    saved = read_things(disk)["things"]
    report("chart the original document stayed intact", saved.get("document 1", (0, b""))[1] == original)
    seen = posts(run)
    report("chart six requests and one correction", len(seen) == 7)
    if len(seen) == 7:
        check_body("chart waits for an open table before appearing in the tool list", seen[0],
                   body_meant("open budget", [], width=1024, height=768, documents=(1, 1, ["Budget"])))
        check_body("chart asks for two column positions and carries the whole table", seen[1],
                   body_meant("chart the budget", [], width=1024, height=768, documents=(1, 1, ["Budget"]),
                             record=chat.records[1], table="Saved document: Budget\n" + description))


def scenario_documents():
    print("documents: save a draft, make another document, then open and edit after restart")
    disk, _ = answered_disk("tools-documents", app_things(1, "an older app", SCRIPT))
    draft = "title Fruit\nwidths 4 5\nhead Name|Count\nrow Pear|3\nrow Plum|4"
    other = "title Lunch\nwidths 5 5\nhead Meal|Count\nrow Soup|2"
    run = Run("tools-documents", disk, behaviours=[
        "table=" + draft, 'save_table={"name":"Fruit budget"}',
        "save_table=" + json.dumps({"name": "Lunch", "table": other}),
        "save_table=" + json.dumps({"name": "fruit budget", "table": other}),
    ])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    exchange(run, chat, "draw a fruit budget", [tokens, "Kernel: I drew the table."], timeout=30)
    exchange(run, chat, "save it as fruit budget", [tokens, 'Kernel: I saved "Fruit budget".'], timeout=30)
    exchange(run, chat, "make and save lunch", [tokens, 'Kernel: I saved "Lunch".'], timeout=30)
    exchange(run, chat, "save over fruit budget",
             [tokens, 'Kernel: a document called "fruit budget" already exists. Open it before editing it.'] + FOLLOW, timeout=30)
    names = ["Lunch", "Fruit budget"]
    picture = documents_panel(screen(1280, 800, chat, ["an older app"]), chat, names, active="Lunch")
    run.shot("named-tables", table(picture, chat, "Lunch", [5, 5], ["Meal", "Count"], [["Soup", "2"]]))
    run.end()
    saved = read_things(disk)["things"]
    report("documents original saved by name", saved.get("document 1", (0, b""))[1] == named_document("Fruit budget", draft))
    report("documents one step save", saved.get("document 2", (0, b""))[1] == named_document("Lunch", other))

    run = Run("tools-documents-open", disk, behaviours=['open_table={"name":"fruit budget"}', "edit-pear"])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=b"save over fruit budget")
    run.shot("list-after-restart", documents_panel(screen(1280, 800, chat, ["an older app"]), chat, names))
    give_key(run, chat)
    exchange(run, chat, "open fruit budget", [tokens, 'Kernel: I opened "Fruit budget".'], timeout=30)
    exchange(run, chat, "change pear to 7", [tokens, 'Kernel: I updated "Fruit budget".'], timeout=30)
    picture = documents_panel(screen(1280, 800, chat, ["an older app"]), chat,
                              ["Fruit budget", "Lunch"], active="Fruit budget")
    run.shot("updated", table(picture, chat, "Fruit", [4, 5], ["Name", "Count"], [["Pear", "7"], ["Plum", "4"]]))
    run.end()
    seen = posts(run)
    report("documents open and edit each take one request", len(seen) == 2)
    if len(seen) == 2:
        check_body("documents the list is available without an open table", seen[0],
                   body_meant("open fruit budget", [(1, "an older app")], documents=(1, 1, names)))
        check_body("documents the edit sees the full named table", seen[1],
                   body_meant("change pear to 7", [(1, "an older app")], documents=(1, 1, names),
                             record=chat.records[1], table="Saved document: Fruit budget\n" + draft))
    switched = read_things(disk)["things"]
    want = draft.replace("Pear|3", "Pear|7")
    report("documents saved update and retained the other document",
           switched.get("document 1", (0, b""))[1] == named_document("Fruit budget", want) and switched.get("document 2") == saved.get("document 2"))


def scenario_documents_fit():
    print("documents_fit: the list pages and a complete saved table on a smaller screen")
    rows = [[f"Item {i}", "abcdefghijklmnopqrstuvwxyz"] for i in range(14)]
    original = "title Ledger\nwidths 8 26\nhead Item|Amount\n" + "\n".join("row " + "|".join(row) for row in rows)
    small = b"\x01head Item\nrow One"
    disk, _ = answered_disk("tools-documents-fit", [("table Ledger", b"\x01" + original.encode())]
                            + [(f"table Note {i}", small) for i in range(1, 9)])
    changed = original.replace("row Item 13|abcdefghijklmnopqrstuvwxyz", "row Item 13|99")
    extra = ["-vga", "std", "-global", "VGA.xres=1024", "-global", "VGA.yres=768"]
    run = Run("tools-documents-fit", disk, width=1024, height=768, extra=extra, behaviours=[
        'turn_document_page={"page":2}', 'open_table={"name":"Ledger"}',
        "update_table=" + json.dumps({"table": changed}), "words=Saved.",
    ])
    chat = ToolsChat(1024, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    exchange(run, chat, "show documents page two", [tokens, "Kernel: The documents list shows page 2 of 2."], timeout=30)
    run.shot("second-page", documents_panel(screen(1024, 768, chat, []), chat, ["Note 1", "Ledger"], page=2, pages=2))
    suffix = " Only part of the full document fits on this screen."
    exchange(run, chat, "open ledger", [tokens, 'Kernel: I opened "Ledger".' + suffix], timeout=30)
    exchange(run, chat, "set the last amount to 99", [tokens, 'Kernel: I updated "Ledger".' + suffix], timeout=30)
    exchange(run, chat, "confirm", [model_row("Saved."), tokens], timeout=30)
    run.end()
    seen = posts(run)
    report("documents_fit one request for each action", len(seen) == 4)
    if len(seen) == 4:
        check_body("documents_fit the hidden row went with the edit", seen[2],
                   body_meant("set the last amount to 99", [], width=1024, height=768, record=chat.records[2],
                             documents=(2, 2, ["Note 1", "Ledger"]), table="Saved document: Ledger\n" + original))
        system = seen[3]["body"]["messages"][0]["content"]
        report("documents_fit the hidden row in later requests shows the new amount", system.endswith("row Item 13|99"))
    disk_values = read_things(disk)
    report("documents_fit all rows survived the write", disk_values["things"].get("table Ledger", (0, b""))[1] == named_document("Ledger", changed))
    report("documents_fit the long update used notebook pieces", sum(n[0] == "table Ledger" for n in disk_values["entries"]) == 4)


def scenario_documents_full():
    print("documents_full: a failed update leaves the old document on screen and on disk")
    original = "title Budget\nwidths 4 5\nhead Item|Count\nrow Pear|3"
    expected_data = b"\x01" + original.encode()
    disk, last = answered_disk("tools-documents-full", [("table Budget", expected_data)], blocks=10)
    larger = "head Count\nrow " + "x" * 1900
    run = Run("tools-documents-full", disk, behaviours=[
        'open_table={"name":"Budget"}', "update_table=" + json.dumps({"table": larger}), "words=Still here.",
    ])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    exchange(run, chat, "open budget", [tokens, 'Kernel: I opened "Budget".'], timeout=30)
    exchange(run, chat, "replace the budget",
             [tokens, 'Kernel: I could not save "Budget", because the notebook is full.'] + FOLLOW, timeout=30)
    picture = documents_panel(screen(1280, 800, chat, []), chat, ["Budget"], active="Budget")
    run.shot("unchanged", table(picture, chat, "Budget", [4, 5], ["Item", "Count"], [["Pear", "3"]]))
    exchange(run, chat, "show the amount", [model_row("Still here."), tokens], timeout=30)
    run.end()
    seen = posts(run)
    report("documents_full kept the older text for the next request",
           len(seen) == 4 and seen[-1]["body"]["messages"][0]["content"].endswith("Saved document: Budget\n" + original))
    disk_values = read_things(disk, last=last)
    report("documents_full disk kept the previous complete version",
           disk_values["things"].get("table Budget", (0, b""))[1] == expected_data and
           sum(n[0] == "table Budget" for n in disk_values["entries"]) == 1)


def scenario_documents_names():
    print("documents_names: rename, remove, and reuse a name")
    fruit = "title Fruit\nwidths 4 5\nhead Item|Count\nrow Pear|3"
    lunch = "title Lunch\nwidths 4 5\nhead Meal|Count\nrow Soup|2"
    disk, _ = answered_disk("tools-documents-names", [
        ("table Fruit", b"\x01" + fruit.encode()), ("table Lunch", b"\x01" + lunch.encode()),
    ])
    tokens = chat_cases.TOKENS_LINE
    run = Run("tools-documents-names", disk, behaviours=[
        'open_table={"name":"Fruit"}', 'rename_table={"name":"Fruit","new_name":"lunch"}',
        'rename_table={"name":"fruit","new_name":"Fruit budget"}',
    ])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    exchange(run, chat, "open fruit", [tokens, 'Kernel: I opened "Fruit".'], timeout=30)
    exchange(run, chat, "rename it to lunch",
             [tokens, 'Kernel: a document called "lunch" already exists.'] + FOLLOW, timeout=30)
    exchange(run, chat, "rename to fruit budget", [tokens, 'Kernel: I renamed "Fruit" to "Fruit budget".'], timeout=30)
    picture = documents_panel(screen(1280, 800, chat, []), chat, ["Fruit budget", "Lunch"], active="Fruit budget")
    run.shot("renamed", table(picture, chat, "Fruit", [4, 5], ["Item", "Count"], [["Pear", "3"]]))
    run.end()
    saved = read_things(disk)["things"]
    report("documents_names rename kept the same key and contents",
           saved["table Fruit"][1] == named_document("Fruit budget", fruit) and saved["table Lunch"][1] == b"\x01" + lunch.encode())

    run = Run("tools-documents-remove", disk, behaviours=[
        'open_table={"name":"Fruit"}', 'open_table={"name":"fruit budget"}',
        'delete_table={"name":"Lunch"}', 'delete_table={"name":"Fruit budget"}',
        "save_table=" + json.dumps({"name": "Lunch", "table": "head Meal\nrow Salad"}),
    ])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=b"rename to fruit budget")
    run.shot("renamed-list-after-restart", documents_panel(screen(1280, 800, chat, []), chat, ["Fruit budget", "Lunch"]))
    give_key(run, chat)
    exchange(run, chat, "open fruit",
             [tokens, 'Kernel: I could not find a document called "Fruit".'] + FOLLOW, timeout=30)
    exchange(run, chat, "open fruit budget", [tokens, 'Kernel: I opened "Fruit budget".'], timeout=30)
    exchange(run, chat, "delete lunch", [tokens, 'Kernel: I removed "Lunch" from the documents list.'], timeout=30)
    picture = documents_panel(screen(1280, 800, chat, []), chat, ["Fruit budget"], active="Fruit budget")
    run.shot("other-removed", table(picture, chat, "Fruit", [4, 5], ["Item", "Count"], [["Pear", "3"]]))
    exchange(run, chat, "delete fruit budget", [tokens, 'Kernel: I removed "Fruit budget" from the documents list.'], timeout=30)
    run.shot("list-and-table-cleared", screen(1280, 800, chat, []))
    exchange(run, chat, "save a new lunch", [tokens, 'Kernel: I saved "Lunch".'], timeout=30)
    run.end()
    seen = posts(run)
    if len(seen) == 6:
        check_body("documents_names nothing deleted is advertised", seen[-1],
                   body_meant("save a new lunch", [], record=chat.records[-1]))
    report("documents_names all six expected requests", len(seen) == 6)
    saved = read_things(disk)["things"]
    report("documents_names the new lunch has its own identity",
           saved["table Fruit"][1] == saved["table Lunch"][1] == b"\x03" and
           saved["document 1"][1] == named_document("Lunch", "head Meal\nrow Salad"))

    run = Run("tools-documents-removed-again", disk)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=b"save a new lunch")
    run.shot("only-new-document-after-restart", documents_panel(screen(1280, 800, chat, []), chat, ["Lunch"]))
    run.end()


class TableKeysChat(ToolsChat):
    hint = None

    def typing_text(self):
        return self.hint or super().typing_text()


CELL_SELECTED = "Arrows move. Enter edits. Esc returns to chat."
CELL_EDITING = "Type to replace. Backspace deletes. Enter saves. Esc cancels."


def scenario_document_keys():
    print("document_keys: keyboard edits stay local and preserve the complete table")
    rows = [["Pear", "3"], ["Plum bow", ""]] + [[f"Item {i}", "4"] for i in range(2, 13)]
    records = ["row Pear|3", "row Plum bowl large"] + ["row " + "|".join(row) for row in rows[2:]]
    original = "\r\n".join(["title Budget", "widths 8 5", "head Item|Count"] + records + ["row Hidden|88888"])
    changed = original.replace("row Plum bowl large\r\n", "row Plum bowl larg|9\r\n")
    draft = "head Name|Count\nrow Soup|2"
    disk, _ = answered_disk("tools-document-keys", [("document 1", named_document("Budget", original))])
    extra = ["-vga", "std", "-global", "VGA.xres=1024", "-global", "VGA.yres=768"]
    run = Run("tools-document-keys", disk, width=1024, height=768, extra=extra, behaviours=[
        'open_table={"name":"Budget"}', "words=Checked.", "table=" + draft, 'save_table={"name":"Lunch"}',
    ])
    chat = TableKeysChat(1024, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    opened = 'Kernel: I opened "Budget". Only part of the full document fits on this screen.'
    exchange(run, chat, "open budget", [tokens, opened], timeout=30)

    def picture(focus=None, editing=False):
        canvas = documents_panel(screen(1024, 768, chat, []), chat, ["Budget"], active="Budget")
        return table(canvas, chat, "Budget", [8, 5], ["Item", "Count"], rows, focus=focus, editing=editing)

    run.press("check ", chat)
    for name in ("tab", "up", "left", "ret"):
        run.m.named_key(name)
    run.press("\b")
    chat.hint = CELL_EDITING
    rows[0][0] = "Pea"
    run.shot("backspace-existing-value", picture(focus=(0, 0), editing=True))
    run.m.named_key("esc")
    rows[0][0] = "Pear"
    chat.hint = CELL_SELECTED
    run.shot("cancelled-cell", picture(focus=(0, 0)))

    run.m.named_key("down")
    run.m.named_key("ret")
    run.press("\b")
    chat.hint = CELL_EDITING
    rows[1][0] = "owl larg"
    run.shot("backspace-clipped-value", picture(focus=(1, 0), editing=True))
    run.m.named_key("ret")
    rows[1][0] = "Plum bow"
    run.m.named_key("right")
    run.m.named_key("ret")
    run.press("93\b")
    rows[1][1] = "9"
    chat.hint = CELL_EDITING
    run.shot("editing-missing-cell", picture(focus=(1, 1), editing=True))
    run.m.named_key("ret")
    run.m.named_key("tab")
    chat.hint = None
    run.shot("saved-cell-and-chat-draft", picture())
    report("document_keys neither edit sent a request", len(posts(run)) == 1)

    exchange(run, chat, "table", [model_row("Checked."), tokens], timeout=30)
    exchange(run, chat, "draw lunch", [tokens, "Kernel: I drew the table."], timeout=30)
    for name in ("tab", "right", "ret"):
        run.m.named_key(name)
    run.press("7")
    run.m.named_key("ret")
    run.m.named_key("esc")
    exchange(run, chat, "save lunch", [tokens, 'Kernel: I saved "Lunch".'], timeout=30)
    run.end()
    seen = posts(run)
    report("document_keys only the four chat lines were sent", len(seen) == 4)
    if len(seen) == 4:
        check_body("document_keys next request had the full edited document", seen[1],
                   body_meant("check table", [], width=1024, height=768, record=chat.records[1],
                             documents=(1, 1, ["Budget"]), table="Saved document: Budget\n" + changed))
    saved = read_things(disk)["things"]
    report("document_keys disk retained hidden cells and rows",
           saved.get("document 1", (0, b""))[1] == named_document("Budget", changed))
    report("document_keys the saved draft kept its keyboard edit",
           saved.get("document 2", (0, b""))[1] == named_document("Lunch", draft.replace("Soup|2", "Soup|7")))

    run = Run("tools-document-keys-reopen", disk, behaviours=['open_table={"name":"Budget"}'],
              width=1024, height=768, extra=extra)
    chat = ToolsChat(1024, kept_name=b"", key_entry=b"", kept_look=b"", last_line=b"save lunch")
    give_key(run, chat)
    exchange(run, chat, "open budget", [tokens, opened], timeout=30)
    canvas = documents_panel(screen(1024, 768, chat, []), chat, ["Lunch", "Budget"], active="Budget")
    run.shot("reopened-cell", table(canvas, chat, "Budget", [8, 5], ["Item", "Count"], rows))
    run.end()


def scenario_document_keys_full():
    print("document_keys_full: a failed keyboard save keeps the old table and the pending edit")
    original = "head Item|Count\nwidths 4 5\nrow Pear|3"
    expected_data = b"\x01" + original.encode()
    # The notebook has room for the key and open lines before it fills.
    disk, last = answered_disk("tools-document-keys-full", [("table Budget", expected_data)], blocks=8)
    run = Run("tools-document-keys-full", disk, behaviours=['open_table={"name":"Budget"}'])
    chat = TableKeysChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    exchange(run, chat, "open budget", [chat_cases.TOKENS_LINE, 'Kernel: I opened "Budget".'], timeout=30)
    for name in ("tab", "right", "ret"):
        run.m.named_key(name)
    run.mark()
    run.press("9\n")
    trouble = 'Kernel: I could not save "Budget", because the notebook is full.'
    report("document_keys_full reported the failed save", run.wait_line(trouble, timeout=5) == trouble)
    chat.add("kernel", trouble)
    chat.hint = CELL_EDITING
    canvas = documents_panel(screen(1280, 800, chat, []), chat, ["Budget"], active="Budget")
    run.shot("replacement-still-editing",
             table(canvas, chat, "", [4, 5], ["Item", "Count"], [["Pear", "9"]], focus=(0, 1), editing=True))
    run.m.named_key("esc")
    run.m.named_key("esc")
    chat.hint = None
    canvas = documents_panel(screen(1280, 800, chat, []), chat, ["Budget"], active="Budget")
    run.shot("cancel-reveals-saved-value", table(canvas, chat, "", [4, 5], ["Item", "Count"], [["Pear", "3"]]))
    run.end()
    saved = read_things(disk, last=last)["things"]
    report("document_keys_full disk was unchanged", saved.get("table Budget", (0, b""))[1] == expected_data)
    report("document_keys_full only opening sent a request", len(posts(run)) == 1)


def scenario_table_cut():
    print("table_cut: only complete rows from an unfinished answer, and clipping at the frame")
    disk, _ = answered_disk("tools-table-cut")
    # Outer JSON is complete. The model's arguments string runs out during
    # a Unicode escape in the final row, after two complete rows.
    unfinished = r'{"table":"title Cut\nwidths 3 2\nhead Key | Q\nrow longer | 123 | skip\nrow A | B\nrow lost\u00'
    wide = ("title Full\nhead A | B | C | D | E | F | G\nwidths 100 1 1 1 1 1\n" +
            "\n".join("row %d | b | c | d | e | f" % n for n in range(20)) +
            "\ncolours head #000000")
    run = Run("tools-table-cut", disk, behaviours=[
        "tablecut=" + unfinished, "tablejson=" + unfinished,
        "table=head X\nrow " + "x" * 2048, "table=" + wide, "forget", "words=Fresh."])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    tokens = chat_cases.TOKENS_LINE
    exchange(run, chat, "draw a cut table", [CUT_OFF, tokens,
             "Kernel: I drew the table. Some text was shortened, extra cells were left out, "
             "the answer ended early and only complete rows were used."] + FOLLOW)

    def cut_picture():
        return table(screen(1280, 800, chat, []), chat, "Cut", [3, 2], ["Key", "Q"], [["lon", "12"], ["A", "B"]])

    run.shot("complete-rows", cut_picture())
    bad = [tokens, "Kernel: the model asked for a table, but I could not read its description."] + FOLLOW
    exchange(run, chat, "draw invalid", bad)
    exchange(run, chat, "draw over limit", bad)
    run.shot("kept-after-refusals", cut_picture())
    exchange(run, chat, "draw a large table", [tokens,
             "Kernel: I drew the table. Extra cells were left out, column widths were changed to fit, "
             "rows below the frame were left out."] + FOLLOW)
    rows = [[str(n), "b", "c", "d", "e", "f"] for n in range(14)]
    run.shot("full-frame", table(screen(1280, 800, chat, []), chat, "Full", [7, 7, 7, 7, 7, 6], list("ABCDEF"), rows))
    exchange(run, chat, "forget", [tokens, FORGOT])
    run.shot("table-cleared", screen(1280, 800, chat, []))
    exchange(run, chat, "hello", [model_row("Fresh."), tokens])
    run.end()
    seen = posts(run)
    report("table_cut every affected line had a follow-up",
           [n.get("request for") for n in seen] == ["a line", "a follow-up"] * 4 + ["a line"] * 2)
    if len(seen) == 10:
        first_follow = seen[1]["body"]["messages"][0]["content"]
        report("table_cut the follow-up sees only the displayed rows",
               "head Key|Q\nrow lon|12\nrow A|B" in first_follow and "row lost" not in first_follow)
        check_body("table_cut forgot the table and chat history", seen[-1], body_meant("hello", []))


def scenario_table_medium():
    print("table_medium: a frame on 1024 by 768 and key masking inside escaped input")
    disk, _ = answered_disk("tools-table-medium")
    fragment = KEY[8:16]
    description = "title " + fragment + "\nwidths 3 3\nhead A | B\n"
    description += "\n".join("row %d | x" % n for n in range(13))
    escaped = "".join(r"\u%04x" % ord(sign) for sign in fragment)
    arguments = json.dumps({"table": description}).replace(fragment, escaped)
    extra = ["-vga", "std", "-global", "VGA.xres=1024", "-global", "VGA.yres=768"]
    run = Run("tools-table-medium", disk, width=1024, height=768, extra=extra, behaviours=["tablejson=" + arguments])
    chat = ToolsChat(1024, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    line = "draw thirteen rows"
    exchange(run, chat, line, [chat_cases.TOKENS_LINE, "Kernel: I drew the table."])
    cells = [[str(n), "x"] for n in range(13)]
    meant = table(screen(1024, 768, chat, []), chat, "*" * len(fragment), [3, 3], ["A", "B"], cells)
    run.shot("rows-and-stars", meant)
    run.end()
    seen = posts(run)
    report("table_medium one request", len(seen) == 1)
    if seen:
        check_body("table_medium advertises the smaller frame", seen[0], body_meant(line, [], width=1024, height=768))


def scenario_table_small():
    print("table_small: a narrow screen offers no tool and refuses a table")
    disk, _ = answered_disk("tools-table-small")
    run = Run("tools-table-small", disk, width=800, height=600, extra=["-vga", "cirrus"],
              behaviours=["table=head A | B\nrow x | y"])
    chat = ToolsChat(800, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    line = "draw a table"
    exchange(run, chat, line, [chat_cases.TOKENS_LINE, "Kernel: this screen has no room for a table."] + FOLLOW)
    run.shot("no-frame", screen(800, 600, chat, []))
    run.end()
    seen = posts(run)
    report("table_small refused before drawing", len(seen) == 2)
    if seen:
        check_body("table_small no drawing tool advertised", seen[0], body_meant(line, [], width=800, height=600))

    headless = Run("tools-table-headless", disk, extra=["-vga", "none"], behaviours=["words=Hello."])
    give_key(headless)
    headless.mark()
    headless.press("hello\n")
    report("table_small headless chat still works", headless.wait_line("Model: Hello.") is not None)
    headless.end()
    seen = posts(headless)
    report("table_small one headless request", len(seen) == 1)
    if seen:
        check_body("table_small no drawing tool when headless", seen[0], body_meant("hello", [], width=0, height=0))


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


def bounded_follow_up(note):
    system, user = note["body"]["messages"]
    earlier, mark, newest = system["content"].partition("\n\nWhat your tools did for the newest line follows.")
    if not mark or "\n" not in newest:
        return False
    _, record_lead, history = earlier.partition("\n\nWhat was said before the newest line, oldest first. ")
    rows = history.splitlines()[1:] if record_lead else []
    rows.append("Person: " + user["content"])
    rows.extend(newest.splitlines()[1:])
    return sum(len(row.encode()) + 1 for row in rows) <= BYTES_REMEMBERED


def scenario_remember():
    print("remember: a second line that only makes sense with the first goes together with the first")
    disk, _ = answered_disk("tools-remember")
    run = Run("tools-remember", disk, behaviours=["make=a dice that rolls", "app", "words=Two dice it is."])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    first, second = "I would like a dice to roll", "make it roll two dice"
    exchange(run, chat, first, app_after("a dice that rolls"), timeout=150)
    exchange(run, chat, second, [model_row("Two dice it is."), chat_cases.TOKENS_LINE])
    lines = run.end()
    seen = posts(run)
    report("remember four requests", len(seen) == 4, "%d requests" % len(seen))
    # What the second line is meant to go with, written out from the notes: the first line as the person's, and the
    # kernel's three rows about it; not the row said at once, not the terminal's lines, not the script.
    output = dice_output([l for l in lines if l.startswith("App: You rolled a ")])
    meant = "\n".join(["Person: " + first, making("a dice that rolls"), answer_row("app"), run_row("app")] + output + [FOLLOW[0]])
    report("remember the chat model keeps the same record", chat.records == ["", meant], "%r" % chat.records)
    if len(seen) == 4:
        check_body("remember the first request", seen[0], body_meant(first, []))
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
        exchange(run, chat, line, [model_row(chat_cases.LONG_WORDS, KEY), CUT_OFF, t, MORE, making(chat_cases.REQUEST_45), refusal] + FOLLOW,
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
    follows = [n for n in posts(run) if n.get("request for") == "a follow-up"]
    report("bound includes the pending results", len(follows) == len(longs) and all(bounded_follow_up(n) for n in follows))
    no_key_in("bound", lines)


SCENARIOS = {"streaming": scenario_streaming, "documents": scenario_documents, "documents_fit": scenario_documents_fit, "documents_full": scenario_documents_full,
             "documents_names": scenario_documents_names,
             "document_keys": scenario_document_keys, "document_keys_full": scenario_document_keys_full,
             "drawing": scenario_drawing, "chart": scenario_chart, "diagram": scenario_diagram, "table_cut": scenario_table_cut,
             "table_medium": scenario_table_medium, "table_small": scenario_table_small,
             "cancel": scenario_cancel, "results": scenario_results, "nokey": scenario_nokey, "words": scenario_words, "dice": scenario_dice, "pages": scenario_pages, "odd": scenario_odd,
             "busy": scenario_busy, "nocard": scenario_nocard, "nodisk": scenario_nodisk, "remember": scenario_remember,
             "forgetting": scenario_forgetting, "bound": scenario_bound}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
