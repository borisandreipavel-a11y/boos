# The network: the PCI list and the network card

Code: `src/pci.rs`, `src/network_card.rs`. The port and device-memory functions are in `src/processor.rs`; `map_device_memory` is in `src/page_tables.rs`.

So far the kernel finds the network card and sets it up. It sends and receives nothing yet.

## The PCI list

- A PC keeps its cards and built-in devices on the PCI list. A place on the list is named by three numbers: the bus (a row of slots, 0 to 255), the device (a slot of that row, 0 to 31) and the function (one of up to 8 devices sharing a slot).
- Each place holds a small table of facts about its device. The first 4 bytes are the maker (low half) and the model (high half). An empty place answers with every bit set.
- `pci_read(place, offset)` reads 4 bytes of that table. It takes two steps: write which place and which 4 bytes to port `0xCF8`, then read the answer from port `0xCFC`. The two steps belong together, so signals are switched off around them. `pci_read_8` picks one byte out of the 4.
- `pci_write(place, offset, value)` writes 4 bytes the same way. Only a few bytes of the table are settings; see "Setting the card up".
- Those two ports work with 4 bytes at a time, which is what `port_write_32` and `port_read_32` are for.
- `pci_find(maker, model)` walks the whole list and returns the first place that states that maker and model.
  - It tries every bus and every slot. It does not follow bridges; trying all 256 buses finds devices behind them as well.
  - If function 0 of a slot is empty, the slot is empty and its other functions are skipped.
  - The other functions are tried only if function 0 says there are several: bit 7 of the byte at offset 14.
- A device says where its ports and its memory are in six "address fields" of 4 bytes, starting at offset 16. `pci_memory_address(place, field)` returns the memory address in one of them. The lowest 4 bits of a field tell its kind and are not part of the address: bit 0 set means ports, and bits 1 and 2 holding the number 2 mean a 64-bit address whose upper half is in the next field.

## The network card

- QEMU's card is a "virtio" card: one that exists only in virtual machines and is made to be simple to drive.
- Its maker's number is `0x1AF4`. Its model is `0x1000` for QEMU's usual card, which knows an older and a newer way of working, and `0x1041` for the card that knows only the newer way.
- `network_card_find()` looks for either and returns its place.
- A network card of another make is not recognised and counts as none.

How the usual card shows up in QEMU 11.1, as seen with the monitor's `info pci` and read by the kernel itself:

- device 3 on bus 0, function 0;
- signal line 11. That line is on the second chip of the interrupt controller, which the kernel holds back entirely today; see [interrupts.md](interrupts.md);
- address field 0: ports at `0xc000`, 32 of them. This is the older way of working;
- address fields 4 and 5: 64-bit memory at `0xc000000000`, 16 KB. This is the newer way of working;
- a list of control groups, all in that memory: group 1 at its start, group 3 at `0x1000`, group 4 at `0x2000`, group 2 at `0x3000` with a knock step of 4.

## Which way of working, and why

The driver uses the newer way (the virtio specification's version 1 interface) only.

- The newer way is the one the specification is written for now, and the model `0x1041` card offers nothing else.
- It fits the kernel as it is. A waiting line's three areas may be anywhere, so each can be a single frame. The older way puts a waiting line in one block of several neighbouring frames, and the frame pile hands out single frames only. That is how the specification reads; the older way was not tried here.
- Its price: the card's controls are in memory far above the 4 GB the page tables cover, so that memory has to be mapped first, and the driver has to read the card's list to find them.
- A card with the newer way switched off is refused with "not set up, because it does not offer the newer way of working".

## Setting the card up

`network_card_setup(place)` does this, with device signals off. It returns the card's address, or the reason it could not finish. `efi_main` prints either.

1. **Settings in the PCI facts.** In the 4 bytes at offset 4 it sets three bits: the card may use its memory (bit 1), it may read and write the machine's memory (bit 2), and it sends no signals of its own (bit 10). The upper half of those 4 bytes is the card's status; it is written as zeros, because writing back what was read there would clear some of its flags.
2. **Finding the controls.** The byte at offset `0x34` starts a list. Each entry says its kind and where the next entry is; 0 ends the list. Entries of kind 9 describe a group of virtio controls: which group (byte 3), in which address field (byte 4), how far in (4 bytes at 8) and how long (4 bytes at 12). The driver takes the first entry for each of groups 1, 2 and 4, and ignores entries that point at ports.
3. **Mapping.** Each group's memory is made reachable with `map_device_memory`; see [memory.md](memory.md).
4. **The handshake.** The driver reports each step by writing marks to the card's state: start over (0), "noticed" (1), "can drive" (2), "features agreed" (8), "ready" (4). After starting over it waits for the state to read 0. After "features agreed" it reads the state back: the card keeps that mark only if it accepts the choice.
5. **Features.** The card offers 64 yes/no features in two halves of 32. The driver needs two and states only those: the card has an address of its own (bit 5) and the newer way of working (bit 32). If the card lacks either, the driver adds its own "giving up" mark (`0x80`) to the state and stops.
6. **The waiting lines.** Line 0 receives and line 1 sends. For each: choose it, read its length, give it three zeroed frames, tell the card their addresses, and switch it on.
7. **Ready.** After the last mark, the state is checked for the two failure marks: the driver's "giving up" (`0x80`) and the card's own "in trouble" (`0x40`), which only the card sets.
8. **The address.** The first six bytes of group 4 are the card's address.

The controls are read and written through `device_read_8`, `_16`, `_32` and `device_write_8`, `_16`, `_32` in `processor.rs`. Two rules:

- Each control has a width and must be used at that width. Reading a 2-byte control one byte at a time gave nonsense.
- The functions are "volatile": Rust must really do every read and write, once and in order. With ordinary reads and writes it may skip or merge them, which is wrong for a device.

## Waiting lines

Packets pass between driver and card through waiting lines (the specification calls them virtqueues). A line is three areas of memory that both sides read and write:

- **descriptions**: where each packet's memory is and how long, 16 bytes per packet;
- **from the driver**: the driver lists here what it hands to the card;
- **from the card**: the card lists here what it hands back.

What the driver relies on:

- Each area is one frame. A frame holds 256 descriptions, so the driver asks for a shorter line if the card offers a longer one. QEMU's lines are 256 long.
- The card uses real memory addresses. It knows nothing of the kernel's page tables, so the areas, and later the packets, must be frames, never heap memory.
- The first two bytes of the "from the driver" area are set to 1, which tells the card not to send a signal when it hands something back. The driver will look by itself.
- To tell the card that a line has news, the driver writes to that line's knocking place: the start of group 2, plus the line's own number from the card times the knock step.

The driver keeps where the groups are (`COMMON`, `KNOCK`, `KNOCK_STEP`, `CARD`) and both lines (`RECEIVE_LINE`, `SEND_LINE`) for the code that will send and receive.

The monitor shows the card's side of all this: `info virtio` lists the card's path, `info virtio-status <path>` shows the handshake's marks and the features in use, and `info virtio-queue-status <path> <line>` shows a line's length and the addresses of its three areas.

## QEMU's built-in network

`run.bat` attaches the card to QEMU's built-in network (`-netdev user`). QEMU plays a small network of its own and passes traffic on through the host computer:

- the network is `10.0.2.0` and the card's own address is `52:54:00:12:34:56`, as the monitor's `info network` shows;
- by QEMU's documentation the gateway is at `10.0.2.2` and a name server at `10.0.2.3`. The kernel has not talked to either yet;
- nothing outside can reach the kernel; only what the kernel sends out gets answers.

With the card attached, the firmware uses a little more memory during startup, and "Free memory" reads 205 MB instead of 206.

Nothing is sent yet. A boot with QEMU recording every packet on that network, from the firmware's start to three seconds after the kernel's prompt, recorded none, also after the card was set up. The option for that is in [testing.md](testing.md).
