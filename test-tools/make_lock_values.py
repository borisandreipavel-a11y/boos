"""Writes src/lock_values.rs: the published values of RFC 7914 section 11 for PBKDF2-HMAC-SHA256, and one locked
secret made by the outside reference in lockref.py (Python's hashlib and a ChaCha20-Poly1305 written here from
RFC 8439), not by the kernel's code. Usage: python make_lock_values.py [project folder]"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lockref  # noqa: E402
import places  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else places.PROJECT

PUBLISHED_1 = bytes.fromhex("55ac046e56e3089fec1691c22544b605f94185216dde0465e68b9d57c20dacbc"
                            "49ca9cccf179b645991664b39d77ef317c71b845b1e30bd509112041d3a19783")
PUBLISHED_2 = bytes.fromhex("4ddcd8f60b98be21830cee5ef22701f9641a4418d04c0414aeff08876b34ab56"
                            "a1d425a1225833549adb841b51c9b3176a272bdebba1d078478f62b397f33c8d")
# The published values must be what Python's own hashlib gives too.
assert hashlib.pbkdf2_hmac("sha256", b"passwd", b"salt", 1, 64) == PUBLISHED_1
assert hashlib.pbkdf2_hmac("sha256", b"Password", b"NaCl", 80000, 64) == PUBLISHED_2

PASSWORD = b"a password made up for the check"
SECRET = b"a secret made up for the check, 46 signs long."
SALT = bytes(range(0x10, 0x20))
NUMBER = bytes(range(0x40, 0x4C))
ROUNDS = 1000
LOCKED = lockref.lock(PASSWORD, SECRET, SALT, NUMBER, ROUNDS)
assert len(LOCKED) == 34 + len(SECRET) + 16


def array(name, kind, data, note):
    rows = []
    for i in range(0, len(data), 16):
        rows.append("    " + ", ".join("0x%02x" % b for b in data[i:i + 16]) + ",")
    return "%s\npub const %s: [%s; %d] = [\n%s\n];\n" % (note, name, kind, len(data), "\n".join(rows))


out = []
out.append("//! The values the check of the lock is made against (see `lock_check` in `lock.rs`).\n"
           "//! Made by a script from outside the kernel, not written by hand: the first two are published in\n"
           "//! RFC 7914, section 11; the locked secret was made by another implementation of the same steps\n"
           "//! (Python's own PBKDF2, and a ChaCha20-Poly1305 written from RFC 8439 and checked against its\n"
           "//! example). Notes: `docs/lock.md`.\n")
out.append(array("PUBLISHED_1", "u8", PUBLISHED_1,
                 "\n// PBKDF2 with HMAC-SHA256, the password \"passwd\", the salt \"salt\", 1 round, 64 bytes."))
out.append(array("PUBLISHED_2", "u8", PUBLISHED_2,
                 "\n// The same with the password \"Password\", the salt \"NaCl\", 80,000 rounds, 64 bytes."))
out.append("\n// A secret locked with a password, a salt, a number and a count of rounds, all made up.\n"
           "pub const CHECK_PASSWORD: &[u8] = b\"%s\";\n" % PASSWORD.decode())
out.append("pub const CHECK_SECRET: &[u8] = b\"%s\";\n" % SECRET.decode())
out.append(array("CHECK_SALT", "u8", SALT, ""))
out.append(array("CHECK_NUMBER", "u8", NUMBER, ""))
out.append("pub const CHECK_ROUNDS: u32 = %d;\n" % ROUNDS)
out.append(array("CHECK_LOCKED", "u8", LOCKED, "\n// What locking them must give."))
text = "".join(out).replace("\n\n\n", "\n\n")
path = os.path.join(PROJECT, "src", "lock_values.rs")
open(path, "w", encoding="ascii", newline="\n").write(text)
print("written", path, len(text), "bytes; locked secret", len(LOCKED), "bytes")
