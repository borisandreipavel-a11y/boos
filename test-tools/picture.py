"""Builds the picture the screen is meant to show, from numbers typed in here
and the letter grids in letters.rs, and compares a saved picture with it.

Nothing here comes from what the kernel prints or paints."""

import os
import re
import struct
import zlib

from conversation_model import Memory
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
CHAT_LINE_LIMIT = 200
# The model's own stand-ins for the keys that are no signs (docs/chat.md); onboard_model.NAMES gives QEMU's names.
LEFT, RIGHT, HOME, END, UP, DOWN, DELETE = "\x02", "\x06", "\x01", "\x05", "\x10", "\x0e", "\x7f"
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

# Where the box with an app's text begins: under the panel of apps, which is 40 dots from the left, 80 from the top
# and 158 high, with 20 dots between them.
BOX_LEFT, BOX_TOP = 40, 80 + 158 + 20

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
        """The box with an app's text (docs/screen.md, "The panel"): 520 by 60 dots, 20 dots under the panel of apps
        (40 dots from the left, 80 from the top, 158 high), at its left edge, on every screen."""
        look = look or LOOK_COLOURS["Blue"]
        width, height, frame = 520, 60, 3
        left, top = BOX_LEFT, BOX_TOP
        self.rectangle(left, top, width, height, look["panel_frame"])
        self.rectangle(left + frame, top + frame, width - 2 * frame, height - 2 * frame, look["panel_inside"])
        self.text(left + 20, top + 21, text[:40], 2, look["panel_text"])


def typing_rows_most():
    """The most rows of the chat box the row being typed may take: half of them, those of what was said and the row
    being typed together (docs/chat.md)."""
    return max((CHAT_ROWS + 1) // 2, 1)


def chat_room(screen_width):
    width = screen_width - 2 * CHAT_MARGIN
    return (width - 2 * CHAT_FRAME - 2 * CHAT_PADDING) // (CHAT_SIZE * (LETTER_WIDTH + 1))


class Chat:
    """What the chat box is meant to hold after a row of keys."""

    def __init__(self, screen_width):
        self.room = chat_room(screen_width) if screen_width else None
        self.rows = []
        self._line = ""
        self.at = 0  # where the next sign goes: how many signs of the line stand before that place
        self.last_sent = ""  # what Up brings back
        self.set_aside = None  # what was typed before Up, with its place, for Down
        self.said = []  # the lines meant to appear in the terminal
        self.secret_asked = False
        self.network = "ready"  # or "none" (no address), "busy" (an answer is still awaited)
        self.secret_signs = 0
        self.secret_held = False
        # What the kernel remembers of the conversation (conversation_model.py), and the record that each line
        # which went to the model went with, in turn.
        self.memory = Memory()
        self.records = []
        # What each further ask about a line went with, in turn, when what a tool did went back to the model: the
        # record of the lines before it and the rows the line brought so far (Memory.split).
        self.agains = []
        if self.room:
            self.add("kernel", GREETING)

    def person(self):
        """What stands in front of the person's rows."""
        return "You"

    @property
    def line(self):
        return self._line

    @line.setter
    def line(self, value):
        """Setting the line whole, as Enter does, puts the place where the next sign goes behind its last sign;
        taking it (an empty line) also lets go of what Up set aside."""
        self._line = value
        self.at = len(value)
        if value == "":
            self.set_aside = None

    def line_room(self):
        return CHAT_LINE_LIMIT

    def kernel_question(self):
        """Whether the kernel waits for the answer to a question of its own; Up and Down do nothing then. This
        model asks none."""
        return False

    def stars_now(self):
        """Whether what is typed shows as stars."""
        return self.secret_asked

    def typing_shape(self):
        """How many rows of the chat box the row being typed takes, and the first row of its text that shows
        (docs/chat.md): its text, "> ", the line and a place for the "_", is as many signs as the line and 3 more, cut
        into rows of `room`; it takes as many rows as that needs, at most typing_rows_most(); then the rows shown
        end with the last, unless the place lies above them, when they begin with the row that holds it. Stars:
        one row."""
        if not self.room or self.stars_now():
            return 1, 0
        needed = max(1, -(-(len(self.line) + 3) // self.room))
        shown = min(needed, typing_rows_most())
        return shown, min(needed - shown, (self.at + 2) // self.room)

    def marked_cell(self):
        """The sign of the typing text painted in swapped colours: the one at the place where the next sign goes,
        when that place lies inside the line (not while stars are typed)."""
        if self.stars_now() or self.at >= len(self.line):
            return None
        return self.at + 2

    def add(self, speaker, text):
        if not self.room:
            return
        for start in range(0, len(text), self.room):
            self.rows.append((speaker, text[start:start + self.room]))
        self.rows = self.rows[-CHAT_ROWS:]

    def typing_text(self):
        if not self.secret_asked:
            return "> " + self.line + ("_" if self.at >= len(self.line) else "")
        text = "> " + "*" * min(self.secret_signs, STARS_SHOWN)
        if self.secret_signs > STARS_SHOWN:
            text += " and %d more" % (self.secret_signs - STARS_SHOWN)
        return text + "_"

    def secret_key(self, sign):
        if sign not in ("\b", "\n") and not " " <= sign <= "~":
            return  # the keys that are no signs do nothing while stars are typed
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
            if self.at > 0:
                self._line = self._line[:self.at - 1] + self._line[self.at:]
                self.at -= 1
        elif sign == DELETE:
            self._line = self._line[:self.at] + self._line[self.at + 1:]
        elif sign == LEFT:
            self.at = max(self.at - 1, 0)
        elif sign == RIGHT:
            self.at = min(self.at + 1, len(self._line))
        elif sign == HOME:
            self.at = 0
        elif sign == END:
            self.at = len(self._line)
        elif sign == UP:
            if not self.kernel_question() and self.set_aside is None and self.last_sent:
                self.set_aside = (self._line, self.at)
                self._line, self.at = self.last_sent, len(self.last_sent)
        elif sign == DOWN:
            if not self.kernel_question() and self.set_aside is not None:
                (self._line, self.at), self.set_aside = self.set_aside, None
        elif sign == "\n":
            if self.line == "":
                return
            self.last_sent = self.line
            mine = self.person() + ": " + self.line
            if self.line == SECRET_WORD:
                answer = "Kernel: type the secret and press Enter. It shows as stars."
                self.secret_asked = True
            elif not self.secret_held:
                answer = NO_KEY
            else:
                answer = {"ready": ASKING, "none": NO_ADDRESS, "busy": BUSY}[self.network]
                if answer == ASKING:
                    self.records.append(self.memory.sent(self.line))
            self.said += [mine, answer]
            self.add("person", mine)
            self.add("kernel", answer)
            self.line = ""
        elif " " <= sign <= "~":
            if len(self._line) < self.line_room():
                self._line = self._line[:self.at] + sign + self._line[self.at:]
                self.at += 1

    def say(self, text):
        """A row the kernel says by itself, such as the answer to an errand. It is remembered with the line it
        answers (conversation_model.py)."""
        self.said.append("Kernel: " + text)
        self.add("kernel", "Kernel: " + text)
        self.memory.answered("Kernel: " + text)

    def row(self, text):
        """A whole row as it is, such as the model's words, which begin with "Model:". It is remembered with the
        line it answers."""
        self.said.append(text)
        self.add("kernel", text)
        self.memory.answered(text)

    def remember(self, text):
        """A sentence of the kernel's that is remembered with the line it answers but not said in the chat box or the
        terminal: what an app left behind, when what a tool did goes back to the model."""
        self.memory.answered("Kernel: " + text)

    def again(self):
        """The kernel asks the model about the newest line again: what that ask goes with is kept, in turn."""
        self.agains.append(self.memory.split())

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
    one_row_top = top + CHAT_FRAME + CHAT_PADDING + CHAT_ROWS * row_height
    # The row being typed grows upward when the line needs more rows, and as many fewer rows of what was said show
    # (docs/chat.md).
    shown, first = chat.typing_shape()
    typing_top = one_row_top - (shown - 1) * row_height
    picture.rectangle(left + CHAT_FRAME, top + CHAT_FRAME, width - 2 * CHAT_FRAME, typing_top - top - CHAT_FRAME, inside)
    bottom = top + height - CHAT_FRAME
    picture.rectangle(left + CHAT_FRAME, typing_top, width - 2 * CHAT_FRAME, bottom - typing_top, typing)
    text_left = left + CHAT_FRAME + CHAT_PADDING
    y = top + CHAT_FRAME + CHAT_PADDING
    fit = CHAT_ROWS - (shown - 1)
    for speaker, text in chat.rows[max(len(chat.rows) - fit, 0):]:
        picture.text(text_left, y, text[:chat.room], CHAT_SIZE, person if speaker == "person" else kernel)
        y += row_height
    # The last row's letters where the one row's always were, the rows above it one row higher each; the sign at
    # the place, inside the line, in swapped colours.
    last_text_top = one_row_top + (bottom - one_row_top - CHAT_SIZE * LETTER_HEIGHT) // 2
    text, marked, room = chat.typing_text(), chat.marked_cell(), chat.room
    sign_width = CHAT_SIZE * (LETTER_WIDTH + 1)
    for number in range(shown):
        piece = first + number
        y = last_text_top - (shown - 1 - number) * row_height
        picture.text(text_left, y, text[piece * room:(piece + 1) * room], CHAT_SIZE, person)
        if marked is not None and marked // room == piece:
            x = text_left + (marked % room) * sign_width
            picture.rectangle(x, y, sign_width, CHAT_SIZE * LETTER_HEIGHT, person)
            picture.text(x, y, text[marked], CHAT_SIZE, typing)
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
        assert BOX_TOP + 60 <= box[1], "the panel and the chat box overlap"
    # The table drawn last, kept in memory until the machine is switched off (table_model.py), when the model of the
    # chat box holds one.
    table = getattr(chat, "table", None)
    if table is not None:
        import table_model
        table_model.paint(picture, table, getattr(chat, "look", "Blue"))
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
