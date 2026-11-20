"""The checks of the kernel's own lines on the screen (lines.rs), for test_lines.py, test_lines_stop.py and
run_lines_breaks.py. Each check boots a kernel without a window, saves pictures of the screen, compares every dot
with the picture that lines_model.py or picture.py builds, and gives back what went wrong (an empty list when all
is as meant). Nothing runs when this file is imported.

The boots use a disk that is not divided, so that the kernel keeps nothing and asks nothing, and the fenced
network, so that nothing leaves this computer."""
import json
import os
import socket
import time

from boot import Machine
from lines_model import MARGIN, ROW, start_screen, stop_picture, view
from picture import Chat, compare, expected, read_ppm, to_png
from ports import free_port

# What makes a failure or a panic on purpose, and where, in a copy of the kernel (lines_copy.py). The texts are
# main.rs's, with its line ends as "\n".
FAULT = "    unsafe { core::ptr::write_volatile(0xFFFF_8000_0000_0000u64 as *mut u8, 1) }; // TEST: a failure on purpose\n"
AFTER_TAKEOVER = r'    write!(serial, "The firmware has stepped aside. This machine is mine.\r\n").ok();' + "\n"
AFTER_PAGE_TABLES = r"""    write!(serial, "Page tables: the kernel's own, covering {} GB\r\n", covered / GIGABYTE).ok();""" + "\n"
BEFORE_LOCK = "    // The kernel can lock a secret with a password (see lock.rs). See that\n"
PANIC = ('    { let list = alloc::vec![1u8, 2, 3]; let index = core::hint::black_box(7usize); '
         'write!(serial, "{}", list[index]).ok(); } // TEST: a panic on purpose\n')
MAIN_LOOP = "        if seconds >= 4 && !hint_shown {\n"
LATE_FAULT = "        if seconds >= 6 {\n    " + FAULT + "        }\n"
TASK_LINE = r'        serial_print(&format!("{}: {}\r\n", name, step));' + "\n"
TASK_FAULT = '        if name == "Task B" && step == 2 {\n    ' + FAULT + "        }\n"

# What makes the kernel find no serial port, in serial.rs, as on a PC that has none.
NO_PORT = ("    unsafe { SERIAL_FOUND = found };\n", "    unsafe { SERIAL_FOUND = false && found }; // TEST: no serial port\n")

# What makes the two demonstration tasks of main.rs count to nine instead of three, so that lines are printed for
# some seconds after the prompt.
LONGER_TASKS = ("    for step in 1..=3 {\n", "    for step in 1..=9 { // TEST: the tasks count longer\n")

# name: (the change to main.rs, whether F1 is pressed at the prompt before the failure, what the report begins with)
STOP_CASES = {
    # Right after the takeover: the screen is drawn on through the firmware's page tables.
    "stop-firmware": ((AFTER_TAKEOVER, AFTER_TAKEOVER + FAULT), False, "CPU fault: page fault"),
    # Right after the kernel's own page tables took over, before the heap and before the usual picture is ready.
    "stop-own": ((AFTER_PAGE_TABLES, AFTER_PAGE_TABLES + FAULT), False, "CPU fault: page fault"),
    # A panic in the middle of the start, after the check of JSON.
    "stop-panic": ((BEFORE_LOCK, PANIC + BEFORE_LOCK), False, "Kernel panic: "),
    # With the usual picture on the screen, six seconds in.
    "stop-picture": ((MAIN_LOOP, LATE_FAULT + MAIN_LOOP), False, "CPU fault: page fault"),
    # With the lines on the screen because F1 was pressed.
    "stop-view": ((MAIN_LOOP, LATE_FAULT + MAIN_LOOP), True, "CPU fault: page fault"),
    # In another task than the main loop, while the start screen shows: task B, right after its second line, which
    # the main loop has not painted yet.
    "stop-task": ((TASK_LINE, TASK_LINE + TASK_FAULT), False, "CPU fault: page fault"),
}


def printed(raw):
    """The whole lines the kernel printed, from its first line on."""
    begin = raw.find(b"Hello from my kernel!")
    if begin < 0:
        return []
    return [line.decode(errors="replace") for line in raw[begin:].split(b"\r\n")[:-1]]


def same(path, picture):
    width, height, dots = read_ppm(path)
    return (width, height) == (picture.width, picture.height) and dots == bytes(picture.dots)


def judge(path, picture, name, problems):
    """Compares a saved picture with the one meant, says how it went, and notes a difference."""
    wrong, places = compare(path, picture)
    print("  %-44s %s" % (name, "every dot right" if wrong == 0 else "%d dots wrong %s" % (wrong, places[:2])))
    if wrong:
        problems.append(name)
        to_png(path, path[:-4] + ".png")


def look(machine, name, picture, problems, wait=0.9):
    """Waits for the painting to end, saves a picture and judges it. Painting the usual picture again takes a
    quarter of a second, and longer while other work runs on this computer, so a picture that is not right yet
    is saved again, up to two more times, half a second apart."""
    time.sleep(wait)
    for _ in range(3):
        path = machine.shot(name.replace(" ", "-").replace(":", "").replace(",", ""))
        if same(path, picture):
            break
        time.sleep(0.5)
    judge(path, picture, name, problems)


def wait_any(machine, words, seconds=150):
    deadline = time.time() + seconds
    while time.time() < deadline:
        raw = machine.serial()
        if any(word in raw for word in words):
            return True
        if machine.process.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def rested(lines):
    return any(line.startswith("The processor rested") for line in lines)


def start_match(path, lines, width, height):
    """How many of `lines` the picture shows as the start screen, or None. The screen may be a few lines behind
    the terminal: once the tasks run, the main loop paints their lines at its next turn."""
    for count in range(len(lines), max(1, len(lines) - 3) - 1, -1):
        if same(path, start_screen(width, height, lines[:count]).picture()):
            return count
    return None


def start_pictures(machine, width, height, problems):
    """Saves pictures while the machine starts, each with the machine paused, until the start is over, and judges
    each at once: it must be the start screen for the lines printed by then. A picture saved in the middle of a
    painting is saved again a moment later, up to three times. Gives back how many lines each right one showed."""
    matched = []
    deadline = time.time() + 150
    while time.time() < deadline and machine.process.poll() is None:
        # Before the kernel's first line of its own the firmware's picture is on the screen, and once the rest
        # count is printed the usual picture takes the lines' place.
        if len(printed(machine.serial())) >= 2:
            for attempt in range(3):
                machine.command("stop")
                time.sleep(0.15)
                lines = printed(machine.serial())
                if rested(lines):
                    machine.command("cont")
                    return matched
                path = machine.shot("start-%02d-%d" % (len(matched), attempt))
                machine.command("cont")
                count = start_match(path, lines, width, height)
                if count is not None:
                    matched.append(count)
                    break
                time.sleep(0.05)
            else:
                judge(path, start_screen(width, height, lines).picture(),
                      "a start picture, %d lines printed" % len(lines), problems)
        time.sleep(0.2)
    return matched


def judge_start(matched, lines, width, height, problems):
    """There must be right start pictures from before the devices started and from after."""
    early = next((i for i, line in enumerate(lines) if line.startswith("Disk controller")), 0)
    late = next((i for i, line in enumerate(lines) if line.startswith("Task A: 1")), len(lines))
    jumps = [count for count in matched if start_screen(width, height, lines[:count]).jumps > 0]
    print("  %-44s %d right, every dot, at %s lines; %d after the lines moved up" % (
        "the start screen (%dx%d)" % (width, height), len(matched), matched, len(jumps)))
    if not any(count <= early for count in matched):
        problems.append("no right start picture before the disk's lines")
    if not any(count > late for count in matched):
        problems.append("no right start picture after the tasks began")
    return jumps


def end_lines(serial, problems):
    lines = printed(serial)
    if any(line.startswith(("Kernel panic", "CPU fault")) for line in lines):
        problems.append("a panic or a fault")
    return lines


def start_check(kernel, tag="lines-start", width=1280, height=800, extra=(), moved=False):
    """The start screen while the machine starts; the usual picture at the prompt; F1, a key, Enter and F1 again.
    `moved`: the lines must have moved up at least once in a picture judged right (a small screen)."""
    problems = []
    machine = Machine(tag, list(extra), kernel=kernel)
    try:
        matched = start_pictures(machine, width, height, problems)
        if not machine.wait_for(b"repeated here:", 150):
            problems.append("the prompt never came")
            return problems
        chat = Chat(width)
        look(machine, "the usual picture at the prompt", expected(width, height, chat), problems)
        machine.named_key("f1", pause=0)
        look(machine, "F1: the lines", view(width, height, printed(machine.serial())).picture(), problems)
        machine.key("a", pause=0)
        chat.keys("a")
        look(machine, "a key: the usual picture, typed", expected(width, height, chat), problems)
        machine.named_key("f1", pause=0)
        look(machine, "F1 again", view(width, height, printed(machine.serial())).picture(), problems)
        machine.key("\n", pause=0)
        chat.keys("\n")
        look(machine, "Enter: the usual picture, the line sent", expected(width, height, chat), problems)
        lines = printed(machine.serial())
        if lines[-2:] != chat.said[-2:]:
            problems.append("the lines said are %r, meant %r" % (lines[-2:], chat.said[-2:]))
        machine.named_key("f1", pause=0)
        look(machine, "F1: the new lines at the bottom", view(width, height, lines).picture(), problems)
        machine.key("b", pause=0)
        chat.keys("b")
        look(machine, "b: the usual picture again", expected(width, height, chat), problems)
    finally:
        serial = machine.quit()
    lines = end_lines(serial, problems)
    jumps = judge_start(matched, lines, width, height, problems)
    if moved and not jumps:
        problems.append("no right picture after the lines moved up")
    return problems


def early_check(kernel, tag="lines-early"):
    """A key pressed while the tasks run, before the start is over, brings the usual picture at once, and is
    typed; the end of the start changes nothing then."""
    problems = []
    machine = Machine(tag, kernel=kernel)
    try:
        if not machine.wait_for(b"Task A: 1", 150):
            problems.append("the tasks never printed")
            return problems
        machine.key("c", pause=0)
        chat = Chat(1280)
        chat.keys("c")
        look(machine, "a key during the start", expected(1280, 800, chat), problems)
        # The picture proves something only if the start was not over yet when it was saved.
        if rested(printed(machine.serial())):
            problems.append("the start was over before the key's picture was saved")
        if not machine.wait_for(b"repeated here:", 150):
            problems.append("the prompt never came")
            return problems
        look(machine, "the prompt after it: still the usual picture", expected(1280, 800, chat), problems)
    finally:
        serial = machine.quit()
    end_lines(serial, problems)
    return problems


def noscreen_check(kernel, tag="lines-noscreen"):
    """A machine without a screen: the start and the typing go on as before, F1 and the keys do no harm."""
    problems = []
    machine = Machine(tag, ["-vga", "none"], kernel=kernel)
    try:
        if not machine.wait_for(b"repeated here:", 150):
            problems.append("the prompt never came")
            return problems
        machine.named_key("f1", pause=0.5)
        machine.type("x\n", pause=0.4)
        time.sleep(1)
    finally:
        serial = machine.quit()
    lines = end_lines(serial, problems)
    for wanted in ["Screen: none found, the firmware has no graphics service", "You: x", 'Kernel: you said "x"']:
        if wanted not in lines:
            problems.append("missing line %r" % wanted)
    print("  %-44s %s" % ("no screen", "as meant" if not problems else problems))
    return problems


def noserial_check(kernel, kernel_without_port, tag="lines-noserial"):
    """A machine without a serial port, played by a kernel that finds none (NO_PORT): its lines are kept and shown
    all the same. Nothing tells the test what it said, so the first six lines of a normal start on the same
    machine stand in for them, and F1 after the start must show those at the top."""
    problems = []
    reference = Machine(tag + "-reference", kernel=kernel)
    try:
        if not reference.wait_for(b"Screen: found", 150):
            problems.append("the normal start never came to the screen line")
            return problems
        time.sleep(0.5)
        first = printed(reference.serial())[:6]
    finally:
        reference.quit()
    machine = Machine(tag, kernel=kernel_without_port)
    try:
        # Long enough for the start to be over, also in a slow windowless run.
        time.sleep(15)
        machine.named_key("f1", pause=0)
        time.sleep(1.0)
        path = machine.shot("noserial-f1")
        serial = machine.serial()
    finally:
        machine.quit()
    if printed(serial)[1:]:
        problems.append("the kernel printed through a serial port it should not have found")
    # The firmware prints the first line itself; all the start's lines fit on the screen, so they begin at the top.
    width, height, dots = read_ppm(path)
    meant = view(width, height, first).picture()
    band = (MARGIN + 6 * ROW) * width * 3
    right = (width, height) == (1280, 800) and dots[:band] == bytes(meant.dots[:band])
    print("  %-44s %s" % ("no serial port: F1 shows the first lines", "every dot right" if right else "WRONG"))
    if not right:
        problems.append("no serial port: the first lines are not on the screen")
        to_png(path, path[:-4] + ".png")
    return problems


def later_check(kernel_longer, tag="lines-later"):
    """Lines printed while F1 shows the lines are added at the bottom by the main loop, and the older half moves off
    when the screen is full. Played by a kernel whose tasks count to nine (LONGER_TASKS): about ten lines come after
    the prompt, more than fit below those already there. F1 is pressed at the prompt, and the picture is saved once
    the last task line is printed."""
    problems = []
    machine = Machine(tag, kernel=kernel_longer)
    try:
        if not machine.wait_for(b"repeated here:", 150):
            problems.append("the prompt never came")
            return problems
        before = printed(machine.serial())
        machine.named_key("f1", pause=0)
        if not machine.wait_for(b"Task B: 9", 30):
            problems.append("the tasks did not count to nine")
            return problems
        lines = printed(machine.serial())
        # Where the screen was covered does not change the picture, as long as the lines printed by then fit on
        # it: they are all painted from the top either way, and every later line below them.
        meant = view(1280, 800, before, lines[len(before):])
        look(machine, "F1, then %d lines more" % (len(lines) - len(before)), meant.picture(), problems)
        if not meant.jumps:
            problems.append("the lines after F1 did not fill the screen, so its moving up was not seen")
    finally:
        serial = machine.quit()
    end_lines(serial, problems)
    return problems


def qmp_send(connection, reader, message):
    """Sends a message to QEMU's machine protocol (QMP) and gives back its answer, passing over its events."""
    connection.sendall((json.dumps(message) + "\n").encode())
    while True:
        answer = json.loads(reader.readline())
        if "return" in answer or "error" in answer:
            return answer


def qmp_key(connection, reader, name, down):
    """Presses a key or lets it go. QEMU's monitor can only do both at once, and a key held down sends its number
    again and again, without letting go in between."""
    event = {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": name}}}
    answer = qmp_send(connection, reader, {"execute": "input-send-event", "arguments": {"events": [event]}})
    if "error" in answer:
        raise RuntimeError("QEMU refused the key: %r" % answer)


def held_check(kernel, tag="lines-held"):
    """F1 held down: the keyboard sends F1's number again until it is let go, and that must not take the lines away
    again. F1 goes down twice, half a second apart, through QEMU's machine protocol."""
    problems = []
    port = free_port()
    machine = Machine(tag, ["-qmp", "tcp:127.0.0.1:%d,server=on,wait=off" % port], kernel=kernel)
    connection = None
    try:
        if not machine.wait_for(b"repeated here:", 150):
            problems.append("the prompt never came")
            return problems
        connection = socket.create_connection(("127.0.0.1", port), timeout=5)
        reader = connection.makefile("r")
        reader.readline()  # QEMU's greeting
        qmp_send(connection, reader, {"execute": "qmp_capabilities"})
        lines = printed(machine.serial())
        qmp_key(connection, reader, "f1", True)
        time.sleep(0.6)
        qmp_key(connection, reader, "f1", True)
        look(machine, "F1 held down: the lines", view(1280, 800, lines).picture(), problems)
        qmp_key(connection, reader, "f1", False)
        look(machine, "F1 let go: still the lines", view(1280, 800, lines).picture(), problems)
        machine.key("a", pause=0)
        chat = Chat(1280)
        chat.keys("a")
        look(machine, "a key: the usual picture, typed", expected(1280, 800, chat), problems)
    finally:
        if connection is not None:
            connection.close()
        serial = machine.quit()
    end_lines(serial, problems)
    return problems


def stop_check(kernel, name, width=1280, height=800):
    """A failure or a panic made on purpose (see STOP_CASES): the stop screen with the report and the lines the
    kernel said before it."""
    _, press_f1, report = STOP_CASES[name]
    problems = []
    machine = Machine("lines-" + name, kernel=kernel)
    try:
        if press_f1:
            if not machine.wait_for(b"repeated here:", 150):
                problems.append("the prompt never came")
                return problems
            time.sleep(0.3)
            machine.named_key("f1", pause=0)
        if not wait_any(machine, [b"CPU fault", b"Kernel panic"]):
            problems.append("no failure came")
            return problems
        time.sleep(1.5)
        lines = printed(machine.serial())
        path = machine.shot(name)
    finally:
        serial = machine.quit()
    if not lines or not lines[-1].startswith(report):
        problems.append("the last line is %r, meant one that begins %r" % (lines[-1:] or [""], report))
    if printed(serial) != lines:
        problems.append("the kernel printed more after the report")
    judge(path, stop_picture(width, height, lines), "%s: the stop screen, %d lines" % (name, len(lines)), problems)
    return problems
