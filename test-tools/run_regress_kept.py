"""Everything for apps kept on the disk, then the suites that this change could touch, one after another, and prints
each one's end: both builds; test_apps_kept.py with every scenario, the older kernel and the times included; the
app test with every kind of answer on a disk without a notebook, where nothing is kept; a first start that makes an
app on a fresh divided disk, both ways; the try of a key and the locked key against the stand-in; the look's
test; and run_regress_try.py's list. Together with this file's own suites, that is every suite of
run_regress_apps.py and run_regress_look.py, each once.
Usage: python run_regress_kept.py > out-regress-kept.txt"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

APP_KINDS = ("app,appfenced,appprose,appopen,appclose,apptwo,appmarksonly,appcut,appfiltered,appthink,appnull,appexact,appover,"
             "appodd,appecho,apppieces,appspaces,appcrlf,appnoending,apponeline,slowapp,realrefusal,upstream,upstreambare,huge,"
             "nothttp,otherform,streamed,runshow,runprint,runcut,runcut41,runexact40,runsplit,runloop,runmemory,runmistake,"
             "runsyntax,runmanyshow,runmanyprint,runrandom,runrandom,runreal,runslow,runnil,runrecurse")
RUNS = [
    ["build_all.py"],
    ["test_apps_kept.py", "first", "make", "echo", "outside", "requests", "look", "small", "damaged", "full", "failing", "cut", "older", "times"],
    ["test_app.py", APP_KINDS, "dump"],
    ["test_app.py", "nocard"],
    ["test_app_first_start.py", "keylater"],
    ["test_app_first_start.py", "keyfirst"],
    ["test_try.py"],
    ["test_key_model.py"],
    ["test_look.py"],
    ["run_regress_try.py"],
]
WORDS = ("FAILURES", "NOT", "wrong", "all as meant", "said lines", "random numbers", "memory after", "Traceback", "Error",
         "stand-in", "requests", "bytes", "lines to the prompt", "Free memory", "Lock:", "interpreter:", "kernel:", "===", "(exit",
         "took", "keeping", "opening")
for run in RUNS:
    started = time.time()
    print("=== " + " ".join(r if len(r) < 60 else r[:40] + "..." for r in run), flush=True)
    done = subprocess.run([sys.executable] + run, cwd=HERE, capture_output=True, text=True)
    lines = (done.stdout + done.stderr).splitlines()
    for line in lines:
        if any(word in line for word in WORDS) and "every dot right" not in line:
            print("  " + line, flush=True)
    print("  (exit %d, %d s, %d lines of output)" % (done.returncode, time.time() - started, len(lines)), flush=True)
print("=== done", flush=True)
