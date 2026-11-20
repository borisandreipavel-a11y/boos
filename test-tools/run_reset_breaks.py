"""Breaks `setup` bringing back the first look on purpose, one break at a time, in the project's own source, and sees
whether test_look_reset.py catches each one. Every changed file is put back byte for byte from what was read before
the break, with its time set to now, and the kernel is built again at the end. While it runs, nothing else may boot
this project's kernel. Usage: python run_reset_breaks.py [break ...]   (default: all)"""
import os
import subprocess
import sys
import time

from boot import PROJECT
from build_all import build

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(PROJECT, "src")

# label: (file, old, new, scenarios of test_look_reset.py that must catch it)
BREAKS = {
    "setup leaves the look as it was": ("onboarding.rs", "    look_reset();\n", "    if false {\n        look_reset();\n    }\n",
        ["atonce"]),
    "the first look not put in use": ("look.rs", "    unsafe { IN_USE = 0 };\n", "", ["atonce"]),
    "the screen not painted again at setup": ("look.rs", "    if changed {\n        look_paint();\n",
        "    if false {\n        look_paint();\n", ["atonce"]),
    "the first look not kept on the disk": ("look.rs",
        "        Some(place) if place != 0 => match notebook_keep(LOOK_ENTRY, &[]) {\n",
        "        Some(place) if place != 0 => match Ok::<(), &'static str>(()) {\n", ["midway"]),
    "the look kept before still counted as kept": ("look.rs", "                KEPT = None;\n", "", ["again"]),
    "an entry although look 1 is kept": ("look.rs", "Some(place) if place != 0 =>", "Some(place) =>", ["unchanged"]),
    "nothing said when the first look cannot be kept": ("look.rs",
        "            Err(reason) => unsafe { RESET_TROUBLE = Some((reason, place)) },\n", "            Err(_) => {}\n",
        ["damaged"]),
    "the rows about the look without the closing words": ("onboarding.rs",
        "        // box is free, so their last row says it.\n        last.push_str(TYPE_A_LINE);\n",
        "        // box is free, so their last row says it.\n", ["damaged"]),
}

if __name__ == "__main__":
    results = []
    originals = {}
    try:
        for label in sys.argv[1:] or list(BREAKS):
            file, old, new, scenarios = BREAKS[label]
            path = os.path.join(SRC, file)
            if path not in originals:
                originals[path] = open(path, "rb").read()
            text = originals[path].decode()
            if "\r\n" in text:
                old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
            assert text.count(old) == 1, (label, text.count(old))
            open(path, "wb").write(text.replace(old, new).encode())
            os.utime(path, (time.time(), time.time()))
            print("BREAK ON PURPOSE:", label, flush=True)
            build(quiet=True)
            run = subprocess.run([sys.executable, "test_look_reset.py"] + scenarios, cwd=HERE, capture_output=True, text=True)
            last = [l for l in run.stdout.splitlines() if l.startswith("FAILURES:")]
            caught = bool(last) and last[-1] != "FAILURES: none"
            wrong = [l.strip() for l in run.stdout.splitlines() if ("dots wrong" in l or ("terminal and disk" in l and "as meant" not in l) or "VAIN" in l)]
            print("   caught" if caught else "   NOT CAUGHT", "|", (wrong[0][:170] if wrong else (run.stdout + run.stderr)[-400:]), flush=True)
            results.append((label, caught))
            # Put the file back before the next break.
            open(path, "wb").write(originals[path])
            os.utime(path, (time.time(), time.time()))
    finally:
        for path, data in originals.items():
            open(path, "wb").write(data)
            os.utime(path, (time.time(), time.time()))
            assert open(path, "rb").read() == data, path
        build(quiet=True)
        print("source put back byte for byte and built again", flush=True)
    print("caught %d of %d" % (sum(c for _, c in results), len(results)))
