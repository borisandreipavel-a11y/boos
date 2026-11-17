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

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::arch::asm;
use core::ffi::c_void;
use core::fmt::Write;
use core::panic::PanicInfo;
use core::sync::atomic::Ordering;

use controller::controller_setup;
use firmware::{SystemTable, print, take_over};
use frames::{FRAME_SIZE, FREE_FRAMES, frames_setup};
use interrupts::load_interrupt_table;
use keyboard::{key_letter, keyboard_setup, next_key};
use network::{gateway_ask, network_start};
use network_card::{network_card_find, network_card_setup};
use page_tables::{GIGABYTE, page_tables_setup};
use processor::stop;
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

    let (map_size, entry_size) = take_over(image, table);

    // No device signals until the kernel is ready for them.
    unsafe { asm!("cli") };

    // From here on the kernel answers for its own failures.
    load_segment_table();
    load_interrupt_table();

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
