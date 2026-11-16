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
use page_tables::{GIGABYTE, page_tables_setup};
use processor::stop;
use segments::load_segment_table;
use serial::{Serial, serial_print, serial_setup};
use timer::{TICKS, TICKS_PER_SECOND, timer_setup};

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

    // Get the devices ready, then let their signals through.
    controller_setup();
    timer_setup();
    keyboard_setup();
    unsafe { asm!("sti") };

    let mut seconds_shown = 0;
    loop {
        // Sleep until the next signal from a device.
        unsafe { asm!("hlt") };

        // Show the first three seconds going by, as proof that the timer works.
        let seconds = TICKS.load(Ordering::Relaxed) / TICKS_PER_SECOND;
        if seconds > seconds_shown && seconds <= 3 {
            seconds_shown = seconds;
            write!(serial, "Timer: {} s\r\n", seconds).ok();
            if seconds == 3 {
                write!(serial, "Click the QEMU window and type. The letters appear here:\r\n").ok();
            }
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
