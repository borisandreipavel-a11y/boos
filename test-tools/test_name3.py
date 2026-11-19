"""The name question, now followed by the question for the key: the name question's scenarios, with Enter alone
given wherever the key is asked for. Every picture against the model, the terminal's lines, and the notebook.
Usage: python test_name3.py [scenario ...]   (default: all)"""
import sys

from keyed_model import KeyedChat
from nb import BLOCK, put_block, put_notebook
from start_helper import Start, failures, fresh_disk


def first():
    disk = fresh_disk("name3-first")
    s = Start("first", disk, KeyedChat(1280))
    s.look("1-question")
    s.keys("Ada")
    s.look("2-typing-the-name")
    s.keys("\n")
    s.look("3-named-then-key")
    s.keys("\n")
    s.look("4-no-key")
    s.keys("hello\n")
    s.look("5-a-line")
    s.end()

    s = Start("first-2", disk, KeyedChat(1280, kept_name=b"Ada", last_line=b"hello", key_entry=b""))
    s.look("1-welcome-back")
    s.keys("hi\n")
    s.keys("setup\n")
    s.look("2-setup-asks")
    s.keys("Bea Lee\n")
    s.look("3-renamed-then-key")
    s.keys("\n")
    s.keys("x\n")
    s.keys("setup\n\n")
    s.look("4-name-stays-then-key")
    s.keys("\n")
    s.look("5-no-key-again")
    s.end()

    s = Start("first-3", disk, KeyedChat(1280, kept_name=b"Bea Lee", last_line=b"setup", key_entry=b""))
    s.look("1-welcome-back-renamed")
    s.end()


def enter_alone():
    disk = fresh_disk("name3-enter")
    s = Start("enter", disk, KeyedChat(1280))
    s.keys("\n")
    s.look("1-stays-you-then-key")
    s.keys("\n")
    s.keys("yo\n")
    s.look("2-a-line")
    s.end()
    s = Start("enter-2", disk, KeyedChat(1280, kept_name=b"", last_line=b"yo", key_entry=b""))
    s.look("1-welcome-back-no-name")
    s.keys("setup\n\n")
    s.look("2-stays-then-key")
    s.keys("\n")
    s.end()


def limit_and_spaces():
    disk = fresh_disk("name3-limit")
    s = Start("limit", disk, KeyedChat(1280))
    s.keys("abcdefghijklmnopqrstuvwxy")
    s.look("1-twenty-taken")
    s.keys("\n\n")
    s.keys("setup\n")
    s.keys("  Cy  \n\n")
    s.keys("setup\n")
    s.keys("   \n\n")
    s.look("2-trimmed-and-spaces")
    s.keys("a line of fifty signs, typed after the name, 0123456789\n")
    s.look("3-line-limit-back")
    s.end()


def no_notebook():
    disk = fresh_disk("name3-none", divided=False)
    raw = open(disk, "rb").read()
    s = Start("none", disk, KeyedChat(1280, notebook=None))
    s.look("1-as-before")
    s.keys("setup\n")
    s.look("2-asks-anyway")
    s.keys("Dee\n")
    s.keys("z\n")
    s.look("3-not-kept-no-key-asked")
    s.end()
    if open(disk, "rb").read() != raw:
        failures.append("none: the undivided disk changed")
        print("  none: THE UNDIVIDED DISK CHANGED")


def upgrade():
    """A notebook from before the questions: lines kept, no name, no key. The first start of the new kernel asks."""
    disk = fresh_disk("name3-upgrade")
    put_notebook(disk, [("last line", b"older"), ("last line", b"from before")])
    s = Start("upgrade", disk, KeyedChat(1280, last_line=b"from before"))
    s.look("1-recall-then-question")
    s.keys("Ivo\n")
    s.look("2-named-then-key")
    s.keys("\n")
    s.end()
    s = Start("upgrade-2", disk, KeyedChat(1280, kept_name=b"Ivo", last_line=b"from before", key_entry=b""))
    s.look("1-welcome-then-recall")
    s.end()


def unanswered():
    """A start that is switched off while the question waits: the next start asks again."""
    disk = fresh_disk("name3-unanswered")
    s = Start("unanswered", disk, KeyedChat(1280))
    s.keys("Ju")   # typed, never sent
    s.look("1-half-typed")
    s.end()
    s = Start("unanswered-2", disk, KeyedChat(1280))
    s.look("1-asks-again")
    s.end()


def odd_name():
    disk = fresh_disk("name3-odd")
    put_notebook(disk, [("last line", b"old line"), ("name", b"\x01Zed\xff" + b"0123456789ABCDEFGHIJKLMNOP")])
    s = Start("odd", disk, KeyedChat(1280, kept_name=b"\x01Zed\xff0123456789ABCDEFGHIJKLMNOP", last_line=b"old line"))
    s.look("1-cleaned-and-cut-then-key")
    s.keys("\n")
    s.keys("q\n")
    s.end()
    disk = fresh_disk("name3-blank")
    put_notebook(disk, [("name", b"Old"), ("name", b"   "), ("locked key", b"")])
    s = Start("blank", disk, KeyedChat(1280, kept_name=b"   ", key_entry=b""))
    s.look("1-blank-name-is-you")
    s.end()


def damaged():
    disk = fresh_disk("name3-damaged")
    put_notebook(disk, [("last line", b"before")])
    put_block(disk, 5, b"junk".ljust(BLOCK, b"\0"))
    s = Start("damaged", disk, KeyedChat(1280, notebook="damaged", last_line=b"before"))
    s.damaged = True
    s.look("1-no-question")
    s.keys("setup\n")
    s.keys("Eve\n")
    s.look("2-cannot-keep")
    s.end()
    disk = fresh_disk("name3-damaged-named")
    put_notebook(disk, [("name", b"Fay")])
    put_block(disk, 4, b"junk".ljust(BLOCK, b"\0"))
    s = Start("damaged-named", disk, KeyedChat(1280, notebook="damaged", kept_name=b"Fay"))
    s.damaged = True
    s.look("1-welcome-back")
    s.end()


def small_screen():
    disk = fresh_disk("name3-small")
    s = Start("small", disk, KeyedChat(800), width=800, height=600, extra=["-vga", "cirrus"])
    s.look("1-question-wraps")
    s.keys("Gus Grimsby-Hartwell\n")
    s.look("2-named-key-rows-wrap")
    s.keys("\n")
    s.keys("setup\n")
    s.look("3-long-name-in-question")
    s.keys("\n")
    s.look("4-key-question-again")
    s.keys("\n")
    s.end()


def no_screen():
    disk = fresh_disk("name3-noscreen")
    s = Start("noscreen", disk, KeyedChat(None), width=None, extra=["-vga", "none"])
    s.keys("Hal\n")
    s.keys("\n")
    s.keys("hey\n")
    s.end()
    s = Start("noscreen-2", disk, KeyedChat(None, kept_name=b"Hal", last_line=b"hey", key_entry=b""), width=None, extra=["-vga", "none"])
    s.end()


SCENARIOS = dict(first=first, enter=enter_alone, limit=limit_and_spaces, none=no_notebook, upgrade=upgrade, unanswered=unanswered, odd=odd_name,
                 damaged=damaged, small=small_screen, noscreen=no_screen)
if __name__ == "__main__":
    for name in sys.argv[1:] or list(SCENARIOS):
        print(name)
        SCENARIOS[name]()
    print("FAILURES:", failures if failures else "none")
