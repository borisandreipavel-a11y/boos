"""The unlocked key is the key that was typed: against the stand-in for the provider on this computer (in a copy
of the project, see net_copy.py), a made-up key is locked at one start, unlocked at the next, and `ask` is sent
each time. The stand-in writes down the key each request carried; it must be the typed key, byte for byte.
At the second start the password is typed while the start's own page fetch is at work.
Usage: python test_key_model.py"""
import json
import os
import subprocess
import sys
import time

from boot import HERE, RUNS, Machine
from certs import test_keys
from disk_helpers import one_disk
from net_copy import build
from onboard_model import name_of
from start_helper import fresh_disk

from ports import standin_port
PORT = standin_port(1)  # 44301 unless BOOS_PORT_BASE says otherwise
TLS = test_keys()
KEY = "sk-orca-TEST_Made-Up-Key-0123456789"
PW = "blue lamp"
failures = []


def press(machine, text, pause=0.22):
    for sign in text:
        machine.command("sendkey %s 20" % name_of(sign))
        time.sleep(pause)


def rows(machine):
    text = machine.serial().decode(errors="replace")
    return [line for line in text.split("\r\n") if line.startswith(("Kernel:", "Ada:", "Network:"))]


def wait_row(machine, words, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if any(words in row for row in rows(machine)):
            return True
        time.sleep(0.1)
    return False


kernel = build(PORT, roots=["a"])
log = os.path.join(RUNS, "model-server.log")
if os.path.exists(log):
    os.remove(log)
server = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT), os.path.join(TLS, "a", "both-chain.pem"),
                           os.path.join(TLS, "a", "both.key"), log, "good,good,good"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
assert server.stdout.readline().strip() == "ready"
disk = fresh_disk("key-model")
try:
    m = Machine("key-model-1", extra=one_disk(disk), disk=False, network="open", kernel=kernel)
    assert m.wait_for(b"repeated here:", 150)
    press(m, "Ada\n" + KEY + "\n")
    assert wait_row(m, "choose a password"), rows(m)[-5:]
    press(m, PW + "\n" + PW + "\n")
    assert wait_row(m, "the key is locked and kept"), rows(m)[-5:]
    press(m, "ask\n")
    ok = wait_row(m, "the model answered")
    serial = m.quit()
    print("start 1:")
    for row in rows(m)[-6:]:
        print("   ", row)
    if not ok:
        failures.append("start 1: no answer")

    m = Machine("key-model-2", extra=one_disk(disk), disk=False, network="open", kernel=kernel)
    # Type the password as soon as the machine has its address: the start's own page fetch then runs while the
    # password is turned into a key.
    assert m.wait_for(b"Network: this machine was given the address", 150)
    press(m, PW + "\n", pause=0.09)
    unlocked = wait_row(m, "the key is unlocked")
    fetched = wait_row(m, "Network: the whole page is")
    text = m.serial().decode(errors="replace")
    at_fetch = text.find("Network: the whole page is")
    at_unlocking = text.find("Kernel: unlocking the key")
    at_unlocked = text.find("Kernel: the key is unlocked")
    print("start 2: unlocking began %s the page had come, and ended %s it" % (
        "before" if at_unlocking < at_fetch else "after", "before" if at_unlocked < at_fetch else "after"))
    assert m.wait_for(b"repeated here:", 60)
    press(m, "ask\n")
    ok = wait_row(m, "the model answered")
    m.quit()
    for row in rows(m)[-8:]:
        print("   ", row)
    if not (unlocked and fetched and ok):
        failures.append("start 2: unlocked %s, fetched %s, answered %s" % (unlocked, fetched, ok))
finally:
    server.kill()

notes = [json.loads(line) for line in open(log)]
keys = [note.get("key came as") for note in notes if "key came as" in note]
print("the stand-in saw %d questions; each carried the typed key, byte for byte: %s" % (len(keys), keys == ["Bearer " + KEY] * 3))
if keys != ["Bearer " + KEY] * 3:
    failures.append("the key that came: %r" % [k[:12] + "..." for k in keys if k])
print("FAILURES:", failures or "none")
