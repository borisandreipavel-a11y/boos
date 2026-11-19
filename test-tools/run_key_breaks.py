"""Breaks on purpose for the key and the password, each alone, in a copy of the project (runs/key-break-copy). For
each: copy the project's sources afresh, make the break, build, and run the test that should catch it with the
copy's kernel. The project itself is only read.
Usage: python run_key_breaks.py [break ...]   (default: all)"""
import os
import shutil
import subprocess
import sys

from places import HERE, PROJECT, RUNS, WASM

COPY = os.path.join(RUNS, "key-break-copy")
KERNEL = os.path.join(COPY, "target", "x86_64-unknown-uefi", "debug", "boos.efi")

MEMORY = [sys.executable, "test_key_memory.py"]
BREAKS = {
    "the typed signs not wiped": ("chat.rs", "            wipe(typed);\n\n            // Repeated in the terminal in one go, like any other rows.",
                                  "\n            // Repeated in the terminal in one go, like any other rows.", MEMORY),
    "the password not forgotten after locking": ("onboarding.rs", "    let locked = secret_lock();\n    password_forget();\n",
                                                 "    let locked = secret_lock();\n", MEMORY),
    "the locking's own rooms not wiped": ("secret.rs", "    wipe(&mut secret);\n    wipe(&mut password);\n    locked\n", "    locked\n", MEMORY),
    "the unlocking's room not wiped": ("secret.rs", "    wipe(&mut room);\n    kept\n", "    kept\n", MEMORY),
    "no least length": ("onboarding.rs", "    if typed.len() < PASSWORD_LEAST {", "    if false {", [sys.executable, "test_key.py", "locked"]),
    "the second password not compared": ("onboarding.rs", "    if !password_same(typed) {", "    if false {", [sys.executable, "test_key.py", "locked"]),
    "the key typed as a plain line": ("onboarding.rs", "matches!(waiting(), Waiting::Key | Waiting::NewPassword",
                                      "matches!(waiting(), Waiting::NewPassword", [sys.executable, "test_key.py", "locked"]),
    "the unlocked key not kept": ("secret.rs", "        Ok(length) => Ok(secret_keep(&room[..length])),", "        Ok(length) => Ok(length),",
                                  [sys.executable, "test_key.py", "locked"]),
    "no key not noted": ("onboarding.rs", "    if unsafe { KEY_ANSWERED } {\n        return Vec::new();\n    }\n    match notebook_keep(KEY_ENTRY, &[]) {",
                         "    if true {\n        return Vec::new();\n    }\n    match notebook_keep(KEY_ENTRY, &[]) {", [sys.executable, "test_name3.py", "first"]),
    "every refusal taken for a wrong password": ("onboarding.rs", "        Err(reason) if reason == NOT_UNLOCKED => vec![", "        Err(_) if true => vec![",
                                                 [sys.executable, "test_key.py", "odd"]),
    "the question for a new key not used at setup": ("onboarding.rs", "    if setting_up && !locked_key().is_empty() {", "    if false {",
                                                     [sys.executable, "test_key.py", "stays"]),
}


def fresh():
    os.makedirs(COPY, exist_ok=True)
    for name in ["src", "password-key", ".cargo"]:
        shutil.rmtree(os.path.join(COPY, name), ignore_errors=True)
        shutil.copytree(os.path.join(PROJECT, name), os.path.join(COPY, name))
        # copytree keeps the files' old times, and cargo would then take an earlier build for up to date.
        for root, _, files in os.walk(os.path.join(COPY, name)):
            for file in files:
                os.utime(os.path.join(root, file), None)
    if not os.path.exists(os.path.join(COPY, "vendor")):
        shutil.copytree(os.path.join(PROJECT, "vendor"), os.path.join(COPY, "vendor"))
    os.makedirs(os.path.dirname(os.path.join(COPY, WASM)), exist_ok=True)
    shutil.copyfile(os.path.join(PROJECT, WASM), os.path.join(COPY, WASM))
    for name in ["Cargo.toml", "Cargo.lock"]:
        shutil.copyfile(os.path.join(PROJECT, name), os.path.join(COPY, name))


def patch(path, old, new):
    text = open(path, "rb").read().decode()
    if "\r\n" in text:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    assert text.count(old) == 1, (path, old[:60], text.count(old))
    open(path, "wb").write(text.replace(old, new).encode())


caught = 0
names = sys.argv[1:] or list(BREAKS)
for name in names:
    file, old, new, command = BREAKS[name]
    fresh()
    patch(os.path.join(COPY, "src", file), old, new)
    built = subprocess.run(["cargo", "build"], cwd=COPY, capture_output=True, text=True)
    if built.returncode != 0:
        print("%-46s THE BREAK DID NOT BUILD: %s" % (name, built.stderr[-400:]))
        continue
    run = subprocess.run(command, cwd=HERE, capture_output=True, text=True, env=dict(os.environ, KERNEL_FILE=KERNEL))
    last = [line for line in run.stdout.splitlines() if line.startswith("FAILURES:")]
    is_caught = bool(last) and last[-1] != "FAILURES: none"
    caught += is_caught
    print("%-46s %s | %s" % (name, "caught" if is_caught else "NOT CAUGHT", (last[-1] if last else run.stdout[-300:])[:170]), flush=True)
print("caught %d of %d" % (caught, len(names)))
