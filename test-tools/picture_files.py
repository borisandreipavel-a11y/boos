"""Made-up PNG pictures for the tests of pictures in documents (test_picture_documents.py): the files the stand-in serves
on the made-up site (download_cases.py hands it every address under /pictures/) and the files the tests put on the
disk from outside. Each is made here, with Python's own zlib (png_reference.py), the first time it is asked for, so
that a stand-in that serves none of them does not pay for them. What the kernel is meant to make of each comes from
picture_document_model.py; for the damaged ones, the reader's words are the crate's own (docs/pictures.md).

    data = picture("harbour")           # the bytes of the file
    data = served("/pictures/harbour.png")"""
import struct
import zlib

from png_reference import SIGNATURE, part, png_write

_made = {}


def _rows_png(width, height, colour, depth, rows):
    """A PNG from its rows of samples as bytes, each behind filter 0, in one IDAT part."""
    head = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)
    return SIGNATURE + part("IHDR", head) + part("IDAT", zlib.compress(b"".join(b"\x00" + row for row in rows), 9)) + part("IEND", b"")


def _harbour():
    """640 by 480 dots, red, green, blue and alpha of 8 bits: colours that change across and down, wholly there in the
    upper half and see-through by every amount in the lower, so that its colours over the look's show the blend."""
    width, height = 640, 480
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            alpha = 255 if y < height // 2 else (x // 2 + y // 3) % 256
            row += bytes((x * 255 // (width - 1), y * 255 // (height - 1), (x // 16 ^ y // 16) * 16 % 256, alpha))
        rows.append(bytes(row))
    return _rows_png(width, height, 6, 8, rows)


def _grid(width, height, samples_at):
    return [[samples_at(x, y) for x in range(width)] for y in range(height)]


def _kinds():
    """Small pictures, shown at their own size, of most kinds a PNG has."""
    made = {}
    # Grey of 16 bits; the dots whose sample is 0x1234 are see-through (the transparency part's key, matched on all 16
    # bits, so 0x12ff beside it is not).
    grey = _grid(40, 30, lambda x, y: [0x1234 if (x + y) % 7 == 0 else (0x12ff if (x + y) % 7 == 1 else (x * 1500 + y * 700) % 65536)])
    made["grey16"] = png_write(grey, 40, 30, 0, 16, transparency=struct.pack(">H", 0x1234))[0]
    # A palette of 16 colours in 4 bits, with an alpha for each of the first ten.
    palette = [((n * 16) % 256, (255 - n * 15) % 256, (n * 40) % 256) for n in range(16)]
    made["pal4"] = png_write(_grid(33, 21, lambda x, y: [(x + 2 * y) % 16]), 33, 21, 3, 4, palette=palette,
                             transparency=bytes([0, 25, 50, 75, 100, 125, 150, 175, 200, 225]))[0]
    # Red, green, blue and alpha of 16 bits: only the high byte counts.
    made["rgba16"] = png_write(_grid(50, 20, lambda x, y: [x * 1300, y * 3000, (x * y * 97) % 65536, (x * 1200 + 300) % 65536]),
                               50, 20, 6, 16)[0]
    # Interlaced (Adam7), red, green, blue and alpha of 8 bits, of an odd size.
    made["lace"] = png_write(_grid(37, 23, lambda x, y: [x * 6, y * 11, (x + y) * 4, 255 - x * 3]), 37, 23, 6, 8, interlaced=True)[0]
    # Grey of 1 bit.
    made["grey1"] = png_write(_grid(64, 16, lambda x, y: [(x // 3 + y // 2) % 2]), 64, 16, 0, 1)[0]
    # Grey with alpha, 8 bits each.
    made["greya8"] = png_write(_grid(30, 30, lambda x, y: [x * 8, y * 8 + 7]), 30, 30, 4, 8)[0]
    # Red, green and blue of 16 bits, with a see-through key colour.
    rgb = _grid(25, 25, lambda x, y: [0x0102, 0x0304, 0x0506] if x == y else [x * 2600, y * 2600, 40000])
    made["rgb16"] = png_write(rgb, 25, 25, 2, 16, transparency=struct.pack(">HHH", 0x0102, 0x0304, 0x0506))[0]
    # A palette of 8 bits, its packed dots cut into IDAT parts of 7 bytes.
    palette = [(n, 255 - n, (n * 7) % 256) for n in range(256)]
    made["pieces"] = png_write(_grid(40, 40, lambda x, y: [(x * 6 + y) % 256]), 40, 40, 3, 8, palette=palette,
                               cut=lambda packed: [packed[at:at + 7] for at in range(0, len(packed), 7)])[0]
    # For the layout: a tall one and a wide one, shrunk to fit a page.
    made["tall"] = _rows_png(200, 600, 2, 8, [bytes(v for x in range(200) for v in (x, y * 255 // 599, 128)) for y in range(600)])
    made["wide"] = _rows_png(1000, 100, 2, 8, [bytes(v for x in range(1000) for v in (x % 256, 200, y * 2)) for y in range(100)])
    # A small good one, and the damaged ones made from it.
    small = _rows_png(20, 20, 2, 8, [bytes(v for x in range(20) for v in (x * 12, y * 12, 99)) for y in range(20)])
    made["small"] = small
    idat = small.index(b"IDAT")
    crc = bytearray(small)
    crc[idat + 6] ^= 0x01
    made["badcheck"] = bytes(crc)
    made["cut"] = small[:idat + 20]
    made["unknown"] = small[:idat - 4] + part("BOOS", b"made up") + small[idat - 4:]
    # One dot row more than the 9,000,000 dots the kernel shows.
    made["huge"] = SIGNATURE + part("IHDR", struct.pack(">IIBBBBB", 3000, 3001, 8, 2, 0, 0, 0)) + small[small.index(b"IDAT") - 4:]
    made["notpng"] = b"GIF89a" + bytes(range(200))
    filtered = _rows_png(20, 20, 2, 8, [bytes(60) for _ in range(20)])
    raw = zlib.decompress(filtered[filtered.index(b"IDAT") + 4:-12 - 4])
    raw = raw[:61 * 5] + b"\x07" + raw[61 * 5 + 1:]
    made["badfilter"] = SIGNATURE + part("IHDR", struct.pack(">IIBBBBB", 20, 20, 8, 2, 0, 0, 0)) + part("IDAT", zlib.compress(raw, 9)) + part("IEND", b"")
    return made


# The reader's words for each damaged picture (docs/pictures.md, "What it offers"), to stand after "because".
REFUSED = {
    "badcheck": "it is damaged: a part does not match its check value",
    "cut": "the file ends before the picture does",
    "unknown": 'it holds a part I cannot read, "BOOS"',
    "huge": "it is 3000 by 3001 dots, more than I show",
    "notpng": "it does not begin as a PNG picture does",
    "badfilter": "it is damaged: a row begins with a filter that does not exist",
}


def picture(name):
    """The bytes of the made-up picture `name`."""
    if not _made:
        _made["harbour"] = _harbour()
        _made.update(_kinds())
    return _made[name]


def served(path):
    """The picture the made-up site serves at /pictures/<name>.png, or None."""
    name = path[len("/pictures/"):-len(".png")] if path.startswith("/pictures/") and path.endswith(".png") else ""
    if not name:
        return None
    try:
        return picture(name)
    except KeyError:
        return None
