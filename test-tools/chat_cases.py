"""The stand-in's answers to a line typed in the chat box, which comes with the list of tools (docs/tools.md), in
the shape the provider's documentation gives and the model's maker shows: `choices[0].message` with `content`
and `tool_calls` (each with an id, the type "function", and a function with a name and its arguments as a text of
JSON), `finish_reason`, and `usage` with the counts the kernel reads. Shared by model_server.py, which sends them,
and test_chat_tools.py, which judges what the kernel makes of them.

A behaviour is a name, or a name, "=" and what it needs: "words=Hello there." answers in words, "make=a dice
that rolls" asks for the tool make_app with that request, "run=1" for run_app with the app 1, "makein=" and "runin="
with a text of JSON behind them for make_app and run_app given exactly that (an app's inputs and values), "look=2" for
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


# ---------- Answers piece by piece ----------

# A line's request asks for its answer piece by piece (docs/model.md). The stand-in then sends a good answer the way the
# model's maker documents it: the notes say "text/event-stream" and give no length, and each piece is a line "data: "
# with a piece of JSON ("chat.completion.chunk", its words, thinking or part of a tool at choices[0].delta), an empty
# line after it, and "data: [DONE]" at the end. First a piece with the role; then the thinking, then the words, a few
# signs to a piece; then each tool call, its name in its first part and what it gives the tool in pieces of a few
# signs; last a piece that says how the answer ended and holds the counts. A behaviour may put ways in front of its name
# ("hold:words=..."), which change that (STREAM_WAYS).
STREAM_HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n"
WORDS_PIECE, THINKING_PIECE, INPUTS_PIECE = 6, 12, 10
# "hold": the stand-in holds the answer once this many signs of its words went, until the test lets it go on.
HOLD_SIGNS = 120
# The ways: hold after HOLD_SIGNS signs of words, or after the thinking; end the connection in the middle of the words
# or the tool ("cut"), or send a piece that breaks the answer off there ("error"); end it as the model's maker's
# "aborted"; the counts in a piece of their own with no choices, as the router's documentation has them
# ("usagealone"); and lines that only say the link is alive before the first piece ("keepalive").
STREAM_WAYS = ("hold", "holdthinking", "cut", "error", "aborted", "usagealone", "keepalive")
BREAK_MESSAGE = "Upstream provider dropped the stream"


def stream_ways(kind):
    """Gives (the ways in front of a behaviour's name, the behaviour without them)."""
    ways = []
    while True:
        first, colon, rest = kind.partition(":")
        if not colon or first not in STREAM_WAYS:
            return ways, kind
        ways.append(first)
        kind = rest


def parts_of(text, size):
    return [text[at:at + size] for at in range(0, len(text), size)]


def stream_pieces(whole, ways=()):
    """The pieces a good answer to a line (`whole`, as Python's JSON reader reads it) goes in: bytes to send, and the
    marks "hold" (the stand-in waits there) and "cut" (it ends the connection there). None when `whole` is no good
    answer whose first choice holds a message: such an answer goes whole."""
    if not isinstance(whole, dict) or whole.get("object") != "chat.completion":
        return None
    choices = whole.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        return None
    found, ending, usage = choices[0]["message"], choices[0].get("finish_reason"), whole.get("usage")
    base = {"id": whole.get("id"), "object": "chat.completion.chunk", "created": whole.get("created"), "model": whole.get("model")}

    def piece(delta=None, finish=None, counts=None):
        one = dict(base)
        one["choices"] = [] if delta is None else [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish}]
        if counts is not None:
            one["usage"] = counts
        return b"data: " + json.dumps(one, separators=(",", ":")).encode() + b"\n\n"

    out = [b": keep-alive\n\n", b": keep-alive\n\n"] if "keepalive" in ways else []
    out.append(piece({"role": "assistant", "content": ""}))
    for name in ("reasoning_content", "reasoning"):
        if isinstance(found.get(name), str):
            out += [piece({name: part}) for part in parts_of(found[name], THINKING_PIECE)]
    if "holdthinking" in ways:
        out.append("hold")
    body_from = len(out)
    content = found.get("content")
    if isinstance(content, str):
        sent = 0
        for part in parts_of(content, WORDS_PIECE):
            out.append(piece({"content": part}))
            sent += len(part)
            if "hold" in ways and sent >= HOLD_SIGNS and "hold" not in out:
                out.append("hold")
    elif content is not None:
        out.append(piece({"content": content}))
    for place, one in enumerate(found.get("tool_calls") or []):
        function = one.get("function") or {}
        index = one.get("index", place)
        first = {"index": index, "id": one.get("id"), "type": one.get("type", "function"), "function": {"name": function.get("name")}}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            first["function"]["arguments"] = ""
        out.append(piece({"tool_calls": [first]}))
        if isinstance(arguments, str):
            out += [piece({"tool_calls": [{"index": index, "function": {"arguments": part}}]}) for part in parts_of(arguments, INPUTS_PIECE)]
    body_pieces = len(out) - body_from
    if "cut" in ways or "error" in ways:
        # In the middle of the words and the tool.
        at = body_from + max(1, body_pieces // 2)
        if "cut" in ways:
            return out[:at] + ["cut"]
        breaking = {"error": {"message": BREAK_MESSAGE, "type": "upstream_error", "code": ""}}
        return out[:at] + [b"data: " + json.dumps(breaking, separators=(",", ":")).encode() + b"\n\n", b"data: [DONE]\n\n"]
    alone = "usagealone" in ways and usage is not None
    out.append(piece({"content": ""}, "aborted" if "aborted" in ways else ending, None if alone else usage))
    if alone:
        out.append(piece(counts=usage))
    return out + [b"data: [DONE]\n\n"]


def stream_sent(pieces, upto=None):
    """What the pieces before the mark `upto` (or all) brought: (the model's words, what the first tool was given)."""
    words, inputs = "", ""
    for item in pieces:
        if item == upto:
            break
        if not isinstance(item, bytes) or not item.startswith(b"data: {"):
            continue
        one = json.loads(item[len(b"data: "):])
        for choice in one.get("choices") or []:
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                words += delta["content"]
            for part in delta.get("tool_calls") or []:
                if part.get("index", 0) == 0:
                    inputs += (part.get("function") or {}).get("arguments") or ""
    return words, inputs


def stream_body(pieces):
    """The bytes of all the pieces, without the marks: what the kernel reads behind the notes."""
    return b"".join(item for item in pieces if isinstance(item, bytes))


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
    if name == "makein":
        return good(body(message(None, [call("make_app", given)]), "tool_calls")), "goodbye"
    if name == "runin":
        return good(body(message(None, [call("run_app", given)]), "tool_calls")), "goodbye"
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
        # Longer than the 2,048 bytes the kernel takes of what the model gives a tool (docs/tools.md).
        return good(body(message(None, [call("make_app", {"request": "a dice", "notes": "n" * 3000})]), "tool_calls")), "goodbye"
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
    if name == "chunkedstream":
        # Pieces with their lengths in between, which a server must not send to a request in HTTP/1.0.
        data = stream_body(stream_pieces(json.loads(body(message("Hello."))), ()))
        chunked = b"%x\r\n" % len(data) + data + b"\r\n0\r\n\r\n"
        return STREAM_HEAD.replace(b"Connection: close", b"Transfer-Encoding: chunked\r\nConnection: close") + chunked, "goodbye"
    # The behaviours for documents are document_cases.py's.
    import document_cases
    return document_cases.answer(kind, line, bearer)
