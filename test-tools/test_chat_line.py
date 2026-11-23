"""The line typed in the chat box (docs/chat.md): up to 200 signs on every screen; the row being typed grows upward
inside the chat box when the line does not fit on one row, at most half of the chat box; the keys that edit it (Left,
Right, Home, End, Delete, and Backspace at the place where the next sign goes, which shows in swapped colours inside the
line); and Up and Down, which bring back the last line sent and what was typed before. Every picture is compared dot
for dot with picture.py's model, written from the notes apart from the kernel's code, and the terminal's rows with what
the model says.

  edit     1280 by 800, a disk that is not divided (no notebook): the rows of what was said filled; a line that grows
           to two rows at its 95th sign and to three at its 192nd, and takes no 201st; Home, Right onto a typed "_" and
           onto a space, Delete, signs put in and taken away in the middle below a row with tails; End; Enter; Up,
           Down, Up over a line half typed and Down again; a line brought back, changed and sent; and a secret typed
           as stars with every new key pressed, of which none counts.
  small    800 by 600: a line of 200 signs needs four rows and three show: the last three, with Home the first three,
           then the three around the place; and the line sent, in four rows.
  noscreen no display card: a line held to 200 signs, brought back by Up, changed with Home, Delete, End, Backspace and
           Left, and sent: the terminal's rows.
  restart  a divided disk whose notebook answers the questions: a long line sent and kept, said again whole at the next
           start and brought back by Up; after `setup`, Up does nothing while the name is asked.
  stream   with the stand-in for the provider and a made-up key: a long line typed while the model's answer comes in
           and the stand-in holds it: the words so far show in the rows the row being typed leaves; then the whole
           answer, and the long line sent after it, whole in its request and in the record of the line after it.

Usage: python test_chat_line.py [scenario ...]   (with none: all)
Environment: BOOS_PORT_BASE (48300 for this lane)."""
import os
import sys
import time

from boot import Machine
from onboard_model import name_of
from picture import DELETE, DOWN, END, HOME, LEFT, RIGHT, UP, Chat, compare, expected, to_png
from places import KERNEL
from test_apps_kept import Run, answered_disk, failures, give_key, report

# A line of 200 signs with a typed "_" in its second row and a space after it, the letters with tails (g, j, p, q, y)
# in its first row, so that a change in the second row is seen not to wipe them.
LONG = "the quick brown fox jumps over the lazy dog and keeps going gently by the quay, joyfully "  # 89 signs
LONG += "fetch file_name.txt from the web, then open it"  # 46 signs: up to 135
LONG += " and draw a table of what it holds, row by row, plus a total"  # 60 signs: up to 195
LONG += " abcde"  # 6 signs: 201, one more than the line takes
assert len(LONG) == 201, len(LONG)
UNDERSCORE = LONG.index("_")
SPACE_AFTER = LONG.index(" ", UNDERSCORE)


class Screen:
    """A machine of Machine's kind (no stand-in, a disk that is not divided) with the chat model beside it."""

    def __init__(self, tag, width, height, extra):
        # `width` None: a machine without a usable screen, where only the terminal shows what was said.
        self.tag, self.width, self.height = tag, width, height
        self.m = Machine(tag, extra)
        self.chat = Chat(width)
        if not self.m.wait_for(b"repeated here:", 200):
            print(self.m.serial().decode(errors="replace")[-3000:])
            report(tag + " start", False, "THE PROMPT NEVER CAME")
            raise SystemExit(1)

    def press(self, text, pause=0.2):
        """Sends the keys of `text` through QEMU's monitor (signs, Enter, Backspace and the model's stand-ins for the
        arrows, Home, End and Delete; onboard_model.name_of names them), and the chat model takes them too."""
        for sign in text:
            name = name_of(sign)
            self.m.command("sendkey %s 20" % name)
            time.sleep(0.25 if name.startswith("shift-") else pause)
            self.chat.key(sign)

    def shot(self, name):
        """A picture compared dot for dot with the model's; taken again, up to four more times half a second apart, in
        case it was taken in the middle of painting."""
        time.sleep(0.7)
        meant = expected(self.width, self.height, self.chat)
        wrong, places, path = -1, [], None
        for _ in range(5):
            path = self.m.shot(name)
            wrong, places = compare(path, meant)
            if wrong == 0:
                break
            time.sleep(0.5)
        report(self.tag + " " + name, wrong == 0, "every dot right" if wrong == 0 else "%s dots wrong %s" % (wrong, places[:2]))
        if wrong:
            to_png(path, path[:-4] + ".png")

    def end(self):
        """Ends the machine, and compares the terminal's rows from the hint on with the ones the model says."""
        raw = self.m.quit()
        ours = raw[max(raw.find(b"Hello from my kernel!"), 0):]
        text = ours.decode(errors="replace")
        meant = "\r\n".join(self.chat.said) + "\r\n"
        report(self.tag + " terminal", text.endswith(meant), None if text.endswith(meant) else "ends %r" % text[-300:])
        bad = [b for b in ours if not (32 <= b <= 126 or b in (13, 10))]
        report(self.tag + " plain text", not bad, None if not bad else "%d bytes that are not plain text" % len(bad))


def scenario_edit():
    print("edit: a long line, the keys that edit it, Up and Down, and the stars")
    s = Screen("line-edit", 1280, 800, [])
    try:
        # The rows of what was said filled, so that the row being typed shows when it takes their place.
        s.press("one\ntwo\nthree\n")
        s.shot("1-rows-full")
        s.press(LONG[:94])
        s.shot("2-94-one-row")
        s.press(LONG[94])
        s.shot("3-95-two-rows")
        s.press(LONG[95:191])
        s.shot("4-191-two-rows")
        s.press(LONG[191])
        s.shot("5-192-three-rows")
        s.press(LONG[192:])  # the 201st sign is not taken
        s.shot("6-200-the-limit")
        s.press(HOME)
        s.shot("7-home")
        s.press(RIGHT * UNDERSCORE)
        s.shot("8-on-a-typed-underscore")
        s.press(RIGHT * (SPACE_AFTER - UNDERSCORE))
        s.shot("9-on-a-space")
        s.press(DELETE * 2 + "ok")
        s.shot("10-changed-below-the-tails")
        s.press(LEFT * 3 + "\b")
        s.shot("11-taken-before-the-place")
        s.press(END)
        s.shot("12-end")
        s.press("\n")
        s.shot("13-sent")
        s.press(UP)
        s.shot("14-up-brings-it-back")
        s.press(DOWN)
        s.shot("15-down-the-empty-line")
        s.press("draft" + LEFT * 2 + UP)
        s.shot("16-up-over-a-draft")
        s.press(UP)
        s.shot("17-up-again-does-nothing")
        s.press(DOWN)
        s.shot("18-down-the-draft-again")
        s.press(END + "\b" * 5 + UP + HOME + DELETE * 4 + "\n")
        s.shot("19-changed-and-sent")
        # A secret, as stars: the new keys count no sign there, and Backspace and Enter work as before.
        s.press("key\nabcde" + LEFT + RIGHT + HOME + END + DELETE + UP + DOWN)
        s.shot("20-stars-stay-five")
        s.press("\b\n")
        s.shot("21-secret-taken")
    finally:
        s.end()


def scenario_small():
    print("small: 800 by 600, where a line of 200 signs needs four rows and three show")
    s = Screen("line-small", 800, 600, ["-vga", "cirrus"])
    try:
        s.press(LONG[:200])
        s.shot("1-four-rows-three-shown")
        s.press(HOME)
        s.shot("2-home-the-first-three")
        s.press(RIGHT * 60)
        s.shot("3-the-three-around-the-place")
        s.press(DELETE * 5 + END)
        s.shot("4-end-the-last-three")
        s.press("\n")
        s.shot("5-sent-in-four-rows")
    finally:
        s.end()


def scenario_noscreen():
    print("noscreen: without a display card the line is held to 200 signs, the keys edit it and Up brings it back")
    s = Screen("line-noscreen", None, None, ["-vga", "none"])
    try:
        s.press(LONG + "\n")  # the 201st sign is not taken
        s.press(UP + HOME + DELETE * 4 + END + "\b" * 3 + "\n")
        s.press("abc" + LEFT * 2 + "X" + "\n")
    finally:
        s.end()


def scenario_restart():
    print("restart: a long line said again whole at the next start, and brought back by Up; Up during the name question")
    from apps_kept_model import screen
    from chat_tools_model import ToolsChat
    disk, _ = answered_disk("line-restart")
    line = LONG[:150]
    run = Run("line-restart-1", disk, kernel_file=KERNEL, network=True)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    try:
        run.press(line + "\n", chat)
        run.shot("1-sent", screen(1280, 800, chat, []))
    finally:
        run.end()
    run = Run("line-restart-2", disk, kernel_file=KERNEL, network=True)
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"", last_line=line.encode())
    try:
        run.shot("2-said-again-whole", screen(1280, 800, chat, []))
        run.press(UP, chat)
        run.shot("3-up-brings-it-back", screen(1280, 800, chat, []))
        run.press(DOWN + "setup\n", chat)
        run.press(UP, chat)
        run.shot("4-up-during-the-name-question", screen(1280, 800, chat, []))
    finally:
        run.end()


def scenario_stream():
    print("stream: a long line typed while the model's answer comes in")
    from apps_kept_model import screen
    from chat_tools_model import ToolsChat, body_meant, model_row
    import chat_cases
    from test_chat_tools import check_body, exchange, growing, pieces_of, posts, so_far
    words = ("words=This answer comes in pieces while a long line is typed below it, and the rows of what was said that "
             "show are fewer while that line takes more rows.")
    disk, _ = answered_disk("line-stream")
    run = Run("line-stream", disk, behaviours=["hold:" + words, "words=The long line came whole.", "words=Short."])
    chat = ToolsChat(1280, kept_name=b"", key_entry=b"", kept_look=b"")
    t = chat_cases.TOKENS_LINE
    try:
        give_key(run, chat)
        sent = chat_cases.stream_sent(pieces_of("hold:" + words), "hold")[0]
        typed = LONG[:120]

        def meanwhile():
            # The stand-in holds the answer: a long line is typed below the words so far, and pictured.
            end = time.time() + 60
            while time.time() < end and not os.path.exists(run.log + ".held"):
                time.sleep(0.05)
            report(run.tag + " held", os.path.exists(run.log + ".held"))
            run.press(typed, chat)
            run.shot("1-words-so-far-and-a-long-line", screen(1280, 800, growing(chat, so_far(sent)), []))
            open(run.log + ".go", "w").close()

        exchange(run, chat, "tell me more", [model_row(words[len("words="):]), t], meanwhile=meanwhile)
        run.shot("2-the-answer-and-the-long-line", screen(1280, 800, chat, []))
        exchange(run, chat, "", [model_row("The long line came whole."), t])
        run.shot("3-the-long-line-sent", screen(1280, 800, chat, []))
        exchange(run, chat, "and a short one", [model_row("Short."), t])
    finally:
        run.end()
    # The long line went whole as the person's message, and goes whole with the next line, in what is remembered
    # (docs/tools.md); every request compared whole with the one worked out from the notes (chat_tools_model.py).
    seen = posts(run)
    report(run.tag + " three requests", len(seen) == 3, "%d requests" % len(seen))
    if len(seen) == 3:
        check_body(run.tag + " the long line's request", seen[1], body_meant(typed, [], record=chat.records[1]))
        check_body(run.tag + " the next request", seen[2], body_meant("and a short one", [], record=chat.records[2]))
        report(run.tag + " the long line whole in what is remembered", "Person: " + typed in chat.records[2].split("\n"))


SCENARIOS = {"edit": scenario_edit, "small": scenario_small, "noscreen": scenario_noscreen, "restart": scenario_restart,
             "stream": scenario_stream}


def main():
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
