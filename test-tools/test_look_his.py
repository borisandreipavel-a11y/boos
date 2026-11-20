"""The path of a person's run, as close as a windowless test gets: a disk file made the way run.bat makes it
(qemu-img, then make-disk.ps1), a name, Enter alone at the key, `look`, a number, Enter alone, then a second start.
Variant "kill": QEMU is killed the moment the row that the look is kept appears, as when a window is closed at once.
Usage: python test_look_his.py [quit|kill ...]"""
import os
import subprocess
import sys
import time

from boot import PROJECT
from disk_helpers import make
from look_model import LookChat
from nb import read_notebook
from start_helper import Start, failures


def his_disk(name):
    path = make(name + ".img", "16M")
    done = subprocess.run(["powershell", "-NoProfile", "-File", os.path.join(PROJECT, "make-disk.ps1"), path],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return path


def run(ending):
    disk = his_disk("look-his-" + ending)
    s = Start("his-%s-1" % ending, disk, LookChat(1280))
    s.keys("Ada\n")
    s.keys("\n")
    s.keys("look\n")
    s.keys("2\n")
    s.look("1-night-tried")
    if ending == "quit":
        s.keys("\n")
        s.look("2-night-kept")
        s.end()
    else:
        s.mark()
        s.keys("\n")
        s.wait_text("is kept on the disk", timeout=20)
        s.m.process.kill()
        s.m.process.wait()
        s.m.monitor.close()
        names = [n for n, _ in read_notebook(disk)["entries"]]
        print("  %-38s %s" % ("his-kill-1 notebook after the kill", names))
        if names[-1:] != ["look"]:
            failures.append("his-kill-1 notebook")
    # No last line: `look` was the answer to the onboarding's question for a look, and an answer is not kept as one.
    s = Start("his-%s-2" % ending, disk, LookChat(1280, kept_name=b"Ada", key_entry=b"", kept_look=b"Night"))
    s.look("1-second-start-in-night")
    s.end()


if __name__ == "__main__":
    for ending in sys.argv[1:] or ["quit", "kill"]:
        print("--- " + ending)
        run(ending)
    print("FAILURES:", failures if failures else "none")
