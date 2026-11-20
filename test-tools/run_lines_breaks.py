"""Breaks of the kernel's own lines on the screen made on purpose, each alone, in a copy of the project
(lines_copy.py; nothing in the project is changed), and whether the checks of lines_checks.py catch them. A
check of a stop screen gets its failure on purpose (lines_checks.STOP_CASES) in the same copy, and the check
"noserial" gets the copy's kernel that finds no serial port, with the break in it too.

Usage: python run_lines_breaks.py [the beginning of a label ...]"""
import sys

from lines_checks import (LONGER_TASKS, NO_PORT, STOP_CASES, early_check, held_check, later_check, noscreen_check,
                          noserial_check, start_check, stop_check)
from lines_copy import build
from places import KERNEL

# label: (file, old, new, the checks that must catch it). The texts are the files' own, with line ends as "\n".
BREAKS = {
    "the lines not shown while the machine starts": (
        "main.rs", "        screen_setup(found);\n        lines_begin();\n", "        screen_setup(found);\n", ["start"]),
    "the usual picture not held": (
        "screen.rs", "pub fn screen_rectangle(left: u32, top: u32, width: u32, height: u32, colour: Colour) {\n"
        "    if unsafe { COVERED } {\n        return;\n    }\n",
        "pub fn screen_rectangle(left: u32, top: u32, width: u32, height: u32, colour: Colour) {\n", ["start"]),
    "the start screen never ends": (
        "lines.rs", "    if unsafe { SHOWING } == Showing::Start {\n", "    if false {\n", ["start"]),
    "the usual picture not painted when the lines go": (
        "lines.rs", "    screen_cover(false);\n    look_paint();\n", "    screen_cover(false);\n", ["start", "early"]),
    "the tasks' lines not painted by the main loop": (
        "main.rs", "        lines_paint_new();\n", "", ["start"]),
    "F1 does nothing": (
        "lines.rs", "    } else if key == F1_KEY {\n", "    } else if false {\n", ["start"]),
    "a key does not end the lines": (
        "lines.rs", "    if unsafe { SHOWING } != Showing::Picture {\n", "    if false {\n", ["start", "early"]),
    "F1 held down counted again": (
        "lines.rs", "    if key == F1_KEY && unsafe { F1_HELD } {\n", "    if false {\n", ["held"]),
    "lines printed while F1 shows them not painted": (
        "lines.rs", "    if !screen_covered() {\n", "    if unsafe { SHOWING } != Showing::Start {\n", ["later"]),
    "the screen not filled when the lines are painted whole": (
        "lines.rs", "    screen_rectangle_over(0, 0, width, height, LINES_BACKGROUND);\n", "", ["small"]),
    "the older lines do not move up": (
        "lines.rs", "            lines_paint_newest(number, rows / 2, room, rows);\n", "", ["small"]),
    "a long line not carried on in the next row": (
        "lines.rs", "        let (piece, after) = rest.split_at(rest.len().min(room as usize));\n",
        "        let (piece, after) = rest.split_at(rest.len());\n", ["small"]),
    "the lines kept only with a serial port": (
        "serial.rs", "    lines_keep(text);\n    // Without a serial port there is nowhere else to print to.\n"
        "    if unsafe { SERIAL_FOUND } {\n",
        "    // Without a serial port there is nowhere else to print to.\n    if unsafe { SERIAL_FOUND } {\n"
        "        lines_keep(text);\n", ["noserial"]),
    "the stop screen not painted after a failure": (
        "faults.rs", "    lines_stop_screen();\n", "", ["stop-picture"]),
    "the stop screen not painted after a panic": (
        "main.rs", "    lines_stop_screen();\n    stop()\n", "    stop()\n", ["stop-panic"]),
    "the report left off the stop screen": (
        "lines.rs", "        row = line_paint(&report[..length], row, room, rows, STOP_LETTERS);\n", "", ["stop-own"]),
    "a failure early on painted in the lines' colours": (
        "lines.rs", "    screen_rectangle_over(0, 0, width, height, STOP_BACKGROUND);\n",
        "    screen_rectangle_over(0, 0, width, height, LINES_BACKGROUND);\n", ["stop-firmware"]),
    "no stop screen while the lines cover the screen": (
        "lines.rs", "    if unsafe { STOP_PAINTED } {\n", "    if unsafe { STOP_PAINTED } || screen_covered() {\n", ["stop-view"]),
}


def check(name, kernel):
    if name == "start":
        return start_check(kernel, "break-start")
    if name == "early":
        return early_check(kernel, "break-early")
    if name == "small":
        return start_check(kernel, "break-small", 800, 600, ["-vga", "cirrus"], moved=True)
    if name == "noscreen":
        return noscreen_check(kernel, "break-noscreen")
    if name == "later":
        return later_check(kernel, "break-later")
    if name == "held":
        return held_check(kernel, "break-held")
    return stop_check(kernel, name)


wanted = sys.argv[1:]
missed = []
for label, (file, old, new, names) in BREAKS.items():
    if wanted and not any(label.startswith(beginning) for beginning in wanted):
        continue
    for name in names:
        changes = {file: [(old, new)]}
        if name in STOP_CASES:
            changes.setdefault("main.rs", []).append(STOP_CASES[name][0])
        if name == "later":
            changes.setdefault("main.rs", []).append(LONGER_TASKS)
        if name == "noserial":
            changes.setdefault("serial.rs", []).insert(0, NO_PORT)
            problems = noserial_check(KERNEL, build(changes), "break-noserial")
        else:
            problems = check(name, build(changes))
        print("%-58s %-14s %s" % (label, name, "caught" if problems else "NOT CAUGHT"))
        if not problems:
            missed.append("%s (%s)" % (label, name))

print("NOT CAUGHT:", missed if missed else "none")
sys.exit(1 if missed else 0)
