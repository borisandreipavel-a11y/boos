"""The key and the password: every picture against the model, the terminal's lines, the notebook read from outside
(a locked key is opened with Python's own PBKDF2 and an outside ChaCha20-Poly1305), and the made-up keys and
passwords searched for in the terminal and the disk file.
Usage: python test_key.py [scenario ...]   (default: all)"""
import os
import struct
import sys

from keyed_model import LOCKED, KeyedChat
from lockref import lock
from nb import put_notebook
from start_helper import Start, failures, fresh_disk

# Made up for these tests. Capitals, "_" and "-" are typed with Shift and without.
KEY = "sk-orca-TEST_Made-Up-Key-0123456789"
KEY2 = "sk-orca-TEST_Second-Made-Up_Key-987"
PW = "blue lamp"
PW2 = "new pass word"
NO_NAME_SERVER = "no answer came, because the network named no name server"


def locked_from_outside(password=PW, key=KEY, rounds=600000):
    return lock(password.encode(), key.encode(), os.urandom(16), os.urandom(12), rounds)


def locked():
    disk = fresh_disk("key-locked")
    s = Start("locked", disk, KeyedChat(1280))
    s.keys("Ada\n")
    s.keys(KEY[:12])
    s.look("1-key-typed-as-stars")
    s.key_tried(KEY[12:] + "\n")
    s.look("2-took-the-key")
    s.keys("abc\n")
    s.look("3-too-short")
    s.keys("lamp\n")
    s.keys("lamb\n")
    s.look("4-differ")
    s.keys(PW + "\n")
    s.look("5-same-again")
    s.keys(PW + "\n")
    s.wait(3)
    s.look("6-locked")
    # A line goes to the model with the key kept; this machine's network names no name server.
    s.mark()
    s.keys("hello\n")
    s.wait_text("no answer came")
    s.chat.say(NO_NAME_SERVER)
    s.end(secrets=[KEY, PW, "lamp", "lamb"])

    s = Start("locked-2", disk, KeyedChat(1280, kept_name=b"Ada", last_line=b"hello", key_entry=LOCKED, password=PW))
    s.look("1-password-question")
    s.keys("red lamp\n")
    s.wait(3)
    s.look("2-wrong")
    s.keys(PW + "\n")
    s.wait(3)
    s.look("3-unlocked")
    s.keys("ask\n")
    s.wait(2)
    s.chat.say(NO_NAME_SERVER)
    s.look("4-asked")
    s.end(secrets=[KEY, PW, "red lamp"])

    s = Start("locked-3", disk, KeyedChat(1280, kept_name=b"Ada", last_line=b"ask", key_entry=LOCKED, password=PW))
    s.keys("\n")
    s.look("1-without-the-key")
    s.keys("ask\n")
    s.look("2-no-key")
    s.end(secrets=[KEY, PW])


def older_disk():
    """A notebook like the one made before the key was asked for: lines and a name, nothing about a key."""
    disk = fresh_disk("key-older")
    put_notebook(disk, [("last line", b"a line"), ("name", b"Dee"), ("last line", b"before the key")])
    s = Start("older", disk, KeyedChat(1280, kept_name=b"Dee", last_line=b"before the key"))
    s.look("1-welcome-then-key-question")
    s.key_tried(KEY + "\n")
    s.keys(PW + "\n")
    s.keys(PW + "\n")
    s.wait(3)
    s.look("2-locked")
    s.end(secrets=[KEY, PW])
    s = Start("older-2", disk, KeyedChat(1280, kept_name=b"Dee", last_line=b"before the key", key_entry=LOCKED, password=PW))
    s.look("1-recall-then-password")
    s.keys(PW + "\n")
    s.wait(3)
    s.look("2-unlocked")
    s.end(secrets=[KEY, PW])


def this_start():
    disk = fresh_disk("key-thisstart")
    s = Start("thisstart", disk, KeyedChat(1280))
    s.keys("\n")
    s.key_tried(KEY + "\n")
    s.keys("\n")
    s.look("1-this-start-only")
    s.keys("ask\n")
    s.wait(2)
    s.chat.say(NO_NAME_SERVER)
    s.look("2-asked")
    s.end(secrets=[KEY])
    s = Start("thisstart-2", disk, KeyedChat(1280, kept_name=b"", last_line=b"ask", key_entry=b""))
    s.look("1-no-question")
    s.keys("ask\n")
    s.look("2-no-key")
    s.keys("setup\n\n")
    s.look("3-setup-asks-the-key")
    s.key_tried(KEY + "\n")
    s.keys("qzxw\n" + "\n")
    s.look("4-enter-alone-the-second-time")
    s.end(secrets=[KEY, "qzxw"])


def setup_new():
    disk = fresh_disk("key-setup")
    put_notebook(disk, [("name", b"Bo"), ("locked key", locked_from_outside())])
    s = Start("setup", disk, KeyedChat(1280, kept_name=b"Bo", key_entry=LOCKED, password=PW))
    s.keys(PW + "\n")
    s.wait(3)
    s.look("1-unlocked")
    s.keys("setup\n")
    s.keys("\n")
    s.look("2-new-key-question")
    s.key_tried(KEY2 + "\n")
    s.keys(PW2 + "\n")
    s.keys(PW2 + "\n")
    s.wait(3)
    s.look("3-locked-again")
    s.end(secrets=[KEY, KEY2, PW, PW2])
    s = Start("setup-2", disk, KeyedChat(1280, kept_name=b"Bo", last_line=b"setup", key_entry=LOCKED, password=PW2))
    s.keys(PW + "\n")
    s.wait(3)
    s.look("1-old-password-refused")
    s.keys(PW2 + "\n")
    s.wait(3)
    s.look("2-new-password-unlocks")
    s.end(secrets=[KEY, KEY2, PW, PW2])


def setup_stays():
    disk = fresh_disk("key-stays")
    put_notebook(disk, [("name", b"Bo"), ("locked key", locked_from_outside())])
    s = Start("stays", disk, KeyedChat(1280, kept_name=b"Bo", key_entry=LOCKED, password=PW))
    s.keys("\n")
    s.look("1-without")
    s.keys("setup\n\n")
    s.look("2-key-question-again")
    s.keys("\n")
    s.look("3-stays")
    s.end(secrets=[KEY, PW])


def odd_entries():
    good = locked_from_outside()
    cases = [
        ("version", bytes([2]) + good[1:], "the locked secret is of a version this kernel does not know"),
        ("way", good[:1] + bytes([2]) + good[2:], "the secret was locked in a way this kernel does not know"),
        ("rounds", good[:2] + struct.pack("<I", 10000001) + good[6:], "the locked secret asks for a count of rounds this kernel does not take"),
        ("no-rounds", good[:2] + struct.pack("<I", 0) + good[6:], "the locked secret asks for a count of rounds this kernel does not take"),
        ("short", good[:20], "it is too short to be a locked secret"),
        ("long", good + bytes(200), "it is too long to be a locked secret"),
        ("proof", good[:-1] + bytes([good[-1] ^ 1]), None),
    ]
    for label, data, trouble in cases:
        disk = fresh_disk("key-odd-" + label)
        put_notebook(disk, [("name", b"Cy"), ("locked key", data)])
        chat = KeyedChat(1280, kept_name=b"Cy", key_entry=LOCKED, password=None, trouble=trouble)
        s = Start("odd-" + label, disk, chat)
        s.keys(PW + "\n")
        s.wait(3 if trouble is None else 1)
        s.look("1-refused")
        if trouble is None:
            s.keys("\n")
            s.look("2-went-on")
        s.end(secrets=[KEY, PW])


def no_random():
    disk = fresh_disk("key-norandom")
    s = Start("norandom", disk, KeyedChat(1280, random=False), extra=["-cpu", "qemu64"])
    s.look("1-one-question")
    s.keys("Kay\n")
    s.look("2-no-random")
    s.end()
    disk = fresh_disk("key-norandom-unlock")
    put_notebook(disk, [("name", b"Kay"), ("locked key", locked_from_outside())])
    s = Start("norandom-2", disk, KeyedChat(1280, kept_name=b"Kay", key_entry=LOCKED, password=PW, random=False), extra=["-cpu", "qemu64"])
    s.keys(PW + "\n")
    s.wait(3)
    s.look("1-unlocked-anyway")
    s.keys("setup\n\n")
    s.look("2-setup-no-random")
    s.end(secrets=[KEY, PW])


def small_screen():
    disk = fresh_disk("key-small")
    s = Start("small", disk, KeyedChat(800), width=800, height=600, extra=["-vga", "cirrus"])
    s.keys("Gus Grimsby-Hartwell\n")
    s.look("1-key-rows-wrap")
    s.keys(KEY)
    s.look("2-thirty-stars-and-more")
    s.key_tried("\n")
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    s.look("3-locked")
    s.end(secrets=[KEY, PW])
    s = Start("small-2", disk, KeyedChat(800, kept_name=b"Gus Grimsby-Hartwell", key_entry=LOCKED, password=PW), width=800, height=600, extra=["-vga", "cirrus"])
    s.look("1-password-question-wraps")
    s.keys("wrong one\n")
    s.wait(3)
    s.look("2-wrong-wraps")
    s.keys(PW + "\n")
    s.wait(3)
    s.look("3-unlocked")
    s.end(secrets=[KEY, PW, "wrong one"])


def no_screen():
    disk = fresh_disk("key-noscreen")
    s = Start("noscreen", disk, KeyedChat(None), width=None, extra=["-vga", "none"])
    s.keys("Hal\n")
    s.key_tried(KEY + "\n")
    s.keys(PW + "\n" + PW + "\n")
    s.wait(3)
    s.end(secrets=[KEY, PW])
    s = Start("noscreen-2", disk, KeyedChat(None, kept_name=b"Hal", key_entry=LOCKED, password=PW), width=None, extra=["-vga", "none"])
    s.keys(PW + "\n")
    s.wait(3)
    s.end(secrets=[KEY, PW])


def during():
    """A line typed while the key is being unlocked waits until the work is done, and is then taken."""
    disk = fresh_disk("key-during")
    put_notebook(disk, [("name", b"Ed"), ("locked key", locked_from_outside())])
    s = Start("during", disk, KeyedChat(1280, kept_name=b"Ed", key_entry=LOCKED, password=PW))
    s.mark()
    s.keys(PW + "\n" + "hello\n")
    s.wait(3)
    # The line goes to the model with the key just unlocked; this machine's network names no name server.
    s.wait_text("no answer came")
    s.chat.say(NO_NAME_SERVER)
    s.look("1-line-after-unlock")
    s.end(secrets=[KEY, PW])


SCENARIOS = dict(locked=locked, older=older_disk, thisstart=this_start, setup=setup_new, stays=setup_stays, odd=odd_entries,
                 norandom=no_random, small=small_screen, noscreen=no_screen, during=during)
if __name__ == "__main__":
    for name in sys.argv[1:] or list(SCENARIOS):
        print(name)
        SCENARIOS[name]()
    print("FAILURES:", failures if failures else "none")
