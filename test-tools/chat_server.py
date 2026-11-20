"""A stand-in for the model provider, for the tests where every line typed in the chat box goes to the model
(test_chat_tools.py) and for the tests of apps kept on the disk (test_apps_kept.py). It follows model_server.py: on
this computer's own address, behind TLS; it answers the kernel's page fetch (a GET) with a small page, and each
request to the model (a POST) with the next behaviour from its list, and writes down what it saw, one line of JSON
per connection, the whole body as Python's JSON reader read it among it.

A request that carries a list of tools is a line typed in the chat box: it is answered with the behaviours of
chat_cases.py. Any other request is one for an app: it is answered with the kinds of app_cases.py. When the next
behaviour is a kind of app and a line comes, the line is answered first with the tool make_app (its request is what
follows "make " in the line, or the whole line), and the kind waits for the request for the app that follows.

Usage: python chat_server.py <port> <chain.pem> <key.pem> <log file> <behaviours, as a JSON list>"""
import json
import socket
import ssl
import sys
import time

import app_cases
import chat_cases

port, chain, key, log_path = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
behaviours = json.loads(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] else []

PAGE = b"<html>\n<head><title>The test server</title></head>\n<body>\n<p>Hello from the test server.</p>\n</body>\n</html>\n"


def with_length(first, data, kind=b"application/json"):
    return first + b"\r\nContent-Type: " + kind + b"\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(data) + data


def made(found, ending):
    """A good answer (200) to a request for an app, as model_server.py makes it."""
    choice = {"index": 0, "message": found}
    if ending is not None:
        choice["finish_reason"] = ending
    return with_length(b"HTTP/1.1 200 OK", json.dumps({
        "id": "gen-test-2", "object": "chat.completion", "created": 1795000000, "model": "deepseek/deepseek-v4.1-flash-1017",
        "choices": [choice], "usage": {"prompt_tokens": 12, "completion_tokens": 1000, "total_tokens": 1012}}).encode())


def the_line(parsed):
    """The text of the last message from the person, or None."""
    try:
        return [m["content"] for m in parsed["messages"] if m.get("role") == "user"][-1]
    except (KeyError, IndexError, TypeError):
        return None


def answer_for(parsed, bearer, note):
    """Gives (bytes to send, how to end) for the request, and notes which behaviour answered it."""
    chat = isinstance(parsed, dict) and "tools" in parsed
    line = the_line(parsed) if chat else None
    note["request for"] = "a line" if chat else "an app"
    waiting = behaviours[0] if behaviours else None
    if chat and waiting is not None and app_cases.answer(waiting, bearer) is not None:
        note["behaviour"] = "makeline, for " + waiting
        return chat_cases.answer("makeline", line or "", bearer)
    kind = behaviours.pop(0) if behaviours else ("words=Hello." if chat else "app")
    note["behaviour"] = kind
    if chat:
        found = chat_cases.answer(kind, line or "", bearer)
        if found is None:
            raise SystemExit("unknown behaviour for a line: " + kind)
        return found
    if kind == "slowapp":
        time.sleep(9)
        kind = "app"
    found = app_cases.answer(kind, bearer)
    if found is None:
        raise SystemExit("unknown behaviour for an app: " + kind)
    return made(*found), "goodbye"


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
                note["length note right"] = len(body) == length
                try:
                    parsed = json.loads(body.decode())
                    note["body"] = parsed
                except ValueError as problem:
                    parsed = None
                    note["body problem"] = str(problem)
                bearer = notes.get("authorization", "")
                note["key came as"] = bearer
                bearer = bearer[len("Bearer "):] if bearer.startswith("Bearer ") else ""
                answer, ending = answer_for(parsed, bearer, note)
                link.sendall(answer)
                note["sent"] = len(answer)
                try:
                    link.unwrap()
                except (ssl.SSLError, OSError):
                    pass
        except (ssl.SSLError, OSError, ValueError) as problem:
            note["problem"] = str(problem)[:200]
        finally:
            try:
                raw.close()
            except OSError:
                pass
        log.write(json.dumps(note) + "\n")
        log.flush()
