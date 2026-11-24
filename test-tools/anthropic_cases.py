"""The stand-in's answers in Anthropic's form (docs/model.md, "Anthropic"), made from the answers it has in
OrcaRouter's form, so that each case is written once: chat_cases.py's, app_cases.py's and model_server.py's own. And
the way back for a request: a request in Anthropic's form, written as the same request in OrcaRouter's form, so that
a test that compares requests in that form compares one in Anthropic's form as well. Shared by model_server.py, which
uses both, and the tests, which judge what the kernel makes of the answers. Nothing runs when this file is imported.

Anthropic's form, from its documentation (read in November 2026): the request names the model and the longest answer
(`max_tokens`), holds the instruction text apart (`system`), the line as the one message, and each tool as its name, its
sentence and its schema (`input_schema`). A good answer is a message whose `content` is a list of blocks: thinking (its
text left empty unless asked for, with a `signature`), words (`text`) and tools asked for (`tool_use`, with what the
model gives the tool at `input`, as JSON of its own); how it ended at `stop_reason` (`end_turn`, `tool_use`,
`max_tokens`, `refusal`, `model_context_window_exceeded`); the counts at `usage`. Piece by piece, it comes as named
events (`message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`,
`message_stop`, `ping`, `error`), each an `event:` line and a `data:` line. A refusal is
{"type":"error","error":{"type":...,"message":...},"request_id":...}.

Behaviours of this file's own, for what OrcaRouter's form has no way to say, begin "a:" (see `special`)."""
import json

import chat_cases

MODEL = "claude-haiku-5-5"
VERSION = "2026-10-21"
SITE = "api.anthropic.com"
PATH = "/v1/messages"
ORCA_MODEL = "deepseek/deepseek-v4.1-flash-1017"
# A made-up signature for a thinking block (Anthropic's documentation: the encrypted reasoning, passed back unchanged).
SIGNATURE = "c2lnbmF0dXJlIG9mIGEgdGVzdA=="
# How an answer ended, in OrcaRouter's words and in Anthropic's. "content_filter" has no like in Anthropic's form; its
# nearest is a refusal, which the kernel reads in its own way (no tool is done).
ENDINGS = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}
ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 402: "billing_error", 403: "permission_error",
               404: "not_found_error", 413: "request_too_large", 429: "rate_limit_error", 500: "api_error",
               504: "timeout_error", 529: "overloaded_error"}
# A piece that breaks the answer off, as Anthropic's documentation shows one.
OVERLOADED = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
# The fields a request of this kernel's in Anthropic's form may hold.
FIELDS = {"model", "max_tokens", "system", "messages", "tools", "stream"}


def back(sent):
    """The request `sent` (Anthropic's form, as Python's JSON reader reads it) as the same request in OrcaRouter's form,
    and why it is not one when it is not: (the request, None) or (None, why). Only what this kernel sends is taken: the
    model, the longest answer and `stream` always, the instruction text if any, one message from the person, and the
    tools, each with exactly a name, a sentence and a schema."""
    if not isinstance(sent, dict):
        return None, "not JSON"
    other = set(sent) - FIELDS
    if other:
        return None, "fields of another kind: %s" % sorted(other)
    if sent.get("model") != MODEL:
        return None, "the model %r" % (sent.get("model"),)
    if not isinstance(sent.get("max_tokens"), int) or isinstance(sent.get("max_tokens"), bool):
        return None, "no longest answer"
    if not isinstance(sent.get("stream"), bool):
        return None, "no word about stream"
    messages = sent.get("messages")
    if not (isinstance(messages, list) and len(messages) == 1 and isinstance(messages[0], dict)
            and set(messages[0]) == {"role", "content"} and messages[0]["role"] == "user" and isinstance(messages[0]["content"], str)):
        return None, "not one message from the person"
    written = []
    if "system" in sent:
        if not isinstance(sent["system"], str):
            return None, "an instruction text that is not a text"
        written.append({"role": "system", "content": sent["system"]})
    written.append({"role": "user", "content": messages[0]["content"]})
    request = {"model": ORCA_MODEL, "messages": written}
    if "tools" in sent:
        if not isinstance(sent["tools"], list) or not sent["tools"]:
            return None, "tools that are no list"
        tools = []
        for tool in sent["tools"]:
            if not isinstance(tool, dict) or set(tool) != {"name", "description", "input_schema"}:
                return None, "a tool not in Anthropic's form: %s" % json.dumps(tool)[:120]
            tools.append({"type": "function", "function": {"name": tool["name"], "description": tool["description"],
                                                           "parameters": tool["input_schema"]}})
        request["tools"] = tools
    request["max_tokens"] = sent["max_tokens"]
    request["stream"] = sent["stream"]
    if sent["stream"]:
        request["stream_options"] = {"include_usage": True}
    return request, None


def usage_of(usage):
    """OrcaRouter's counts as Anthropic gives them: (the counts at `usage`, the thinking tokens or None), or None. The
    question's tokens that were read back from what was kept are apart from those counted afresh, which together make
    all of them; the thinking is part of the answer's."""
    if not isinstance(usage, dict):
        return None
    asked, answered = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not isinstance(asked, int) or not isinstance(answered, int):
        return None
    read = usage.get("prompt_cache_hit_tokens")
    if read is None:
        read = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    counts = {"input_tokens": asked - (read or 0)}
    if read is not None:
        counts["cache_read_input_tokens"] = read
    counts["output_tokens"] = answered
    return counts, (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")


def message_of(whole):
    """A good answer in OrcaRouter's form (as Python's JSON reader reads it) as the same in Anthropic's form:
    (the message, the texts each tool is given as they were written, the counts as usage_of gives them), or None when
    `whole` is no good answer whose first choice holds a message."""
    if not isinstance(whole, dict) or whole.get("object") != "chat.completion":
        return None
    choices = whole.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        return None
    found, ending = choices[0]["message"], choices[0].get("finish_reason")
    blocks, inputs = [], []
    thought = next((found[name] for name in ("reasoning_content", "reasoning") if isinstance(found.get(name), str)), None)
    if thought and thought.strip():
        blocks.append({"type": "thinking", "thinking": "", "signature": SIGNATURE})
    content = found.get("content")
    if isinstance(content, str):
        if content:
            blocks.append({"type": "text", "text": content})
    elif isinstance(content, list):
        for piece in content:
            if isinstance(piece, dict) and isinstance(piece.get("text"), str):
                blocks.append({"type": "text", "text": piece["text"]})
    elif content is not None:
        blocks.append({"type": "text", "text": content})
    for place, one in enumerate(found.get("tool_calls") or []):
        function = one.get("function") or {}
        written = function.get("arguments")
        try:
            given = json.loads(written) if isinstance(written, str) else {}
        except ValueError:
            given = {}
        blocks.append({"type": "tool_use", "id": "toolu_test_%d" % place, "name": function.get("name"),
                       "input": given if isinstance(given, dict) else {}})
        inputs.append(written if isinstance(written, str) else None)
    message = {"id": "msg_test", "type": "message", "role": "assistant", "model": MODEL, "content": blocks}
    if ending is not None:
        message["stop_reason"] = ENDINGS.get(ending, ending)
        message["stop_sequence"] = None
    counts = usage_of(whole.get("usage"))
    if counts:
        message["usage"] = dict(counts[0])
        if counts[1] is not None:
            message["usage"]["output_tokens_details"] = {"thinking_tokens": counts[1]}
    return message, inputs, counts


def with_body(head, data):
    """`head` (an answer's first line and notes) with a new body and its length."""
    lines = [line for line in head.split(b"\r\n") if not line.lower().startswith(b"content-length:")]
    return b"\r\n".join(lines[:1] + [b"Content-Length: %d" % len(data)] + lines[1:]) + b"\r\n\r\n" + data


def gathered(data):
    """The pieces of an answer in OrcaRouter's form (the bytes behind the notes) as the whole answer they make, as
    Python's JSON reader would read it: the words of all the pieces, the last word about how it ended, the counts."""
    words, ending, usage = "", None, None
    for line in data.split(b"\n"):
        if not line.startswith(b"data: {"):
            continue
        try:
            one = json.loads(line[len(b"data: "):])
        except ValueError:
            continue
        for choice in one.get("choices") or []:
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                words += delta["content"]
            if choice.get("finish_reason") is not None:
                ending = choice["finish_reason"]
        if one.get("usage") is not None:
            usage = one["usage"]
    made = {"object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": words}, "finish_reason": ending}]}
    if usage is not None:
        made["usage"] = usage
    return made


def whole(answer):
    """An answer in OrcaRouter's form (the bytes the stand-in would send) as the same in Anthropic's form: a good one
    as a message, a refusal that gives its reason as Anthropic's refusal, a good one in pieces with a length note as the
    same in Anthropic's pieces, anything else as it is."""
    head, _, data = answer.partition(b"\r\n\r\n")
    if head.startswith(b"HTTP/1.1 200 ") and b"text/event-stream" in head and b"content-length:" in head.lower():
        return with_body(head, b"".join(item for item in events(*message_of(gathered(data))) if isinstance(item, bytes)))
    if not head.startswith(b"HTTP/1.1 ") or b"application/json" not in head:
        return answer
    status = int(head[9:12]) if head[9:12].isdigit() else 0
    try:
        parsed = json.loads(data)
    except ValueError:
        return answer
    if status == 200:
        made = message_of(parsed)
        return answer if made is None else with_body(head, json.dumps(made[0]).encode())
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict) and isinstance(parsed["error"].get("message"), str):
        refusal = {"type": "error", "error": {"type": ERROR_TYPES.get(status, "api_error"), "message": parsed["error"]["message"]},
                   "request_id": "req_test"}
        return with_body(head, json.dumps(refusal).encode())
    return answer


def event(kind, data):
    return b"event: " + kind.encode() + b"\ndata: " + json.dumps(data, separators=(",", ":")).encode() + b"\n\n"


def events(message, inputs, counts, ways=()):
    """The pieces a good answer (as message_of gives it) goes in, in Anthropic's form, with the marks of
    chat_cases.stream_pieces ("hold", "cut") at the same places: the words in pieces of the same size, what a tool is
    given in pieces of the same size, as it was written. The ways are chat_cases.STREAM_WAYS: "keepalive" sends two
    `ping`s first; "cut" ends the connection in the middle, and "error" breaks the answer off there with an `error`
    event, both after as many of the body's units as OrcaRouter's form sends before its cut (a piece of the words, the
    beginning of a tool, a piece of what a tool is given; the beginning of a block of words and the end of every block
    are none), so that the same words, and the same part of what a tool is given, come before it; "aborted", which
    Anthropic's form does not have, ends it with Anthropic's own `overloaded_error` in place of its end; "usagealone"
    changes nothing, since the counts always come in `message_delta`."""
    out = [event("ping", {"type": "ping"}), event("ping", {"type": "ping"})] if "keepalive" in ways else []
    first = {"id": message["id"], "type": "message", "role": "assistant", "model": MODEL, "content": [], "stop_reason": None,
             "stop_sequence": None}
    if counts:
        first["usage"] = {name: value for name, value in counts[0].items() if name != "output_tokens"}
        first["usage"]["output_tokens"] = 1
    out.append(event("message_start", {"type": "message_start", "message": first}))
    units = []  # the places in `out` of the body's units
    tool = 0
    for index, block in enumerate(message["content"]):
        start = {"type": "content_block_start", "index": index}
        stop = event("content_block_stop", {"type": "content_block_stop", "index": index})

        def delta(change):
            return event("content_block_delta", {"type": "content_block_delta", "index": index, "delta": change})

        if block["type"] == "thinking":
            out += [event("content_block_start", dict(start, content_block={"type": "thinking", "thinking": "", "signature": ""})),
                    delta({"type": "thinking_delta", "thinking": ""}), delta({"type": "signature_delta", "signature": SIGNATURE}), stop]
            if "holdthinking" in ways:
                out.append("hold")
            continue
        if block["type"] == "text":
            out.append(event("content_block_start", dict(start, content_block={"type": "text", "text": ""})))
            text = block["text"]
            if isinstance(text, str):
                sent = 0
                for part in chat_cases.parts_of(text, chat_cases.WORDS_PIECE):
                    out.append(delta({"type": "text_delta", "text": part}))
                    units.append(len(out) - 1)
                    sent += len(part)
                    if "hold" in ways and sent >= chat_cases.HOLD_SIGNS and "hold" not in out:
                        out.append("hold")
            else:
                out.append(delta({"type": "text_delta", "text": text}))
                units.append(len(out) - 1)
            out.append(stop)
        elif block["type"] == "tool_use":
            out.append(event("content_block_start", dict(start, content_block={"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}})))
            units.append(len(out) - 1)
            written = inputs[tool] if tool < len(inputs) else None
            tool += 1
            if isinstance(written, str):
                for part in chat_cases.parts_of(written, chat_cases.INPUTS_PIECE):
                    out.append(delta({"type": "input_json_delta", "partial_json": part}))
                    units.append(len(out) - 1)
            out.append(stop)
    if "cut" in ways or "error" in ways:
        at = units[max(1, len(units) // 2) - 1] + 1 if units else len(out)
        if "cut" in ways:
            return out[:at] + ["cut"]
        breaking = {"type": "error", "error": {"type": "api_error", "message": chat_cases.BREAK_MESSAGE}}
        return out[:at] + [event("error", breaking)]
    if "aborted" in ways:
        return out + [event("error", OVERLOADED)]
    change = {"stop_reason": message.get("stop_reason"), "stop_sequence": None}
    last = {"type": "message_delta", "delta": change}
    if counts:
        last["usage"] = {"output_tokens": counts[0]["output_tokens"]}
        if counts[1] is not None:
            last["usage"]["output_tokens_details"] = {"thinking_tokens": counts[1]}
    return out + [event("message_delta", last), event("message_stop", {"type": "message_stop"})]


def sent_words(pieces, upto=None):
    """The model's words that the pieces before the mark `upto` (or all) brought, as chat_cases.stream_sent gives them
    for OrcaRouter's form."""
    words = ""
    for item in pieces:
        if item == upto:
            break
        if not isinstance(item, bytes):
            continue
        for text in item.split(b"\n"):
            if text.startswith(b"data: "):
                one = json.loads(text[len(b"data: "):])
                delta = one.get("delta") or {}
                if one.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    words += delta.get("text", "")
    return words


def streamed(sent, answer, ways, whole_only=False):
    """The pieces `answer` (bytes in OrcaRouter's form) goes in, in Anthropic's form, when its request (`sent`, in
    Anthropic's form) asked for it piece by piece and it is a good answer that can go so; None when it goes whole."""
    if whole_only or not isinstance(sent, dict) or sent.get("stream") is not True:
        return None
    head, _, data = answer.partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/1.1 200 ") or b"application/json" not in head:
        return None
    try:
        made = message_of(json.loads(data))
    except ValueError:
        return None
    if made is None:
        return None
    return events(*made, ways=ways)


def special(kind):
    """The pieces of a behaviour of this file's own ("a:..."), for what OrcaRouter's form has no way to say, or None:
      a:refusal       the provider's checks stop the answer after its first words
      a:refusaltool   the provider's checks stop the answer in the middle of what the model gives a tool
      a:window        the answer reaches the model's context after its first words
      a:unknown       a kind of event and a kind of block the kernel does not know, then words
      a:overloaded    `overloaded_error` after the first words, with no end
      a:stopnoend     the end mark without a word about how it ended, after words
      a:forget        the tool `forget`, which takes no inputs, with one piece of its inputs, empty, as Anthropic
                      begins what a tool is given in its documentation's example"""
    name = kind[len("a:"):]
    counts = ({"input_tokens": 40, "cache_read_input_tokens": 600, "output_tokens": 42}, 12)
    words = {"type": "text", "text": "These are the first words."}
    thinking = {"type": "thinking", "thinking": "", "signature": SIGNATURE}
    if name == "refusal":
        return events({"id": "msg_test", "content": [thinking, words], "stop_reason": "refusal"}, [], counts)
    if name == "refusaltool":
        tool = {"type": "tool_use", "id": "toolu_test_0", "name": "draw_table", "input": {}}
        return events({"id": "msg_test", "content": [thinking, tool], "stop_reason": "refusal"}, ['{"table":"title Half a table\\nhead A | B\\nro'], counts)
    if name == "window":
        return events({"id": "msg_test", "content": [words], "stop_reason": "model_context_window_exceeded"}, [], counts)
    if name == "overloaded":
        return events({"id": "msg_test", "content": [words], "stop_reason": "end_turn"}, [], counts, ways=("aborted",))
    if name == "stopnoend":
        return events({"id": "msg_test", "content": [words], "stop_reason": None}, [], counts)
    if name == "unknown":
        pieces = events({"id": "msg_test", "content": [{"type": "text", "text": "Words after the unknown."}], "stop_reason": "end_turn"}, [], counts)
        odd = [event("future_event", {"type": "future_event", "note": "a kind the kernel does not know"}),
               event("content_block_start", {"type": "content_block_start", "index": 5, "content_block": {"type": "future_block"}}),
               event("content_block_stop", {"type": "content_block_stop", "index": 5})]
        return pieces[:1] + odd + pieces[1:]
    if name == "forget":
        tool = {"type": "tool_use", "id": "toolu_test_0", "name": "forget", "input": {}}
        pieces = events({"id": "msg_test", "content": [thinking, tool], "stop_reason": "tool_use"}, [None], counts)
        at = next(place for place, item in enumerate(pieces)
                  if isinstance(item, bytes) and item.startswith(b"event: content_block_start") and b'"tool_use"' in item)
        empty = event("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ""}})
        return pieces[:at + 1] + [empty] + pieces[at + 1:]
    return None
