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
            and is kept; after a restart "roll the dice" runs the kept app without asking for it to be made again.
  pages     seven kept apps: the tool that turns the panel's page is offered, and turns it; a kept app by number.
  odd       what the model may send that must not be believed: words beside a tool, two tools, a tool the kernel does
            not have, an odd name, inputs that cannot be read, numbers as text, numbers that fit nothing, and
            requests for an app that are long, odd, empty or hold the key.
  busy      a line sent while the answer to the one before is awaited.
  nocard    a machine without a network card.
  nodisk    a disk that is not divided: no notebook, so a look picked by the model lasts until the machine is off.

Usage: python test_chat_tools.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, chat_tools_breaks.py), BOOS_PORT_BASE (47300 for this lane)."""
import json
import os
import time

os.environ["DIVIDED_DISK"] = ""

import app_cases
import chat_cases
from apps_kept_model import app_things, kept_line, kept_script, note, read_things, screen
from chat_tools_model import (ASKING, BUSY, CANNOT_READ, CUT_OFF, MORE, NO_ADDRESS, NO_KEY, NO_REQUEST, THOUGHT_ALL, ToolsChat,
                              body_meant, cannot_do, key_pieces, making, model_row, no_page_row, no_such_app, page_row,
                              refused_row, request_cleaned, running, words_cut)
from disk_helpers import make
from test_apps_kept import (KEY, SCRIPT, Run, answer_row, answered_disk, failures, give_key, report, run_row)

SHOWN = ("You:", "Kernel:", "Model:", "Tokens:", "Apps:")
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


def shown_since(run):
    return [line for line in run.since() if line.startswith(SHOWN)]


def exchange(run, chat, line, after, last=None, timeout=90):
    """Sends `line` (the chat model takes it too), waits for the last line meant, and compares what the terminal
    showed since with the person's row, the row said at once, and `after`. Rows in `after` that belong in the chat
    box are added to the chat model."""
    run.mark()
    run.press(line + "\n", chat)
    meant = chat.said[-2:] + after
    wanted = last or (after[-1] if after else meant[-1])
    end = time.time() + timeout
    while time.time() < end and wanted not in run.since():
        time.sleep(0.1)
    time.sleep(0.6)
    got = shown_since(run)
    report(run.tag + " %r" % line[:24], got == meant, None if got == meant else "got %r, meant %r" % (got[-8:], meant[-8:]))
    for row in after:
        if row.startswith(("Kernel:", "Model:")):
            chat.row(row)
    return got


def check_body(tag, note_, meant):
    body = note_.get("body") if note_ else None
    report(tag, body == meant, None if body == meant else "got %s" % json.dumps(body)[:300])
    if note_:
        report(tag + " key", note_.get("key came as") == "Bearer " + KEY)


def app_after(request, kind="app", kept=True):
    """What the terminal shows after the model asked for make_app with `request`, up to the line about keeping."""
    rows = [chat_cases.TOKENS_LINE, making(request), answer_row(kind), "Tokens: 12 in; 1000 out", run_row(kind)]
    return rows + ([kept_line(request)] if kept else [])


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
    got = exchange(run, chat, line, app_after("a dice that rolls"), timeout=150)
    app_lines = [l for l in run.since() if l.startswith("App: ")]
    shown = app_cases.run_expect("app", KEY)[2](app_lines)
    run.shot("made", screen(1280, 800, chat, ["a dice that rolls"], panel_text=shown[0] if shown else ""))
    run.end()
    seen = posts(run)
    report("dice two requests", len(seen) == 2, "%d requests" % len(seen))
    if len(seen) == 2:
        check_body("dice the request for the line", seen[0], body_meant(line, []))
        check_body("dice the request for the app", seen[1], app_body("a dice that rolls"))
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
    exchange(run, chat, "page five", [chat_cases.TOKENS_LINE, no_page_row(5, 2)])
    run.end()
    seen = posts(run)
    report("pages requests", len(seen) == 3, "%d requests" % len(seen))
    if len(seen) == 3:
        check_body("pages the first request", seen[0], body_meant("show me the next page", apps, shown=1))
        check_body("pages the second request", seen[1], body_meant("run the third one", apps, shown=2))


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
    exchange(run, chat, "two looks", [t, MORE, "Kernel: this is look 3, Paper. It is kept on the disk."])
    chat.look, chat.look_kept = "Paper", "Paper"
    exchange(run, chat, "format it", [t, cannot_do("format_disk")])
    exchange(run, chat, "odd name", [t, cannot_do("\u0007" + chat_cases.LONG_NAME)])
    exchange(run, chat, "which", [t, CANNOT_READ["run_app"]])
    exchange(run, chat, "no inputs", [t, CANNOT_READ["pick_look"]])
    exchange(run, chat, "too much", [t, CANNOT_READ["make_app"]])
    exchange(run, chat, "as text", [t, running("a dice that rolls"), run_row("app")])
    exchange(run, chat, "app seven", [t, no_such_app(7)])
    exchange(run, chat, "look nine", [t, "Kernel: the model asked for look 9, but there are only 4 looks."])
    exchange(run, chat, "page three", [t, no_page_row(3, 1)])
    keyed = request_cleaned(app_cases.hide("an app about " + KEY, KEY))
    exchange(run, chat, "an app with my key", app_after(keyed), timeout=150)
    long_request = request_cleaned(chat_cases.LONG_REQUEST)
    exchange(run, chat, "a long request", app_after(long_request), timeout=150)
    odd_request = request_cleaned(chat_cases.ODD_REQUEST)
    exchange(run, chat, "an odd request", app_after(odd_request), timeout=150)
    exchange(run, chat, "an empty request", [t, NO_REQUEST])
    lines = run.end()
    seen = posts(run)
    report("odd requests", len(seen) == len(behaviours), "%d requests" % len(seen))
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


SCENARIOS = {"nokey": scenario_nokey, "words": scenario_words, "dice": scenario_dice, "pages": scenario_pages, "odd": scenario_odd,
             "busy": scenario_busy, "nocard": scenario_nocard, "nodisk": scenario_nodisk}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
