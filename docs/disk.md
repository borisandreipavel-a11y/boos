# The disk

Code: `src/disk.rs`, `src/parts.rs`, `pci_find_kind` in `src/pci.rs`, the calls in `efi_main`, the disk file that `run.bat` makes and attaches, and `make-disk.ps1`, which divides it.

The kernel finds the controller that the machine's disks are plugged into, sets it up, asks the first disk on it who it is, its name and how many blocks it holds, and can read a block from it. It reads the list that says how the disk is divided into parts, and finds the part that is its own. **It writes only inside that part,** and so far one block of it: a count of its own starts.

## The words

- A **disk** keeps data while the machine is switched off. To the kernel it is a long row of numbered boxes, called **blocks**, numbered from 0. A block is 512 bytes (`BLOCK_SIZE`); a disk that says its blocks have another size is refused.
- A disk is not on the PCI list itself. It is plugged into a **controller**, and the controller is on the list.
- **SATA** is the kind of plug and cable most PC disks have had for many years. **AHCI** is the agreed way for a kernel to talk to a SATA controller, the same for every maker.
- A disk is divided into **parts** (partitions), and a list at its start says which part is which; see "The parts of a disk".
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
10. **Asking the disk who it is,** see below. Only when that has worked does the kernel remember the socket and the two frames (`SOCKET_CONTROLS`, `WORK_FRAME`, `DATA_FRAME`) and what the disk said (`DISK_BLOCKS`, `DISK_COUNTS_LONG`). They stay 0 if anything failed.

## A command

`disk_command` hands the disk one command that makes it send back one block, and waits for it.

- A socket takes commands only while "carry out commands" is on. If it is off, the command is not given, and the reason says so.
- **The packet for the disk** (the specification says FIS) lies at the start of the command, 20 bytes. It is filled with zeros first, so that nothing of an earlier command is left in it. Its first byte, `0x27`, says "from the machine to the disk"; bit 7 of the second says "this carries a new command"; the third is the command's number.
- **A command about a block names the block** in six bytes of the packet, the lowest part of the number first: bytes 5, 6 and 7, then bytes 9, 10 and 11. Between them, byte 8 holds `0x40`, which says that a block number is meant and not the older way of naming a place on a disk. Byte 13 says how many blocks: one. (Bytes are counted from 1 here; the code counts from 0.)
- **The place for the data** lies `0x80` bytes into the command: the address of the data frame, and how many bytes may go there, written as one less than the number (511).
- **The entry in the list of commands,** entry 0, says how long the packet is (5 times 4 bytes, in the lowest 5 bits), that there is one place for data (in the upper half), and where the command lies. The bit that would say "the data goes to the disk" stays 0.
- The socket's notes of earlier events are wiped first, so that an old failure is not taken for a new one. The start of the data frame is wiped as well, so that what an earlier command read cannot be taken for this one's answer.
- **"Command 0 is ready"** is said by writing a 1 into the socket's control for commands under way (PxCI). The socket clears that bit when the disk has finished. The kernel looks again and again until it does. If the socket notes meanwhile that the disk reported a failure (TFES in PxIS), the command has failed.
- When the command is finished, the kernel reads from the entry how many bytes the controller passed on, and takes only a whole block as an answer. The kernel writes 0 there before the command, and the specification (section 5.4.1) says the controller must have the true count there before it clears the bit, for every command that is not of the queued kind; this kernel uses none of that kind. QEMU's controller does not keep to it: it wrote 512 also when less room, or none, was named.

- **After a command that went wrong,** because the disk reported a failure or did not answer in time, `socket_restart` gets the socket going again as the specification says (section 6.2.2.1): "carry out commands" off, wait until the socket has stopped, wipe the notes of errors and events, and "carry out commands" on again. If the disk is still busy then, it would need a harder push that the kernel does not know how to give, and the socket stays stopped.

## Asking the disk who it is

- The command is number `0xEC`. The disk answers with one block of facts about itself, 256 numbers of 2 bytes each, the lower byte first.
- **The name** is 40 letters in numbers 27 to 46, two letters in each, the first of the two in the number's upper byte, filled up with spaces. It comes from outside the kernel, so it is cleaned with `plain_text` before it is printed.
- **The size of a block:** if, of the bits 15, 14 and 12 of number 106, exactly 14 and 12 are set, the disk's blocks have another size than 512 bytes, and numbers 117 and 118 give it, counted in 2-byte numbers. A disk whose blocks are not 512 bytes long is refused, because everything in the kernel reckons with 512.
- **The number of blocks:** bit 10 of number 83 says that the disk counts its blocks in 48 bits; then the count is in numbers 100 to 103, the lowest part first. Number 83 is believed only if, of its two top bits, the lower one alone is set, and the long count only if it is not 0. Otherwise the count is in numbers 60 and 61.
- **A count that cannot be true is not believed:** none at all, or more than 48 bits can hold. The setup then stops with a reason. Before that check existed, a count of all ones, believed, stopped the kernel with `attempt to multiply with overflow` when the size was worked out; the size is now worked out by dividing.

## Writing a block

Code: `disk_write` in `src/disk.rs`, `part_write` and `WriteTicket` in `src/parts.rs`. Three things write: the count of starts in `src/starts.rs`, the notebook in `src/notebook.rs` (see [notebook.md](notebook.md)), and files fetched from the web in `src/files.rs` (see "The room for files" below).

- **The kernel writes only inside its own part.** `part_write(block, from)` writes one block of the kernel's own part, numbered from 0 at the part's beginning, and refuses a number at or past the part's length, exactly as `part_read` does for reading. It is the only place in the kernel that writes to a disk.
- **That is enforced when the kernel is built, not by habit.** `disk_write`, which writes a block of the disk by its own number, asks for a ticket, a `WriteTicket`. What a ticket holds is private to `parts.rs`, so only code in that file can make one, and `part_write` is the one place that does, with `part_write_run` below. Code anywhere else that tries to call `disk_write`, with a ticket it makes itself or with none, does not build.
- `disk_write` also keeps its own bound: a block the disk does not have is refused, as for reading.
- **The command is number `0x35`,** the write command for disks that count their blocks in 48 bits. The block to be written is put into the data frame first. The entry in the list of commands gets one more mark, bit 6, which says that the command's data goes to the disk.
- The data frame is wiped before a command that reads, and must not be before one that writes: it holds the block on its way out.
- **Then the disk is told to put it down for good,** command `0xEA`. A disk may keep written blocks in a store of its own for a while, where a power cut would lose them; this command empties that store onto the disk itself. It is a command without data: its entry names no place for data, and the check for a whole block does not apply to it.
- A write that fails, because the disk reports a failure or does not answer, comes back as a reason in words, and the socket is got going again as after a failed read.

### A run of blocks

A file takes many neighbouring blocks, and one command per block, each followed by "put it down for good", would make a file of 4 MB take over half a minute: keeping a thing in the notebook took 0.32 seconds for 74 blocks (see [testing.md](testing.md)).

- **One command moves up to eight blocks,** as many as the data frame of 4 KB holds (`BLOCKS_AT_ONCE`): the same read and write commands, with the count of blocks in the packet where one stood before, room for that many bytes in the place for data, and the check that the controller passed on all of them. `disk_read_blocks` and `disk_write_blocks` do that; `disk_read` and `disk_write` are as before.
- `disk_write_blocks` does not tell the disk to put the blocks down for good. `disk_put_down` does that, once, for all that was written before it. It asks for the same ticket.
- **`part_write_run(block, bytes)`** in `parts.rs` writes all of the bytes from that block of the kernel's own part on, the last block filled up with zeros, eight blocks to a command, and then has the disk put them down for good once. A run that would reach past the part's end is refused before anything is written, so it keeps to the part as `part_write` does. `part_read_run` reads such a run back.

### The count of starts

`start_count()` in `starts.rs` counts how often the kernel has started. It shows that what the kernel writes is still there after the machine was switched off.

- The count is kept in **the last block of the kernel's own part**. The part's first block holds the head of the notebook and the blocks between hold its entries; the notebook leaves the last block alone. See [notebook.md](notebook.md).
- The block holds the 16 letters `boos start count`, then the count as a number of 8 bytes, lowest byte first, then a check value of those 24 bytes in 4 bytes. The rest is zeros.
- **A start is counted only after the notebook was opened.** If the kernel's part holds something the kernel does not know, the notebook refuses it, and then nothing is written to the part, the count included.
- At each start the kernel reads the block. Nothing but zeros means no start was counted yet. The letters with a check value that fits give the count. Anything else is not believed: the count begins again, and the line says so. The kernel's own part is its own, so it writes over what it finds there.
- It adds 1, without going past the largest number there is, writes the block, **reads it back, and counts the start only if the disk holds exactly what was written.**
- This is a demonstration. It can go, with its block, now that the notebook keeps things on the disk.

## Reading a block

`disk_read(block, into)` reads the block with that number into 512 bytes that the caller hands over.

- **The command is number `0x25`,** the one for disks that count their blocks in 48 bits; the specification says that all passing of data should be done this way (it calls it DMA). A disk that counts in fewer bits does not know this command, and is not read: `the disk is of an older kind that the kernel cannot read`.
- **A block the disk does not have is not asked for at all:** a number at or past the disk's count comes back as `the disk has no block with that number`, without a command being given.
- Before the setup has made the disk ready the answer is `the disk is not ready`.
- The block lands in the data frame and is copied out byte by byte.
- **Nothing on the disk is changed by reading.**
- `block_text(block, longest)`, which nothing in the kernel calls at present, gives the text a block begins with: its bytes up to the first 0, at most `longest` of them, with every byte that is not a plain sign turned into a dot. A block's contents come from outside the kernel.
- Reading 2,048 blocks one after another added about a second to a boot in QEMU: a boot with those reads took 17 seconds from the start of QEMU to the prompt, and three boots with the same disk and without them 16. So a block takes about half a thousandth of a second there. Each read holds everything else up while it waits; today that is at startup only.

## The parts of a disk

Code: `src/parts.rs`, and `make-disk.ps1`, which divides a new disk file.

A PC's disk is divided into **parts** (the usual word is "partitions"). A list at the start of the disk says where each part begins and ends and what kind of part it is. Every system that uses the disk reads that list and keeps to its own parts. The list this kernel reads is the one PCs use today, the GUID partition table of the UEFI specification.

**The kernel keeps its things in one part only, the one whose kind is its own.** This is the rule for writing: the kernel writes only inside the part that the disk's own list names as its own; "Writing a block" says how that is enforced. It never writes the list, never another part, and never divides a disk or takes one over. A disk without such a part is never written to. Dividing a disk is done from outside, on purpose.

### How the list is laid out

- **Block 0** holds a list of an older style, four entries of 16 bytes starting 446 bytes in. On a disk divided the newer way, one of them has the kind `0xEE` and says that it begins at block 1. It is there so that older programs see the disk as taken and leave it alone.
- **Block 1** holds the head of the list: the signature `EFI PART`, the version (1.0, written `0x00010000`), the head's own length (92 bytes), a check value of the head, the block the head lies in, the block where a second copy of the head lies, the first and the last block a part may use, a number for the disk, the block where the entries begin, how many entries there are and how long each is, and a check value of all the entries.
- **The entries** follow, usually 128 of them of 128 bytes each, which is 32 blocks. An entry holds the part's kind (16 bytes; all zeros means the entry is not in use), a number of the part's own (16 bytes), the part's first and last block, some marks, and a name.
- **A second copy** of the entries and of the head lies at the very end of the disk, the head in the last block.
- A **check value** (CRC-32) is a number worked out from some bytes. Whoever wrote the list stored it; whoever reads the list works it out again. If a byte has changed since, the two no longer agree. The head's value is worked out over the head's own length with the place for the value holding zeros; the entries' value over all the entries.
- The 16-byte numbers (kinds, and the numbers of disks and parts) are written on the disk with their first three groups turned round, lowest byte first. The kernel's kind, `261e771e-cc8b-4a7f-96d1-b57fd92eafea`, stands on a disk as `1e 77 1e 26 8b cc 7f 4a 96 d1 b5 7f d9 2e af ea`. It was made up once, at random, for this kernel. The kind of the part a PC starts a kernel from is `c12a7328-f81f-11d2-ba4b-00a0c93ec93b`.

### What `part_find` checks

`part_find(disk_blocks)` reads the list and gives back where the kernel's own part is: its first block, its last and how many blocks it is long. Everything in the list comes from outside the kernel, and writing trusts what is found here, so nothing is taken on trust. In this order, each with its reason in words:

1. Block 0 has an old-style entry of kind `0xEE` that begins at block 1. Otherwise: `it has no list of parts`.
2. The head begins with its signature, is of version 1.0, is at least 92 bytes long and no longer than a block, and says that it lies in block 1. Otherwise: `the head of its list of parts is not as it must be`.
3. The head's check value fits. Otherwise: `the head of its list of parts is damaged`.
4. There is at least one entry, and an entry is 128 bytes long or that doubled some number of times. Otherwise the reason of step 2.
5. All the entries together are at most 128 KB (`ENTRIES_MOST`). Otherwise they are not read: `its list of parts is longer than the kernel is prepared to read`. This keeps a head that claims millions of entries from making the kernel read, or ask the heap for, some enormous amount.
6. The first usable block is not past the last, the last is a block the disk has, the entries begin after block 1 and lie wholly on the disk, and the block the head names for its second copy is a block the disk has. Otherwise: `the head of its list of parts names blocks the disk does not have`.
7. **The usable blocks do not lie on the list itself:** not on the entries, and not on the second copy at the end, whose own entries lie just in front of its head. Otherwise: `the head of its list of parts lets a part lie on the list itself`. A check value that fits shows that the head was not changed by accident. It does not show that whoever wrote the list wrote it right, and a part is checked against the usable blocks in step 10. Without this step, a head that calls block 2 usable would let the kernel's part lie on the entries, and writing there would destroy the list.
8. The entries' check value fits. Otherwise: `the entries of its list of parts are damaged`.
9. Exactly one entry has the kernel's kind. None: `its list of parts names no part as mine`. Two or more: `its list of parts names more than one part as mine`, because which is meant cannot be known.
10. That part begins no later than it ends, and lies between the first and the last usable block. Otherwise: `the part named as mine does not lie where a part may lie`.
11. That part shares no block with any other entry in use. Otherwise: `the part named as mine shares blocks with another part`.

Steps 1 to 4, 8, 10 and 11 are what the reference firmware's own reader of such lists checks; the others are this kernel's. Only the copy at the start is read. If it is damaged the kernel does not turn to the copy at the end, and does not repair anything.

`part_read(block, into)` reads one block of the kernel's own part, with blocks numbered from 0 at the part's beginning. It is the one place where "block of my part" becomes a block of the disk. A number at or past the part's length is refused there, so nothing outside the part can be reached through it.

### The firmware may write to the disk before the kernel runs

QEMU's firmware reads the list of every disk it finds, and **repairs it**: if the copy at the start is damaged and the copy at the end is whole, it writes the start copy anew from the end copy, and the other way round. It does that while starting, before the kernel has run a single instruction. A test disk whose head had a wrong check value came out of a boot with a head that was whole again, and the kernel found its part on it. A test disk with a whole copy at the start and none at the end came out with a second copy written at the block its head named, also where that block lay inside what the same head called usable. So the kernel is not the only thing that writes to a disk: besides the kernel's one block in its own part, the firmware may have written to the list, and a real PC's firmware may do the same. To test the kernel's own checks of the head, a test disk must have no second copy to repair from.

### Dividing a disk file

`make-disk.ps1` divides a disk file, in the script language that comes with Windows (PowerShell). `run.bat` calls it for a disk file it has just made:

```
powershell -NoProfile -File make-disk.ps1 disk.img
```

- It writes block 0, the head, 128 entries, and the second copy at the end, with their check values. One entry is in use: the kernel's own part, named `boos`, from block 2048, which is 1 MB in, to the last usable block. On a file of 16 MB that is blocks 2048 to 32734, 14 MB.
- The disk and the part each get a number of their own, drawn at random, so two disk files are never the same byte for byte.
- **It refuses a file that holds anything but zeros,** and a file that is missing, not a whole number of blocks, or under 4 MB. So it cannot divide a disk file that is in use.
- `-StartPartMegabytes 10` puts a part of the kind a PC starts from in front, 10 MB large, with the kernel's part after it. That is the order a disk has on a machine that starts from it. The option is for tests; nothing is put into that part.
- A computer whose settings refuse to run script files stops `run.bat` there, with a line saying that the disk file could not be divided, and the half-made file is deleted. No setting is changed to get round that.

## What these facts rest on

- The controller's controls, the layout of the list, of a command and of the answer area, and the order of the steps: the AHCI specification, version 1.3.1.
- The packet's first three bytes: the Linux kernel's source, the function that builds such a packet, and QEMU's source, which names `0x27` and the bit `0x80`.
- The signature of a hard disk, `0x00000101`, and of a drive for CDs: QEMU's source.
- Where the name and the counts stand in the disk's answer, and bit 10 of number 83: QEMU's source, the part that plays a disk and fills in that answer.
- The command numbers `0x35` for writing and `0xEA` for putting down, and that the entry's bit 6 says "the data goes to the disk": the same two sources, and the AHCI specification's picture of an entry.
- The command numbers `0xEC` and `0x25`, the `0x40` that says "block number", and the two rules for when number 83 and number 106 may be believed: the Linux kernel's source, the file that lists them, and QEMU's source, which has the same two numbers and the same `0x40`. That file could not be fetched when the setup was written, and was fetched for the reading.
- Which bytes of the packet hold which part of the block number: the Linux function that builds the packet, and QEMU's source, the part that puts the number together again on the disk's side.
- What to do after a failed command: the AHCI specification, section 6.2.2.1.
- The layout of the list of parts, of its head and of an entry, the old-style list in block 0, and the kind number of the part a PC starts from: the header files of the UEFI reference firmware (edk2). The specification's own site refuses to be fetched.
- What a reader must check before believing a list, the version number, and that the head's check value is worked out over the head's own length with its place holding zeros: the reference firmware's reader of such lists.
- How the check value is worked out: the reference firmware's routine for it. Its comment names the standard it follows, ITU-T V.42. The kernel's routine and the script's are written bit by bit and not copied from it; both give the same values as the routine in Python's own library, and the firmware accepts a list that carries the script's values.
- The FAT32 file system of the boot disk's start part: Microsoft's "Microsoft Extensible Firmware Initiative FAT32 File System Specification" (fatgen103, version 1.03 of December 6, 2000), for the fields of the first sector and of FSInfo, the sum for the length of a table, the rule that the count of clusters decides the kind, the table of cluster sizes, entries 0 and 1 of a table, the end mark, the `.` and `..` entries, and the copy in sector 6.
- Where each field of the first sector, of FSInfo and of a folder entry lies, byte by byte, and what the reference firmware refuses to read: the reference firmware's FAT reader (edk2, `FatPkg`), its file of layouts and its routine that opens a file system. The UEFI specification's site refused to be fetched for this too.

## The disk file

In QEMU the disk is a file on the building computer, `disk.img` in the project folder.

- `run.bat` makes it the first time, 16 MB of zeros, with `qemu-img`, a program that comes with QEMU: `qemu-img create -f raw disk.img 16M`, and then divides it with `make-disk.ps1`; see "Dividing a disk file". If the file is there already it is left alone, divided or not. A disk file from before the list of parts came is not divided, and the kernel then says that the disk has no list of parts. The remedy is to delete the file, which loses what is in it; `run.bat` makes a new, divided one at its next run. If it cannot be made or divided, `run.bat` stops and says so, and leaves no half-made file behind.
- `run.bat` then starts QEMU with three more options: `-device ich9-ahci,id=ahci0` adds an AHCI controller, `-drive if=none,id=disk0,format=raw,file=disk.img` names the file as a disk, and `-device ide-hd,drive=disk0,bus=ahci0.0` plugs that disk into the controller's first socket. (`ide-hd` is QEMU's name for a hard disk, also for one on a SATA controller.)
- The options stand behind the network card's, so the card keeps its place on the PCI list, device 3, and the controller gets device 4.
- **The file is not in the repository.** `.gitignore` names it. It holds what the kernel has stored: its notebook and its count of starts. **Every start of the kernel changes it, and so does every line sent in the chat box.**
- **Tests never use this file.** Each test boot makes a disk file of its own in a temporary folder.
- In QEMU the kernel can reach only what QEMU is given: this file, and the folder it boots from. It cannot reach the building computer's own disk.
- **On the machine `run.bat` starts, the drive the kernel boots from is another device.** The `esp` folder is attached to QEMU's IDE controller (device 1, function 1), not to the AHCI controller. A driver that talks only to the AHCI controller cannot reach it there. That is true of this one machine. On QEMU's newer kind of PC, and on a real PC, every SATA disk is plugged into the one AHCI controller, the disk with the machine's own system among them, and the first disk the kernel finds there is usually that one. Today it only asks that disk who it is. On such a machine nothing but the rule in "The parts of a disk" keeps the kernel off what is not its own: it will write only inside the part that the disk's list names as its.
- If the project folder is kept in step with another place by a sync program, the disk file is copied there as well, like every other file in it.

## The boot disk

A PC starts from a disk, not from a folder: its startup program, the firmware, looks on a disk for a part of the start kind, reads the file system in it, and starts the file `EFI\BOOT\BOOTX64.EFI` it finds there. `make-boot-disk.ps1` makes such a disk as one file, `boot.img`, and `run-boot-disk.bat` starts QEMU from that file with no folder (see "Starting from the boot disk" in [startup.md](startup.md)). The same file serves VirtualBox, through a copy in its own format (see "In VirtualBox" in [startup.md](startup.md)), and is meant for a USB stick later.

```
powershell -NoProfile -File make-boot-disk.ps1 boot.img target\x86_64-unknown-uefi\debug\boos.efi
```

- **The first time** it makes the file, 80 MB (`-Megabytes` asks for another size), and has `make-disk.ps1` divide it with `-StartPartMegabytes 64`: a start part of 64 MB, blocks 2048 to 133119, and boos's own part after it, blocks 133120 to 163806, a little under 15 MB.
- **Then it writes the start part:** a FAT32 file system with the folders `EFI` and `EFI\BOOT` and the kernel as `EFI\BOOT\BOOTX64.EFI`. Every byte of it is written by the script itself, from Microsoft's FAT specification; no other program formats anything.
- **For a new kernel it is run again.** A file made before is not made anew: the script finds the two parts in the disk's list, writes the start part afresh with the new kernel, and does not touch boos's part, so what the kernel keeps there, its notebook and its count of starts, stays.
- **It writes only inside the start part.** Every write is checked against the start part's first and last block before it is made, and a write that would reach outside stops the script there, before that write; the writes before it would have been made. No test has made one reach outside: the check is a guard, and the layout keeps every write inside.
- **It refuses, and leaves the file byte for byte as it was,** when the file has no list of parts; when the list does not name exactly one start part and one part for boos, or the two overlap; when the start part is too small for FAT32; and when the kernel does not fit into it. Each refusal says which. It also refuses a file that a running machine has open, since it cannot have the file to itself then.
- **The file system, rule by rule** (Microsoft's FAT specification, and the checks of the reference firmware's FAT reader where it has some):
  - A sector is 512 bytes and a cluster one sector: Microsoft's table gives one sector to a cluster for a part of up to 260 MB.
  - 32 reserved sectors at the start: the first sector; sector 1, which counts the free clusters (the specification calls it FSInfo); and copies of both in sectors 6 and 7. The copy of the first sector stands in sector 6 and nowhere else, as the specification asks.
  - Two tables of clusters, kept the same, each as long as the specification's sum says: 1016 sectors for the part of 64 MB. That leaves 129,008 clusters.
  - The kind of FAT is decided by the count of clusters and by nothing else: 65,525 or more is FAT32. The reference firmware's reader refuses a FAT32 file system with fewer, and so does the script, for a start part under about 33 MB.
  - The media byte is `0xF8`, "a disk that stays in its machine", the version 0.0, and both tables are kept the same (bit 7 of the flags off). The reference firmware's reader refuses a media byte from `0x02` to `0xEF` or from `0xF1` to `0xF7`, a version other than 0.0, and tables that are not kept the same.
  - Entry 0 of the table holds the media byte with all other bits 1, and entry 1 the end mark, whose top two bits say that the file system was left cleanly and without disk errors.
  - The top folder is cluster 2, `EFI` cluster 3, `BOOT` cluster 4, and the kernel follows from cluster 5 in one run. A folder below the top begins with the entries `.` and `..`; the `..` of a folder at the top names cluster 0.
  - The first sector names the start part's first block as the blocks that come before it on the disk, has no name ("NO NAME") and a volume number drawn at random at each writing. The times in the folders are when the script ran.
- **QEMU's firmware writes into the start part.** On this machine it has no store for its own settings (its program is given read-only and nothing else), so it keeps them in a file `NvVars` that it writes at the top of the start part, with a long name. A start from the boot disk changed 27 blocks there: the file's clusters, its entries in the top folder, its clusters in both tables, and the count of free clusters in sector 1, whose copy in sector 7 stays as it was. The kernel's file stayed byte for byte, and so did everything outside the two parts. Writing the start part again for a new kernel takes `NvVars` away, and the firmware writes it anew.
- **The firmware's own lines.** QEMU's firmware prints two lines on the serial port before the kernel's first, as it does when it starts the kernel from the folder. They name the disk it started from: `BdsDxe: loading Boot0001 "UEFI QEMU HARDDISK QM00005 " from PciRoot(0x0)/Pci(0x4,0x0)/Sata(0x0,0xFFFF,0x0)`, the SATA disk on the AHCI controller, where a start from the folder names `PciRoot(0x0)/Pci(0x1,0x1)/Ata(Primary,Master,0x0)`, the folder's disk on the IDE controller. Counted from the kernel's first line, a start from the disk shows as many lines up to the prompt as one from the folder.
- **The file is not in the repository:** `.gitignore` names `boot.img`, and `boot.vdi` for a copy in VirtualBox's own format. Like `disk.img` it holds what the kernel keeps. Nothing of this reads or changes `disk.img`.

## The room for files

Code: `src/files.rs`. Files fetched from the web (see "download_file" in [tools.md](tools.md)) are kept in a room of their own in the back half of the kernel's part. The kernel still writes only inside its own part.

- **Where:** on a part of 4096 blocks (2 MB) or more, the room begins in the part's middle block, `blocks / 2`, which holds the room's **head**: the 16 letters `boos files      ` (six spaces at the end), the version of the layout, 1, in 4 bytes, and a check value of those 20 bytes in 4 more, all lowest byte first, as the notebook's head. Files lie behind it, up to the last but one block of the part; the last holds the count of starts. On a part of 30,687 blocks, as on the usual disk file and the boot disk, the head is in block 15,343 and files may take 15,342 blocks, about 7.5 MB. A smaller part has no room for files.
- **The notebook ends in front of it.** Its entries may then use the blocks from 1 to the one before the head, so it has room for about half as many entries as before (see [notebook.md](notebook.md)). The room is checked at startup, before the notebook is opened (`files_look`): a head there means the room is in use, and the notebook's entries end in front of it, so that no block of a file is ever read as an entry; zeros there mean that no file was kept yet, and the room is left to the files only if the notebook ends more than eight blocks in front of it, so that the eight blocks the notebook looks at behind its end lie in front of the room too. A notebook that reaches further keeps all of its room, and there is no room for files. So does a part whose middle block holds anything else.
- **The head is written when the first file is kept,** and read back. A start writes nothing for the room.
- **A file** lies in one run of neighbouring blocks: the first run of free blocks it fits in, counted from the head. It is written with `part_write_run` and read back, a frame's worth at a time, and only if every byte is as written does its note go into the notebook, under `file 1`, `file 2` and so on. Until then the blocks count as free: a power cut while a file is written leaves nothing half kept.
- **The note** is text, one line each: `blocks <first> <how many>`, `bytes <length>`, `check <CRC-32 of the file, 8 hex digits>`, `kind pdf` (or `docx`, `xlsx`, `txt`, `csv`), `name <name>`, `date <the clock chip's date and time, or unknown>`, `from <the address it came from>`. A note comes from the disk, from outside the kernel: it counts only if every line is as written and the file lies wholly inside the room. The address is read too, for a PDF that Anthropic fetches from it (see `open_file` in [tools.md](tools.md)): it counts only as one the kernel could have fetched, `https://` and a site, plain signs without spaces, at most 2,048 bytes; a note without such an address still counts, without one. A note that holds nothing is a file that was removed (see [notebook.md](notebook.md): a name can only be replaced).
- **The free room** is what no note names. A file that fits in no run is refused, with the largest run that is free.
- **Removing a file** replaces its note with one that holds nothing; its blocks are free again for the next file. Nothing on them is wiped.
- **Sites the person allowed** are kept in the notebook too, under `site 1`, `site 2` and so on, each holding a site's name; at startup only the names that read as a site's name count.

## What a boot prints

Six lines, after the lines of the apps and before the network card's, and then the chat box's rows from the notebook:

```
Disk controller: found, device 4 on bus 0 of the PCI list
Disk: ready, "QEMU HARDDISK", 16 MB, in socket 0 of its controller
Disk: my own part is 14 MB, from block 2048 to block 32734
Disk: the notebook holds 3 entries and has room for 15339 more
Disk: the room for files holds 2 files and has room for 7650 KB more
Disk: this is start number 3
Kernel: last time you said "hello"
Kernel: welcome back, Ada.
Kernel: type your password and press Enter to unlock the key. Enter alone goes on without it.
```

- The fourth line is the notebook's, and the lines that begin with `Kernel:` come from the chat box: the line kept last, the greeting by the name kept in the notebook, and the question for the password that unlocks the key locked there, or else the question for the key or for a name; [notebook.md](notebook.md) and [chat.md](chat.md) list their other forms. If the notebook cannot be opened the fourth line reads `Disk: nothing is kept on it, because ...`, nothing is written to the part, and no line about the count follows.
- The fifth line is the room for files': how many files it holds, and how much room is free in it, in KB rounded down. `..., no more are kept, since the notebook cannot be added to` when the notebook is damaged. When there is no room for files: `Disk: no room for files, because ...`, with `my part is too small for it`, `the notebook reaches into it`, or `the block where it begins holds something I do not know`.
- The sixth line counts the kernel's starts with this disk. The number is one higher at every start, because the kernel keeps it on the disk. A new disk file begins at 1.
- If the block for the count holds something the kernel does not know, the line reads `Disk: the count of starts could not be read and begins again; this is start number 1`.
- If the count cannot be written, or the disk does not hold what was written when it is read back, the line reads `Disk: this start could not be counted, because ...` with the reason, and the kernel carries on.
- A disk with no part of the kernel's own gives no fourth, fifth or sixth line, and nothing is written to it.

- The third line says where the kernel's own part lies on the disk, with its first and its last block, and its size in MB, rounded down.
- If the kernel finds no part of its own, the third line reads `Disk: nothing on it is mine, because ...` with one of the reasons listed under "What `part_find` checks", or with the reason of a block that could not be read. A disk file that was never divided gives `it has no list of parts`.
- A disk that is not ready gives no third line.
- An earlier form of the kernel read the disk's last block here and showed a text that had been written into the disk file from the building computer. That went when the list of parts came: on a divided disk the last block holds the second copy of the list's head, and writing a text there would damage it.

- When the controller is not the first device in its slot, as on QEMU's newer kind of PC and on the laptop, the first line reads `Disk controller: found, device 31 (function 2) on bus 0 of the PCI list`.
- On a machine without an AHCI controller there is one line, `Disk controller: none found`.
- The name is the disk's own. The size is in MB, and in GB for a disk of 10 GB or more, rounded down.
- If the disk cannot be made ready the second line reads `Disk: not ready, because ...` with the reason: `no disk is plugged into the controller`, `the controller does not say where its controls are`, `the firmware did not hand the controller over`, `the disk's socket did not stop carrying out commands`, `the disk's socket did not stop taking answers`, `the controller cannot reach the memory the kernel has for it`, `the disk stayed busy`, `the disk reported that it could not do what was asked`, `the disk did not answer in time`, `the disk finished the command without sending a whole block`, `the disk's blocks are not 512 bytes long`, `the disk's socket is stopped`, or `the disk gave a number of blocks that cannot be true`.

The kernel carries on in every case. Without a disk, or without a notebook on it, the chat box keeps nothing and says nothing about it.

With the controller attached and a divided disk on it, "Free memory" read 195 MB when this was looked at, two less than without a controller (it reads 198 and 199 since the kernel's file got smaller; see [memory.md](memory.md)): the firmware keeps a little more for itself. With a disk that is not divided it reads 196. The two frames lent to the controller are taken after that line is printed.

## Waiting

All waiting for the controller is done by looking again and again, up to 3 million times (`PATIENCE`), because the setup runs before the timer's signals are let through. In QEMU giving up takes about 3 seconds, and after a command that was given up on, getting the socket going again may wait as long once more. The specification speaks in times instead: half a second for a socket to stop, 25 thousandths of a second and then 2 seconds for the firmware to let go. On a fast machine 3 million looks may be less than half a second.

## Limits

See [open-points.md](open-points.md). In short: the kernel reads and writes one block at a time, but for files, eight; the room for files is about 7.5 MB on the usual disks, and nothing makes it larger but a larger part; only an AHCI controller and the first disk on it are used; only startup code and the main loop use the disk; every list of parts it has read was made by this project's own script or tests; and several of the steps were never seen to matter in QEMU.
