"""Writes src/drawing_values.rs: for each of the 256 amounts of light a colour's red, green or blue can have, the
amount made linear, as WCAG 2 has it for its relative luminance (an amount v of 255 is c = v / 255; linear is
c / 12.92 when c is at most 0.04045, and ((c + 0.055) / 1.055) to the power 2.4 above), in millionths, rounded to
the nearest whole number. The kernel's check that a table's letters can be read is worked out in whole numbers with
it (docs/screen.md, "The table"); table_model.py works the same numbers out for the tests.

Usage: python make_drawing_values.py [project folder]"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import places  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else places.PROJECT


def linear(value):
    """The amount of light `value` (0 to 255) made linear, in millionths, rounded to the nearest."""
    c = value / 255
    made = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return int(made * 1_000_000 + 0.5)


LINEAR = [linear(value) for value in range(256)]
assert LINEAR[0] == 0 and LINEAR[255] == 1_000_000
assert all(a < b for a, b in zip(LINEAR, LINEAR[1:])), "the amounts must grow"

rows = []
for start in range(0, 256, 8):
    rows.append("    " + ", ".join("%d" % value for value in LINEAR[start:start + 8]) + ",")
text = ("//! The values the check that a table's letters can be read is worked out with (see `readable` in\n"
        "//! `drawing.rs`). Made by a script from outside the kernel, not written by hand:\n"
        "//! `test-tools/make_drawing_values.py`. Notes: `docs/screen.md`.\n"
        "\n"
        "// For each amount of light a colour's red, green or blue can have, from 0 to 255, that amount made\n"
        "// linear the way WCAG 2 has it for a colour's relative luminance, in millionths, rounded.\n"
        "pub const LINEAR: [u32; 256] = [\n" + "\n".join(rows) + "\n];\n")
path = os.path.join(PROJECT, "src", "drawing_values.rs")
open(path, "w", encoding="ascii", newline="\r\n").write(text)
print("written", path, len(text), "bytes")
