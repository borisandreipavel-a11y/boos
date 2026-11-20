"""Limits, long rows, more rows than fit, every sign. Usage:
   python test_more.py <tag> [size=WxH] [noscreen] [memory=96M] [shift] [qemu options...]
With `shift`, test_shift.py's keys and pictures follow in the same start, so that one boot serves both tests; the
terminal's rows are then checked for both."""

import sys
import time

from boot import Machine
from picture import Chat, compare, expected, to_png
from verdict import Failures

tag = sys.argv[1]
width, height, screen, memory, with_shift = 1280, 800, True, "256M", False
extra = []
for option in sys.argv[2:]:
    if option.startswith("size="):
        width, height = [int(n) for n in option[5:].split("x")]
    elif option == "noscreen":
        screen = False
    elif option.startswith("memory="):
        memory = option[7:]
    elif option == "shift":
        with_shift = True
    else:
        extra.append(option)
if with_shift and (not screen or (width, height) != (1280, 800)):
    sys.exit("`shift` needs the screen at 1280 by 800, as test_shift.py has it")

machine = Machine(tag, extra, memory=memory)
failures = Failures()
chat = Chat(width if screen else None)


def look(name):
    if not screen:
        return None
    time.sleep(0.6)  # let the kernel finish painting
    path = machine.shot(name)
    wrong, places = compare(path, expected(width, height, chat))
    print("%-28s %s" % (name, "every dot right" if wrong == 0 else "%d dots wrong %s" % (wrong, places)))
    if wrong:
        failures.append(name)
    return path


def keys(text, pause=0.08):
    machine.type(text, pause=pause, hold=20)
    chat.keys(text)


try:
    if not machine.wait_for(b"repeated here:"):
        print("the hint line never came")
        print(machine.serial().decode(errors="replace"))
        sys.exit(1)
    look("1-empty")

    keys("abcdefghij" * 5 + "vwxyz")  # 55 keys, the limit is 50
    look("2-line-at-the-limit")
    keys("\n")
    look("3-long-line-sent")

    keys("one\n")
    keys("two\n")
    look("4-rows-full")
    keys("three\n")
    keys("a much longer line than the ones before it\n")
    keys("x\n")
    look("5-oldest-gone-short-after-long")

    keys("take me away" + "\b" * 14)
    look("6-all-taken-away")

    keys("1234567890-=[];'`\\,./ qwertyuiopasdfghjklzxcvbnm")
    look("7-every-sign")
    keys("\n")
    last = look("8-every-sign-sent")
    if last:
        to_png(last, last[:-4] + ".png")
    if with_shift:
        from test_shift import steps
        print("--- Shift, in the same start")
        steps(machine, chat, lambda name: look("shift-" + name))
finally:
    serial = machine.quit()

start = serial.find(b"Hello from my kernel!")
ours = serial[start:]
text = ours.decode(errors="replace")
print("--- the terminal, from the hint on")
print(text[text.find("The processor rested"):])
bad_bytes = [b for b in ours if not (32 <= b <= 126 or b in (13, 10))]
bare = ours.replace(b"\r\n", b"")
print("bytes that are not plain text:", len(bad_bytes), "| stray 13 or 10:", bare.count(b"\r") + bare.count(b"\n"), "| lines:", ours.count(b"\r\n"))
for wanted in ["Free memory:", "Screen:", "The processor rested"]:
    print([line for line in text.split("\r\n") if line.startswith(wanted)])
want_said = "\r\n".join(chat.said) + "\r\n"
print("said lines as meant:", text.endswith(want_said))
if not text.endswith(want_said) or bad_bytes:
    failures.append("terminal")
print("FAILURES:", failures if failures else "none")
