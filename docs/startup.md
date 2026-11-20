# Startup: from the firmware to the main loop

Code: `src/main.rs`, `src/firmware.rs`, `src/serial.rs`, `src/processor.rs`.

## The order of startup

`efi_main` in `main.rs` runs these steps. The order matters; the reason for each rule is given.

1. **`serial_setup()`** comes first, so that everything after it can report problems.
2. **`print(table, ...)`** writes "Hello" through the firmware. It works only before the takeover. **`screen_find(table)`** follows: it asks the firmware's graphics service where the screen's memory is and how large the screen is. That works only before the takeover too. The answer is kept and printed later, after the heap line. See "The screen" below.
3. **`take_over(image, table)`** gets the memory map and tells the firmware to step aside. After it returns, no firmware service may be called again.
4. **`cli`** switches device signals off. The firmware may have left them on, and the kernel has nothing to catch them with yet.
5. **`load_segment_table()`, then `load_interrupt_table()`.** The interrupt table's lines name the kernel's code segment, so the segment table goes first. From here on a processor failure prints a report instead of resetting the machine. Right after, **`sse_refuse()`** tells the processor to refuse SSE instructions. It must not come before step 3, because the firmware uses them. See [encryption.md](encryption.md). **`screen_setup(...)`, then `lines_begin()`** follow, if step 2 found a screen: from here on the kernel's lines cover the screen as they are printed, and a failure shows there too (see "The kernel's lines" in [screen.md](screen.md)). They come before the memory steps, which are the likeliest to go wrong on a machine the kernel has not met. The screen's memory is reached through the firmware's page tables until step 7.
6. **`frames_setup(...)`** collects the free memory. It runs after step 5 on purpose: it writes to every free frame, and if the firmware had protected one, the failure would be reported.
7. **`page_tables_setup(...)`** needs frames for its tables, so it follows step 6. **`screen_reach()`** follows at once: the kernel's own tables must lead to the screen's memory before the next line is painted.
8. **The heap** needs both frames and `map_page`. It has no setup step; it starts working at the first request. The demonstration in `efi_main` is that first request. **`screen_background()`** and **`chat_setup()`** follow, if step 2 found a screen: they make the usual picture ready, the screen in one colour with one sentence on it and the chat box along the bottom (see [chat.md](chat.md)), but while the kernel's lines cover the screen nothing of it is painted. It is painted when the start is over, in step 14. See [screen.md](screen.md).
9. **`random_setup()`, then `clock_read()`** ask the processor whether it can make random numbers, and read the date from the clock chip. Both results are printed. They need only the processor and two ports, so they could come earlier; they stand here so that their lines follow the memory lines. See [random-and-date.md](random-and-date.md). **`encryption_check()`** follows: it tries the outside code for encryption once and its result is printed. It needs the heap, takes 0.2 to 0.3 seconds, and goes 42 KB deep on the firmware's stack. See [encryption.md](encryption.md). **`box_check()`, then `box_run(&GREETING_APP)`, then `box_run(&SHOWING_APP)`** come next: three small apps are run once each in the locked box. The first is asked for a sum, which is printed; the second asks the kernel to print a text; the third asks the kernel to show a text on the screen, which paints a box in the middle of the screen and prints nothing. They need the heap too and go 16 KB deep on the same stack. The third needs the screen set up, which step 8 did. See [box.md](box.md). **`interpreter_check()`** follows: it sees whether the box would take the interpreter for Lua, a program of 762 KB that the kernel carries, and the answer is printed. It runs nothing of that program, takes 0.2 to 0.3 seconds, and goes 17 KB deep on the same stack. **`script_run(GREETING_SCRIPT)`** then has the interpreter carry out one script written by hand, which prints a line and shows a text in the box on the screen. That takes 0.3 to 0.5 seconds more, with device signals off, and goes 17 KB deep. See [interpreter.md](interpreter.md). **`json_check()`** follows: it sees that the kernel's own code for JSON makes and reads it as another JSON reader does, and the result is printed. It takes one to two hundredths of a second. See [json.md](json.md). **`lock_check()`** comes last of the checks: it sees that locking a secret with a password gives the published values and what another implementation gives, and the result is printed. It takes about a third of a second. See [lock.md](lock.md).
10. **`disk_controller_find()`, then `disk_setup(...)`** look on the PCI list for the controller that the machine's disks are plugged into, set it up, and ask the first disk on it for its name and size; both results are printed. **`part_find(...)`** then reads the list that says how the disk is divided into parts, and where the kernel's own part lies is printed. **`notebook_open()`** then opens the notebook that the kernel keeps things in, in that part, or begins one on a part that holds nothing; **`start_count()`** counts this start in the part's last block, and the number is printed; and **`chat_begin()`** puts the look kept in the notebook in use, if one is kept there (see "The look" in [screen.md](screen.md)), greets the person at the machine by the name kept in the notebook, or asks for one if none is kept, asks for the password if a key is locked there or for the key if the notebook holds no answer about one, asks for a look when nothing about the key is asked and the notebook holds no answer about the look (otherwise the question for a look comes once the questions about the key are answered), and says the line that was kept in the notebook before the machine was switched off, if there is one. What is typed in answer is taken later, in the main loop. If the notebook cannot be opened, the start is not counted and nothing is written to the part; see [notebook.md](notebook.md). The setup takes two frames and maps the controller's memory, so it must follow step 7, and it waits by looking again and again, because signals are still off. Nothing is written outside the kernel's own part; see [disk.md](disk.md). **`network_card_find()`, then `network_card_setup(...)`, then `gateway_ask(...)`, then `network_start(...)`** look for the network card on the PCI list, set it up, ask the network who the gateway is, and add the task that runs the network stack; the first three results are printed. The stack's task gets its first turn only after step 13, and prints the address it is given from there. The setup takes frames and maps the card's memory, so it must follow step 7. It runs with signals off, like everything before step 13, which is why the wait for the gateway's answer is counted in looks and not in ticks.
11. **`task_add(...)`** adds the two demonstration tasks. Tasks need the heap for their stacks, so this follows step 8. They get their first turn only after step 13.
12. **`controller_setup()`, `timer_setup()`, `keyboard_setup()`**, in that order. The controller is set up first and the keyboard's waiting byte is emptied last. The other way round, a key arriving in between would send its signal before the controller was listening, and the keyboard would stay silent. **`lines_tasks_start()`** comes after them: from here on other tasks print too, and the kernel's lines are painted by the main loop.
13. **`sti`** lets device signals through. It comes last, after the interrupt table is loaded and every device is ready. From the first tick on, the timer switches between the tasks.
14. **The main loop** is task 0. It paints the kernel's lines printed meanwhile, while they cover the screen; prints the rest count once four seconds have gone by, ends the start, so that the usual picture takes the lines' place (`lines_start_over`), and prints the typing prompt; hands every key to the kernel's lines (`lines_key`: F1 shows them, and a key brings the usual picture back) and then the keys that have letters to the chat box; picks up the answer to an errand if the network's task has left one and says it in the chat box (see [tasks.md](tasks.md)); and then calls `task_rest()`: the other tasks run if they have something to do, and otherwise the processor sleeps until the next device signal.

## What the firmware hands over

- The entry point is `extern "efiapi" fn efi_main(image, table) -> usize`. `image` identifies the kernel to the firmware; `table` points to the firmware's table of services.
- The firmware's structures are written by hand with `#[repr(C)]`, naming only what is used and skipping the rest with padding:
  - `SystemTable`: `console_out` at offset 64, `boot_services` at offset 96.
  - `TextOutput`: `output_string` at offset 8.
  - `BootServices`: `get_memory_map` at offset 56, `exit_boot_services` at offset 232, `locate_protocol` at offset 320.
  - `MemoryEntry`: kind (u32), physical start, virtual start, page count, attribute.
  - `ServiceName`, `GraphicsService`, `GraphicsMode`, `GraphicsDetails`: the graphics service; see "The screen" below.
- Adding another firmware service means adding its field at the right offset. Check the offset against the UEFI specification; a wrong one calls a random function.

## The takeover

- `take_over` calls the firmware's GetMemoryMap and then ExitBootServices, in a loop. ExitBootServices refuses if the map changed in between, and then both are called again.
- Nothing may call a firmware service between those two calls, not even `print`.
- The memory map is saved in `MEMORY_MAP`, a `static mut [u64; 4096]` (32 KB), reached through `&raw`. `take_over` returns how many bytes of it are filled and the size of one entry.
- Step through the map by the entry size the firmware reports, not by the size of `MemoryEntry`. The firmware's entries are larger than the struct (48 bytes in QEMU).
- Anything else wanted from the firmware must be fetched before `take_over`. The screen's details are fetched that way.

## The screen

A picture on the screen is a grid of dots (pixels). The screen's memory (the framebuffer) holds four bytes for every dot: how much red, green and blue it shows, and one byte that is not used. Writing there changes the picture. This section is about asking the firmware where that memory is; drawing is in [screen.md](screen.md).

- `screen_find` in `firmware.rs` asks the firmware for its graphics service (GOP, the Graphics Output Protocol) with the boot service `locate_protocol`. A service is named by 16 bytes; the graphics service's are `9042a9de-23dc-4a38-96fb-7aded080516a`, written in `GRAPHICS_SERVICE`. The firmware answers 0 and a pointer when it has the service, and a failure code when it has none (`0x800000000000000e`, "not found", in QEMU).
- The service is a list of three functions, which the kernel does not call, and a pointer to the facts (`GraphicsMode`): where the screen's memory starts, how many bytes it is, and a pointer to the details (`GraphicsDetails`): width and height in dots, the form of a dot's colour, and how many dots one row takes up in the memory.
- A row in the memory can be longer than the picture is wide. The dot at column x of row y sits at `memory_start + (y * row_length + x) * 4`. Use `row_length` there, not `width`.
- The form of a dot's colour is a number: 0 means the bytes are red, green, blue, unused; 1 means blue, green, red, unused; 2 means "described by four masks"; 3 means the screen has no memory to write into and can only be drawn on through the firmware's functions. The kernel takes 0 and 1 and refuses the others.
- Everything is copied into a `Screen` before the takeover, because the facts lie in the firmware's memory. `efi_main` keeps the `Screen` and hands it to `screen_setup` once the kernel's page tables are in place.
- The kernel takes the screen as the firmware left it. It does not choose a size, and it asks for the first graphics service only.
- What the kernel refuses, with the reason in its line: no graphics service; no facts or details; a colour form other than 0 or 1; facts that do not fit together (no memory address, an address that cannot be divided by four, a width or height of zero, a row shorter than the picture, or less memory than rows times height times four).
- The layout of the structures and the place of `locate_protocol` were taken from the header files of the firmware QEMU uses (edk2: `UefiSpec.h` and `GraphicsOutput.h`), because the pages of the UEFI specification could not be fetched. The two places the kernel used before, 56 and 232, agree with the same list.

Seen in QEMU 11.1 with its UEFI firmware:

| Display card | Size in dots | Memory starts at | Memory size in bytes |
| --- | --- | --- | --- |
| QEMU's usual one (`-vga std`), also `-vga vmware`, `virtio-vga`, `bochs-display` | 1280 by 800 | `0x80000000` | 4,096,000 |
| `-vga cirrus` | 800 by 600 | `0x80000000` | 1,921,024 |
| `-vga none -device VGA,xres=1024,yres=768` | 1024 by 768 | `0x80000000` | 3,145,728 |
| `-vga none -device ramfb` | 800 by 600 | near `0xe4cf000` | 3,145,728 |
| none (`-vga none`) | no graphics service | | |

- Every one of them writes colours as blue, green, red, and none had a row longer than the picture. The other order and longer rows have not been seen.
- `0x80000000` is the display card's first memory area on the PCI list, as QEMU's `info pci` shows it. It lies inside the 4 GB that the kernel's page tables cover.
- With `ramfb` the screen's memory lies in ordinary memory, in a stretch the firmware set aside. See [open-points.md](open-points.md).
- The firmware's own text, the line "Hello from my kernel!" among it, is on the screen until the kernel fills it with a colour.

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
- `serial_setup` then does a loop-back test: it sends one byte to itself and checks that it comes back. The result is kept in `SERIAL_FOUND`. When no port was found, `serial_print` sends nothing, so a machine without a serial port says what it says on the screen only.
- `serial_print` hands every text to `lines_keep` first, whether or not a port was found, and `print` does the same: the kernel's lines are kept for the screen and shown there (see "The kernel's lines" in [screen.md](screen.md)).
- `serial_print` waits without limit for the port to be ready for each letter.
- `serial_print` switches device signals off while it keeps and sends a text, so that the text stays in one piece when several tasks print; see [tasks.md](tasks.md). While the machine starts, a whole line is also painted on the screen then.
- Tested only in QEMU, with and without a serial port. Never run on real hardware.

## What a normal boot prints

```
Hello from my kernel!
The firmware has stepped aside. This machine is mine.
Free memory: 197 MB
Page tables: the kernel's own, covering 4 GB
Heap: Hello from the heap! [1, 4, 9, 16, 25, 36, 49, 64, 81, 100], kept at 0x400000000020
Screen: found, 1280 dots wide and 800 dots high, its memory starts at 0x80000000
Random numbers: made by the processor, for example <16 signs, different at every start>
Date and time: 2026-11-17 05:37:53, by this machine's clock
Encryption: 8 of 8 checks of the arithmetic are right, and 112 trusted roots are on board
Box: a program of 41 bytes ran inside it and answered 2 + 3 = 5
App: Hello from inside the box
Interpreter: a program of 765037 bytes that understands Lua is on board, and the box accepts it
App: Hello from a Lua script!!!
JSON: 13 of 13 checks of making and reading it are right
Lock: 6 of 6 checks of locking a secret with a password are right
Disk controller: found, device 4 on bus 0 of the PCI list
Disk: ready, "QEMU HARDDISK", 16 MB, in socket 0 of its controller
Disk: my own part is 14 MB, from block 2048 to block 32734
Disk: the notebook holds <so many> entries and has room for <so many> more
Disk: this is start number <one more at every start>
Kernel: last time you said "<the last line sent in the chat box before the switch-off>"
Kernel: welcome back, <the name given at an earlier start>.
Kernel: type your password and press Enter to unlock the key. Enter alone goes on without it.
Network card: found, device 3 on bus 0 of the PCI list
Network card: ready, its address is 52:54:00:12:34:56
Network: the gateway 10.0.2.2 answered, its address is 52:55:0a:00:02:02
Network: this machine was given the address 10.0.2.15 by 10.0.2.2
Network: the name example.com belongs to the address <the site's address>
Task A: 1
Task B: 1
Network: example.com proved who it is: its certificate leads back to one of the 112 trusted roots. The link is encrypted with ChaCha20-Poly1305.
Network: example.com answered "HTTP/1.1 200 OK". Its page begins:
    <up to 8 rows of the page>
Network: the whole page is 577 bytes long.
Task A: 2
Task B: 2
Task A: 3
Task B: 3
The processor rested through 382 of the first 400 ticks.
Click the QEMU window and type in its chat box. What is said there is repeated here:
```

All of this appears in the terminal, and on the screen too: the QEMU window shows the firmware's text for a moment, and from the line about the firmware stepping aside on, the same lines in white on dark blue, one below the other as they are printed, the older half moving off when the screen is full (see "The kernel's lines" in [screen.md](screen.md)). When the start is over, between the rest count and the prompt, the usual picture takes their place: a dark blue screen with the sentence "Hello from my kernel! I draw my own letters now." in white near the top left corner; along the bottom the chat box, a light box with an orange frame, with the kernel's rows from the notebook in it, the same rows as the lines that begin with "Kernel:" in the terminal, or "Kernel: type a line and press Enter." where there is no notebook, and a white row for typing at its bottom; and in the middle a light box with an orange frame, holding the text "Hello from a Lua script!!!" in black, which a script asked to have shown at startup. See [screen.md](screen.md). Those are the colours of the first look. If another look is kept in the notebook, the usual picture shows in it; see "The look" in [screen.md](screen.md). F1 shows the lines again, and any key brings the usual picture back.

That is with QEMU's 256 MB, and with the network card and the processor that `run.bat` asks for. The screen line tells what the firmware said before the takeover; on a machine without a display card it reads "Screen: none found, the firmware has no graphics service", and for a screen the kernel cannot use, "Screen: found but not usable, ..." with the reason. The kernel carries on after either. The random number is written with 16 signs, the digits and the letters a to f. The date and time are the clock chip's. QEMU sets its chip to world time, so the time shown is not the time on the wall. On a processor that cannot make random numbers the line reads "Random numbers: none, because this processor has no sound source for them", and if the clock chip gives nothing usable, "Date and time: unknown, because the clock chip gave no usable answer". The kernel carries on after either. The encryption line follows 0.2 to 0.3 seconds later, the time its checks take. If one of them fails it reads "Encryption: not to be trusted here, only N of 8 checks of the arithmetic are right", and the kernel carries on then too. The box line follows at once, and after it the line of the second app, which the app itself asks the kernel to print; every line an app prints begins with "App: ". If the first program cannot be run or answers wrongly its line reads "Box: not working, ..." with the reason, and if the second app is stopped, "Box: the app was stopped, because ..." takes the place of its line. The third app prints nothing; only if it is stopped does a line appear, "Box: the app that shows a text was stopped, because ...". The kernel carries on in every case; [box.md](box.md) has the wording. The address line comes from the network stack's task, within about a tenth of a second of the tasks starting, well before the first task line. The disk's three lines come after the apps' lines: the controller's place, then the disk's own name, its size and the socket it is plugged into, and then where the kernel's own part of the disk lies. If the disk has no such part the third line reads "Disk: nothing on it is mine, because ..." with the reason, and none of the disk's lines after it follow. The fourth line is the notebook's: how many entries it holds and how much room is left. On a part that held nothing it reads "Disk: a new notebook was begun, with room for 30685 entries", and if the part holds something the kernel does not know, "Disk: nothing is kept on it, because ..." with the reason, and then no count follows. The fifth line is the number of this start, which the kernel keeps on the disk and raises by one each time; if that fails it reads "Disk: this start could not be counted, because ...". The lines that begin with "Kernel:" are rows of the chat box, on the screen too. The first is there only if a line was sent in the chat box before. The second greets the person by the name they gave at an earlier start ("Kernel: welcome back." when the answer then was to stay "You"), and the third asks for the password that unlocks the key locked on the disk. Where no key is locked, the question for the password gives way to the two rows of the question for the key, "Kernel: to ask the model I need your key. I lock it with a password and keep it on the disk." and "Kernel: type the key and press Enter. It shows as stars. Enter alone goes on without a key.", if the notebook holds no answer about the key yet; if it says that no key is wanted, nothing is asked, the greeting ends with "Type a line and press Enter." and comes first, and the row of the last line follows it. Where the notebook holds no answer about the look, the question for a look follows the questions about the key, or the greeting itself when nothing is asked about the key, and the row of the last line then comes first; see "Picking a look" in [chat.md](chat.md). At a start where the notebook holds no name, the greeting's place is taken by two rows that ask for one, "Kernel: hello! I do not know you yet, so I have a few questions before we begin." (or "... so I have one question before we begin." when nothing will be asked about the key or the look) and "Kernel: what should I call you? Type a name and press Enter. Enter alone keeps "You".", after the row of the last line; see [chat.md](chat.md). If the notebook is damaged, so that nothing can be added to it, nothing is asked but the password for a key locked in it: a name kept in it is still greeted, and without one there is only the row of the last line, if any. Without a notebook there are no such lines at all. If the disk cannot be made ready the second line reads "Disk: not ready, because ..." with the reason and there is no third; [disk.md](disk.md) lists the reasons. On a machine without such a controller there is one line, "Disk controller: none found", and "Free memory" reads 198 MB there. Without a network card, "Free memory" reads 200 MB, the disk controller is device 3, and all the network lines become one, "Network card: none found". A card that cannot be set up gives "Network card: not set up, because ..." with the reason, and no gateway line. If nobody answers the question, the gateway line reads "Network: the gateway 10.0.2.2 did not answer", after a wait of about a second. If nobody hands out an address, no address line is printed and no page is fetched. The task lines arrive half a second apart, taking turns. The rest count follows a second after the last one, and the prompt about a quarter of a second after it, the time the usual picture takes to be painted whole (see "The kernel's lines" in [screen.md](screen.md)); the count read 382 in a run against the real site, and 386 in one with the kernel's lines on the screen, and 374 to 395 against a test server, the lower figures with a page of 300,000 bytes. Without a network card, or when no link is made, it reads 396 to 399. (Before the outside crates were built optimized it read 336 to 365 with a link, whose arithmetic then kept the processor busy for about half a second.)

The lines about the page come from the network stack's task as well. The name line follows the address line within about a tenth of a second. Under two seconds later come the line saying that the site proved who it is, and then the report (the answer line, the page's rows and the length line) in one piece. They land among the task lines: after the second of them in the last run against the real site, after the third in the two runs before the outside crates were built optimized. The way of scrambling named in the first of them is the site's choice between the two the kernel offers. The address in the name line and the page itself belong to the site and can change; the listing shows what came on 2026-11-17, with the page's rows left out. If the page cannot be fetched, one line says why instead, `Network: no page fetched, because ...`, and it can come as late as after the prompt. [network.md](network.md) and [encryption.md](encryption.md) list the reasons. Keys typed in the QEMU window (not in the terminal) appear in the chat box at any time, also while the tasks are still running. When Enter is pressed, the typed line and the kernel's answer are added to the terminal as two lines, `You: ...` (with the person's name in place of `You` once one was given) and `Kernel: you said "..."`, and the line is kept on the disk; see [chat.md](chat.md). While the kernel waits for a name, the line sent is the answer instead.

The heap line and the task lines are demonstrations kept from the work that added them. They can go when something better shows that those pieces work. The task lines replaced three `Timer: N s` lines that the main loop used to print; the tasks now show that the timer works, because they pace themselves by its ticks. The rest count shows that a waiting task uses no processor time. Fetching the page at every start is a demonstration too.
