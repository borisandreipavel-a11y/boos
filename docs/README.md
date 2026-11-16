# Notes for whoever works on this kernel next

This folder holds what the code cannot say for itself: the order things must happen in, facts about the hardware, known limits, and how to check that the kernel still works. It is written for AI agents and people who pick the project up cold.

**Keep it true.** When code changes, change the matching note in the same change. A note that disagrees with the code is worse than no note. Record what was tested and what was not, and never write "tested" for something that was only compiled.

## What this is

A from-scratch kernel for x86-64 PCs, written in Rust. It is a UEFI application: the firmware loads it directly and there is no separate bootloader. It runs in QEMU and has never run on real hardware.

Today it starts, takes the machine over from the firmware, reports processor failures, listens to the timer and the keyboard, manages memory (frames, its own page tables, a heap), runs several tasks that take turns under the timer, and finds and sets up its network card. It can send and receive single packets, and at startup it asks the network one question by hand. It has no network address and no network stack yet.

## Read in this order

1. This file: where things are, and the conventions.
2. [startup.md](startup.md): what the firmware hands over, the takeover, and the order of startup.
3. [interrupts.md](interrupts.md): failures, device signals, the interrupt controller, the timer, the keyboard.
4. [memory.md](memory.md): the memory map, frames, page tables, the heap.
5. [tasks.md](tasks.md): several tasks taking turns, the switch, and the rules for code that runs in tasks.
6. [network.md](network.md): the PCI list, the network card, sending and receiving packets, QEMU's built-in network.
7. [testing.md](testing.md): how to build, run and verify, what has been verified, and the traps.
8. [open-points.md](open-points.md): known limits and what later work must deal with.

## Where things are

Each file in `src/` holds one topic. `main.rs` lists them in the order below.

| File | What it holds | Notes |
| --- | --- | --- |
| `main.rs` | `efi_main` (the order of startup and the main loop) and the panic handler | [startup.md](startup.md) |
| `firmware.rs` | The firmware's tables, `print` through the firmware, `take_over`, the saved memory map | [startup.md](startup.md) |
| `processor.rs` | `port_read`, `port_write` and their 4-byte pair, `device_read_...` and `device_write_...` for controls kept in memory, `signals_off`, `signals_back`, `stop`, `TablePointer` | used everywhere |
| `serial.rs` | `serial_setup`, `serial_print`, `Serial` for `write!` | [startup.md](startup.md) |
| `segments.rs` | The segment table (GDT) and `load_segment_table` | [interrupts.md](interrupts.md) |
| `faults.rs` | The 32 processor failures: `fault_entry!`, `FAULTS`, `report_fault` | [interrupts.md](interrupts.md) |
| `interrupts.rs` | The interrupt table (IDT), `device_entry!`, `ignore_signal`, `load_interrupt_table` | [interrupts.md](interrupts.md) |
| `controller.rs` | The interrupt controller (PIC): `controller_setup`, `signal_done`, the line numbers | [interrupts.md](interrupts.md) |
| `timer.rs` | The timer (PIT): `timer_setup`, `on_timer`, `TICKS` | [interrupts.md](interrupts.md) |
| `keyboard.rs` | The keyboard: `keyboard_setup`, `on_keyboard`, the waiting line, `key_letter` | [interrupts.md](interrupts.md) |
| `frames.rs` | Free memory as a pile of frames: `frames_setup`, `frame_take`, `frame_give_back` | [memory.md](memory.md) |
| `page_tables.rs` | The kernel's page tables: `page_tables_setup`, `map_page`, `map_device_memory` | [memory.md](memory.md) |
| `heap.rs` | The heap: `heap_take`, `heap_give_back`, and `KernelHeap` for Rust's `alloc` | [memory.md](memory.md) |
| `tasks.rs` | Tasks: `timer_entry` (the switch), the list of tasks, `next_task`, `task_add` | [tasks.md](tasks.md) |
| `pci.rs` | The PCI list of cards and devices: `pci_read`, `pci_write`, `pci_find`, `pci_memory_address` | [network.md](network.md) |
| `network_card.rs` | The network card: `network_card_find`, `network_card_setup`, its waiting lines, `network_card_send`, `network_card_receive` | [network.md](network.md) |
| `network.rs` | The first words on the network, by hand: `gateway_ask` | [network.md](network.md) |

Which file uses which:

- `main.rs` uses all of them.
- `firmware.rs` uses `serial.rs`.
- `serial.rs`, `segments.rs`, `controller.rs` use `processor.rs`.
- `faults.rs` uses `processor.rs` and `serial.rs`.
- `keyboard.rs` uses `controller.rs` and `processor.rs`. `timer.rs` uses those two and `tasks.rs`.
- `interrupts.rs` uses `faults.rs`, `controller.rs`, `tasks.rs`, `keyboard.rs`, `segments.rs`, `processor.rs`.
- `frames.rs` uses `firmware.rs`. `page_tables.rs` uses `frames.rs` and `processor.rs`. `heap.rs` uses `frames.rs`, `page_tables.rs` and `processor.rs`.
- `tasks.rs` uses `heap.rs`, `timer.rs`, `segments.rs` and `processor.rs`.
- `pci.rs` uses `processor.rs`. `network_card.rs` uses `pci.rs`, `frames.rs`, `page_tables.rs` and `processor.rs`. `network.rs` uses `network_card.rs`.

Outside `src/`:

- `.cargo/config.toml` sets the build target to `x86_64-unknown-uefi`.
- `run.bat` builds, copies the kernel to `esp\EFI\BOOT\BOOTX64.EFI` (where the firmware looks) and starts QEMU with a virtio network card on QEMU's built-in network.
- Not in the repository: `esp/` and `target/` (build output) and `edk2-x86_64-code.fd` (QEMU's UEFI firmware, copied from QEMU's `share` folder).

## Conventions

The code is written to be readable without a background in kernels: plain words, small files, every unusual step explained. Follow these, so the next change looks like the last one.

**Rust and dependencies**

- Stable Rust, edition 2024 (hence `#[unsafe(no_mangle)]` and `#[unsafe(naked)]`), `#![no_std]`, `#![no_main]`.
- No external crates: `Cargo.toml` has no dependencies. `core` and `alloc` are used; both ship with Rust, so nothing is downloaded. Ask the owner before adding any dependency or tool.
- The `x86_64-unknown-uefi` target has no SSE (it uses soft-float), so code never touches the SSE registers. Several pieces rely on that; see [interrupts.md](interrupts.md).

**Words**

- Names and comments use plain words. A device "signal" is an interrupt. A processor "failure" is an exception. A "frame" is 4096 bytes of real memory. A "pile" is a stack of free things. A table has "lines".
- The hardware's own name appears once, in brackets, where the thing is introduced: segment table (GDT), interrupt table (IDT), interrupt controller (PIC), timer (PIT).
- Comments sit above the thing they explain and say why, not only what. Magic numbers sent to devices get a comment in quotes saying what they tell the device.

**Structure**

- One topic per file. `main.rs` holds only the startup order, the main loop and the panic handler.
- Each file starts with a `//!` header: what the file is for and which note covers it.
- Functions keep their topic in the name (`serial_setup`, `frame_take`) and are imported by name, so a call reads `frame_take()`, not `frames::take()`.
- A macro must be defined above the place that uses it, in the same file. `fault_entry!` lives with `FAULTS`, and `device_entry!` lives with `load_interrupt_table`. Do not split them apart.
- Only what another file needs is `pub`.

**Shared values**

- A value shared between a signal handler and other code is an atomic from `core::sync::atomic`, used with `Ordering::Relaxed`.
- Other global state is a `static mut`, read and written by value inside `unsafe`. Edition 2024 refuses references to a `static mut`; use `&raw` when an address is needed.
- Several tasks run at once, and a switch can happen between any two instructions. State that more than one task changes is changed with device signals off: `let were_on = signals_off(); ... signals_back(were_on);`. See [tasks.md](tasks.md).
- Signal handlers only count or store. They never print.

**Output**

- Everything the kernel says goes through the serial port: `serial_print("...")` or `write!(serial, "...")` with `let mut serial = Serial;`. Lines end in `\r\n`.
- From a task, build the line first and send it in one go, `serial_print(&format!(...))`, so another task's line cannot land in the middle of it.
