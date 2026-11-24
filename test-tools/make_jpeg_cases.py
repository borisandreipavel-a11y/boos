"""Makes the test photos of the pictures crate's JPEG reader, kept in pictures/test-data/ as two files that the crate's
tests read (pictures/src/jpeg_tests.rs): jpeg-cases.bin, every test file one after another, and jpeg-cases.txt, the
list of the cases and where each file lies in jpeg-cases.bin.

    python make_jpeg_cases.py

The photos are written by jpeg_reference.py from blocks of coefficients made here, and their dots are worked out
from those blocks by the rules docs/pictures.md writes down ("JPEG"). Each photo is also read back with the second
reader (jpeg_reference.jpeg_read), which must find the same blocks and give the same dots, so that a mistake here
shows here; each photo that must be turned down must be turned down by it too. The samples come from a fixed
sequence of numbers, so every run makes the same files.

Lines of jpeg-cases.txt:
    jpeg NAME WIDTH HEIGHT COMPONENTS PROGRESSIVE      NAME.jpg, and NAME.rgba: its dots at its whole size
    jshrunk NAME ROOM_W ROOM_H SHOWN_W SHOWN_H          NAME-ROOM_WxROOM_H.rgba: NAME.jpg shown in that room
    jrefused NAME REASON...                             NAME.jpg is turned down, because REASON
    file NAME AT LENGTH                                 the file NAME is the LENGTH bytes of jpeg-cases.bin from AT on
"""
import os
import struct

import jpeg_reference as jpeg
from make_picture_cases import Numbers

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "pictures", "test-data")

# T.81's example tables (K.1), in natural order.
LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22,
        29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103,
        121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
CHROMA = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99,
          99, 99, 99, 99, 99] + [99] * 32

SEQUENTIAL = [dict(parts=[0, 1, 2], kind="sequential")]
# A progression as common encoders send it: the DC coefficients first, less one bit; the first AC coefficients of
# the brightness; the colours' AC whole but for a bit; the rest of the brightness's, less two bits; then the bits
# that were left out, one at a time.
PROGRESSIVE = [dict(parts=[0, 1, 2], kind="dc-first", band=(0, 0), approximation=(0, 1)),
               dict(parts=[0], kind="ac-first", band=(1, 5), approximation=(0, 2)),
               dict(parts=[2], kind="ac-first", band=(1, 63), approximation=(0, 1)),
               dict(parts=[1], kind="ac-first", band=(1, 63), approximation=(0, 1)),
               dict(parts=[0], kind="ac-first", band=(6, 63), approximation=(0, 2)),
               dict(parts=[0], kind="ac-refine", band=(1, 63), approximation=(2, 1)),
               dict(parts=[0, 1, 2], kind="dc-refine", band=(0, 0), approximation=(1, 0)),
               dict(parts=[2], kind="ac-refine", band=(1, 63), approximation=(1, 0)),
               dict(parts=[1], kind="ac-refine", band=(1, 63), approximation=(1, 0)),
               dict(parts=[0], kind="ac-refine", band=(1, 63), approximation=(1, 0))]
GREY_PROGRESSIVE = [dict(parts=[0], kind="dc-first", band=(0, 0), approximation=(0, 1)),
                    dict(parts=[0], kind="ac-first", band=(1, 5), approximation=(0, 2)),
                    dict(parts=[0], kind="ac-first", band=(6, 63), approximation=(0, 2)),
                    dict(parts=[0], kind="ac-refine", band=(1, 63), approximation=(2, 1)),
                    dict(parts=[0], kind="dc-refine", band=(0, 0), approximation=(1, 0)),
                    dict(parts=[0], kind="ac-refine", band=(1, 63), approximation=(1, 0))]


def with_restart(scans, interval):
    return [dict(scan, restart=interval) for scan in scans]


def plane(width, height, c, numbers):
    """A component's samples: a slope, a disc whose edge is sharp, and noise."""
    out = []
    for y in range(height):
        row = []
        for x in range(width):
            value = (x * 3 + y * 2 + c * 50) % 256
            if (x - width / 2) ** 2 + (y - height / 3) ** 2 < (min(width, height) / 3) ** 2:
                value = 255 - value
            row.append(max(0, min(255, value + numbers.below(21) - 10)))
        out.append(row)
    return out


def markers_of(data):
    """Each marker of a file: (where its first FF is, its code, where what goes with it ends: its segment and, for a
    scan, its data)."""
    out, at = [(0, 0xD8, 2)], 2
    while at < len(data):
        start = at
        while data[at + 1] == 0xFF:
            at += 1
        code = data[at + 1]
        at += 2
        if code == 0xD9:
            out.append((start, code, at))
            break
        if code == 0x01 or 0xD0 <= code <= 0xD7:
            out.append((start, code, at))
            continue
        at += struct.unpack(">H", data[at:at + 2])[0]
        if code == 0xDA:
            while not (data[at] == 0xFF and data[at + 1] != 0 and not 0xD0 <= data[at + 1] <= 0xD7):
                at += 1
        out.append((start, code, at))
    return out


def find(data, code, nth=0):
    """Where the nth marker of this code begins and where what goes with it ends."""
    found = [(start, end) for start, c, end in markers_of(data) if c == code]
    return found[nth]


def main():
    os.makedirs(OUT, exist_ok=True)
    numbers = Numbers(20261125)
    lines, files = [], []

    def write(name, data):
        files.append((name, data))

    def blocks_for(width, height, factors, quants_of, extreme=False):
        geometry = jpeg.Geometry(width, height, factors)
        blocks = []
        for c, component in enumerate(geometry.components):
            if extreme:
                # Coefficients as large as 16 bits hold, so that the sums of the transforms are as large as
                # they can be; the DC values differ by less than 2^15 from block to block.
                blocks.append([[[(16383 if (x + y) % 2 else -16383) if i == 0 else
                                 (32767 if numbers.below(2) else -32767) * (numbers.below(3) == 0)
                                 for i in range(64)] for x in range(component["across"])]
                               for y in range(component["down"])])
                continue
            samples = plane(component["across"] * 8, component["down"] * 8, c, numbers)
            blocks.append(jpeg.blocks_of_plane(samples, component["across"], component["down"], quants_of[c]))
        return geometry, blocks

    def made(name, width, height, factors, scans, frame=0xC0, quant16=False, ids=None, places=None,
             extreme=False, shown_in=(), **options):
        """A photo written from blocks; its dots at its whole size and in each room, checked by the second
        reader."""
        count = len(factors)
        quants_of = [LUMA if c == 0 else CHROMA for c in range(count)]
        if extreme:
            quants_of = [[65535] * 64 for _ in range(count)]
        geometry, blocks = blocks_for(width, height, factors, quants_of, extreme)
        ids = ids or [c + 1 for c in range(count)]
        places = places or [min(c, 1) for c in range(count)]
        components = [(ids[c], h, v, min(c, 1), places[c], places[c]) for c, (h, v) in enumerate(factors)]
        quants = {0: (1 if quant16 or extreme else 0, quants_of[0])}
        if count > 1:
            quants[1] = (1 if extreme else 0, quants_of[1])
        data = jpeg.jpeg_write(width, height, components, blocks, quants, scans, frame=frame, **options)
        meant = jpeg.sent_blocks(geometry, blocks, scans)
        read = jpeg.jpeg_read(data)
        assert read["blocks"] == meant, name
        colour = read["colour"]
        write(name + ".jpg", data)
        _, _, dots = jpeg.shown_dots(geometry, meant, quants_of, colour, width, height)
        assert jpeg.jpeg_dots(data, width, height) == (width, height, dots), name
        write(name + ".rgba", dots)
        lines.append("jpeg %s %d %d %d %d" % (name, width, height, count, frame == 0xC2))
        for room_width, room_height in shown_in:
            shown_width, shown_height, dots = jpeg.shown_dots(geometry, meant, quants_of, colour, room_width,
                                                              room_height)
            assert jpeg.jpeg_dots(data, room_width, room_height) == (shown_width, shown_height, dots), name
            write("%s-%dx%d.rgba" % (name, room_width, room_height), dots)
            lines.append("jshrunk %s %d %d %d %d" % (name, room_width, room_height, shown_width, shown_height))
        return data

    # ---------- Photos that are read ----------
    made("seq444", 61, 37, [(1, 1)] * 3, SEQUENTIAL, shown_in=[(20, 20), (7, 5), (61, 10)])
    made("seq420", 77, 45, [(2, 2), (1, 1), (1, 1)], with_restart(SEQUENTIAL, 3), fill=2,
         shown_in=[(40, 40), (10, 10), (77, 12), (1, 1)])
    made("seq422", 50, 33, [(2, 1), (1, 1), (1, 1)], SEQUENTIAL, shown_in=[(13, 9)])
    made("seq440", 33, 50, [(1, 2), (1, 1), (1, 1)], SEQUENTIAL, shown_in=[(9, 13)])
    made("seq411", 90, 21, [(4, 1), (1, 1), (1, 1)], SEQUENTIAL, shown_in=[(23, 6)])
    made("seq311", 70, 20, [(3, 1), (1, 1), (1, 1)], with_restart(SEQUENTIAL, 1))
    made("mixed", 45, 45, [(2, 2), (2, 1), (1, 2)], SEQUENTIAL, shown_in=[(12, 12)])
    made("odd121", 64, 64, [(1, 2), (1, 1), (2, 1)], SEQUENTIAL, table_maker=jpeg.long_table, shown_in=[(32, 32)])
    made("grey", 50, 30, [(1, 1)], [dict(parts=[0], kind="sequential", restart=5)], shown_in=[(13, 13)])
    made("grey22", 50, 30, [(2, 2)], [dict(parts=[0], kind="sequential")])
    made("greyprog", 50, 30, [(1, 1)], with_restart(GREY_PROGRESSIVE, 7), frame=0xC2, shown_in=[(25, 15)])
    made("multiscan", 70, 40, [(2, 1), (1, 1), (1, 1)],
         [dict(parts=[0], kind="sequential"), dict(parts=[1, 2], kind="sequential")], frame=0xC1, quant16=True,
         between=[(0xFE, b"between the scans")], shown_in=[(35, 20)])
    made("multi3", 70, 40, [(1, 1)] * 3, [dict(parts=[2], kind="sequential"), dict(parts=[0], kind="sequential"),
                                         dict(parts=[1], kind="sequential")], places=[0, 1, 2])
    made("tables23", 40, 24, [(1, 1)] * 3, SEQUENTIAL, frame=0xC1, places=[2, 3, 3])
    made("prog420", 77, 45, [(2, 2), (1, 1), (1, 1)], PROGRESSIVE, frame=0xC2,
         shown_in=[(30, 30), (19, 11), (5, 5)])
    made("prog420r", 77, 45, [(2, 2), (1, 1), (1, 1)], with_restart(PROGRESSIVE, 2), frame=0xC2)
    made("prog411r", 90, 21, [(4, 1), (1, 1), (1, 1)], with_restart(PROGRESSIVE, 1), frame=0xC2,
         shown_in=[(45, 11)])
    made("proglong", 64, 64, [(2, 2), (1, 1), (1, 1)], PROGRESSIVE, frame=0xC2, table_maker=jpeg.long_table)
    made("progpart", 77, 45, [(2, 2), (1, 1), (1, 1)], PROGRESSIVE[:6], frame=0xC2, quant16=True,
         shown_in=[(39, 23)])
    made("rgbadobe", 40, 24, [(1, 1)] * 3, SEQUENTIAL, adobe=0, jfif=False)
    made("rgbids", 40, 24, [(1, 1)] * 3, SEQUENTIAL, ids=[82, 71, 66], jfif=False)
    made("jfifwins", 40, 24, [(1, 1)] * 3, SEQUENTIAL, ids=[82, 71, 66], adobe=0)
    made("adobewins", 40, 24, [(1, 1)] * 3, SEQUENTIAL, ids=[82, 71, 66], adobe=1, jfif=False)
    # Other segments: an Exif note with no entries (a TIFF head and an empty directory), a piece of a colour
    # profile, a comment, a table for arithmetic coding, an empty APP15; fill bytes, and bytes after the end.
    made("extras", 24, 16, [(2, 1), (1, 1), (1, 1)], SEQUENTIAL, fill=3, after_end=b"anything at all",
         before=[(0xE1, b"Exif\x00\x00MM\x00\x2a\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00"),
                 (0xE2, b"ICC_PROFILE\x00\x01\x01"), (0xFE, b"a comment"), (0xCC, b"\x00\x11"), (0xEF, b"")])
    made("extreme", 16, 16, [(1, 1)], [dict(parts=[0], kind="sequential")], extreme=True)
    made("extreme3", 16, 8, [(1, 1)] * 3, SEQUENTIAL, extreme=True)
    made("one", 1, 1, [(1, 1)], [dict(parts=[0], kind="sequential")])
    made("one420", 1, 1, [(2, 2), (1, 1), (1, 1)], SEQUENTIAL)
    made("nine", 9, 9, [(2, 2), (1, 1), (1, 1)], with_restart(PROGRESSIVE, 1), frame=0xC2, shown_in=[(4, 4)])
    made("eight", 8, 8, [(1, 1)] * 3, SEQUENTIAL, shown_in=[(1, 1), (2, 2), (3, 3)])
    made("big", 160, 120, [(2, 2), (1, 1), (1, 1)], with_restart(SEQUENTIAL, 9),
         shown_in=[(64, 64), (100, 30), (20, 15), (160, 119)])

    # ---------- Photos that are turned down ----------
    def refused(name, data, reason):
        try:
            jpeg.jpeg_read(data)
        except jpeg.Refused:
            pass
        else:
            raise AssertionError("the second reader reads %s" % name)
        write(name + ".jpg", data)
        lines.append("jrefused %s %s" % (name, reason))

    damaged = "it is damaged: "
    kind = "it is a kind of JPEG I do not read: "
    sound = made("sound", 20, 12, [(2, 2), (1, 1), (1, 1)], with_restart(SEQUENTIAL, 1))
    made("soundprog", 20, 12, [(2, 2), (1, 1), (1, 1)], PROGRESSIVE, frame=0xC2)
    made("soundgrey", 20, 12, [(1, 1)], [dict(parts=[0], kind="sequential")])
    frame_at, frame_end = find(sound, 0xC0)

    def changed(data, at, new):
        return data[:at] + new + data[at + len(new):]

    def with_frame_code(code, data=sound):
        return changed(data, frame_at + 1, bytes([code]))

    refused("arith", with_frame_code(0xC9), kind + "its data is packed with arithmetic coding")
    refused("lossless", with_frame_code(0xC3), kind + "it is lossless")
    refused("hier", with_frame_code(0xC5), kind + "it is hierarchical")
    refused("twelve", changed(with_frame_code(0xC1), frame_at + 4, b"\x0c"), kind + "its samples have 12 bits")
    refused("twelvebase", changed(sound, frame_at + 4, b"\x0c"),
            damaged + "its samples have a number of bits its kind of frame does not allow")
    refused("height0", changed(sound, frame_at + 5, b"\x00\x00"), kind + "its height comes after its first scan")
    refused("width0", changed(sound, frame_at + 7, b"\x00\x00"), damaged + "its width is 0")
    four = jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0), (2, 1, 1, 0, 0, 0), (3, 1, 1, 0, 0, 0), (4, 1, 1, 0, 0, 0)],
                           [[[[0] * 64]]] * 4, {0: (0, LUMA)}, [dict(parts=[0, 1, 2, 3], kind="sequential")])
    refused("cmyk", four, kind + "its colours are in other than 1 or 3 components, as CMYK's are in 4")
    two = jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0), (2, 1, 1, 0, 0, 0)], [[[[0] * 64]]] * 2, {0: (0, LUMA)},
                          [dict(parts=[0, 1], kind="sequential")])
    refused("twocomp", two, kind + "its colours are in other than 1 or 3 components, as CMYK's are in 4")
    ratios = jpeg.jpeg_write(8, 8, [(1, 3, 1, 0, 0, 0), (2, 2, 1, 0, 0, 0), (3, 1, 1, 0, 0, 0)],
                             [[[[0] * 64] * 3], [[[0] * 64] * 2], [[[0] * 64]]], {0: (0, LUMA)}, SEQUENTIAL)
    refused("ratios", ratios, kind + "its colour components are sampled at ratios that are not whole")
    end_at = find(sound, 0xD9)[0]
    refused("dnl", sound[:end_at] + b"\xff\xdc\x00\x04\x00\x0c" + sound[end_at:],
            kind + "its height comes after its first scan")
    refused("unknown", sound[:frame_at] + b"\xff\xf7\x00\x04ab" + sound[frame_at:],
            kind + "it holds a marker I do not know")
    refused("notjpeg", b"GIF89a" + sound[6:], "it does not begin as a JPEG photo does")
    refused("twoframes", sound[:frame_end] + sound[frame_at:frame_end] + sound[frame_end:],
            damaged + "it has two frames")
    refused("noframe", sound[:frame_at] + sound[frame_end:], damaged + "a scan or its end comes before its frame")
    refused("twostarts", sound[:frame_at] + b"\xff\xd8" + sound[frame_at:], damaged + "it has a second start marker")
    refused("notmarker", sound[:frame_at] + b"\x00" + sound[frame_at:],
            damaged + "something stands between its segments that is not a marker")
    refused("strayrst", sound[:frame_at] + b"\xff\xd0" + sound[frame_at:],
            damaged + "a restart marker stands outside a scan's data")
    refused("factors", changed(sound, frame_at + 11, b"\x52"),
            damaged + "a component's sampling factors are not from 1 to 4")
    refused("tableplace", changed(sound, frame_at + 12, b"\x04"), damaged + "it names a table that cannot be")
    refused("samenames", changed(sound, frame_at + 13, b"\x01"), damaged + "two of its components have the same name")
    refused("framelength", changed(sound, frame_at + 3, bytes([sound[frame_at + 3] + 1])),
            damaged + "a segment's length does not fit what it holds")
    quant_at, quant_end = find(sound, 0xDB)
    refused("quantprecision", changed(sound, quant_at + 4, b"\x20"),
            damaged + "a quantization table has a precision that does not exist")
    refused("quantzero", changed(sound, quant_at + 5, b"\x00"), damaged + "a quantization table holds a 0")
    refused("noquant", sound[:quant_at] + sound[quant_end:], damaged + "a scan uses a table that has not been given")
    codes_at, codes_end = find(sound, 0xC4)
    refused("notable", sound[:codes_at] + sound[codes_end:], damaged + "a scan uses a table that has not been given")
    # A table of two codes of 1 bit: the second is all 1-bits, which is kept for longer codes.
    overfull = b"\xff\xc4\x00\x15\x00\x02" + bytes(15) + b"\x00\x01"
    refused("overfull", sound[:codes_at] + overfull + sound[codes_at:],
            damaged + "a table of codes has more codes than can be")
    scan_at, _ = find(sound, 0xDA)
    refused("scansize", changed(sound, scan_at + 4, b"\x05"), damaged + "a scan names no components, or more than 4")
    refused("notinframe", changed(sound, scan_at + 5, b"\x09"),
            damaged + "a scan names a component its frame does not have")
    refused("scanorder", changed(changed(sound, scan_at + 5, b"\x02"), scan_at + 7, b"\x01"),
            damaged + "a scan names its components out of the frame's order")
    many = jpeg.jpeg_write(32, 32, [(1, 4, 4, 0, 0, 0), (2, 1, 1, 0, 0, 0), (3, 1, 1, 0, 0, 0)],
                           [[[[0] * 64] * 4] * 4, [[[0] * 64]], [[[0] * 64]]], {0: (0, LUMA)}, SEQUENTIAL)
    refused("manyblocks", many, damaged + "a scan's units have more than 10 blocks")
    refused("twoscans", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0)], [[[[0] * 64]]], {0: (0, LUMA)},
                                        [dict(parts=[0], kind="sequential")] * 2),
            damaged + "a component comes in two scans")
    refused("missing", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0), (2, 1, 1, 0, 0, 0), (3, 1, 1, 0, 0, 0)],
                                       [[[[0] * 64]]] * 3, {0: (0, LUMA)},
                                       [dict(parts=[0], kind="sequential"), dict(parts=[1], kind="sequential")]),
            damaged + "it ends before all its components have come")
    small = [[[[5] + [1] * 63]]]
    refused("acfirst", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0)], small, {0: (0, LUMA)},
                                       [dict(parts=[0], kind="ac-first", band=(1, 63)),
                                        dict(parts=[0], kind="dc-first", band=(0, 0))], frame=0xC2),
            damaged + "its scans do not build up its coefficients in order")
    refused("badrefine", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0)], small, {0: (0, LUMA)},
                                         [dict(parts=[0], kind="dc-first", band=(0, 0)),
                                          dict(parts=[0], kind="ac-first", band=(1, 63), approximation=(0, 2)),
                                          dict(parts=[0], kind="ac-refine", band=(1, 63), approximation=(2, 0))],
                                         frame=0xC2),
            damaged + "a scan's band of coefficients is not as a progressive scan's must be")
    refused("wrongah", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0)], small, {0: (0, LUMA)},
                                       [dict(parts=[0], kind="dc-first", band=(0, 0)),
                                        dict(parts=[0], kind="ac-first", band=(1, 63), approximation=(0, 2)),
                                        dict(parts=[0], kind="ac-refine", band=(1, 63), approximation=(3, 2))],
                                       frame=0xC2),
            damaged + "its scans do not build up its coefficients in order")
    refused("resent", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0)], small, {0: (0, LUMA)},
                                      [dict(parts=[0], kind="dc-first", band=(0, 0)),
                                       dict(parts=[0], kind="ac-first", band=(1, 63)),
                                       dict(parts=[0], kind="ac-first", band=(5, 9))], frame=0xC2),
            damaged + "its scans do not build up its coefficients in order")
    refused("dcband", jpeg.jpeg_write(8, 8, [(1, 1, 1, 0, 0, 0)], small, {0: (0, LUMA)},
                                      [dict(parts=[0], kind="dc-first", band=(0, 5))], frame=0xC2),
            damaged + "a scan's band of coefficients is not as a progressive scan's must be")
    rst_at = sound.index(b"\xff\xd0", scan_at)
    refused("rstorder", changed(sound, rst_at + 1, b"\xd1"), damaged + "a restart marker is missing or out of turn")
    refused("rstmissing", sound[:rst_at] + sound[rst_at + 2:],
            damaged + "a scan's data goes on where a marker must come")
    refused("extradata", sound[:rst_at] + b"\x12" + sound[rst_at:],
            damaged + "a scan's data goes on where a marker must come")
    refused("extradataend", sound[:end_at] + b"\x12" + sound[end_at:],
            damaged + "a scan's data goes on where a marker must come")
    refused("rstatend", sound[:end_at] + b"\xff\xd3" + sound[end_at:],
            damaged + "a restart marker is missing or out of turn")
    refused("noend", sound[:end_at], "the file ends before the picture does")
    # A grey photo whose DC values climb by 2000 from block to block: the 17th is past what 16 bits hold.
    climbing = jpeg.jpeg_write(17 * 8, 8, [(1, 1, 1, 0, 0, 0)], [[[[2000 * (x + 1)] + [0] * 63 for x in range(17)]]],
                               {0: (0, LUMA)}, [dict(parts=[0], kind="sequential")])
    refused("climbing", climbing, damaged + "a coefficient is larger than 16 bits hold")
    # A progressive photo whose run of empty blocks goes on past its restart interval: the writer is told to
    # count a block more in the run it sends at the restart.
    rows = [[[[7] + [0] * 63 for _ in range(4)]]]
    runs = jpeg.jpeg_write(32, 8, [(1, 1, 1, 0, 0, 0)], rows, {0: (0, LUMA)},
                           [dict(parts=[0], kind="dc-first", band=(0, 0)),
                            dict(parts=[0], kind="ac-first", band=(1, 63), restart=2, long_run=True)], frame=0xC2)
    refused("eobpast", runs, damaged + "a run of empty blocks goes past the end of its restart interval")

    at = 0
    for name, data in files:
        lines.append("file %s %d %d" % (name, at, len(data)))
        at += len(data)
    with open(os.path.join(OUT, "jpeg-cases.bin"), "wb") as f:
        f.write(b"".join(data for _, data in files))
    with open(os.path.join(OUT, "jpeg-cases.txt"), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("%d cases, %d test files, %d bytes in %s" % (len(lines) - len(files), len(files), at, OUT))


if __name__ == "__main__":
    main()
