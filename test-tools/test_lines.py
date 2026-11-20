"""The kernel's own lines on the screen: the start screen while the machine starts, judged dot by dot at moments
along the way; the usual picture in its place at the prompt; F1, a key, Enter and F1 again; a key during the
start; a smaller screen, where the lines move up; a machine without a screen; one without a serial port (played by
a copy of the kernel that finds none, lines_copy.py); lines printed while F1 shows the lines (a copy whose tasks
count longer); and F1 held down.

Usage: python test_lines.py [start] [early] [small] [noscreen] [noserial] [later] [held] [kernel=<path>]
Without names it runs all seven, on the project's kernel unless kernel= names another."""
import sys

from boot import KERNEL
from lines_checks import (LONGER_TASKS, NO_PORT, early_check, held_check, later_check, noscreen_check, noserial_check,
                          start_check)
from lines_copy import build

kernel = KERNEL
names = []
for argument in sys.argv[1:]:
    if argument.startswith("kernel="):
        kernel = argument[len("kernel="):]
    else:
        names.append(argument)
names = names or ["start", "early", "small", "noscreen", "noserial", "later", "held"]

failures = []
for name in names:
    print(name)
    if name == "start":
        problems = start_check(kernel)
    elif name == "early":
        problems = early_check(kernel)
    elif name == "small":
        # QEMU's display card of another make shows 800 by 600 dots: more lines go on in a second row, and the
        # screen fills before the start is over.
        problems = start_check(kernel, "lines-small", 800, 600, ["-vga", "cirrus"], moved=True)
    elif name == "noscreen":
        problems = noscreen_check(kernel)
    elif name == "noserial":
        problems = noserial_check(kernel, build({"serial.rs": [NO_PORT]}))
    elif name == "later":
        problems = later_check(build({"main.rs": [LONGER_TASKS]}))
    elif name == "held":
        problems = held_check(kernel)
    else:
        print("no such check:", name)
        sys.exit(2)
    failures += ["%s: %s" % (name, problem) for problem in problems]

print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
