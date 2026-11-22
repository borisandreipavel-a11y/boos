"""A request for an app made the way a person's first run in a new folder goes: a fresh divided disk, so the
kernel first asks for a name and then for the key, against the stand-in for the provider (in a copy of the
project, see net_copy.py). Made-up name, key and password only.

  keylater: Enter alone at the key question, then `key` and the key, then a line that asks for an app ("make " and a
            request of 45 signs), which goes to the model like every line; the stand-in answers it with the tool
            make_app, and then the request for the app.
  keyfirst: the key typed at the key question (tried, answered, locked with a password), then the same line.

Usage: python test_app_first_start.py keylater|keyfirst
Checks the rows from that line on word for word, the `Script` lines, the stand-in's requests (the try of the key, the
line, the request for the app, and the line asked about again with what came of the app), and that the terminal holds
no byte that is not plain text and no piece of the key."""
import json
import os
import subprocess
import sys
import time

os.environ["DIVIDED_DISK"] = "1"

from app_cases import INSTRUCTIONS, LEAD, SCRIPT, listing_meant
from boot import HERE, RUNS, Machine
from certs import test_keys
from chat_cases import AGAIN_WORDS
from chat_tools_model import body_again, body_meant, left_on_screen
from net_copy import build
from ports import standin_port
from verdict import Failures

PORT = standin_port(4)
ENTER = chr(10)
KEY = "sk-orca-TEST_Pz4n/Kd8+Ys2wQc7Vb5Mh3Jt6=="
NAME = "Ada"
PASSWORD = "plum7tree"
REQUEST = "a dice game that rolls two dice and adds them"
assert len(REQUEST) == 45
NAMES = {"-": "minus", "=": "equal", "/": "slash", "+": "shift-equal", "_": "shift-minus", " ": "spc", ENTER: "ret"}
MEANT_ASK = {"model": "deepseek/deepseek-v4.1-flash-1017", "messages": [{"role": "user", "content": "Say hello in five words."}], "max_tokens": 1000, "stream": False}


def press(machine, text):
    for sign in text:
        name = NAMES.get(sign) or ("shift-" + sign.lower() if sign.isupper() else sign)
        machine.command("sendkey " + name)
        time.sleep(0.22 if name.startswith("shift-") else 0.09)


def lines_of(machine):
    return machine.serial().decode(errors="replace").split("\r\n")


def wait_line(machine, start, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        if any(line.startswith(start) for line in lines_of(machine)):
            return True
        time.sleep(0.2)
    return False


def answer_the_look(machine, failures):
    """When the questions about the key are over, a first start asks for a look (docs/chat.md, "Picking a look"):
    Enter alone keeps the first one, so that the next lines go where they did before that question came."""
    if not wait_line(machine, "Kernel: pick a look by number"):
        failures.append("no question for a look")
    press(machine, ENTER)
    if not wait_line(machine, "Kernel: look 1, Blue, stays."):
        failures.append("the question for a look was not answered")


def main():
    scenario = sys.argv[1]
    kernel = build(PORT, roots=["a"])
    tls = test_keys()
    log = os.path.join(RUNS, "app-first-start-server.log")
    if os.path.exists(log):
        os.remove(log)
    answers = ["app"] if scenario == "keylater" else ["good", "app"]
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT), os.path.join(tls, "a", "both-chain.pem"),
                               os.path.join(tls, "a", "both.key"), log, ",".join(answers)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              cwd=HERE)
    assert server.stdout.readline().strip() == "ready"
    machine = Machine("app-first-start-" + scenario, network="open", kernel=kernel)
    failures = Failures()
    try:
        machine.wait_for(b"repeated here:")
        # The machine's address comes from the network's task; wait for it before anything that needs it.
        wait_line(machine, "Network: this machine was given the address", 30)
        time.sleep(1.0)
        press(machine, NAME + ENTER)
        if not wait_line(machine, "Kernel: type the key and press Enter."):
            failures.append("no key question")
        if scenario == "keylater":
            press(machine, ENTER)
            wait_line(machine, "Kernel: then no key is kept.")
            answer_the_look(machine, failures)
            press(machine, "key" + ENTER)
            press(machine, KEY + ENTER)
            wait_line(machine, "Kernel: I took a secret of")
        else:
            press(machine, KEY + ENTER)
            if not wait_line(machine, "Kernel: the key works."):
                failures.append("the key's try did not answer")
            press(machine, PASSWORD + ENTER)
            wait_line(machine, "Kernel: type the same password again")
            press(machine, PASSWORD + ENTER)
            if not wait_line(machine, "Kernel: the key is locked and kept on the disk."):
                failures.append("the key was not locked")
            answer_the_look(machine, failures)
            time.sleep(1.0)
        # The text so far ends in a line end, which leaves an empty piece behind the last line: the next line
        # will stand in that piece's place.
        before = len(lines_of(machine)) - 1
        press(machine, "make " + REQUEST + ENTER)
        wait_line(machine, "Kernel: the model wrote an app", 40)
        # What came of the new app goes back to the model, which is asked about the line again; the stand-in
        # answers with its words (chat_cases.AGAIN_WORDS).
        wait_line(machine, "Model: ", 40)
        time.sleep(1.0)
        machine.shot("end")
    finally:
        raw = machine.quit()
        server.kill()
    lines = raw.decode(errors="replace").split("\r\n")
    after = lines[before:]
    said = [line for line in after if line.startswith((NAME + ":", "Kernel:", "Script ", "App: ", "Model: "))]
    # The app runs: it prints the number it rolled, which no one can know beforehand.
    rolled = [line for line in said if line.startswith("App: ")]
    meant = ["%s: make %s" % (NAME, REQUEST), "Kernel: I am asking the model.", 'Kernel: I am asking the model to make "%s".' % REQUEST,
             "Kernel: the model wrote an app of 4 lines. It is shown in the terminal."] + listing_meant(SCRIPT.strip())
    meant += [rolled[0] if rolled and rolled[0] in ["App: You rolled a %d" % n for n in range(1, 7)] else "App: You rolled a (1 to 6)",
              "Kernel: the app ran to its end.", "Model: " + AGAIN_WORDS]
    # What the second ask about the line goes with: no line before it, and the rows the line brought, with what the
    # app left on the screen, which the chat box does not say.
    dice = rolled[0][len("App: You rolled a "):] if rolled else "(no dice line)"
    done = "\n".join(meant[2:4] + ["Kernel: the app ran to its end.", "Kernel: " + left_on_screen("Dice: " + dice)])
    print("--- the rows from the request on:")
    for line in said:
        print("   " + line)
    if said != meant:
        failures.append("rows")
        print("--- meant:")
        for line in meant:
            print("   " + line)
    whole = raw[raw.find(b"Hello from my kernel!"):]
    odd = sum(1 for index, byte in enumerate(whole) if not (32 <= byte <= 126 or (byte == 13 and whole[index + 1:index + 2] == b"\n")
                                                          or (byte == 10 and whole[index - 1:index] == b"\r")))
    key_pieces = sum(whole.count(KEY[i:i + 6].encode()) for i in range(len(KEY) - 5))
    if odd:
        failures.append("odd bytes")
    if key_pieces:
        failures.append("key in the terminal")
    notes = [json.loads(line) for line in open(log).read().splitlines()]
    posts = [note for note in notes if not note.get("first line", "").startswith("GET")]
    app_body = {"model": "deepseek/deepseek-v4.1-flash-1017", "messages": [{"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": LEAD + REQUEST}], "max_tokens": 4000, "stream": False}
    # The try of the key asks the fixed question; the line goes with the list of tools (no app is kept yet); the
    # line is asked about again with the new app kept.
    wanted = ([MEANT_ASK] if scenario == "keyfirst" else []) + [body_meant("make " + REQUEST, []), app_body,
                                                                 body_again("make " + REQUEST, [(1, REQUEST)], ("", done), key=KEY)]
    got = [note.get("body") for note in posts]
    keys = [note.get("key came as") == "Bearer " + KEY for note in posts]
    print("stand-in: %d requests, bodies as meant %s, each with the whole key %s" % (len(posts), got == wanted, all(keys)))
    if got != wanted or not all(keys):
        failures.append("requests")
    print("bytes in the terminal that are not plain text: %d | pieces of the key in the terminal: %d" % (odd, key_pieces))
    print("FAILURES: %s" % failures if failures else "all as meant")


main()
