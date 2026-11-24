"""PNG pictures for the tests of the pictures crate (pictures/), written and read here with Python's own library.

- `png_write` makes a PNG file from samples: any kind of colour and depth, filters chosen per row, Adam7 or not,
  packed by Python's zlib with any level, window and strategy, the packed dots cut into IDAT parts anywhere.
- `png_read` is a second reader, written apart from the crate's: Python's zlib unpacks, and the rest is done here.
  It reads the test pictures again, and pictures made by other programs, so that the crate's reader can be
  compared with something it does not share code with.
- `fitted_size` and `shrink` are the crate's rule for showing a picture in a room, worked out the same way.

Every rule follows RFC 2083 (PNG 1.0), as docs/pictures.md says. Nothing here reads a file but those it is given."""
import struct
import zlib

SIGNATURE = bytes([137, 80, 78, 71, 13, 10, 26, 10])

# Where each Adam7 pass begins and how far it steps, across and down (RFC 2083, 2.6).
ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def part(name, data):
    """One part (chunk): length, name, data, CRC-32 of name and data."""
    name = name.encode("ascii") if isinstance(name, str) else name
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def pass_size(size, start, step):
    return 0 if size <= start else (size - start + step - 1) // step


def row_bytes(width, colour, depth):
    return (width * CHANNELS[colour] * depth + 7) // 8


def pack_row(samples, depth):
    """A row's samples as bytes: 16-bit ones highest byte first, smaller ones packed leftmost in the high bits."""
    if depth == 16:
        return b"".join(struct.pack(">H", s) for s in samples)
    if depth == 8:
        return bytes(samples)
    out = bytearray()
    per_byte = 8 // depth
    for start in range(0, len(samples), per_byte):
        byte = 0
        group = samples[start:start + per_byte]
        for i, s in enumerate(group):
            byte |= s << (8 - depth * (i + 1))
        out.append(byte)
    return bytes(out)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def filter_row(kind, raw, prior, step):
    """Stores each byte as its difference from the filter's guess (RFC 2083, 6)."""
    out = bytearray()
    for i, x in enumerate(raw):
        a = raw[i - step] if i >= step else 0
        b = prior[i]
        c = prior[i - step] if i >= step else 0
        guess = [0, a, b, (a + b) // 2, paeth(a, b, c)][kind]
        out.append((x - guess) & 0xFF)
    return bytes([kind]) + bytes(out)


def unfilter_row(kind, row, prior, step):
    out = bytearray(len(row))
    for i, x in enumerate(row):
        a = out[i - step] if i >= step else 0
        b = prior[i]
        c = prior[i - step] if i >= step else 0
        if kind > 4:
            raise ValueError("no such filter %d" % kind)
        guess = [0, a, b, (a + b) // 2, paeth(a, b, c)][kind]
        out[i] = (x + guess) & 0xFF
    return bytes(out)


def raw_dots(samples, width, height, colour, depth, interlaced, filters):
    """The bytes that go to zlib: every row of every pass, each with its filter byte. `samples[y][x]` is a list of
    the dot's samples; `filters(n)` gives the filter of the n-th row written."""
    channels = CHANNELS[colour]
    step = max(1, channels * depth // 8)
    passes = ADAM7 if interlaced else [(0, 0, 1, 1)]
    out = bytearray()
    n = 0
    for x0, y0, dx, dy in passes:
        pw, ph = pass_size(width, x0, dx), pass_size(height, y0, dy)
        if pw == 0 or ph == 0:
            continue
        prior = bytes(row_bytes(pw, colour, depth))
        for j in range(ph):
            y = y0 + j * dy
            flat = []
            for i in range(pw):
                flat.extend(samples[y][x0 + i * dx])
            raw = pack_row(flat, depth)
            out += filter_row(filters(n), raw, prior, step)
            prior = raw
            n += 1
    return bytes(out)


def png_write(samples, width, height, colour, depth, interlaced=False, filters=lambda n: n % 5, palette=None,
              transparency=None, level=9, wbits=15, strategy=zlib.Z_DEFAULT_STRATEGY, cut=None, before_dots=(),
              after_dots=(), after_end=b""):
    """A whole PNG file. `cut(packed)` splits the packed dots into the data of the IDAT parts (one part when None).
    `before_dots` and `after_dots` are extra parts (name, data) put before the first IDAT and after the last."""
    raw = raw_dots(samples, width, height, colour, depth, interlaced, filters)
    packer = zlib.compressobj(level, zlib.DEFLATED, wbits, 9, strategy)
    packed = packer.compress(raw) + packer.flush()
    head = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 1 if interlaced else 0)
    out = SIGNATURE + part("IHDR", head)
    for name, data in before_dots:
        out += part(name, data)
    if palette is not None:
        out += part("PLTE", b"".join(bytes(c) for c in palette))
    if transparency is not None:
        out += part("tRNS", transparency)
    for piece in (cut(packed) if cut else [packed]):
        out += part("IDAT", piece)
    for name, data in after_dots:
        out += part(name, data)
    out += part("IEND", b"") + after_end
    return out, raw


def eight(value, depth):
    """A sample stretched or cut to 8 bits, as the crate does (RFC 2083, 10.4)."""
    if depth == 16:
        return value >> 8
    if depth == 8:
        return value
    return value * 255 // ((1 << depth) - 1)


def dot_rgba(dot, colour, depth, palette, alphas, key):
    if colour == 0:
        g = eight(dot[0], depth)
        return [g, g, g, 0 if key is not None and key == (dot[0],) * 3 else 255]
    if colour == 2:
        return [eight(s, depth) for s in dot] + [0 if key is not None and key == tuple(dot) else 255]
    if colour == 3:
        r, g, b = palette[dot[0]]
        return [r, g, b, alphas[dot[0]] if dot[0] < len(alphas) else 255]
    if colour == 4:
        g = eight(dot[0], depth)
        return [g, g, g, eight(dot[1], depth)]
    return [eight(s, depth) for s in dot]


def expected_rgba(samples, width, height, colour, depth, palette=None, alphas=b"", key=None):
    """Four bytes a dot, worked out from the samples themselves, not from a file."""
    out = bytearray()
    for y in range(height):
        for x in range(width):
            out += bytes(dot_rgba(samples[y][x], colour, depth, palette, alphas, key))
    return bytes(out)


def png_read(data):
    """The second reader: a PNG file to (width, height, four bytes a dot). Raises ValueError for anything it does
    not take."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    at = 8
    head = None
    palette = None
    trns = None
    packed = bytearray()
    while True:
        if at + 8 > len(data):
            raise ValueError("cut short")
        length, name = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + length]
        if len(body) != length or at + 12 + length > len(data):
            raise ValueError("cut short")
        crc = struct.unpack(">I", data[at + 8 + length:at + 12 + length])[0]
        if zlib.crc32(name + body) & 0xFFFFFFFF != crc:
            raise ValueError("bad check value")
        at += 12 + length
        if name == b"IHDR":
            head = struct.unpack(">IIBBBBB", body)
        elif name == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif name == b"tRNS":
            trns = body
        elif name == b"IDAT":
            packed += body
        elif name == b"IEND":
            break
        elif name[0] < 97:
            raise ValueError("unknown critical part %r" % name)
    width, height, depth, colour, _, _, interlace = head
    raw = zlib.decompress(bytes(packed))
    channels = CHANNELS[colour]
    step = max(1, channels * depth // 8)
    alphas, key = b"", None
    if trns is not None:
        if colour == 3:
            alphas = trns
        elif colour == 0:
            g = struct.unpack(">H", trns[:2])[0]
            key = (g, g, g)
        elif colour == 2:
            key = struct.unpack(">HHH", trns[:6])
    picture = [[None] * width for _ in range(height)]
    passes = ADAM7 if interlace else [(0, 0, 1, 1)]
    pos = 0
    for x0, y0, dx, dy in passes:
        pw, ph = pass_size(width, x0, dx), pass_size(height, y0, dy)
        if pw == 0 or ph == 0:
            continue
        rb = row_bytes(pw, colour, depth)
        prior = bytes(rb)
        for j in range(ph):
            kind = raw[pos]
            row = unfilter_row(kind, raw[pos + 1:pos + 1 + rb], prior, step)
            pos += 1 + rb
            prior = row
            for i in range(pw):
                dot = []
                for c in range(channels):
                    index = i * channels + c
                    if depth == 16:
                        dot.append(struct.unpack(">H", row[index * 2:index * 2 + 2])[0])
                    elif depth == 8:
                        dot.append(row[index])
                    else:
                        bit = index * depth
                        dot.append((row[bit // 8] >> (8 - depth - bit % 8)) & ((1 << depth) - 1))
                if colour == 3 and dot[0] >= len(palette):
                    raise ValueError("palette index out of range")
                picture[y0 + j * dy][x0 + i * dx] = dot_rgba(dot, colour, depth, palette, alphas, key)
    if pos != len(raw):
        raise ValueError("more or fewer dots than the size")
    return width, height, bytes(b for row in picture for dot in row for b in dot)


def fitted_size(width, height, room_width, room_height):
    """The crate's rule: as it is if it fits; else as large as fits, keeping its shape, the other side rounded."""
    if width <= room_width and height <= room_height:
        return width, height
    if width * room_height >= height * room_width:
        return room_width, min(max(1, (height * room_width + width // 2) // width), room_height)
    return min(max(1, (width * room_height + height // 2) // height), room_width), room_height


def shrink(width, height, rgba, room_width, room_height):
    """The crate's shrinking: each shown dot is the average of the dots that fall on it (column x falls on
    x * shown_width // width), the colours weighed by their alpha; both rounded to the nearest."""
    sw, sh = fitted_size(width, height, room_width, room_height)
    sums = [[[0, 0, 0, 0, 0] for _ in range(sw)] for _ in range(sh)]
    for y in range(height):
        for x in range(width):
            r, g, b, a = rgba[(y * width + x) * 4:(y * width + x) * 4 + 4]
            s = sums[y * sh // height][x * sw // width]
            s[0] += a
            s[1] += r * a
            s[2] += g * a
            s[3] += b * a
            s[4] += 1
    out = bytearray()
    for row in sums:
        for a, r, g, b, n in row:
            if n == 0:
                out += bytes(4)
                continue
            colour = [0 if a == 0 else (c + a // 2) // a for c in (r, g, b)]
            out += bytes(colour + [(a + n // 2) // n])
    return sw, sh, bytes(out)
