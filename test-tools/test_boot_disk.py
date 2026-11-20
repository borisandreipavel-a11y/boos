"""The boot disk: make-boot-disk.ps1 makes one disk file with a FAT32 start part that holds the kernel and boos's own
part after it, QEMU starts from that file alone, and writing another kernel leaves what boos keeps alone.

- made: a new disk file of 80 MB, and one of 120 MB (-Megabytes): its list of parts as gpt.py reads it, and the start
  part's FAT32 file system as boot_disk_checks.fat_look reads it, with the kernel's file byte for byte the kernel.
- start: QEMU starts from the file alone, with no folder; its firmware names the SATA disk it started from; the
  kernel reaches the prompt, finds its own part on that disk and begins a notebook there; the list of parts and the
  blocks outside the two parts stay byte for byte, and the start part stays a whole FAT32 file system with the
  kernel's file unchanged (QEMU's firmware adds a file of its own there, NvVars, where it keeps its settings).
- again: the script writes another kernel file into a disk that has been started from (the kernel with 4096 bytes
  more at its end, so that its length and its clusters differ): boos's part stays byte for byte, the start part holds
  the new file byte for byte, and the next start finds the notebook again (start number 2).
- refuses: a disk without a start part, one with two start parts, one whose start part overlaps boos's part, a start
  part too small for FAT32, a kernel too large for it, a file that is not divided, and a disk that a running machine
  has open: each is refused with its own reason, and all but the last are left byte for byte as they were (the
  running machine writes to its disk itself).

This suite and run_boot_disk_breaks.py share the work folder runs/boot-disk: they must not run side by side.
Usage: python test_boot_disk.py [made] [start] [again] [refuses]   (all four without names)"""
import os
import re
import sys

from boot import KERNEL
from boot_disk_checks import (BLOCK, DiskMachine, blocks_hash, divide, fat_look, file_hash, make, parts, start,
                              work_folder)
from gpt import BOOS, START, build

names = sys.argv[1:] or ["made", "start", "again", "refuses"]
failures = []
kernel = open(KERNEL, "rb").read()
folder = work_folder("boot-disk")
disk = os.path.join(folder, "boot.img")
MB = 1048576
START_PART = (2048, 2048 + 64 * 2048 - 1)


def check(label, problems):
    print("  %-48s %s" % (label, "as meant" if not problems else problems))
    failures.extend("%s: %s" % (label, p) for p in problems)


def new_disk(path, megabytes=80):
    """Makes a disk file anew with the script and gives back the problems an outside reader finds in it."""
    if os.path.exists(path):
        os.remove(path)
    code, said = make(path, megabytes=None if megabytes == 80 else megabytes)
    if code != 0:
        return ["the script failed: " + said]
    print("    " + said.splitlines()[-1])
    problems = []
    if os.path.getsize(path) != megabytes * MB:
        problems.append("the file is not %d MB" % megabytes)
    found = parts(path)
    problems += found["problems"]
    if found.get("start") != START_PART:
        problems.append("the start part is not the 64 MB from block 2048: %r" % (found.get("start"),))
    # boos's part follows, up to the last block the list lets a part use: 34 before the end.
    if found.get("boos") != (START_PART[1] + 1, megabytes * 2048 - 34):
        problems.append("boos's part is not the rest of the disk: %r" % (found.get("boos"),))
    if not problems:
        fat = fat_look(path, START_PART[0])
        problems += fat["problems"]
        print("    FAT32: %d sectors, tables of %d sectors, %d clusters, %d free" %
              (fat["sectors"], fat["fat_sectors"], fat["clusters"], fat["free"]))
        print("    folders: %s / %s / %s" % (fat.get("folder top"), fat.get("folder EFI"), fat.get("folder BOOT")))
        if fat.get("kernel") != kernel:
            problems.append("EFI\\BOOT\\BOOTX64.EFI is not the kernel byte for byte")
    return problems


def plain_lines(lines):
    return [re.sub(r"\x1b\[[0-9;=]*[A-Za-z]", "", line) for line in lines]


notebook_done = False
for name in names:
    print(name)
    if name == "made":
        check("a new boot disk of 80 MB", new_disk(disk))
        check("a new boot disk of 120 MB", new_disk(os.path.join(folder, "big.img"), 120))

    elif name == "start":
        problems = new_disk(disk)
        found = parts(disk)
        boos_part = found["boos"]
        total = os.path.getsize(disk) // BLOCK
        outside = (blocks_hash(disk, 0, START_PART[0] - 1), blocks_hash(disk, boos_part[1] + 1, total - 1))
        own_before = blocks_hash(disk, boos_part[0], boos_part[1])
        lines = plain_lines(start("boot-disk-start", disk, problems))
        firmware = [line for line in lines if "BdsDxe" in line]
        for line in firmware:
            print("    " + line[line.index("BdsDxe"):][:110])
        if not any("starting" in line and "Sata(" in line for line in firmware):
            problems.append("the firmware did not say it started from the SATA disk")
        hello = next((i for i, line in enumerate(lines) if line == "Hello from my kernel!"), None)
        end = next((i for i, line in enumerate(lines) if line.startswith("Click the QEMU window")), None)
        if hello is not None and end is not None:
            print("    lines to the prompt, from the kernel's first: %d" % (end - hello + 1))
        megabytes = (boos_part[1] - boos_part[0] + 1) // 2048
        for line in ["Disk: my own part is %d MB, from block %d to block %d" % (megabytes, boos_part[0], boos_part[1]),
                     "Disk: this is start number 1"]:
            if line not in lines:
                problems.append("missing line %r" % line)
        if not any(line.startswith("Disk: a new notebook was begun") for line in lines):
            problems.append("no new notebook was begun")
        for line in lines:
            if line.startswith("Disk:"):
                print("    " + line)
        if (blocks_hash(disk, 0, START_PART[0] - 1), blocks_hash(disk, boos_part[1] + 1, total - 1)) != outside:
            problems.append("the list of parts or a block outside the two parts changed")
        if blocks_hash(disk, boos_part[0], boos_part[1]) == own_before:
            problems.append("nothing was written into boos's own part")
        # The firmware may write into the start part: QEMU's, which has no store for its settings, keeps them in
        # a file NvVars there. The kernel's file and the file system must stay whole, and nothing else appear.
        fat = fat_look(disk, START_PART[0], fresh=False)
        problems += fat["problems"]
        if fat.get("kernel") != kernel:
            problems.append("the kernel's file changed")
        others = [n for n in fat.get("folder top", []) if n not in ("EFI        ", "NVVARS     ")]
        if others:
            problems.append("other things at the top of the start part: %r" % others)
        print("    the start part's top folder after the start: %s" % fat.get("folder top"))
        check("started from the disk alone", problems)
        notebook_done = not problems

    elif name == "again":
        problems = []
        if not notebook_done:
            problems += new_disk(disk)
            start("boot-disk-first", disk, problems)
        boos_part = parts(disk)["boos"]
        kept = blocks_hash(disk, boos_part[0], boos_part[1])
        old_id = fat_look(disk, START_PART[0], fresh=False)["volume id"]
        # Another kernel file: the kernel with 4096 bytes more at its end. The firmware loads what the file's own
        # header names and leaves the rest, so it starts like the kernel; its length and clusters differ.
        other = kernel + bytes(4096)
        other_path = os.path.join(folder, "other.efi")
        with open(other_path, "wb") as handle:
            handle.write(other)
        code, said = make(disk, other_path)
        if code != 0:
            problems.append("the script failed for a disk made before: " + said)
        print("    " + (said.splitlines()[-1] if said else ""))
        if blocks_hash(disk, boos_part[0], boos_part[1]) != kept:
            problems.append("boos's part changed when another kernel was written")
        fat = fat_look(disk, START_PART[0])
        problems += fat["problems"]
        if fat["volume id"] == old_id:
            problems.append("the start part was not written again (same volume number)")
        if fat.get("kernel") != other:
            problems.append("the start part does not hold the new kernel file byte for byte")
        if fat.get("folder top") != ["EFI        "]:
            problems.append("the top folder holds more than EFI: %r" % fat.get("folder top"))
        lines = start("boot-disk-again", disk, problems)
        if "Disk: this is start number 2" not in lines:
            problems.append("the next start did not find the notebook again: %r" %
                            [line for line in lines if line.startswith("Disk:")])
        check("another kernel, the notebook kept", problems)

    elif name == "refuses":
        # Each case with the words of its own reason: a refusal for another reason would hide a missing check.
        cases = []
        plain = os.path.join(folder, "plain.img")
        divide(plain, 16)
        cases.append(("a disk without a start part", plain, KERNEL, "exactly one start part"))
        two = os.path.join(folder, "two.img")
        build(two, 160, parts=[(START, 2048, 133119, "start"), (START, 133120, 264191, "start"),
                               (BOOS, 264192, 160 * 2048 - 34, "boos")])
        cases.append(("a disk with two start parts", two, KERNEL, "exactly one start part"))
        overlap = os.path.join(folder, "overlap.img")
        build(overlap, 80, parts=[(START, 2048, 133119, "start"), (BOOS, 133000, 80 * 2048 - 34, "boos")])
        cases.append(("a start part that overlaps boos's part", overlap, KERNEL, "overlaps"))
        small = os.path.join(folder, "small.img")
        divide(small, 40, 16)
        cases.append(("a start part too small for FAT32", small, KERNEL, "too small for FAT32"))
        big_kernel = os.path.join(folder, "huge.efi")
        with open(big_kernel, "wb") as handle:
            handle.truncate(70 * MB)
        fits = os.path.join(folder, "fits.img")
        if os.path.exists(fits):
            os.remove(fits)
        make(fits)
        cases.append(("a kernel too large for the start part", fits, big_kernel, "does not fit"))
        loose = os.path.join(folder, "loose.img")
        with open(loose, "wb") as handle:
            handle.write(b"boos" * 4096)
        cases.append(("a file that is not divided", loose, KERNEL, "no list of parts"))
        for label, path, which, reason in cases:
            problems = []
            before = file_hash(path)
            code, said = make(path, which)
            if code == 0:
                problems.append("not refused")
            elif reason not in said:
                problems.append("refused for another reason")
            if file_hash(path) != before:
                problems.append("the file changed")
            print("    " + (said.splitlines()[-1] if said else ""))
            check("refused: " + label, problems)
        # A disk that a running machine has open.
        busy = os.path.join(folder, "busy.img")
        problems = new_disk(busy)
        machine = DiskMachine("boot-disk-busy", busy)
        try:
            if not machine.wait_for(b"Hello from my kernel!", 120):
                problems.append("the machine did not start")
            code, said = make(busy)
        finally:
            machine.quit()
        if code == 0:
            problems.append("not refused")
        elif "cannot be opened" not in said:
            problems.append("refused for another reason")
        print("    " + (said.splitlines()[-1] if said else ""))
        check("refused: a disk a running machine has open", problems)
    else:
        print("  no such scenario: " + name)
        failures.append(name)

print("FAILURES: " + ("none" if not failures else str(len(failures))))
for failure in failures:
    print("  " + failure)
sys.exit(1 if failures else 0)
