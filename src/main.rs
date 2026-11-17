//! The kernel starts here. This file holds the order in which everything is
//! set up, the main loop, and what happens when Rust code gives up. Each topic
//! has its own file, listed below. What the code cannot say is in `docs/`.

#![no_std]
#![no_main]
#![allow(dead_code)]

// The part of Rust's own library with lists and text that grow as needed.
// Like `core`, it comes with Rust. It gets its memory from this kernel's heap.
extern crate alloc;

mod firmware; // What the firmware hands over at startup, and the takeover.
mod processor; // The smallest pieces: ports, stopping the processor.
mod serial; // Printing through the serial port.
mod segments; // The segment table (GDT).
mod faults; // Catching the processor's failures.
mod interrupts; // The interrupt table (IDT) and the stubs for device signals.
mod controller; // The interrupt controller (PIC).
mod timer; // The timer (PIT) and its tick count.
mod keyboard; // The keyboard: key numbers, the waiting line, letters.
mod frames; // Free memory, in frames of 4096 bytes.
mod page_tables; // The kernel's own page tables.
mod heap; // The heap, and Rust's lists and text on top of it.
mod tasks; // Several tasks taking turns, switched by the timer.
mod pci; // The PCI list of the machine's cards and devices.
mod network_card; // The network card.
mod network; // The first words on the network.
mod page; // Fetching one page from the web.
mod random; // Random numbers, made by the processor.
mod clock; // The clock chip: the date and the time.
mod encryption; // Encryption: a check that the outside code for it works here.
mod encryption_values; // The values that check is made against.
mod provider; // The adapter between the TLS library and the arithmetic.
mod tls; // The encrypted link.
mod app_box; // The locked box that apps run in.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::arch::asm;
use core::ffi::c_void;
use core::fmt::Write;
use core::panic::PanicInfo;
use core::sync::atomic::Ordering;

use app_box::{ADDING_APP, GREETING_APP, box_check, box_run};
use clock::clock_read;
use controller::controller_setup;
use encryption::{encryption_check, trusted_roots};
use firmware::{SystemTable, print, screen_find, take_over};
use frames::{FRAME_SIZE, FREE_FRAMES, frames_setup};
use interrupts::load_interrupt_table;
use keyboard::{key_letter, keyboard_setup, next_key};
use network::{gateway_ask, network_start};
use network_card::{network_card_find, network_card_setup};
use page_tables::{GIGABYTE, page_tables_setup};
use processor::{sse_refuse, stop};
use random::{random_number, random_setup};
use segments::load_segment_table;
use serial::{Serial, serial_print, serial_setup};
use tasks::{RESTED_TICKS, task_add, task_rest, task_wait};
use timer::{TICKS, TICKS_PER_SECOND, timer_setup};

// Writes a hardware address the usual way: six pairs of digits with colons.
fn hardware_address(address: [u8; 6]) -> String {
    format!(
        "{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}",
        address[0], address[1], address[2], address[3], address[4], address[5]
    )
}

// Two tasks to show that several can run at once. Each prints a line, waits
// a second and prints the next. While a task waits it uses no processor time:
// the other tasks run, or the processor rests.
fn task_a() {
    count_aloud("Task A", TICKS_PER_SECOND / 2);
}

fn task_b() {
    count_aloud("Task B", TICKS_PER_SECOND);
}

// Prints three lines one second apart, the first after `first_wait` ticks.
fn count_aloud(name: &str, first_wait: u64) {
    task_wait(first_wait);
    for step in 1..=3 {
        // The line is put together first and printed in one go, so that
        // another task's line cannot land in the middle of it.
        serial_print(&format!("{}: {}\r\n", name, step));
        task_wait(TICKS_PER_SECOND);
    }
}

#[unsafe(no_mangle)]
extern "efiapi" fn efi_main(image: *mut c_void, table: *mut SystemTable) -> usize {
    serial_setup();

    print(table, "Hello from my kernel!\r\n");

    // Only the firmware can say where the screen is, so ask before it goes.
    let screen = screen_find(table);

    let (map_size, entry_size) = take_over(image, table);

    // No device signals until the kernel is ready for them.
    unsafe { asm!("cli") };

    // From here on the kernel answers for its own failures.
    load_segment_table();
    load_interrupt_table();

    // This kernel does not use the processor's SSE registers. Have the
    // processor refuse any instruction that does.
    sse_refuse();

    let mut serial = Serial;
    write!(serial, "The firmware has stepped aside. This machine is mine.\r\n").ok();

    // Collect the free memory listed in the map.
    let memory_end = frames_setup(map_size, entry_size);
    let free_frames = unsafe { FREE_FRAMES };
    write!(serial, "Free memory: {} MB\r\n", free_frames * FRAME_SIZE / (1024 * 1024)).ok();

    // Stop relying on the firmware's page tables.
    let covered = page_tables_setup(memory_end);
    write!(serial, "Page tables: the kernel's own, covering {} GB\r\n", covered / GIGABYTE).ok();

    // Try the heap: a text and a list, both growing as they are filled. At
    // the closing brace Rust hands their memory back to the heap by itself.
    {
        let mut greeting = String::from("Hello");
        greeting.push_str(" from the heap!");
        let mut squares = Vec::new();
        for number in 1..=10 {
            squares.push(number * number);
        }
        write!(serial, "Heap: {} {:?}, kept at {:p}\r\n", greeting, squares, greeting.as_ptr()).ok();
    }

    // What the firmware said about the screen. Nothing is drawn on it yet.
    match &screen {
        Ok(screen) => {
            write!(serial, "Screen: found, {} dots wide and {} dots high, its memory starts at {:#x}\r\n", screen.width, screen.height, screen.memory_start).ok();
        }
        Err(reason) => {
            write!(serial, "Screen: {}\r\n", reason).ok();
        }
    }

    // Encryption, when it comes, needs two things from the machine: numbers
    // that nobody can guess, and today's date.
    random_setup();
    match random_number() {
        // The number shown is only a sample. It is used for nothing else.
        Some(number) => {
            write!(serial, "Random numbers: made by the processor, for example {:016x}\r\n", number).ok();
        }
        None => {
            write!(serial, "Random numbers: none, because this processor has no sound source for them\r\n").ok();
        }
    }
    match clock_read() {
        Some(date) => {
            write!(
                serial,
                "Date and time: {:04}-{:02}-{:02} {:02}:{:02}:{:02}, by this machine's clock\r\n",
                date.year, date.month, date.day, date.hour, date.minute, date.second
            )
            .ok();
        }
        None => {
            write!(serial, "Date and time: unknown, because the clock chip gave no usable answer\r\n").ok();
        }
    }

    // Encryption will be done by code that was not written for this kernel.
    // Before relying on it, see that it computes correctly on this machine.
    let (right, all) = encryption_check();
    if right == all {
        write!(serial, "Encryption: {} of {} checks of the arithmetic are right, and {} trusted roots are on board\r\n", right, all, trusted_roots()).ok();
    } else {
        write!(serial, "Encryption: not to be trusted here, only {} of {} checks of the arithmetic are right\r\n", right, all).ok();
    }

    // Apps will run in a locked box, kept by code that was not written for
    // this kernel either. See that it works here: run the smallest app.
    match box_check() {
        Ok(5) => {
            write!(serial, "Box: a program of {} bytes ran inside it and answered 2 + 3 = 5\r\n", ADDING_APP.len()).ok();
        }
        Ok(answer) => {
            write!(serial, "Box: not working, the program inside it answered 2 + 3 = {}\r\n", answer).ok();
        }
        Err(reason) => {
            write!(serial, "Box: not working, because {}\r\n", reason).ok();
        }
    }

    // Now an app that asks the kernel for something: it hands over a text
    // and the kernel prints it, with "App: " in front.
    if let Err(reason) = box_run(&GREETING_APP) {
        write!(serial, "Box: the app was stopped, because {}\r\n", reason).ok();
    }

    // Look for the network card among the machine's cards and devices, and set it up.
    if let Some(card) = network_card_find() {
        write!(serial, "Network card: found, device {} on bus {} of the PCI list\r\n", card.device, card.bus).ok();
        match network_card_setup(card) {
            Ok(address) => {
                write!(serial, "Network card: ready, its address is {}\r\n", hardware_address(address)).ok();

                // The kernel's first packet: ask who the gateway is.
                match gateway_ask(address) {
                    Some(gateway) => {
                        write!(serial, "Network: the gateway 10.0.2.2 answered, its address is {}\r\n", hardware_address(gateway)).ok();
                    }
                    None => {
                        write!(serial, "Network: the gateway 10.0.2.2 did not answer\r\n").ok();
                    }
                }

                // From here on the network stack does the talking, in a task of its own.
                network_start(address);
            }
            Err(reason) => {
                write!(serial, "Network card: not set up, because {}\r\n", reason).ok();
            }
        }
    } else {
        write!(serial, "Network card: none found\r\n").ok();
    }

    // Two more tasks, next to the one that has run so far. They get their
    // first turn once the timer's signals come through.
    task_add(task_a);
    task_add(task_b);

    // Get the devices ready, then let their signals through.
    controller_setup();
    timer_setup();
    keyboard_setup();
    unsafe { asm!("sti") };

    let mut hint_shown = false;
    loop {
        // Let the other tasks run. If none has anything to do, sleep until
        // the next signal from a device.
        task_rest();

        // When the two tasks have had their say, tell how much the processor
        // rested, and ask for some typing.
        let ticks = TICKS.load(Ordering::Relaxed);
        let seconds = ticks / TICKS_PER_SECOND;
        if seconds >= 4 && !hint_shown {
            hint_shown = true;
            write!(serial, "The processor rested through {} of the first {} ticks.\r\n", RESTED_TICKS.load(Ordering::Relaxed), ticks).ok();
            write!(serial, "Click the QEMU window and type. The letters appear here:\r\n").ok();
        }

        // Print the letters of the keys that arrived in the meantime.
        while let Some(key) = next_key() {
            match key_letter(key) {
                Some(b'\n') => serial_print("\r\n"),
                Some(letter) => {
                    write!(serial, "{}", letter as char).ok();
                }
                None => {} // A key without a letter, or a key being let go.
            }
        }
    }
}

// Runs when Rust code gives up, for example on a list index that is out of range.
#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    // No device signals while the kernel reports its own end.
    unsafe { asm!("cli") };
    let mut serial = Serial;
    if let Some(place) = info.location() {
        write!(serial, "Kernel panic: {}:{}: ", place.file(), place.line()).ok();
    }
    write!(serial, "{}\r\n", info.message()).ok();
    stop()
}
