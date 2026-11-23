"""The stand-in's answers to a line typed in the chat box, which comes with the list of tools (docs/tools.md), in
the shape the provider's documentation gives and the model's maker shows: `choices[0].message` with `content`
and `tool_calls` (each with an id, the type "function", and a function with a name and its arguments as a text of
JSON), `finish_reason`, and `usage` with the counts the kernel reads. Shared by model_server.py, which sends them,
and test_chat_tools.py, which judges what the kernel makes of them.

A behaviour is a name, or a name, "=" and what it needs: "words=Hello there." answers in words, "make=a dice
that rolls" asks for the tool make_app with that request, "run=1" for run_app with the app 1, "look=2" for
pick_look, "turn=2" for turn_page (not "page", which is a kind of model_server.py's own); "fullrun=1" asks for run_app in the fuller shape a real answer may have
(`full_body`); "forget" asks for the tool forget; "longall" brings the longest rows a line can bring; "table=fruit"
asks for draw_table with a table of TABLES, "tablecut=long" with one that the limit of tokens cut off (CUT_LINES),
and "tablebad" with inputs that hold no table. Nothing runs when this file is imported."""
import json
import time

# What every answer says about the tokens it took, and the terminal's line the kernel is meant to print for it.
USAGE = {"prompt_tokens": 640, "completion_tokens": 42, "total_tokens": 682, "prompt_cache_hit_tokens": 600,
         "prompt_cache_miss_tokens": 40, "prompt_tokens_details": {"cached_tokens": 600},
         "completion_tokens_details": {"reasoning_tokens": 12}}
TOKENS_LINE = "Tokens: 640 in, 600 of them repeated; 42 out, 12 of them thinking"
# The router's own place for the repeated tokens, without the model maker's (docs/model.md).
USAGE_ROUTER = {"prompt_tokens": 500, "completion_tokens": 30, "total_tokens": 530, "prompt_tokens_details": {"cached_tokens": 450}}
TOKENS_ROUTER = "Tokens: 500 in, 450 of them repeated; 30 out"
NO_TOKENS_LINE = "Tokens: the provider did not say how many this answer took"
REFUSAL = "Invalid API key (request id: 20261120120000123456789CHAT)"


def call(name, arguments, number=0):
    """One tool call; `arguments` is put in as it is when it is a text, and as JSON otherwise."""
    return {"id": "call_%d" % number, "type": "function",
            "function": {"name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}}


def message(content=None, calls=None, reasoning="The person wants something done."):
    found = {"role": "assistant", "content": content}
    if reasoning is not None:
        found["reasoning_content"] = reasoning
    if calls:
        found["tool_calls"] = calls
    return found


def body(found, ending="stop", usage=USAGE):
    choice = {"index": 0, "message": found}
    if ending is not None:
        choice["finish_reason"] = ending
    whole = {"id": "gen-chat-1", "object": "chat.completion", "created": 1795000000,
             "model": "deepseek/deepseek-v4.1-flash-1017", "choices": [choice]}
    if usage is not None:
        whole["usage"] = usage
    return json.dumps(whole, separators=(",", ":")).encode()


# A thinking text as a real model may write it before a tool call: line ends, quotes, a backslash, signs that are
# not plain (sent as \u escapes), and brackets and the words of another tool call, which are only text.
THINKING = ('The person typed "roll the dice".\nA kept app fits: 1 is "a dice that rolls" — so run_app, not '
            '{"tool_calls": [{"function": {"name": "make_app", "arguments": "{}"}}]}.\n\\ café [done]')


def full_body(calls):
    """A good answer to a line in the fuller shape a real one may have: the words an empty text; the thinking in
    the three places the model's maker and the router give for it, all before the tool calls; each call with its
    place in the list first; fields the kernel does not read; and a space after every comma and colon."""
    found = {"role": "assistant", "content": "", "reasoning_content": THINKING, "reasoning": THINKING,
             "reasoning_details": [{"type": "reasoning.text", "text": THINKING, "format": "unknown", "index": 0}],
             "refusal": None, "tool_calls": [dict({"index": place}, **one) for place, one in enumerate(calls)]}
    choice = {"index": 0, "message": found, "logprobs": None, "finish_reason": "tool_calls",
              "native_finish_reason": "tool_calls"}
    whole = {"id": "gen-chat-2", "provider": "DeepSeek", "model": "deepseek/deepseek-v4.1-flash-1017",
             "object": "chat.completion", "created": 1795000000, "choices": [choice],
             "system_fingerprint": "fp_test", "usage": USAGE}
    return json.dumps(whole).encode()


def with_length(first, data):
    return first + b"\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(data) + data


def good(data):
    return with_length(b"HTTP/1.1 200 OK", data)


def request_of_line(line):
    """The request the stand-in gives make_app for a line like "make a dice": what follows the word, or the line."""
    return line[5:] if line.startswith("make ") else line


# Answers with something odd in them, each with what it is meant to show (see test_chat_tools.py).
LONG_REQUEST = "a dice that rolls and says what it rolled out loud every time"
ODD_REQUEST = "a dice\twith café signs\u0007 and a tail that goes on and on and on"
LONG_NAME = "x" * 100

# For the bound on what is remembered (docs/tools.md): the longest rows a line can bring. Words longer than the 300
# signs said; a request of the 45 signs kept; and, for the request for that app, a refusal whose reason is longer
# than the 300 signs said (model_server.py's "longrefusal").
LONG_WORDS = "These words are long on purpose, so that what the kernel remembers fills up quickly. " * 5
REQUEST_45 = "a dice that rolls and shows the number it got"
LONG_REASON = "This key may not ask for that, and here is a long reason why. " * 8

# Another ask about a line, when what a tool did needs the model (docs/tools.md, "When what a tool did goes back"), is
# known by the words that stand behind the record in its instruction text. model_server.py answers it with the next
# behaviour only when that begins with "again:" (what follows is a behaviour as for a line); otherwise with these
# words, and the list stays as it is, so that a list made for the lines alone keeps its order.
AGAIN_MARK = "\n\nWhat came of the newest line so far, oldest first. "
AGAIN_WORDS = "I see what came of it."

# Tables the stand-in describes with the tool draw_table (docs/tools.md), by name, as lines.
TABLES = {
    # Every kind of line, and a colour for each part, the rows' letters too faint on their background; widths narrower
    # than the longest cells, which widen their columns; a line that is no part of a table, and a title after the first row, both
    # skipped; a row written with a | at either end, one with a cell too many and one with a cell too few.
    "fruit": "\n".join([
        "title Fruit and what it costs",
        "colours head #1b5e20 head-letters #c8e6c9 rows #fffde7 letters #fff59d lines #33691e",
        "widths 8 12 5",
        "note this line is no part of a table",
        "head Fruit | Colour | Price",
        "row Apple | red | 0.40",
        "row Blackcurrant | very dark purple | 3.10",
        "title Not the title any more",
        "row | Banana | yellow | 0.25 |",
        "row Cherry | dark red | 2.80 | one too many",
        "row Kiwi | green",
    ]),
    # No colours and no widths, and more rows than fit.
    "big": "\n".join(["title Squares and cubes", "head Number | Square | Cube"]
                     + ["row %d | %d | %d" % (n, n * n, n * n * n) for n in range(1, 21)]),
    # A smaller one, with line ends of the other kind, capitals in its words, and colours written another way.
    "fewer": "\r\n".join(["TITLE Ten squares", "Colours: head=#0d47a1, head-letters=#ffffff", "Head Number | Square"]
                         + ["Row %d | %d" % (n, n * n) for n in range(1, 11)]),
    # For a description cut off: two columns and twelve rows.
    "long": "\n".join(["title Cut short", "head Line | Word"] + ["row Line %d | word %d" % (n, n) for n in range(1, 13)]),
    # For inputs longer than their bound of 4,096 bytes: sixty long rows.
    "many": "\n".join(["title Many long rows", "head Number | Words"] + ["row %d | %send" % (n, "word " * 12) for n in range(1, 61)]),
}

# The bound on what the model gives draw_table (docs/tools.md).
TABLE_INPUTS_LONGEST = 4096


def table_wide(bearer):
    """A table without a title or a head, whose first row has eight cells, with widths for all eight that add up to more
    than the room, and the key in a cell (the stand-in's "tablewide")."""
    return "\n".join(["widths 20 20 20 20 20 20 20 20", "row a | b | c | d | e | f | g | h",
                      "row key | " + bearer + " | 3 | 4 | 5 | 6 | 7 | 8", "row 1 | 2 | 3"])


def table_bound(name):
    """The text the kernel's reader takes out of what the model gives draw_table for the table `name` when that is
    longer than its bound: cut there, as far as it goes (the table holds no backslash form but the line end's)."""
    whole = json.dumps({"table": TABLES[name]})
    assert len(whole) > TABLE_INPUTS_LONGEST and whole.startswith('{"table": "')
    text = whole[:TABLE_INPUTS_LONGEST][len('{"table": "'):]
    if text.endswith("\\"):
        text = text[:-1]
    return text.replace("\\n", "\n")

# Where "tablecut" cuts what the model gives the tool: in the line end behind this many lines of the description,
# between its backslash and its n, as the limit of tokens may.
CUT_LINES = 9


def table_cut(name):
    """What the model gives draw_table for the table `name`, cut off as "tablecut" sends it, and the text the kernel's
    reader takes out of it: the first CUT_LINES lines, the last without its line end."""
    whole = json.dumps({"table": TABLES[name]})
    at = -1
    for _ in range(CUT_LINES):
        at = whole.index("\\n", at + 1)
    return whole[:at + 1], "\n".join(TABLES[name].split("\n")[:CUT_LINES])


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour, or None if `kind` is none of these."""
    name, _, given = kind.partition("=")
    if name == "words":
        return good(body(message(given))), "goodbye"
    if name == "slowwords":
        time.sleep(9)
        return good(body(message(given))), "goodbye"
    if name == "make":
        return good(body(message(None, [call("make_app", {"request": given})]), "tool_calls")), "goodbye"
    if name == "makeline":
        return good(body(message(None, [call("make_app", {"request": request_of_line(line)})]), "tool_calls")), "goodbye"
    if name == "run":
        return good(body(message(None, [call("run_app", {"app": int(given)})]), "tool_calls")), "goodbye"
    if name == "fullrun":
        return good(full_body([call("run_app", {"app": int(given)})])), "goodbye"
    if name == "runtext":
        return good(body(message(None, [call("run_app", {"app": given})]), "tool_calls")), "goodbye"
    if name == "wordsrun":
        return good(body(message("Rolling it for you.", [call("run_app", {"app": int(given)})]), "tool_calls")), "goodbye"
    if name == "look":
        return good(body(message(None, [call("pick_look", {"look": int(given)})]), "tool_calls")), "goodbye"
    if name == "turn":
        return good(body(message(None, [call("turn_page", {"page": int(given)})]), "tool_calls")), "goodbye"
    if name == "two":
        calls = [call("pick_look", {"look": 3}, 0), call("pick_look", {"look": 4}, 1)]
        return good(body(message(None, calls), "tool_calls")), "goodbye"
    if name == "forget":
        return good(body(message(None, [call("forget", {})]), "tool_calls")), "goodbye"
    if name == "longall":
        # Words past what is said, cut off at the limit, and two tools, the first asking for an app.
        calls = [call("make_app", {"request": REQUEST_45}, 0), call("pick_look", {"look": 2}, 1)]
        return good(body(message(LONG_WORDS, calls), "length")), "goodbye"
    if name == "unknown":
        return good(body(message(None, [call("format_disk", {})]), "tool_calls")), "goodbye"
    if name == "oddname":
        return good(body(message(None, [call("\u0007" + LONG_NAME, {})]), "tool_calls")), "goodbye"
    if name == "badinputs":
        return good(body(message(None, [call("run_app", "the first one, please")]), "tool_calls")), "goodbye"
    if name == "noinputs":
        bare = {"id": "call_0", "type": "function", "function": {"name": "pick_look"}}
        return good(body(message(None, [bare]), "tool_calls")), "goodbye"
    if name == "biginputs":
        return good(body(message(None, [call("make_app", {"request": "a dice", "notes": "n" * 2000})]), "tool_calls")), "goodbye"
    if name == "keyrequest":
        return good(body(message(None, [call("make_app", {"request": "an app about " + bearer})]), "tool_calls")), "goodbye"
    if name == "longrequest":
        return good(body(message(None, [call("make_app", {"request": LONG_REQUEST})]), "tool_calls")), "goodbye"
    if name == "oddrequest":
        return good(body(message(None, [call("make_app", {"request": ODD_REQUEST})]), "tool_calls")), "goodbye"
    if name == "emptyrequest":
        return good(body(message(None, [call("make_app", {"request": "   "})]), "tool_calls")), "goodbye"
    if name == "thinkall":
        return good(body(message("", reasoning="The person wants something. " * 60), "length")), "goodbye"
    if name == "cutwords":
        return good(body(message("Here is the first part of"), "length")), "goodbye"
    if name == "nothing":
        return good(body({"role": "assistant"}, None)), "goodbye"
    if name == "nousage":
        return good(body(message("No counts this time."), usage=None)), "goodbye"
    if name == "routerusage":
        return good(body(message("Counted the router's way."), usage=USAGE_ROUTER)), "goodbye"
    if name == "keywords":
        return good(body(message("Your key is " + bearer + ", I think."))), "goodbye"
    if name == "table":
        return good(body(message(None, [call("draw_table", {"table": TABLES[given]})]), "tool_calls")), "goodbye"
    if name == "tablecut":
        return good(body(message(None, [call("draw_table", table_cut(given)[0])]), "length")), "goodbye"
    if name == "tablewide":
        return good(body(message(None, [call("draw_table", {"table": table_wide(bearer)})]), "tool_calls")), "goodbye"
    if name == "tablebad":
        return good(body(message(None, [call("draw_table", {"rows": 3})]), "tool_calls")), "goodbye"
    if name == "fetch":
        return good(body(message(None, [call("download_file", {"address": given})]), "tool_calls")), "goodbye"
    if name == "remove":
        return good(body(message(None, [call("remove_file", {"file": int(given)})]), "tool_calls")), "goodbye"
    if name == "refused":
        error = {"error": {"code": "", "message": REFUSAL, "type": "orcarouter_api_error"}}
        return with_length(b"HTTP/1.1 401 Unauthorized", json.dumps(error, separators=(",", ":")).encode()), "goodbye"
    return None
