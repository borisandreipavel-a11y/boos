"""An independent reader and writer of the notebook, built from the written layout, with Python's own CRC-32.
Also a driver that boots a machine with a given disk, types lines and gives back what was printed.
Nothing runs when this file is imported."""
import os
import struct
import time
import zlib

from boot import Machine
from disk_helpers import RUNS, one_disk

BLOCK = 512
FIRST = 2048          # where the kernel's part begins on the usual test disk
LAST = 32734          # and where it ends
HEAD_LETTERS = b"boos notebook   "
ENTRY_LETTERS = b"boosnote"


def head(version=1, good=True, letters=HEAD_LETTERS):
    body = letters + struct.pack("<I", version)
    check = zlib.crc32(body) & 0xFFFFFFFF
    return (body + struct.pack("<I", check if good else check ^ 1)).ljust(BLOCK, b"\0")


def entry(number, name, data, good=True, name_length=None, data_length=None, letters=ENTRY_LETTERS):
    name = name if isinstance(name, bytes) else name.encode()
    data = data if isinstance(data, bytes) else data.encode()
    block = bytearray(BLOCK)
    block[0:8] = letters
    block[8:16] = struct.pack("<Q", number)
    block[16:18] = struct.pack("<H", len(name) if name_length is None else name_length)
    block[18:20] = struct.pack("<H", len(data) if data_length is None else data_length)
    text = (name + data)[:BLOCK - 32]
    block[32:32 + len(text)] = text
    check = zlib.crc32(bytes(block)) & 0xFFFFFFFF
    block[20:24] = struct.pack("<I", check if good else check ^ 1)
    return bytes(block)


def part_block(path, number, first=FIRST):
    with open(path, "rb") as f:
        f.seek((first + number) * BLOCK)
        return f.read(BLOCK)


def put_block(path, number, block, first=FIRST):
    assert len(block) == BLOCK
    with open(path, "r+b") as f:
        f.seek((first + number) * BLOCK)
        f.write(block)


def put_notebook(path, things, first=FIRST, start=1):
    """Writes a head and one entry per (name, data), numbered from `start`."""
    put_block(path, 0, head(), first)
    for place, (name, data) in enumerate(things):
        put_block(path, start + place, entry(start + place, name, data), first)


def read_entry(block, number):
    if block[:8] != ENTRY_LETTERS or struct.unpack("<Q", block[8:16])[0] != number:
        return None
    name_length, data_length = struct.unpack("<HH", block[16:20])
    if name_length < 1 or name_length > 32 or data_length > 448:
        return None
    name = block[32:32 + name_length]
    if any(not 32 <= b <= 126 for b in name):
        return None
    zeroed = block[:20] + b"\0\0\0\0" + block[24:]
    if zlib.crc32(zeroed) & 0xFFFFFFFF != struct.unpack("<I", block[20:24])[0]:
        return None
    return name.decode(), block[32 + name_length:32 + name_length + data_length]


def read_notebook(path, first=FIRST, last=LAST):
    """Reads a notebook the way the layout says. Gives back the head's state, the entries in order, and how many
    blocks behind the end are not zeros."""
    size = last - first + 1
    h = part_block(path, 0, first)
    if h == bytes(BLOCK):
        state = "no head"
    elif h[:16] != HEAD_LETTERS or zlib.crc32(h[:20]) & 0xFFFFFFFF != struct.unpack("<I", h[20:24])[0]:
        state = "unknown head"
    elif h[24:] != bytes(BLOCK - 24):
        state = "head with more in its block"
    else:
        state = "version %d" % struct.unpack("<I", h[16:20])[0]
    entries = []
    number = 1
    with open(path, "rb") as f:
        f.seek((first + 1) * BLOCK)
        while number <= size - 2:
            found = read_entry(f.read(BLOCK), number)
            if found is None:
                break
            entries.append(found)
            number += 1
        f.seek((first + number) * BLOCK)
        rest = f.read((size - 1 - number) * BLOCK)
    behind = [number + n for n in range(len(rest) // BLOCK) if rest[n * BLOCK:(n + 1) * BLOCK] != bytes(BLOCK)]
    return dict(head=state, entries=entries, end=number, behind=behind)


def newest(entries):
    out = {}
    for name, data in entries:
        out[name] = data
    return out


def changed(before, path, first=FIRST):
    """Which blocks of the disk file differ from an earlier state, as blocks of the kernel's part where they lie in it."""
    now = open(path, "rb").read()
    assert len(now) == len(before)
    out = []
    for n in range(len(now) // BLOCK):
        if now[n * BLOCK:(n + 1) * BLOCK] != before[n * BLOCK:(n + 1) * BLOCK]:
            out.append("part %d" % (n - first) if n >= first else "disk %d" % n)
    return out


def session(tag, disk, lines=(), kill=False, pause=0.2, shots=None, after=0.8, more=None, drive=None, **options):
    """Boots with the given disk file, waits for the prompt, types each line with Enter behind it, and ends the
    machine (by killing QEMU's process if `kill`). Gives back the kernel's printed lines."""
    extra = (drive if drive is not None else one_disk(disk)) + (more or [])
    m = Machine(tag, extra=extra, disk=False, **options)
    try:
        ok = m.wait_for(b"repeated here:", 150)
        if ok:
            if shots is not None:
                time.sleep(0.6)
                shots.append(m.shot("at-prompt"))
            for line in lines:
                m.type(line + "\n", pause=pause, hold=20)
            time.sleep(after)
            if shots is not None and lines:
                shots.append(m.shot("after-typing"))
    finally:
        if kill:
            m.process.kill()
            m.process.wait()
            try:
                m.monitor.close()
            except OSError:
                pass
            s = m.serial()
        else:
            s = m.quit()
    ours = s[s.find(b"Hello from my kernel!"):]
    odd = len([b for b in ours if not (32 <= b <= 126 or b in (13, 10))])
    return ours.decode(errors="replace").split("\r\n"), odd


def telling(lines):
    """The lines about the disk and the chat's lines."""
    return [l for l in lines if l.startswith(("Disk: the notebook", "Disk: a new notebook", "Disk: nothing", "Disk: this", "Disk: the count", "Kernel", "You:", "CPU fault"))]
