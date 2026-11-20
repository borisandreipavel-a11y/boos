"""Shift: capitals and the signs above the digits, typed through QEMU.
Usage: python test_shift.py <tag>
`steps` is the test itself; test_more.py with `shift` runs it in its own start, after its own keys."""

import os
import sys
import time

from boot import Machine
from picture import Chat, compare, expected, to_png
from verdict import Failures

PLAIN = "1234567890-=qwertyuiop[]asdfghjkl;'`\\zxcvbnm,./"
SHIFTED = "!@#$%^&*()_+QWERTYUIOP{}ASDFGHJKL:\"~|ZXCVBNM<>?"
NAMES = {"-": "minus", "=": "equal", "[": "bracket_left", "]": "bracket_right", ";": "semicolon", "'": "apostrophe",
         "`": "grave_accent", "\\": "backslash", ",": "comma", ".": "dot", "/": "slash", " ": "spc", "\n": "ret", "\b": "backspace"}


def name_of(sign):
    if sign in SHIFTED:
        base = PLAIN[SHIFTED.index(sign)]
        return "shift-" + NAMES.get(base, base)
    return NAMES.get(sign, sign)


def steps(machine, chat, look):
    """Shift's keys and pictures, in the chat box of a machine at the prompt. `look(name)` saves a picture, compares
    it with what `chat` says is meant, counts a wrong one and gives back the picture's file (or None)."""

    def keys(text):
        for sign in text:
            machine.command("sendkey %s 20" % name_of(sign))
            time.sleep(float(os.environ.get("KEY_PAUSE", "0.2")))
        chat.keys(text)

    def named(name, gives):
        machine.command("sendkey %s 20" % name)
        time.sleep(0.2)
        chat.keys(gives)

    keys("Hello, World!?")
    shot = look("1-hello-world-typed")
    if shot:
        to_png(shot, shot[:-4] + ".png")
    keys("\n")
    look("2-hello-world-sent")

    keys(SHIFTED + "\n")  # all 47 second signs
    look("3-every-second-sign")
    keys(PLAIN + "\n")  # and the first signs still work
    look("4-every-first-sign")

    named("shift_r-a", "A")           # the right Shift key
    named("shift-shift_r-b", "B")     # both at once
    named("shift-c-d", "CD")          # Shift held over two keys
    named("e", "e")                   # and let go again
    named("print-f", "f")             # Print Screen sends a Shift number of its own
    named("g", "g")
    named("caps_lock", "")            # Caps Lock does nothing
    named("h", "h")
    named("shift-spc", " ")           # Shift leaves the space bar alone
    named("shift-backspace", "\b")    # and Backspace
    named("shift-i", "I")
    named("shift-ret", "\n")          # and Enter
    last = look("5-special-cases")
    if last:
        to_png(last, last[:-4] + ".png")


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "shift"
    machine = Machine(tag)
    chat = Chat(1280)
    failures = Failures()

    def look(name):
        time.sleep(0.6)
        path = machine.shot(name)
        wrong, places = compare(path, expected(1280, 800, chat))
        print("%-30s %s" % (name, "every dot right" if wrong == 0 else "%d dots wrong %s" % (wrong, places[:2])))
        if wrong:
            failures.append(name)
        return path

    try:
        if not machine.wait_for(b"repeated here:"):
            print("the hint line never came")
            sys.exit(1)
        steps(machine, chat, look)
    finally:
        serial = machine.quit()

    ours = serial[serial.find(b"Hello from my kernel!"):]
    text = ours.decode(errors="replace")
    print(text[text.find("repeated here:") + 16:])
    bad = [b for b in ours if not (32 <= b <= 126 or b in (13, 10))]
    want = "\r\n".join(chat.said) + "\r\n"
    print("bytes that are not plain text:", len(bad), "| said lines as meant:", text.endswith(want))
    if not text.endswith(want) or bad:
        failures.append("terminal")
        print("meant:", chat.said)
    print("FAILURES:", failures if failures else "none")


if __name__ == "__main__":
    main()
