"""Builds the interpreter and then the kernel, in that order, and stops loudly if either fails.
Usage: python build_all.py [folder]   (default: the project)
Prints the two files' sizes. Used before every test boot, so that the kernel never carries a stale interpreter."""
import hashlib
import os
import subprocess
import sys

from places import PROJECT


def build(folder=PROJECT, quiet=False):
    inner = os.path.join(folder, "interpreter")
    first = subprocess.run(["cargo", "build", "--release"], cwd=inner, capture_output=True, text=True)
    if first.returncode != 0:
        print("THE INTERPRETER'S BUILD FAILED")
        print(first.stderr[-3000:])
        sys.exit(1)
    wasm = os.path.join(inner, "target", "wasm32-unknown-unknown", "release", "interpreter.wasm")
    second = subprocess.run(["cargo", "build"], cwd=folder, capture_output=True, text=True)
    if second.returncode != 0:
        print("THE KERNEL'S BUILD FAILED")
        print(second.stderr[-3000:])
        sys.exit(1)
    kernel = os.path.join(folder, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
    data = open(wasm, "rb").read()
    # The kernel must hold exactly this interpreter.
    if data not in open(kernel, "rb").read():
        print("THE KERNEL DOES NOT HOLD THE INTERPRETER THAT WAS JUST BUILT")
        sys.exit(1)
    warnings = [line for line in (first.stderr + second.stderr).split("\n") if line.startswith("warning")]
    if not quiet:
        print("interpreter: %d bytes, sha256 %s" % (len(data), hashlib.sha256(data).hexdigest()[:16]))
        print("kernel: %d bytes; warnings: %d" % (os.path.getsize(kernel), len(warnings)))
        for line in warnings[:5]:
            print("  " + line)
    return wasm, kernel


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else PROJECT)
