"""Runs the earlier test suites one after another against the project's kernel (and the stand-in copy for the model's
cases and the try of a key), then the look's own test, and prints each one's end.
Usage: python run_regress_look.py > out-regress-look.txt"""
import os
import subprocess
import sys
import time

from suites import MODEL_KINDS  # the same list run_tests.py runs
# The model's cases type "key" and "ask" as ordinary lines: they boot with a disk that is not divided, so that
# no notebook is opened and nothing is asked at the start.
UNDIVIDED = {"DIVIDED_DISK": ""}
RUNS = [
    (["test_key.py"], {}),
    (["test_name3.py"], {}),
    (["test_key_memory.py"], {}),
    (["test_secret_keyed.py"], {}),
    (["test_more.py", "regress-look"], {}),
    (["test_shift.py", "regress-look-shift"], {}),
    (["boot_count.py", "regress-look-count"], {}),
    (["test_try.py"], {}),
    (["test_key_model.py"], {}),
    (["test_model.py", MODEL_KINDS], UNDIVIDED),
    (["test_look.py"], {}),
]
for run, env in RUNS:
    started = time.time()
    print("=== " + " ".join(r if len(r) < 60 else r[:40] + "..." for r in run), flush=True)
    done = subprocess.run([sys.executable] + run, capture_output=True, text=True, env=dict(os.environ, **env))
    lines = (done.stdout + done.stderr).splitlines()
    for line in lines:
        if any(word in line for word in ("FAILURES", "wrong", "NOT", "MEANT", "meant:", "got:", "lines to the prompt", "bytes that are",
                                         "Traceback", "Error", "error", "failed", "  Free memory", "  Lock:", "VAIN", "never",
                                         "all as meant", "said lines", "times:", "panic", "fault", "NEVER", "NO ADDRESS")):
            print("  " + line, flush=True)
    print("  (exit %d, %d s, %d lines of output)" % (done.returncode, time.time() - started, len(lines)), flush=True)
print("=== done", flush=True)
