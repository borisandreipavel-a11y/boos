"""An outside reference for the lock: ChaCha20-Poly1305 written here in Python from RFC 8439 (not from the
kernel's code), PBKDF2 from Python's own hashlib, and the lock's layout from docs/lock.md.
Nothing runs when this file is imported; run it to check the ChaCha20-Poly1305 against RFC 8439's example."""
import hashlib
import struct

MASK = 0xFFFFFFFF


def _rotl(v, c):
    return ((v << c) & MASK) | (v >> (32 - c))


def _quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & MASK; s[d] ^= s[a]; s[d] = _rotl(s[d], 16)
    s[c] = (s[c] + s[d]) & MASK; s[b] ^= s[c]; s[b] = _rotl(s[b], 12)
    s[a] = (s[a] + s[b]) & MASK; s[d] ^= s[a]; s[d] = _rotl(s[d], 8)
    s[c] = (s[c] + s[d]) & MASK; s[b] ^= s[c]; s[b] = _rotl(s[b], 7)


def chacha20_block(key, counter, nonce):
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
    state += list(struct.unpack("<8I", key))
    state += [counter]
    state += list(struct.unpack("<3I", nonce))
    work = state[:]
    for _ in range(10):
        _quarter(work, 0, 4, 8, 12); _quarter(work, 1, 5, 9, 13); _quarter(work, 2, 6, 10, 14); _quarter(work, 3, 7, 11, 15)
        _quarter(work, 0, 5, 10, 15); _quarter(work, 1, 6, 11, 12); _quarter(work, 2, 7, 8, 13); _quarter(work, 3, 4, 9, 14)
    return struct.pack("<16I", *[(w + s) & MASK for w, s in zip(work, state)])


def chacha20(key, counter, nonce, data):
    out = bytearray()
    for i in range(0, len(data), 64):
        stream = chacha20_block(key, counter + i // 64, nonce)
        out += bytes(a ^ b for a, b in zip(data[i:i + 64], stream))
    return bytes(out)


def poly1305(key, message):
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(message), 16):
        n = int.from_bytes(message[i:i + 16] + b"\x01", "little")
        acc = ((acc + n) * r) % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(b):
    return b"\0" * ((16 - len(b) % 16) % 16)


def seal(key, nonce, plaintext, aad):
    """Gives the scrambled text and the 16-byte proof (tag)."""
    otk = chacha20_block(key, 0, nonce)[:32]
    ciphertext = chacha20(key, 1, nonce, plaintext)
    mac_data = aad + _pad16(aad) + ciphertext + _pad16(ciphertext) + struct.pack("<QQ", len(aad), len(ciphertext))
    return ciphertext, poly1305(otk, mac_data)


def lock(password, secret, salt, number, rounds):
    """The locked bytes, as docs/lock.md lays them out."""
    head = bytes([1, 1]) + struct.pack("<I", rounds) + salt + number
    key = hashlib.pbkdf2_hmac("sha256", password, salt, rounds, 32)
    ciphertext, tag = seal(key, number, secret, head)
    return head + ciphertext + tag


if __name__ == "__main__":
    key = bytes(range(0x80, 0xA0))
    nonce = bytes([0x07, 0, 0, 0]) + bytes(range(0x40, 0x48))
    aad = bytes([0x50, 0x51, 0x52, 0x53, 0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7])
    text = (b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
            b"sunscreen would be it.")
    ciphertext, tag = seal(key, nonce, text, aad)
    want_start = bytes.fromhex("d31a8d34648e60db7b86afbc53ef7ec2")
    want_end = bytes.fromhex("6116")
    want_tag = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")
    print("RFC 8439 2.8.2: text begins right %s, ends right %s, length %d (114 meant), proof right %s" % (
        ciphertext[:16] == want_start, ciphertext[-2:] == want_end, len(ciphertext), tag == want_tag))
