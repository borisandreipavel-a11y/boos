"""Trying the key: every key typed at the onboarding goes to the stand-in for the provider (in a copy of the
project, see net_copy.py) with the question that "ask" asks, and the onboarding goes on by the answer. Each
scenario starts the stand-in with its own list of answers; the stand-in writes down the key every question
carried. Pictures dot by dot against the model (keyed_model.py), the terminal's rows, the notebook read from
outside, the keys the stand-in saw, and dumps of memory.
Usage: python test_try.py [scenario ...]   (default: all)"""
import json
import os
import subprocess
import sys
import time

from boot import HERE, RUNS
from certs import test_keys
from keyed_model import KeyedChat, LOCKED, TRY_AWAY
from lockref import lock
from nb import put_notebook
from net_copy import build
from start_helper import Start, failures, fresh_disk

from ports import standin_port
PORT = standin_port(2)  # 44302 unless BOOS_PORT_BASE says otherwise
TLS = test_keys()
LOG = os.path.join(RUNS, "try-server.log")

# Made up for these tests, with no run of six signs in common.
K1 = "Ref-Qm3Vx9Lp2Rt7Ke4Ah"     # refused
K2 = "Ok8-Hw8Nc4Jd6Zs1Uy5Bn"     # works
K3 = "New-Pf5Gk7Bq2Wy8Tc3Dm"     # refused at setup, or turned away
KEYS_C = ["Lim-Xr2Yd9Fs4Jh6Wn1Qe", "Cre-Tb3Mk8Zq5Vp2Rx7Gs", "Pag-Wd6Hn1Kc9Ly4Fj2Mt",
          "Bus-Qs4Zr7Xn2Gd8Kp5Hv", "Ups-Jm9Ft3Wb6Rc1Lx8Ny", "Chu-Vk2Pd7Hs4Mq9Zt3Bf", "Ech-Rn5Gx8Lc1Wj6Ky2Ps"]
PW = "green door"
PW2 = "red window"
EARLY = "Zv7Wz8Xy3Q"           # typed while a key is tried; must never be taken

GOOD = 'the model answered "Hello there, how are you?".'
REFUSED = 'the provider turned the question down (401): "Invalid API key (request id: 20261119120000123456789TEST)".'
REFUSED_SLOW = 'the provider turned the question down (401): "Invalid API key (request id: 20261119120000123456789SLOW)".'


def echoed(key):
    return 'the provider turned the question down (401): "Incorrect API key provided: %s. Find your key in the console.".' % ("*" * len(key))


C_OUTCOMES = [
    ("Known", 'the provider turned the question down (403): "token quota is not enough".'),
    ("Known", 'the provider turned the question down (402): "user quota is not enough".'),
    ("NotTold", "the provider turned the question down (403), and I could not read why."),
    ("NotTold", "the provider turned the question down (429), and I could not read why."),
    ("NotTold", 'the provider could not answer (502): "All upstream providers failed".'),
    ("Unknown", "the provider turned the question down (401), and I could not read why."),
    ("Unknown", echoed(KEYS_C[6])),
]
C_BEHAVIOURS = "keyquota,nowallet,page,nobody,upstream,chunked,echo"

kernel = None
server = None

# Breaks on purpose (run_try_breaks.py sets BREAK to one of these names): (file, old, new), made in the copy only.
TRY_BREAKS = {
    "the refused key not wiped": ("secret.rs", "pub fn trial_forget() {\n    let were_on = signals_off();\n    wipe(unsafe { &mut *(&raw mut TRIAL) });\n",
                                  "pub fn trial_forget() {\n    let were_on = signals_off();\n"),
    "the refused key kept": ("onboarding.rs", "    if verdict == KeyVerdict::Unknown {\n        trial_forget();\n",
                             "    if verdict == KeyVerdict::Unknown {\n        trial_take();\n"),
    "the try lends the kept key": ("model.rs", "    if trying {\n        trial_lend(", "    if false {\n        trial_lend("),
    "keys typed during the try taken": ("chat.rs", "    if onboarding_trying() && letter != b'\\n' {", "    if false {"),
    "nothing said about signs not taken": ("chat.rs", "        rows.insert(0, String::from(\"Kernel: what was typed while I tried the key was not taken.\"));\n", ""),
    "403 taken as unknown": ("model.rs", "                402 | 403 => KeyVerdict::Known,\n", "                402 => KeyVerdict::Known,\n                403 => KeyVerdict::Unknown,\n"),
    "a reasonless 401 not taken as unknown": ("model.rs", "    let verdict = if parts.number == 401 { KeyVerdict::Unknown } else { KeyVerdict::NotTold };\n",
                                              "    let verdict = KeyVerdict::NotTold;\n"),
    "a 403 page taken as known": ("model.rs", "    let verdict = if parts.number == 401 { KeyVerdict::Unknown } else { KeyVerdict::NotTold };\n",
                                  "    let verdict = if parts.number == 401 { KeyVerdict::Unknown } else if parts.number == 403 { KeyVerdict::Known } else { KeyVerdict::NotTold };\n"),
    "a key that cannot be tried not kept": ("onboarding.rs", "        Err(reason) => {\n            trial_take();\n            wait_for(Waiting::NewPassword);\n",
                                            "        Err(reason) => {\n            trial_forget();\n            wait_for(Waiting::NewPassword);\n"),
    "the try's answer not handed to the onboarding": ("chat.rs", "    if answer.errand != Errand::KeyTry {\n", "    if true {\n"),
}


def broken():
    """The `more` for net_copy.build: the break named in BREAK, made in the copy."""
    name = os.environ.get("BREAK")
    if not name:
        return None
    file, old, new = TRY_BREAKS[name]

    def change(text):
        assert text.count(old) == 1, (name, text.count(old))
        return text.replace(old, new)
    print("BREAK ON PURPOSE: " + name)
    return {file: change}


def serve(behaviours):
    global server
    if os.path.exists(LOG):
        os.remove(LOG)
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT), os.path.join(TLS, "a", "both-chain.pem"),
                               os.path.join(TLS, "a", "both.key"), LOG, behaviours], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert server.stdout.readline().strip() == "ready"


def seen(tag, meant):
    """The keys the stand-in's questions carried, in turn, against `meant`; and every body as meant."""
    server.kill()
    time.sleep(0.3)
    notes = [json.loads(line) for line in open(LOG)] if os.path.exists(LOG) else []
    asked = [n for n in notes if "key came as" in n]
    keys = [n["key came as"][len("Bearer "):] for n in asked]
    bodies = all(n.get("body as meant") for n in asked)
    ok = keys == meant and bodies
    print("  %-38s %s" % (tag + " stand-in", "saw %d questions, each with the key meant%s" % (len(keys), "" if bodies else ", A BODY NOT AS MEANT") if ok
                         else "SAW %r, MEANT %r" % ([k[:8] for k in keys], [k[:8] for k in meant])))
    if not ok:
        failures.append(tag + " stand-in")


def dump(s, name):
    path = os.path.join(s.m.folder, name + ".mem")
    s.m.command("pmemsave 0 0x10000000 " + path.replace(chr(92), "/"))
    last = -1
    for _ in range(100):
        time.sleep(0.3)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        if size == 0x10000000 and size == last:
            break
        last = size
    data = open(path, "rb").read()
    os.remove(path)
    return data


def memory(s, name, meant):
    """`meant`: text -> whole copies meant in memory. No loose piece of six signs of any of them anywhere."""
    time.sleep(0.6)
    data = dump(s, name)
    report, wrong = [], False
    for text, want in meant.items():
        pieces = [text[i:i + 6].encode() for i in range(len(text) - 5)]
        whole = data.count(text.encode())
        loose = sum(data.count(p) for p in pieces) - whole * len(pieces)
        report.append("%s.. %d%s" % (text[:3], whole, "" if not loose else " +%d loose" % loose))
        if whole != want or loose:
            wrong = True
    print("  %-38s %s" % (s.tag + " " + name, ", ".join(report) + (" NOT AS MEANT" if wrong else "")))
    if wrong:
        failures.append(s.tag + " " + name)


def refused_then_works():
    """A first start: a key the provider does not know is not kept and is asked for again; the next one works."""
    serve("realrefusal,good,good")
    chat = KeyedChat(1280, tries=[("Unknown", REFUSED), ("Works", GOOD)])
    s = Start("try-a", fresh_disk("try-a"), chat, kernel=kernel, network="open")
    s.keys("Ada\n")
    s.key_tried(K1 + "\n")
    s.look("1-refused-asked-again")
    s.key_tried(K2 + "\n")
    s.look("2-works")
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    s.look("3-locked")
    s.mark()
    s.keys("ask\n")
    s.wait_text("the model answered")
    s.chat.say(GOOD)
    s.look("4-asked")
    memory(s, "memory", {K1: 0, K2: 1, PW: 0})
    s.end(secrets=[K1, K2, PW])
    seen("try-a", [K1, K2, K2])


def setup_refused_keeps_old():
    """After the key was unlocked, "setup" and a key the provider does not know: Enter alone keeps the locked key,
    and the key unlocked at this start still goes with "ask"."""
    serve("realrefusal,good")
    disk = fresh_disk("try-b")
    put_notebook(disk, [("name", b"Bo"), ("locked key", lock(PW.encode(), K2.encode(), os.urandom(16), os.urandom(12), 600000))])
    chat = KeyedChat(1280, kept_name=b"Bo", key_entry=LOCKED, password=PW, tries=[("Unknown", REFUSED)])
    s = Start("try-b", disk, chat, kernel=kernel, network="open")
    s.keys(PW + "\n")
    s.wait(3)
    s.keys("setup\n\n")
    s.key_tried(K3 + "\n")
    s.look("1-refused-new-key-question")
    s.keys("\n")
    s.look("2-locked-key-stays")
    s.mark()
    s.keys("ask\n")
    s.wait_text("the model answered")
    s.chat.say(GOOD)
    s.look("3-asked-with-the-old-key")
    memory(s, "memory", {K3: 0, K2: 1, PW: 0})
    s.end(secrets=[K2, K3, PW])
    seen("try-b", [K3, K2])


def answers():
    """One start, several keys after "setup": answers that keep the key (402, 403 with the provider's reason),
    answers that do not say (403 page, 429 without words, 502), and 401s (unread, and repeating the key)."""
    serve(C_BEHAVIOURS)
    chat = KeyedChat(1280, tries=list(C_OUTCOMES))
    s = Start("try-c", fresh_disk("try-c"), chat, kernel=kernel, network="open")
    s.keys("Cy\n")
    s.key_tried(KEYS_C[0] + "\n")
    s.look("1-known-403")
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    for number, key in enumerate(KEYS_C[1:], start=2):
        s.keys("setup\n\n")
        s.key_tried(key + "\n")
        if number in (2, 3, 6, 7):
            s.look("%d-%s" % (number, {2: "known-402", 3: "page-403", 6: "unread-401", 7: "echoed-401"}[number]))
        s.keys("\n")
    s.look("8-locked-key-stays")
    s.end(secrets=KEYS_C + [PW])
    seen("try-c", KEYS_C)


def typed_during_the_try():
    """Keys typed while a slow refusal is awaited are not taken: Enter says why, signs typed after that Enter
    are not taken either, and the next key goes alone."""
    serve("slowrefusal,good")
    chat = KeyedChat(1280, tries=[("Unknown", REFUSED_SLOW), ("Works", GOOD)], instant=False)
    s = Start("try-d", fresh_disk("try-d"), chat, kernel=kernel, network="open")
    s.keys("Di\n")
    s.mark()
    s.keys(K1 + "\n")
    s.keys(EARLY[:5] + "\n")
    s.look("1-still-trying")
    s.keys(EARLY[5:])
    s.wait_text("does not know that key")
    s.chat.tried()
    s.look("2-refused-after-the-wait")
    s.mark()
    s.keys(K2 + "\n")
    s.wait_text("choose a password")
    s.chat.tried()
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    s.look("3-locked")
    memory(s, "memory", {K1: 0, EARLY: 0, K2: 1, PW: 0})
    s.end(secrets=[K1, K2, PW, EARLY])
    seen("try-d", [K1, K2])


def no_card():
    """A machine without a network card: the try is turned away at once, and the key is kept all the same."""
    chat = KeyedChat(1280, tries=[TRY_AWAY])
    options = {"kernel": kernel} if kernel else {}
    s = Start("try-e", fresh_disk("try-e"), chat, network=False, **options)
    s.keys("Ed\n")
    s.keys(K1 + "\n")
    s.look("1-cannot-try")
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    s.look("2-locked")
    s.end(secrets=[K1, PW])


def busy():
    """An answer to "ask" is still awaited when a key is typed at "setup": the try is turned away, the key is kept
    for this start, and the late answer is said as an ordinary row."""
    serve("silent")
    disk = fresh_disk("try-f")
    put_notebook(disk, [("name", b"Fi"), ("locked key", lock(PW.encode(), K2.encode(), os.urandom(16), os.urandom(12), 600000))])
    chat = KeyedChat(1280, kept_name=b"Fi", key_entry=LOCKED, password=PW, tries=[("away", "the answer to what I asked before has not come yet")])
    s = Start("try-f", disk, chat, kernel=kernel, network="open")
    s.keys(PW + "\n")
    s.wait(3)
    s.keys("ask\n")
    s.keys("setup\n\n")
    s.keys(K3 + "\n")
    s.look("1-turned-away")
    s.keys("\n")
    s.mark()
    s.wait_text("the site took too long", timeout=200)
    s.chat.say("no answer came, because the site took too long")
    s.look("2-late-answer")
    s.end(secrets=[K2, K3, PW])
    seen("try-f", [K2])


def odd_good_answer():
    """A good answer (200) in a shape the kernel cannot read: the provider took the key, so it works."""
    serve("otherform")
    sentence = ("the provider answered, but I could not find the model's words in its answer, because it has no such part. "
                'It begins "{"output": {"text": "Hello in another shape"}, "status": "done"}".')
    chat = KeyedChat(1280, tries=[("Works", sentence)])
    s = Start("try-g", fresh_disk("try-g"), chat, kernel=kernel, network="open")
    s.keys("Gi\n")
    s.key_tried(K1 + "\n")
    s.look("1-works-unread")
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    s.look("2-locked")
    s.end(secrets=[K1, PW])
    seen("try-g", [K1])


SCENARIOS = dict(refused=refused_then_works, setup=setup_refused_keeps_old, answers=answers, during=typed_during_the_try,
                 nocard=no_card, busy=busy, odd200=odd_good_answer)
if __name__ == "__main__":
    names = sys.argv[1:] or list(SCENARIOS)
    if any(n != "nocard" for n in names) or os.environ.get("BREAK"):
        kernel = build(PORT, roots=["a"], more=broken())
    try:
        for name in names:
            print(name)
            SCENARIOS[name]()
    finally:
        if server:
            server.kill()
    print("FAILURES:", failures if failures else "none")
