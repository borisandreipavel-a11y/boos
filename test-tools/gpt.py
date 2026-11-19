"""An independent look at a divided disk file, and a builder of such files for tests.
Uses Python's own CRC-32 (zlib), not the script's and not the kernel's."""
import struct
import uuid
import zlib

BLOCK = 512
BOOS = uuid.UUID("261e771e-cc8b-4a7f-96d1-b57fd92eafea")
START = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
OTHER = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")


def look(path):
    """Reads a disk file's list of parts and gives back what it finds, with every check an outside reader would make."""
    data = open(path, "rb").read()
    blocks = len(data) // BLOCK
    out = {"blocks": blocks, "problems": []}
    first = data[:BLOCK]
    records = [first[446 + i * 16:446 + (i + 1) * 16] for i in range(4)]
    out["old-style entry"] = any(r[4] == 0xEE and struct.unpack("<I", r[8:12])[0] == 1 for r in records)
    out["first block ends in 55 AA"] = first[510:512] == b"\x55\xaa"

    def head(at):
        h = data[at * BLOCK:(at + 1) * BLOCK]
        sig, rev, size, crc, res, here, other, fu, lu = struct.unpack("<8sIIIIQQQQ", h[:56])
        disk = uuid.UUID(bytes_le=h[56:72])
        entries_at, count, esize, ecrc = struct.unpack("<QIII", h[72:92])
        calc = zlib.crc32(h[:16] + b"\0\0\0\0" + h[20:size]) & 0xFFFFFFFF if 92 <= size <= BLOCK else None
        return dict(sig=sig, rev=rev, size=size, crc=crc, crc_right=(calc == crc), here=here, other=other, first_usable=fu,
                    last_usable=lu, disk=disk, entries_at=entries_at, count=count, esize=esize, ecrc=ecrc)

    h = head(1)
    out["head"] = h
    if h["sig"] != b"EFI PART":
        out["problems"].append("no signature")
        return out
    for name, ok in [("version 1.0", h["rev"] == 0x10000), ("head check value", h["crc_right"]), ("lies in block 1", h["here"] == 1),
                     ("other copy in the last block", h["other"] == blocks - 1)]:
        if not ok:
            out["problems"].append(name)
    raw = data[h["entries_at"] * BLOCK:h["entries_at"] * BLOCK + h["count"] * h["esize"]]
    if zlib.crc32(raw) & 0xFFFFFFFF != h["ecrc"]:
        out["problems"].append("entries check value")
    parts = []
    for i in range(h["count"]):
        e = raw[i * h["esize"]:(i + 1) * h["esize"]]
        kind = uuid.UUID(bytes_le=e[:16])
        if kind.int == 0:
            continue
        own = uuid.UUID(bytes_le=e[16:32])
        a, b, attributes = struct.unpack("<QQQ", e[32:56])
        name = e[56:128].decode("utf-16-le").rstrip("\0")
        parts.append(dict(kind=kind, own=own, first=a, last=b, name=name))
    out["parts"] = parts
    c = head(blocks - 1)
    out["copy"] = c
    craw = data[c["entries_at"] * BLOCK:c["entries_at"] * BLOCK + c["count"] * c["esize"]]
    for name, ok in [("copy: signature", c["sig"] == b"EFI PART"), ("copy: head check value", c["crc_right"]), ("copy: lies in the last block", c["here"] == blocks - 1),
                     ("copy: points back at block 1", c["other"] == 1), ("copy: same entries", craw == raw), ("copy: same disk number", c["disk"] == h["disk"]),
                     ("copy: entries check value", zlib.crc32(craw) & 0xFFFFFFFF == c["ecrc"])]:
        if not ok:
            out["problems"].append(name)
    return out


def build(path, megabytes=16, parts=None, change=None, entry_size=128, count=128, wipe_copy=False):
    """Writes a divided disk file. `parts` is a list of (kind, first, last, name); `change` may alter the head's
    fields or the raw blocks before they are written, to make damaged lists."""
    blocks = megabytes * 2048
    entry_blocks = (count * entry_size + BLOCK - 1) // BLOCK
    first_usable = 2 + entry_blocks
    last_usable = blocks - 2 - entry_blocks
    if parts is None:
        parts = [(BOOS, 2048, last_usable, "boos")]
    entries = bytearray(count * entry_size)
    for i, (kind, a, b, name) in enumerate(parts):
        e = kind.bytes_le + uuid.uuid4().bytes_le + struct.pack("<QQQ", a, b, 0) + name.encode("utf-16-le")
        entries[i * entry_size:i * entry_size + len(e)] = e
    fields = dict(sig=b"EFI PART", rev=0x10000, size=92, here=1, other=blocks - 1, first_usable=first_usable, last_usable=last_usable,
                  disk=uuid.uuid4(), entries_at=2, count=count, esize=entry_size, ecrc=zlib.crc32(bytes(entries)) & 0xFFFFFFFF, crc=None,
                  old_kind=0xEE, old_first=1)
    if change:
        change(fields, entries)

    def head(f):
        h = bytearray(BLOCK)
        h[:56] = struct.pack("<8sIIIIQQQQ", f["sig"], f["rev"], f["size"], 0, 0, f["here"], f["other"], f["first_usable"], f["last_usable"])
        h[56:72] = f["disk"].bytes_le
        h[72:92] = struct.pack("<QIII", f["entries_at"], f["count"], f["esize"], f["ecrc"])
        crc = f["crc"] if f["crc"] is not None else zlib.crc32(bytes(h[:min(max(f["size"], 0), BLOCK)])) & 0xFFFFFFFF
        h[16:20] = struct.pack("<I", crc)
        return h

    data = bytearray(blocks * BLOCK)
    first = bytearray(BLOCK)
    first[446:462] = bytes([0, 0, 2, 0, fields["old_kind"], 0xFF, 0xFF, 0xFF]) + struct.pack("<II", fields["old_first"], min(blocks - 1, 0xFFFFFFFF))
    first[510:512] = b"\x55\xaa"
    data[:BLOCK] = first
    data[BLOCK:2 * BLOCK] = head(fields)
    data[2 * BLOCK:2 * BLOCK + len(entries)] = entries
    copy = dict(fields, here=blocks - 1, other=1, entries_at=last_usable + 1, crc=None)
    data[(last_usable + 1) * BLOCK:(last_usable + 1) * BLOCK + len(entries)] = entries
    data[(blocks - 1) * BLOCK:] = head(copy)
    if wipe_copy:
        # No second copy at the end, so that a firmware cannot repair the first from it.
        data[(last_usable + 1) * BLOCK:] = bytes(len(data) - (last_usable + 1) * BLOCK)
    open(path, "wb").write(data)
    return path
