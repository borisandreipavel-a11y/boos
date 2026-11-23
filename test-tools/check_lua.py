"""Runs a Lua script of ours in place of the greeting script, in a copy of the project only (under the tests' work
folder), and prints the App: and Interpreter: lines of each boot. Used to check what the instruction text tells
the model about the interpreter, and how the script at startup reports a stop. The scripts used so far are in
lua/: claims.lua (the libraries, the cuts, random numbers), seed.lua (math.randomseed), startup_mistake.lua and
startup_loop.lua (a stopped script at startup), numbers.lua (numbers with a point, and the words Lua keeps for itself,
which an app's input may not be named after).

Usage: python check_lua.py <script file> [boots]"""
import os
import re
import shutil
import subprocess
import sys
import time

from boot import Machine
from places import PROJECT, RUNS, WASM

COPY = os.path.join(RUNS, "lua-copy")


def build(script):
    os.makedirs(COPY, exist_ok=True)
    for name in ["src", "vendor", ".cargo", "password-key"]:
        target = os.path.join(COPY, name)
        if name == "vendor" and os.path.exists(target):
            continue
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(PROJECT, name), target)
    for root, _, files in os.walk(os.path.join(COPY, "src")):
        for file in files:
            os.utime(os.path.join(root, file), None)
    os.makedirs(os.path.dirname(os.path.join(COPY, WASM)), exist_ok=True)
    shutil.copyfile(os.path.join(PROJECT, WASM), os.path.join(COPY, WASM))
    for name in ["Cargo.toml", "Cargo.lock"]:
        shutil.copyfile(os.path.join(PROJECT, name), os.path.join(COPY, name))
    path = os.path.join(COPY, "src", "interpreter.rs")
    code = open(path, "rb").read().decode("utf-8")
    assert '"#' not in script
    new, count = re.subn(r"pub const GREETING_SCRIPT: &str = concat!\(.*?\n\);", lambda _: 'pub const GREETING_SCRIPT: &str = r#"' + script + '"#;', code, flags=re.S)
    assert count == 1
    open(path, "w", newline="", encoding="utf-8").write(new)
    built = subprocess.run(["cargo", "build"], cwd=COPY, capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stderr[-3000:])
        sys.exit(1)
    return os.path.join(COPY, "target", "x86_64-unknown-uefi", "debug", "boos.efi")


def main():
    script = open(sys.argv[1], encoding="utf-8").read()
    boots = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    kernel = build(script)
    for number in range(boots):
        machine = Machine("lua-check-%d" % number, kernel=kernel)
        try:
            machine.wait_for(b"JSON:", seconds=60)
            time.sleep(0.5)
        finally:
            raw = machine.quit()
        print("--- boot %d" % (number + 1))
        for line in raw.decode(errors="replace").split("\r\n"):
            if line.startswith(("App:", "Interpreter:")):
                print(line)


main()
