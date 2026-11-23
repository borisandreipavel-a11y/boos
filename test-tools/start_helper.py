"""One boot of the kernel with a given disk, driven key by key and checked against a model of the chat box: every
picture dot by dot, the terminal's rows, and the entries the start added to the notebook, read from outside.
A locked key in the notebook is opened from outside with the model's password and must give the model's key."""
import os
import time

from boot import Machine
from disk_helpers import make, one_disk
from gpt import build
from keyed_model import LOCKED
from keyref import head_facts, unlock
from nb import BLOCK, read_notebook
from onboard_model import name_of
from picture import compare, expected, to_png
from verdict import Failures

failures = Failures()


def fresh_disk(name, divided=True):
    path = make(name + ".img", "16M")
    if divided:
        build(path)
    return path


class Start:
    def __init__(self, tag, disk, chat, width=1280, height=800, extra=None, kernel=None, network=True):
        self.tag, self.disk, self.chat, self.width, self.height = tag, disk, chat, width, height
        self.before = read_notebook(disk)["entries"] if disk else []
        self.raw_before = open(disk, "rb").read() if disk else None
        # A model that leaves the look to the disk learns, from the notebook read from outside, what it holds
        # under "look" before this start.
        if not getattr(chat, "begun", True):
            looks = [data for name, data in self.before if name == "look"]
            chat.begin(looks[-1] if looks else None)
        options = {"kernel": kernel} if kernel else {}
        self.m = Machine(tag, extra=(one_disk(disk) if disk else []) + (extra or []), disk=False, network=network, **options)
        if not self.m.wait_for(b"repeated here:", 150):
            print(tag, "THE HINT NEVER CAME")
            print(self.m.serial().decode(errors="replace")[-3000:])
            failures.append(tag + " boot")
            self.m.quit()
            raise SystemExit(1)
        # A key typed before the machine has its address cannot be tried; wait for it, so that every run is alike.
        if network and not self.m.wait_for(b"Network: this machine was given the address", 60):
            print(tag, "NO ADDRESS")
            failures.append(tag + " address")
        # A test about other things answers the question for a look with Enter alone (see keyed_model.py).
        if getattr(chat, "auto_look", False) and getattr(chat, "look_asking", False):
            self.keys("\n")

    def mark(self):
        """Remembers how much the kernel has printed, for wait_text."""
        self.at = len(self.m.serial())

    def wait_text(self, *texts, timeout=150):
        """Waits until one of `texts` stands in what the kernel printed after the last mark()."""
        end = time.time() + timeout
        while time.time() < end:
            later = self.m.serial()[self.at:]
            if any(text.encode() in later for text in texts):
                time.sleep(0.3)
                return True
            time.sleep(0.1)
        print("  %-38s %s" % (self.tag, "WAITED IN VAIN FOR %r" % (texts,)))
        failures.append(self.tag + " waited for %r" % (texts,))
        return False

    def key_tried(self, text, timeout=150):
        """Types a key that ends in Enter, and waits until the answer to its try has come."""
        self.mark()
        self.keys(text)
        return self.wait_text("choose a password", "does not know that key", timeout=timeout)

    def keys(self, text, pause=0.2):
        for sign in text:
            self.m.command("sendkey %s 20" % name_of(sign))
            # Keys with Shift are four key numbers each and pile up inside QEMU when sent quickly.
            time.sleep(pause + (0.05 if name_of(sign).startswith("shift-") else 0))
            asking = getattr(self.chat, "look_asking", False)
            self.chat.key(sign)
            # The question for a look has just appeared: a test about other things answers it with Enter alone.
            if getattr(self.chat, "auto_look", False) and self.chat.look_asking and not asking:
                self.keys("\n", pause)

    def wait(self, seconds):
        """For work the kernel does after Enter, such as turning a password into a key. Waits `seconds`, and then,
        for at most a minute more, until the last row the model expects has come in the terminal: such work takes
        longer while other work runs on the computer."""
        time.sleep(seconds)
        if self.chat.said:
            last = self.chat.said[-1].encode()
            end = time.time() + 60
            while time.time() < end and last not in self.m.serial():
                time.sleep(0.2)

    def look(self, name):
        if self.width is None:
            return
        time.sleep(0.7)
        meant = expected(self.width, self.height, self.chat)
        # Painting the whole screen again in another look takes a quarter of a second, and longer while other work
        # runs on the computer: a picture saved in the middle of it is saved again, up to four more times, half a
        # second apart, before it counts as wrong.
        for _ in range(5):
            path = self.m.shot(name)
            wrong, places = compare(path, meant)
            if wrong == 0:
                break
            time.sleep(0.5)
        print("  %-38s %s" % (self.tag + " " + name, "every dot right" if wrong == 0 else "%d dots wrong %s" % (wrong, places[:2])))
        if wrong:
            failures.append(self.tag + " " + name)
            to_png(path, path[:-4] + ".png")

    def end(self, secrets=()):
        """`secrets`: texts that must not stand in the terminal or the disk file, whole or in pieces of six."""
        time.sleep(0.5)
        serial = self.m.quit()
        ours = serial[serial.find(b"Hello from my kernel!"):]
        text = ours.decode(errors="replace")
        lines = text.split("\r\n")
        odd = [b for b in ours if not (32 <= b <= 126 or b in (13, 10))]
        bare = ours.replace(b"\r\n", b"")
        problems = []
        if odd or b"\r" in bare or b"\n" in bare:
            problems.append("bytes that are not plain text or stray line ends")
        if any(l.startswith(("Kernel panic", "CPU fault")) for l in lines):
            problems.append("a panic or a fault")
        hint = next(i for i, l in enumerate(lines) if l.startswith("The processor rested"))
        begin = max([i for i, l in enumerate(lines[:hint]) if l.startswith("Disk:")] + [-1]) + 1
        start_rows = [l for l in lines[begin:hint] if l.startswith("Kernel:")]
        if start_rows != self.chat.start_said:
            problems.append("startup rows %r, meant %r" % (start_rows, self.chat.start_said))
        # The terminal's lines about the network, about the tokens an answer took and about how its pieces came are no
        # rows of the chat box.
        said = [l for l in lines[hint + 2:] if l and not l.startswith(("Network:", "Tokens:", "Stream:"))]
        if said != self.chat.said:
            problems.append("the lines said are not as meant")
            print("    meant:", self.chat.said[-5:])
            print("    got:  ", said[-5:])
        disk_bytes = open(self.disk, "rb").read() if self.disk else b""
        for secret in secrets:
            pieces = [secret[i:i + 6].encode() for i in range(max(len(secret) - 5, 1))]
            if any(p in serial for p in pieces):
                problems.append("a piece of %r in the terminal" % secret[:4])
            if any(p in disk_bytes for p in pieces):
                problems.append("a piece of %r on the disk" % secret[:4])
        if self.disk:
            after = read_notebook(self.disk)
            if self.raw_before[:2048 * BLOCK] != disk_bytes[:2048 * BLOCK]:
                problems.append("the disk changed outside the kernel's part")
            added = after["entries"][len(self.before):] if after["entries"][:len(self.before)] == self.before else None
            if added is None:
                problems.append("the notebook's earlier entries changed")
            elif [n for n, _ in added] != [n for n, _ in self.chat.kept]:
                problems.append("notebook got %r, meant %r" % ([n for n, _ in added], [n for n, _ in self.chat.kept]))
            else:
                for (name, data), (_, meant) in zip(added, self.chat.kept):
                    if meant == LOCKED and len(data) < 34:
                        problems.append("entry %r holds %d bytes where a locked key is meant" % (name, len(data)))
                    elif meant == LOCKED:
                        version, way, rounds, _, _ = head_facts(data)
                        opened = unlock(self.chat.password.encode(), data)
                        meant_key = getattr(self.chat, "locked_key_text", None) or self.chat.key_in_memory
                        if (version, way, rounds) != (1, 1, 600000) or opened != meant_key.encode():
                            problems.append("the locked key does not open to the key typed (%d, %d, %d)" % (version, way, rounds))
                    elif data != meant:
                        problems.append("entry %r holds %r, meant %r" % (name, data[:30], meant[:30]))
            if not self.chat.can_keep and after["entries"] != self.before:
                problems.append("the notebook changed although it cannot be added to")
            if after["behind"] and not getattr(self, "damaged", False):
                problems.append("something behind the notebook's end: %r" % after["behind"][:3])
        print("  %-38s %s" % (self.tag + " terminal and disk", "as meant" if not problems else problems))
        if problems:
            failures.append(self.tag + " terminal/disk")
        return lines
