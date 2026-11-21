**An early test version.** boos is the beginning of an operating system where a model makes the apps. Its kernel is written from nothing in Rust, for x86-64 PCs, and the firmware loads it directly. This release is a ready disk to start it in a virtual machine, built by GitHub from the public code at this release's commit. It has been tried only in QEMU and in VirtualBox, never on a real PC.

## What you need

- **VirtualBox** (the steps below were checked against version 7.2.22), or QEMU.
- **Your own key for OrcaRouter**, the provider through which boos talks to its model (`deepseek/deepseek-v4.1-flash-1017` at `api.orcarouter.ai`). At its first start boos asks for a name, then for the key, then for a password that locks the key on the disk. Every line typed in the chat box, except `key` and `setup`, goes to the model with your key, and each one is paid on your OrcaRouter account; `docs/tools.md` in the repository has estimates of what a line costs.

## Start it in VirtualBox

1. Unpack `boos-{version}.zip`.
2. Put `boot.vdi` into a folder of its own for the machine, for example a folder `boos` in VirtualBox's folder for machines, which `VBoxManage list systemproperties` names ("Default machine folder").
3. Make and start the machine with VirtualBox's command-line program `VBoxManage`, which lies in VirtualBox's install folder; `<folder>` is the folder that holds `boot.vdi`:

```
VBoxManage createvm --name=boos --platform-architecture=x86 --ostype=Other_64 --register
VBoxManage modifyvm boos --firmware=efi --memory=256 --nic1=nat --nic-type1=virtio --keyboard=ps2
VBoxManage storagectl boos --name=SATA --add=sata --controller=IntelAhci
VBoxManage storageattach boos --storagectl=SATA --port=0 --device=0 --type=hdd --medium="<folder>\boot.vdi"
VBoxManage startvm boos --type=gui
```

- The machine needs firmware of the UEFI kind, 256 MB, its disk on an AHCI controller, the virtio network card on VirtualBox's built-in network and a PS/2 keyboard, as above. VirtualBox's default network card is another, for which the kernel has no driver.
- Secure Boot must be off, since the kernel is not signed. If a start is refused for that: `VBoxManage modifynvram boos secureboot --disable`.
- If VirtualBox does not take `boot.vdi`, make one from `boot.img`: `VBoxManage convertfromraw boot.img "<folder>\boot.vdi" --format=VDI`.
- Later starts need only the last line. The machine stops when its window is closed with "Power off the machine".

## Start it in QEMU

`boot.img` is the same disk as one raw file. QEMU starts it with its own UEFI firmware, the file `edk2-x86_64-code.fd` in QEMU's `share` folder:

```
qemu-system-x86_64 -m 256M -cpu qemu64,+rdrand -netdev user,id=net0 -device virtio-net-pci,netdev=net0 -device ich9-ahci,id=ahci0 -drive if=none,id=disk0,format=raw,file=boot.img -device ide-hd,drive=disk0,bus=ahci0.0 -drive if=pflash,format=raw,readonly=on,file=edk2-x86_64-code.fd -serial stdio
```

## Good to know

- A normal start fetches one web page from the internet over an encrypted link, the page of example.com.
- After use, the disk holds what you gave it: your name, and your key locked with your password. Do not pass a used disk on.
- The line `setup` asks the first start's questions again.

## Checksums (SHA-256)

```
{checksums}
```

## Licences

The project's own code may be used under the MIT licence or the Apache License, Version 2.0, whichever you choose (`LICENSE-MIT`, `LICENSE-APACHE` in the zip). The outside code built into the disk keeps its own licences: `NOTICES.txt` and `COPYRIGHT-library.html` in the zip carry their texts.
