"""Made-up PNG pictures and JPEG photos for the tests of pictures in documents (test_picture_documents.py): the files the
stand-in serves on the made-up site (download_cases.py hands it every address under /pictures/) and the files the tests
put on the disk from outside. Each is made here, the PNG pictures with Python's own zlib (png_reference.py) and the
photos with the project's own JPEG writer (jpeg_reference.py), the first time one is asked for, so that a stand-in that
serves none of them does not pay for them. What the kernel is meant to make of each comes from
picture_document_model.py; for the damaged ones, the reader's words are the crate's own (docs/pictures.md).

    data = picture("harbour")           # the bytes of the file
    data = served("/pictures/harbour.png")
    data = served("/pictures/photo.jpg")"""
import struct
import zlib

import jpeg_reference
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


# ---------- JPEG photos ----------

def _photo(width, height, factors, scans, frame=0xC0, seed=1, turn=None):
    """A made-up photo from blocks made straight away, without the forward transform, so that it is made fast: each
    block's DC follows a slope across the photo, and eight of its first AC coefficients come from a fixed sequence of
    numbers (xorshift32). T.81's example quantization tables (K.1)."""
    from make_jpeg_cases import CHROMA, LUMA
    state = [seed]

    def below(n):
        x = state[0]
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        state[0] = x
        return x % n

    geometry = jpeg_reference.Geometry(width, height, factors)
    blocks = []
    for c, component in enumerate(geometry.components):
        rows = []
        for y in range(component["down"]):
            row = []
            for x in range(component["across"]):
                block = [0] * 64
                block[0] = (x * 5 + y * 3 + c * 30) % 120 - 60
                for place in (1, 2, 3, 8, 9, 10, 16, 17):
                    block[place] = below(9) - 4
                row.append(block)
            rows.append(row)
        blocks.append(rows)
    components = [(c + 1, h, v, min(c, 1), min(c, 1), min(c, 1)) for c, (h, v) in enumerate(factors)]
    quants = {0: (0, LUMA)}
    if len(factors) > 1:
        quants[1] = (0, CHROMA)
    before = [(0xE1, jpeg_reference.exif_note(turn))] if turn else []
    return jpeg_reference.jpeg_write(width, height, components, blocks, quants, scans, frame=frame, before=before)


def _flat_progressive(width, height):
    """A progressive colour photo, 4:2:0, with its DC scan only and every block flat grey: one code in its table, a
    zero bit a block. Small, however large it says it is."""
    def segment(code, body):
        return bytes([0xFF, code]) + struct.pack(">H", len(body) + 2) + body
    out = b"\xff\xd8" + segment(0xDB, b"\x00" + b"\x01" * 64)
    out += segment(0xC2, struct.pack(">BHHB", 8, height, width, 3) + bytes([1, 0x22, 0, 2, 0x11, 0, 3, 0x11, 0]))
    out += segment(0xC4, bytes([0, 1] + [0] * 15 + [0]))
    out += segment(0xDA, bytes([3, 1, 0, 2, 0, 3, 0, 0, 0, 0]))
    bits = -(-width // 16) * -(-height // 16) * 6
    out += bytes(bits // 8) + (bytes([0xFF >> (bits % 8)]) if bits % 8 else b"")
    return out + b"\xff\xd9"


def _photos():
    """The photos: a baseline one to fetch, shrunk to fit a page; a progressive and a grey one shown at their own size;
    and those that must be turned down."""
    from make_jpeg_cases import PROGRESSIVE
    made = {}
    made["photo"] = _photo(1200, 900, [(2, 2), (1, 1), (1, 1)], [dict(parts=[0, 1, 2], kind="sequential", restart=4)])
    made["photoprog"] = _photo(400, 260, [(2, 2), (1, 1), (1, 1)], [dict(scan, restart=3) for scan in PROGRESSIVE], frame=0xC2,
                               seed=2)
    grey = _photo(300, 200, [(1, 1)], [dict(parts=[0], kind="sequential")], seed=3)
    made["photogrey"] = grey
    # Taken turned, as a phone keeps a photo taken upright: stored 300 by 200, its Exif note says turn 6, a quarter
    # turn clockwise, so it is seen 200 by 300.
    made["phototurned"] = _photo(300, 200, [(2, 2), (1, 1), (1, 1)], [dict(parts=[0, 1, 2], kind="sequential")], seed=4, turn=6)
    # Turned down: four components, as CMYK has; cut in the middle; a head that says 10000 by 10001 dots, just over the
    # kernel's limit of 100 million; a progressive photo of 10000 by 10000 dots, every block flat, whose blocks would
    # take 23 MB, more than the kernel lets it keep; a restart marker out of turn; and a GIF kept as a JPEG.
    made["cmyk"] = jpeg_reference.jpeg_write(8, 8, [(c + 1, 1, 1, 0, 0, 0) for c in range(4)], [[[[0] * 64]]] * 4,
                                             {0: (0, [1] * 64)}, [dict(parts=[0, 1, 2, 3], kind="sequential")])
    made["photocut"] = grey[:len(grey) // 2]
    frame = grey.index(b"\xff\xc0")
    made["photohuge"] = grey[:frame + 5] + struct.pack(">HH", 10001, 10000) + grey[frame + 9:]
    made["photobig"] = _flat_progressive(10000, 10000)
    restarted = made["photo"]
    marker = restarted.index(b"\xff\xd0", restarted.index(b"\xff\xda"))
    made["photorst"] = restarted[:marker + 1] + b"\xd5" + restarted[marker + 2:]
    made["notjpeg"] = b"GIF89a" + bytes(range(200))
    return made


# The reader's words for each photo that must be turned down (docs/pictures.md, "What it offers"), to stand after
# "because".
PHOTOS_REFUSED = {
    "cmyk": "it is a kind of JPEG I do not read: its colours are in other than 1 or 3 components, as CMYK's are in 4",
    "photocut": "the file ends before the picture does",
    "photohuge": "it is 10000 by 10001 dots, more than I show",
    "photobig": "it is 10000 by 10000 dots, more than I show",
    "photorst": "it is damaged: a restart marker is missing or out of turn",
    "notjpeg": "it does not begin as a JPEG photo does",
}


def picture(name):
    """The bytes of the made-up picture or photo `name`."""
    if not _made:
        _made["harbour"] = _harbour()
        _made.update(_kinds())
    if name not in _made and "photo" not in _made:
        _made.update(_photos())
    return _made[name]


def served(path):
    """The picture the made-up site serves at /pictures/<name>.png, or the photo at /pictures/<name>.jpg, or None."""
    if not path.startswith("/pictures/") or not path.endswith((".png", ".jpg")):
        return None
    try:
        return picture(path[len("/pictures/"):-len(".png")])
    except KeyError:
        return None
