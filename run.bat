@echo off
cargo build || exit /b 1
if not exist esp\EFI\BOOT mkdir esp\EFI\BOOT
del /Q esp\EFI\BOOT\BOOTX64.EFI 2>nul
for %%f in (target\x86_64-unknown-uefi\debug\*.efi) do copy /Y "%%f" esp\EFI\BOOT\BOOTX64.EFI
if not exist esp\EFI\BOOT\BOOTX64.EFI (
    echo No kernel file was found in target\x86_64-unknown-uefi\debug
    exit /b 1
)
"C:\Program Files\qemu\qemu-system-x86_64.exe" -m 256M -net none -drive if=pflash,format=raw,readonly=on,file=edk2-x86_64-code.fd -drive format=raw,file=fat:rw:esp -serial stdio