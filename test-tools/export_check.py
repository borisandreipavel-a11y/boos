"""A clean export of one commit: unpack it, compare it with the working files (for the commit the working tree is
at), build the interpreter and the kernel in it from nothing, and report sizes, warnings and helper programs.
Usage: python export_check.py <commit> [compare]"""
import os
import shutil
import subprocess
import sys

from places import PROJECT, WORK

commit = sys.argv[1]
folder = os.path.join(WORK, "export-" + commit)
shutil.rmtree(folder, ignore_errors=True)
os.makedirs(folder)
archive = subprocess.run(["git", "archive", "--format=tar", commit], cwd=PROJECT, capture_output=True, check=True).stdout
subprocess.run(["tar", "-x", "-C", folder.replace("\\", "/")], input=archive, check=True)

files = []
for root, _, names in os.walk(folder):
    for name in names:
        files.append(os.path.relpath(os.path.join(root, name), folder))
print("files in the export:", len(files))
built = [f for f in files if f.endswith((".efi", ".wasm", ".img", ".exe")) or f.startswith(("target", "esp")) or f == "CLAUDE.md"]
print("built files, disk files or the private file in it:", built or "none")

if len(sys.argv) > 2 and sys.argv[2] == "compare":
    same = ends = other = 0
    others = []
    for f in files:
        a = open(os.path.join(folder, f), "rb").read()
        b = open(os.path.join(PROJECT, f), "rb").read()
        if a == b:
            same += 1
        elif a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n"):
            ends += 1
        else:
            other += 1
            others.append(f)
    print("against the working files: %d identical, %d differ in line ends only, %d differ otherwise %s" % (same, ends, other, others[:5]))

inner = os.path.join(folder, "interpreter")
first = subprocess.run(["cargo", "build", "--release"], cwd=inner, capture_output=True, text=True)
second = subprocess.run(["cargo", "build", "-v"], cwd=folder, capture_output=True, text=True)
# Which crates were built at the fast setting: cargo's command line for each crate says so.
for crate in ("password_key", "hmac", "sha2", "chacha20poly1305", "boos"):
    lines = [l for l in second.stderr.splitlines() if "--crate-name " + crate + " " in l]
    print("%s: %s" % (crate, "not built" if not lines else ("opt-level=2" if "opt-level=2" in lines[0] else "plain (no opt-level)")))
for label, run in (("interpreter", first), ("kernel", second)):
    timing = [l.strip() for l in run.stderr.splitlines() if "Finished" in l]
    warnings = [l for l in run.stderr.splitlines() if l.startswith("warning")]
    print("%s: exit %d, %s, warnings %d" % (label, run.returncode, timing[-1] if timing else "?", len(warnings)))
    if run.returncode:
        print(run.stderr[-2000:])
        sys.exit(1)
wasm = os.path.join(inner, "target", "wasm32-unknown-unknown", "release", "interpreter.wasm")
kernel = os.path.join(folder, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
w = open(wasm, "rb").read()
project_wasm = open(os.path.join(PROJECT, "interpreter", "target", "wasm32-unknown-unknown", "release", "interpreter.wasm"), "rb").read()
print("interpreter %d bytes, byte for byte the project's: %s, inside the exported kernel: %s" % (len(w), w == project_wasm, w in open(kernel, "rb").read()))
print("kernel %d bytes" % os.path.getsize(kernel))
helpers = []
for t in (os.path.join(folder, "target"), os.path.join(inner, "target")):
    for root, dirs, names in os.walk(t):
        # Cargo keeps every crate's compiled library under a folder called "build"; a helper program would
        # show as a program file or as a build script's folder.
        for n in names + dirs:
            if n.endswith(".exe") or n.startswith("build-script") or n.startswith("build_script"):
                helpers.append(os.path.relpath(os.path.join(root, n), folder))
print("helper programs or build folders made along the way:", helpers or "none")
print("KERNEL_FILE=" + kernel)
