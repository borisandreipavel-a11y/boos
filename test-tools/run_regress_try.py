"""Runs the earlier test suites one after another against the project's kernel (and the stand-in copy for the
model's cases), and prints each one's end. Usage: python run_regress_try.py > out-regress-try.txt"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

from suites import MODEL_KINDS  # the same list run_tests.py runs
# The model's cases type "key" and "ask" as ordinary lines: they boot with a disk that is not divided, so that
# no notebook is opened and nothing is asked at the start.
UNDIVIDED = {"DIVIDED_DISK": ""}
RUNS = [
    (["test_key.py"], {}),
    (["test_name3.py"], {}),
    (["test_key_memory.py"], {}),
    (["test_secret_keyed.py"], {}),
    (["test_more.py", "regress-try"], {}),
    (["test_shift.py", "regress-try-shift"], {}),
    (["boot_count.py", "regress-try-count"], {}),
    (["test_model.py", MODEL_KINDS], UNDIVIDED),
]
for run, env in RUNS:
    started = time.time()
    print("=== " + " ".join(r if len(r) < 60 else r[:40] + "..." for r in run), flush=True)
    done = subprocess.run([sys.executable] + run, cwd=HERE, capture_output=True, text=True, env=dict(os.environ, **env))
    lines = (done.stdout + done.stderr).splitlines()
    for line in lines:
        if any(word in line for word in ("FAILURES", "wrong", "NOT", "MEANT", "meant:", "got:", "lines to the prompt", "bytes that are",
                                         "Traceback", "Error", "error", "failed", "  Free memory", "  Lock:", "VAIN", "never",
                                         "all as meant", "said lines", "times:")):
            print("  " + line, flush=True)
    print("  (exit %d, %d s, %d lines of output)" % (done.returncode, time.time() - started, len(lines)), flush=True)
print("=== done", flush=True)
