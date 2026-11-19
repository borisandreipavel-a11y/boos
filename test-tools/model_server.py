"""A stand-in for the model provider, on this computer's own address, behind TLS. It answers the kernel's page
fetch (a GET) with a small page, and each question to the model (a POST) with the next behaviour from its list.
It checks every POST with Python's own JSON code and writes down what it saw as one line of JSON per connection.

Usage: python model_server.py <port> <chain.pem> <key.pem> <log file> <behaviour,behaviour,...>

Behaviours: wrongkey, credit, echo, echopart, good, goodlong, chunked, page, nothttp, harmful, huge, cutoff,
silent, empty, flaterror, nobody, keepopen, and more below; for a request for an app, the kinds of app_cases.py
(app..., run...) and slowapp."""
import json
import socket
import ssl
import sys
import time

# The answers to a request for an app, which test_app.py shares (in this folder).
import app_cases

port, chain, key, log_path = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
behaviours = sys.argv[5].split(",") if len(sys.argv) > 5 and sys.argv[5] else []

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
    if app_cases.answer(kind, bearer) is not None:
        message, ending = app_cases.answer(kind, bearer)
        return made(message, ending), "goodbye"
    raise SystemExit("unknown behaviour " + kind)


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
                link.sendall(with_length(b"HTTP/1.0 200 OK", PAGE, b"text/html"))
                try:
                    link.unwrap()
                except (ssl.SSLError, OSError):
                    pass
                note["answered"] = "the page"
            else:
                length = int(notes.get("content-length", "0"))
                while len(body) < length:
                    piece = link.recv(4096)
                    if not piece:
                        break
                    body += piece
                note["body bytes"] = len(body)
                note["length note right"] = len(body) == length
                try:
                    parsed = json.loads(body.decode())
                    note["body as meant"] = parsed == MEANT
                    # The whole body as Python's JSON reader read it, so that a test can check a request
                    # that is not the fixed question (test_app.py).
                    note["body"] = parsed
                except ValueError as problem:
                    note["body as meant"] = False
                    note["body problem"] = str(problem)
                bearer = notes.get("authorization", "")
                note["key came as"] = bearer
                bearer = bearer[len("Bearer "):] if bearer.startswith("Bearer ") else ""
                kind = behaviours.pop(0) if behaviours else "wrongkey"
                note["behaviour"] = kind
                answer, ending = answer_for(kind, bearer)
                if answer:
                    link.sendall(answer)
                note["sent"] = len(answer)
                if ending == "goodbye":
                    try:
                        link.unwrap()
                        note["goodbye answered"] = True
                    except (ssl.SSLError, OSError) as problem:
                        note["goodbye answered"] = False
                elif ending == "cut":
                    socket.socket(fileno=link.detach()).close()
                else:
                    # Hold the connection open and say nothing more, until the other side gives up.
                    started = time.time()
                    try:
                        while link.recv(4096):
                            pass
                    except (ssl.SSLError, OSError):
                        pass
                    note["held for"] = round(time.time() - started, 1)
        except (ssl.SSLError, OSError, ValueError) as problem:
            note["problem"] = str(problem)[:200]
        finally:
            try:
                raw.close()
            except OSError:
                pass
        log.write(json.dumps(note) + "\n")
        log.flush()
