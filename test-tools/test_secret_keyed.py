"""The secret line in the chat box. A made-up secret is typed through QEMU's keys only: it stands in no file
that goes into the kernel. After each step the picture is compared dot by dot, and at chosen moments the
terminal's bytes, the whole disk file and a dump of the machine's whole memory are searched for the secret and
for pieces of it.
Usage: python test_secret_keyed.py [tag]   (tag: usual, cirrus, nodisplay)"""
import contextlib
import os
import sys
import time

from interp_helpers import odd_bytes  # sets the divided disk
from boot import Machine
from boot_count import start_report
from picture import compare, expected
from keyed_model import KeyedChat as NamedChat
from nb import read_notebook
from verdict import Failures

# Made up, and chosen so that no piece of six signs occurs in a machine's memory by accident.
SECRET = "sk-orca-TEST_Qm7x/Zp4+Lw9vKd2Rb8nHt5Yc3=="
OTHER = "zq-Wj6#Xu1v"
tag = sys.argv[1] if len(sys.argv) > 1 else "usual"
width, height, extra = {"usual": (1280, 800, []), "cirrus": (800, 600, ["-vga", "cirrus"]), "nodisplay": (None, None, ["-vga", "none"])}[tag]
kernel = os.environ.get("KERNEL_FILE")
machine = Machine("secret-" + tag, extra, **({"kernel": kernel} if kernel else {}))
chat = NamedChat(width, kept_look=None)  # a fresh disk: nothing under "look" either
failures = Failures()
NAMES = {"-": "minus", "=": "equal", "/": "slash", "+": "shift-equal", "_": "shift-minus", "#": "shift-3", " ": "spc", chr(10): "ret", chr(8): "backspace"}
ENTER, BACK = chr(10), chr(8)
# Every line but `key` and `setup` goes to the model once a secret is held (docs/tools.md); this machine's network
# names no name server, so the answer is this row.
NO_ANSWER = "no answer came, because the network named no name server"


def answered(count):
    """Waits until the kernel has said for the `count`-th time that no answer came to a line, and adds the row."""
    end = time.time() + 30
    while time.time() < end and machine.serial().count(("Kernel: " + NO_ANSWER).encode()) < count:
        time.sleep(0.1)
    chat.say(NO_ANSWER)


def press(text):
    for sign in text:
        if sign in NAMES:
            name = NAMES[sign]
        elif sign.isupper():
            name = "shift-" + sign.lower()
        else:
            name = sign
        machine.command("sendkey " + name)
        # Keys with Shift are four key numbers each and pile up inside QEMU when sent quickly.
        time.sleep(0.22 if name.startswith("shift-") else 0.09)
        chat.key(sign)


def pieces(secret):
    """Every piece of 6 signs of a secret."""
    return [secret[i:i + 6].encode() for i in range(0, len(secret) - 5)]


def look(name, secrets, check_memory=True):
    """`secrets` is a list of (label, secret, whole copies meant in memory, loose pieces meant in memory)."""
    time.sleep(0.6)
    report = []
    if width:
        wrong, places = compare(machine.shot(name.replace(" ", "-")), expected(width, height, chat))
        report.append("picture: every dot right" if wrong == 0 else "picture: %d dots wrong %s" % (wrong, places))
        if wrong:
            failures.append(name + ": picture")
    serial = machine.serial()
    disk = open(machine.disk_path, "rb").read()
    with (machine.memory(name.replace(" ", "-")) if check_memory else contextlib.nullcontext()) as dump:
        for label, secret, whole_meant, loose_meant in secrets:
            in_serial = sum(serial.count(p) for p in pieces(secret))
            in_disk = sum(disk.count(p) for p in pieces(secret))
            text = "%s: terminal %d, disk %d" % (label, in_serial, in_disk)
            if in_serial or in_disk:
                failures.append("%s: %s leaked" % (name, label))
            if dump is not None:
                whole = dump.count(secret.encode())
                # A whole copy holds every 6-sign piece once; what is found beyond that is loose.
                loose = sum(dump.count(p) for p in pieces(secret)) - whole * len(pieces(secret))
                text += ", memory whole %d (meant %d), loose pieces %d (meant %d)" % (whole, whole_meant, loose, loose_meant)
                if whole != whole_meant or loose != loose_meant:
                    failures.append("%s: %s memory" % (name, label))
            report.append(text)
    print("%-36s %s" % (name, " | ".join(report)))


try:
    assert machine.wait_for(b"repeated here:"), machine.serial()[-400:]
    look("0 before anything", [("secret", SECRET, 0, 0), ("second", OTHER, 0, 0)])
    press(ENTER)  # the answer to the name question: Enter alone, so the name stays "You"
    press(ENTER)  # the question for the provider: Enter alone, so OrcaRouter stays
    press(ENTER)  # the question for the key: Enter alone, so no key is kept
    press(ENTER)  # the question for a look: Enter alone, so the first look stays
    look("0b the question answered", [("secret", SECRET, 0, 0)], check_memory=False)
    press("key" + ENTER)
    look("1 asked", [("secret", SECRET, 0, 0)], check_memory=False)
    press(SECRET[:20])
    # Twenty signs typed stand once in the room they are typed into: 15 pieces of six signs.
    look("2 twenty signs typed", [("secret", SECRET, 0, 15)])
    press(SECRET[20:])
    look("3 all signs typed", [("secret", SECRET, 1, 0)])
    press(BACK * 3)
    look("4 three signs taken away", [("secret", SECRET, 0, len(SECRET) - 3 - 5)])
    press(SECRET[-3:])
    press(ENTER)
    look("5 handed over", [("secret", SECRET, 1, 0)])
    press("hello after" + ENTER)
    answered(1)
    look("6 a normal line after it", [("secret", SECRET, 1, 0)])
    press("key" + ENTER)
    press(OTHER)
    look("7 a shorter second one typed", [("secret", SECRET, 1, 0), ("second", OTHER, 1, 0)])
    press(ENTER)
    look("8 the second one handed over", [("secret", SECRET, 0, 0), ("second", OTHER, 1, 0)])
    press("key" + ENTER)
    press("abc" + BACK * 3 + ENTER)
    look("9 asked again, nothing given", [("secret", SECRET, 0, 0), ("second", OTHER, 1, 0)])
    press("key" + ENTER + "x" + ENTER)
    look("10 a secret of one sign", [("secret", SECRET, 0, 0), ("second", OTHER, 0, 0)])
    # Lines that only look like the word go to the model; each answer is awaited before the next line, which would
    # otherwise be turned away while it is awaited.
    press("keys" + ENTER)
    answered(2)
    press("Key" + ENTER)
    answered(3)
    look("11 lines that only look like the word", [("second", OTHER, 0, 0)], check_memory=False)
finally:
    raw = machine.quit()
# The start itself, as boot_count.py reports it: this start is the same kind (a fresh divided disk), so one boot
# serves both checks.
start, wrong = start_report(raw)
print("the start: " + " | ".join(start[:2]))
for what in wrong:
    failures.append("the start: " + what)
raw = raw[raw.find(b"repeated here:"):]
lines = [l for l in raw.decode(errors="replace").split(chr(13) + chr(10)) if l.startswith(("You:", "Kernel:"))]
print("the terminal after the prompt:")
for line in lines:
    print("    " + line)
print("said lines as meant: %s | odd bytes %d" % (lines == chat.said, odd_bytes(raw)))
if lines != chat.said:
    failures.append("said lines")
    print("    meant:", chat.said)
kept = read_notebook(machine.disk_path)
print("the notebook, read from outside:", kept["entries"])
print("FAILURES:", failures or "none")
