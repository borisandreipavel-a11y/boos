"""A model of what the chat box should hold and say with the onboarding's two questions, the name and the key with
its password, written from the design in docs/chat.md (not from the kernel's code), on top of picture.Chat."""
from picture import Chat, CHAT_LINE_LIMIT, STARS_SHOWN, SECRET_LIMIT

NAME_LIMIT = 20
PASSWORD_LEAST = 4
LOCKED = "<a locked key>"   # stands for the bytes of a locked key, which hold random numbers
TYPE_A_LINE = " Type a line and press Enter."
HELLO_ONE = "Kernel: hello! I do not know your name yet, so I have one question before we begin."
HELLO_FEW = "Kernel: hello! I do not know you yet, so I have a few questions before we begin."
KEY_WHY = "Kernel: to ask the model I need your key. I lock it with a password and keep it on the disk."
KEY_QUESTION = "Kernel: type the key and press Enter. It shows as stars. Enter alone goes on without a key."
KEY_QUESTION_AGAIN = "Kernel: type a new key and press Enter. Enter alone keeps the one locked on the disk."
PASSWORD_QUESTION = "Kernel: type your password and press Enter to unlock the key. Enter alone goes on without it."
NO_RANDOM = ["Kernel: I cannot lock a key on this machine, because it cannot make random numbers.",
             'Kernel: send "key" for a key that lasts until the machine is switched off.']
KEY_STAYS = "Kernel: the key locked on the disk stays as it was. Type a line and press Enter."
NO_KEY = 'Kernel: then no key is kept. Send "setup" to give one later. Type a line and press Enter.'
SAME = "Kernel: type the same password again and press Enter."
DIFFER = "Kernel: the two passwords differ. Choose a password again and press Enter."
FOR_THIS_START = "Kernel: then the key is kept for this start only, not on the disk. Type a line and press Enter."
LOCKING = "Kernel: locking the key with your password. This takes a second or two."
LOCKED_ROWS = ["Kernel: the key is locked and kept on the disk. Each start will ask for the password.",
               "Kernel: type a line and press Enter."]
WITHOUT_KEY = 'Kernel: going on without the key. Send "setup" to lock a new one. Type a line and press Enter.'
UNLOCKING = "Kernel: unlocking the key. This takes a second or two."
UNLOCKED = 'Kernel: the key is unlocked, so "ask" works. Type a line and press Enter.'
WRONG = ["Kernel: the key could not be unlocked: the password is wrong, or the locked key was changed.",
         "Kernel: type the password again, or press Enter alone to go on without the key."]
STAR_STEPS = ("key", "trying", "new", "same", "password")

# The try of a key (docs/chat.md, "Trying the key"): what comes of it is given to the model as an outcome,
# (verdict, sentence) with verdict "Works", "Unknown", "Known" or "NotTold", or ("away", reason) when the try
# is turned away before it starts.
TRY_FENCED = ("NotTold", "no answer came, because the network named no name server")
TRY_AWAY = ("away", "this machine has no address on the network")
CANNOT_TELL = "Kernel: so I cannot tell whether the key is right. I keep it all the same."
STILL_TRYING = "Kernel: I am still trying the key. Wait for its answer, then type."
UNKNOWN_KEY = "Kernel: the provider does not know that key, so I did not keep it."
KNOWN_KEY = "Kernel: the provider knows the key, so I keep it."
WORKS = "Kernel: the key works. Now choose a password of at least %d signs to lock it with." % PASSWORD_LEAST
CHOOSE = "Kernel: now choose a password of at least %d signs to lock it with." % PASSWORD_LEAST
NOT_TAKEN = "Kernel: what was typed while I tried the key was not taken."


def signs(count):
    return "sign" if count == 1 else "signs"


def trying(count):
    return "Kernel: I took a key of %d %s, and I am trying it with one question to the model." % (count, signs(count))


def cannot_try(count, reason):
    return "Kernel: I took a key of %d %s, but I cannot try it now, because %s." % (count, signs(count), reason)


def question(person):
    return 'Kernel: what should I call you? Type a name and press Enter. Enter alone keeps "%s".' % person


def recall(line):
    return 'Kernel: last time you said "%s"' % line


def clean_name(data):
    """What the kernel should make of a name read from the disk."""
    signs = "".join(chr(b) if 32 <= b <= 126 else "." for b in data[:NAME_LIMIT])
    return signs.strip(" ")


def clean_line(data):
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data[:CHAT_LINE_LIMIT])


def took(count):
    return "Kernel: I took a key of %d %s. Now choose a password of at least %d signs to lock it with." % (
        count, "sign" if count == 1 else "signs", PASSWORD_LEAST)


def too_short(count):
    return "Kernel: that password has only %d %s, and it needs at least %d. Choose a longer one." % (
        count, "sign" if count == 1 else "signs", PASSWORD_LEAST)


class KeyedChat(Chat):
    """notebook: "ready" (can be added to), "damaged" (read only), or None (no notebook at all).
    kept_name: bytes of the newest name entry, or None. last_line: bytes of the newest last line, or None.
    key_entry: None (no entry for the key), b"" (no key wanted), or LOCKED; password: the one that unlocks it.
    random: whether the machine can make random numbers."""

    def __init__(self, screen_width, notebook="ready", kept_name=None, last_line=None, key_entry=None, password=None,
                 random=True, trouble=None, tries=None, instant=True):
        super().__init__(screen_width)
        self.trouble = trouble         # why the locked key on the disk is refused before any password is tried
        self.tries = list(tries) if tries is not None else None   # outcomes of the tries, in turn; None: always TRY_FENCED
        self.instant = instant         # the answer to a try is there before the next key (else the test calls tried())
        self.pending = None            # the key being tried and the outcome its try will have
        self.name = ""
        self.waiting = None
        self.setting_up = False
        self.name_kept = False
        self.can_keep = notebook == "ready"
        self.random = random
        self.key_entry = key_entry
        self.password = password       # the password that unlocks the locked key on the disk
        self.first = None              # a new password typed once
        self.typed = ""                # what is typed as stars for the onboarding
        self.key_in_memory = None      # the key this start holds, as far as the model knows it
        self.kept = []                 # entries this start should add to the notebook, in order
        self.start_said = []           # the kernel's rows at startup, in the terminal before the hint
        if notebook is None:
            return                     # nothing is opened, nothing is said: as before
        start = []
        if kept_name is not None:
            self.name = clean_name(kept_name)
            self.name_kept = True
            greeting = "Kernel: welcome back, %s." % self.name if self.name else "Kernel: welcome back."
            start = self.then_key([greeting])
        elif self.can_keep:
            hello = HELLO_FEW if self.more_follows() else HELLO_ONE
            self.waiting = "name"
            start = [hello, question(self.person())]
        else:
            start = self.key_rows()
        if start:
            self.rows = []             # the onboarding's rows take the place of GREETING; the recall row alone does not
        recall_row = recall(clean_line(last_line)) if last_line is not None else None
        if recall_row:
            if self.waiting:
                start.insert(0, recall_row)
            else:
                start.append(recall_row)
        for row in start:
            self.start_said.append(row)
            self.add("kernel", row)

    # ---- the design's steps ----

    def person(self):
        return self.name or "You"

    def done(self):
        self.waiting = None
        self.setting_up = False

    def more_follows(self):
        if self.key_entry == LOCKED:
            return True
        if self.key_entry == b"":
            return False
        return self.can_keep and self.random

    def then_key(self, rows):
        following = self.key_rows()
        if following:
            return rows + following
        return rows[:-1] + [rows[-1] + TYPE_A_LINE]

    def key_rows(self):
        if self.key_entry == LOCKED and not self.setting_up:
            self.waiting = "password"
            return [PASSWORD_QUESTION]
        if self.key_entry == b"" and not self.setting_up:
            self.done()
            return []
        if not self.can_keep:
            self.done()
            return []
        if not self.random:
            self.done()
            return list(NO_RANDOM)
        self.waiting = "key"
        if self.setting_up and self.key_entry == LOCKED:
            return [KEY_QUESTION_AGAIN]
        return [KEY_WHY, KEY_QUESTION]

    def key_question(self):
        return KEY_QUESTION_AGAIN if self.setting_up and self.key_entry == LOCKED else KEY_QUESTION

    def next_try(self):
        if self.tries is None:
            return TRY_FENCED
        return self.tries.pop(0)

    def tried_rows(self):
        """What the kernel says when the answer to the try comes."""
        typed, (verdict, sentence) = self.pending
        self.pending = None
        rows = ["Kernel: " + sentence]
        if verdict == "Unknown":
            self.waiting = "key"
            return rows + [UNKNOWN_KEY, self.key_question()]
        self.key_in_memory = typed
        self.secret_held = True
        self.waiting = "new"
        if verdict == "Works":
            return rows + [WORKS]
        if verdict == "Known":
            return rows + [KNOWN_KEY, CHOOSE]
        return rows + [CANNOT_TELL, CHOOSE]

    def tried(self):
        """The answer to a try came (for a model made with instant=False)."""
        rows = self.tried_rows()
        if getattr(self, "dropped", False):
            self.dropped = False
            rows.insert(0, NOT_TAKEN)
        for row in rows:
            self.said.append(row)
            self.add("kernel", row)

    def answer_name(self, said):
        self.waiting = None
        given = said.strip(" ")
        changed = given != ""
        if changed:
            self.name = given
        elif self.name_kept:
            return self.then_key(['Kernel: your name stays "%s".' % self.person()])
        if changed:
            opening, what = "Kernel: hello, %s." % given, "your name"
        else:
            opening, what = 'Kernel: I will call you "%s".' % self.person(), "that"
        if self.can_keep:
            self.name_kept = True
            self.kept.append(("name", self.name.encode()))
            return self.then_key([opening + (" I will remember your name." if changed else "")])
        rows = ["%s I could not keep %s, because the notebook cannot be added to, so it lasts only until the machine is switched off." % (opening, what)]
        return rows + self.key_rows()

    def no_key_noted(self):
        if self.key_entry is None:
            self.key_entry = b""
            self.kept.append(("locked key", b""))
        return []

    def for_this_start(self):
        self.first = None
        self.done()
        return [FOR_THIS_START] + self.no_key_noted()

    def answer_secret(self, typed):
        step = self.waiting
        if step == "key":
            if typed == "":
                self.done()
                if self.key_entry == LOCKED:
                    return [KEY_STAYS]
                return [NO_KEY] + self.no_key_noted()
            outcome = self.next_try()
            if outcome[0] == "away":
                self.key_in_memory = typed
                self.secret_held = True
                self.waiting = "new"
                return [cannot_try(len(typed), outcome[1]), CANNOT_TELL, CHOOSE]
            self.waiting = "trying"
            self.pending = (typed, outcome)
            rows = [trying(len(typed))]
            if self.instant:
                rows += self.tried_rows()
            return rows
        if step == "trying":
            return [STILL_TRYING]
        if step == "new":
            if typed == "":
                return self.for_this_start()
            if len(typed) < PASSWORD_LEAST:
                return [too_short(len(typed))]
            self.first = typed
            self.waiting = "same"
            return [SAME]
        if step == "same":
            if typed == "":
                return self.for_this_start()
            if typed != self.first:
                self.first = None
                self.waiting = "new"
                return [DIFFER]
            self.tell(LOCKING)
            self.first = None
            self.done()
            self.key_entry = LOCKED
            self.password = typed
            self.locked_key_text = self.key_in_memory
            self.kept.append(("locked key", LOCKED))
            return list(LOCKED_ROWS)
        if step == "password":
            if typed == "":
                self.done()
                return [WITHOUT_KEY]
            self.tell(UNLOCKING)
            if self.trouble:
                self.done()
                return ["Kernel: I cannot unlock the key kept on the disk, because %s." % self.trouble,
                        'Kernel: send "setup" to lock a new one. Type a line and press Enter.']
            if typed == self.password:
                self.done()
                self.secret_held = True
                return [UNLOCKED]
            return list(WRONG)
        return []

    # ---- keys ----

    def tell(self, row):
        """A row the kernel says before it begins a long piece of work."""
        self.said.append(row)
        self.add("kernel", row)

    def line_room(self):
        limit = NAME_LIMIT if self.waiting == "name" else CHAT_LINE_LIMIT
        if self.room is None:
            return limit
        return min(limit, max(self.room - 3, 0))

    def typing_text(self):
        if self.waiting in STAR_STEPS and not self.secret_asked:
            text = "> " + "*" * min(len(self.typed), STARS_SHOWN)
            if len(self.typed) > STARS_SHOWN:
                text += " and %d more" % (len(self.typed) - STARS_SHOWN)
            return text + "_"
        return super().typing_text()

    def key(self, sign):
        if self.secret_asked:
            return super().key(sign)
        if self.waiting in STAR_STEPS:
            if self.waiting == "trying" and sign != "\n":
                self.dropped = True    # nothing typed is taken while a key is tried
                return
            if sign == "\b":
                self.typed = self.typed[:-1]
            elif sign == "\n":
                typed, self.typed = self.typed, ""
                for row in self.answer_secret(typed):
                    self.said.append(row)
                    self.add("kernel", row)
            elif len(self.typed) < SECRET_LIMIT:
                self.typed += sign
            return
        if sign == "\n" and self.waiting == "name":
            said, self.line = self.line, ""
            rows = []
            if said:
                rows.append(("person", "%s: %s" % (self.person(), said)))
            rows += [("kernel", row) for row in self.answer_name(said)]
            for speaker, row in rows:
                self.said.append(row)
                self.add(speaker, row)
            return
        if sign == "\n" and self.line:
            line = self.line
            if line == "setup":
                mine = "%s: setup" % self.person()
                self.setting_up = True
                self.waiting = "name"
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
