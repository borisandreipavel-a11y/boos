"""Breaks on purpose for the pictures crate (pictures/): each puts one mistake into a copy of the crate and runs
the one test of its own that must catch it, which must then fail. It shows that the tests see what they are for.

    python run_picture_breaks.py            every break
    python run_picture_breaks.py NAME ...   only these

The copy is made in the work folder (places.WORK), never in the project; cargo's output goes there too. Each break
is a text swap in one file, which must be found exactly once. It changes no file of the kernel and boots nothing,
so run_tests.py runs it as one job (the entry "pictures breaks" in suites.py), which reads its last line:
"FAILURES: none", or the breaks not caught; each of those is said first on a line "FAILED: ...". It ends with 0
only when every break was caught."""
import os
import shutil
import subprocess
import sys

import places

CRATE = os.path.join(places.PROJECT, "pictures")
COPY = os.path.join(places.WORK, "pictures-break-copy")
TARGET = os.path.join(places.WORK, "pictures-break-target")
HOST = "x86_64-pc-windows-msvc"

# name: (file in src/, text, its mistake, the test that must catch it, what it breaks)
BREAKS = {
    "paeth-ties": ("png.rs", "} else if pb <= pc {", "} else if pb < pc {",
                   "pictures_read_whole", "Paeth's ties go to the byte above before the one above-left (RFC 2083, 6.6)"),
    "average-rounds-up": ("png.rs", "((u16::from(left) + u16::from(above)) / 2)",
                          "((u16::from(left) + u16::from(above) + 1) / 2)",
                          "pictures_read_whole", "the Average filter rounds down"),
    "filter-step": ("png.rs", "let left = if i >= step { row.get(i - step)", "let left = if i >= step { row.get(i - 1)",
                    "pictures_read_whole", "filters look back a whole dot, not a byte"),
    "length-258": ("unpack.rs", "195, 227, 258,", "195, 227, 257,",
                   "every_length_and_distance", "length code 285 stands for 258"),
    "distance-extra": ("unpack.rs", "12, 12, 13, 13];", "12, 12, 13, 12];",
                       "every_length_and_distance", "distance code 29 has 13 extra bits"),
    "no-part-check": ("png.rs", "if !crc_update(crc_update(0xffff_ffff, &name), data) != stored {",
                      "if false && !crc_update(crc_update(0xffff_ffff, &name), data) != stored {",
                      "check_values_kept", "each part's check value is checked"),
    "no-sum-check": ("unpack.rs", "if stored_sum != out.sum.value() {", "if false && stored_sum != out.sum.value() {",
                     "streams_turned_down", "the packed dots' Adler-32 is checked"),
    "fixed-nine-bits": ("unpack.rs", "144..=255 => 9,", "144..=255 => 8,",
                        "streams_unpack", "the fixed code gives literals 144 to 255 nine bits"),
    "alpha-rounds-down": ("shrink.rs", "(alpha + count / 2).checked_div(count)", "alpha.checked_div(count)",
                          "shrink_by_hand", "a shrunk dot's alpha is rounded to the nearest"),
    "palette-depth": ("png.rs", "colours > 1usize << head.depth", "colours > 256",
                      "heads_and_parts_turned_down", "a palette has no more colours than its depth can name"),
    "see-through-grey": ("png.rs", "let alpha = if layout.see_through == Some([grey, grey, grey]) { 0 } else { 255 };",
                         "let alpha = 255;", "pictures_read_whole", "the transparency part's grey is see-through"),
    "adam7-pass": ("png.rs", "(0, 0, 8, 8), (4, 0, 8, 8)", "(0, 0, 8, 8), (4, 0, 8, 4)",
                   "pictures_read_whole", "Adam7's second pass steps 8 down (RFC 2083, 2.6)"),
    "no-size-limit": ("png.rs", "if head.width > limits.side_most || head.height > limits.side_most || dots > limits.dots_most {",
                      "if false {", "limits_kept", "a picture larger than the limits is turned down first"),
    "short-reach": ("unpack.rs", "self.hand_on(REACH, sink)", "self.hand_on(REACH - 1, sink)",
                    "every_length_and_distance", "the last 32 KB stay for copies to reach back into"),
    "too-many-literals": ("unpack.rs", "if literal_count > 286 {", "if literal_count > 288 {",
                          "streams_turned_down", "a dynamic block has at most 286 literal codes"),
    "long-codes": ("unpack.rs", "code |= (ahead >> (length - 1)) & 1;", "code |= (ahead >> length) & 1;",
                   "streams_unpack", "codes longer than nine bits are read bit by bit, highest bit first"),
    "shown-in-room": ("shrink.rs", "if width * room_height >= height * room_width {",
                      "if width * room_height <= height * room_width {", "fitted_by_hand",
                      "a picture wider than the room fills its width"),
}


def fresh_copy():
    if os.path.exists(COPY):
        shutil.rmtree(COPY)
    shutil.copytree(CRATE, COPY, ignore=shutil.ignore_patterns("Cargo.lock", "target"))


def run_break(name):
    file, text, mistake, test, what = BREAKS[name]
    fresh_copy()
    path = os.path.join(COPY, "src", file)
    with open(path, encoding="utf-8", newline="") as f:
        source = f.read()
    if source.count(text) != 1:
        return "NOT APPLIED", "the text is found %d times in %s" % (source.count(text), file)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(source.replace(text, mistake))
    env = dict(os.environ, CARGO_TARGET_DIR=TARGET)
    done = subprocess.run(["cargo", "test", "--offline", "--target", HOST, "--lib", test, "--", "--exact",
                           "tests::" + test], cwd=COPY, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    output = done.stdout + done.stderr
    if "could not compile" in output:
        return "NOT BUILT", next((l for l in output.splitlines() if l.startswith("error")), "")
    if done.returncode != 0 and ("1 failed" in output or "FAILED" in output):
        why = next((l.strip() for l in output.splitlines() if "panicked" in l or "assertion" in l), "")
        return "caught", why
    return "MISSED", "%s passed with the mistake" % test


def main():
    names = sys.argv[1:] or list(BREAKS)
    unknown = [n for n in names if n not in BREAKS]
    if unknown:
        print("no such break: " + ", ".join(unknown))
        return 2
    missed = []
    for name in names:
        result, why = run_break(name)
        print("%-18s %-11s %s (%s)" % (name, result, BREAKS[name][4], why[:110]), flush=True)
        if result != "caught":
            missed.append(name)
            print("FAILED: break %s %s: %s" % (name, result, why[:150]), flush=True)
    shutil.rmtree(COPY, ignore_errors=True)
    print("%d of %d breaks caught" % (len(names) - len(missed), len(names)))
    print("FAILURES: " + (", ".join(missed) if missed else "none"), flush=True)
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
