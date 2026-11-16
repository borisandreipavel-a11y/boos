# Startup: from the firmware to the main loop

Code: `src/main.rs`, `src/firmware.rs`, `src/serial.rs`, `src/processor.rs`.

## The order of startup

`efi_main` in `main.rs` runs these steps. The order matters; the reason for each rule is given.

1. **`serial_setup()`** comes first, so that everything after it can report problems.
2. **`print(table, ...)`** writes "Hello" through the firmware. It works only before the takeover.
3. **`take_over(image, table)`** gets the memory map and tells the firmware to step aside. After it returns, no firmware service may be called again.
4. **`cli`** switches device signals off. The firmware may have left them on, and the kernel has nothing to catch them with yet.
5. **`load_segment_table()`, then `load_interrupt_table()`.** The interrupt table's lines name the kernel's code segment, so the segment table goes first. From here on a processor failure prints a report instead of resetting the machine.
6. **`frames_setup(...)`** collects the free memory. It runs after step 5 on purpose: it writes to every free frame, and if the firmware had protected one, the failure would be reported.
7. **`page_tables_setup(...)`** needs frames for its tables, so it follows step 6.
8. **The heap** needs both frames and `map_page`. It has no setup step; it starts working at the first request. The demonstration in `efi_main` is that first request.
9. **`network_card_find()`, then `network_card_setup(...)`** look for the network card on the PCI list and set it up; both results are printed. The setup takes frames and maps the card's memory, so it must follow step 7. It runs with signals off, like everything before step 12.
10. **`task_add(...)`** adds the two demonstration tasks. Tasks need the heap for their stacks, so this follows step 8. They get their first turn only after step 12.
11. **`controller_setup()`, `timer_setup()`, `keyboard_setup()`**, in that order. The controller is set up first and the keyboard's waiting byte is emptied last. The other way round, a key arriving in between would send its signal before the controller was listening, and the keyboard would stay silent.
12. **`sti`** lets device signals through. It comes last, after the interrupt table is loaded and every device is ready. From the first tick on, the timer switches between the tasks.
13. **The main loop** is task 0. It sleeps with `hlt`, wakes on every device signal, prints the typing prompt once four seconds have gone by, and prints the letters of the keys that arrived.

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

State of the processor at handover, as seen in QEMU with its UEFI firmware. The addresses were measured without a network card; with the card `run.bat` now attaches, the kernel and the stack sit a little lower (a fault then reports code near `0xde2c000`):

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
Free memory: 205 MB
Page tables: the kernel's own, covering 4 GB
Heap: Hello from the heap! [1, 4, 9, 16, 25, 36, 49, 64, 81, 100], kept at 0x400000000020
Network card: found, device 3 on bus 0 of the PCI list
Network card: ready, its address is 52:54:00:12:34:56
Task A: 1
Task B: 1
Task A: 2
Task B: 2
Task A: 3
Task B: 3
Click the QEMU window and type. The letters appear here:
```

That is with QEMU's 256 MB and the network card `run.bat` attaches. Without a card, "Free memory" reads 206 MB and the two card lines become one, "Network card: none found". A card that cannot be set up gives "Network card: not set up, because ..." with the reason. The task lines arrive half a second apart, taking turns. The prompt follows a second after the last one. Keys typed in the QEMU window (not in the terminal) are echoed in the terminal at any time, also while the tasks are still running.

The heap line and the task lines are demonstrations kept from the work that added them. They can go when something better shows that those pieces work. The task lines replaced three `Timer: N s` lines that the main loop used to print; the tasks now show that the timer works, because they pace themselves by its ticks.
