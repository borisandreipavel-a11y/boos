"""Helpers for the tests of the interpreter on board: boot a kernel without a window and give back its lines
with the time at which each arrived."""
import os
import time

os.environ.setdefault("DIVIDED_DISK", "1")
from boot import Machine, KERNEL, HINT  # noqa: E402


def boot_lines(tag, seconds=120, kernel=KERNEL, until=HINT, **options):
    """Boots, waits for `until` (or a panic or fault), and gives back (lines with stamps, raw bytes)."""
    machine = Machine(tag, kernel=kernel, **options)
    start = time.time()
    seen = 0
    stamps = []
    try:
        while time.time() - start < seconds:
            data = machine.serial()
            begin = data.find(b"Hello from my kernel!")
            text = data[begin:] if begin >= 0 else b""
            lines = text.split(b"\r\n")[:-1]
            for line in lines[seen:]:
                stamps.append((time.time() - start, line.decode(errors="replace")))
            seen = len(lines)
            if until in data or b"Kernel panic" in data or b"CPU fault" in data or machine.process.poll() is not None:
                time.sleep(1.5)
                break
            time.sleep(0.01)
    finally:
        raw = machine.quit()
    begin = raw.find(b"Hello from my kernel!")
    raw = raw[begin:] if begin >= 0 else raw
    # lines that arrived in the last moment
    all_lines = raw.split(b"\r\n")[:-1]
    for line in all_lines[len(stamps):]:
        stamps.append((time.time() - start, line.decode(errors="replace")))
    return stamps, raw


def odd_bytes(raw):
    """Counts bytes that are neither plain signs nor part of a proper line end, and line ends that are not 13 10."""
    odd = 0
    for index, byte in enumerate(raw):
        if 32 <= byte <= 126:
            continue
        if byte == 13 and raw[index + 1:index + 2] == b"\n":
            continue
        if byte == 10 and index > 0 and raw[index - 1] == 13:
            continue
        odd += 1
    return odd


def line_of(stamps, start):
    for when, line in stamps:
        if line.startswith(start):
            return when, line
    return None, None
