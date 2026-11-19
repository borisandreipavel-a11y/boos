"""Where things are. Every other tool takes its folders from here, so that no tool names a folder of one
particular computer.

- PROJECT: the project, found as the folder above this one. BOOS_PROJECT names another (a copy, say).
- QEMU_DIR: where QEMU is installed. QEMU_DIR overrides the usual place on Windows.
- WORK: where tests put what they make (disk files, pictures, copies of the project, test certificates),
  in the computer's temporary folder and never inside the project. One folder per project folder, so that two
  checkouts tested at once keep apart. BOOS_TEST_WORK names another.

Nothing runs when this file is imported but working out these names."""
import hashlib
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.environ.get("BOOS_PROJECT") or os.path.dirname(HERE))
QEMU_DIR = os.environ.get("QEMU_DIR") or r"C:\Program Files\qemu"
QEMU = os.path.join(QEMU_DIR, "qemu-system-x86_64.exe")
QEMU_IMG = os.path.join(QEMU_DIR, "qemu-img.exe")
QEMU_IO = os.path.join(QEMU_DIR, "qemu-io.exe")
FIRMWARE = os.path.join(PROJECT, "edk2-x86_64-code.fd")
KERNEL = os.environ.get("KERNEL_FILE") or os.path.join(PROJECT, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
WASM = os.path.join("interpreter", "target", "wasm32-unknown-unknown", "release", "interpreter.wasm")

_project_mark = hashlib.sha256(os.path.normcase(PROJECT).encode()).hexdigest()[:10]
WORK = os.path.abspath(os.environ.get("BOOS_TEST_WORK") or os.path.join(tempfile.gettempdir(), "boos-tests", _project_mark))
RUNS = os.path.join(WORK, "runs")
