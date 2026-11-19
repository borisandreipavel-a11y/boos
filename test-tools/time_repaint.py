"""How long painting the whole screen again takes. Puts a temporary measurement into look_paint in the project
(timer ticks, 100 a second, and the processor's time stamp), builds, types looks in a windowless QEMU, reads the
printed times, then puts look.rs back byte for byte and builds again. Usage: python time_repaint.py"""
import os
import re
import time

from boot import Machine, PROJECT
from build_all import build
from disk_helpers import one_disk
from nb import put_notebook
from start_helper import fresh_disk

FILE = os.path.join(PROJECT, "src", "look.rs")
OLD = "pub fn look_paint() {\n    screen_background();\n    chat_paint();\n    screen_panel_again();\n}\n"
NEW = ("pub fn look_paint() {\n"
       "    let ticks = crate::timer::TICKS.load(core::sync::atomic::Ordering::Relaxed);\n"
       "    let cycles = crate::processor::time_stamp();\n"
       "    screen_background();\n    chat_paint();\n    screen_panel_again();\n"
       "    let ticks = crate::timer::TICKS.load(core::sync::atomic::Ordering::Relaxed) - ticks;\n"
       "    let cycles = crate::processor::time_stamp() - cycles;\n"
       "    crate::serial::serial_print(&format!(\"LOOK TIMING: {} ticks, {} cycles\\r\\n\", ticks, cycles));\n"
       "}\n")

original = open(FILE, "rb").read()
text = original.decode()
old = OLD.replace("\n", "\r\n") if "\r\n" in text else OLD
new = NEW.replace("\n", "\r\n") if "\r\n" in text else NEW
assert text.count(old) == 1, text.count(old)
try:
    open(FILE, "wb").write(text.replace(old, new).encode())
    os.utime(FILE, (time.time(), time.time()))
    build(quiet=True)
    disk = fresh_disk("look-repaint")
    put_notebook(disk, [("name", b"Ivo"), ("locked key", b""), ("look", b"Paper")])
    m = Machine("look-repaint", extra=one_disk(disk), disk=False)
    try:
        assert m.wait_for(b"repeated here:", 150), "no prompt"
        for answer in ["look\n", "2\n", "3\n", "4\n", "1\n", "2\n", "4\n", "3\n", "\n"]:
            m.type(answer, pause=0.2, hold=20)
            time.sleep(1.0)
    finally:
        serial = m.quit()
    found = re.findall(rb"LOOK TIMING: (\d+) ticks, (\d+) cycles", serial)
    print("at startup (device signals off, so no ticks):", found[:1])
    later = [(int(t), int(c)) for t, c in found[1:]]
    print("in the main loop:", later)
    if later:
        ticks = sorted(t for t, _ in later)
        print("ticks: least %d, most %d (a tick is a hundredth of a second)" % (ticks[0], ticks[-1]))
finally:
    open(FILE, "wb").write(original)
    os.utime(FILE, (time.time(), time.time()))
    assert open(FILE, "rb").read() == original
    build(quiet=True)
    print("look.rs put back byte for byte and built again")
