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
mod screen; // Drawing on the screen.
mod letters; // The shapes of the letters, drawn by hand.
mod chat; // The chat box: typing on the screen, and what was said.
mod disk; // The disk: its controller, asking the disk who it is, reading a block.
mod parts; // The parts of the disk, and the one that is this kernel's own.
mod starts; // A count of the kernel's starts, kept on the disk.
mod notebook; // The notebook: named things kept on the disk.
mod interpreter; // The interpreter for apps written as Lua text.
mod secret; // A secret typed by the person at the machine, kept in memory only.
mod errand; // Errands: work the main loop hands to the network's task.
mod json; // JSON: writing a text that way, and finding a text in it.
mod json_values; // The values the check of JSON is made against.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::arch::asm;
use core::ffi::c_void;
use core::fmt::Write;
use core::panic::PanicInfo;
use core::sync::atomic::Ordering;

use app_box::{ADDING_APP, GREETING_APP, SHOWING_APP, box_check, box_run};
use chat::{chat_key, chat_recall, chat_say, chat_setup};
use clock::clock_read;
use controller::controller_setup;
use disk::{BLOCK_SIZE, disk_controller_find, disk_setup};
use encryption::{encryption_check, trusted_roots};
use errand::errand_answer_take;
use firmware::{SystemTable, print, screen_find, take_over};
use frames::{FRAME_SIZE, FREE_FRAMES, frames_setup};
use interpreter::{GREETING_SCRIPT, interpreter_check, script_run};
use json::json_check;
use interrupts::load_interrupt_table;
use keyboard::{key_letter, keyboard_setup, next_key};
use network::{gateway_ask, network_start};
use network_card::{network_card_find, network_card_setup};
use notebook::notebook_open;
use page_tables::{GIGABYTE, page_tables_setup};
use parts::part_find;
use processor::{sse_refuse, stop};
use random::{random_number, random_setup};
use screen::{Colour, screen_fill, screen_setup, screen_text};
use segments::load_segment_table;
use starts::start_count;
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

    // What the firmware said about the screen. If there is one, try it:
    // paint all of it dark blue, write a sentence in white near the top left
    // corner, and put the chat box along the bottom.
    match screen {
        Ok(screen) => {
            write!(serial, "Screen: found, {} dots wide and {} dots high, its memory starts at {:#x}\r\n", screen.width, screen.height, screen.memory_start).ok();
            screen_setup(screen);
            screen_fill(Colour { red: 0, green: 40, blue: 90 });
            // The 2 makes every dot of a letter a block of 2 by 2 dots.
            screen_text(40, 40, "Hello from my kernel! I draw my own letters now.", 2, Colour { red: 255, green: 255, blue: 255 });
            chat_setup();
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

    // And an app that asks for its text to be shown on the screen. The
    // kernel paints a box in the middle of the screen and writes the app's
    // text in it. Nothing is printed for it unless the app is stopped.
    if let Err(reason) = box_run(&SHOWING_APP) {
        write!(serial, "Box: the app that shows a text was stopped, because {}\r\n", reason).ok();
    }

    // Apps will be written as text in the language Lua, and a program that
    // understands Lua, the interpreter, runs them inside the box. It is a
    // far bigger program than the apps above. See that the box takes it,
    // and then have it run a script written by hand, which prints one line
    // and shows the same text in the box on the screen.
    match interpreter_check() {
        Ok(size) => {
            write!(serial, "Interpreter: a program of {} bytes that understands Lua is on board, and the box accepts it\r\n", size).ok();
            if let Err(reason) = script_run(GREETING_SCRIPT) {
                write!(serial, "Interpreter: the script was stopped, because {}\r\n", reason).ok();
            }
        }
        Err(reason) => {
            write!(serial, "Interpreter: not usable, because {}\r\n", reason).ok();
        }
    }

    // Services on the internet speak JSON. The kernel makes and reads it with
    // code of its own; see that this code gives what another JSON reader
    // gives.
    let (right, all) = json_check();
    if right == all {
        write!(serial, "JSON: {} of {} checks of making and reading it are right\r\n", right, all).ok();
    } else {
        write!(serial, "JSON: not to be trusted here, only {} of {} checks of making and reading it are right\r\n", right, all).ok();
    }

    // Look for the controller that the machine's disks are plugged into.
    // Several devices can share one slot of the PCI list; a controller that
    // is not the first in its slot gets its number in the slot named too.
    if let Some(place) = disk_controller_find() {
        if place.function == 0 {
            write!(serial, "Disk controller: found, device {} on bus {} of the PCI list\r\n", place.device, place.bus).ok();
        } else {
            write!(serial, "Disk controller: found, device {} (function {}) on bus {} of the PCI list\r\n", place.device, place.function, place.bus).ok();
        }

        // Set the controller up, ask the first disk on it who it is, and
        // find the kernel's own part of it.
        match disk_setup(place) {
            Ok(disk) => {
                // The size is shown in MB, and in GB for a disk of 10 GB or
                // more. So many blocks make 1 MB; dividing by that cannot
                // overflow, where multiplying the blocks by their size could.
                let megabytes = disk.blocks / (1024 * 1024 / BLOCK_SIZE);
                let (size, unit) = if megabytes >= 10 * 1024 { (megabytes / 1024, "GB") } else { (megabytes, "MB") };
                write!(serial, "Disk: ready, \"{}\", {} {}, in socket {} of its controller\r\n", disk.name, size, unit, disk.socket).ok();

                // A disk is divided into parts, and a list at its start says
                // which part is which. Read that list and find the part that
                // is this kernel's own. Only there will the kernel ever write.
                match part_find(disk.blocks) {
                    Ok(part) => {
                        write!(serial, "Disk: my own part is {} MB, from block {} to block {}\r\n", part.blocks / (1024 * 1024 / BLOCK_SIZE), part.first, part.last).ok();

                        // Open the notebook that the kernel keeps things in,
                        // in that part. If the part holds something else,
                        // the kernel writes nothing to it at all.
                        match notebook_open() {
                            Ok(notebook) => {
                                let entries = if notebook.entries == 1 { "entry" } else { "entries" };
                                if notebook.damaged {
                                    write!(serial, "Disk: the notebook holds {} {} and is damaged behind that; nothing is added to it\r\n", notebook.entries, entries).ok();
                                } else if notebook.new {
                                    write!(serial, "Disk: a new notebook was begun, with room for {} entries\r\n", notebook.room).ok();
                                } else {
                                    write!(serial, "Disk: the notebook holds {} {} and has room for {} more\r\n", notebook.entries, entries, notebook.room).ok();
                                }

                                // Count this start, in the last block of the
                                // part.
                                match start_count() {
                                    Ok((number, false)) => {
                                        write!(serial, "Disk: this is start number {}\r\n", number).ok();
                                    }
                                    Ok((number, true)) => {
                                        write!(serial, "Disk: the count of starts could not be read and begins again; this is start number {}\r\n", number).ok();
                                    }
                                    Err(reason) => {
                                        write!(serial, "Disk: this start could not be counted, because {}\r\n", reason).ok();
                                    }
                                }

                                // If a line was kept in the notebook before
                                // the machine was switched off, say it.
                                chat_recall();
                            }
                            Err(reason) => {
                                write!(serial, "Disk: nothing is kept on it, because {}\r\n", reason).ok();
                            }
                        }
                    }
                    Err(reason) => {
                        write!(serial, "Disk: nothing on it is mine, because {}\r\n", reason).ok();
                    }
                }
            }
            Err(reason) => {
                write!(serial, "Disk: not ready, because {}\r\n", reason).ok();
            }
        }
    } else {
        write!(serial, "Disk controller: none found\r\n").ok();
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
            write!(serial, "Click the QEMU window and type in its chat box. What is said there is repeated here:\r\n").ok();
        }

        // Hand the keys that arrived in the meantime to the chat box. A key
        // without a letter, or a key being let go, gives nothing.
        while let Some(key) = next_key() {
            if let Some(letter) = key_letter(key) {
                chat_key(letter);
            }
        }

        // If the network's task has left the answer to an errand, say it in
        // the chat box.
        if let Some(answer) = errand_answer_take() {
            chat_say(&answer);
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
