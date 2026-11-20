"""The boot disk (make-boot-disk.ps1): an independent reader of its start part's FAT32 file system, worked out from
Microsoft's FAT specification (fatgen103) and from the checks of the FAT reader in the UEFI reference firmware
(edk2, FatPkg), not from the script; a machine that QEMU starts from the disk file alone, with no folder; and the
checks that test_boot_disk.py runs. Nothing runs when this file is imported."""
import hashlib
import os
import shutil
import socket
import struct
import subprocess
import time

from boot import FIRMWARE, KERNEL, PROJECT, QEMU, RUNS, Machine, greeted_by_qemu
from gpt import BOOS, START, look

BLOCK = 512
# BOOT_DISK_SCRIPT names a copy of the script with a break made on purpose (run_boot_disk_breaks.py).
SCRIPT = os.environ.get("BOOT_DISK_SCRIPT") or os.path.join(PROJECT, "make-boot-disk.ps1")
DIVIDER = os.path.join(PROJECT, "make-disk.ps1")


def make(path, kernel=KERNEL, megabytes=None):
    """Runs the script as run-boot-disk.bat does, and gives back its exit code and what it printed."""
    command = ["powershell", "-NoProfile", "-File", SCRIPT, path, kernel]
    if megabytes:
        command += ["-Megabytes", str(megabytes)]
    done = subprocess.run(command, capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def divide(path, megabytes, start_megabytes=0):
    """An empty disk file divided by make-disk.ps1, for the cases the script must refuse."""
    with open(path, "wb") as handle:
        handle.truncate(megabytes * 1048576)
    command = ["powershell", "-NoProfile", "-File", DIVIDER, path]
    if start_megabytes:
        command += ["-StartPartMegabytes", str(start_megabytes)]
    subprocess.run(command, capture_output=True, check=True)


def blocks_hash(path, first, last):
    """A fingerprint of blocks first to last of a disk file."""
    with open(path, "rb") as handle:
        handle.seek(first * BLOCK)
        return hashlib.sha256(handle.read((last - first + 1) * BLOCK)).hexdigest()


def file_hash(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def parts(path):
    """The disk's list of parts as gpt.py reads it: the start part and boos's part, with the checks it made."""
    seen = look(path)
    found = {"problems": list(seen["problems"])}
    for entry in seen.get("parts", []):
        if entry["kind"] == START:
            found["start"] = (entry["first"], entry["last"])
        elif entry["kind"] == BOOS:
            found["boos"] = (entry["first"], entry["last"])
    return found


def fat_look(path, first_block, fresh=True):
    """Reads the FAT32 file system that begins at first_block and gives back what an outside reader finds: the
    fields of its first sector, its layout, and the file EFI\\BOOT\\BOOTX64.EFI, with every rule it breaks.
    `fresh`: as the script left it. Once a firmware has used the file system it keeps the count of free clusters in
    sector 1 up to date and leaves the copy in sector 7 as it was, so the two are compared only on a fresh one."""
    with open(path, "rb") as handle:
        handle.seek(first_block * BLOCK)
        reserved = handle.read(32 * BLOCK)
    problems = []
    first = reserved[:BLOCK]
    (jump, oem, sector_size, per_cluster, reserved_sectors, fats, root_entries, sectors16, media, fat16,
     _track, _heads, hidden, sectors32) = struct.unpack("<3s8sHBHBHHBHHHII", first[:36])
    fat32, flags, version, root_cluster, info_sector, copy_sector = struct.unpack("<IHHIHH", first[36:52])
    drive, boot_mark, volume_id, label, kind = struct.unpack("<B x B I 11s 8s", first[64:90])
    out = {"volume id": volume_id, "problems": problems}

    def need(condition, words):
        if not condition:
            problems.append(words)

    # The specification's rules for the first sector, and the firmware's own checks (FatOpenDevice in edk2).
    need(jump[0] == 0xEB and jump[2] == 0x90 or jump[0] == 0xE9, "the first three bytes are not a jump")
    need(first[510:512] == b"\x55\xaa", "the first sector does not end in 55 AA")
    need(sector_size == BLOCK, "a sector is not 512 bytes")
    need(per_cluster in (1, 2, 4, 8, 16, 32, 64, 128) and per_cluster * sector_size <= 32768, "sectors to a cluster")
    need(reserved_sectors != 0 and fats != 0, "no reserved sectors or no table of clusters")
    need(root_entries == 0 and sectors16 == 0 and fat16 == 0, "the FAT16 fields are not 0")
    need(media == 0xF0 or media >= 0xF8, "the media byte")
    need(version == 0 and flags & 0x80 == 0, "the version is not 0.0, or the tables are not kept the same")
    need(info_sector == 1 and copy_sector == 6, "FSInfo is not sector 1 or the copy not sector 6")
    need(boot_mark == 0x29 and kind == b"FAT32   ", "the signature 0x29 and the kind FAT32")
    need(reserved[6 * BLOCK:7 * BLOCK] == first, "sector 6 is not a copy of sector 0")
    if fresh:
        need(reserved[7 * BLOCK:8 * BLOCK] == reserved[BLOCK:2 * BLOCK], "sector 7 is not a copy of sector 1")
    need(hidden == first_block, "the hidden sectors are not the part's first block")

    # The layout, and the count of clusters that decides the kind (specification, "FAT Type Determination").
    data_start = reserved_sectors + fats * fat32
    clusters = (sectors32 - data_start) // per_cluster
    need(clusters >= 65525, "fewer than 65525 clusters: that is not FAT32")
    temp = (256 * per_cluster + fats) // 2
    need(fat32 == (sectors32 - reserved_sectors + temp - 1) // temp, "the table's length is not the specification's sum")
    need((clusters + 2) * 4 <= fat32 * BLOCK, "the table of clusters is too short for the clusters")
    out.update(sectors=sectors32, fat_sectors=fat32, clusters=clusters, data_start=data_start)

    info = reserved[info_sector * BLOCK:(info_sector + 1) * BLOCK]
    lead, = struct.unpack("<I", info[0:4])
    middle, free, next_free = struct.unpack("<III", info[484:496])
    trail, = struct.unpack("<I", info[508:512])
    need((lead, middle, trail) == (0x41615252, 0x61417272, 0xAA550000), "the FSInfo signatures")

    with open(path, "rb") as handle:
        handle.seek((first_block + reserved_sectors) * BLOCK)
        tables = [handle.read(fat32 * BLOCK) for _ in range(fats)]
        handle.seek((first_block + data_start) * BLOCK)
        data = handle.read(min(clusters, 40000) * per_cluster * BLOCK)
    need(all(table == tables[0] for table in tables), "the tables of clusters differ")
    table = tables[0]

    def entry(number):
        return struct.unpack_from("<I", table, number * 4)[0] & 0x0FFFFFFF

    need(entry(0) == 0x0FFFFF00 | media, "entry 0 of the table")
    need(struct.unpack_from("<I", table, 4)[0] & 0x0FFFFFFF >= 0x0FFFFFF8, "entry 1 of the table is not an end")
    need(struct.unpack_from("<I", table, 4)[0] & 0x0C000000 == 0x0C000000, "entry 1 does not say clean")
    used = sum(1 for number in range(2, clusters + 2) if entry(number) != 0)
    need(free == clusters - used, "FSInfo's count of free clusters")
    out["free"] = free

    size = per_cluster * BLOCK

    def chain(start):
        clusters_seen = []
        number = start
        while 2 <= number < 0x0FFFFFF8 and len(clusters_seen) <= clusters:
            clusters_seen.append(number)
            number = entry(number)
        need(number >= 0x0FFFFFF8, "a chain of clusters does not end")
        return clusters_seen

    def read(start):
        return b"".join(data[(n - 2) * size:(n - 1) * size] for n in chain(start))

    def folder(start, name):
        entries = {}
        raw = read(start)
        for at in range(0, len(raw), 32):
            item = raw[at:at + 32]
            if item[0] == 0:
                break
            if item[0] == 0xE5 or item[11] & 0x0F == 0x0F:
                continue    # A taken-away entry, or a piece of a long name (kind 0x0F).
            high, = struct.unpack_from("<H", item, 20)
            low, length = struct.unpack_from("<HI", item, 26)
            entries[item[:11].decode("ascii", "replace")] = (item[11], high << 16 | low, length)
        out["folder " + name] = sorted(entries)
        return entries

    top = folder(root_cluster, "top")
    efi = top.get("EFI        ")
    need(efi is not None and efi[0] & 0x10, "no folder EFI at the top")
    if efi:
        efi_entries = folder(efi[1], "EFI")
        need(efi_entries.get(".          ", (0, -1))[1] == efi[1], "EFI's dot entry")
        need(efi_entries.get("..         ", (0, -1))[1] == 0, "EFI's dotdot entry is not 0")
        boot = efi_entries.get("BOOT       ")
        need(boot is not None and boot[0] & 0x10, "no folder BOOT in EFI")
        if boot:
            boot_entries = folder(boot[1], "BOOT")
            need(boot_entries.get(".          ", (0, -1))[1] == boot[1], "BOOT's dot entry")
            need(boot_entries.get("..         ", (0, -1))[1] == efi[1], "BOOT's dotdot entry")
            kernel = boot_entries.get("BOOTX64 EFI")
            need(kernel is not None and kernel[0] & 0x10 == 0, "no file BOOTX64.EFI in BOOT")
            if kernel:
                out["kernel"] = read(kernel[1])[:kernel[2]]
                need(len(out["kernel"]) == kernel[2], "the file is shorter than its length says")
    return out


class DiskMachine(Machine):
    """QEMU started from a disk file alone: the disk on its AHCI controller, the firmware, the network card with
    no way out, the serial lines to a file. No folder: the firmware must find the kernel on the disk itself.
    Keys, pictures, waiting and quitting are Machine's."""

    def __init__(self, tag, disk_path, port=None, memory="256M"):
        if port is None:
            from ports import free_port
            port = free_port()
        self.port = port
        self.tag = tag
        self.folder = os.path.join(RUNS, tag)
        os.makedirs(self.folder, exist_ok=True)
        self.serial_path = os.path.join(self.folder, "serial.txt")
        if os.path.exists(self.serial_path):
            os.remove(self.serial_path)
        self.disk_path = disk_path
        command = [QEMU, "-m", memory, "-cpu", "qemu64,+rdrand",
                   "-netdev", "user,id=net0,restrict=on", "-device", "virtio-net-pci,netdev=net0",
                   "-device", "ich9-ahci,id=ahci0", "-drive", "if=none,id=disk0,format=raw,file=" + disk_path,
                   "-device", "ide-hd,drive=disk0,bus=ahci0.0",
                   "-drive", "if=pflash,format=raw,readonly=on,file=" + FIRMWARE,
                   "-serial", "file:" + self.serial_path, "-display", "none", "-no-reboot",
                   "-monitor", "tcp:127.0.0.1:%d,server=on,wait=off" % port]
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.monitor = None
        deadline = time.time() + 20
        while time.time() < deadline and self.process.poll() is None:
            try:
                candidate = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                time.sleep(0.2)
                continue
            if greeted_by_qemu(candidate):
                self.monitor = candidate
                break
            candidate.close()
            time.sleep(0.2)
        if self.monitor is None:
            self.process.kill()
            raise RuntimeError("no monitor on port %d: " % port + self.process.stderr.read().decode(errors="replace"))
        self.monitor.settimeout(0.3)
        self.drain()


def lines_of(serial):
    return serial.decode("ascii", "replace").replace("\r", "").split("\n")


def start(tag, disk_path, problems, seconds=150):
    """Starts QEMU from the disk file, waits for the prompt, and gives back the serial lines."""
    machine = DiskMachine(tag, disk_path)
    try:
        if not machine.wait_for(b"repeated here:", seconds):
            problems.append("%s: the prompt never came" % tag)
    finally:
        serial = machine.quit()
    return lines_of(serial)


def work_folder(tag):
    folder = os.path.join(RUNS, tag)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    return folder
