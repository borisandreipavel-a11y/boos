"""The model for `setup` bringing back the first look (docs/chat.md, "Picking a look"), on top of look_model.LookChat,
written from the design, not from the kernel's code. When the line `setup` is taken (while nothing waits), the first
look is put in use at once and the whole screen is painted again in it. If the notebook holds another look, an entry
with no signs is kept under "look" at once, before the line itself is kept as the last line. If that entry cannot be
written, two rows say so when the questions of `setup` are over: before the question for a look when it is asked, or
else as the last rows, the second ending with the words that say the chat box is free."""
from keyed_model import CANNOT_ADD, TYPE_A_LINE, look_named
from look_model import LookChat


def reset_rows(name, reason=CANNOT_ADD):
    """The two rows when `setup` cannot keep the first look; `name` is the look the notebook still holds."""
    return ["Kernel: I could not keep look 1, Blue, on the disk, because %s." % reason,
            "Kernel: so the next start shows %s, again." % look_named(name)]


class ResetChat(LookChat):
    def __init__(self, screen_width, **options):
        # Set before the start's rows are worked out, which may already end the questions (finish).
        self.reset_said = []           # rows to say when the questions of `setup` are over
        super().__init__(screen_width, **options)

    def key(self, sign):
        # The line `setup` is taken as such only while nothing waits: no secret, no question of the onboarding's,
        # no question for a look (as in keyed_model.KeyedChat.key).
        if (sign == "\n" and self.line == "setup" and not self.secret_asked and self.waiting is None
                and not self.look_asking):
            self.look = "Blue"
            if self.look_kept not in (None, "Blue"):
                if self.can_keep:
                    self.kept.append(("look", b""))
                    self.look_kept = None
                    self.look_answered = True
                else:
                    self.reset_said = reset_rows(self.look_kept)
        super().key(sign)

    def finish(self, rows):
        said, self.reset_said = self.reset_said, []
        asked = self.look_due(self.setting_up)
        rows = super().finish(rows)
        if not said:
            return rows
        if asked:
            return rows[:-1] + said + rows[-1:]
        return rows + said[:-1] + [said[-1] + TYPE_A_LINE]
