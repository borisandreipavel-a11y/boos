"""Makes the test pictures and packed streams of the pictures crate, kept in pictures/test-data/ as two files that the
crate's tests read (pictures/src/tests.rs): cases.bin, every test file one after another, and cases.txt, the list of
the cases and where each file lies in cases.bin. Two files rather than a hundred, so that the table of tests
(suites.py) can name them.

    python make_picture_cases.py

What is made is kept in the repository as made: another version of zlib may pack the same bytes differently, so
the files are not made again to check them. Each picture is also read back with the second reader
(png_reference.png_read) and compared with what was meant before it is written, so that a mistake here shows
here. The samples come from a fixed sequence of numbers, so every run makes the same pictures.

Lines of cases.txt:
    png NAME WIDTH HEIGHT                         NAME.png and NAME.rgba, its dots, four bytes each
    shrunk NAME ROOM_W ROOM_H SHOWN_W SHOWN_H     NAME-ROOM_WxROOM_H.rgba: NAME.png shown in that room
    raw NAME                                      NAME.raw: NAME.png's unpacked bytes, filter bytes and all
    zlib NAME LENGTH CRC32                        NAME.zlib: a zlib stream of LENGTH bytes whose CRC-32 is CRC32
    file NAME AT LENGTH                           the file NAME is the LENGTH bytes of cases.bin from AT on
"""
import os
import zlib

import png_reference as png

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "pictures", "test-data")


class Numbers:
    """A fixed sequence of numbers (xorshift32), so that every run makes the same files."""

    def __init__(self, seed):
        self.state = seed or 1

    def next(self):
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x

    def below(self, n):
        return self.next() % n


def samples_of(width, height, channels, top, numbers, smooth=False):
    """A picture's samples, each from 0 to `top`: noise, or a gentle slope with a little noise."""
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            if smooth:
                dot = [min(top, (x * 7 + y * 3 + c * 40) * top // 400 + numbers.below(3)) for c in range(channels)]
            else:
                dot = [numbers.below(top + 1) for _ in range(channels)]
            row.append(dot)
        rows.append(row)
    return rows


def palette_of(n, numbers):
    return [(numbers.below(256), numbers.below(256), numbers.below(256)) for _ in range(n)]


def tiny_parts(packed):
    """The packed dots cut into parts of 1, 0, 2, 0, 3 ... bytes: boundaries anywhere, and empty parts."""
    pieces, at, size = [], 0, 1
    while at < len(packed):
        pieces.append(packed[at:at + size])
        pieces.append(b"")
        at += size
        size = size % 7 + 1
    return pieces


def words(length, numbers):
    """Text of made-up words, for packing as text packs."""
    syllables = ["ka", "lo", "mi", "ne", "su", "ra", "to", "vi", "ze", "po", "qu", "de"]
    vocabulary = ["".join(syllables[numbers.below(12)] for _ in range(1 + numbers.below(4))) for _ in range(300)]
    out = bytearray()
    while len(out) < length:
        out += vocabulary[numbers.below(300)].encode() + (b"\n" if numbers.below(9) == 0 else b" ")
    return bytes(out[:length])


def main():
    os.makedirs(OUT, exist_ok=True)
    numbers = Numbers(20261124)
    lines = []
    files = []

    def write(name, data):
        files.append((name, data))

    def picture(name, width, height, colour, depth, smooth=False, palette_size=0, alpha_count=0, key=False,
                shown_in=(), keep_raw=False, **options):
        channels = png.CHANNELS[colour]
        top = (palette_size - 1) if colour == 3 else (1 << depth) - 1
        samples = samples_of(width, height, channels, top, numbers, smooth)
        palette = palette_of(palette_size, numbers) if colour == 3 else options.pop("palette", None)
        alphas = bytes(numbers.below(256) for _ in range(alpha_count))
        transparency, key_value = None, None
        if colour == 3 and alpha_count:
            transparency = alphas
        if key:
            # The first dot's samples are see-through, wherever they come again.
            key_value = tuple(samples[0][0]) if colour == 2 else (samples[0][0][0],) * 3
            transparency = b"".join(v.to_bytes(2, "big") for v in (key_value if colour == 2 else key_value[:1]))
        data, raw = png.png_write(samples, width, height, colour, depth, palette=palette, transparency=transparency,
                                  **options)
        meant = png.expected_rgba(samples, width, height, colour, depth, palette, alphas, key_value)
        read_width, read_height, read = png.png_read(data)
        assert (read_width, read_height, read) == (width, height, meant), name
        write(name + ".png", data)
        write(name + ".rgba", meant)
        lines.append("png %s %d %d" % (name, width, height))
        for room_width, room_height in shown_in:
            shown_width, shown_height, dots = png.shrink(width, height, meant, room_width, room_height)
            write("%s-%dx%d.rgba" % (name, room_width, room_height), dots)
            lines.append("shrunk %s %d %d %d %d" % (name, room_width, room_height, shown_width, shown_height))
        if keep_raw:
            write(name + ".raw", raw)
            lines.append("raw " + name)

    picture("g1", 13, 7, 0, 1, shown_in=[(5, 5)], keep_raw=True)
    picture("g2i", 9, 5, 0, 2, interlaced=True)
    picture("g4", 17, 3, 0, 4)
    picture("g8key", 33, 9, 0, 8, key=True)
    picture("g16key", 5, 7, 0, 16, key=True)
    picture("rgb8", 31, 17, 2, 8, shown_in=[(10, 10), (31, 5), (3, 17), (1, 1)], keep_raw=True)
    picture("rgb16key", 7, 9, 2, 16, key=True)
    picture("p1", 19, 4, 3, 1, palette_size=2)
    picture("p2t", 10, 6, 3, 2, palette_size=4, alpha_count=2)
    picture("p4", 23, 11, 3, 4, palette_size=16, keep_raw=True)
    picture("p8t", 40, 30, 3, 8, palette_size=200, alpha_count=100, shown_in=[(17, 9)], keep_raw=True)
    picture("ga8", 12, 12, 4, 8)
    picture("ga16", 6, 6, 4, 16, shown_in=[(4, 4)])
    picture("rgba8i", 29, 13, 6, 8, interlaced=True, shown_in=[(10, 10)], keep_raw=True)
    picture("rgba16", 9, 4, 6, 16)
    picture("one", 1, 1, 2, 8, interlaced=True)
    picture("three", 3, 3, 6, 8, interlaced=True)
    picture("stored", 50, 40, 2, 8, level=0)
    picture("fixed", 64, 32, 6, 8, smooth=True, strategy=zlib.Z_FIXED)
    picture("huff", 40, 40, 2, 8, strategy=zlib.Z_HUFFMAN_ONLY)
    picture("rle", 40, 40, 0, 8, smooth=True, strategy=zlib.Z_RLE)
    picture("win9", 64, 64, 2, 8, smooth=True, wbits=9)
    picture("parts", 20, 10, 6, 8, cut=tiny_parts)
    picture("extras", 16, 16, 2, 8, palette=[(1, 2, 3), (4, 5, 6)],
            before_dots=[("gAMA", (45455).to_bytes(4, "big")), ("tEXt", b"Title\x00made-up words")],
            after_dots=[("zzZz", b"a part no reader knows, which may be passed over")], after_end=b"anything at all")
    picture("big", 160, 120, 2, 8, smooth=True, shown_in=[(64, 64), (100, 30)])
    for kind in range(5):
        picture("filter%d" % kind, 24, 8, 2, 8, filters=lambda n, kind=kind: kind)

    def stream(name, data, level=6, wbits=15, strategy=zlib.Z_DEFAULT_STRATEGY, sync_every=0):
        packer = zlib.compressobj(level, zlib.DEFLATED, wbits, 9, strategy)
        if sync_every:
            packed = b""
            for at in range(0, len(data), sync_every):
                packed += packer.compress(data[at:at + sync_every]) + packer.flush(zlib.Z_SYNC_FLUSH)
            packed += packer.flush()
        else:
            packed = packer.compress(data) + packer.flush()
        assert zlib.decompress(packed) == data, name
        write(name + ".zlib", packed)
        lines.append("zlib %s %d %d" % (name, len(data), zlib.crc32(data) & 0xFFFFFFFF))

    text = words(200_000, numbers)
    noise = bytes(numbers.below(256) for _ in range(32_000))
    skewed = bytes(min(255, numbers.below(16) * numbers.below(16)) for _ in range(80_000))
    runs = b"".join(bytes([numbers.below(256)]) * (1 + numbers.below(400)) for _ in range(1000))
    stream("z-empty", b"")
    stream("z-one", b"a")
    stream("z-text", text)
    stream("z-fixed", text[:100_000], strategy=zlib.Z_FIXED)
    stream("z-huff", skewed, strategy=zlib.Z_HUFFMAN_ONLY)
    stream("z-rle", runs, strategy=zlib.Z_RLE)
    stream("z-stored", text[:70_000], level=0)
    stream("z-far", noise * 3, level=9)
    stream("z-win9", text[:60_000], wbits=9)
    stream("z-sync", text[:50_000], sync_every=7_000)
    stream("z-level1", text[:100_000], level=1)

    at = 0
    for name, data in files:
        lines.append("file %s %d %d" % (name, at, len(data)))
        at += len(data)
    with open(os.path.join(OUT, "cases.bin"), "wb") as f:
        f.write(b"".join(data for _, data in files))
    with open(os.path.join(OUT, "cases.txt"), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("%d cases, %d test files, %d bytes in %s" % (len(lines) - len(files), len(files), at, OUT))


if __name__ == "__main__":
    main()
