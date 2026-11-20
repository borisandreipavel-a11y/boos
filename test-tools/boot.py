"""Boots the kernel in QEMU without a window, types keys through QEMU's
monitor, saves pictures of the screen, and gives back what the kernel printed.

Used as a module by the test scripts in this folder."""

import contextlib
import os
import shutil
import socket
import subprocess
import time

from places import FIRMWARE, HERE, KERNEL, PROJECT, QEMU, QEMU_IMG, RUNS  # noqa: F401 (others import them from here)
from turns import memory_turn
HINT = b"repeated here:"

KEY_NAMES = {
    " ": "spc", "-": "minus", "=": "equal", "[": "bracket_left", "]": "bracket_right",
    ";": "semicolon", "'": "apostrophe", "`": "grave_accent", "\\": "backslash",
    ",": "comma", ".": "dot", "/": "slash", "\n": "ret", "\b": "backspace",
}


def key_name(sign):
    return KEY_NAMES.get(sign, sign)


def greeted_by_qemu(connection, seconds=3.0):
    """True if what answers on the port says it is QEMU's monitor within a few seconds."""
    heard = b""
    deadline = time.time() + seconds
    connection.settimeout(0.3)
    while time.time() < deadline and b"QEMU" not in heard:
        try:
            piece = connection.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            return False
        if not piece:
            return False
        heard += piece
    return b"QEMU" in heard


class Machine:
    def __init__(self, tag, extra=None, port=None, memory="256M", network=True, kernel=KERNEL, disk=True):
        # The monitor's port is asked of Windows for every boot unless a test names one,
        # so that tests run at once from two checkouts never share it (see ports.py).
        if port is None:
            from ports import free_port
            port = free_port()
        self.port = port
        self.tag = tag
        self.folder = os.path.join(RUNS, tag)
        shutil.rmtree(self.folder, ignore_errors=True)
        os.makedirs(os.path.join(self.folder, "esp", "EFI", "BOOT"))
        shutil.copyfile(kernel, os.path.join(self.folder, "esp", "EFI", "BOOT", "BOOTX64.EFI"))
        self.serial_path = os.path.join(self.folder, "serial.txt")
        command = [QEMU, "-m", memory, "-cpu", "qemu64,+rdrand"]
        if network:
            # network="open" lets the kernel reach this computer (and beyond); only for kernels whose
            # page fetch was pointed at a test server, and for a deliberate fetch from the real site.
            fence = "" if network == "open" else ",restrict=on"
            command += ["-netdev", "user,id=net0" + fence, "-device", "virtio-net-pci,netdev=net0"]
        else:
            command += ["-net", "none"]
        if disk:
            # Every test gets a disk file of its own. Never the project's.
            self.disk_path = os.path.join(self.folder, "disk.img")
            command += disk_options(self.disk_path)
            if os.environ.get("DIVIDED_DISK"):
                # The test's disk is divided into parts, so that the kernel has a part of its own to keep things in.
                from gpt import build
                build(self.disk_path)
        command += [
            "-drive", "if=pflash,format=raw,readonly=on,file=" + FIRMWARE,
            "-drive", "format=raw,file=fat:rw:" + os.path.join(self.folder, "esp"),
            "-serial", "file:" + self.serial_path,
            "-display", "none", "-no-reboot",
            "-monitor", "tcp:127.0.0.1:%d,server=on,wait=off" % port,
        ]
        command += extra or []
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.monitor = None
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.process.poll() is not None:
                # QEMU stopped at once: most likely another program took the port first.
                break
            try:
                candidate = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                time.sleep(0.2)
                continue
            # Only QEMU's monitor greets with "QEMU". Anything else holds the port by mistake,
            # and the test must not type keys into it.
            if greeted_by_qemu(candidate):
                self.monitor = candidate
                break
            candidate.close()
            time.sleep(0.2)
        if self.monitor is None:
            self.process.kill()
            raise RuntimeError("no monitor on port %d (taken by another program, or QEMU did not start): " % port
                               + self.process.stderr.read().decode(errors="replace"))
        self.monitor.settimeout(0.3)
        self.drain()

    def drain(self):
        try:
            while self.monitor.recv(65536):
                pass
        except OSError:
            pass

    def command(self, text):
        self.monitor.sendall((text + "\n").encode())

    def serial(self):
        try:
            with open(self.serial_path, "rb") as handle:
                return handle.read()
        except OSError:
            return b""

    def wait_for(self, words, seconds=90):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if words in self.serial():
                return True
            if self.process.poll() is not None:
                return False
            time.sleep(0.25)
        return False

    def key(self, sign, pause=0.25, hold=None):
        if hold is None:
            self.command("sendkey " + key_name(sign))
        else:
            self.command("sendkey %s %d" % (key_name(sign), hold))
        time.sleep(pause)

    def named_key(self, name, pause=0.25):
        self.command("sendkey " + name)
        time.sleep(pause)

    def type(self, text, pause=0.25, hold=None):
        for sign in text:
            self.key(sign, pause, hold)

    def shot(self, name):
        path = os.path.join(self.folder, name + ".ppm")
        if os.path.exists(path):
            os.remove(path)
        self.command("screendump " + path.replace("\\", "/"))
        deadline = time.time() + 15
        last = -1
        while time.time() < deadline:
            time.sleep(0.3)
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size > 0 and size == last:
                    return path
                last = size
        raise RuntimeError("no picture saved: " + path)

    @contextlib.contextmanager
    def memory(self, name):
        """The machine's whole memory (256 MB) as bytes, inside a `with`. The copy is made, read and searched in the
        memory turn (turns.py): one test at a time on the computer, so two copies never sit in memory at once.
        Its file is removed as soon as it is read."""
        path = os.path.join(self.folder, name + ".mem")
        with memory_turn():
            self.command("pmemsave 0 0x10000000 " + path.replace("\\", "/"))
            last = -1
            for _ in range(100):
                time.sleep(0.3)
                size = os.path.getsize(path) if os.path.exists(path) else 0
                if size == 0x10000000 and size == last:
                    break
                last = size
            data = open(path, "rb").read()
            os.remove(path)
            yield data

    def quit(self):
        try:
            self.command("quit")
        except OSError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        try:
            self.monitor.close()
        except OSError:
            pass
        return self.serial()


def ask(machine, text, wait=0.8):
    """Sends a command to QEMU's monitor and gives back what it answers."""
    machine.drain()
    machine.command(text)
    time.sleep(wait)
    answer = b""
    try:
        while True:
            piece = machine.monitor.recv(65536)
            if not piece:
                break
            answer += piece
    except OSError:
        pass
    return answer.decode(errors="replace")


def disk_options(path, megabytes=16):
    """Makes an empty disk file for a test and gives the QEMU options that attach it to an AHCI controller."""
    if os.path.exists(path):
        os.remove(path)
    subprocess.run([QEMU_IMG, "create", "-f", "raw", path, "%dM" % megabytes], check=True, stdout=subprocess.DEVNULL)
    return ["-device", "ich9-ahci,id=ahci0", "-drive", "if=none,id=disk0,format=raw,file=" + path, "-device", "ide-hd,drive=disk0,bus=ahci0.0"]
