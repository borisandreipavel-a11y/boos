"""Breaks on purpose for the try of a key, each alone, made in the stand-in copy of the project by test_try.py
(BREAK names one of its TRY_BREAKS). For each: the scenario that should catch it runs with the broken copy.
The project itself is only read.
Usage: python run_try_breaks.py [break ...]   (default: all)"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WHICH = {
    "the refused key not wiped": "setup",
    "the refused key kept": "setup",
    "the try lends the kept key": "refused",
    "keys typed during the try taken": "during",
    "nothing said about signs not taken": "during",
    "403 taken as unknown": "answers",
    "a reasonless 401 not taken as unknown": "answers",
    "a 403 page taken as known": "answers",
    "a key that cannot be tried not kept": "nocard",
    "the try's answer not handed to the onboarding": "refused",
}
caught = 0
names = sys.argv[1:] or list(WHICH)
for name in names:
    run = subprocess.run([sys.executable, "test_try.py", WHICH[name]], cwd=HERE, capture_output=True, text=True,
                         env=dict(os.environ, BREAK=name), timeout=900)
    lines = run.stdout.splitlines()
    last = [line for line in lines if line.startswith("FAILURES:")]
    built = any(line.startswith("BREAK ON PURPOSE") for line in lines)
    is_caught = built and bool(last) and last[-1] != "FAILURES: none"
    caught += is_caught
    how = [line.strip() for line in lines if any(w in line for w in ("dots wrong", "NOT AS MEANT", "SAW", "not as meant", "VAIN", "problems", "["))]
    print("%-46s %s | %s" % (name, "caught" if is_caught else ("NOT CAUGHT" if built else "THE BREAK WAS NOT MADE"),
                             (how[0] if how else (last[-1] if last else (run.stdout + run.stderr)[-300:]))[:150]), flush=True)
print("caught %d of %d" % (caught, len(names)))
