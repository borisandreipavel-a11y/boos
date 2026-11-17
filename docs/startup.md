# Startup: from the firmware to the main loop

Code: `src/main.rs`, `src/firmware.rs`, `src/serial.rs`, `src/processor.rs`.

## The order of startup

`efi_main` in `main.rs` runs these steps. The order matters; the reason for each rule is given.

1. **`serial_setup()`** comes first, so that everything after it can report problems.
2. **`print(table, ...)`** writes "Hello" through the firmware. It works only before the takeover.
3. **`take_over(image, table)`** gets the memory map and tells the firmware to step aside. After it returns, no firmware service may be called again.
4. **`cli`** switches device signals off. The firmware may have left them on, and the kernel has nothing to catch them with yet.
5. **`load_segment_table()`, then `load_interrupt_table()`.** The interrupt table's lines name the kernel's code segment, so the segment table goes first. From here on a processor failure prints a report instead of resetting the machine. Right after, **`sse_refuse()`** tells the processor to refuse SSE instructions. It must not come before step 3, because the firmware uses them. See [encryption.md](encryption.md).
6. **`frames_setup(...)`** collects the free memory. It runs after step 5 on purpose: it writes to every free frame, and if the firmware had protected one, the failure would be reported.
7. **`page_tables_setup(...)`** needs frames for its tables, so it follows step 6.
8. **The heap** needs both frames and `map_page`. It has no setup step; it starts working at the first request. The demonstration in `efi_main` is that first request.
9. **`random_setup()`, then `clock_read()`** ask the processor whether it can make random numbers, and read the date from the clock chip. Both results are printed. They need only the processor and two ports, so they could come earlier; they stand here so that their lines follow the memory lines. See [random-and-date.md](random-and-date.md). **`encryption_check()`** follows: it tries the outside code for encryption once and its result is printed. It needs the heap, takes about half a second, and goes 46 KB deep on the firmware's stack. See [encryption.md](encryption.md). **`box_check()`, then `box_run(&GREETING_APP)`** come next: two small apps are run once each in the locked box. The first is asked for a sum, which is printed; the second asks the kernel to print a text. They need the heap too and go 45 KB deep on the same stack. See [box.md](box.md).
10. **`network_card_find()`, then `network_card_setup(...)`, then `gateway_ask(...)`, then `network_start(...)`** look for the network card on the PCI list, set it up, ask the network who the gateway is, and add the task that runs the network stack; the first three results are printed. The stack's task gets its first turn only after step 13, and prints the address it is given from there. The setup takes frames and maps the card's memory, so it must follow step 7. It runs with signals off, like everything before step 13, which is why the wait for the gateway's answer is counted in looks and not in ticks.
11. **`task_add(...)`** adds the two demonstration tasks. Tasks need the heap for their stacks, so this follows step 8. They get their first turn only after step 13.
12. **`controller_setup()`, `timer_setup()`, `keyboard_setup()`**, in that order. The controller is set up first and the keyboard's waiting byte is emptied last. The other way round, a key arriving in between would send its signal before the controller was listening, and the keyboard would stay silent.
13. **`sti`** lets device signals through. It comes last, after the interrupt table is loaded and every device is ready. From the first tick on, the timer switches between the tasks.
14. **The main loop** is task 0. It prints the rest count and the typing prompt once four seconds have gone by, prints the letters of the keys that arrived, and then calls `task_rest()`: the other tasks run if they have something to do, and otherwise the processor sleeps until the next device signal.

## What the firmware hands over

- The entry point is `extern "efiapi" fn efi_main(image, table) -> usize`. `image` identifies the kernel to the firmware; `table` points to the firmware's table of services.
- The firmware's structures are written by hand with `#[repr(C)]`, naming only what is used and skipping the rest with padding:
  - `SystemTable`: `console_out` at offset 64, `boot_services` at offset 96.
  - `TextOutput`: `output_string` at offset 8.
  - `BootServices`: `get_memory_map` at offset 56, `exit_boot_services` at offset 232.
  - `MemoryEntry`: kind (u32), physical start, virtual start, page count, attribute.
- Adding another firmware service means adding its field at the right offset. Check the offset against the UEFI specification; a wrong one calls a random function.

## The takeover

- `take_over` calls the firmware's GetMemoryMap and then ExitBootServices, in a loop. ExitBootServices refuses if the map changed in between, and then both are called again.
- Nothing may call a firmware service between those two calls, not even `print`.
- The memory map is saved in `MEMORY_MAP`, a `static mut [u64; 4096]` (32 KB), reached through `&raw`. `take_over` returns how many bytes of it are filled and the size of one entry.
- Step through the map by the entry size the firmware reports, not by the size of `MemoryEntry`. The firmware's entries are larger than the struct (48 bytes in QEMU).
- Anything else wanted from the firmware must be fetched before `take_over`. See [open-points.md](open-points.md) for the screen.

State of the processor at handover, as seen in QEMU with its UEFI firmware. The addresses were measured without a network card; with the card `run.bat` now attaches, the kernel and the stack sit a little lower (a fault then reports code near `0xde2c000`), lower again with the processor `run.bat` now asks for (near `0xdad0000`), again since the kernel's file grew with the crates for encryption (near `0xd8a0000`), and once more with the code that runs apps (near `0xd02c000`):

- `cr0 = 0x80010033`: paging on, write protection on.
- `cr4 = 0x668`: 4-level page tables, no global pages.
- `efer = 0xd00`: long mode, no-execute available.
- The firmware's page tables make every address lead to itself. Its top table was at `0xf801000`.
- The stack is the firmware's, in a 128 KB stretch of the map, near `0xfe65600`. The kernel keeps running on it. See [memory.md](memory.md) for what that prevents.
- The kernel itself is loaded near `0xdf06000`, in a stretch of the map of kind 1.

## Printing

- `print(table, text)` uses the firmware's console and is valid only before the takeover. QEMU's firmware copies its console to the serial port, which is why "Hello from my kernel!" also appears in the terminal.
- `serial_print` writes to the first serial port (COM1, port `0x3F8`) using `port_read` and `port_write`. `Serial` implements `core::fmt::Write`, so `write!` works with numbers and formatting.
- `serial_setup` sets the speed and format (115200 bits per second, 8 bits, no check bit, 1 stop bit). QEMU's port works without this; a real PC's port does not.
- `serial_setup` then does a loop-back test: it sends one byte to itself and checks that it comes back. The result is kept in `SERIAL_FOUND`. When no port was found, `serial_print` does nothing, so a machine without a serial port still runs but says nothing.
- `serial_print` waits without limit for the port to be ready for each letter.
- `serial_print` switches device signals off while it sends a text, so that the text stays in one piece when several tasks print; see [tasks.md](tasks.md).
- Tested only in QEMU, with and without a serial port. Never run on real hardware.

## What a normal boot prints

```
Hello from my kernel!
The firmware has stepped aside. This machine is mine.
Free memory: 197 MB
Page tables: the kernel's own, covering 4 GB
Heap: Hello from the heap! [1, 4, 9, 16, 25, 36, 49, 64, 81, 100], kept at 0x400000000020
Random numbers: made by the processor, for example <16 signs, different at every start>
Date and time: 2026-11-17 05:37:53, by this machine's clock
Encryption: 8 of 8 checks of the arithmetic are right, and 112 trusted roots are on board
Box: a program of 41 bytes ran inside it and answered 2 + 3 = 5
App: Hello from inside the box
Network card: found, device 3 on bus 0 of the PCI list
Network card: ready, its address is 52:54:00:12:34:56
Network: the gateway 10.0.2.2 answered, its address is 52:55:0a:00:02:02
Network: this machine was given the address 10.0.2.15 by 10.0.2.2
Network: the name example.com belongs to the address <the site's address>
Task A: 1
Task B: 1
Task A: 2
Network: example.com proved who it is: its certificate leads back to one of the 112 trusted roots. The link is encrypted with ChaCha20-Poly1305.
Network: example.com answered "HTTP/1.1 200 OK". Its page begins:
    <up to 8 rows of the page>
Network: the whole page is 577 bytes long.
Task B: 2
Task A: 3
Task B: 3
The processor rested through 344 of the first 400 ticks.
Click the QEMU window and type. The letters appear here:
```

That is with QEMU's 256 MB, and with the network card and the processor that `run.bat` asks for. The random number is written with 16 signs, the digits and the letters a to f. The date and time are the clock chip's. QEMU sets its chip to world time, so the time shown is not the time on the wall. On a processor that cannot make random numbers the line reads "Random numbers: none, because this processor has no sound source for them", and if the clock chip gives nothing usable, "Date and time: unknown, because the clock chip gave no usable answer". The kernel carries on after either. The encryption line follows about half a second later, the time its checks take. If one of them fails it reads "Encryption: not to be trusted here, only N of 8 checks of the arithmetic are right", and the kernel carries on then too. The box line follows at once, and after it the line of the second app, which the app itself asks the kernel to print; every line an app prints begins with "App: ". If the first program cannot be run or answers wrongly its line reads "Box: not working, ..." with the reason, and if the second app is stopped, "Box: the app was stopped, because ..." takes the place of its line. The kernel carries on either way; [box.md](box.md) has the wording. The address line comes from the network stack's task, within about a tenth of a second of the tasks starting, well before the first task line. Without a card, "Free memory" reads 199 MB and all the network lines become one, "Network card: none found". A card that cannot be set up gives "Network card: not set up, because ..." with the reason, and no gateway line. If nobody answers the question, the gateway line reads "Network: the gateway 10.0.2.2 did not answer", after a wait of about a second. If nobody hands out an address, no address line is printed and no page is fetched. The task lines arrive half a second apart, taking turns. The rest count and the prompt follow a second after the last one; the count reads 336 to 365 in the runs so far, because the arithmetic of the encrypted link keeps the processor busy for about half a second. Without a network card, or when no link is made, it reads 393 to 399.

The lines about the page come from the network stack's task as well. The name line follows the address line within about a tenth of a second. Under two seconds later come the line saying that the site proved who it is, and then the report (the answer line, the page's rows and the length line) in one piece. They land among the task lines: after the third of them in both runs against the real site. The way of scrambling named in the first of them is the site's choice between the two the kernel offers. The address in the name line and the page itself belong to the site and can change; the listing shows what came on 2026-11-17, with the page's rows left out. If the page cannot be fetched, one line says why instead, `Network: no page fetched, because ...`, and it can come as late as after the prompt. [network.md](network.md) and [encryption.md](encryption.md) list the reasons. Keys typed in the QEMU window (not in the terminal) are echoed in the terminal at any time, also while the tasks are still running.

The heap line and the task lines are demonstrations kept from the work that added them. They can go when something better shows that those pieces work. The task lines replaced three `Timer: N s` lines that the main loop used to print; the tasks now show that the timer works, because they pace themselves by its ticks. The rest count shows that a waiting task uses no processor time. Fetching the page at every start is a demonstration too.
