# The network: the card, the stack, and fetching a page

Code: `src/pci.rs`, `src/network_card.rs`, `src/network.rs`, `src/page.rs`, and the network stack in `vendor/`. The port and device-memory functions are in `src/processor.rs`; `map_device_memory` is in `src/page_tables.rs`.

So far the kernel finds the network card, sets it up, and sends and receives packets through it. At startup it asks one question by hand: who is the gateway. After that a network stack, smoltcp, takes over in a task of its own and gets the kernel a network address. With that address the kernel fetches one web page, without encryption: it looks up the site's name, connects, asks for the page and prints how it begins.

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

## The gateway question

`gateway_ask(card_address)` in `network.rs` is the kernel's first packet, put together by hand.

- Every machine on a network has a hardware address (6 bytes, its network card's) and a network address (4 bytes, such as `10.0.2.2`). Packets are delivered by hardware address, so before talking to a machine one asks the whole network "who has this network address?" (the address question, ARP).
- The gateway is the machine that passes packets on to the outside: `10.0.2.2` on QEMU's built-in network.
- The question is a packet of 60 bytes, the shortest a network carries: to everybody (`ff:ff:ff:ff:ff:ff`), from the card, kind `0806`, and inside it "1" for question, who asks, and whose address is wanted.
- The kernel has no network address yet. For this question it assumes `10.0.2.15`, the first address QEMU's network hands out (`ASSUMED_OWN_ADDRESS`).
- It then looks at arriving packets until one is an answer (kind `0806`, "2" for answer) from `10.0.2.2`, and returns the hardware address in it. Other packets are passed over.
- It runs at startup with device signals off, so the tick count stands still and cannot time the wait. The wait is bounded by looks instead: 2,000,000 (`LOOKS`), about a second in QEMU. The real answer needed 32 looks on average and 283 at most.
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
- The task uses about 11.5 KB of its 64 KB stack, a page fetch included; it was 8.7 KB before there was one. smoltcp's own objects are small: the interface measured 392 bytes when only the address request was switched on.

## Getting an address

- The stack asks the network for an address by itself (the address request, DHCP). `network_task` adds one "socket" for that, `dhcpv4::Socket`, and after each `poll` asks it for news.
- The exchange is four packets: the kernel asks everybody, a server offers an address, the kernel requests that address, the server confirms.
- On "given an address": the task tells smoltcp to use that address, sets the gateway as the place to send packets for the outside, and prints `Network: this machine was given the address 10.0.2.15 by 10.0.2.2`.
- The first news is always "no address", before anything was asked. Nothing is printed for it. A line is printed only when an address arrives, and one more if an address the kernel had is lost.
- An address is lent for a time. smoltcp renews it by itself, half-way through, and reports nothing as long as the address stays the same.
- If nobody answers, smoltcp keeps asking quietly. Nothing is printed and the kernel carries on.

The monitor shows the card's side of all this: `info virtio` lists the card's path, `info virtio-status <path>` shows the handshake's marks and the features in use, and `info virtio-queue-status <path> <line>` shows a line's length and the addresses of its three areas.

## Fetching a page

`page.rs` fetches one page from the web and prints how it begins. The site is `example.com` (`SITE`), which its owners keep for examples. `network_task` calls `page_fetch` once, the first time the kernel has an address.

The fetch runs inside the network's own task, because only that task may touch the stack. It is written as one run from top to bottom. Wherever it has to wait for the network it calls `stack_turn`: one `Interface::poll`, then a wait of one tick. So the stack keeps working during a fetch and the address is still renewed, but news about the address is read only when the fetch is over.

The steps:

1. **The name.** Machines are reached by network address, but sites are known by name. A name server is a machine that knows which address belongs to which name (the name system, DNS). Together with the address, the network names a name server, and the task keeps the first one named. `name_lookup` adds a `dns::Socket` for that server, asks for the name's address (`start_query`, kind `A`: an address of the 4-byte sort) and waits for the answer. smoltcp is set to keep one address per answer (`DNS_MAX_RESULT_COUNT` in the copy's `config.rs`), so a site with several addresses is tried at one only. The kernel prints `Network: the name example.com belongs to the address ...`.
2. **The connection.** A connection (TCP) is an agreement between two machines to pass bytes back and forth so that none is lost and all arrive in order. smoltcp does that work. `page_ask` adds a `tcp::Socket` with room for 4096 arrived bytes and 512 bytes to send. A port is the number that says which conversation on a machine a packet belongs to. Sites wait for page requests on port 80 (`WEB_PORT`). This side takes a number between 49152 and 65535, picked by `time_stamp()` so that it differs between boots.
3. **The request.** Once the site has agreed to the connection, the kernel sends three lines in the web's language (HTTP): `GET / HTTP/1.0`, then `Host: example.com`, then an empty line that ends the request. Nothing else is sent: no line names the kernel or the machine. With `HTTP/1.0` the site closes the connection when the page is sent, and that is how the kernel knows the page is over.
4. **The answer.** It arrives as one run of bytes in three parts: a first line saying how it went (`200 OK` means "here is the page"), lines of notes about the page, an empty line, then the page. `Answer::take` is given every byte as it arrives. It keeps the first line, counts its way through the notes without keeping them, and keeps the first rows of the page. The rest of the page is only counted.
5. **Goodbye.** If the site finished properly, the kernel closes its side properly too (`close`). Otherwise it drops the connection (`abort`), which tells the site so. It gives the stack up to a second to pass that on and then takes the connection off the stack's list.

What is printed, as one text so that other tasks' lines cannot land inside it:

- `Network: example.com answered "HTTP/1.1 200 OK". Its page begins:`
- up to 8 rows of the page (`ROWS_SHOWN`), each up to 72 signs (`ROW_LENGTH`) and set in by four spaces. A longer line goes on in the next row. Empty rows are left out;
- `Network: the whole page is 577 bytes long.` "Whole" means that the site ended the connection in the regular way. The length that the site states in its notes is not read, so the two are not compared. Otherwise the last line reads `Network: the page is not whole: the connection broke or took too long. N bytes of it came.`

**The page is text from outside.** Somebody else wrote it, and a terminal obeys certain bytes as commands. `plain_sign` therefore lets only plain letters, digits and signs through (bytes 32 to 126). Byte 13, which comes before each line end, is dropped, and every other byte becomes a dot. The first line gets the same treatment and is cut at 72 signs. However long a line of notes is, only its length is counted.

**No wait is endless.** The name lookup may take 5 seconds, agreeing on the connection 5, the answer 10 and the goodbye 1 (`LOOKUP_WAIT` and the three constants below it, counted in ticks). When something fails, one line says so and the kernel carries on: `Network: no page fetched, because ...`

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
| the request could not be sent | the connection would not take the request |
| the site sent nothing | the connection ended, or 10 seconds passed, without a byte |

How it goes in QEMU:

- From the name question to the end takes about 1.1 seconds, and one whole second of that is a pause inside smoltcp. After asking for one machine's hardware address it asks for no other for a second (`SILENT_TIME` in the copy's `iface/neighbor.rs`), and a connection that lacks such an address waits just as long before it tries again (`DISCOVERY_SILENT_TIME` in `iface/socket_meta.rs`). The name server's hardware address is asked for first, so the gateway's has to wait. The by-hand gateway answer from startup is not handed to the stack.
- The page report therefore lands among the demonstration tasks' lines; after the second of them in the runs so far.
- A big page arrives at about 70 KB a second: one packet every two ticks. The card's adapter says "one packet at a time", so the site sends one packet and waits for the kernel to confirm it, and the kernel looks once per tick.
- Twenty fetches in a row left the count of free frames where it was after the first.

Every start of the kernel fetches the page, so every start sends one name question and one request out to the internet. The page is not encrypted: anybody on the way can read it and change it. For test boots that should stay off the internet, see [testing.md](testing.md).

## QEMU's built-in network

`run.bat` attaches the card to QEMU's built-in network (`-netdev user`). QEMU plays a small network of its own and passes traffic on through the host computer:

- the network is `10.0.2.0` and the card's own address is `52:54:00:12:34:56`, as the monitor's `info network` shows;
- the gateway is at `10.0.2.2`, with the hardware address `52:55:0a:00:02:02`; it answered the kernel's question. It also answers the address request, and hands out `10.0.2.15` first;
- a name server is at `10.0.2.3`, and the answer to the address request names it. QEMU passes name questions on to the host computer's own name lookup;
- `10.0.2.2` also stands for the host computer itself: a connection to it reaches a program that listens on the host's own address `127.0.0.1`. Tests of the page fetch use that. Where no program listens, QEMU does not pass the host's refusal on: the kernel's requests to connect simply get no answer;
- with `restrict=on` added to `-netdev user`, nothing gets out, and the answer to the address request names no name server;
- the network can be changed for a test: `-netdev user,id=net0,net=192.168.76.0/24,dhcpstart=192.168.76.9` made the kernel print `192.168.76.9`, given by `192.168.76.2`;
- nothing outside can reach the kernel; only what the kernel sends out gets answers.

With the card attached, the firmware uses a little more memory during startup, and "Free memory" reads 205 MB instead of 206.

A boot with QEMU recording every packet on that network, from the firmware's start to three seconds after the kernel's prompt, records 21:

- two for the by-hand question and its answer;
- four for the address request;
- two for the stack asking for the name server's hardware address, and two for the name question and its answer;
- two for the stack asking for the gateway's hardware address, which it has to find out for itself;
- nine for the connection: three to open it, the request, the site's confirmation, the answer (891 bytes in one packet when it was recorded), the site's goodbye, the kernel's confirmation and goodbye in one, and the site's last confirmation.

The request packet carries exactly the three lines listed under "Fetching a page", 37 bytes. The option for recording is in [testing.md](testing.md). The recording shows what passes between the card and QEMU's network. The gateway is QEMU itself, which answers the hardware-address questions on its own; the recording cannot show what QEMU passes on to the host's real network.
