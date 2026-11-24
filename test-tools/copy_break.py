"""A break on purpose made in a copy of the project and built there, for a test that boots the copy's kernel through
KERNEL_FILE. The project itself is only read. Used by run_key_breaks.py, run_look_breaks.py and run_tests.py.

A break is (file in src, old text, new text), and the old text must stand exactly once in the file. The copy keeps
its build folder, so every build after the first takes seconds. It lies in BOOS_COPIES when that is set (run_tests.py
shares one copy among the tests it runs at once), and in this checkout's work folder otherwise. The copy is changed
and built in the build turn (turns.py), and its kernel is copied out for the test before the turn is given back."""
import os
import shutil
import subprocess

from places import PROJECT, RUNS, WASM
from turns import build_turn

COPY = os.path.join(os.environ.get("BOOS_COPIES") or RUNS, "break-copy")
COPY_KERNEL = os.path.join(COPY, "target", "x86_64-unknown-uefi", "debug", "boos.efi")


class NotMade(Exception):
    """The break cannot be made: its old text does not stand exactly once in the file."""


def swapped(text, old, new):
    """`text` with the break made in it. Breaks are written with plain line ends; a file with Windows ones gets them."""
    if "\r\n" in text:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    count = text.count(old)
    if count != 1:
        raise NotMade("its old text stands %d times in %s, not once: %r" % (count, "the file", old[:70]))
    return text.replace(old, new)


def check(file, old, new):
    """Raises NotMade if the break cannot be made in the project's own source as it is now."""
    swapped(open(os.path.join(PROJECT, "src", file), "rb").read().decode(), old, new)


def fresh():
    """Brings the copy's sources up to date with the project's; keeps the copy's build folder and its vendor folder."""
    os.makedirs(COPY, exist_ok=True)
    for name in ["src", "password-key", "pictures", ".cargo"]:
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


def build_copy():
    """Builds the copy as it stands. The old kernel is removed first, so that a failed build can never leave the
    previous break's kernel to be booted."""
    if os.path.exists(COPY_KERNEL):
        os.remove(COPY_KERNEL)
    built = subprocess.run(["cargo", "build"], cwd=COPY, capture_output=True, text=True)
    if built.returncode != 0 or not os.path.exists(COPY_KERNEL):
        raise RuntimeError("the copy did not build: " + built.stderr[-600:])


def make(file, old, new, kernel_out):
    """Makes the break in a fresh copy, builds it, copies its kernel to `kernel_out` and gives back that path.
    Raises NotMade, or RuntimeError when the copy does not build."""
    with build_turn():
        fresh()
        path = os.path.join(COPY, "src", file)
        text = open(path, "rb").read().decode()
        open(path, "wb").write(swapped(text, old, new).encode())
        build_copy()
        os.makedirs(os.path.dirname(kernel_out), exist_ok=True)
        shutil.copyfile(COPY_KERNEL, kernel_out)
    return kernel_out


def warm():
    """Builds the copy once without any break, so that the first break builds in seconds."""
    with build_turn():
        fresh()
        build_copy()
