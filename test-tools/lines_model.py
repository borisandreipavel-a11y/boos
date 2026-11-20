"""The picture the kernel's own lines are meant to make on the screen (lines.rs): the lines on the whole screen
while the machine starts and after F1, and the stop screen after a failure or a panic. Built from numbers typed in
here and the letter grids in letters.rs, and from the lines the kernel printed, which are what it keeps; nothing
here comes from how the kernel paints.

    screen = LinesScreen(1280, 800)
    screen.keep("Hello from my kernel!"); screen.cover()     # the start screen begins
    for line in more: screen.keep(line); screen.paint_new()
    picture = screen.picture()
    stop_picture(1280, 800, lines)                          # the last line is the report
"""
from picture import Picture

MARGIN = 8
SIZE = 2
SIGN = SIZE * 6          # a sign and the empty column after it
ROW = SIZE * 10          # a letter and one empty row of its dots
KEPT = 100               # how many lines the kernel keeps
LONGEST = 300            # how many signs of a line it keeps

BACKGROUND = (0, 40, 90)
LETTERS = (255, 255, 255)
STOP_BACKGROUND = (140, 0, 0)
STOP_LETTERS = (255, 255, 255)
STOPPED = "The kernel stopped:"
BEFORE = "What the kernel said before that:"


def place(width, height):
    """How many signs fit on a row, and how many rows fit."""
    return (width - 2 * MARGIN) // SIGN, (height - 2 * MARGIN) // ROW


def clean(line):
    """What the kernel keeps of a printed line: plain signs, anything else as a sign with no picture, 300 at most."""
    return "".join(sign if 32 <= ord(sign) <= 126 else chr(127) for sign in line)[:LONGEST]


def rows_of(text, room):
    return max(1, -(-len(text) // room))


class LinesScreen:
    """What the screen shows while the lines cover it, line by line as the kernel paints them."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.room, self.rows = place(width, height)
        self.kept = []
        self.on_screen = []  # (row, piece of text) painted since the screen was last filled
        self.next_row = 0
        self.painted = 0
        self.jumps = 0

    def keep(self, line):
        self.kept.append(clean(line))

    def paint_line(self, text, row):
        pieces = [text[i:i + self.room] for i in range(0, len(text), self.room)] or [""]
        for piece in pieces:
            if row >= self.rows:
                return row
            self.on_screen.append((row, piece))
            row += 1
        return row

    def newest(self, end, rows_room):
        """Fills the screen and paints the newest lines before `end` that fit in `rows_room` rows."""
        oldest = max(len(self.kept) - KEPT, 0)
        first, used = end, 0
        while first > oldest:
            needed = rows_of(self.kept[first - 1], self.room)
            if used + needed > rows_room:
                break
            used += needed
            first -= 1
        self.on_screen = []
        row = 0
        for number in range(first, end):
            row = self.paint_line(self.kept[number], row)
        self.next_row = row

    def cover(self):
        """The lines cover the screen: at the start, and after F1."""
        self.painted = len(self.kept)
        self.newest(len(self.kept), self.rows)

    def paint_new(self):
        while True:
            number = max(self.painted, len(self.kept) - KEPT)
            if number >= len(self.kept):
                return
            self.painted = number + 1
            if self.next_row + rows_of(self.kept[number], self.room) > self.rows:
                self.jumps += 1
                self.newest(number, self.rows // 2)
            self.next_row = self.paint_line(self.kept[number], self.next_row)

    def picture(self):
        picture = Picture(self.width, self.height)
        picture.fill(BACKGROUND)
        for row, piece in self.on_screen:
            picture.text(MARGIN, MARGIN + row * ROW, piece, SIZE, LETTERS)
        return picture


def start_screen(width, height, lines):
    """The start screen once `lines` (from "Hello from my kernel!" on) were printed and painted."""
    screen = LinesScreen(width, height)
    screen.keep(lines[0])
    screen.cover()
    for line in lines[1:]:
        screen.keep(line)
        screen.paint_new()
    return screen


def view(width, height, lines_before, lines_after=()):
    """The lines after F1: `lines_before` were printed when F1 was pressed, `lines_after` since."""
    screen = LinesScreen(width, height)
    for line in lines_before:
        screen.keep(line)
    screen.cover()
    for line in lines_after:
        screen.keep(line)
        screen.paint_new()
    return screen


def stop_picture(width, height, lines):
    """The stop screen; the last of `lines` is the report."""
    room, rows = place(width, height)
    kept = [clean(line) for line in lines][-KEPT:]
    picture = Picture(width, height)
    picture.fill(STOP_BACKGROUND)
    painted = []

    def paint(text, row):
        pieces = [text[i:i + room] for i in range(0, len(text), room)] or [""]
        for piece in pieces:
            if row >= rows:
                return row
            painted.append((row, piece))
            row += 1
        return row

    row = paint(STOPPED, 0)
    if kept:
        row = paint(kept[-1], row)
    row = paint(BEFORE, row + 1)
    before = kept[:-1]
    first, used = len(before), 0
    while first > 0:
        needed = rows_of(before[first - 1], room)
        if used + needed > max(rows - row, 0):
            break
        used += needed
        first -= 1
    for text in before[first:]:
        row = paint(text, row)
    for row, piece in painted:
        picture.text(MARGIN, MARGIN + row * ROW, piece, SIZE, STOP_LETTERS)
    return picture
