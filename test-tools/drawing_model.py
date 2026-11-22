"""The frame and cells expected on screen, independently painted from
the table's intended contents. The tests give the visible strings and
colours directly, without running a reader or the kernel's contrast check.
"""
from decimal import Decimal
from fractions import Fraction

from picture import CHAT_FRAME, CHAT_MARGIN, CHAT_PADDING, CHAT_ROW_GAP, CHAT_ROWS, CHAT_SIZE, LETTER_HEIGHT, look_of


def table_room(width, height):
    chat_height = (CHAT_ROWS + 1) * (CHAT_SIZE * LETTER_HEIGHT + CHAT_ROW_GAP) + 2 * (CHAT_FRAME + CHAT_PADDING)
    across = width - CHAT_MARGIN - 660 - 26
    down = height - CHAT_MARGIN - chat_height - 100 - 26
    if width < 1000 or across < 127 or down < 85:
        return None
    return (down - 1) // 28 - 2, [(across - 1 - 9 * columns) // 12 for columns in range(1, 7)]


def table(picture, chat, title, widths, head, rows, colours=None, focus=None, editing=False):
    """Paint with fitted data and readable ink. Focus pictures use the light Blue table background."""
    look = look_of(chat)
    colours = colours or {}
    frame, inside, title_ink = (look["panel_frame"], look["panel_inside"], look["panel_text"])
    frame_width = picture.width - 700
    frame_height = picture.height - 320
    picture.rectangle(660, 80, frame_width, frame_height, frame)
    picture.rectangle(663, 83, frame_width - 6, frame_height - 6, inside)
    picture.text(673, 98, title, 2, title_ink)
    spans = [9 + 12 * width for width in widths]
    picture.rectangle(673, 121, sum(spans) + 1, 28 * (1 + len(rows)) + 1, colours.get("lines", frame))
    for number, row in enumerate([head] + rows):
        paper = colours.get("head", frame) if number == 0 else colours.get("rows", inside)
        ink = colours.get("head_ink", title_ink) if number == 0 else colours.get("ink", title_ink)
        x, y = 674, 122 + 28 * number
        for column, (sign, span) in enumerate(zip(row, spans)):
            selected = focus == (number - 1, column)
            fill, text = ((0, 0, 0), paper) if selected else (paper, ink)
            picture.rectangle(x, y, span - 1, 27, fill)
            picture.text(x + 4, y + 4, sign, 2, text)
            if selected and editing:
                picture.rectangle(x + 4 + 12 * len(sign), y + 4, 2, 18, text)
            x += span
    return picture



def bar_chart(picture, chat, title, rows):
    """Horizontal bars from known labels and expected number strings."""
    look = look_of(chat)
    ink, bars = look["panel_text"], look["chat_kernel"]
    frame_width, frame_height = picture.width - 700, picture.height - 320
    picture.rectangle(660, 80, frame_width, frame_height, look["panel_frame"])
    picture.rectangle(663, 83, frame_width - 6, frame_height - 6, look["panel_inside"])
    left, top, width = 673, 93, frame_width - 26
    picture.text(left, top + 5, title[:width // 12], 2, ink)
    digits = max(len(number) for _, number in rows)
    value_size = 2 if digits * 12 <= width // 3 else 1
    value_step = value_size * 6
    label_signs = min(18, max(len(name) for name, _ in rows), (width - digits * value_step - 88) // 12)
    start, end = left + label_signs * 12 + 12, left + width - digits * value_step - 12
    values = [Decimal(number) for _, number in rows]
    low, high = min(0, *values), max(0, *values)
    span = end - start - 1
    if low == 0:
        zero = start
    elif high == 0:
        zero = end - 1
    else:
        zero = start + max(1, min(span - 1, int(-low / (high - low) * span)))
    picture.rectangle(zero, top + 28, 1, len(rows) * 28, ink)
    for index, ((name, number), value) in enumerate(zip(rows, values)):
        y = top + (index + 1) * 28
        if value > 0:
            length = max(1, int(value / high * (end - zero - 1)))
            picture.rectangle(zero + 1, y + 6, length, 16, bars)
        elif value < 0:
            length = max(1, int(value / low * (zero - start)))
            picture.rectangle(zero - length, y + 6, length, 16, bars)
        picture.text(left, y + 5, name[:label_signs], 2, ink)
        picture.text(left + width - len(number) * value_step, y + (28 - value_size * 9) // 2, number, value_size, ink)
    picture.text(left, 80 + frame_height - 13 - 28 + 5, "Tab returns to table", 2, ink)
    return picture


def diagram_picture(picture, chat, edited=False):
    """The three-step flowchart and the edited fixture's edge strokes."""
    look = look_of(chat)
    left, top = 673, 93
    width, height = picture.width - 726, picture.height - 346
    picture.rectangle(660, 80, width + 26, height + 26, look["panel_frame"])
    picture.rectangle(663, 83, width + 20, height + 20, look["panel_inside"])
    ink = (0, 0, 0)  # The pale ink is corrected against the Blue background.

    def rect(x, y, w, h, colour=ink):
        picture.rectangle(left + x, top + y, w, h, colour)

    def stroke(start, end, colour=ink):
        dx, dy = end[0] - start[0], end[1] - start[1]
        steps = max(abs(dx), abs(dy))
        for step in range(steps + 1):
            t = Fraction(step, steps)
            x = start[0] + (1 if dx >= 0 else -1) * int(abs(dx) * t + Fraction(1, 2))
            y = start[1] + (1 if dy >= 0 else -1) * int(abs(dy) * t + Fraction(1, 2))
            rect(x, y, min(2, width - x), min(2, height - y), colour)

    for y in (24, 117, 210):
        rect(56, y, 186, 2)
        rect(56, y + 44, 186, 2)
        rect(56, y, 2, 46)
        rect(240, y, 2, 46)
    for start, end in ((73, 113), (166, 206)):
        stroke((149, start), (149, end))
        stroke((144, end - 10), (149, end))
        stroke((154, end - 10), (149, end))
    label_colour = look["panel_text"]
    picture.text(left + 119, top + 38, "Start", 2, label_colour)
    picture.text(left + 113, top + 131, "Check" if edited else "Review", 2, label_colour)
    picture.text(left + 125, top + 224, "Done", 2, label_colour)
    if edited:
        stroke((292, 416), (297, 421), label_colour)
        stroke((297, 365), (297, 392), label_colour)
        stroke((292, 382), (297, 392), label_colour)
    return picture


def documents_panel(picture, chat, names, active=None, page=1, pages=1):
    """The saved names below the app's output. Supply one page of names."""
    look = look_of(chat)
    left, top, width = 40, 338, 600
    frame, pad, row = 3, 4, 20
    height = picture.height - 240 - top
    room = min(8, (height - 2 * (frame + pad)) // row - 1)
    assert 0 < len(names) <= room
    box_height = 2 * (frame + pad) + (room + 1) * row
    picture.rectangle(left, top, width, box_height, look["panel_frame"])
    picture.rectangle(left + frame, top + frame, width - 2 * frame, box_height - 2 * frame, look["panel_inside"])
    text = [f"Documents: page {page} of {pages}"] + [("> " if name == active else "- ") + name for name in names]
    for index, line in enumerate(text):
        picture.text(left + frame + pad, top + frame + pad + index * row, line, 2, look["panel_text"])
    return picture



def named_document(name, description):
    name = name.encode("ascii")
    return bytes((2, len(name))) + name + description.encode("ascii")
