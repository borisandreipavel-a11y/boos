@echo off
rem Like run.bat, but the machine starts from the boot disk, boot.img: one disk
rem file whose start part holds the kernel and whose other part is boos's own.
rem No folder is needed: the machine's startup program finds the kernel on the
rem disk itself, as a PC does. Notes: docs/disk.md, "The boot disk".
pushd interpreter || exit /b 1
cargo build --release
if %errorlevel% neq 0 (
    popd
    echo The interpreter could not be built
    exit /b 1
)
popd
cargo build || exit /b 1
if not exist target\x86_64-unknown-uefi\debug\boos.efi (
    echo No kernel file was found in target\x86_64-unknown-uefi\debug
    exit /b 1
)
rem The first time the disk file is made, 80 MB. After that only its start part
rem is written again, with the new kernel: what boos keeps in its own part stays.
powershell -NoProfile -File make-boot-disk.ps1 boot.img target\x86_64-unknown-uefi\debug\boos.efi
if %errorlevel% neq 0 (
    echo The boot disk boot.img could not be made
    exit /b 1
)
"C:\Program Files\qemu\qemu-system-x86_64.exe" -m 256M -cpu qemu64,+rdrand -netdev user,id=net0 -device virtio-net-pci,netdev=net0 -device ich9-ahci,id=ahci0 -drive if=none,id=disk0,format=raw,file=boot.img -device ide-hd,drive=disk0,bus=ahci0.0 -drive if=pflash,format=raw,readonly=on,file=edk2-x86_64-code.fd -serial stdio
