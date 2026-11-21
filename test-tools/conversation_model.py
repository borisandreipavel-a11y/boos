"""What the kernel remembers of the conversation, worked out from the notes apart from the kernel's code
(docs/tools.md, "What the model remembers"): the last 10 lines that went to the model, each as it was sent with the
key starred ("Person: ..."), with the rows its answer brought ("Model: ..." and "Kernel: ..."), never more than 8,000
bytes with a line end after each row, the oldest lines going first. The tool `forget` and the line `setup` forget it
all. picture.Chat keeps one of these: a line that goes to the model takes the record as it stands (Chat.records), and
the next row said by the kernel (Chat.say, Chat.row) begins the line's piece of the conversation, since every answer to
a line brings at least one row. Nothing runs when this file is imported."""
from app_cases import hide

LINES_REMEMBERED = 10
BYTES_REMEMBERED = 8000

# What the kernel says when the model asks for the tool `forget`. It forgets first, so this row is not remembered.
FORGOT = "Kernel: I forgot what was said so far. The next line starts afresh."


class Memory:
    def __init__(self, key=""):
        self.exchanges = []    # oldest first; each a list of rows, the person's line first
        self.open = False      # whether rows said now belong to the newest line
        self.waiting = None    # a line that went to the model, whose answer has not come yet
        self.key = key         # the key, starred in a line as it is sent (set by a test whose lines hold it)

    def sent(self, line):
        """A line goes to the model: gives back the record it goes with, and waits for its answer."""
        self.waiting = line
        return self.record()

    def answered(self, row):
        """A row the kernel says: the first after a line went begins that line's piece of the conversation."""
        if self.waiting is not None:
            self.line(self.waiting)
            self.waiting = None
        self.row(row)

    def line(self, line):
        self.exchanges.append(["Person: " + hide(line, self.key)])
        self.exchanges = self.exchanges[-LINES_REMEMBERED:]
        self.open = self.fit()

    def row(self, row):
        if row == FORGOT:
            self.forget()
            return
        if not self.open:
            return
        self.exchanges[-1].append(row)
        self.open = self.fit()

    def fit(self):
        while self.exchanges and sum(len(row.encode()) + 1 for rows in self.exchanges for row in rows) > BYTES_REMEMBERED:
            self.exchanges.pop(0)
        return bool(self.exchanges)

    def forget(self):
        self.exchanges = []
        self.open = False
        self.waiting = None

    def record(self):
        return "\n".join(row for rows in self.exchanges for row in rows)
