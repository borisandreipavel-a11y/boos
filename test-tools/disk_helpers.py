"""Helpers for the disk tests: making test disk files, QEMU options, changing
the kernel's source for a test, and booting."""
import hashlib
import os
import subprocess
import time

from boot import Machine, HERE, PROJECT, QEMU_IMG
from restore import SRC

from places import QEMU_IO, RUNS
os.makedirs(RUNS, exist_ok=True)


def make(name, size, fmt="raw"):
    path = os.path.join(RUNS, name)
    if os.path.exists(path):
        os.remove(path)
    subprocess.run([QEMU_IMG, "create", "-f", fmt, path, size], check=True, stdout=subprocess.DEVNULL)
    return path


def put(path, offset, data):
    """Writes bytes into a raw disk file."""
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(data)


def put_pattern(path, fmt, offset, sign, length=512):
    """Writes `length` bytes of one sign into a disk file of any format, with QEMU's own tool."""
    r = subprocess.run([QEMU_IO, "-f", fmt, "-c", "write -q -P %d %d %d" % (ord(sign), offset, length), path], capture_output=True, text=True)
    assert r.returncode == 0 and "rror" not in r.stdout + r.stderr, r.stdout + r.stderr


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            h.update(piece)
    return h.hexdigest()


def ahci(*devices):
    out = ["-device", "ich9-ahci,id=ahci0"]
    for number, (kind, path, fmt, where, more) in enumerate(devices):
        if kind == "disk":
            out += ["-drive", "if=none,id=d%d,format=%s,file=%s" % (number, fmt, path), "-device", "ide-hd,drive=d%d,bus=ahci0.%d%s" % (number, where, more)]
        else:
            out += ["-device", "ide-cd,bus=ahci0.%d" % where]
    return out


def one_disk(path, fmt="raw", more=""):
    return ahci(("disk", path, fmt, 0, more))


def build():
    r = subprocess.run(["cargo", "build"], cwd=PROJECT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1200:]


def change(file, old, new):
    path = os.path.join(SRC, file)
    text = open(path, newline="").read()
    assert text.count(old) == 1, (old[:80], text.count(old))
    open(path, "w", newline="").write(text.replace(old, new))
    os.utime(path, (time.time(), time.time()))


def boot(tag, seconds=150, **options):
    """Boots to the prompt (or to a failure) and gives back the kernel's lines and how many bytes were not plain text."""
    m = Machine(tag, **options)
    try:
        deadline = time.time() + seconds
        while time.time() < deadline:
            s = m.serial()
            if b"repeated here:" in s or b"\nKernel panic" in s or b"\nCPU fault" in s or m.process.poll() is not None:
                break
            time.sleep(0.1)
    finally:
        s = m.quit()
    ours = s[s.find(b"Hello from my kernel!"):]
    odd = len([b for b in ours if not (32 <= b <= 126 or b in (13, 10))])
    return ours.decode(errors="replace").split("\r\n"), odd


def disk_lines(lines):
    return [l for l in lines if l.startswith(("Disk", "Kernel panic", "CPU fault", "PROBE"))]
