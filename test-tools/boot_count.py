"""Boots a kernel (KERNEL_FILE) on a fresh divided disk to the prompt and reports its lines.
Usage: python boot_count.py <tag>"""
import os
import sys

from interp_helpers import boot_lines, odd_bytes  # sets the divided disk

stamps, raw = boot_lines(sys.argv[1])
lines = [line for _, line in stamps]
end = next((i for i, l in enumerate(lines) if l.startswith("Click the QEMU window")), None)
print("lines to the prompt:", end + 1 if end is not None else "THE PROMPT NEVER CAME")
print("bytes that are not plain text or stray line ends:", odd_bytes(raw))
for wanted in ("Free memory", "Lock:", "Interpreter:", "JSON:", "Disk: ", "Kernel:", "Kernel panic", "CPU fault"):
    found = [l for l in lines if l.startswith(wanted)]
    if found:
        print("  " + " | ".join(found))
