"""A model of what the chat box should hold and say with the name question, written from the design (not from
the kernel's code), on top of picture.Chat. Also the key names QEMU needs for capitals and signs."""
from picture import Chat, CHAT_LINE_LIMIT, GREETING

NAME_LIMIT = 20
HELLO = "Kernel: hello! I do not know your name yet, so I have one question before we begin."


def question(person):
    return 'Kernel: what should I call you? Type a name and press Enter. Enter alone keeps "%s".' % person


def welcome(name):
    return ("Kernel: welcome back, %s." % name if name else "Kernel: welcome back.") + " Type a line and press Enter."


def recall(line):
    return 'Kernel: last time you said "%s"' % line


def clean_name(data):
    """What the kernel should make of a name read from the disk."""
    signs = "".join(chr(b) if 32 <= b <= 126 else "." for b in data[:NAME_LIMIT])
    return signs.strip(" ")


def clean_line(data):
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data[:CHAT_LINE_LIMIT])


class NamedChat(Chat):
    """notebook: "ready" (can be added to), "damaged" (read only), or None (no notebook at all).
    kept_name: bytes of the newest name entry, or None. last_line: bytes of the newest last line, or None."""

    def __init__(self, screen_width, notebook="ready", kept_name=None, last_line=None):
        super().__init__(screen_width)
        self.name = ""
        self.asking = False
        self.answer_kept = False
        self.can_keep = notebook == "ready"
        self.kept = []        # entries this start should add to the notebook, in order
        self.start_said = []  # the kernel's rows at startup, in the terminal before the hint
        if notebook is None:
            return            # nothing is opened, nothing is said: as before
        start = []
        if kept_name is not None:
            self.name = clean_name(kept_name)
            self.answer_kept = True
            start = [welcome(self.name)]
        elif self.can_keep:
            self.asking = True
            start = [HELLO, question(self.person())]
        recall_row = recall(clean_line(last_line)) if last_line is not None else None
        if recall_row:
            if self.asking:
                start.insert(0, recall_row)
            else:
                start.append(recall_row)
        if start and (kept_name is not None or self.asking):
            self.rows = []    # the greeting or the question takes the place of GREETING
        for row in start:
            self.start_said.append(row)
            self.add("kernel", row)

    def person(self):
        return self.name or "You"

    def line_room(self):
        limit = NAME_LIMIT if self.asking else CHAT_LINE_LIMIT
        if self.room is None:
            return limit
        return min(limit, max(self.room - 3, 0))

    def answer(self, said):
        self.asking = False
        given = said.strip(" ")
        changed = given != ""
        if changed:
            self.name = given
        elif self.answer_kept:
            return 'Kernel: your name stays "%s". Type a line and press Enter.' % self.person()
        if changed:
            opening, what = "Kernel: hello, %s." % given, "your name"
        else:
            opening, what = 'Kernel: I will call you "%s".' % self.person(), "that"
        if self.can_keep:
            self.answer_kept = True
            self.kept.append(("name", self.name.encode()))
            return opening + (" I will remember your name." if changed else "") + " Type a line and press Enter."
        return "%s I could not keep %s, because the notebook cannot be added to, so it lasts only until the machine is switched off." % (opening, what)

    def key(self, sign):
        if self.secret_asked:
            return super().key(sign)
        if sign == "\n" and self.asking:
            said, self.line = self.line, ""
            rows = []
            if said:
                rows.append(("person", "%s: %s" % (self.person(), said)))
            rows.append(("kernel", self.answer(said)))
            for speaker, row in rows:
                self.said.append(row)
                self.add(speaker, row)
            return
        if sign == "\n" and self.line:
            line = self.line
            if line == "setup":
                mine = "%s: setup" % self.person()
                self.asking = True
                answer = question(self.person())
                self.said += [mine, answer]
                self.add("person", mine)
                self.add("kernel", answer)
                self.line = ""
            else:
                super().key(sign)
            if self.can_keep:
                self.kept.append(("last line", line.encode()))
            return
        super().key(sign)


PLAIN = "1234567890-=qwertyuiop[]asdfghjkl;'`\\zxcvbnm,./"
SHIFTED = "!@#$%^&*()_+QWERTYUIOP{}ASDFGHJKL:\"~|ZXCVBNM<>?"
NAMES = {"-": "minus", "=": "equal", "[": "bracket_left", "]": "bracket_right", ";": "semicolon", "'": "apostrophe",
         "`": "grave_accent", "\\": "backslash", ",": "comma", ".": "dot", "/": "slash", " ": "spc", "\n": "ret", "\b": "backspace"}


def name_of(sign):
    if sign in SHIFTED:
        base = PLAIN[SHIFTED.index(sign)]
        return "shift-" + NAMES.get(base, base)
    return NAMES.get(sign, sign)
