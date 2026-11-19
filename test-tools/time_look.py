"""How long a start shows the first look before the look kept in the notebook takes its place: the time from the
screen line (the first painting) to the greeting's row (the rows are printed just before the screen is painted
again), by the wall clock of this computer, on a disk whose notebook keeps Night. Usage: python time_look.py [boots]"""
import sys

from disk_helpers import one_disk
from interp_helpers import boot_lines, line_of
from nb import put_notebook
from start_helper import fresh_disk

boots = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for number in range(1, boots + 1):
    disk = fresh_disk("look-time-%d" % number)
    entries = [("name", b"Hal"), ("locked key", b"")] + [("last line", b"line %d" % n) for n in range(200)] + [("look", b"Night")]
    put_notebook(disk, entries)
    stamps, raw = boot_lines("look-time-%d" % number, extra=one_disk(disk), disk=False)
    screen_at, _ = line_of(stamps, "Screen: found")
    greeting_at, _ = line_of(stamps, "Kernel: welcome back")
    notebook_at, notebook_line = line_of(stamps, "Disk: the notebook holds")
    print("boot %d: screen line at %.2f s, notebook line at %.2f s, greeting at %.2f s: the first look shows for %.2f s (%s)" % (
        number, screen_at, notebook_at, greeting_at, greeting_at - screen_at, notebook_line))
