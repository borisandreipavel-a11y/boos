"""The stop screen: for each case in lines_checks.STOP_CASES a copy of the kernel is built with a failure or a
panic made on purpose (right after the takeover, right after the kernel's own page tables, in the middle of the
start, with the usual picture on the screen, with the lines on it after F1, and in another task than the main
loop while the start screen shows), and the screen after it is judged dot by dot: dark red, the report at the top,
and below it the lines the kernel said before it.

Usage: python test_lines_stop.py [case ...]   (all cases without names)"""
import sys

from lines_checks import STOP_CASES, stop_check
from lines_copy import build

names = sys.argv[1:] or list(STOP_CASES)
failures = []
for name in names:
    change, _, _ = STOP_CASES[name]
    print(name)
    kernel = build({"main.rs": [change]})
    failures += ["%s: %s" % (name, problem) for problem in stop_check(kernel, name)]

print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
