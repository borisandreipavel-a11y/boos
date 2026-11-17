# The disk

Code: `src/disk.rs`, `pci_find_kind` in `src/pci.rs`, the calls in `efi_main`, and the disk file that `run.bat` makes and attaches.

The kernel finds the controller that the machine's disks are plugged into, sets it up, and asks the first disk on it who it is: its name and how many blocks it holds. **It cannot read or write a block of data yet, and nothing in it can write to a disk.**

## The words

- A **disk** keeps data while the machine is switched off. To the kernel it is a long row of numbered boxes, called **blocks**. The kernel takes a block to be 512 bytes (`BLOCK_SIZE`).
- A disk is not on the PCI list itself. It is plugged into a **controller**, and the controller is on the list.
- **SATA** is the kind of plug and cable most PC disks have had for many years. **AHCI** is the agreed way for a kernel to talk to a SATA controller, the same for every maker.
- A controller has several **sockets**, each for one disk or one drive for CDs. The AHCI specification calls a socket a "port"; this kernel says socket, because "port" already means the numbered doors of the processor (`port_read`).

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

What is not recognised:

- **A controller set to RAID mode.** The specification says such a controller states narrow kind 4 and way 0 instead. None was seen.
- A controller of the older IDE kind, and an NVMe disk. As QEMU plays them, its IDE controller states 1, 1 and `0x80`, and its NVMe disk 1, 8 and 2; neither matches.
- Any other kind of storage.
- A second AHCI controller: the first one found is taken.

## Setting the controller up

`disk_setup(place)` does this once, at startup, with device signals off. It hands back a `Disk` (its socket, its name, its number of blocks) or a reason in words. The steps follow the AHCI specification, section 10.1.2 and what it refers to; the names in brackets are the specification's.

1. **Three settings in the controller's PCI facts,** the same as for the network card: it may use its memory, it may read and write the machine's memory, and it sends no signals of its own.
2. **Where the controls are.** The controller's controls are in memory, at the address in the sixth address field of its table (byte `0x24`). `map_device_memory` makes them reachable: the controller's own, which come first, and a set for each of up to 32 sockets, the first set `0x100` bytes in and each `0x80` long. In QEMU the address is `0x81040000`.
3. **"Talk to me the AHCI way"** (AE in GHC) is written before anything else is touched. The same write leaves the controller's own switch for signals off. The kernel looks at the controller itself and wants no signals from it.
4. **Taking the controller over from the firmware.** If the controller says it has the control for that (BOH in CAP2), the kernel sets "the kernel owns it" (OOS in BOHC) and waits until the firmware's own mark (BOS) and its "still busy" mark (BB) are both gone.
5. **Choosing the socket.** One control says which sockets exist (PI). For each, the lowest 4 bits of its link control (DET in PxSSTS) read 3 when something is plugged in and answering, and its signature control (PxSIG) reads `0x00000101` for a hard disk. The first socket with a disk is taken. A socket with nothing in it, or with a drive for CDs, which gives another signature, is passed over and not touched.
6. **Stopping the socket.** The firmware may have left it at work, with the firmware's memory named in it. The kernel puts off "carry out commands" (ST in PxCMD) and waits for "working through the list" (CR) to go off, then puts off "take answers" (FRE) and waits for "taking answers" (FR) to go off.
7. **Lending memory.** The kernel takes two frames and fills them with zeros. One is laid out for the controller: the list of commands at its start (1024 bytes), the area for the disk's short answers 1024 bytes in (256 bytes), and the one command the kernel uses 2048 bytes in. The other frame takes the data a command reads. The specification wants the list at an address divisible by 1024, the answer area by 256 and a command by 128; one frame gives all three, so no neighbouring frames are needed. A controller that cannot name memory above 4 GB (S64A in CAP not set) is not given a frame from up there: the setup stops with a reason.
8. **Telling the socket.** The addresses of the list and of the answer area are written into the socket's controls, as two halves of 4 bytes each. "Take answers" goes on again. The notes of old errors and old events are wiped, by writing a 1 to each bit, and no event may send a signal.
9. **Starting it.** When the disk reports that it is neither busy nor in the middle of passing data (BSY and DRQ in PxTFD), "carry out commands" goes on.
10. **Asking the disk who it is,** see below. Only when that has worked does the kernel remember the socket and the two frames (`SOCKET_CONTROLS`, `WORK_FRAME`, `DATA_FRAME`). They stay 0 if anything failed.

## A command

`disk_command` hands the disk one command that makes it send back one block, and waits for it.

- **The packet for the disk** (the specification says FIS) lies at the start of the command. Its first byte, `0x27`, says "from the machine to the disk"; bit 7 of the second says "this carries a new command"; the third is the command's number. Every other byte stays 0.
- **The place for the data** lies `0x80` bytes into the command: the address of the data frame, and how many bytes may go there, written as one less than the number (511).
- **The entry in the list of commands,** entry 0, says how long the packet is (5 times 4 bytes, in the lowest 5 bits), that there is one place for data (in the upper half), and where the command lies. The bit that would say "the data goes to the disk" stays 0.
- The socket's notes of earlier events are wiped first, so that an old failure is not taken for a new one.
- **"Command 0 is ready"** is said by writing a 1 into the socket's control for commands under way (PxCI). The socket clears that bit when the disk has finished. The kernel looks again and again until it does. If the socket notes meanwhile that the disk reported a failure (TFES in PxIS), the command has failed.
- When the command is finished, the kernel reads from the entry how many bytes the controller passed on, and takes only a whole block as an answer. The kernel writes 0 there before the command, and the specification (section 5.4.1) says the controller must have the true count there before it clears the bit, for every command that is not of the queued kind; this kernel uses none of that kind. QEMU's controller does not keep to it: it wrote 512 also when less room, or none, was named.

## Asking the disk who it is

- The command is number `0xEC`. The disk answers with one block of facts about itself, 256 numbers of 2 bytes each, the lower byte first.
- **The name** is 40 letters in numbers 27 to 46, two letters in each, the first of the two in the number's upper byte, filled up with spaces. It comes from outside the kernel, so it is cleaned with `plain_text` before it is printed.
- **The number of blocks:** bit 10 of number 83 says that the disk counts its blocks in 48 bits; then the count is in numbers 100 to 103, the lowest part first. Otherwise it is in numbers 60 and 61.
- **A count that cannot be true is not believed:** none at all, or more than 48 bits can hold. The setup then stops with a reason. Before that check existed, a count of all ones, believed, stopped the kernel with `attempt to multiply with overflow` when the size was worked out; the size is now worked out by dividing.

## What these facts rest on

- The controller's controls, the layout of the list, of a command and of the answer area, and the order of the steps: the AHCI specification, version 1.3.1.
- The packet's first three bytes: the Linux kernel's source, the function that builds such a packet, and QEMU's source, which names `0x27` and the bit `0x80`.
- The signature of a hard disk, `0x00000101`, and of a drive for CDs: QEMU's source.
- Where the name and the counts stand in the disk's answer, and bit 10 of number 83: QEMU's source, the part that plays a disk and fills in that answer.
- **The command's number, `0xEC`, was in nothing that was read.** The file that names it could not be fetched. It rests on QEMU's disk answering it with the block of facts.
- **Not read:** the rule that says when number 83 may be believed, and the numbers in which a disk states a block size other than 512 bytes.

## The disk file

In QEMU the disk is a file on the building computer, `disk.img` in the project folder.

- `run.bat` makes it the first time, 16 MB of zeros, with `qemu-img`, a program that comes with QEMU: `qemu-img create -f raw disk.img 16M`. If the file is there already it is left alone. If it cannot be made, `run.bat` stops and says so.
- `run.bat` then starts QEMU with three more options: `-device ich9-ahci,id=ahci0` adds an AHCI controller, `-drive if=none,id=disk0,format=raw,file=disk.img` names the file as a disk, and `-device ide-hd,drive=disk0,bus=ahci0.0` plugs that disk into the controller's first socket. (`ide-hd` is QEMU's name for a hard disk, also for one on a SATA controller.)
- The options stand behind the network card's, so the card keeps its place on the PCI list, device 3, and the controller gets device 4.
- **The file is not in the repository.** `.gitignore` names it. It will hold what the person at the machine has stored.
- **Tests never use this file.** Each test boot makes a disk file of its own in a temporary folder.
- In QEMU the kernel can reach only what QEMU is given: this file, and the folder it boots from. It cannot reach the building computer's own disk.
- **On the machine `run.bat` starts, the drive the kernel boots from is another device.** The `esp` folder is attached to QEMU's IDE controller (device 1, function 1), not to the AHCI controller. A driver that talks only to the AHCI controller cannot reach it there. That is true of this one machine. On QEMU's newer kind of PC, and on a real PC, every SATA disk is plugged into the one AHCI controller, the disk with the machine's own system among them, and the first disk the kernel finds there is usually that one. Today it only asks that disk who it is. Before the kernel can write, nothing but a rule in the kernel can keep it off a disk that is not its own (see [open-points.md](open-points.md)).
- If the project folder is kept in step with another place by a sync program, the disk file is copied there as well, like every other file in it.

## What a boot prints

Two lines, after the lines of the apps and before the network card's:

```
Disk controller: found, device 4 on bus 0 of the PCI list
Disk: ready, "QEMU HARDDISK", 16 MB, in socket 0 of its controller
```

- When the controller is not the first device in its slot, as on QEMU's newer kind of PC and on the laptop, the first line reads `Disk controller: found, device 31 (function 2) on bus 0 of the PCI list`.
- On a machine without an AHCI controller there is one line, `Disk controller: none found`.
- The name is the disk's own. The size is in MB, and in GB for a disk of 10 GB or more, rounded down.
- If the disk cannot be made ready the second line reads `Disk: not ready, because ...` with the reason: `no disk is plugged into the controller`, `the controller does not say where its controls are`, `the firmware did not hand the controller over`, `the disk's socket did not stop carrying out commands`, `the disk's socket did not stop taking answers`, `the controller cannot reach the memory the kernel has for it`, `the disk stayed busy`, `the disk reported that it could not do what was asked`, `the disk did not answer in time`, `the disk finished the command without sending a whole block`, or `the disk gave a number of blocks that cannot be true`.

The kernel carries on in every case. Nothing depends on the disk yet.

With the controller attached, "Free memory" reads 196 MB, one less than without: the firmware keeps a little more for itself. The two frames lent to the controller are taken after that line is printed.

## Waiting

All waiting for the controller is done by looking again and again, up to 3 million times (`PATIENCE`), because the setup runs before the timer's signals are let through. In QEMU giving up takes about 3 seconds. The specification speaks in times instead: half a second for a socket to stop, 25 thousandths of a second and then 2 seconds for the firmware to let go. On a fast machine 3 million looks may be less than half a second.

## Limits

See [open-points.md](open-points.md). In short: the kernel knows the disk's name and size and can do nothing with it yet; only an AHCI controller and the first disk on it are used; a block is taken to be 512 bytes; and several of the steps were never seen to matter in QEMU.
