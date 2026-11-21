@echo off
rem Two things are built. First the interpreter, a program that the kernel
rem carries inside it. It is built from inside its own folder, because that
rem is where its settings are. Then the kernel itself.
pushd interpreter || exit /b 1
cargo build --release
if %errorlevel% neq 0 (
    popd
    echo The interpreter could not be built
    exit /b 1
)
popd
cargo build || exit /b 1
if not exist esp\EFI\BOOT mkdir esp\EFI\BOOT
del /Q esp\EFI\BOOT\BOOTX64.EFI 2>nul
for %%f in (target\x86_64-unknown-uefi\debug\*.efi) do copy /Y "%%f" esp\EFI\BOOT\BOOTX64.EFI
if not exist esp\EFI\BOOT\BOOTX64.EFI (
    echo No kernel file was found in target\x86_64-unknown-uefi\debug
    exit /b 1
)
rem The machine's disk is a file, disk.img. The first time, make one of 16 MB
rem and divide it into parts, with one part for the kernel to keep its things in.
if exist disk.img goto disk_there
"C:\Program Files\qemu\qemu-img.exe" create -f raw disk.img 16M
if not exist disk.img (
    echo The disk file disk.img could not be made
    exit /b 1
)
powershell -NoProfile -File make-disk.ps1 disk.img
if %errorlevel% neq 0 (
    del /Q disk.img 2>nul
    echo The disk file disk.img could not be divided into parts
    exit /b 1
)
:disk_there
rem The machine's network card: the virtio card, or with the word e1000
rem (.\run.bat e1000) the Intel card QEMU plays under that name.
set NETWORK_CARD=virtio-net-pci
if /I "%~1"=="e1000" set NETWORK_CARD=e1000
"C:\Program Files\qemu\qemu-system-x86_64.exe" -m 256M -cpu qemu64,+rdrand -netdev user,id=net0 -device %NETWORK_CARD%,netdev=net0 -device ich9-ahci,id=ahci0 -drive if=none,id=disk0,format=raw,file=disk.img -device ide-hd,drive=disk0,bus=ahci0.0 -drive if=pflash,format=raw,readonly=on,file=edk2-x86_64-code.fd -drive format=raw,file=fat:rw:esp -serial stdio