"""Each break on purpose of apps_kept_breaks.py in turn, alone, in the stand-in copy (test_apps_kept.py with BREAK
set), with the scenario that should catch it. A break counts as caught when test_apps_kept.py reports a failure.
Afterwards the copy is built once more without any break, by the next ordinary test.
Usage: python run_apps_kept_breaks.py [name ...] > out-kept-breaks.txt"""
import os
import subprocess
import sys
import time

from apps_kept_breaks import BREAKS, CATCH

HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or list(BREAKS)
caught = []
for name in names:
    started = time.time()
    done = subprocess.run([sys.executable, "test_apps_kept.py", CATCH[name]], cwd=HERE, capture_output=True, text=True,
                          env=dict(os.environ, BREAK=name))
    lines = (done.stdout + done.stderr).splitlines()
    verdict = [line for line in lines if line.startswith("FAILURES")]
    found = bool(verdict) and "all as meant" not in verdict[-1]
    broken_build = any("BUILD FAILED" in line or "DID NOT BUILD" in line for line in lines)
    if found and not broken_build:
        caught.append(name)
    print("%-18s %s (%d s)" % (name, "CAUGHT" if found and not broken_build else ("THE COPY DID NOT BUILD" if broken_build else "NOT CAUGHT"),
                                time.time() - started), flush=True)
    for line in lines:
        if line.startswith(("FAILURES", "BREAK", "Traceback")) or "NOT AS MEANT" in line or "dots wrong" in line or "got " in line:
            print("    " + line[:200], flush=True)
print("caught %d of %d" % (len(caught), len(names)), flush=True)
