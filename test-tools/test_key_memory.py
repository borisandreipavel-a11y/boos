"""The key and the passwords in memory: made-up ones typed through QEMU's keys only, so that they stand in no file
that goes into the kernel. At each step a dump of the machine's whole memory is searched for each of them, whole
and in pieces of six signs, and for the key that PBKDF2 makes from the password (worked out by Python from the
salt in the notebook). Also times locking and unlocking: from Enter to the row that says it is done.
Usage: python test_key_memory.py"""
import hashlib
import os
import time

from keyed_model import KeyedChat, LOCKED
from keyref import head_facts
from nb import newest, read_notebook
from start_helper import Start, failures, fresh_disk

KEY = "sk-orca-TEST_Wq8#Jd3!Mn5^Rt7*Kx2"
KEY2 = "ok-Prov-KEY2_Pz4@Ld6$Gh8%Xc1"
PW = "Vz7 qpL3 wk9"
WRONG = "Hy4 rt8 zm2"
PW_A = "Jk5 vb3 qq7"
PW_B = "Jk5 vb3 qq8"
ALL = [("key", KEY), ("key2", KEY2), ("pw", PW), ("wrong", WRONG), ("pw-a", PW_A), ("pw-b", PW_B)]


def pieces(text):
    return [text[i:i + 6].encode() for i in range(0, len(text) - 5)]


def check(s, name, meant, derived=None):
    """`meant`: label -> whole copies meant in memory; every other secret must be absent. No loose pieces anywhere."""
    time.sleep(0.6)
    report = []
    with s.m.memory(name) as data:
        for label, text in ALL:
            whole = data.count(text.encode())
            loose = sum(data.count(p) for p in pieces(text)) - whole * len(pieces(text))
            want = meant.get(label, 0)
            if whole or label in meant:
                report.append("%s %d" % (label, whole))
            if whole != want or loose:
                failures.append("%s: %s whole %d (meant %d), loose %d" % (name, label, whole, want, loose))
                report.append("(%s MEANT %d, LOOSE %d)" % (label, want, loose))
        if derived is not None:
            found = data.count(derived)
            report.append("derived key %d" % found)
            if found:
                failures.append(name + ": the derived key is in memory")
    print("  %-34s %s" % (name, ", ".join(report) or "nothing"))


def timed(s, words, timeout=30):
    """Seconds from now until the terminal holds `words` once more than it does now."""
    before = s.m.serial().count(words)
    start = time.time()
    while time.time() - start < timeout:
        if s.m.serial().count(words) > before:
            return time.time() - start
        time.sleep(0.05)
    return None


def derived_key(disk, password):
    locked = newest(read_notebook(disk)["entries"])["locked key"]
    _, _, rounds, salt, _ = head_facts(locked)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds, 32)


disk = fresh_disk("key-memory")
s = Start("memory", disk, KeyedChat(None), width=None)
check(s, "0-before", {})
s.keys("Ada\n")
s.keys(KEY)
check(s, "1-key-typed", {"key": 1})
s.keys("\n")
check(s, "2-key-handed-over", {"key": 1})
s.keys("Zq9\n")
s.keys(PW + "\n")
check(s, "3-password-once", {"key": 1, "pw": 1})
s.keys(PW)
check(s, "4-password-typed-again", {"key": 1, "pw": 2})
s.keys("\n")
seconds = timed(s, b"the key is locked and kept")
print("  locking took %.2f s from Enter to its row" % seconds)
check(s, "5-locked", {"key": 1}, derived=derived_key(disk, PW))
s.end(secrets=[text for _, text in ALL])

s = Start("memory-2", disk, KeyedChat(None, kept_name=b"Ada", key_entry=LOCKED, password=PW), width=None)
check(s, "6-before-the-password", {})
s.keys(WRONG + "\n")
seconds = timed(s, b"the key could not be unlocked")
print("  a wrong password took %.2f s" % seconds)
check(s, "7-wrong-password", {})
s.keys(PW + "\n")
seconds = timed(s, b"the key is unlocked")
print("  unlocking took %.2f s" % seconds)
check(s, "8-unlocked", {"key": 1}, derived=derived_key(disk, PW))
s.keys("setup\n\n")
s.keys(KEY2 + "\n")
check(s, "9-a-new-key", {"key2": 1})
s.keys(PW_A + "\n" + PW_B + "\n")
check(s, "10-passwords-differ", {"key2": 1})
s.keys("\n")
check(s, "11-this-start-only", {"key2": 1})
s.end(secrets=[text for _, text in ALL])

s = Start("memory-3", disk, KeyedChat(None, kept_name=b"Ada", last_line=b"setup", key_entry=LOCKED, password=PW), width=None)
s.keys("\n")
check(s, "12-without-the-key", {})
s.end(secrets=[text for _, text in ALL])
print("FAILURES:", failures or "none")
