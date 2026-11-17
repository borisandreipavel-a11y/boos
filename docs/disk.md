# The disk

Code: `src/disk.rs`, `pci_find_kind` in `src/pci.rs`, the call in `efi_main`, and the disk file that `run.bat` makes and attaches.

So far the kernel only finds the controller that the machine's disks are plugged into. It does not talk to the controller yet, does not know whether a disk is plugged in, and cannot read or write anything.

## The words

- A **disk** keeps data while the machine is switched off. To the kernel it is a long row of numbered boxes, called blocks, each holding a small fixed amount of data.
- A disk is not on the PCI list itself. It is plugged into a **controller**, and the controller is on the list.
- **SATA** is the kind of plug and cable most PC disks have had for many years. **AHCI** is the agreed way for a kernel to talk to a SATA controller, the same for every maker.

## Which kind of disk, and why

The kernel looks for an AHCI controller, because that is what real PCs have: a real laptop that was asked reports its SATA controller in AHCI mode. QEMU can play such a controller, so the code can be tested there first.

What was weighed against it, with what QEMU 11.1 offers:

- **A virtio disk** would have shared its way of talking with the network card's driver. Only virtual machines have one, so the driver would have been of no use on a real PC.
- **NVMe** is what newer PCs have. The laptop does not.
- **An IDE disk** exists on old PCs only, and in QEMU's usual machine the drive the kernel boots from sits on the IDE controller.

## Finding the controller

- Every device on the PCI list states what kind of thing it is in three numbers, in the three bytes that follow byte 8 of its table of facts: the way it is talked to (byte 9), the narrow kind (byte 10) and the broad kind (byte 11). Byte 8 is the device's revision.
- An AHCI controller states broad kind 1 (something that stores data), narrow kind 6 (a SATA controller) and way 1 (AHCI). That is from the AHCI specification, version 1.3.1, section 2.1.5; the names there are Base Class Code, Sub Class Code and Programming Interface.
- `pci_find_kind(broad_kind, narrow_kind, way)` in `pci.rs` walks the whole list as `pci_find` does, and returns the first place whose three numbers match. It reads the 4 bytes at byte 8 and drops the revision by shifting right 8 bits. An empty place is passed over.
- `disk_controller_find()` in `disk.rs` asks for the three numbers of an AHCI controller.
- Looking by kind and not by maker and model is what makes this work on any PC: controllers of different makers and models state the same three numbers. QEMU's controller says maker `8086`, model `2922`, and reads `0x01060102` at byte 8: kind 1, 6, 1 and revision 2. The laptop's has another model number, and its own system lists it as kind `0106`.
- The specification also says where the controller's own controls are: in memory, at the address in the sixth address field of its table (byte `0x24`). The kernel does not read that yet. In QEMU it is `0x81040000`, inside the 4 GB the page tables cover.

What is not recognised:

- **A controller set to RAID mode.** The specification says such a controller states narrow kind 4 and way 0 instead. None was seen.
- A controller of the older IDE kind, and an NVMe disk. As QEMU plays them, its IDE controller states 1, 1 and `0x80`, and its NVMe disk 1, 8 and 2; neither matches.
- Any other kind of storage.
- A second AHCI controller: the first one found is taken.

## The disk file

In QEMU the disk is a file on the building computer, `disk.img` in the project folder.

- `run.bat` makes it the first time, 16 MB of zeros, with `qemu-img`, a program that comes with QEMU: `qemu-img create -f raw disk.img 16M`. If the file is there already it is left alone. If it cannot be made, `run.bat` stops and says so.
- `run.bat` then starts QEMU with three more options: `-device ich9-ahci,id=ahci0` adds an AHCI controller, `-drive if=none,id=disk0,format=raw,file=disk.img` names the file as a disk, and `-device ide-hd,drive=disk0,bus=ahci0.0` plugs that disk into the controller's first place. (`ide-hd` is QEMU's name for a hard disk, also for one on a SATA controller.)
- The options stand behind the network card's, so the card keeps its place on the PCI list, device 3, and the controller gets device 4.
- **The file is not in the repository.** `.gitignore` names it. It will hold what the person at the machine has stored.
- **Tests never use this file.** Each test boot makes a disk file of its own in a temporary folder.
- In QEMU the kernel can reach only what QEMU is given: this file, and the folder it boots from. It cannot reach the building computer's own disk.
- **On the machine `run.bat` starts, the drive the kernel boots from is another device.** The `esp` folder is attached to QEMU's IDE controller (device 1, function 1), not to the AHCI controller. A driver that talks only to the AHCI controller cannot reach it there. That is true of this one machine. On QEMU's newer kind of PC, and on a real PC, every SATA disk is plugged into the one AHCI controller, the disk with the machine's own system among them; there nothing but a rule in the kernel can keep it off a disk that is not its own (see [open-points.md](open-points.md)).
- If the project folder is kept in step with another place by a sync program, the disk file is copied there as well, like every other file in it.

## What a boot prints

One line, after the lines of the apps and before the network card's:

- `Disk controller: found, device 4 on bus 0 of the PCI list`
- when the controller is not the first device in its slot, as on QEMU's newer kind of PC and on the laptop: `Disk controller: found, device 31 (function 2) on bus 0 of the PCI list`
- on a machine without an AHCI controller: `Disk controller: none found`

The kernel carries on in every case. Nothing depends on the controller yet.

With the controller attached, "Free memory" reads 196 MB, one less than without: the firmware keeps a little more for itself.

## Limits

See [open-points.md](open-points.md). In short: the controller is only found, nothing is read or written, and only an AHCI controller is recognised.
