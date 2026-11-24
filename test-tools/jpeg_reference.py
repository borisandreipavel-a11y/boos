"""JPEG photos for the tests of the pictures crate (pictures/), written and read here in Python, from the rules that
docs/pictures.md ("JPEG") writes down.

- `jpeg_write` makes a JPEG file from blocks of coefficients: a baseline, extended or progressive frame of one or
  three components, any whole sampling ratios, quantization tables of 8 or 16 bits, Huffman tables made for each
  scan (or with codes of up to 16 bits on purpose), restart intervals, and other segments and fill bytes anywhere a
  file may have them. The scans' coding follows T.81's Annexes F and G.
- `jpeg_read` is a second reader, written apart from the crate's: it keeps every coefficient of every block, and it
  reads the test photos again, so that a mistake of the writer shows here before the crate sees the file.
- `jpeg_dots` turns a photo into dots for a room as the crate does: the size it is read at, the inverse transforms
  in whole numbers, the colours, and the shrinking.

Every rule follows ITU-T T.81 and JFIF 1.02, as the page says. Nothing here reads a file but those it is given."""
import math
import struct
from collections import Counter

# Where each of a block's coefficients, in the zig-zag order they are sent in, lies in the block's natural order,
# row by row (T.81, A.3.6).
ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7,
          14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46,
          53, 60, 61, 54, 47, 55, 62, 63]

# The page's table of K(u, x) = round(8192 x 1/2 x C(u) x cos((2x + 1) u pi / 16)), worked out again below.
K = [[2896, 2896, 2896, 2896, 2896, 2896, 2896, 2896],
     [4017, 3406, 2276, 799, -799, -2276, -3406, -4017],
     [3784, 1567, -1567, -3784, -3784, -1567, 1567, 3784],
     [3406, -799, -4017, -2276, 2276, 4017, 799, -3406],
     [2896, -2896, -2896, 2896, 2896, -2896, -2896, 2896],
     [2276, -4017, 799, 3406, -3406, -799, 4017, -2276],
     [1567, -3784, 3784, -1567, -1567, 3784, -3784, 1567],
     [799, -2276, 3406, -4017, 4017, -3406, 2276, -799]]
assert K == [[round(8192 * 0.5 * (math.sqrt(0.5) if u == 0 else 1.0) * math.cos((2 * x + 1) * u * math.pi / 16))
              for x in range(8)] for u in range(8)]


def ceil_div(a, b):
    return -(-a // b)


def clamp(value):
    return 0 if value < 0 else 255 if value > 255 else value


# ---------- The frame's sizes ----------

class Geometry:
    """A frame's sizes (T.81, A.1.1, A.2.2, A.2.3): its units across and down, as a scan of several components
    has them, and for each component its sampling factors (1 and 1 in a frame of one component), its blocks as they
    are kept (whole units' worth) and the blocks a scan of it alone has."""

    def __init__(self, width, height, factors):
        if len(factors) == 1:
            factors = [(1, 1)]
        self.width, self.height = width, height
        self.h_most = max(h for h, _ in factors)
        self.v_most = max(v for _, v in factors)
        self.units_across = ceil_div(width, 8 * self.h_most)
        self.units_down = ceil_div(height, 8 * self.v_most)
        self.components = []
        for h, v in factors:
            self.components.append(dict(
                h=h, v=v, across=self.units_across * h, down=self.units_down * v,
                own_across=ceil_div(ceil_div(width * h, self.h_most), 8),
                own_down=ceil_div(ceil_div(height * v, self.v_most), 8)))


def empty_blocks(geometry):
    """For each component, its kept blocks, each 64 zeros in natural order: blocks[c][y][x]."""
    return [[[[0] * 64 for _ in range(c["across"])] for _ in range(c["down"])] for c in geometry.components]


def scan_blocks(geometry, parts):
    """The blocks of a scan, unit by unit: each unit a list of (part, component, x, y). A scan of one component
    has its own blocks one by one (A.2.2); one of several has units of each component's h by v blocks (A.2.3)."""
    if len(parts) == 1:
        c = geometry.components[parts[0]]
        return [[(0, parts[0], x, y)] for y in range(c["own_down"]) for x in range(c["own_across"])]
    units = []
    for unit_y in range(geometry.units_down):
        for unit_x in range(geometry.units_across):
            unit = []
            for part, index in enumerate(parts):
                c = geometry.components[index]
                for local_y in range(c["v"]):
                    for local_x in range(c["h"]):
                        unit.append((part, index, unit_x * c["h"] + local_x, unit_y * c["v"] + local_y))
            units.append(unit)
    return units


# ---------- Transforms, colours and shrinking: the page's rules ----------

def block_samples(n, block, quant):
    """A block (64 coefficients, natural order) at n dots a side: n rows of n samples."""
    f = [block[i] * quant[i] for i in range(64)]
    if n == 1:
        return [[clamp(((f[0] + 4) >> 3) + 128)]]
    step = 8 // n
    t = [[(sum(K[u * step][x] * f[v * 8 + u] for u in range(n)) + 1024) >> 11 for x in range(n)] for v in range(n)]
    return [[clamp(((sum(K[v * step][y] * t[v][x] for v in range(n)) + 16384) >> 15) + 128) for x in range(n)]
            for y in range(n)]


def rgb_of_ycc(y, cb, cr):
    cb, cr = cb - 128, cr - 128
    return (clamp(y + ((91881 * cr + 32768) >> 16)), clamp(y + ((-22554 * cb - 46802 * cr + 32768) >> 16)),
            clamp(y + ((116130 * cb + 32768) >> 16)))


def colour_of(ids, jfif, adobe):
    """Grey for one component. Three: YCbCr when JFIF's note came; else as Adobe's note says (transform 0: red,
    green and blue as they are; any other: YCbCr); else red, green and blue when they are named R, G and B; else
    YCbCr."""
    if len(ids) == 1:
        return "grey"
    if jfif:
        return "ycc"
    if adobe is not None:
        return "rgb" if adobe == 0 else "ycc"
    return "rgb" if list(ids) == [82, 71, 66] else "ycc"


def read_size(width, height, room_width, room_height):
    """The size shown at (as the crate's fitted_size), the n read at, and the size read at: a photo shown at its
    whole size is read whole; any other at the smallest n that is still large enough."""
    if width <= room_width and height <= room_height:
        shown = (width, height)
    elif width * room_height >= height * room_width:
        shown = (room_width, min(max(1, (height * room_width + width // 2) // width), room_height))
    else:
        shown = (min(max(1, (width * room_height + height // 2) // height), room_width), room_height)
    for n in (1, 2, 4, 8):
        if shown == (width, height) and n < 8:
            continue
        read = (ceil_div(width * n, 8), ceil_div(height * n, 8))
        if read[0] >= shown[0] and read[1] >= shown[1]:
            return shown, n, read
    raise AssertionError("n = 8 always fits")


def render(geometry, blocks, quants, colour, n):
    """The dots at n dots a block side: each component's blocks turned into samples, and each dot (x, y) taking
    component i's sample at (x x h / Hmax, y x v / Vmax). Four bytes a dot, alpha 255."""
    planes = []
    for c, quant, component_blocks in zip(geometry.components, quants, blocks):
        plane = [[0] * (c["across"] * n) for _ in range(c["down"] * n)]
        for by, row in enumerate(component_blocks):
            for bx, block in enumerate(row):
                for y, samples in enumerate(block_samples(n, block, quant)):
                    plane[by * n + y][bx * n:bx * n + n] = samples
        planes.append((plane, geometry.h_most // c["h"], geometry.v_most // c["v"]))
    width, height = ceil_div(geometry.width * n, 8), ceil_div(geometry.height * n, 8)
    out = bytearray()
    for y in range(height):
        for x in range(width):
            samples = [plane[y // down][x // across] for plane, across, down in planes]
            if colour == "grey":
                rgb = (samples[0],) * 3
            elif colour == "rgb":
                rgb = tuple(samples)
            else:
                rgb = rgb_of_ycc(*samples)
            out += bytes(rgb) + b"\xff"
    return width, height, bytes(out)


def shrink_to(width, height, rgba, to_width, to_height):
    """The crate's shrinking (shrink.rs) to a size no larger: dot (x, y) falls on (x * to_width // width,
    y * to_height // height); each shown dot is the average of those that fall on it, the colours weighed by
    their alpha, both rounded to the nearest."""
    if (width, height) == (to_width, to_height):
        return rgba
    sums = [[[0, 0, 0, 0, 0] for _ in range(to_width)] for _ in range(to_height)]
    for y in range(height):
        row = sums[y * to_height // height]
        for x in range(width):
            r, g, b, a = rgba[(y * width + x) * 4:(y * width + x) * 4 + 4]
            s = row[x * to_width // width]
            s[0] += a
            s[1] += r * a
            s[2] += g * a
            s[3] += b * a
            s[4] += 1
    out = bytearray()
    for row in sums:
        for a, r, g, b, count in row:
            if count == 0:
                out += bytes(4)
                continue
            out += bytes([0 if a == 0 else (c + a // 2) // a for c in (r, g, b)] + [(a + count // 2) // count])
    return bytes(out)


def shown_dots(geometry, blocks, quants, colour, room_width, room_height):
    """What the crate shows in a room: read at the smallest n that is still large enough, then shrunk."""
    shown, n, _ = read_size(geometry.width, geometry.height, room_width, room_height)
    width, height, dots = render(geometry, blocks, quants, colour, n)
    return shown[0], shown[1], shrink_to(width, height, dots, shown[0], shown[1])


# ---------- Making blocks ----------

def fdct(samples):
    """The forward transform of 8 by 8 samples, level-shifted (T.81, A.3.3), in floating point: 64 numbers in
    natural order."""
    out = []
    for v in range(8):
        for u in range(8):
            cu = math.sqrt(0.5) if u == 0 else 1.0
            cv = math.sqrt(0.5) if v == 0 else 1.0
            total = 0.0
            for y in range(8):
                for x in range(8):
                    total += (samples[y][x] - 128) * math.cos((2 * x + 1) * u * math.pi / 16) * \
                        math.cos((2 * y + 1) * v * math.pi / 16)
            out.append(0.25 * cu * cv * total)
    return out


def blocks_of_plane(plane, across, down, quant):
    """A plane of samples (at least across x 8 by down x 8) as quantized blocks (A.3.4)."""
    blocks = []
    for by in range(down):
        row = []
        for bx in range(across):
            samples = [plane[by * 8 + y][bx * 8:bx * 8 + 8] for y in range(8)]
            row.append([int(round(f / q)) for f, q in zip(fdct(samples), quant)])
        blocks.append(row)
    return blocks


# ---------- Huffman tables ----------

def optimal_table(counts):
    """A table for the symbols counted (T.81, K.2): Huffman's code lengths, with a pseudo-symbol that takes the
    code of all 1-bits, then lengths over 16 made shorter, as K.2's Figure K.3 says. Its 16 counts and values."""
    freq = dict(counts)
    freq[256] = 1
    size = {s: 0 for s in freq}
    others = {s: None for s in freq}
    while True:
        living = [s for s in freq if freq[s] > 0]
        if len(living) < 2:
            break
        c1 = max(living, key=lambda s: (-freq[s], s))
        c2 = max((s for s in living if s != c1), key=lambda s: (-freq[s], s))
        freq[c1] += freq[c2]
        freq[c2] = 0
        size[c1] += 1
        while others[c1] is not None:
            c1 = others[c1]
            size[c1] += 1
        others[c1] = c2
        size[c2] += 1
        while others[c2] is not None:
            c2 = others[c2]
            size[c2] += 1
    bits = [0] * 33
    for s, length in size.items():
        if length:
            bits[length] += 1
    for i in range(32, 16, -1):
        while bits[i] > 0:
            j = i - 2
            while bits[j] == 0:
                j -= 1
            bits[i] -= 2
            bits[i - 1] += 1
            bits[j + 1] += 2
            bits[j] -= 1
    i = 16
    while bits[i] == 0:
        i -= 1
    bits[i] -= 1
    values = [s for length in range(1, 33) for s in sorted(counts) if size.get(s) == length]
    return bits[1:17], values


def long_table(counts):
    """A table whose codes are mostly 16 bits long, so that the long codes are read: the symbols in order of
    their counts get one code each of 2 to 15 bits, the rest 16 bits."""
    symbols = sorted(counts, key=lambda s: (-counts[s], s))
    bits = [0] * 16
    for i, _ in enumerate(symbols):
        bits[min(i + 1, 15)] += 1
    return bits, symbols


def codes_of(bits, values):
    """Each value's code and length, as Annex C makes them."""
    codes, code, at = {}, 0, 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            codes[values[at]] = (code, length)
            code += 1
            at += 1
        assert code < (1 << length), "a code of all 1-bits"
        code <<= 1
    return codes


# ---------- Writing ----------

class Coder:
    """Codes a scan's data: with no codes it only counts the symbols, for making the tables; with them it writes
    the bits, highest first, an FF byte followed by 00 (F.1.2.3)."""

    def __init__(self, codes=None):
        self.codes = codes
        self.counts = {}
        self.out = bytearray()
        self.held = 0
        self.count = 0

    def symbol(self, key, value):
        self.counts.setdefault(key, Counter())[value] += 1
        if self.codes is not None:
            self.bits(*self.codes[key][value])

    def bits(self, value, n):
        if n == 0:
            return
        self.held = (self.held << n) | (value & ((1 << n) - 1))
        self.count += n
        while self.count >= 8:
            self.count -= 8
            byte = (self.held >> self.count) & 0xFF
            self.out.append(byte)
            if byte == 0xFF:
                self.out.append(0)
        self.held &= (1 << self.count) - 1

    def pad(self):
        """The last byte filled with 1-bits."""
        if self.count:
            self.bits((1 << (8 - self.count)) - 1, 8 - self.count)


class ScanCoder:
    """The coding of one scan's blocks (Annex F; G.1.2): the DC predictions, and the run of empty blocks (EOBRUN)
    with the correction bits that wait for it."""

    def __init__(self, coder, ac_key=None):
        self.coder = coder
        self.ac_key = ac_key
        self.predictions = [0] * 4
        self.eob_run = 0
        self.waiting = []

    def end_run(self):
        """Sends the run of empty blocks, if any: EOBn, its n low bits, then the correction bits that wait."""
        if self.eob_run:
            n = self.eob_run.bit_length() - 1
            self.coder.symbol(self.ac_key, n << 4)
            self.coder.bits(self.eob_run, n)
            self.eob_run = 0
            for bit in self.waiting:
                self.coder.bits(bit, 1)
            self.waiting = []

    def number(self, key, value):
        """A DC difference: its size in bits as a code, then its bits; a negative one's are its size's
        complement (F.1.2.1)."""
        size = abs(value).bit_length()
        self.coder.symbol(key, size)
        self.coder.bits(value if value >= 0 else value - 1, size)

    def sequential(self, part, dc_key, ac_key, block):
        self.number(dc_key, block[0] - self.predictions[part])
        self.predictions[part] = block[0]
        run = 0
        for k in range(1, 64):
            value = block[ZIGZAG[k]]
            if value == 0:
                run += 1
                continue
            while run > 15:
                self.coder.symbol(ac_key, 0xF0)
                run -= 16
            size = abs(value).bit_length()
            self.coder.symbol(ac_key, (run << 4) | size)
            self.coder.bits(value if value > 0 else value - 1, size)
            run = 0
        if run:
            self.coder.symbol(ac_key, 0x00)

    def dc_first(self, part, dc_key, block, low):
        value = block[0] >> low
        self.number(dc_key, value - self.predictions[part])
        self.predictions[part] = value

    def dc_refine(self, block, low):
        self.coder.bits((block[0] >> low) & 1, 1)

    def ac_first(self, block, start, end, low):
        run = 0
        for k in range(start, end + 1):
            value = block[ZIGZAG[k]]
            size_of = abs(value) >> low
            if size_of == 0:
                run += 1
                continue
            self.end_run()
            while run > 15:
                self.coder.symbol(self.ac_key, 0xF0)
                run -= 16
            size = size_of.bit_length()
            self.coder.symbol(self.ac_key, (run << 4) | size)
            self.coder.bits(size_of if value > 0 else ~size_of, size)
            run = 0
        if run:
            self.eob_run += 1
            if self.eob_run == 0x7FFF:
                self.end_run()

    def ac_refine(self, block, start, end, low):
        sizes = {k: abs(block[ZIGZAG[k]]) >> low for k in range(start, end + 1)}
        last_new = max([k for k in sizes if sizes[k] == 1], default=0)
        run, own = 0, []
        for k in range(start, end + 1):
            size_of = sizes[k]
            if size_of == 0:
                run += 1
                continue
            while run > 15 and k <= last_new:
                self.end_run()
                self.coder.symbol(self.ac_key, 0xF0)
                run -= 16
                for bit in own:
                    self.coder.bits(bit, 1)
                own = []
            if size_of > 1:
                own.append(size_of & 1)
                continue
            self.end_run()
            self.coder.symbol(self.ac_key, (run << 4) | 1)
            self.coder.bits(0 if block[ZIGZAG[k]] < 0 else 1, 1)
            for bit in own:
                self.coder.bits(bit, 1)
            own, run = [], 0
        if run or own:
            self.eob_run += 1
            self.waiting += own
            if self.eob_run == 0x7FFF:
                self.end_run()


def segment(code, body):
    return bytes([0xFF, code]) + struct.pack(">H", len(body) + 2) + body


def code_scan(geometry, blocks, scan, places, codes):
    """One scan's data, coded with `codes` (or only counted, with None)."""
    coder = Coder(codes)
    parts = scan["parts"]
    start, end = scan.get("band", (0, 63))
    high, low = scan.get("approximation", (0, 0))
    kind = scan["kind"]
    ac_key = ("ac", places[parts[0]][1]) if kind in ("ac-first", "ac-refine") else None
    scan_coder = ScanCoder(coder, ac_key)
    interval = scan.get("restart", 0)
    for number, unit in enumerate(scan_blocks(geometry, parts)):
        if interval and number and number % interval == 0:
            if scan.get("long_run") and scan_coder.eob_run:
                # Damage on purpose: the run sent counts a block more than the interval has.
                scan_coder.eob_run += 1
            scan_coder.end_run()
            coder.pad()
            coder.out += bytes([0xFF, 0xD0 + (number // interval - 1) % 8])
            scan_coder.predictions = [0] * 4
        for part, index, x, y in unit:
            block = blocks[index][y][x]
            dc_key, ac_key = ("dc", places[index][0]), ("ac", places[index][1])
            if kind == "sequential":
                scan_coder.sequential(part, dc_key, ac_key, block)
            elif kind == "dc-first":
                scan_coder.dc_first(part, dc_key, block, low)
            elif kind == "dc-refine":
                scan_coder.dc_refine(block, low)
            elif kind == "ac-first":
                scan_coder.ac_first(block, start, end, low)
            else:
                scan_coder.ac_refine(block, start, end, low)
    scan_coder.end_run()
    coder.pad()
    return coder


def jpeg_write(width, height, components, blocks, quants, scans, frame=0xC0, table_maker=optimal_table,
               before=(), between=(), after_end=b"", fill=0, adobe=None, jfif=True):
    """A JPEG file.

    components: (id, h, v, quantization place, DC place, AC place) for each; blocks: blocks[c][y][x], 64
    coefficients in natural order, as quantized, every kept block; quants: {place: (precision 0 or 1, 64 numbers
    in natural order)}; scans: dicts with "parts" (component indices), "kind" ("sequential", "dc-first",
    "dc-refine", "ac-first", "ac-refine"), and maybe "band" (start, end), "approximation" (Ah, Al) and "restart"
    (the interval, given before the scan with DRI). frame: 0xC0, 0xC1 or 0xC2. before: segments (code, body) put
    before the frame; between: put before every scan after the first; after_end: bytes after the end marker;
    fill: how many fill bytes (FF) go before every marker after the first; adobe: Adobe's colour transform, if
    its note is wanted."""
    geometry = Geometry(width, height, [(h, v) for _, h, v, _, _, _ in components])
    places = [(dc, ac) for _, _, _, _, dc, ac in components]
    marker_fill = b"\xff" * fill
    out = bytearray(b"\xff\xd8")

    def put(code, body):
        out.extend(marker_fill + segment(code, body))

    if jfif:
        put(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00")
    if adobe is not None:
        put(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00" + bytes([adobe]))
    for code, body in before:
        put(code, body)
    for place, (precision, numbers) in sorted(quants.items()):
        natural = [numbers[ZIGZAG[k]] for k in range(64)]
        body = bytes([(precision << 4) | place]) + (bytes(natural) if precision == 0 else
                                                    b"".join(struct.pack(">H", q) for q in natural))
        put(0xDB, body)
    put(frame, struct.pack(">BHHB", 8, height, width, len(components)) +
        b"".join(bytes([ident, (h << 4) | v, tq]) for ident, h, v, tq, _, _ in components))
    interval = None
    for number, scan in enumerate(scans):
        if number:
            for code, body in between:
                put(code, body)
        counted = code_scan(geometry, blocks, scan, places, None)
        tables = {key: table_maker(counts) for key, counts in counted.counts.items()}
        body = b""
        for (kind, place), (bits, values) in sorted(tables.items()):
            body += bytes([(0 if kind == "dc" else 1) << 4 | place]) + bytes(bits) + bytes(values)
        if body:
            put(0xC4, body)
        if scan.get("restart", 0) != interval:
            interval = scan.get("restart", 0)
            put(0xDD, struct.pack(">H", interval))
        coded = code_scan(geometry, blocks, scan, places,
                          {key: codes_of(*table) for key, table in tables.items()})
        start, end = scan.get("band", (0, 63))
        high, low = scan.get("approximation", (0, 0))
        header = bytes([len(scan["parts"])])
        for index in scan["parts"]:
            dc, ac = places[index]
            header += bytes([components[index][0], (dc << 4) | ac])
        header += bytes([start, end, (high << 4) | low])
        put(0xDA, header)
        out.extend(coded.out)
    out.extend(marker_fill + b"\xff\xd9" + after_end)
    return bytes(out)


def sent_blocks(geometry, blocks, scans):
    """The blocks a reader ends with after these scans: each scan sets, in the blocks it holds (a scan of one
    component holds only that component's own blocks, A.2.2), its band of coefficients as far as its point
    transform sends them (the DC's bits below Al dropped, rounding down; an AC's, towards zero). Others stay 0."""
    out = [[[[0] * 64 for _ in row] for row in component_blocks] for component_blocks in blocks]
    for scan in scans:
        start, end = scan.get("band", (0, 63))
        low = scan.get("approximation", (0, 0))[1]
        for unit in scan_blocks(geometry, scan["parts"]):
            for _, index, x, y in unit:
                block, new = blocks[index][y][x], out[index][y][x]
                for k in range(start, end + 1):
                    value = block[ZIGZAG[k]]
                    if k == 0:
                        new[0] = (value >> low) << low
                    else:
                        new[ZIGZAG[k]] = (abs(value) >> low << low) * (1 if value >= 0 else -1)
    return out


# ---------- Reading ----------

class Refused(ValueError):
    """What the second reader does not read, or finds damaged."""


class Bits:
    """A scan's data as bits, highest first: FF 00 stands for FF; any other FF begins a marker, which ends it."""

    def __init__(self, data, at):
        self.data, self.at = data, at
        self.byte, self.left = 0, 0
        self.marker = None

    def next_byte(self):
        if self.marker is not None:
            return None
        if self.at >= len(self.data):
            raise Refused("the file ends before the picture does")
        byte = self.data[self.at]
        if byte != 0xFF:
            self.at += 1
            return byte
        after = self.at + 1
        while after < len(self.data) and self.data[after] == 0xFF:
            after += 1
        if after >= len(self.data):
            raise Refused("the file ends before the picture does")
        if self.data[after] == 0:
            if after != self.at + 1:
                raise Refused("fill bytes that no marker follows")
            self.at = after + 1
            return 0xFF
        self.marker = self.data[after]
        return None

    def bit(self):
        if self.left == 0:
            byte = self.next_byte()
            if byte is None:
                raise Refused("a scan's data ends before its last unit")
            self.byte, self.left = byte, 8
        self.left -= 1
        return (self.byte >> self.left) & 1

    def take(self, n):
        value = 0
        for _ in range(n):
            value = (value << 1) | self.bit()
        return value

    def number(self, size):
        bits = self.take(size)
        return bits - (1 << size) + 1 if size and bits < (1 << (size - 1)) else bits

    def decode(self, table):
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            if (length, code) in table:
                return table[(length, code)]
        raise Refused("a code that its table does not have")

    def finish(self):
        """The data must end here, with a marker: its code."""
        self.left = 0
        if self.next_byte() is not None:
            raise Refused("a scan's data goes on where a marker must come")
        return self.marker

    def restart(self, number):
        if self.finish() != 0xD0 + number:
            raise Refused("a restart marker is missing or out of turn")
        while self.data[self.at] == 0xFF:
            self.at += 1
        self.at += 1
        self.marker = None


def fits(value):
    if not -32768 <= value <= 32767:
        raise Refused("a coefficient is larger than 16 bits hold")
    return value


def read_scan(data, at, geometry, blocks, parts, tables, kind, band, low, interval):
    """Reads one scan's data into the blocks; gives where the marker after it begins."""
    bits = Bits(data, at)
    predictions = [0] * 4
    eob_run = 0
    start, end = band
    for number, unit in enumerate(scan_blocks(geometry, [index for index, _, _ in parts])):
        if interval and number and number % interval == 0:
            if eob_run:
                raise Refused("a run of empty blocks goes past its restart interval")
            bits.restart((number // interval - 1) % 8)
            predictions = [0] * 4
        for part, index, x, y in unit:
            block = blocks[index][y][x]
            dc, ac = tables[part]
            if kind in ("sequential", "dc-first"):
                size = bits.decode(dc)
                if size > 15:
                    raise Refused("a code that means nothing")
                predictions[part] += bits.number(size)
                block[0] = fits(predictions[part] << low)
                if kind == "dc-first":
                    continue
                k = 1
                while k <= 63:
                    code = bits.decode(ac)
                    run, size = code >> 4, code & 15
                    if size == 0:
                        if run == 15:
                            k += 16
                            if k > 64:
                                raise Refused("a run of zeros past the end of its band")
                            continue
                        if run == 0:
                            break
                        raise Refused("a code that means nothing")
                    k += run
                    if k > 63:
                        raise Refused("a run of zeros past the end of its band")
                    block[ZIGZAG[k]] = bits.number(size)
                    k += 1
            elif kind == "dc-refine":
                if bits.bit():
                    block[0] |= 1 << low
            elif kind == "ac-first":
                if eob_run:
                    eob_run -= 1
                    continue
                k = start
                while k <= end:
                    code = bits.decode(ac)
                    run, size = code >> 4, code & 15
                    if size == 0:
                        if run == 15:
                            k += 16
                            if k > end + 1:
                                raise Refused("a run of zeros past the end of its band")
                            continue
                        eob_run = (1 << run) + bits.take(run) - 1
                        break
                    k += run
                    if k > end:
                        raise Refused("a run of zeros past the end of its band")
                    value = bits.number(size) * (1 << low)
                    if abs(value) > 32767:
                        raise Refused("a coefficient is larger than 16 bits hold")
                    block[ZIGZAG[k]] = value
                    k += 1
            else:
                step = 1 << low
                k = start
                if eob_run == 0:
                    while k <= end:
                        code = bits.decode(ac)
                        zeros, size = code >> 4, code & 15
                        value = 0
                        if size == 1:
                            value = step if bits.bit() else -step
                        elif size == 0 and zeros != 15:
                            eob_run = (1 << zeros) + bits.take(zeros)
                            break
                        elif size != 0:
                            raise Refused("a code that means nothing")
                        while True:
                            if k > end:
                                raise Refused("a run of zeros past the end of its band")
                            here = ZIGZAG[k]
                            if block[here] != 0:
                                if bits.bit() and block[here] & step == 0:
                                    block[here] = fits(block[here] + (step if block[here] >= 0 else -step))
                            elif zeros == 0:
                                break
                            else:
                                zeros -= 1
                            k += 1
                        if value:
                            block[ZIGZAG[k]] = value
                        k += 1
                if eob_run:
                    while k <= end:
                        here = ZIGZAG[k]
                        if block[here] != 0 and bits.bit() and block[here] & step == 0:
                            block[here] = fits(block[here] + (step if block[here] >= 0 else -step))
                        k += 1
                    eob_run -= 1
    if eob_run:
        raise Refused("a run of empty blocks goes past its restart interval")
    marker = bits.finish()
    if 0xD0 <= marker <= 0xD7:
        raise Refused("a restart marker is missing or out of turn")
    return bits.at


def jpeg_read(data):
    """Reads a JPEG file: a dict with its geometry, its blocks (every coefficient), each component's quantization
    table (as its first scan found it) and its kind of colour. Raises Refused for what it does not read."""
    if data[:2] != b"\xff\xd8":
        raise Refused("it does not begin as a JPEG photo does")
    at = 2
    quant = {}
    huffman = {}
    interval = 0
    jfif, adobe = False, None
    frame = None
    while True:
        if at >= len(data) or data[at] != 0xFF:
            raise Refused("something stands between its segments that is not a marker")
        while at < len(data) and data[at] == 0xFF:
            at += 1
        if at >= len(data):
            raise Refused("the file ends before the picture does")
        code = data[at]
        at += 1
        if code == 0xD9:
            break
        if code == 0x01:
            continue
        if code in (0x00, 0xD8) or 0xD0 <= code <= 0xD7:
            raise Refused("a marker out of place")
        length = struct.unpack(">H", data[at:at + 2])[0]
        body = data[at + 2:at + length]
        if len(body) != length - 2:
            raise Refused("the file ends before the picture does")
        at += length
        if code == 0xDB:
            i = 0
            while i < len(body):
                precision, place = body[i] >> 4, body[i] & 15
                if precision > 1:
                    raise Refused("a quantization table has a precision that does not exist")
                size = 1 if precision == 0 else 2
                numbers = body[i + 1:i + 1 + 64 * size]
                if len(numbers) != 64 * size:
                    raise Refused("a segment's length does not fit what it holds")
                values = list(numbers) if size == 1 else [struct.unpack(">H", numbers[2 * k:2 * k + 2])[0]
                                                         for k in range(64)]
                if precision > 1 or place > 3 or len(values) != 64 or 0 in values:
                    raise Refused("a quantization table that cannot be")
                natural = [0] * 64
                for k, value in enumerate(values):
                    natural[ZIGZAG[k]] = value
                quant[place] = natural
                i += 1 + 64 * size
        elif code == 0xC4:
            i = 0
            while i < len(body):
                kind, place = body[i] >> 4, body[i] & 15
                bits = list(body[i + 1:i + 17])
                values = list(body[i + 17:i + 17 + sum(bits)])
                if kind > 1 or place > 3 or len(values) != sum(bits) or sum(bits) > 256:
                    raise Refused("a table of codes that cannot be")
                try:
                    codes = codes_of(bits, values)
                except AssertionError:
                    raise Refused("a table of codes has more codes than can be")
                huffman[(kind, place)] = {(length, code): value for value, (code, length) in codes.items()}
                i += 17 + sum(bits)
        elif code == 0xDD:
            if len(body) != 2:
                raise Refused("a segment's length does not fit what it holds")
            interval = struct.unpack(">H", body)[0]
        elif code == 0xEE and body.startswith(b"Adobe") and len(body) >= 12:
            if frame is None or not frame["scanned"]:
                adobe = body[11]
        elif code == 0xE0 and body.startswith(b"JFIF\x00"):
            if frame is None or not frame["scanned"]:
                jfif = True
        elif code in (0xC0, 0xC1, 0xC2):
            if frame is not None:
                raise Refused("it has two frames")
            precision, height, width, count = struct.unpack(">BHHB", body[:6])
            if precision != 8 or height == 0 or width == 0 or count not in (1, 3) or len(body) != 6 + 3 * count:
                raise Refused("a frame I do not read")
            ids = [body[6 + 3 * i] for i in range(count)]
            factors = [(body[7 + 3 * i] >> 4, body[7 + 3 * i] & 15) for i in range(count)]
            tables = [body[8 + 3 * i] for i in range(count)]
            if len(set(ids)) != count or any(not (1 <= h <= 4 and 1 <= v <= 4) for h, v in factors):
                raise Refused("a frame that cannot be")
            h_most, v_most = max(h for h, _ in factors), max(v for _, v in factors)
            if count > 1 and any(h_most % h or v_most % v for h, v in factors):
                raise Refused("sampling ratios that are not whole")
            geometry = Geometry(width, height, factors)
            frame = dict(progressive=code == 0xC2, ids=ids, tables=tables, geometry=geometry, scanned=False,
                         blocks=empty_blocks(geometry), quants=[None] * count, sent=[[None] * 64 for _ in ids])
        elif code == 0xDA:
            if frame is None:
                raise Refused("a scan comes before its frame")
            count = body[0]
            if not 1 <= count <= 4:
                raise Refused("a scan names no components, or more than 4")
            if len(body) != 4 + 2 * count:
                raise Refused("a segment's length does not fit what it holds")
            parts = []
            for i in range(count):
                ident, places = body[1 + 2 * i], body[2 + 2 * i]
                if ident not in frame["ids"]:
                    raise Refused("a scan names a component its frame does not have")
                index = frame["ids"].index(ident)
                if parts and parts[-1][0] >= index:
                    raise Refused("a scan names its components out of the frame's order")
                parts.append((index, places >> 4, places & 15))
            start, end, approximation = body[1 + 2 * count:4 + 2 * count]
            high, low = approximation >> 4, approximation & 15
            geometry = frame["geometry"]
            if count > 1 and sum(geometry.components[i]["h"] * geometry.components[i]["v"] for i, _, _ in parts) > 10:
                raise Refused("a scan's units have more than 10 blocks")
            if not frame["progressive"]:
                kind, band, low = "sequential", (0, 63), 0
                for index, _, _ in parts:
                    if frame["sent"][index][0] is not None:
                        raise Refused("a component comes in two scans")
                    frame["sent"][index] = [0] * 64
            else:
                dc = start == 0
                if (dc and end != 0) or (not dc and not (start <= end <= 63 and count == 1)) or high > 13 or \
                        low > 13 or (high and low != high - 1):
                    raise Refused("a scan's band is not as a progressive scan's must be")
                kind = ("dc-first" if not high else "dc-refine") if dc else ("ac-first" if not high else "ac-refine")
                band = (start, end)
                for index, _, _ in parts:
                    sent = frame["sent"][index]
                    if not dc and sent[0] is None:
                        raise Refused("an AC scan before the DC scan")
                    for k in range(start, end + 1):
                        if sent[k] != (high if high else None):
                            raise Refused("scans that do not build up the coefficients in order")
                        sent[k] = low
            tables = []
            for index, dc_place, ac_place in parts:
                dc_table = huffman.get((0, dc_place)) if kind in ("sequential", "dc-first") else None
                ac_table = huffman.get((1, ac_place)) if kind in ("sequential", "ac-first", "ac-refine") else None
                if (kind in ("sequential", "dc-first") and dc_table is None) or \
                        (kind in ("sequential", "ac-first", "ac-refine") and ac_table is None):
                    raise Refused("a scan uses a table that has not been given")
                tables.append((dc_table, ac_table))
                if frame["quants"][index] is None:
                    if frame["tables"][index] not in quant:
                        raise Refused("a scan uses a table that has not been given")
                    frame["quants"][index] = quant[frame["tables"][index]]
            if not frame["scanned"]:
                frame["colour"] = colour_of(frame["ids"], jfif, adobe)
                frame["scanned"] = True
            at = read_scan(data, at, geometry, frame["blocks"], parts, tables, kind, band, low, interval)
        elif 0xE0 <= code <= 0xEF or code in (0xFE, 0xCC):
            pass
        else:
            raise Refused("a marker I do not read: %02X" % code)
    if frame is None or any(sent[0] is None for sent in frame["sent"]):
        raise Refused("it ends before all its components have come")
    return frame


def jpeg_dots(data, room_width, room_height):
    """What the crate shows of a JPEG file in a room: (width, height, dots)."""
    frame = jpeg_read(data)
    return shown_dots(frame["geometry"], frame["blocks"], frame["quants"], frame["colour"], room_width, room_height)
