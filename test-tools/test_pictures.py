"""Runs the pictures crate's own tests (pictures/), on this computer, not in QEMU: the crate is code of the project's
own that turns a picture file into dots (docs/pictures.md), and it needs no machine to be tested.

    python test_pictures.py                  its tests, clippy, and a build for the kernel's target
    python test_pictures.py --cross-check    also: PNG pictures made by other programs on this computer, read by the
                                             crate and by the second reader (png_reference.py) and compared dot for dot

1. `cargo test` for this computer (x86_64-pc-windows-msvc): the tests in pictures/src/tests.rs, with the test
   pictures and streams of pictures/test-data/, and the count of memory in pictures/tests/memory.rs. They are
   built and run as a program on this computer; on a computer whose settings refuse programs that were built a
   moment ago, they cannot run.
2. `cargo clippy`, with every warning an error: the crate forbids, among others, indexing that could stop the
   kernel (see the top of pictures/src/lib.rs). Where clippy is not installed (GitHub's test computers install Rust's
   smallest set), this step says so and is passed over; the build check on GitHub (build.yml) installs it and runs
   this script whole.
3. `cargo build` for the kernel's own target (x86_64-unknown-uefi, from the project's .cargo/config.toml), which
   must give no warning.

Cargo's output goes to the work folder (places.WORK), never into the project, and the Cargo.lock that cargo writes
beside the crate is removed again if it was not there before. run_tests.py runs it as the entry "pictures" in
suites.py and reads its last line: "FAILURES: none", or the steps that failed, each said first on a line
"FAILED: ...". It ends with 0 only when every step passed.

The cross-check reads only: the PNG files that come with Python, with Git and with QEMU here (QEMU's many icons
sampled), each at most 4 MB and two million dots. Nothing of them is kept but in the work folder."""
import argparse
import os
import subprocess
import sys

import places
import png_reference

CRATE = os.path.join(places.PROJECT, "pictures")
MANIFEST = os.path.join(CRATE, "Cargo.toml")
TARGET = os.path.join(places.WORK, "pictures-target")
CROSS = os.path.join(places.WORK, "pictures-cross-check")
HOST = "x86_64-pc-windows-msvc"


def cargo(title, args, extra_env=None, no_warnings=False):
    """Runs cargo from the project folder; prints its last lines; True when it passed."""
    env = dict(os.environ, CARGO_TARGET_DIR=TARGET, **(extra_env or {}))
    done = subprocess.run(["cargo"] + args, cwd=places.PROJECT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    output = done.stdout + done.stderr
    lines = [line for line in output.splitlines() if line.strip() and not line.strip().startswith(("Compiling",
                                                                                                    "Checking"))]
    warned = no_warnings and any(line.lstrip().startswith("warning") for line in lines)
    passed = done.returncode == 0 and not warned
    print("== %s: %s" % (title, "passed" if passed else "FAILED"), flush=True)
    for line in lines[-25:] if not passed else [l for l in lines if "test result" in l or "held" in l]:
        print("   " + line, flush=True)
    if not passed:
        print("FAILED: %s%s" % (title, ", with a warning" if warned and done.returncode == 0 else ""), flush=True)
    return passed


def clippy_here():
    """Whether clippy is installed with the Rust in use."""
    done = subprocess.run(["cargo", "clippy", "--version"], cwd=places.PROJECT, capture_output=True, text=True)
    return done.returncode == 0


def pictures_here():
    """The PNG files that come with Python, Git and QEMU on this computer; QEMU's sampled to about 60."""
    found = []
    for root, most in ((sys.base_prefix, None), (r"C:\Program Files\Git", None), (places.QEMU_DIR, 60)):
        files = []
        for folder, _, names in os.walk(root):
            files += [os.path.join(folder, n) for n in names if n.lower().endswith(".png")]
        files.sort()
        if most and len(files) > most:
            step = len(files) // most
            files = files[::step][:most]
        found += files
    return found


def cross_check_prepare():
    """Reads each picture with the second reader; writes its dots and the list for the crate's test."""
    os.makedirs(CROSS, exist_ok=True)
    listed, refused, skipped = [], [], 0
    for n, path in enumerate(pictures_here()):
        if os.path.getsize(path) > 4 * 1024 * 1024:
            skipped += 1
            continue
        with open(path, "rb") as f:
            data = f.read()
        try:
            if data[16:24] and int.from_bytes(data[16:20], "big") * int.from_bytes(data[20:24], "big") > 2_000_000:
                skipped += 1
                continue
            width, height, dots = png_reference.png_read(data)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            refused.append((path, str(error)))
            continue
        name = "%d.rgba" % n
        with open(os.path.join(CROSS, name), "wb") as f:
            f.write(dots)
        listed.append("%s\t%d\t%d\t%s" % (path, width, height, name))
    with open(os.path.join(CROSS, "list.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(listed) + "\n")
    print("== cross-check: %d pictures read by the second reader, %d it turned down, %d skipped for size"
          % (len(listed), len(refused), skipped))
    for path, why in refused:
        print("   turned down by the second reader: %s (%s)" % (path, why))
    return len(listed)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cross-check", action="store_true", help="also compare with pictures made by other programs")
    options = parser.parse_args()
    lock = os.path.join(CRATE, "Cargo.lock")
    had_lock = os.path.exists(lock)
    results = {}
    try:
        results["tests"] = cargo("tests", ["test", "--offline", "--manifest-path", MANIFEST, "--target", HOST, "--",
                                           "--nocapture"])
        if clippy_here():
            results["clippy"] = cargo("clippy", ["clippy", "--offline", "--manifest-path", MANIFEST, "--target", HOST,
                                                 "--all-targets", "--", "-D", "warnings"])
        else:
            print("== clippy: not installed with this Rust, so not run here", flush=True)
        results["the kernel's target"] = cargo("the kernel's target", ["build", "--offline", "--manifest-path",
                                                                       MANIFEST], no_warnings=True)
        if options.cross_check:
            if cross_check_prepare():
                results["cross-check"] = cargo("cross-check", ["test", "--offline", "--manifest-path", MANIFEST,
                                                               "--target", HOST, "cross_check", "--", "--ignored",
                                                               "--nocapture"], extra_env={"PICTURES_CROSS_CHECK": CROSS})
    finally:
        if not had_lock and os.path.exists(lock):
            os.remove(lock)
    failed = [title for title, passed in results.items() if not passed]
    print("== %d of %d steps passed" % (len(results) - len(failed), len(results)))
    print("FAILURES: " + (", ".join(failed) if failed else "none"), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
