# The network: the card, the stack, and fetching a page

Code: `src/pci.rs`, `src/network_card.rs`, `src/intel_card.rs`, `src/network.rs`, `src/page.rs`, and the network stack in `vendor/`. The port and device-memory functions are in `src/processor.rs`; `map_device_memory` is in `src/page_tables.rs`.

So far the kernel finds the network card, a virtio card or one of Intel's, sets it up, and sends and receives packets through it. At startup it asks one question by hand: who is the gateway. After that a network stack, smoltcp, takes over in a task of its own and gets the kernel a network address. With that address the kernel fetches one web page over an encrypted link: it looks up the site's name, connects, lets the site prove who it is, asks for the page and prints how it begins.

## The PCI list

- A PC keeps its cards and built-in devices on the PCI list. A place on the list is named by three numbers: the bus (a row of slots, 0 to 255), the device (a slot of that row, 0 to 31) and the function (one of up to 8 devices sharing a slot).
- Each place holds a small table of facts about its device. The first 4 bytes are the maker (low half) and the model (high half). An empty place answers with every bit set.
- `pci_read(place, offset)` reads 4 bytes of that table. It takes two steps: write which place and which 4 bytes to port `0xCF8`, then read the answer from port `0xCFC`. The two steps belong together, so signals are switched off around them. `pci_read_8` picks one byte out of the 4.
- `pci_write(place, offset, value)` writes 4 bytes the same way. Only a few bytes of the table are settings; see "Setting the card up".
- Those two ports work with 4 bytes at a time, which is what `port_write_32` and `port_read_32` are for.
- Bytes 9, 10 and 11 of the table say what kind of thing the device is. `pci_find_kind(broad_kind, narrow_kind, way)` walks the list in the same way as `pci_find` below and returns the first place that states those three numbers. It finds a device whose maker and model are not known beforehand; the disk controller is found that way, see [disk.md](disk.md).
- `pci_find(maker, model)` walks the whole list and returns the first place that states that maker and model.
  - It tries every bus and every slot. It does not follow bridges; trying all 256 buses finds devices behind them as well.
  - If function 0 of a slot is empty, the slot is empty and its other functions are skipped.
  - The other functions are tried only if function 0 says there are several: bit 7 of the byte at offset 14.
- A device says where its ports and its memory are in six "address fields" of 4 bytes, starting at offset 16. `pci_memory_address(place, field)` returns the memory address in one of them. The lowest 4 bits of a field tell its kind and are not part of the address: bit 0 set means ports, and bits 1 and 2 holding the number 2 mean a 64-bit address whose upper half is in the next field.

## The network card

- QEMU's card is a "virtio" card: one that exists only in virtual machines and is made to be simple to drive.
- Its maker's number is `0x1AF4`. Its model is `0x1000` for QEMU's usual card, which knows an older and a newer way of working, and `0x1041` for the card that knows only the newer way.
- `network_card_find()` looks for either and returns its place.
- Two models of Intel's cards have a driver of their own; see "Intel's network card" below. A network card of another make is not recognised and counts as none.

How the usual card shows up in QEMU 11.1, as seen with the monitor's `info pci` and read by the kernel itself:

- device 3 on bus 0, function 0;
- signal line 11. That line is on the second chip of the interrupt controller, which the kernel holds back entirely today; see [interrupts.md](interrupts.md);
- address field 0: ports at `0xc020`, 32 of them (at `0xc000` before the disk controller was attached, which now has those). This is the older way of working, which the kernel does not use;
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

The driver keeps where the groups are (`COMMON`, `KNOCK`, `KNOCK_STEP`, `CARD`) and both lines (`RECEIVE_LINE`, `SEND_LINE`).

How the three areas are laid out, as the driver uses them:

- A description is 16 bytes: the memory's address (8), its length (4), marks (2) and a link to another description (2, unused). The mark 2 means the card may write into that memory.
- The "from the driver" area is marks (2 bytes), the driver's counter (2 bytes), then a list of description numbers, 2 bytes each.
- The "from the card" area is marks (2 bytes), the card's counter (2 bytes), then a list of entries of 8 bytes: which description the card used (4) and how many bytes it wrote there (4).
- The counters are 2 bytes wide and start again at 0 after 65535. The place in a list is the counter's remainder after dividing by the line's length.
- Handing something to the card goes in this order: the list entry, then the counter, then the knock (`hand_to_card`). The knock is a 2-byte write of the line's number.
- All of it is read and written with the volatile device functions, because the card changes this memory too.

## Sending and receiving packets

- Every packet handed to the card, and every packet it hands back, starts with 12 bytes of notes meant for the card itself (`NOTES`). All zeros means "nothing special", and the driver uses nothing else. A recording of the packets confirms the length: the kernel's question arrives on the network starting with its first real byte.
- **Receiving.** At the end of the setup the driver lends the card 16 frames (`RECEIVE_FRAMES`), each described as writable by the card, and remembers them in `RECEIVE_FRAME_LIST`. The card puts each arriving packet into one of them.
- `network_card_receive(into)` looks once. If the card's counter is ahead of the driver's (`PICKED_UP`), it copies the packet, without the notes, into `into`, lends the frame to the card again, and returns the packet's length. Otherwise it returns nothing. It does not wait.
  - It uses the description number the card names, but only if that number is one of the 16 lent frames.
  - It never copies more than a frame holds or than `into` has room for.
- **Sending.** There is one frame for packets going out (`SEND_FRAME`). `network_card_send(packet)` waits, up to a million looks, until the card has taken the packet before this one, then writes the notes and the packet into the frame and hands it to the card. It says whether it did. A packet longer than 1514 bytes (`LONGEST_PACKET`) is refused.
- Both switch device signals off while they work, so tasks can call them.
- The card sends no signals. Nothing tells the kernel that a packet has arrived; code that wants one has to keep looking.

## Intel's network card

`src/intel_card.rs` drives a second kind of card: Intel's gigabit cards of the 8254x family, which Intel's "PCI/PCI-X Family of Gigabit Ethernet Controllers Software Developer's Manual" (revision 4.0, 2009) describes. What the driver does comes from that manual; the code names its chapters and tables where it matters.

- **Which models.** Two, the ones that virtual machines play: the 82540EM (maker `0x8086`, model `0x100E`, or `0x1015`, both in the manual's table of models) and the 82545EM (model `0x100F`). QEMU plays the first as its card `e1000` and the second as `e1000-82545em` (its own list, `-device help`). VirtualBox's guide (version 7.2) names them "Intel PRO/1000 MT Desktop (82540EM)" and "Intel PRO/1000 MT Server (82545EM)", and VMware's own page says its card "E1000" is an 82545EM. The manual says that the two models' controls are "essentially the same".
- **Not known:** the other models of the manual (82541, 82544, 82546, 82547, and the 82545EM for fibre cables, `0x1011`); VirtualBox's third Intel card, "PRO/1000 T Server", an 82543GC, which the manual does not cover; and Intel's later cards, which Linux drives with other drivers (`e1000e`, `igb`, `igc`), among them the 82574 that QEMU plays as `e1000e` and VMware as "E1000E", and the network ports built into many PCs with Intel's chips.
- `intel_card_find()` looks for the three model numbers in turn and returns the place and the model's name.

### Which card is used

`efi_main` looks for the virtio card first. If there is none, or it cannot be set up, it looks for an Intel card. One card is used; another one is left as the firmware left it. A start with the virtio card prints the same lines as before there was a second driver; the Intel card's first line names it, `Network card: found, an Intel 82540EM, device 3 on bus 0 of the PCI list`. When an Intel card was set up (`intel_card_ready`), `network_card_send` and `network_card_receive` hand over to `intel_card_send` and `intel_card_receive`, so the rest of the network code is the same for both kinds.

### Setting the Intel card up

`intel_card_setup(place)` does this, with device signals off, in the order of chapter 14 of the manual. It returns the card's address, or the reason it could not finish.

1. The same three settings in its PCI facts as for the virtio card: it may use its memory, it may read and write the machine's memory, it sends no signals of its own.
2. Its controls are 128 KB of memory named by address field 0 (a field that names ports is refused), each control 4 bytes wide. They are made reachable with `map_device_memory`; in QEMU they lie below 4 GB, where nothing has to be added.
3. Every signal of the card is masked. If something used the card before, the firmware looking for a system on the network, say, it is stopped and started over: the manual says that a receiver that was switched off must start over before it is switched on again. Receiving or sending switched on, or a ring set up, shows such use; a card that was switched on and not used since has all four at zero, and is in the state the manual's setup begins from. Starting over: receiving and sending are switched off, then the card is told to start over (bit 26 of its main settings). The manual asks for about a microsecond before the card is touched again; since the tick count stands still at startup, the pause counts the processor's own steps, 100,000, at least ten microseconds on a processor slower than 10 GHz. Then the driver looks until the bit has cleared. A card nobody used is not started over, because VirtualBox keeps its card's link down for five seconds after every start-over (see "Other virtual machines").
4. The main settings: the link and its speed as the card's cable part finds them (bits 5 and 6), with forced speed and duplex, the link reset of fibre cards, the inverted loss signal, tags and the cable part's reset all cleared. The four controls of flow control are set to zero, as the manual says for a driver that does not use it.
5. The card's address is read from its small memory chip (its EEPROM): the first three words, each two bytes of the address with the first byte low, through the "EEPROM read" control (`0x14`), in the layout the manual gives these two models. An address of all zeros, all ones, or one for a group of machines is refused. It is written into the card's first receive address with the mark that makes it count, and the 128 lines of the table for groups of machines are cleared.
6. The receive ring (below), then receiving is switched on, as the manual wants it, only once the ring is ready: receive, take packets sent to everybody, leave off the 4-byte check at the end of each packet. The size of a buffer stays at the card's own, 2048 bytes.
7. The send ring, then sending is switched on: send, fill up short packets, 10h tries after a collision and a collision distance of 40h, as chapter 14 names them, and the pause between packets set to 10, 10 and 10, from its table. The description of that control gives 8 and 6 for the second and third parts; both count only on a cable that cannot talk both ways at once.

### The rings

- A ring is a list of slots that the card goes round in a circle. Each slot has a description of 16 bytes: where its buffer is (8 bytes), a length, what to do or what was done, and a status byte whose bit 0 says that the card is done with the slot. A ring's descriptions take one frame; the buffers are 2048 bytes, two to a frame. The receive ring has 64 slots and the send ring 8, the fewest the card allows (a ring's length must be a multiple of 128 bytes): 38 frames in all, about 150 KB.
- Each ring has two places: the card's (the head), where it works next, and the kernel's (the tail), where the kernel hands over the next slot. The card uses the slots from its own place up to the one before the kernel's; when the two are equal, the card has nothing.
- **Receiving.** The setup gives the card 63 of the 64 slots. `intel_card_receive(into)` looks at the slot after the last one picked up. If its done mark is set, it copies the packet into `into`, never more than a buffer holds or than `into` has room for, makes the slot ready again and moves the kernel's place onto it, which gives the slot before it back to the card. Otherwise it returns nothing; it does not wait. A packet that does not end in its slot would be longer than the card takes; it is passed over.
- **Sending.** `intel_card_send(packet)` copies the packet into the next send slot, fills it up with zeros to 60 bytes, the shortest a network carries, and asks the card to add the 4-byte check and to set the done mark. One slot always stays free, so that the kernel's place never catches up with the card's and the card never takes a full ring for an empty one: before it uses a slot, the driver waits, up to a million looks, until the card is done with the slot after it. The card does the slots in order, so it is done with this one then too. The setup marks every send slot done, which the driver takes to mean "free". So up to seven packets can wait to go out, where the virtio card's driver has one frame for sending.
- **No signals.** All of the card's own signals are masked. The manual allows that: software "can determine if a receive buffer is valid by reading descriptors in memory". The card is told to write each slot back as soon as it is done with it (write-back threshold 0, counted in slots); its default holds slots back until more than one is done. QEMU writes back at once either way, so that setting was not seen to matter.
- What the driver writes into memory the card reads is in place before the kernel's place moves, and nothing of a packet is read before its done mark. `compiler_fence` keeps the compiler from moving those reads and writes around.

### The Intel card in QEMU

- QEMU's `e1000` takes the virtio card's place as device 3 on bus 0, with signal line 11, and the address `52:54:00:12:34:56`. In a look with the firmware alone, its controls were 128 KB at `0x81040000`, below 4 GB.
- **QEMU's Intel card holds every arriving packet back for a second after receiving is switched on.** Its source (`hw/net/e1000.c`, version 11.1.0) starts a timer of 1000 ms whenever the receive settings are written, and takes no packet until it has run out; the packets that arrive meanwhile wait and are handed over then. So the answer to the kernel's first question comes about a second after the setup: after 2,444,855 looks in a measurement, more than one round of looks of the gateway question (below), which therefore asks twice. On a computer that looks faster, both rounds can end before QEMU hands the answer over, and the line then says that the gateway did not answer; a GitHub computer did so once. The stack's own questions come later and are answered either way.
- QEMU's firmware leaves the card unused (all four signs of use read zero), so a start does not start it over. When it is told to, QEMU's card does not start over either: its handling of the main settings only clears the bit.
- A recording of a start with the card on QEMU's network with no way out held ten packets: the two that the firmware sends before the kernel starts, the kernel's question twice, as the 60 bytes it built, with the gateway's two answers, and the four packets of the address request.

### Other virtual machines

- **VirtualBox:** its two "PRO/1000 MT" cards are the two models above. It does not give them by default to the kind of machine that the steps in [startup.md](startup.md) make, "Other/Unknown (64-bit)": its guide calls AMD's PCnet-FAST III "the default setting on x86 guests", and its source (version 7.2.22) gives that card to machines of that kind, and to every new card that nothing else is said about. The kernel has no driver for it. The Intel card would be chosen with `--nic-type1=82540EM`. Not tried in VirtualBox.
- What VirtualBox's source (`DevE1000.cpp`, version 7.2.22) says about the steps above: it starts its card over when told to, and then keeps the link down for five seconds (`LinkUpDelay`, 5000 ms by default), receiving nothing and sending nothing meanwhile; it reads a word of the memory chip at once; it holds no packet back after receiving is switched on, as QEMU's card does; it writes each slot back as soon as it is done, and has no control for the write-back threshold (writes to it are dropped); it does not add the 4-byte check to packets it sends, and adds one to received packets only when it is not told to leave it off. A card that nobody used sees its link at once when the driver sets bit 6 of the main settings.
- **VMware:** its card "E1000" is an 82545EM by VMware's own page. Which card VMware Workstation gives a new machine of an unknown kind was not found in its documentation. Not tried.

## The gateway question

`gateway_ask(card_address)` in `network.rs` is the kernel's first packet, put together by hand.

- Every machine on a network has a hardware address (6 bytes, its network card's) and a network address (4 bytes, such as `10.0.2.2`). Packets are delivered by hardware address, so before talking to a machine one asks the whole network "who has this network address?" (the address question, ARP).
- The gateway is the machine that passes packets on to the outside: `10.0.2.2` on QEMU's built-in network.
- The question is a packet of 60 bytes, the shortest a network carries: to everybody (`ff:ff:ff:ff:ff:ff`), from the card, kind `0806`, and inside it "1" for question, who asks, and whose address is wanted.
- The kernel has no network address yet. For this question it assumes `10.0.2.15`, the first address QEMU's network hands out (`ASSUMED_OWN_ADDRESS`).
- It then looks at arriving packets until one is an answer (kind `0806`, "2" for answer) from `10.0.2.2`, and returns the hardware address in it. Other packets are passed over.
- It runs at startup with device signals off, so the tick count stands still and cannot time the wait. The wait is bounded by looks instead: 2,000,000 (`LOOKS`), under a second in QEMU (0.7 to 0.8 seconds in measurements with either card). If no answer has come by then, it asks once more and waits as long again (`ASKINGS` is 2), then gives up. With the virtio card the real answer needed 32 looks on average and 283 at most; QEMU's Intel card hands it over only a second after its setup, in the second round (see "The Intel card in QEMU").
- `efi_main` prints the gateway's hardware address, `52:55:0a:00:02:02` in QEMU, or that the gateway did not answer.

This by-hand code is a demonstration from before the network stack. The stack asks such questions itself, for whatever address it needs, and does not use this code. On a network that is not `10.0.2.0` the by-hand question gets no answer and prints so, while the stack carries on unharmed.

## The network stack

The rules of the network (getting an address, finding other machines, keeping connections going) are not written in this kernel. They come from smoltcp, version 0.14.0, a network stack made for systems without an operating system underneath. It is the only code here that was not written for this kernel. It is kept as a copy in `vendor/`, and [vendor/README.md](../vendor/README.md) says why and what was changed in the copy.

`Cargo.toml` switches smoltcp's default features off, because they need an operating system. Six are switched on: `alloc` (it may use the kernel's heap), `medium-ethernet`, `proto-ipv4`, `socket-dhcpv4` (asking the network for an address), `socket-dns` (looking up names) and `socket-tcp` (connections). The last two brought no new crate. The feature `socket-tcp-cubic` must stay off: it uses floating point.

smoltcp needs three things from the kernel, all in `network.rs`:

- **A way to send and receive packets.** `Card` is the adapter over the driver. smoltcp describes what it needs as a trait called `Device`, and `impl Device for Card` provides it.
  - `receive` looks once with `network_card_receive`. If a packet has arrived, it hands smoltcp an `ArrivedPacket` holding it, together with a `PacketToSend`.
  - `transmit` always hands out a `PacketToSend`. When smoltcp uses it, it says how long the packet is and writes it, and `network_card_send` sends it.
  - `capabilities` says: Ethernet, at most 1514 bytes per packet, one packet at a time. smoltcp counts the 14 bytes that start every Ethernet packet as part of that length. It takes "one packet at a time" for arriving packets as well: on a connection it lets the other side send one packet's worth and then waits for the kernel to confirm it (`max_window_size` in the copy's `iface/packet.rs`).
  - Both kinds of packet live on the heap, so they take almost no room on the task's stack.
- **The time.** `now()` gives milliseconds since the kernel started, from the tick count. It moves in steps of 10.
- **Somebody who calls it regularly.** `network_task` calls `Interface::poll` once per tick and then waits one tick. The card sends no signals, so looking again is the only way to notice a packet.

Also:

- **The start number.** smoltcp wants a number that differs at every start of the kernel, for picking port numbers and the like. `time_stamp()` in `processor.rs` gives the processor's count of its own steps, which did differ between boots. smoltcp's documentation says the number need not be secret. It is not, and it would not do for encryption.
- **`network_start(card_address)`** is called from `efi_main` once the card is set up. It keeps the card's address and adds the task. With no card, or a card that could not be set up, the stack is not started.
- The task uses up to 56 KB of its 256 KB stack (100 KB before the outside crates were built optimized). Nearly all of that is the arithmetic of an encrypted link; without one it was 11.5 KB with a page fetch and 8.7 KB before there was one. smoltcp's own objects are small: the interface measured 392 bytes when only the address request was switched on.

## Getting an address

- The stack asks the network for an address by itself (the address request, DHCP). `network_task` adds one "socket" for that, `dhcpv4::Socket`, and after each `poll` asks it for news.
- The exchange is four packets: the kernel asks everybody, a server offers an address, the kernel requests that address, the server confirms.
- On "given an address": the task tells smoltcp to use that address, sets the gateway as the place to send packets for the outside, and prints `Network: this machine was given the address 10.0.2.15 by 10.0.2.2`.
- The first news is always "no address", before anything was asked. Nothing is printed for it. A line is printed only when an address arrives, and one more if an address the kernel had is lost.
- An address is lent for a time. smoltcp renews it by itself, half-way through, and reports nothing as long as the address stays the same.
- If nobody answers, smoltcp keeps asking quietly. Nothing is printed and the kernel carries on.

The monitor shows the card's side of all this: `info virtio` lists the card's path, `info virtio-status <path>` shows the handshake's marks and the features in use, and `info virtio-queue-status <path> <line>` shows a line's length and the addresses of its three areas.

## Fetching a page

`page.rs` fetches one page from the web over an encrypted link and prints how it begins. The site is `example.com` (`SITE`), which its owners keep for examples. `network_task` calls `page_fetch` once, the first time the kernel has an address.

The fetch runs inside the network's own task, because only that task may touch the stack. It is written as one run from top to bottom. Wherever it has to wait for the network it calls `stack_turn`: one `Interface::poll`, then a wait of one tick. So the stack keeps working during a fetch and the address is still renewed, but news about the address is read only when the fetch is over.

The steps:

1. **Can this machine encrypt?** `secure_ready()` is asked first. The page is fetched over an encrypted link or not at all: if the answer is no, nothing is sent, not even the site's name. See [encryption.md](encryption.md).
2. **The name.** Machines are reached by network address, but sites are known by name. A name server is a machine that knows which address belongs to which name (the name system, DNS). Together with the address, the network names a name server, and the task keeps the first one named. `name_lookup` adds a `dns::Socket` for that server, asks for the name's address (`start_query`, kind `A`: an address of the 4-byte sort) and waits for the answer. smoltcp is set to keep one address per answer (`DNS_MAX_RESULT_COUNT` in the copy's `config.rs`), so a site with several addresses is tried at one only. The kernel prints `Network: the name example.com belongs to the address ...`.
3. **The connection.** A connection (TCP) is an agreement between two machines to pass bytes back and forth so that none is lost and all arrive in order. smoltcp does that work. `site_exchange` adds a `tcp::Socket` with room for 4096 arrived bytes and 512 bytes to send. A port is the number that says which conversation on a machine a packet belongs to. Sites wait for requests over an encrypted link on port 443 (`WEB_PORT`), and for requests in the open on port 80. This side takes a number between 49152 and 65535, picked by `time_stamp()` so that it differs between boots.
4. **The encrypted link.** `secure_exchange` in `tls.rs` greets the site over the connection, checks its certificate and agrees on keys; [encryption.md](encryption.md) describes it. `ConnectionWire` in `page.rs` is the connection in the form `tls.rs` wants: it sends bytes, waiting for room where the connection has none, and receives bytes, waiting for some to arrive. The kernel prints `Network: example.com proved who it is: ...`.
5. **The request.** Three lines in the web's language (HTTP): `GET / HTTP/1.0`, then `Host: example.com`, then an empty line that ends the request. Nothing else is sent: no line names the kernel or the machine. The request travels through the link, scrambled. With `HTTP/1.0` the site ends the exchange when the page is sent.
6. **The answer.** It arrives through the link, unscrambled piece by piece, as one run of bytes in three parts: a first line saying how it went (`200 OK` means "here is the page"), lines of notes about the page, an empty line, then the page. `Answer::take` is given every byte as it arrives. It keeps the first line, counts its way through the notes without keeping them, and keeps the first rows of the page. The rest of the page is only counted.
7. **Goodbye.** The site says through the link that it has sent everything, and the kernel answers the same way. Then the kernel closes the connection underneath properly (`close`). If anything went wrong it drops the connection instead (`abort`), which tells the site so. It gives the stack up to a second to pass that on and then takes the connection off the stack's list.

What is printed about the page, as one text so that other tasks' lines cannot land inside it:

- `Network: example.com answered "HTTP/1.1 200 OK". Its page begins:`
- up to 8 rows of the page (`ROWS_SHOWN`), each up to 72 signs (`ROW_LENGTH`) and set in by four spaces. A longer line goes on in the next row. Empty rows are left out;
- `Network: the whole page is 577 bytes long.` "Whole" means that the site said, through the encrypted link itself, that it had sent everything. Nobody on the way can fake that or cut the page short unnoticed. If the connection simply ends, the last line reads `Network: the page is not whole: the connection broke or took too long. N bytes of it came.`

**The page is text from outside.** Somebody else wrote it, and a terminal obeys certain bytes as commands. `plain_sign` therefore lets only plain letters, digits and signs through (bytes 32 to 126). Byte 13, which comes before each line end, is dropped, and every other byte becomes a dot. The first line gets the same treatment and is cut at 72 signs. However long a line of notes is, only its length is counted. `plain_text` cleans a whole text the same way; the reasons printed for a failed link pass through it.

**No wait is endless.** The name lookup may take 5 seconds, agreeing on the connection 5, the greeting and the answer together 15, and the goodbye 1 (`LOOKUP_WAIT` and the three constants below it, counted in ticks). When something fails, one line says so and the kernel carries on: `Network: no page fetched, because ...`

| The reason printed | When |
| --- | --- |
| the network named no name server | the address came without one |
| the name could not be asked for | smoltcp refused the question |
| the name server did not answer in time | 5 seconds without an answer |
| the name server does not know the name | the name server said so |
| the name server knows no address for the name | an answer without an address |
| the connection could not be started | smoltcp refused to start it |
| the site refused the connection | the site answered "no" |
| the site did not agree to a connection in time | 5 seconds without an answer |
| the connection broke | it ended while bytes were still to be sent |
| the site took too long | 15 seconds passed and no part of the answer had come. If part of it had, that part is shown as a page that is not whole |
| the site sent nothing | the link came about, but no byte of an answer |

The reasons that have to do with encryption and certificates are listed in [encryption.md](encryption.md).

How it goes in QEMU:

- From the name question to the end takes about 1.8 seconds with the real site. One whole second of that is a pause inside smoltcp: after asking for one machine's hardware address it asks for no other for a second (`SILENT_TIME` in the copy's `iface/neighbor.rs`), and a connection that lacks such an address waits just as long before it tries again (`DISCOVERY_SILENT_TIME` in `iface/socket_meta.rs`). The name server's hardware address is asked for first, so the gateway's has to wait. The by-hand gateway answer from startup is not handed to the stack. Most of the rest is the arithmetic of the greeting.
- The lines about the link and the page therefore land among the demonstration tasks' lines; after the third of them in both runs against the real site.
- A page of 300,000 bytes took about 6 seconds through the link, some 50 KB a second: one packet every two ticks, as without encryption. The card's adapter says "one packet at a time", so the site sends one packet and waits for the kernel to confirm it, and the kernel looks once per tick.
- Three fetches in a row left the count of free frames where it was after the first.

Every start of the kernel fetches the page, so every start sends one name question and makes one encrypted exchange with the site. The site's name can be read on the way; the request and the page cannot. For test boots that should stay off the internet, see [testing.md](testing.md).

### One exchange with any site

Steps 1 to 3 and the encrypted exchange are one function, `site_exchange`. It is given the site's name, the request as bytes, how long the exchange may take (`Waits`), and a piece of code that takes each piece of the answer and says whether it wants more. It answers whether the site said through the link that it had sent everything. Only the network's task may call it.

- **How long it may take** is counted from the moment the site agreed to the connection: `first` for the greeting and the first piece of the answer, and `rest` for the whole answer, or, when `restarts` is set, for each next piece after the one before it. `Waits::one(15)` is one wait of 15 seconds for all of it, as the page has always had.
- **Saying stop.** When the piece-taker wants no more, the encrypted link says goodbye from this side (its closure alert), reads nothing more and hands nothing more on, and the connection underneath is closed properly, as after the site's own goodbye. The answer is then not counted as whole by the site's word; whoever stopped it knows why it did.
- `page_get` calls it with the example site, a `GET` request and `Waits::one(15)`, takes every piece, and reads the answer with `Answer`. The question to the model calls it with the provider's site, a `POST` request and `Waits::one(60)`, takes every piece, and reads the answer in its own way; see [model.md](model.md). A file is fetched through it too, with two waits and a stop; see "Fetching a file" below.

### Fetching it again

The page is fetched once, at startup. The line `fetch`, which once fetched it again from the chat box, is an ordinary line now, and goes to the model like any other (see [tools.md](tools.md)). Every exchange with the provider goes through the same `site_exchange`; the sockets an exchange uses are taken out of the stack's set when it ends, so exchanges can follow each other without end: twelve fetches in a row took no frame, when they could still be asked for.

## Fetching a file

Code: `src/download.rs`, and `HeadReader` in `src/page.rs`. What the main loop does with what comes back, the questions to the person and keeping the file, is in `src/files.rs`; see "download_file" in [tools.md](tools.md) and "The room for files" in [disk.md](disk.md).

A file is fetched in **hops**: one request and its answer each, one errand of the network's task each (`Errand::Download`, with the address). A hop brings the file, or an address the site sends one on to, or why there is no file (`Fetched`). The main loop decides whether the next hop goes, because only it may ask the person, and a site not contacted before is asked about first.

What the web's rules say, as read for this (RFC 9112 for the messages of HTTP/1.1, RFC 9110 for what they mean, RFC 3986 for addresses), is named where it is used.

### The address

`address_read` reads an address that came from outside, from the model or from a site that sends one on, and checks it before anything is sent. What is wrong comes back in words, which the chat box says.

| Taken only if | Otherwise |
| --- | --- |
| at most 1000 signs, all plain (bytes 33 to 126) | `it is longer than 1000 signs`, `it holds signs an address may not have` |
| it begins with `https://` (in any capitals) | `it is not an encrypted address (https)` for `http://`, `it is no address that begins with https://` for anything else |
| no name and password before the site (an `@`): the web's rules say a recipient should treat one from an untrusted source as an error (RFC 9110, 4.2.4) | `it holds a name and a password` |
| no port but 443, the web's encrypted port, which is also the one taken when none is named (RFC 9110, 4.2.2) | `it names a port other than 443` |
| the site is a name: parts of small letters, digits and hyphens between dots, at least two parts, none empty or beginning or ending with a hyphen, at most 253 signs, and the last part not digits alone, so that a machine's number is never taken; capitals become small letters | `its site's name is not one I can look up` |

What follows a `#` stays on this side and is not kept. In the path, steps of `.` and `..` are worked out as RFC 3986 says (5.2.4). An address without a path asks for `/`.

### The request

Word for word, each line ending in bytes 13 and 10, with an empty line behind the last:

```text
GET /a.pdf HTTP/1.0
Host: files.example.org
Accept-Encoding: identity
Connection: close
```

Nothing else is sent: no line names the kernel, the machine or the person. That includes no `User-Agent`: the web's rules say a client should send one "unless specifically configured not to do so" (RFC 9110, 10.1.5), and this kernel sends none, as for the page and the question to the model.

- **HTTP/1.0.** A server must not send an answer in pieces with their lengths in between ("chunked", the note Transfer-Encoding) unless the request says HTTP/1.1 (RFC 9112, 6.1). Without "keep-alive", the connection is closed after the answer (RFC 9112, 9.3). A server answers with the highest version it knows whose first number is not higher than the request's (RFC 9110, 6.2), so the first line of the answer usually says `HTTP/1.1`.
- **Accept-Encoding: identity** asks for the file as it is, not packed: a request without that note counts as taking any packing (RFC 9110, 12.5.3), and the requests for the page and to the model, which do not send it, are answered unpacked only because those sites choose to. A server only should keep to it, so the answer is checked as well.

### The answer's head

`HeadReader` reads the first line and the lines of notes up to the empty line as the pieces arrive, however they are cut, even in the middle of a line. A line ends in byte 10, with or without byte 13 before it. The head may take 16 KB at most; a longer one stops the hop with `its notes are longer than I read`, and an answer that does not begin with `HTTP/` with `its answer does not begin the way an answer on the web does`.

It keeps the three digits of the first line and up to 40 signs of the words behind them, and five notes, whose names are told apart without regard to capitals:

| Note | What the reader keeps |
| --- | --- |
| Content-Type | what kind of thing is sent, in small letters, up to 100 signs |
| Content-Length | how long the body is, if written as digits alone; two that differ, or one that is not digits, count as unreadable (RFC 9110, 8.6, lets a recipient reject them) |
| Transfer-Encoding | that it is there |
| Content-Encoding | how the body is packed |
| Location | where the site sends one on to, as written, if it is plain signs and at most 2048 of them; otherwise as unusable |

Every text is cleaned like all text from outside (see "Fetching a page"). A line that begins with a space (a note going on from the line before, which the web no longer allows) and a line without a colon are passed over. The streaming of the model's answers is meant to use the same reader.

### What the head decides

| First line | What happens |
| --- | --- |
| 200, with Transfer-Encoding | no file: `it sent the file in pieces with their lengths in between ("chunked"), which it should not for this kind of request` |
| 200, with Content-Encoding other than `identity` | no file: `it sent the file packed ("gzip"), which I do not take` |
| 200, with an unreadable length | no file: `it gave a length I cannot read`; an invalid length in an answer means the answer is to be thrown away (RFC 9112, 6.3) |
| 200, with a length over 4 MB | no file, before any of it comes: `the file is 4.8 MB, more than the 4 MB I take` |
| 200 otherwise | the file comes |
| 301, 302, 303, 307 or 308 | the site sends one on: the Location goes back to the main loop, as written; without one, `it sends me on, but does not say where` |
| anything else | no file: `it answered 404 Not Found`, with the number and its words. A server must not send a 1xx answer to an HTTP/1.0 client (RFC 9110, 15.2), so one is taken as any other number |

When the head decides against the file, the hop says stop at once.

### The file

The bytes behind the head are kept in memory, at most 4 MB (`FILE_MOST`); with a length, the room is taken in one go. More than 4 MB stops the hop as soon as the bytes pass it: `it is larger than the 4 MB I take`.

- **With a length,** the file is whole when that many bytes have come, and the hop says stop then; a client should take an answer as complete once it has as many bytes as its length says (RFC 9112, 9.8). If the connection ends first, or the wait runs out: `the file did not come whole: 5000 of 20000 bytes came` (RFC 9112, 6.3: the message is incomplete). More bytes than the length: `it sent more than the length it gave`.
- **Without a length,** the file is what came before the site closed the connection (RFC 9112, 6.3), and it counts as whole only if the site said goodbye through the encrypted link: such an answer "is complete only if a valid closure alert has been received" (RFC 9112, 9.8). Otherwise: `the file did not come whole: the connection ended without the site's goodbye`.
- **No answer:** `no answer came:` and the reason of the exchange, such as `the site took too long`; a head that never ended: `its answer ended before its notes were over`; nothing at all: `it sent nothing`.

**The waits** of a hop: the greeting and the first piece of the answer within 15 seconds, the whole hop within 3 minutes. At the link's speed, some 50 KB a second (see "How it goes in QEMU" above), the largest file takes about 80 seconds.

**The terminal** has one line for each hop, after it: `Download: https://files.example.org/a.pdf: the file, 12016 bytes, whole`, `Download: https://files.example.org/go/a.pdf: sent on to ../a.pdf`, or `Download: ...: no file, because ...`, the addresses cut at 120 signs.

### An address a site sends one on to

`address_join` reads the Location against the address that was asked for, as RFC 3986 says (5.2) and RFC 9110 asks of a Location (10.2.2): a whole address stands by itself; one that begins with `//` names another site; one that begins with `/` is on the same site; an empty one, or one of a query alone, keeps the path; any other is read from the folder of the address asked for (`../a.pdf` from `/go/a.pdf` is `/a.pdf`). The result is read and checked as every address is, so a site cannot send the kernel to `http://`, to another port or to a machine's number.

## QEMU's built-in network

`run.bat` attaches the card to QEMU's built-in network (`-netdev user`). QEMU plays a small network of its own and passes traffic on through the host computer:

- the network is `10.0.2.0` and the card's own address is `52:54:00:12:34:56`, as the monitor's `info network` shows;
- the gateway is at `10.0.2.2`, with the hardware address `52:55:0a:00:02:02`; it answered the kernel's question. It also answers the address request, and hands out `10.0.2.15` first;
- a name server is at `10.0.2.3`, and the answer to the address request names it. QEMU passes name questions on to the host computer's own name lookup;
- `10.0.2.2` also stands for the host computer itself: a connection to it reaches a program that listens on the host's own address `127.0.0.1`. Tests of the page fetch use that. Where no program listens, QEMU does not pass the host's refusal on: the kernel's requests to connect simply get no answer;
- with `restrict=on` added to `-netdev user`, nothing gets out, and the answer to the address request names no name server;
- the network can be changed for a test: `-netdev user,id=net0,net=192.168.76.0/24,dhcpstart=192.168.76.9` made the kernel print `192.168.76.9`, given by `192.168.76.2`;
- nothing outside can reach the kernel; only what the kernel sends out gets answers.

With the card attached, the firmware uses more memory during startup: "Free memory" reads 196 MB with the card and 198 without, on the machine that `run.bat` starts. [memory.md](memory.md) has the figures for other processors.

A boot with QEMU recording every packet on that network, from the firmware's start to three seconds after the kernel's prompt, records 37:

- two that the firmware itself sends before the kernel starts. They are of the newer internet protocol (IPv6), and they appear only with the processor that `run.bat` asks for;
- two for the by-hand question and its answer;
- four for the address request;
- two for the stack asking for the name server's hardware address, and two for the name question and its answer;
- two for the stack asking for the gateway's hardware address, which it has to find out for itself;
- 23 for the connection: three to open it, then the greeting, the request, the answer and both goodbyes, with their confirmations. The kernel sent 390 bytes in them and the site about 5,700.

In the kernel's bytes on the connection the site's name can be read once, in the greeting. The request cannot be read anywhere. The option for recording is in [testing.md](testing.md). The recording shows what passes between the card and QEMU's network. The gateway is QEMU itself, which answers the hardware-address questions on its own; the recording cannot show what QEMU passes on to the host's real network.
