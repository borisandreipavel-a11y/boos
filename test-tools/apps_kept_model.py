"""An outside model of the apps kept on the disk, written from docs/notebook.md ("A thing in pieces") and docs/apps.md
("Keeping an app" and "The panel of apps"), not from the kernel's code: a writer and a reader of notebooks whose
things may be kept in pieces, with Python's own CRC-32; the apps a notebook holds and the lines the kernel is meant
to print about them at a start; the panel of apps as part of the picture of the screen; and the chat box with the
line `make`.

Nothing runs when this file is imported."""
import re
import struct
import zlib

from app_cases import answer, hide, script_meant
from keyed_model import KeyedChat
from look_values import LOOKS
from nb import BLOCK, ENTRY_LETTERS, FIRST, LAST, head, put_block
from picture import LETTER_HEIGHT, LETTER_WIDTH, expected

DATA_MOST = 448                       # the most data one entry holds
THING_MOST = 32 * 1024                # the most data one thing holds
PIECES_MOST = -(-THING_MOST // DATA_MOST)
assert PIECES_MOST == 74

NOTE_FORM = 1                         # the first byte of an app's note
REQUEST_MOST = 45                     # the most of a request that is taken from the disk
ANSWERS = [("name", b""), ("locked key", b""), ("look", b"")]   # a notebook whose start asks nothing


def crc(data):
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


# ---------- Writing notebooks ----------

def block_of(number, name, data, piece=0, pieces=0, whole=0, good=True):
    """One entry's block as the layout says: letters, number, lengths, check value of the block, the eight bytes for
    pieces, then the name and the data."""
    name = name if isinstance(name, bytes) else name.encode()
    block = bytearray(BLOCK)
    block[0:8] = ENTRY_LETTERS
    block[8:16] = struct.pack("<Q", number)
    block[16:18] = struct.pack("<H", len(name))
    block[18:20] = struct.pack("<H", len(data))
    block[24:26] = struct.pack("<H", piece)
    block[26:28] = struct.pack("<H", pieces)
    block[28:32] = struct.pack("<I", whole)
    text = name + data
    block[32:32 + len(text)] = text
    check = crc(block)
    block[20:24] = struct.pack("<I", check if good else check ^ 1)
    return bytes(block)


def pieces_of(data):
    """The pieces a thing longer than one entry is kept in: (piece, pieces, whole check, data of the piece)."""
    chunks = [data[i:i + DATA_MOST] for i in range(0, len(data), DATA_MOST)]
    return [(i + 1, len(chunks), crc(data), chunk) for i, chunk in enumerate(chunks)]


def raw(name, data, piece=0, pieces=0, whole=0, good=True):
    """A block made by hand, for write_notebook: its number is filled in where it lands."""
    return lambda number: block_of(number, name, data, piece, pieces, whole, good)


def thing(name, data):
    """The blocks of a thing kept as the notes say: one entry for up to 448 bytes, otherwise pieces."""
    data = data if isinstance(data, bytes) else data.encode()
    if len(data) <= DATA_MOST:
        return [raw(name, data)]
    return [raw(name, chunk, piece, pieces, whole) for piece, pieces, whole, chunk in pieces_of(data)]


def write_notebook(path, items, first=FIRST):
    """Writes a head and, from block 1 on, the items: each a (name, data) pair, kept as the kernel keeps a thing, or
    a list of blocks made by hand (raw). Gives back the number of the block behind the last."""
    put_block(path, 0, head(), first)
    number = 1
    for item in items:
        blocks = item if isinstance(item, list) else thing(*item)
        for make in blocks:
            put_block(path, number, make(number), first)
            number += 1
    return number


def note(request):
    """An app's note of form 1: the byte 1, then the request."""
    return bytes([NOTE_FORM]) + (request if isinstance(request, bytes) else request.encode())


def app_things(number, request, script):
    """The two things an app is kept as, in the order they are written: its script, then its note."""
    return [("app %d script" % number, script), ("app %d" % number, note(request))]


# ---------- Reading notebooks ----------

def piece_kind(piece, pieces, whole, length):
    """What the eight bytes for pieces make of a whole entry: "whole" (all zeros), "piece", or "odd"."""
    if piece == 0 and pieces == 0 and whole == 0:
        return "whole"
    if not (2 <= pieces <= PIECES_MOST and 1 <= piece <= pieces):
        return "odd"
    if piece < pieces and length != DATA_MOST:
        return "odd"
    if piece == pieces and (length == 0 or (pieces - 1) * DATA_MOST + length > THING_MOST):
        return "odd"
    return "piece"


def parse(block, number):
    """A whole entry with this number: (name, data, piece, pieces, whole), or None."""
    if block[:8] != ENTRY_LETTERS or struct.unpack("<Q", block[8:16])[0] != number:
        return None
    name_length, data_length = struct.unpack("<HH", block[16:20])
    if name_length > 32 or data_length > DATA_MOST:
        return None
    name = block[32:32 + name_length]
    if not name or any(not 32 <= b <= 126 for b in name):
        return None
    if crc(block[:20] + b"\0\0\0\0" + block[24:]) != struct.unpack("<I", block[20:24])[0]:
        return None
    piece, pieces, whole = struct.unpack("<HHI", block[24:32])
    return name.decode(), bytes(block[32 + name_length:32 + name_length + data_length]), piece, pieces, whole


def read_things(path, first=FIRST, last=LAST):
    """Reads a notebook as the notes say. The end is the first block that is not the next whole entry, whatever its
    eight bytes for pieces say; a thing counts once it is whole. Gives back the end, the entries in order, the things
    that count ({name: (block it begins in, data)}), and the blocks behind the end (up to eight) that are not zeros."""
    size = last - first + 1
    disk = open(path, "rb").read()

    def block(number):
        return disk[(first + number) * BLOCK:(first + number + 1) * BLOCK]

    entries, things, gathering = [], {}, None
    number = 1
    while number <= size - 2:
        found = parse(block(number), number)
        if found is None:
            break
        entries.append(found)
        name, data, piece, pieces, whole = found
        kind = piece_kind(piece, pieces, whole, len(data))
        if kind == "whole":
            gathering = None
            things[name] = (number, data)
        elif kind == "piece":
            if piece == 1:
                gathering = dict(name=name, first=number, pieces=pieces, whole=whole, data=bytearray(data))
            elif (gathering and gathering["name"] == name and gathering["pieces"] == pieces and gathering["whole"] == whole
                  and gathering["first"] + piece - 1 == number):
                gathering["data"] += data
            else:
                gathering = None
            if gathering and piece == pieces:
                if crc(gathering["data"]) == whole:
                    things[name] = (gathering["first"], bytes(gathering["data"]))
                gathering = None
        else:
            gathering = None
        number += 1
    behind = [n for n in range(number + 1, min(number + 8, size - 2) + 1) if block(n) != bytes(BLOCK)]
    return dict(end=number, entries=entries, things=things, behind=behind)


# ---------- The apps a notebook holds ----------

def clean_request(data):
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data[:REQUEST_MOST])


def apps_of(things):
    """The apps a start finds: [(number, request, whole)], the one whose script was kept last first, the apps whose
    script is not whole last, in the order their notes were kept."""
    found = []
    for name, (block, data) in sorted(things.items(), key=lambda item: item[1][0]):
        match = re.fullmatch(r"app ([1-9][0-9]{0,8})", name)
        if not match or len(data) < 2 or data[0] != NOTE_FORM:
            continue
        script = things.get("app %s script" % match.group(1))
        found.append((script[0] if script else None, int(match.group(1)), clean_request(data[1:])))
    whole = sorted([f for f in found if f[0] is not None], key=lambda f: -f[0])
    broken = [f for f in found if f[0] is None]
    return [(number, request, block is not None) for block, number, request in whole + broken]


def start_lines(apps):
    """The lines that begin with "Apps:" at a start."""
    listed = [request for _, request, whole in apps if whole]
    lines = []
    if listed:
        lines.append("Apps: %d %s kept on the disk:" % (len(listed), "is" if len(listed) == 1 else "are"))
        lines += ['Apps: "%s"' % request for request in listed]
    lines += ['Apps: the script kept for "%s" is not whole, so that app is left out' % request for _, request, whole in apps if not whole]
    return lines


def kept_line(request):
    return 'Apps: the app made for "%s" is kept on the disk' % request


def not_kept_row(reason):
    return "Kernel: I could not keep the app, because %s." % reason


# ---------- The scripts the stand-in sends, as the kernel keeps them ----------

def kept_script(kind, key):
    """The script of an app kind of app_cases.py as the kernel takes and keeps it: out of the model's words, with
    the key hidden, as bytes."""
    message, _ = answer(kind, key)
    content = message.get("content")
    if isinstance(content, list):
        content = content[0]["text"]
    return hide(script_meant(content.strip()), key).encode()


# ---------- The panel of apps ----------

PANEL = dict(left=40, top=80, width=600, frame=3, padding=10, size=2, gap=4, apps=5)


def panel(picture, requests, page=0, look="Blue"):
    """Paints the panel of apps as docs/apps.md describes it: nothing without apps; otherwise the frame, the inside,
    the row that says the page, and the apps of that page, five a page."""
    if not requests:
        return
    p = PANEL
    colours = LOOKS[look]
    row_height = p["size"] * LETTER_HEIGHT + p["gap"]
    height = 2 * p["frame"] + 2 * p["padding"] + (p["apps"] + 1) * row_height
    assert height == 158
    picture.rectangle(p["left"], p["top"], p["width"], height, colours["panel_frame"])
    picture.rectangle(p["left"] + p["frame"], p["top"] + p["frame"], p["width"] - 2 * p["frame"], height - 2 * p["frame"],
                      colours["panel_inside"])
    pages = -(-len(requests) // p["apps"])
    page = min(page, pages - 1)
    rows = ["Apps: page %d of %d" % (page + 1, pages)] + ["- " + r for r in requests[page * p["apps"]:(page + 1) * p["apps"]]]
    room = (p["width"] - 2 * p["frame"] - 2 * p["padding"]) // (p["size"] * (LETTER_WIDTH + 1))
    assert room == 47
    y = p["top"] + p["frame"] + p["padding"]
    for row in rows:
        picture.text(p["left"] + p["frame"] + p["padding"], y, row[:room], p["size"], colours["panel_text"])
        y += row_height
    # It must lie under the sentence and above the box with an app's text.
    assert p["top"] >= 40 + 18 and p["top"] + height <= picture.height // 2 - 30, "the panel of apps overlaps"


def screen(width, height, chat, requests, page=0, panel_text="Hello from a Lua script!!!"):
    """The whole screen meant: picture.expected's, with the panel of apps on top."""
    picture = expected(width, height, chat, panel_text)
    panel(picture, requests, page, getattr(chat, "look", "Blue"))
    return picture


# ---------- The chat box with the line `make` ----------

def wanted_of(line):
    """The rule for a request: the word alone, or the word, a space and what to make."""
    if not line.startswith("make"):
        return None
    rest = line[4:]
    return rest.strip() if rest == "" or rest.startswith(" ") else None


class MakeChat(KeyedChat):
    """keyed_model.KeyedChat with the line `make` (docs/apps.md): the row it answers at once; the rows that come
    later are added with say()."""

    def key(self, sign):
        busy = self.secret_asked or self.waiting or self.look_asking
        if not busy and sign == "\n" and self.line and wanted_of(self.line) is not None:
            wanted = wanted_of(self.line)
            mine = self.person() + ": " + self.line
            if wanted == "":
                reply = 'Kernel: write what app to make after the word, such as "make a dice".'
            elif not self.secret_held:
                reply = 'Kernel: I cannot ask the model for an app, because no key is kept. Send the line "key" first.'
            else:
                reply = 'Kernel: I am asking the model to make "%s".' % wanted
            self.said += [mine, reply]
            self.add("person", mine)
            self.add("kernel", reply)
            if self.can_keep:
                self.kept.append(("last line", self.line.encode()))
            self.line = ""
            return
        super().key(sign)
