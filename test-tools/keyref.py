"""Unlocking from outside the kernel: a locked secret as docs/lock.md lays it out, opened with Python's own PBKDF2
and the ChaCha20-Poly1305 of lockref.py (written from RFC 8439 and checked against its example)."""
import hashlib
import struct

from lockref import chacha20, seal

HEAD = 34
PROOF = 16


def head_facts(locked):
    """Version, way, rounds, salt, number."""
    return locked[0], locked[1], struct.unpack("<I", locked[2:6])[0], locked[6:22], locked[22:34]


def unlock(password, locked):
    """The secret, or None if the layout is not version 1, way 1, or the proof does not fit."""
    if len(locked) < HEAD + PROOF:
        return None
    version, way, rounds, salt, number = head_facts(locked)
    if version != 1 or way != 1 or rounds == 0:
        return None
    head, body, proof = locked[:HEAD], locked[HEAD:-PROOF], locked[-PROOF:]
    key = hashlib.pbkdf2_hmac("sha256", password, salt, rounds, 32)
    secret = chacha20(key, 1, number, body)
    _, want = seal(key, number, secret, head)
    return secret if want == proof else None
