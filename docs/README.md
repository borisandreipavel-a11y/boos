# Notes for whoever works on this kernel next

This folder holds what the code cannot say for itself: the order things must happen in, facts about the hardware, known limits, and how to check that the kernel still works. It is written for AI agents and people who pick the project up cold.

**Keep it true.** When code changes, change the matching note in the same change. A note that disagrees with the code is worse than no note. Record what was tested and what was not, and never write "tested" for something that was only compiled.

## What this is

A from-scratch kernel for x86-64 PCs, written in Rust. It is a UEFI application: the firmware loads it directly and there is no separate bootloader. It runs in QEMU and has never run on real hardware.

Today it starts, takes the machine over from the firmware, reports processor failures, listens to the timer and the keyboard, manages memory (frames, its own page tables, a heap), runs several tasks that take turns under the timer and can wait without using the processor, and finds and sets up its network card. A network stack runs in a task of its own and gets the kernel a network address. It can get random numbers from the processor and read the date from the clock chip. With all of that it fetches one web page at startup over an encrypted link: the site proves who it is with a certificate, which the kernel checks, and the kernel prints how the page begins. It can also run a small program that is not part of it, an app, locked in a box: the app gets a block of memory of its own and can touch nothing else. An app can ask the kernel for two things so far: to print a text, and to show a text on the screen. It knows where the screen's memory is and how large the screen is, because it asks the firmware before the takeover, and it can paint filled rectangles and write text there, with letters whose shapes were drawn by hand for it: at startup it fills the screen with one colour and writes one sentence, and an app's text appears in a box in the middle of the screen. The app only says which text; the kernel decides how the box looks. Along the bottom of the screen is a chat box: what is typed on the keyboard appears there, small letters and with Shift capitals and the second signs of the keys, Backspace takes a sign away, and Enter sends the line, which the kernel answers for now by giving it back. It also finds the controller that the machine's disks are plugged into, sets it up, asks the first disk for its name and size, reads the list that says how the disk is divided into parts, and finds the part that is its own. It writes only inside that part. There it keeps a notebook: things kept under a name, each written as a new entry behind the last, so that nothing already written is ever changed. The first thing kept is the last line that was sent in the chat box, which the kernel says again at its next start. It also keeps a count of its own starts there, which goes up by one at every start.

## Read in this order

1. This file: where things are, and the conventions.
2. [startup.md](startup.md): what the firmware hands over, the screen's details, the takeover, and the order of startup.
3. [interrupts.md](interrupts.md): failures, device signals, the interrupt controller, the timer, the keyboard.
4. [memory.md](memory.md): the memory map, frames, page tables, the heap.
5. [tasks.md](tasks.md): several tasks taking turns, the switch, and the rules for code that runs in tasks.
6. [network.md](network.md): the PCI list, the network card, sending and receiving packets, the network stack, fetching a page, QEMU's built-in network.
7. [random-and-date.md](random-and-date.md): random numbers from the processor, the date from the clock chip.
8. [encryption.md](encryption.md): the outside code for encryption, the settings it needs, the check at startup, the provider and the encrypted link.
9. [box.md](box.md): running an app locked in a box, the outside code for it, and the limits an app is held to.
10. [screen.md](screen.md): the screen's memory, painting rectangles, the rule that keeps drawing inside the screen, letters, and the box that shows an app's text.
11. [chat.md](chat.md): the chat box, where the person at the machine types and reads the answers.
12. [disk.md](disk.md): the disk: which kind and why, finding its controller, setting it up, a command, asking the disk who it is, reading a block, the parts of a disk and the kernel's own part, writing a block and the count of starts, the disk file in QEMU and the script that divides it.
13. [notebook.md](notebook.md): the notebook, where named things are kept on the disk: its layout, opening it, keeping and finding, and who may use it.
14. [testing.md](testing.md): how to build, run and verify, what has been verified, and the traps.
15. [open-points.md](open-points.md): known limits and what later work must deal with.

## Where things are

Each file in `src/` holds one topic. `main.rs` lists them in the order below.

| File | What it holds | Notes |
| --- | --- | --- |
| `main.rs` | `efi_main` (the order of startup and the main loop) and the panic handler | [startup.md](startup.md) |
| `firmware.rs` | The firmware's tables, `print` through the firmware, `screen_find`, which gives a `Screen`, `take_over`, the saved memory map | [startup.md](startup.md) |
| `processor.rs` | `port_read`, `port_write` and their 4-byte pair, `device_read_...` and `device_write_...` for controls kept in memory, `time_stamp`, `processor_ask`, `sse_refuse`, `signals_off`, `signals_back`, `stop`, `TablePointer` | used everywhere |
| `serial.rs` | `serial_setup`, `serial_print`, `Serial` for `write!` | [startup.md](startup.md) |
| `segments.rs` | The segment table (GDT) and `load_segment_table` | [interrupts.md](interrupts.md) |
| `faults.rs` | The 32 processor failures: `fault_entry!`, `FAULTS`, `report_fault` | [interrupts.md](interrupts.md) |
| `interrupts.rs` | The interrupt table (IDT), `device_entry!`, `ignore_signal`, `load_interrupt_table` | [interrupts.md](interrupts.md) |
| `controller.rs` | The interrupt controller (PIC): `controller_setup`, `signal_done`, the line numbers | [interrupts.md](interrupts.md) |
| `timer.rs` | The timer (PIT): `timer_setup`, `on_timer`, `TICKS` | [interrupts.md](interrupts.md) |
| `keyboard.rs` | The keyboard: `keyboard_setup`, `on_keyboard`, the waiting line, `key_letter`, which also follows the Shift keys, `BACKSPACE` | [interrupts.md](interrupts.md) |
| `frames.rs` | Free memory as a pile of frames: `frames_setup`, `frame_take`, `frame_give_back` | [memory.md](memory.md) |
| `page_tables.rs` | The kernel's page tables: `page_tables_setup`, `map_page`, `map_device_memory` | [memory.md](memory.md) |
| `heap.rs` | The heap: `heap_take`, `heap_give_back`, and `KernelHeap` for Rust's `alloc` | [memory.md](memory.md) |
| `tasks.rs` | Tasks: `switch_entry!` (the switch, for the timer and for a task stepping aside), the list of tasks, `task_add`, `task_wait`, `task_rest` | [tasks.md](tasks.md) |
| `pci.rs` | The PCI list of cards and devices: `pci_read`, `pci_write`, `pci_find`, `pci_find_kind`, `pci_memory_address` | [network.md](network.md) |
| `network_card.rs` | The network card: `network_card_find`, `network_card_setup`, its waiting lines, `network_card_send`, `network_card_receive` | [network.md](network.md) |
| `network.rs` | One question by hand (`gateway_ask`), then the network stack: the adapter `Card`, `network_start`, and `network_task`, which also starts the page fetch | [network.md](network.md) |
| `page.rs` | Fetching one page from the web over an encrypted link: `page_fetch`, the name lookup, the connection, `ConnectionWire`, and `Answer`, which reads what the site sends | [network.md](network.md) |
| `random.rs` | Random numbers from the processor: `random_setup`, `random_number`, `random_fill` | [random-and-date.md](random-and-date.md) |
| `clock.rs` | The clock chip: `clock_read`, which gives a `Date`, and `seconds_since_1970` | [random-and-date.md](random-and-date.md) |
| `encryption.rs` | The startup check of the outside encryption code and the list of roots: `encryption_check`, `encryption_sound`, `root_list` | [encryption.md](encryption.md) |
| `encryption_values.rs` | The values that check is made against | [encryption.md](encryption.md) |
| `provider.rs` | The adapter between the TLS library and the crates that do the arithmetic: `provider` | [encryption.md](encryption.md) |
| `tls.rs` | The encrypted link: `Wire`, `secure_ready`, `secure_exchange` | [encryption.md](encryption.md) |
| `app_box.rs` | The locked box that apps run in, and what an app may ask the kernel for: `box_run`, `box_check`, `kernel_print`, `kernel_show`, the limits, and three whole apps written by hand, `ADDING_APP`, `GREETING_APP` and `SHOWING_APP` | [box.md](box.md) |
| `screen.rs` | Drawing on the screen: `Colour`, `screen_setup`, `screen_size`, `screen_rectangle`, `screen_fill`, `screen_text`, and `screen_panel` with `PANEL_STYLE`, the box an app's text is shown in and its look | [screen.md](screen.md) |
| `letters.rs` | The shapes of the letters, digits and signs, drawn by hand as grids of dots: `SHAPES`, `letter_shape` | [screen.md](screen.md) |
| `chat.rs` | The chat box: `chat_setup`, `chat_key`, `chat_recall`, which says the line kept from before the last switch-off, the rows of what was said, the line being typed, and `CHAT_STYLE`, its look | [chat.md](chat.md) |
| `disk.rs` | The disk: `disk_controller_find`, which looks for the controller that disks are plugged into, `disk_setup`, which sets it up and gives a `Disk` with the first disk's name and size, `disk_read`, which reads one block, `disk_write`, which writes one and can be called from `parts.rs` only, and `block_text` | [disk.md](disk.md) |
| `parts.rs` | The parts of the disk: `part_find`, which reads the disk's list of parts and finds the kernel's own, `part_read` and `part_write`, which read and write one block of that part, and `WriteTicket` | [disk.md](disk.md) |
| `starts.rs` | A count of the kernel's starts, kept on the disk: `start_count` | [disk.md](disk.md) |
| `notebook.rs` | The notebook, named things kept on the disk: `notebook_open`, `notebook_keep`, `notebook_find`, `notebook_ready` | [notebook.md](notebook.md) |

Which file uses which:

- `main.rs` uses all of them.
- `firmware.rs` uses `serial.rs`.
- `serial.rs`, `segments.rs`, `controller.rs` use `processor.rs`.
- `faults.rs` uses `processor.rs` and `serial.rs`.
- `keyboard.rs` uses `controller.rs` and `processor.rs`. `timer.rs` uses those two and `tasks.rs`.
- `interrupts.rs` uses `faults.rs`, `controller.rs`, `tasks.rs`, `keyboard.rs`, `segments.rs`, `processor.rs`.
- `frames.rs` uses `firmware.rs`. `page_tables.rs` uses `frames.rs` and `processor.rs`. `heap.rs` uses `frames.rs`, `page_tables.rs` and `processor.rs`.
- `tasks.rs` uses `heap.rs`, `timer.rs`, `segments.rs` and `processor.rs`.
- `pci.rs` uses `processor.rs`. `network_card.rs` uses `pci.rs`, `frames.rs`, `page_tables.rs` and `processor.rs`. `network.rs` uses `network_card.rs`, `page.rs`, `tasks.rs`, `timer.rs`, `serial.rs`, `processor.rs` and the crate smoltcp. `page.rs` uses `network.rs` (for `Card` and `now`), `tls.rs`, `tasks.rs`, `timer.rs`, `serial.rs`, `processor.rs` and smoltcp.
- `random.rs` and `clock.rs` use `processor.rs`.
- `encryption.rs` uses `encryption_values.rs` and the crates for encryption. `provider.rs` uses `random.rs` and those crates. `tls.rs` uses `provider.rs`, `encryption.rs`, `clock.rs`, `random.rs`, `serial.rs`, `page.rs` (for `plain_text`) and rustls.
- `app_box.rs` uses `page.rs` (for `plain_text`), `serial.rs`, `screen.rs` (for `screen_panel`) and the crate wasmi.
- `screen.rs` uses `firmware.rs` (for `Screen`), `page_tables.rs`, `processor.rs` and `letters.rs`. `letters.rs` uses nothing.
- `chat.rs` uses `screen.rs`, `letters.rs` (for the size of a letter), `keyboard.rs` (for `BACKSPACE`), `serial.rs` and `notebook.rs`.
- `disk.rs` uses `pci.rs`, `frames.rs`, `page_tables.rs`, `processor.rs` and `page.rs` (for `plain_text`). `parts.rs` uses `disk.rs`, and `disk.rs` uses `parts.rs` for the ticket that writing asks for. `starts.rs` uses `parts.rs` and `disk.rs`, and so does `notebook.rs`.

Outside `src/`:

- `vendor/` holds copies of seven crates that were not written for this kernel: smoltcp, the network stack, and heapless, which it needs; rustls, which speaks TLS, rustls-webpki, which checks certificates, and num-traits, which the arithmetic of encryption needs; wasmparser, which reads and checks an app's program, and libm, arithmetic for numbers with a point, both needed by wasmi, which runs apps. `vendor/README.md` says where they came from and what was changed. Their text is other people's and does not follow the conventions below.
- `Cargo.toml` names twelve dependencies, smoltcp, ten crates for encryption and wasmi, and points cargo at the copies. `Cargo.lock` lists 78 crates besides the kernel; 68 of them are compiled.

- `.cargo/config.toml` sets the build target to `x86_64-unknown-uefi`, and tells the crates for encryption to use their plain code; see [encryption.md](encryption.md).
- `run.bat` builds, copies the kernel to `esp\EFI\BOOT\BOOTX64.EFI` (where the firmware looks) and starts QEMU with a processor that can make random numbers, a virtio network card on QEMU's built-in network, and a disk controller with one disk, which is the file `disk.img`. It makes that file the first time and has `make-disk.ps1` divide it into parts.
- `make-disk.ps1` divides a new, empty disk file into parts, with one part for the kernel; see [disk.md](disk.md). It is written in PowerShell, which comes with Windows.
- Not in the repository: `esp/` and `target/` (build output), `edk2-x86_64-code.fd` (QEMU's UEFI firmware, copied from QEMU's `share` folder) and `disk.img` (the machine's disk, which holds what was stored on it).

## Conventions

The code is written to be readable without a background in kernels: plain words, small files, every unusual step explained. Follow these, so the next change looks like the last one.

**Rust and dependencies**

- Stable Rust, edition 2024 (hence `#[unsafe(no_mangle)]` and `#[unsafe(naked)]`), `#![no_std]`, `#![no_main]`.
- Three pieces of outside code: smoltcp, the network stack, with the seven crates it needs; rustls, the TLS library, with the crates that do the arithmetic of encryption (52 compiled crates); and wasmi, which runs apps, with the seven crates it needs. Seven crates are kept as copies in `vendor/`; the others are fetched from crates.io the first time the kernel is built. Everything else is written for this kernel. `core` and `alloc` ship with Rust. Ask the owner before adding any dependency or tool.
- No crate may run a build script. The building computer refuses to run programs that were compiled a moment ago (see `vendor/README.md`), so a crate that has one can only come in as a copy with the script taken out. A macro crate, which the compiler loads as a piece of program during the build, has never been tried on such a computer: none is in use, and before taking one in, stop and ask.
- The `x86_64-unknown-uefi` target has no SSE (it uses soft-float), so code never touches the SSE registers. Several pieces rely on that; see [interrupts.md](interrupts.md). The kernel also tells the processor to refuse SSE instructions, so outside code that tried to use them stops with a report; see [encryption.md](encryption.md).

**Words**

- Names and comments use plain words. A device "signal" is an interrupt. A processor "failure" is an exception. A "frame" is 4096 bytes of real memory. A "pile" is a stack of free things. A table has "lines".
- The hardware's own name appears once, in brackets, where the thing is introduced: segment table (GDT), interrupt table (IDT), interrupt controller (PIC), timer (PIT).
- Comments sit above the thing they explain and say why, not only what. Magic numbers sent to devices get a comment in quotes saying what they tell the device.

**Structure**

- One topic per file. `main.rs` holds only the startup order, the main loop and the panic handler.
- Each file starts with a `//!` header: what the file is for and which note covers it.
- Functions keep their topic in the name (`serial_setup`, `frame_take`) and are imported by name, so a call reads `frame_take()`, not `frames::take()`.
- A macro must be defined above the place that uses it, in the same file. `fault_entry!` lives with `FAULTS`, `device_entry!` lives with `load_interrupt_table`, and `switch_entry!` lives in `tasks.rs` with the two entries it produces. Do not split them apart.
- Only what another file needs is `pub`.

**Shared values**

- A value shared between a signal handler and other code is an atomic from `core::sync::atomic`, used with `Ordering::Relaxed`.
- Other global state is a `static mut`, read and written by value inside `unsafe`. Edition 2024 refuses references to a `static mut`; use `&raw` when an address is needed. Two files depart from "by value": the chat box keeps two lists that grow, which cannot be copied in and out, so `chat.rs` has two small functions that hand them out through their addresses, and `notebook.rs` has one for its list of names. The rule that goes with them is written above them and in [chat.md](chat.md).
- Several tasks run at once, and a switch can happen between any two instructions. State that more than one task changes is changed with device signals off: `let were_on = signals_off(); ... signals_back(were_on);`. See [tasks.md](tasks.md).
- Signal handlers only count or store. They never print.

**Output**

- Everything the kernel says goes through the serial port: `serial_print("...")` or `write!(serial, "...")` with `let mut serial = Serial;`. Lines end in `\r\n`. What is said in the chat box is on the screen as well, and is repeated through the serial port as whole lines.
- From a task, build the line first and send it in one go, `serial_print(&format!(...))`, so another task's line cannot land in the middle of it. Lines that must stay together, such as the report about a fetched page, are built as one text and sent in one go too.
- Text that comes from outside the kernel, such as a web page, is never printed as it arrived. Only plain letters, digits and signs pass; see `plain_sign` in `page.rs`.
