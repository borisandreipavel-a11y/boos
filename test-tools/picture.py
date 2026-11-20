"""Builds the picture the screen is meant to show, from numbers typed in here
and the letter grids in letters.rs, and compares a saved picture with it.

Nothing here comes from what the kernel prints or paints."""

import os
import re
import struct
import zlib

from places import PROJECT

LETTERS = os.path.join(PROJECT, "src", "letters.rs")

BLUE = (0, 40, 90)
WHITE = (255, 255, 255)
ORANGE = (255, 150, 0)
BLACK = (0, 0, 0)
PANEL_INSIDE = (240, 240, 240)

# The chat box's look, typed in here by hand.
CHAT_ROWS = 6
CHAT_MARGIN = 40
CHAT_FRAME = 3
CHAT_PADDING = 10
CHAT_ROW_GAP = 4
CHAT_SIZE = 2
CHAT_INSIDE = (232, 236, 244)
CHAT_TYPING = (255, 255, 255)
CHAT_PERSON = (0, 0, 0)
CHAT_KERNEL = (0, 60, 140)
CHAT_LINE_LIMIT = 50
SECRET_WORD = "key"
# Every other line but `setup` goes to the model, and the kernel says at once one of these (docs/tools.md).
ASKING = "Kernel: I am asking the model."
NO_KEY = 'Kernel: I cannot ask the model, because no key is kept. Send the line "key" first.'
NO_ADDRESS = "Kernel: I cannot ask the model, because this machine has no address on the network"
BUSY = "Kernel: I cannot ask the model, because the answer to what I asked before has not come yet"
STARS_SHOWN = 30
SECRET_LIMIT = 200
import os
if os.environ.get("CHAT_LOOK") == "other":
    CHAT_ROWS, CHAT_MARGIN, CHAT_FRAME, CHAT_PADDING, CHAT_ROW_GAP, CHAT_SIZE = 4, 20, 5, 6, 2, 3
    CHAT_INSIDE, CHAT_TYPING, CHAT_PERSON, CHAT_KERNEL = (20, 30, 40), (60, 70, 80), (250, 250, 250), (120, 220, 120)
    CHAT_FRAME_COLOUR = (200, 200, 200)
else:
    CHAT_FRAME_COLOUR = (255, 150, 0)
GREETING = "Kernel: type a line and press Enter."

LETTER_WIDTH = 5
LETTER_HEIGHT = 9

# The looks a person can pick (look_values.py, typed in by hand from the design). A model of the chat box may say
# which one is in use with an attribute `look` (its name); without one, the first look, "Blue", is meant.
from look_values import LOOKS as LOOK_COLOURS


def look_of(chat):
    return LOOK_COLOURS[getattr(chat, "look", "Blue")]


def read_shapes():
    rows = re.findall(r'\*b"([#.]{5})"', open(LETTERS, encoding="utf-8").read())
    assert len(rows) == 96 * 9, len(rows)
    shapes = [rows[i * 9:(i + 1) * 9] for i in range(96)]
    return shapes[0], shapes[1:]


UNKNOWN, SHAPES = read_shapes()


def shape_of(sign):
    number = ord(sign)
    if 32 <= number <= 126:
        return SHAPES[number - 32]
    return UNKNOWN


class Picture:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.dots = bytearray(width * height * 3)

    def rectangle(self, left, top, width, height, colour):
        right = min(left + width, self.width)
        bottom = min(top + height, self.height)
        if left >= right or top >= bottom:
            return
        row = bytes(colour) * (right - left)
        for y in range(top, bottom):
            start = (y * self.width + left) * 3
            self.dots[start:start + len(row)] = row

    def fill(self, colour):
        self.rectangle(0, 0, self.width, self.height, colour)

    def text(self, left, top, text, size, colour):
        sign_left = left
        for sign in text:
            shape = shape_of(sign)
            for row, dots in enumerate(shape):
                for column, dot in enumerate(dots):
                    if dot == "#":
                        self.rectangle(sign_left + size * column, top + size * row, size, size, colour)
            sign_left += size * (LETTER_WIDTH + 1)

    def panel(self, text, look=None):
        look = look or LOOK_COLOURS["Blue"]
        width, height, frame = 520, 60, 3
        left = self.width // 2 - width // 2
        top = self.height // 2 - height // 2
        self.rectangle(left, top, width, height, look["panel_frame"])
        self.rectangle(left + frame, top + frame, width - 2 * frame, height - 2 * frame, look["panel_inside"])
        self.text(left + 20, top + 21, text[:40], 2, look["panel_text"])


def chat_room(screen_width):
    width = screen_width - 2 * CHAT_MARGIN
    return (width - 2 * CHAT_FRAME - 2 * CHAT_PADDING) // (CHAT_SIZE * (LETTER_WIDTH + 1))


class Chat:
    """What the chat box is meant to hold after a row of keys."""

    def __init__(self, screen_width):
        self.room = chat_room(screen_width) if screen_width else None
        self.rows = []
        self.line = ""
        self.said = []  # the lines meant to appear in the terminal
        self.secret_asked = False
        self.network = "ready"  # or "none" (no address), "busy" (an answer is still awaited)
        self.secret_signs = 0
        self.secret_held = False
        if self.room:
            self.add("kernel", GREETING)

    def person(self):
        """What stands in front of the person's rows."""
        return "You"

    def line_room(self):
        if self.room is None:
            return CHAT_LINE_LIMIT
        return min(CHAT_LINE_LIMIT, max(self.room - 3, 0))

    def add(self, speaker, text):
        if not self.room:
            return
        for start in range(0, len(text), self.room):
            self.rows.append((speaker, text[start:start + self.room]))
        self.rows = self.rows[-CHAT_ROWS:]

    def typing_text(self):
        if not self.secret_asked:
            return "> " + self.line + "_"
        text = "> " + "*" * min(self.secret_signs, STARS_SHOWN)
        if self.secret_signs > STARS_SHOWN:
            text += " and %d more" % (self.secret_signs - STARS_SHOWN)
        return text + "_"

    def secret_key(self, sign):
        if sign == "\b":
            self.secret_signs = max(self.secret_signs - 1, 0)
        elif sign == "\n":
            if self.secret_signs == 0:
                answer = "Kernel: no secret was taken."
            else:
                answer = "Kernel: I took a secret of %d %s. It is kept in memory only.%s" % (
                    self.secret_signs, "sign" if self.secret_signs == 1 else "signs", " The one before is gone." if self.secret_held else "")
                self.secret_held = True
            self.said.append(answer)
            self.add("kernel", answer)
            self.secret_signs = 0
            self.secret_asked = False
        elif self.secret_signs < SECRET_LIMIT:
            self.secret_signs += 1

    def key(self, sign):
        if self.secret_asked:
            self.secret_key(sign)
            return
        if sign == "\b":
            self.line = self.line[:-1]
        elif sign == "\n":
            if self.line == "":
                return
            mine = self.person() + ": " + self.line
            if self.line == SECRET_WORD:
                answer = "Kernel: type the secret and press Enter. It shows as stars."
                self.secret_asked = True
            elif not self.secret_held:
                answer = NO_KEY
            else:
                answer = {"ready": ASKING, "none": NO_ADDRESS, "busy": BUSY}[self.network]
            self.said += [mine, answer]
            self.add("person", mine)
            self.add("kernel", answer)
            self.line = ""
        else:
            if len(self.line) < self.line_room():
                self.line += sign

    def say(self, text):
        """A row the kernel says by itself, such as the answer to an errand."""
        self.said.append("Kernel: " + text)
        self.add("kernel", "Kernel: " + text)

    def row(self, text):
        """A whole row as it is, such as the model's words, which begin with "Model:"."""
        self.said.append(text)
        self.add("kernel", text)

    def keys(self, text):
        for sign in text:
            self.key(sign)


def chat_box(picture, chat):
    # The chat box's colours: those of the look in use, or the other look of an old test (CHAT_LOOK=other).
    if os.environ.get("CHAT_LOOK") == "other":
        frame_colour, inside, typing, person, kernel = CHAT_FRAME_COLOUR, CHAT_INSIDE, CHAT_TYPING, CHAT_PERSON, CHAT_KERNEL
    else:
        look = look_of(chat)
        frame_colour, inside, typing, person, kernel = (look["chat_frame"], look["chat_inside"], look["chat_typing"],
                                                        look["chat_person"], look["chat_kernel"])
    row_height = CHAT_SIZE * LETTER_HEIGHT + CHAT_ROW_GAP
    width = picture.width - 2 * CHAT_MARGIN
    height = 2 * CHAT_FRAME + 2 * CHAT_PADDING + (CHAT_ROWS + 1) * row_height
    left = CHAT_MARGIN
    top = picture.height - CHAT_MARGIN - height
    picture.rectangle(left, top, width, height, frame_colour)
    typing_top = top + CHAT_FRAME + CHAT_PADDING + CHAT_ROWS * row_height
    picture.rectangle(left + CHAT_FRAME, top + CHAT_FRAME, width - 2 * CHAT_FRAME, typing_top - top - CHAT_FRAME, inside)
    bottom = top + height - CHAT_FRAME
    picture.rectangle(left + CHAT_FRAME, typing_top, width - 2 * CHAT_FRAME, bottom - typing_top, typing)
    text_left = left + CHAT_FRAME + CHAT_PADDING
    y = top + CHAT_FRAME + CHAT_PADDING
    for speaker, text in chat.rows:
        picture.text(text_left, y, text[:chat.room], CHAT_SIZE, person if speaker == "person" else kernel)
        y += row_height
    typing_text_top = typing_top + (bottom - typing_top - CHAT_SIZE * LETTER_HEIGHT) // 2
    picture.text(text_left, typing_text_top, chat.typing_text()[:chat.room], CHAT_SIZE, person)
    return (left, top, width, height)


def expected(width, height, chat, panel_text="Hello from a Lua script!!!"):
    picture = Picture(width, height)
    look = look_of(chat)
    picture.fill(look["background"])
    picture.text(40, 40, "Hello from my kernel! I draw my own letters now.", 2, look["sentence"])
    box = chat_box(picture, chat)
    if panel_text is not None:
        picture.panel(panel_text, look)
        # The parts must not lie on top of each other on this screen.
        panel_bottom = height // 2 - 30 + 60
        assert panel_bottom <= box[1], "the panel and the chat box overlap"
        assert 40 + 18 <= height // 2 - 30, "the sentence and the panel overlap"
    return picture


def read_ppm(path):
    data = open(path, "rb").read()
    parts = data.split(None, 4)
    assert parts[0] == b"P6", parts[0]
    width, height, most = int(parts[1]), int(parts[2]), int(parts[3])
    assert most == 255
    dots = data[len(data) - width * height * 3:]
    return width, height, dots


def compare(path, picture):
    """Gives the number of dots that differ, and the first few places."""
    width, height, dots = read_ppm(path)
    if (width, height) != (picture.width, picture.height):
        return -1, ["size %dx%d, meant %dx%d" % (width, height, picture.width, picture.height)]
    want = bytes(picture.dots)
    if dots == want:
        return 0, []
    wrong = 0
    places = []
    for y in range(height):
        a = dots[y * width * 3:(y + 1) * width * 3]
        b = want[y * width * 3:(y + 1) * width * 3]
        if a == b:
            continue
        for x in range(width):
            if a[x * 3:x * 3 + 3] != b[x * 3:x * 3 + 3]:
                wrong += 1
                if len(places) < 5:
                    places.append("column %d row %d is %s, meant %s" % (x, y, tuple(a[x * 3:x * 3 + 3]), tuple(b[x * 3:x * 3 + 3])))
    return wrong, places


def to_png(ppm_path, png_path):
    width, height, dots = read_ppm(ppm_path)
    raw = b"".join(b"\x00" + dots[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(png_path, "wb").write(png)
