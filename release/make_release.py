"""Makes the files of a release of the boot disk from the code of this checkout, into a new output folder:

- boos-<version>.zip, holding boot.vdi (for VirtualBox), boot.img (the raw disk), LICENSE-MIT, LICENSE-APACHE,
  NOTICES.txt and COPYRIGHT-library.html;
- SHA256SUMS.txt beside it: the checksum of the zip and of each file in it;
- release-notes.md: the release's text, release/release-text.md with the version and the checksums filled in.

    python release/make_release.py <output folder>

It builds the interpreter and the kernel (test-tools/build_all.py), makes boot.img with make-boot-disk.ps1, the copy
for VirtualBox with QEMU's qemu-img (and checks with qemu-img that the copy holds the same disk), and the notices
(release/make_notices.py). Then it starts QEMU once from a copy
of boot.img, never from boot.img itself, since a start writes to its disk, and checks that the kernel reaches its
first question with plain text only; boot.img must be unchanged afterwards. On any failure it stops and says why
("NOT MADE"), with an exit code of 1; what it had made stays in the output folder. It uploads nothing. QEMU, the
firmware and the tests' work folder come from the environment like the tests' (test-tools/places.py). See
docs/release.md."""
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, "test-tools")
sys.path.insert(0, TOOLS)

from places import QEMU_IMG, RUNS  # noqa: E402

# The kernel this checkout builds, whatever KERNEL_FILE may say: a release holds only what its own code builds.
KERNEL = os.path.join(REPO, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
IN_ZIP = ["boot.vdi", "boot.img", "LICENSE-MIT", "LICENSE-APACHE", "NOTICES.txt", "COPYRIGHT-library.html"]


def stop(reason):
    print("NOT MADE: " + reason)
    sys.exit(1)


def run(label, command, **options):
    done = subprocess.run(command, capture_output=True, text=True, **options)
    if done.returncode:
        stop("%s failed (exit %d): %s" % (label, done.returncode, (done.stdout + done.stderr).strip()[-600:]))
    return done.stdout


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for piece in iter(lambda: handle.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def first_start(image):
    """Starts QEMU from a copy of the image until the prompt; gives back the start check's report and what is wrong."""
    from boot_count import start_report
    from boot_disk_checks import DiskMachine
    folder = os.path.join(RUNS, "release-first-start")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    copy = os.path.join(folder, "boot-copy.img")
    shutil.copyfile(image, copy)
    machine = DiskMachine("release-first-start", copy)
    try:
        reached = machine.wait_for(b"repeated here:", 150)
    finally:
        serial = machine.quit()
    report, wrong = start_report(serial)
    if not reached:
        wrong = ["the prompt never came"] + wrong
    if b"Kernel: hello!" not in serial:
        wrong.append("no first question (\"Kernel: hello!\")")
    return report, wrong


def main():
    if len(sys.argv) != 2:
        stop("usage: python release/make_release.py <output folder>")
    out = os.path.abspath(sys.argv[1])
    if os.path.exists(out) and os.listdir(out):
        stop("the output folder %s is not empty" % out)
    version = tomllib.load(open(os.path.join(REPO, "Cargo.toml"), "rb"))["package"]["version"]
    files = os.path.join(out, "files")
    os.makedirs(files)

    print(run("building the interpreter and the kernel", [sys.executable, os.path.join(TOOLS, "build_all.py")],
              cwd=TOOLS).strip())
    image = os.path.join(files, "boot.img")
    run("make-boot-disk.ps1", ["powershell", "-NoProfile", "-File", os.path.join(REPO, "make-boot-disk.ps1"), image, KERNEL])
    vdi = os.path.join(files, "boot.vdi")
    run("qemu-img convert", [QEMU_IMG, "convert", "-f", "raw", "-O", "vdi", image, vdi])
    # The copy for VirtualBox must hold the same disk: the same contents, block for block, and the same size. (Strict
    # mode would also ask that the same blocks be stored, but a VDI does not store blocks that hold nothing.)
    print(run("qemu-img compare", [QEMU_IMG, "compare", "-f", "raw", "-F", "vdi", image, vdi]).strip())
    import json
    vdi_size = json.loads(run("qemu-img info", [QEMU_IMG, "info", "--output=json", "-f", "vdi", vdi]))["virtual-size"]
    if vdi_size != os.path.getsize(image):
        stop("boot.vdi is a disk of %d bytes, boot.img of %d" % (vdi_size, os.path.getsize(image)))
    print("boot.vdi: a disk of %d bytes, as boot.img" % vdi_size)
    print(run("make_notices.py", [sys.executable, os.path.join(HERE, "make_notices.py"), files]).strip())
    for name in ("LICENSE-MIT", "LICENSE-APACHE"):
        shutil.copyfile(os.path.join(REPO, name), os.path.join(files, name))

    before = sha256(image)
    report, wrong = first_start(image)
    print("\n".join("first start from a copy: " + line for line in report))
    if wrong:
        stop("the first start from a copy of boot.img: " + "; ".join(wrong))
    if sha256(image) != before:
        stop("boot.img changed during the check")

    archive = os.path.join(out, "boos-%s.zip" % version)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as packed:
        for name in IN_ZIP:
            packed.write(os.path.join(files, name), name)
    sums = [(sha256(archive), os.path.basename(archive))] + [(sha256(os.path.join(files, name)), name) for name in IN_ZIP]
    with open(os.path.join(out, "SHA256SUMS.txt"), "w", encoding="ascii", newline="\n") as listing:
        listing.write("".join("%s  %s\n" % pair for pair in sums))

    text = open(os.path.join(HERE, "release-text.md"), encoding="utf-8").read()
    checksums = "\n".join("%s  %s" % pair for pair in sums)
    text = text.replace("{version}", version).replace("{checksums}", checksums)
    with open(os.path.join(out, "release-notes.md"), "w", encoding="utf-8", newline="\n") as notes:
        notes.write(text)

    print("version %s" % version)
    for name in [os.path.basename(archive), "SHA256SUMS.txt", "release-notes.md"]:
        print("  %-24s %10d bytes" % (name, os.path.getsize(os.path.join(out, name))))
    for name in IN_ZIP:
        print("    in the zip: %-22s %10d bytes" % (name, os.path.getsize(os.path.join(files, name))))
    print("".join("%s  %s\n" % pair for pair in sums).strip())


if __name__ == "__main__":
    main()
