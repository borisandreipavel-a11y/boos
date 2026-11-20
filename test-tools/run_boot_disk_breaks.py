"""Breaks make-boot-disk.ps1 on purpose, one break at a time, in a copy of the script (with make-disk.ps1 beside
it), and sees whether test_boot_disk.py catches each one. The project's own script is only read.
Usage: python run_boot_disk_breaks.py [break ...]   (default: all)"""
import os
import shutil
import subprocess
import sys

from boot import PROJECT, RUNS

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(PROJECT, "make-boot-disk.ps1")

# label: (old text, new text, scenarios of test_boot_disk.py that must catch it). The texts have plain line ends.
BREAKS = {
    "the tables of clusters one sector short": (
        "    $dataStart = $ReservedSectors + $FatCount * $fatSectors\n",
        "    $fatSectors = $fatSectors - 1\n    $dataStart = $ReservedSectors + $FatCount * $fatSectors\n", ["made"]),
    "entry 1 of the table not an end": (
        "Set-Number $fat 4 $EndOfChain 4", "Set-Number $fat 4 0x07FFFFFF 4", ["made"]),
    "no copy of the first sector": (
        "    [Array]::Copy($first, 0, $reserved, $CopySector * $BlockSize, $BlockSize)\n", "", ["made"]),
    "EFI's dotdot entry pointing at itself": (
        '(New-Entry "..         " $Folder 0 0)', '(New-Entry "..         " $Folder $efiCluster 0)', ["made"]),
    "the kernel's chain ending one cluster early": (
        "    Set-Number $fat ([int]($lastCluster * 4)) $EndOfChain 4",
        "    Set-Number $fat ([int](($lastCluster - 1) * 4)) $EndOfChain 4", ["made"]),
    "a media byte the firmware refuses": (
        "$MediaByte = 0xF8 ", "$MediaByte = 0xF7 ", ["made", "start"]),
    "the free clusters miscounted": (
        "Set-Number $info 488 ([uint64]($clusters - ($lastCluster - 1))) 4",
        "Set-Number $info 488 ([uint64]$clusters) 4", ["made"]),
    "the blocks before the part left 0": (
        "Set-Number $first 28 ([uint64]$StartFirst) 4", "Set-Number $first 28 0 4", ["made"]),
    "a disk made before made new again": (
        "if (-not (Test-Path -LiteralPath $Path)) {", "if ($true) {", ["again"]),
    "a disk without a start part not refused": (
        "    if ($starts.Count -ne 1 -or $boosParts.Count -ne 1) {", "    if ($boosParts.Count -ne 1) {", ["refuses"]),
}

if __name__ == "__main__":
    # Matched with plain line ends, whichever the checkout has.
    source = open(SCRIPT, "rb").read().decode().replace("\r\n", "\n")
    copy_folder = os.path.join(RUNS, "boot-disk-break-copy")
    names = sys.argv[1:] or list(BREAKS)
    caught = 0
    missed = []
    for label in names:
        old, new, scenarios = BREAKS[label]
        if source.count(old) != 1:
            print("%-46s THE BREAK COULD NOT BE MADE (its text stands %d times)" % (label, source.count(old)), flush=True)
            missed.append(label + " (not made)")
            continue
        shutil.rmtree(copy_folder, ignore_errors=True)
        os.makedirs(copy_folder)
        shutil.copyfile(os.path.join(PROJECT, "make-disk.ps1"), os.path.join(copy_folder, "make-disk.ps1"))
        broken = os.path.join(copy_folder, "make-boot-disk.ps1")
        with open(broken, "wb") as handle:
            handle.write(source.replace(old, new).encode())
        done = subprocess.run([sys.executable, "test_boot_disk.py"] + scenarios, cwd=HERE, capture_output=True,
                              text=True, env=dict(os.environ, BOOT_DISK_SCRIPT=broken))
        lines = done.stdout.splitlines()
        verdict = [line for line in lines if line.startswith("FAILURES:")]
        is_caught = done.returncode != 0 and bool(verdict) and verdict[-1] != "FAILURES: none"
        caught += is_caught
        if not is_caught:
            missed.append(label)
        # The test names what went wrong in the lines after its verdict.
        after = lines[lines.index(verdict[-1]) + 1:] if verdict else []
        why = [line.strip() for line in after if line.strip()]
        print("%-46s %s | %s" % (label, "caught" if is_caught else "NOT CAUGHT",
                                 (" / ".join(why) if why else (done.stdout + done.stderr)[-200:])[:400]), flush=True)
    print("caught %d of %d" % (caught, len(names)), flush=True)
    # The verdict line, as every suite ends: run_tests.py runs this list as one job of its own (suites.py).
    print("FAILURES: " + ("none" if not missed else str(missed)), flush=True)
    sys.exit(1 if missed else 0)
