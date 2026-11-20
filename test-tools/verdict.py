"""The list of what went wrong in a test. A test adds to it as before; each entry is also printed at once, on a line
of its own that begins with "FAILED: ", so that run_tests.py sees the first failure the moment it happens. It stops a
break on purpose there: one failure is enough to show that the break is caught. The test's own last line,
`FAILURES: none` or the list, stays as it was."""


class Failures(list):
    def append(self, entry):
        super().append(entry)
        print("FAILED: %s" % (entry,), flush=True)

    def extend(self, entries):
        for entry in entries:
            self.append(entry)

    def __iadd__(self, entries):
        self.extend(entries)
        return self
