"""Picking a look through the model, for the tests of the look (test_look.py, test_look_reset.py): the stand-in for
the provider (model_server.py), which answers the next lines with the behaviours it is given, the copy of the
kernel that talks to it (net_copy.py), and the line `key` with a made-up key, after which every line goes to the
model (docs/tools.md). The model picks a look with the tool pick_look; the chat box's model says what the kernel
says to it (keyed_model.KeyedChat.pick)."""
import json
import os
import subprocess
import sys

from boot import HERE, RUNS
from certs import test_keys
from net_copy import build
from ports import standin_port

KEY = "sk-orca-TEST_Look-Made-Up-Key-4321"
PORT = standin_port(6)
LOG = os.path.join(RUNS, "look-server.log")
standin = {}  # the copy of the kernel that talks to the stand-in, and the stand-in running now


def with_standin(behaviours):
    """Starts the stand-in, which answers the next lines with these behaviours (chat_cases.py: "look=3" asks for
    pick_look with look 3), and gives back the copy of the kernel that talks to it, built once."""
    if "kernel" not in standin:
        standin["kernel"] = build(PORT, roots=["a"])
    stop_standin()
    if os.path.exists(LOG):
        os.remove(LOG)
    tls = test_keys()
    standin["server"] = subprocess.Popen([sys.executable, os.path.join(HERE, "model_server.py"), str(PORT),
                                          os.path.join(tls, "a", "both-chain.pem"), os.path.join(tls, "a", "both.key"), LOG,
                                          json.dumps(behaviours)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE)
    assert standin["server"].stdout.readline().strip() == "ready"
    return standin["kernel"]


def stop_standin():
    if standin.get("server"):
        standin["server"].kill()
        standin["server"] = None


def give_key(s):
    """The line `key` and the made-up key: kept in memory only, and every line after it goes to the model."""
    s.keys("key\n")
    s.keys(KEY + "\n")


def picked(s, line, number):
    """A line that the stand-in answers with pick_look and this number: waits for the kernel's row about it."""
    s.mark()
    s.keys(line + "\n")
    s.wait_text("Kernel: this is look", "Kernel: the model asked for look")
    s.chat.pick(number)
