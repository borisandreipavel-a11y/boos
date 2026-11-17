@echo off
cargo build || exit /b 1
if not exist esp\EFI\BOOT mkdir esp\EFI\BOOT
del /Q esp\EFI\BOOT\BOOTX64.EFI 2>nul
for %%f in (target\x86_64-unknown-uefi\debug\*.efi) do copy /Y "%%f" esp\EFI\BOOT\BOOTX64.EFI
if not exist esp\EFI\BOOT\BOOTX64.EFI (
    echo No kernel file was found in target\x86_64-unknown-uefi\debug
    exit /b 1
)
rem The machine's disk is a file, disk.img. Make an empty one of 16 MB the first time.
if not exist disk.img "C:\Program Files\qemu\qemu-img.exe" create -f raw disk.img 16M
if not exist disk.img (
    echo The disk file disk.img could not be made
    exit /b 1
)
"C:\Program Files\qemu\qemu-system-x86_64.exe" -m 256M -cpu qemu64,+rdrand -netdev user,id=net0 -device virtio-net-pci,netdev=net0 -device ich9-ahci,id=ahci0 -drive if=none,id=disk0,format=raw,file=disk.img -device ide-hd,drive=disk0,bus=ahci0.0 -drive if=pflash,format=raw,readonly=on,file=edk2-x86_64-code.fd -drive format=raw,file=fat:rw:esp -serial stdio