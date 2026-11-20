"""A copy of the project for the tests of the kernel's own lines that need the kernel changed: a failure made on
purpose, or a break on purpose. The copy is a folder of the test work (never inside the project), with a build
folder of its own that is kept, so that a change rebuilds only the kernel's own code. The project's built
interpreter is copied in, unchanged.

    kernel = build({"main.rs": [(old, new)], "lines.rs": [...]})

Each `old` must stand exactly once in the file (line ends as "\\n"). Nothing runs when this file is imported."""
import os
import shutil
import subprocess
import sys

from places import PROJECT, RUNS, WASM

COPY = os.path.join(RUNS, "lines-copy")


def fresh():
    """Brings the copy's sources up to date with the project's; keeps its build folder and its vendor folder."""
    os.makedirs(COPY, exist_ok=True)
    for name in ["src", ".cargo", "password-key", "vendor"]:
        target = os.path.join(COPY, name)
        if name == "vendor" and os.path.exists(target):
            continue
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(PROJECT, name), target)
    # copytree keeps the files' old times, and cargo would then take an earlier build (with another change in it)
    # for up to date. New times make it build the copy's sources as they are now.
    for root, _, files in os.walk(os.path.join(COPY, "src")):
        for file in files:
            os.utime(os.path.join(root, file), None)
    os.makedirs(os.path.dirname(os.path.join(COPY, WASM)), exist_ok=True)
    shutil.copyfile(os.path.join(PROJECT, WASM), os.path.join(COPY, WASM))
    for name in ["Cargo.toml", "Cargo.lock"]:
        shutil.copyfile(os.path.join(PROJECT, name), os.path.join(COPY, name))


def build(changes):
    """Makes the copy, changes it, builds its kernel, and gives the kernel file's path."""
    fresh()
    for file, swaps in changes.items():
        path = os.path.join(COPY, "src", file)
        text = open(path, "rb").read().decode().replace("\r\n", "\n")
        for old, new in swaps:
            if text.count(old) != 1:
                print("THE COPY CANNOT BE CHANGED: %r stands %d times in %s" % (old[:70], text.count(old), file))
                sys.exit(1)
            text = text.replace(old, new)
        open(path, "w", newline="").write(text)
    # Rust's own linker was once refused by Windows and let through on the next try (docs/testing.md).
    for _ in range(2):
        built = subprocess.run(["cargo", "build"], cwd=COPY, capture_output=True, text=True)
        if built.returncode == 0:
            return os.path.join(COPY, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
    print("THE COPY'S BUILD FAILED")
    print(built.stderr[-3000:])
    sys.exit(1)
