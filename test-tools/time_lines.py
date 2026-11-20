"""How much time showing the kernel's own lines on the screen adds to a start. Builds the kernel of another commit
(master unless named) from a clean export in the test folder, boots it and this project's kernel a few times
each without a window, in turns, and compares by this computer's clock when the lines of the start arrive. Every
span begins at the firmware's "Hello from my kernel!", before the lines first cover the screen.

Usage: python time_lines.py [boots] [commit]   (5 boots of each unless named)"""
import os
import shutil
import subprocess
import sys
import zipfile

from interp_helpers import boot_lines, line_of
from places import KERNEL, PROJECT, RUNS, WASM

boots = int(sys.argv[1]) if len(sys.argv) > 1 else 5
commit = sys.argv[2] if len(sys.argv) > 2 else "master"

# The other kernel: an export of the commit, with the project's interpreter (it is the same program).
named = subprocess.run(["git", "rev-parse", "--short", commit], cwd=PROJECT, capture_output=True, text=True, check=True).stdout.strip()
export = os.path.join(RUNS, "time-lines-" + named)
if not os.path.exists(os.path.join(export, "target", "x86_64-unknown-uefi", "debug", "boos.efi")):
    shutil.rmtree(export, ignore_errors=True)
    os.makedirs(export)
    packed = export + ".zip"
    subprocess.run(["git", "archive", "--format=zip", "-o", packed, named], cwd=PROJECT, check=True)
    with zipfile.ZipFile(packed) as archive:
        archive.extractall(export)
    os.remove(packed)
    os.makedirs(os.path.dirname(os.path.join(export, WASM)), exist_ok=True)
    shutil.copyfile(os.path.join(PROJECT, WASM), os.path.join(export, WASM))
    built = subprocess.run(["cargo", "build"], cwd=export, capture_output=True, text=True)
    if built.returncode != 0:
        print("THE OTHER KERNEL DID NOT BUILD")
        print(built.stderr[-3000:])
        sys.exit(1)
other = os.path.join(export, "target", "x86_64-unknown-uefi", "debug", "boos.efi")

# (what, from the line that begins so, to the line that begins so)
SPANS = [
    ("Hello to the line after the takeover", "Hello from my kernel!", "The firmware has stepped aside"),
    ("Hello to the lock's check", "Hello from my kernel!", "Lock:"),
    ("Hello to the network card's first line", "Hello from my kernel!", "Network card:"),
    ("rest count to the prompt", "The processor rested", "Click the QEMU window"),
    ("Hello to the prompt", "Hello from my kernel!", "Click the QEMU window"),
]
times = {"this kernel": [], named: []}
for number in range(boots):
    for name, kernel in [(named, other), ("this kernel", KERNEL)]:
        stamps, raw = boot_lines("time-lines-%d" % number, kernel=kernel)
        spans = []
        for what, first, last in SPANS:
            begun, _ = line_of(stamps, first)
            ended, _ = line_of(stamps, last)
            spans.append(None if begun is None or ended is None else ended - begun)
        times[name].append(spans)
        print("boot %d, %-12s %s" % (number + 1, name, ", ".join("%.2f s" % span if span is not None else "-" for span in spans)))

print()
for index, (what, _, _) in enumerate(SPANS):
    means = {}
    for name in times:
        values = [spans[index] for spans in times[name] if spans[index] is not None]
        means[name] = sum(values) / len(values) if values else None
    if None in means.values():
        print("%-46s not measured" % what)
        continue
    ranges = {name: (min(spans[index] for spans in times[name] if spans[index] is not None),
                     max(spans[index] for spans in times[name] if spans[index] is not None)) for name in times}
    print("%-40s %s %.2f s (%.2f to %.2f), this kernel %.2f s (%.2f to %.2f): %+.2f s" % (
        what, named, means[named], ranges[named][0], ranges[named][1], means["this kernel"],
        ranges["this kernel"][0], ranges["this kernel"][1], means["this kernel"] - means[named]))
