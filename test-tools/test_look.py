"""Picking a look: with the line `look`, and as the onboarding's question once its questions about the key are over.
Every picture against the model (look_model.py, the onboarding's model with the look), the terminal's lines, and the
notebook read from outside, across starts on the same disk.
Usage: python test_look.py [scenario ...]   (default: all)"""
import os
import sys

from keyed_model import LOCKED
from lockref import lock
from look_model import LookChat
from nb import BLOCK, put_block, put_notebook
from start_helper import Start, failures, fresh_disk

KEY = "sk-orca-TEST_Look-Made-Up-Key-4321"
PW = "green door"


def locked_from_outside(password=PW, key=KEY, rounds=600000):
    return lock(password.encode(), key.encode(), os.urandom(16), os.urandom(12), rounds)


def pick():
    """A first start on a new disk: a name, Enter alone at the key, and the onboarding's question for a look; every
    number shown at once; Night kept. The next start in Night; there `look` and Enter alone keep nothing, and then
    Paper is kept; a third start in Paper."""
    disk = fresh_disk("look-pick")
    s = Start("pick-1", disk, LookChat(1280))
    s.look("1-name-question")
    s.keys("Ada\n")
    s.keys("\n")                 # Enter alone at the key: no key, and the question for a look follows
    s.look("2-list-from-the-onboarding")
    s.keys("2\n")
    s.look("3-night")
    s.keys("3\n")
    s.look("4-paper")
    s.keys("4\n")
    s.look("5-contrast")
    s.keys("1\n")
    s.look("6-blue-again")
    s.keys("2\n")
    s.keys("\n")
    s.look("7-night-kept")
    s.keys("hello\n")
    s.look("8-a-line-in-night")
    s.end()

    s = Start("pick-2", disk, LookChat(1280, kept_name=b"Ada", key_entry=b"", last_line=b"hello", kept_look=b"Night"))
    s.look("1-next-start-in-night-no-question")
    s.keys("look\n")
    s.keys("\n")                 # Enter alone: Night stays, nothing more is kept
    s.look("2-stays")
    s.keys("look\n")
    s.keys("3\n")
    s.keys("\n")                 # another look kept at a later start: a second entry under "look"
    s.look("3-paper-kept")
    s.end()

    s = Start("pick-3", disk, LookChat(1280, kept_name=b"Ada", key_entry=b"", last_line=b"look", kept_look=b"Paper"))
    s.look("1-third-start-in-paper")
    s.end()


def at_once():
    """Enter alone at once at the onboarding's question: look 1 stays, an entry with no signs notes the answer, and
    the next start asks nothing."""
    disk = fresh_disk("look-at-once")
    s = Start("at-once-1", disk, LookChat(1280))
    s.keys("Bo\n")
    s.keys("\n")
    s.keys("\n")
    s.look("1-blue-stays")
    s.end()
    s = Start("at-once-2", disk, LookChat(1280, kept_name=b"Bo", key_entry=b"", kept_look=b""))
    s.look("1-no-question")
    s.end()


def his():
    """A disk like one from before the look: a name, a locked key and lines, nothing about the look. The start asks
    for the password, and then for a look; the next start asks only for the password, in the look kept."""
    disk = fresh_disk("look-his")
    put_notebook(disk, [("last line", b"a line"), ("name", b"Dee"), ("locked key", locked_from_outside()),
                        ("last line", b"before the look")])
    s = Start("his-1", disk, LookChat(1280, kept_name=b"Dee", key_entry=LOCKED, password=PW, last_line=b"before the look"))
    s.look("1-password-question")
    # Unlocking takes a second or more: wait for the question that follows it, not for a fixed time.
    s.mark()
    s.keys(PW + "\n")
    s.wait_text("pick a look by number")
    s.look("2-unlocked-then-the-question")
    s.keys("3\n")
    s.look("3-paper")
    s.keys("\n")
    s.look("4-paper-kept")
    s.end(secrets=[KEY, PW])

    s = Start("his-2", disk, LookChat(1280, kept_name=b"Dee", key_entry=LOCKED, password=PW, last_line=b"before the look",
                                      kept_look=b"Paper"))
    s.look("1-password-question-in-paper")
    s.keys("\n")                 # Enter alone at the password: on without the key, and no question for a look
    s.look("2-without-the-key")
    s.end(secrets=[KEY, PW])


def setup():
    """`setup` asks for a look again after the name and the key, even when one is kept."""
    disk = fresh_disk("look-setup")
    put_notebook(disk, [("name", b"Fay"), ("locked key", b""), ("look", b"Night")])
    s = Start("setup-1", disk, LookChat(1280, kept_name=b"Fay", key_entry=b"", kept_look=b"Night"))
    s.keys("setup\n")
    s.keys("\n")                 # the name stays
    s.keys("\n")                 # no key
    s.look("1-question-after-setup")
    s.keys("\n")                 # Enter alone at once: Night stays, nothing written
    s.look("2-night-stays")
    s.keys("setup\n")
    s.keys("\n")
    s.keys("\n")
    s.keys("4\n")
    s.keys("\n")
    s.look("3-contrast-kept")
    s.end()
    s = Start("setup-2", disk, LookChat(1280, kept_name=b"Fay", key_entry=b"", last_line=b"setup", kept_look=b"Contrast"))
    s.look("1-in-contrast")
    s.end()


def no_random():
    """No random numbers: no key can be locked, so the question for a look follows the two rows that say so."""
    disk = fresh_disk("look-norandom")
    s = Start("norandom", disk, LookChat(1280, random=False), extra=["-cpu", "qemu64"])
    s.look("1-a-few-questions")
    s.keys("Kay\n")
    s.look("2-no-random-then-the-question")
    s.keys("4\n")
    s.keys("\n")
    s.look("3-contrast-kept")
    s.end()


def stays():
    """Numbers that are not on the list, back to the first look, and keeping a look the notebook already holds,
    with the line `look`, after the onboarding's question was answered with Enter alone."""
    disk = fresh_disk("look-stays")
    put_notebook(disk, [("name", b"Bea"), ("locked key", b"")])
    s = Start("stays", disk, LookChat(1280, kept_name=b"Bea", key_entry=b""))
    s.look("1-question-at-startup")
    s.keys("\n")                 # the onboarding's question: look 1 stays, and an entry with no signs is kept
    s.keys("look\n")
    s.keys("\n")                 # nothing tried: look 1 stays, nothing written
    s.look("2-stays-at-once")
    s.keys("look\n")
    s.keys("7\n")
    s.keys("x\n")
    s.keys("0\n")
    s.keys("-2\n")
    s.look("3-not-numbers")
    s.keys(" 3 \n")              # spaces at either end do not count
    s.look("4-paper-tried")
    s.keys("99999999999999999999999\n")
    s.keys("01\n")               # a nought in front still makes 1
    s.look("5-blue-tried")
    s.keys("\n")                 # tried, and the notebook holds no look: Blue is kept
    s.look("6-blue-kept")
    s.keys("look\n")
    s.keys("4\n")
    s.keys("1\n")
    s.keys("\n")                 # Blue tried again, and the notebook holds it already: nothing kept
    s.look("7-blue-stays")
    s.end()


def no_notebook():
    """A disk that is not divided: no notebook, so nothing is asked. A look can be tried with `look`, and lasts until
    the machine is switched off."""
    disk = fresh_disk("look-nonotebook", divided=False)
    s = Start("nonotebook", disk, LookChat(1280, notebook=None))
    s.keys("look\n")
    s.keys("3\n")
    s.look("1-paper")
    s.keys("\n")
    s.look("2-not-kept")
    s.keys("hi\n")
    s.look("3-still-paper")
    s.end()


def odd_entries():
    """Entries under "look" written from outside: a name not on the list (and with bytes that are not plain text),
    a name in other letters, an entry that holds no signs, and a look kept on a disk that holds no name yet."""
    disk = fresh_disk("look-unknown")
    put_notebook(disk, [("name", b"Cy"), ("locked key", b""), ("look", b"Night"), ("look", b"Ni\xffght\x00")])
    s = Start("unknown", disk, LookChat(1280, kept_name=b"Cy", key_entry=b"", kept_look=b"Ni\xffght\x00"))
    s.look("1-blue-a-row-and-the-question")
    s.keys("\n")
    s.look("2-answered")
    s.end()

    disk = fresh_disk("look-case")
    put_notebook(disk, [("name", b"Cy"), ("locked key", b""), ("last line", b"x"), ("look", b"night")])
    s = Start("case", disk, LookChat(1280, kept_name=b"Cy", key_entry=b"", last_line=b"x", kept_look=b"night"))
    s.look("1-blue-a-row-and-the-question")
    s.end()

    disk = fresh_disk("look-empty")
    put_notebook(disk, [("name", b"Cy"), ("locked key", b""), ("look", b"Paper"), ("look", b"")])
    s = Start("empty", disk, LookChat(1280, kept_name=b"Cy", key_entry=b"", kept_look=b""))
    s.look("1-blue-no-row-no-question")
    s.end()

    disk = fresh_disk("look-question")
    put_notebook(disk, [("look", b"Contrast")])
    s = Start("question", disk, LookChat(1280, kept_look=b"Contrast"))
    s.look("1-name-question-in-contrast")
    s.keys("Dee\n")
    s.keys("\n")                 # no key, and the look is answered: nothing more is asked
    s.look("2-no-key-in-contrast")
    s.end()

    # No name, but answers about the key and the look: the first row says "one question".
    disk = fresh_disk("look-one")
    put_notebook(disk, [("locked key", b""), ("look", b"Night")])
    s = Start("one", disk, LookChat(1280, key_entry=b"", kept_look=b"Night"))
    s.look("1-one-question-in-night")
    s.keys("Kim\n")
    s.look("2-nothing-more")
    s.end()


def locked():
    """A key typed, tried and locked with a password, then Contrast picked at the onboarding's question: the next
    start asks for the password in Contrast."""
    disk = fresh_disk("look-locked")
    s = Start("locked-1", disk, LookChat(1280))
    s.keys("Eve\n")
    s.key_tried(KEY + "\n")
    s.keys(PW + "\n")
    # Locking takes a second or more: wait for the question that follows it, not for a fixed time.
    s.mark()
    s.keys(PW + "\n")
    s.wait_text("pick a look by number")
    s.look("1-locked-then-the-question")
    s.keys("4\n")
    s.keys("\n")
    s.look("2-contrast-kept")
    s.end(secrets=[KEY, PW])

    s = Start("locked-2", disk, LookChat(1280, kept_name=b"Eve", key_entry=LOCKED, password=PW, kept_look=b"Contrast"))
    s.look("1-password-question-in-contrast")
    s.mark()
    s.keys(PW + "\n")
    s.wait_text("the key is unlocked")
    s.look("2-unlocked")
    s.end(secrets=[KEY, PW])


def damaged():
    """A damaged notebook (something behind its end) that holds a name and a look: the look is put in use at the
    start, nothing is asked, and another look can be tried but not kept."""
    disk = fresh_disk("look-damaged")
    put_notebook(disk, [("name", b"Hal"), ("look", b"Paper")])
    put_block(disk, 5, b"junk".ljust(BLOCK, b"\0"))
    s = Start("damaged", disk, LookChat(1280, notebook="damaged", kept_name=b"Hal", kept_look=b"Paper"))
    s.damaged = True
    s.look("1-paper-from-a-damaged-notebook")
    s.keys("look\n")
    s.keys("4\n")
    s.keys("\n")
    s.look("2-contrast-not-kept")
    s.end()


def small_screen():
    """A screen of 800 by 600 dots, where a row holds 57 signs and the list takes two rows."""
    disk = fresh_disk("look-small")
    put_notebook(disk, [("name", b"Ivo"), ("locked key", b"")])
    s = Start("small", disk, LookChat(800, kept_name=b"Ivo", key_entry=b""), width=800, height=600, extra=["-vga", "cirrus"])
    s.look("1-list-in-two-rows")
    s.keys("2\n")
    s.look("2-night")
    s.keys("\n")
    s.look("3-kept")
    s.end()

    s = Start("small-2", disk, LookChat(800, kept_name=b"Ivo", key_entry=b"", kept_look=b"Night"),
              width=800, height=600, extra=["-vga", "cirrus"])
    s.look("1-next-start-in-night")
    s.end()


def no_screen():
    """No display card: nothing is painted, but the question is asked, a look kept, and the next start reads it."""
    disk = fresh_disk("look-noscreen")
    put_notebook(disk, [("name", b"Gus"), ("locked key", b"")])
    s = Start("noscreen", disk, LookChat(None, kept_name=b"Gus", key_entry=b""), width=None, extra=["-vga", "none"])
    s.keys("3\n")
    s.keys("\n")
    s.end()

    s = Start("noscreen-2", disk, LookChat(None, kept_name=b"Gus", key_entry=b"", kept_look=b"Paper"),
              width=None, extra=["-vga", "none"])
    s.end()


SCENARIOS = dict(pick=pick, atonce=at_once, his=his, setup=setup, norandom=no_random, stays=stays,
                 nonotebook=no_notebook, odd=odd_entries, locked=locked, damaged=damaged, small=small_screen,
                 noscreen=no_screen)

if __name__ == "__main__":
    for name in sys.argv[1:] or list(SCENARIOS):
        print("--- " + name)
        SCENARIOS[name]()
    print("FAILURES:", failures if failures else "none")
