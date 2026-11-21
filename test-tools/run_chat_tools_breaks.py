"""Each break on purpose of chat_tools_breaks.py in turn, alone, in the stand-in copy (test_chat_tools.py with BREAK
set), with the scenario that should catch it. A break counts as caught when test_chat_tools.py reports a failure; a
break that cannot be made (its text is not found once in the source) counts as not caught.
Usage: python run_chat_tools_breaks.py [name ...] > out-chat-tools-breaks.txt"""
import os
import subprocess
import sys
import time

from chat_tools_breaks import BREAKS, CATCH

HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or list(BREAKS)
caught = []
for name in names:
    started = time.time()
    done = subprocess.run([sys.executable, "test_chat_tools.py", CATCH[name]], cwd=HERE, capture_output=True, text=True,
                          env=dict(os.environ, BREAK=name))
    lines = (done.stdout + done.stderr).splitlines()
    verdict = [line for line in lines if line.startswith("FAILURES")]
    found = bool(verdict) and "all as meant" not in verdict[-1]
    broken_build = any("BUILD FAILED" in line or "DID NOT BUILD" in line for line in lines)
    unmade = any("AssertionError" in line for line in lines) and not verdict
    if found and not broken_build:
        caught.append(name)
    state = "CAUGHT" if found and not broken_build else ("THE COPY DID NOT BUILD" if broken_build else
                                                         ("COULD NOT BE MADE" if unmade else "NOT CAUGHT"))
    print("%-16s %s (%d s)" % (name, state, time.time() - started), flush=True)
    for line in lines:
        if line.startswith(("FAILURES", "BREAK", "Traceback", "AssertionError")) or "NOT AS MEANT" in line or "dots wrong" in line or "got " in line:
            print("    " + line[:200], flush=True)
print("caught %d of %d" % (len(caught), len(names)), flush=True)
