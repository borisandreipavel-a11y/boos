"""Breaks on purpose for the key and the password, each alone, in a copy of the project (copy_break.py). For each:
copy the project's sources afresh, make the break, build, and run the test that should catch it with the copy's
kernel. The project itself is only read. A break whose old text no longer stands once in its file is reported as not
made, and the others still run.
Usage: python run_key_breaks.py [break ...]   (default: all)
BREAKS is data: run_tests.py runs the same breaks."""
import os
import subprocess
import sys

MEMORY = ["test_key_memory.py"]
LOCKED = ["test_key.py", "locked"]
# name: (file in src, old text, new text, the test that should catch it)
BREAKS = {
    "the typed signs not wiped": ("chat.rs", "            wipe(typed);\n            kernel_rows(&rows);\n", "            kernel_rows(&rows);\n", MEMORY),
    "the password not forgotten after locking": ("onboarding.rs", "    let locked = secret_lock();\n    password_forget();\n",
                                                 "    let locked = secret_lock();\n", MEMORY),
    "the locking's own rooms not wiped": ("secret.rs", "    wipe(&mut secret);\n    wipe(&mut password);\n    locked\n", "    locked\n", MEMORY),
    "the unlocking's room not wiped": ("secret.rs", "    wipe(&mut room);\n    kept\n", "    kept\n", MEMORY),
    "no least length": ("onboarding.rs", "    if typed.len() < PASSWORD_LEAST {", "    if false {", LOCKED),
    "the second password not compared": ("onboarding.rs", "    if !password_same(typed) {", "    if false {", LOCKED),
    "the key typed as a plain line": ("onboarding.rs", "matches!(waiting(), Waiting::Key | Waiting::Trying", "matches!(waiting(), Waiting::Trying", LOCKED),
    "the unlocked key not kept": ("secret.rs", "        Ok(length) => Ok(secret_keep(&room[..length])),", "        Ok(length) => Ok(length),", LOCKED),
    "no key not noted": ("onboarding.rs", "    if unsafe { KEY_ANSWERED } {\n        return Vec::new();\n    }\n    match notebook_keep(KEY_ENTRY, &[]) {",
                         "    if true {\n        return Vec::new();\n    }\n    match notebook_keep(KEY_ENTRY, &[]) {", ["test_name3.py", "first"]),
    "every refusal taken for a wrong password": ("onboarding.rs", "        Err(reason) if reason == NOT_UNLOCKED => vec![", "        Err(_) if true => vec![",
                                                 ["test_key.py", "odd"]),
    "the question for a new key not used at setup": ("onboarding.rs",
                                                     "    String::from(if setting_up && !locked_key().is_empty() { KEY_QUESTION_AGAIN } else { KEY_QUESTION })",
                                                     "    String::from(if false { KEY_QUESTION_AGAIN } else { KEY_QUESTION })", ["test_key.py", "stays"]),
}
# Known not to be caught (docs/testing.md): what is left in those rooms has been written over by the time of the dump.
MISSES = {"the locking's own rooms not wiped", "the unlocking's room not wiped"}


def main():
    from copy_break import NotMade, make
    from places import HERE, RUNS
    kernel_out = os.path.join(RUNS, "key-break-kernel.efi")
    caught = not_made = 0
    names = sys.argv[1:] or list(BREAKS)
    for name in names:
        file, old, new, command = BREAKS[name]
        try:
            kernel = make(file, old, new, kernel_out)
        except NotMade as reason:
            not_made += 1
            print("%-46s THE BREAK CANNOT BE MADE: %s" % (name, reason), flush=True)
            continue
        except RuntimeError as reason:
            not_made += 1
            print("%-46s THE BREAK DID NOT BUILD: %s" % (name, str(reason)[-400:]), flush=True)
            continue
        run = subprocess.run([sys.executable] + command, cwd=HERE, capture_output=True, text=True,
                             env=dict(os.environ, KERNEL_FILE=kernel))
        last = [line for line in run.stdout.splitlines() if line.startswith("FAILURES:")]
        is_caught = bool(last) and last[-1] != "FAILURES: none"
        caught += is_caught
        print("%-46s %s | %s" % (name, "caught" if is_caught else ("NOT CAUGHT (documented)" if name in MISSES else "NOT CAUGHT"),
                                 (last[-1] if last else run.stdout[-300:])[:170]), flush=True)
    print("caught %d of %d%s" % (caught, len(names), "; %d not made" % not_made if not_made else ""))
    sys.exit(1 if not_made else 0)


if __name__ == "__main__":
    main()
