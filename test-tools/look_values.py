"""The four looks, typed in here by hand from the design (not read from the kernel), and a check of each with the
contrast ratio of WCAG 2 (the Web Content Accessibility Guidelines): how much brighter the lighter of two colours is
than the darker, from 1 (the same) to 21 (black on white). Letters need at least 4.5 against what is behind them
(WCAG's level AA for ordinary text); a frame at least 3 against the screen around it (WCAG's rule for the edges of
things on a screen). Usage: python look_values.py"""

ORDER = ["Blue", "Night", "Paper", "Contrast"]

LOOKS = {
    # Today's look, unchanged.
    "Blue": dict(background=(0, 40, 90), sentence=(255, 255, 255),
                 chat_frame=(255, 150, 0), chat_inside=(232, 236, 244), chat_typing=(255, 255, 255),
                 chat_person=(0, 0, 0), chat_kernel=(0, 60, 140),
                 panel_frame=(255, 150, 0), panel_inside=(240, 240, 240), panel_text=(0, 0, 0)),
    # An almost black screen, dark grey boxes, light letters.
    "Night": dict(background=(18, 18, 24), sentence=(210, 210, 220),
                  chat_frame=(110, 125, 170), chat_inside=(36, 38, 48), chat_typing=(52, 55, 68),
                  chat_person=(240, 240, 240), chat_kernel=(140, 190, 255),
                  panel_frame=(110, 125, 170), panel_inside=(36, 38, 48), panel_text=(240, 240, 240)),
    # A white screen, black letters, grey frames, like a printed page.
    "Paper": dict(background=(246, 244, 236), sentence=(30, 30, 30),
                  chat_frame=(120, 120, 120), chat_inside=(255, 255, 255), chat_typing=(236, 236, 230),
                  chat_person=(0, 0, 0), chat_kernel=(130, 40, 20),
                  panel_frame=(120, 120, 120), panel_inside=(255, 255, 255), panel_text=(0, 0, 0)),
    # A black screen, white and yellow letters, yellow frames.
    "Contrast": dict(background=(0, 0, 0), sentence=(255, 255, 0),
                     chat_frame=(255, 255, 0), chat_inside=(0, 0, 0), chat_typing=(40, 40, 40),
                     chat_person=(255, 255, 255), chat_kernel=(255, 255, 0),
                     panel_frame=(255, 255, 0), panel_inside=(0, 0, 0), panel_text=(255, 255, 255)),
}

# (what, letters or frame, behind it, the least ratio)
PAIRS = [
    ("the sentence on the screen", "sentence", "background", 4.5),
    ("the person's letters in the chat box", "chat_person", "chat_inside", 4.5),
    ("the kernel's letters in the chat box", "chat_kernel", "chat_inside", 4.5),
    ("the letters typed, on the row being typed", "chat_person", "chat_typing", 4.5),
    ("an app's letters in its box", "panel_text", "panel_inside", 4.5),
    ("the chat box's frame against the screen", "chat_frame", "background", 3.0),
    ("the app's box's frame against the screen", "panel_frame", "background", 3.0),
]


def channel(value):
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour):
    r, g, b = (channel(v) for v in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(name):
    look = LOOKS[name]
    out = []
    for what, front, back, least in PAIRS:
        value = ratio(look[front], look[back])
        out.append((what, value, least, value >= least))
    return out


if __name__ == "__main__":
    bad = 0
    for number, name in enumerate(ORDER, 1):
        print("%d %s" % (number, name))
        for what, value, least, ok in check(name):
            print("   %-45s %5.1f  (at least %.1f) %s" % (what, value, least, "" if ok else "TOO LOW"))
            bad += not ok
    print("all pairs readable" if bad == 0 else "%d pairs too low" % bad)
