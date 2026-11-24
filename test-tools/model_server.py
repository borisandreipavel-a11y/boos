"""A stand-in for the model provider, on this computer's own address, behind TLS. It answers the kernel's page
fetch (a GET) with a small page, and each question to the model (a POST) with the next behaviour from its list.
It checks every POST with Python's own JSON code and writes down what it saw as one line of JSON per connection.

Usage: python model_server.py <port> <chain.pem> <key.pem> <log file> <behaviour,behaviour,...>
       python model_server.py <port> <chain.pem> <key.pem> <log file> <behaviours, as a JSON list>
(a JSON list when a behaviour holds a comma, as "words=Hello there, I am ..." does)

A GET of a file from any other site, or of another path, gets the answer download_cases.py gives for it.

Behaviours: wrongkey, credit, echo, echopart, good, goodlong, chunked, page, nothttp, harmful, huge, cutoff,
silent, empty, flaterror, nobody, keepopen, and more below; for a request for an app, the kinds of app_cases.py
(app..., run...), slowapp and keyapp.

A request that carries a list of tools is a line typed in the chat box, since every line but `key` and `setup`
goes to the model (docs/tools.md). When the next behaviour is a kind of app, the line is answered first with the
tool make_app (its request is what follows "make " in the line, or the whole line), and the kind waits for the
request for the app that follows; so is one of the kinds above with "app:" in front (app:realrefusal, say), which
then answers the request for the app. Otherwise the line gets the next behaviour: one of chat_cases.py's
(words=..., run=..., ...) or any of the kinds above, which the kernel reads the same way for a line. With no
behaviour left, a line gets "words=Hello." and anything else "wrongkey".

Another ask about a line, when what a tool did needs the model, is a line too, with or without a list of tools (the
last ask goes without): its instruction text holds chat_cases.AGAIN_MARK. It gets the next behaviour only when that
begins with "again:", as "again:make=a dice that rolls" does, and chat_cases.AGAIN_WORDS in words otherwise, which
leaves the list as it is.

A request that asks for its answer piece by piece ("stream": true, as a line's does) gets a good answer of the shape
above piece by piece (chat_cases.stream_pieces), unless the last argument is "whole": then it gets it whole, as a
provider that does not send pieces would. Ways in front of a line's behaviour change how the pieces go
(chat_cases.STREAM_WAYS): "hold:words=..." holds the answer after its first words, and goes on when a file named as
the log with ".go" behind it appears; the stand-in says it holds by writing the file named as the log with ".held".

A POST to /v1/messages is a question in Anthropic's form (docs/model.md, "Anthropic"; anthropic_cases.py). It is
answered with the same behaviours, each turned into Anthropic's form (anthropic_cases.whole and .streamed), and a
behaviour that begins "a:" is one of anthropic_cases.special's. The log notes, for every POST, the provider whose form
it has ("provider"), the name the link was asked for and the request's Host, which note carried the key ("key note"),
and for Anthropic's the version note and the body as it was sent ("sent body"). Its "body" is the same request in
OrcaRouter's form (anthropic_cases.back), and "key came as" is written as for OrcaRouter, only when the request is
right in Anthropic's form in every way ("anthropic form right": the body, the version, the site, no other key note), so
that a test written for either form reads both the same."""
import json
import os
import socket
import ssl
import sys
import time

# The answers to a request for an app, which test_app.py shares (in this folder), and those to a line.
import anthropic_cases
import app_cases
import chat_cases
import download_cases

port, chain, key, log_path = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
if len(sys.argv) > 5 and sys.argv[5].startswith("["):
    behaviours = json.loads(sys.argv[5])
else:
    behaviours = sys.argv[5].split(",") if len(sys.argv) > 5 and sys.argv[5] else []
# Whether answers go whole even to a request that asks for them piece by piece.
WHOLE = len(sys.argv) > 6 and sys.argv[6] == "whole"

PAGE = b"<html>\n<head><title>The test server</title></head>\n<body>\n<p>Hello from the test server.</p>\n</body>\n</html>\n"
MEANT = {"model": "deepseek/deepseek-v4.1-flash-1017", "messages": [{"role": "user", "content": "Say hello in five words."}], "max_tokens": 1000, "stream": False}
REFUSAL = {"error": {"message": "Missing or invalid API key", "type": "authentication_error", "code": "invalid_api_key"}}


def with_length(first, body, kind=b"application/json"):
    return first + b"\r\nContent-Type: " + kind + b"\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body


def good(words):
    return json.dumps({
        "id": "gen-test-1", "object": "chat.completion", "created": 1795000000, "model": MEANT["model"],
        "choices": [{"index": 0, "message": {"role": "assistant", "content": words, "reasoning_content": "The user wants a greeting."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21},
    }).encode()


def made(message, ending):
    """A good answer (200) whose first choice holds `message` and ended as `ending`."""
    choice = {"index": 0, "message": message}
    if ending is not None:
        choice["finish_reason"] = ending
    return with_length(b"HTTP/1.1 200 OK", json.dumps({
        "id": "gen-test-2", "object": "chat.completion", "created": 1795000000, "model": MEANT["model"],
        "choices": [choice], "usage": {"prompt_tokens": 12, "completion_tokens": 1000, "total_tokens": 1012}}).encode())


NEW = {
    "lengthempty": ({"role": "assistant", "content": "", "reasoning_content": "Okay, the user wants five words. " * 40}, "length"),
    "lengthnull": ({"role": "assistant", "content": None}, "length"),
    "nullthink": ({"role": "assistant", "content": None, "reasoning_content": "Hmm."}, "stop"),
    "pieces": ({"role": "assistant", "content": [{"type": "text", "text": "Hello in pieces, my friend."}]}, "stop"),
    "lengthwords": ({"role": "assistant", "content": "Hello there, my good"}, "length"),
    "filtered": ({"role": "assistant", "content": ""}, "content_filter"),
    "filteredwords": ({"role": "assistant", "content": "Hello"}, "content_filter"),
    "spaces": ({"role": "assistant", "content": "\n\n  Hello world, nice to meet you.\n"}, "stop"),
    "nocontent": ({"role": "assistant", "reasoning": "The user asked for a greeting."}, "length"),
    "oddending": ({"role": "assistant", "content": "Hi, hello, greetings, hey, howdy."}, "\x1b[31mweird\x07"),
    "noending": ({"role": "assistant", "content": "Five words of hello here."}, None),
    "blank": ({"role": "assistant", "content": "   \n "}, "stop"),
}


def orca_error(status, code, message):
    """A refusal in the shape the real provider sent one (seen once, with a made-up key), and its documentation
    describes: error.message, error.type orcarouter_api_error, error.code."""
    return with_length(status, json.dumps({"error": {"code": code, "message": message, "type": "orcarouter_api_error"}}, separators=(",", ":")).encode())


def answer_for(kind, bearer):
    """Gives (bytes to send, how to end: 'goodbye', 'cut', 'hold')."""
    if kind == "realrefusal":
        return orca_error(b"HTTP/1.1 401 Unauthorized", "", "Invalid API key (request id: 20261119120000123456789TEST)"), "goodbye"
    if kind == "slowrefusal":
        time.sleep(9)
        return orca_error(b"HTTP/1.1 401 Unauthorized", "", "Invalid API key (request id: 20261119120000123456789SLOW)"), "goodbye"
    if kind == "keyquota":
        return orca_error(b"HTTP/1.1 403 Forbidden", "pre_consume_token_quota_failed", "token quota is not enough"), "goodbye"
    if kind == "notallowed":
        return orca_error(b"HTTP/1.1 403 Forbidden", "", "This token has no access to model deepseek/deepseek-v4.1-flash-1017"), "goodbye"
    if kind == "nowallet":
        return orca_error(b"HTTP/1.1 402 Payment Required", "insufficient_user_quota", "user quota is not enough"), "goodbye"
    if kind == "wrongkey":
        return with_length(b"HTTP/1.1 401 Unauthorized", json.dumps(REFUSAL).encode()), "goodbye"
    if kind == "credit":
        return with_length(b"HTTP/1.1 402 Payment Required", json.dumps({"error": {"message": "Insufficient credit. Top up to go on.", "type": "billing_error", "code": "insufficient_credit"}}).encode()), "goodbye"
    if kind == "echo":
        return with_length(b"HTTP/1.1 401 Unauthorized", json.dumps({"error": {"message": "Incorrect API key provided: %s. Find your key in the console." % bearer, "type": "authentication_error"}}).encode()), "goodbye"
    if kind == "echopart":
        return with_length(b"HTTP/1.1 401 Unauthorized", json.dumps({"error": {"message": "Incorrect API key provided: %s****%s." % (bearer[:14], bearer[-7:]), "type": "authentication_error"}}).encode()), "goodbye"
    if kind == "echoescaped":
        # The key written in a roundabout way: every fifth sign as a backslash, a u and four digits.
        roundabout = "".join("\\u%04x" % ord(sign) if place % 5 == 4 else sign for place, sign in enumerate(bearer))
        return with_length(b"HTTP/1.1 401 Unauthorized", ('{"error":{"message":"Incorrect API key provided: %s."}}' % roundabout).encode()), "goodbye"
    if kind == "echocut":
        # The key begins five signs before the place where the kernel cuts what it says.
        return with_length(b"HTTP/1.1 401 Unauthorized", json.dumps({"error": {"message": "x" * 295 + bearer}}).encode()), "goodbye"
    if kind in NEW:
        message, ending = NEW[kind]
        return made(message, ending), "goodbye"
    if kind == "echo200":
        return made({"role": "assistant", "content": "Your key is " + bearer + ", hello!"}, "stop"), "goodbye"
    if kind == "streamed":
        return with_length(b"HTTP/1.1 200 OK", 'data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'.encode(), b"text/event-stream"), "goodbye"
    if kind == "otherform":
        return with_length(b"HTTP/1.1 200 OK", '{"output": {"text": "Hello in another shape"}, "status": "done"}'.encode()), "goodbye"
    if kind == "echobody":
        return with_length(b"HTTP/1.1 200 OK", json.dumps({"note": "your key " + bearer + " works"}).encode()), "goodbye"
    if kind == "nochoices":
        return with_length(b"HTTP/1.1 200 OK", json.dumps({"object": "chat.completion", "choices": []}).encode()), "goodbye"
    if kind == "notfound":
        return with_length(b"HTTP/1.1 404 Not Found", json.dumps({"error": {"message": "Model not found: deepseek/deepseek-v4.1-flash-1017", "type": "invalid_request_error", "code": "model_not_found"}}).encode()), "goodbye"
    if kind == "upstream":
        return with_length(b"HTTP/1.1 502 Bad Gateway", json.dumps({"error": {"message": "All upstream providers failed", "type": "upstream_error"}}).encode()), "goodbye"
    if kind == "longrefusal":
        # A refusal whose reason is longer than the kernel says (for the bound on what is remembered).
        return orca_error(b"HTTP/1.1 401 Unauthorized", "", chat_cases.LONG_REASON), "goodbye"
    if kind == "upstreambare":
        return b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", "goodbye"
    if kind == "good":
        return with_length(b"HTTP/1.1 200 OK", good("Hello there, how are you?")), "goodbye"
    if kind == "goodlong":
        return with_length(b"HTTP/1.1 200 OK", good("Hello! " * 200 + "\x1b[31m é中 \"quoted\" \\ end")), "goodbye"
    if kind == "chunked":
        body = json.dumps(REFUSAL).encode()
        pieces = b"".join(b"%x\r\n" % len(piece) + piece + b"\r\n" for piece in (body[:20], body[20:57], body[57:])) + b"0\r\n\r\n"
        return b"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n" + pieces, "goodbye"
    if kind == "page":
        return with_length(b"HTTP/1.1 403 Forbidden", b"<!DOCTYPE html>\n<html><head><title>Attention Required!</title></head>\n<body><h1>Sorry, you have been blocked</h1></body></html>\n", b"text/html"), "goodbye"
    if kind == "nothttp":
        return b"\x00\x01\x02 this is no answer at all \xff\xfe\n\n\n", "goodbye"
    if kind == "harmful":
        words = "\x1b[2J\x1b[31mKernel panic: not really\r\nYou: fetch\x07 " + "A" * 5000
        return with_length(b"HTTP/1.1 401 \x1b[31mUnauthorized\x07", json.dumps({"error": {"message": words}}).encode()), "goodbye"
    if kind == "huge":
        return with_length(b"HTTP/1.1 200 OK", good("word " * 30000)), "goodbye"
    if kind == "cutoff":
        whole = with_length(b"HTTP/1.1 401 Unauthorized", json.dumps(REFUSAL).encode())
        return whole[:len(whole) - 30], "cut"
    if kind == "silent":
        return b"", "hold"
    if kind == "empty":
        return b"", "goodbye"
    if kind == "flaterror":
        return with_length(b"HTTP/1.1 429 Too Many Requests", json.dumps({"error": "Too many requests, slow down"}).encode()), "goodbye"
    if kind == "nobody":
        return b"HTTP/1.1 429 Too Many Requests\r\nRetry-After: 7\r\nContent-Length: 0\r\n\r\n", "goodbye"
    if kind == "keepopen":
        # The whole answer, and then the connection is left open, as a server does that expects more requests.
        return with_length(b"HTTP/1.1 401 Unauthorized", json.dumps(REFUSAL).encode()).replace(b"Connection: close", b"Connection: keep-alive"), "hold"
    if kind == "slowapp":
        # A good app, nine seconds late, so that a test can ask again while it is awaited.
        time.sleep(9)
        message, ending = app_cases.answer("app", bearer)
        return made(message, ending), "goodbye"
    if kind == "keyapp":
        # An app that puts the key together out of pieces of five signs, too short to be starred in its script, and
        # shows it: what it leaves on the screen goes back to the model, starred (docs/tools.md).
        pieces = " .. ".join('"%s"' % bearer[start:start + 5] for start in range(0, len(bearer), 5))
        return made({"role": "assistant", "content": "show(%s)\n" % pieces}, "stop"), "goodbye"
    if app_cases.answer(kind, bearer) is not None:
        message, ending = app_cases.answer(kind, bearer)
        return made(message, ending), "goodbye"
    raise SystemExit("unknown behaviour " + kind)


def the_line(parsed):
    """The text of the last message from the person, or None; of a message in parts (a PDF and a text, as
    anthropic_cases.back writes it), its text."""
    try:
        found = [m["content"] for m in parsed["messages"] if m.get("role") == "user"][-1]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(found, list):
        return "".join(part["text"] for part in found if isinstance(part, dict) and isinstance(part.get("text"), str))
    return found


def the_instructions(parsed):
    """The text of the system message, or "" if there is none."""
    try:
        found = [m["content"] for m in parsed["messages"] if m.get("role") == "system"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    return found if isinstance(found, str) else ""


def an_app_kind(kind, bearer):
    return kind.startswith("app:") or kind in ("slowapp", "keyapp") or app_cases.answer(kind, bearer) is not None


def choose(parsed, bearer, note):
    """Gives (bytes to send, how to end) for one request, and notes what it was for and which behaviour answered it."""
    again = isinstance(parsed, dict) and chat_cases.AGAIN_MARK in the_instructions(parsed)
    chat = isinstance(parsed, dict) and ("tools" in parsed or again)
    note["request for"] = "a line" if chat else "an app"
    if chat:
        note["asked again"] = again
        note["tools offered"] = "tools" in parsed
    if again:
        if behaviours and behaviours[0].startswith("again:"):
            kind = behaviours.pop(0)[len("again:"):]
        else:
            kind = "words=" + chat_cases.AGAIN_WORDS
        note["behaviour"] = "again, " + kind
        note["ways"], kind = chat_cases.stream_ways(kind)
        found = chat_cases.answer(kind, the_line(parsed) or "", bearer)
        return found if found is not None else answer_for(kind, bearer)
    if chat and behaviours and an_app_kind(behaviours[0], bearer):
        note["behaviour"] = "makeline, for " + behaviours[0]
        return chat_cases.answer("makeline", the_line(parsed) or "", bearer)
    kind = behaviours.pop(0) if behaviours else ("words=Hello." if chat else "wrongkey")
    note["behaviour"] = kind
    if kind.startswith("app:"):
        kind = kind[len("app:"):]
    if chat:
        note["ways"], kind = chat_cases.stream_ways(kind)
        found = chat_cases.answer(kind, the_line(parsed) or "", bearer)
        if found is not None:
            return found
    return answer_for(kind, bearer)


# Ends a connection as `ending` says: "goodbye" (the link's goodbye), "cut" (closed without it), or "hold" (held
# open, saying nothing more, until the other side gives up).
def end_link(link, ending, note):
    if ending == "goodbye":
        try:
            link.unwrap()
            note["goodbye answered"] = True
        except (ssl.SSLError, OSError):
            note["goodbye answered"] = False
    elif ending == "cut":
        socket.socket(fileno=link.detach()).close()
    else:
        started = time.time()
        try:
            while link.recv(4096):
                pass
        except (ssl.SSLError, OSError):
            pass
        note["held for"] = round(time.time() - started, 1)


def streamed(parsed, answer, ways):
    """The pieces `answer` goes in, when its request asked for it piece by piece and it is a good answer that can go
    so (chat_cases.stream_pieces); None when it goes whole."""
    if WHOLE or not isinstance(parsed, dict) or parsed.get("stream") is not True:
        return None
    head, _, data = answer.partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/1.1 200 ") or b"application/json" not in head:
        return None
    try:
        whole = json.loads(data)
    except ValueError:
        return None
    return chat_cases.stream_pieces(whole, ways)


def stream_send(link, pieces, note):
    """Sends the notes and the pieces: what lies between two marks in three writes cut anywhere, a twentieth of a
    second apart, so that pieces arrive cut in two and several together. At "hold" it waits for the test; at "cut" it
    stops there. Gives back how to end."""
    gathered, sent = chat_cases.STREAM_HEAD, 0
    for item in pieces + [None]:
        if isinstance(item, bytes):
            gathered += item
            continue
        third = len(gathered) // 3
        for part in (gathered[:third], gathered[third:2 * third], gathered[2 * third:]):
            if part:
                link.sendall(part)
                time.sleep(0.05)
        sent, gathered = sent + len(gathered), b""
        if item == "hold":
            note["held"] = True
            with open(HELD, "w") as held:
                held.write("held\n")
            end = time.time() + 120
            while not os.path.exists(GO) and time.time() < end:
                time.sleep(0.05)
            for name in (GO, HELD):
                if os.path.exists(name):
                    os.remove(name)
        elif item == "cut":
            note["sent"] = sent
            return "cut"
    note["sent"] = sent
    return "goodbye"


# The files by which a held answer is said to be held, and is let go on (see the top).
HELD, GO = log_path + ".held", log_path + ".go"
for name in (HELD, GO):
    if os.path.exists(name):
        os.remove(name)

names = []
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", port))
listener.listen(8)
listener.settimeout(240)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.minimum_version = ssl.TLSVersion.TLSv1_3
context.load_cert_chain(chain, key)
context.sni_callback = lambda link, name, _context: names.append(name)
print("ready", flush=True)

with open(log_path, "a") as log:
    while True:
        note = {}
        try:
            raw, _ = listener.accept()
        except socket.timeout:
            break
        raw.settimeout(100)
        try:
            del names[:]
            link = context.wrap_socket(raw, server_side=True)
            note["name asked for"] = names[-1] if names else None
            note["version"], note["scrambling"] = link.version(), link.cipher()[0]
            request = b""
            while b"\r\n\r\n" not in request:
                piece = link.recv(4096)
                if not piece:
                    break
                request += piece
            head, _, body = request.partition(b"\r\n\r\n")
            lines = head.decode(errors="replace").split("\r\n")
            note["first line"] = lines[0]
            notes = {}
            for line in lines[1:]:
                label, _, value = line.partition(":")
                notes[label.strip().lower()] = value.strip()
            note["notes"] = notes
            if lines[0].startswith("GET "):
                words = lines[0].split(" ")
                path = words[1] if len(words) > 1 else ""
                if notes.get("host") == "example.com" and path == "/":
                    link.sendall(with_length(b"HTTP/1.0 200 OK", PAGE, b"text/html"))
                    try:
                        link.unwrap()
                    except (ssl.SSLError, OSError):
                        pass
                    note["answered"] = "the page"
                else:
                    answer, ending = download_cases.answer_get(notes.get("host", ""), path)
                    if answer:
                        link.sendall(answer)
                    note["answered"] = "a file"
                    note["sent"] = len(answer)
                    end_link(link, ending, note)
            else:
                length = int(notes.get("content-length", "0"))
                while len(body) < length:
                    piece = link.recv(4096)
                    if not piece:
                        break
                    body += piece
                note["body bytes"] = len(body)
                note["length note right"] = len(body) == length
                anthropic = lines[0].startswith("POST " + anthropic_cases.PATH + " ")
                note["provider"] = "anthropic" if anthropic else "orcarouter"
                note["host"] = notes.get("host")
                note["key note"] = next((name for name in ("authorization", "x-api-key") if name in notes), None)
                parsed = None
                try:
                    parsed = json.loads(body.decode())
                    note["body as meant"] = parsed == MEANT
                    # The whole body as Python's JSON reader read it, so that a test can check a request
                    # that is not the fixed question (test_app.py).
                    note["body"] = parsed
                except ValueError as problem:
                    note["body as meant"] = False
                    note["body problem"] = str(problem)
                if anthropic:
                    sent = parsed
                    note["sent body"] = sent
                    note["version note"] = notes.get("anthropic-version")
                    parsed, problem = anthropic_cases.back(sent)
                    if problem:
                        note["anthropic form problem"] = problem
                    note["anthropic form right"] = (parsed is not None and note["key note"] == "x-api-key" and "authorization" not in notes
                                                    and note["version note"] == anthropic_cases.VERSION
                                                    and note["host"] == anthropic_cases.SITE and note["name asked for"] == anthropic_cases.SITE)
                    note["body"] = parsed
                    note["body as meant"] = parsed == MEANT
                    bearer = notes.get("x-api-key", "")
                    note["key came as"] = ("Bearer " + bearer) if note["anthropic form right"] else "x-api-key " + bearer
                    if behaviours and behaviours[0].startswith("a:"):
                        kind = behaviours.pop(0)
                        note["behaviour"] = kind
                        pieces, ending = anthropic_cases.special(kind), "goodbye"
                        if pieces is None:
                            raise SystemExit("unknown behaviour " + kind)
                    else:
                        answer, ending = choose(parsed, bearer, note)
                        pieces = anthropic_cases.streamed(sent, answer, note.get("ways", []), WHOLE)
                        if pieces is None:
                            answer = anthropic_cases.whole(answer)
                else:
                    bearer = notes.get("authorization", "")
                    note["key came as"] = bearer
                    bearer = bearer[len("Bearer "):] if bearer.startswith("Bearer ") else ""
                    answer, ending = choose(parsed, bearer, note)
                    pieces = streamed(parsed, answer, note.get("ways", []))
                if pieces is not None:
                    note["piece by piece"] = True
                    ending = stream_send(link, pieces, note)
                else:
                    if answer:
                        link.sendall(answer)
                    note["sent"] = len(answer)
                end_link(link, ending, note)
        except (ssl.SSLError, OSError, ValueError) as problem:
            note["problem"] = str(problem)[:200]
        finally:
            try:
                raw.close()
            except OSError:
                pass
        log.write(json.dumps(note) + "\n")
        log.flush()
