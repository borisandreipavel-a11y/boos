"""`setup` brings back the first look: at once, before its first question, and kept on the disk at once when the
notebook holds another look, so that the next start shows it too, also after a switch-off in the middle of `setup`.
Every picture against the model (reset_model.py), the terminal's lines, and the notebook read from outside, across
starts on the same disk. Usage: python test_look_reset.py [scenario ...]   (default: all)"""
import os
import sys

from keyed_model import LOCKED
from lockref import lock
from nb import BLOCK, put_block, put_notebook
from reset_model import ResetChat
from start_helper import Start, failures, fresh_disk

KEY = "sk-orca-TEST_Reset-Made-Up-Key-8765"
PW = "blue door"


def locked_from_outside(password=PW, key=KEY, rounds=600000):
    return lock(password.encode(), key.encode(), os.urandom(16), os.urandom(12), rounds)


def at_once():
    """Night kept: `setup` paints the whole screen in look 1 before its first question, and keeps an entry with no
    signs under "look" before the line itself; Enter alone at the question for a look keeps look 1, and nothing more
    is written. The next start shows look 1 and asks nothing about the look."""
    disk = fresh_disk("reset-at-once")
    put_notebook(disk, [("name", b"Fay"), ("locked key", b""), ("look", b"Night")])
    s = Start("at-once-1", disk, ResetChat(1280, kept_name=b"Fay", key_entry=b"", kept_look=b"Night"))
    s.look("1-night")
    s.keys("setup\n")
    s.look("2-blue-at-once")
    s.keys("\n")                 # the name stays
    s.keys("\n")                 # no key
    s.look("3-question-in-blue")
    s.keys("\n")                 # Enter alone: look 1 stays
    s.look("4-blue-stays")
    s.end()
    s = Start("at-once-2", disk, ResetChat(1280, kept_name=b"Fay", key_entry=b"", last_line=b"setup", kept_look=b""))
    s.look("1-blue-no-question")
    s.end()


def midway():
    """Night kept: the machine is switched off while `setup` waits for the name. The entry kept at once makes the next
    start show look 1, without the question for a look."""
    disk = fresh_disk("reset-midway")
    put_notebook(disk, [("name", b"Gil"), ("locked key", b""), ("look", b"Night")])
    s = Start("midway-1", disk, ResetChat(1280, kept_name=b"Gil", key_entry=b"", kept_look=b"Night"))
    s.keys("setup\n")
    s.look("1-blue-at-once")
    s.end()                      # switched off while the question for the name waits
    s = Start("midway-2", disk, ResetChat(1280, kept_name=b"Gil", key_entry=b"", last_line=b"setup", kept_look=b""))
    s.look("1-blue-no-question")
    s.end()


def again():
    """Night kept: after `setup`, Night picked again at the question for a look is kept anew, behind the entry with no
    signs, and the next start shows it."""
    disk = fresh_disk("reset-again")
    put_notebook(disk, [("name", b"Hob"), ("locked key", b""), ("look", b"Night")])
    s = Start("again-1", disk, ResetChat(1280, kept_name=b"Hob", key_entry=b"", kept_look=b"Night"))
    s.keys("setup\n")
    s.keys("\n")
    s.keys("\n")
    s.keys("2\n")
    s.look("1-night-tried")
    s.keys("\n")
    s.look("2-night-kept")
    s.end()
    s = Start("again-2", disk, ResetChat(1280, kept_name=b"Hob", key_entry=b"", last_line=b"setup", kept_look=b"Night"))
    s.look("1-in-night")
    s.end()


def unchanged():
    """No look to bring back: with an entry with no signs, and with look 1 kept by its name, `setup` writes nothing
    about the look, and its question for a look comes as before."""
    for tag, kept in (("empty", b""), ("blue", b"Blue")):
        disk = fresh_disk("reset-unchanged-" + tag)
        put_notebook(disk, [("name", b"Ida"), ("locked key", b""), ("look", kept)])
        s = Start("unchanged-" + tag, disk, ResetChat(1280, kept_name=b"Ida", key_entry=b"", kept_look=kept))
        s.keys("setup\n")
        s.look("1-name-question")
        s.keys("\n")
        s.keys("\n")
        s.keys("\n")             # Enter alone at the question for a look: look 1 stays, nothing written
        s.look("2-blue-stays")
        s.end()


def no_notebook():
    """A disk that is not divided: no notebook. A look tried with `look` lasts until the machine is switched off;
    `setup` brings back look 1 at once, and says nothing about the disk, where nothing was kept."""
    disk = fresh_disk("reset-nonotebook", divided=False)
    s = Start("nonotebook", disk, ResetChat(1280, notebook=None))
    s.keys("look\n")
    s.keys("3\n")
    s.keys("\n")                 # Paper cannot be kept, and lasts until the machine is switched off
    s.look("1-paper")
    s.keys("setup\n")
    s.look("2-blue-at-once")
    s.keys("\n")                 # "You" cannot be kept either; nothing is asked after the name
    s.look("3-blue")
    s.end()


def damaged():
    """A damaged notebook (something behind its end) that holds a name and Paper: `setup` brings back look 1 at once,
    cannot keep it, and says so when its questions are over; the next start shows Paper again."""
    disk = fresh_disk("reset-damaged")
    put_notebook(disk, [("name", b"Hal"), ("look", b"Paper")])
    put_block(disk, 5, b"junk".ljust(BLOCK, b"\0"))
    s = Start("damaged-1", disk, ResetChat(1280, notebook="damaged", kept_name=b"Hal", kept_look=b"Paper"))
    s.damaged = True
    s.look("1-paper")
    s.keys("setup\n")
    s.look("2-blue-at-once")
    s.keys("\n")                 # the name stays; the two rows about the look follow
    s.look("3-rows-about-the-look")
    s.end()
    s = Start("damaged-2", disk, ResetChat(1280, notebook="damaged", kept_name=b"Hal", kept_look=b"Paper"))
    s.damaged = True
    s.look("1-paper-again")
    s.end()


def locked():
    """A key locked on the disk and Contrast kept: the start asks for the password in Contrast. Enter alone there, and
    then `setup`: look 1 at once, the question for a new key, where Enter alone keeps the locked one, and Enter alone
    at the question for a look keeps look 1. The next start asks for the password in look 1."""
    disk = fresh_disk("reset-locked")
    put_notebook(disk, [("name", b"Ivy"), ("locked key", locked_from_outside()), ("look", b"Contrast")])
    s = Start("locked-1", disk, ResetChat(1280, kept_name=b"Ivy", key_entry=LOCKED, password=PW, kept_look=b"Contrast"))
    s.look("1-password-question-in-contrast")
    s.keys("\n")                 # Enter alone at the password: on without the key
    s.keys("setup\n")
    s.look("2-blue-at-once")
    s.keys("\n")                 # the name stays; the question for a new key follows
    s.keys("\n")                 # Enter alone keeps the locked key
    s.keys("\n")                 # Enter alone at the question for a look: look 1 stays
    s.look("3-blue-stays")
    s.end(secrets=[KEY, PW])
    s = Start("locked-2", disk, ResetChat(1280, kept_name=b"Ivy", key_entry=LOCKED, password=PW, last_line=b"setup",
                                          kept_look=b""))
    s.look("1-password-question-in-blue")
    s.end(secrets=[KEY, PW])


def no_screen():
    """No display card: nothing is painted, but `setup` keeps the entry with no signs at once, and the next start
    reads it."""
    disk = fresh_disk("reset-noscreen")
    put_notebook(disk, [("name", b"Jo"), ("locked key", b""), ("look", b"Paper")])
    s = Start("noscreen-1", disk, ResetChat(None, kept_name=b"Jo", key_entry=b"", kept_look=b"Paper"), width=None,
              extra=["-vga", "none"])
    s.keys("setup\n")
    s.keys("\n")
    s.keys("\n")
    s.keys("\n")
    s.end()
    s = Start("noscreen-2", disk, ResetChat(None, kept_name=b"Jo", key_entry=b"", last_line=b"setup", kept_look=b""),
              width=None, extra=["-vga", "none"])
    s.end()


def small():
    """A screen of 800 by 600 dots, where a row holds 57 signs, and a damaged notebook that holds a name and Night:
    `setup` brings back look 1 at once; a new name cannot be kept either, and after its row each of the two rows about
    the look, which cannot be kept, takes two rows."""
    disk = fresh_disk("reset-small")
    put_notebook(disk, [("name", b"Kit"), ("look", b"Night")])
    put_block(disk, 5, b"junk".ljust(BLOCK, b"\0"))
    s = Start("small", disk, ResetChat(800, notebook="damaged", kept_name=b"Kit", kept_look=b"Night"),
              width=800, height=600, extra=["-vga", "cirrus"])
    s.damaged = True
    s.look("1-night")
    s.keys("setup\n")
    s.look("2-blue-at-once")
    s.keys("Lu\n")               # a new name, which cannot be kept; the two rows about the look follow
    s.look("3-rows-about-the-look")
    s.end()


SCENARIOS = dict(atonce=at_once, midway=midway, again=again, unchanged=unchanged, nonotebook=no_notebook,
                 damaged=damaged, locked=locked, noscreen=no_screen, small=small)

if __name__ == "__main__":
    for name in sys.argv[1:] or list(SCENARIOS):
        print("--- " + name)
        SCENARIOS[name]()
    print("FAILURES:", failures if failures else "none")
