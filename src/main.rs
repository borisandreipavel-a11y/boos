#![no_std]
#![no_main]
#![allow(dead_code)]

// The part of Rust's own library with lists and text that grow as needed.
// Like `core`, it comes with Rust. It gets its memory from this kernel's heap.
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use core::alloc::{GlobalAlloc, Layout};
use core::arch::{asm, naked_asm};
use core::ffi::c_void;
use core::fmt::{self, Write};
use core::panic::PanicInfo;
use core::sync::atomic::{AtomicU8, AtomicU64, AtomicUsize, Ordering};

// ---------- What the firmware hands over at startup ----------

// The firmware service that writes text to the screen.
#[repr(C)]
struct TextOutput {
    reset: usize,
    output_string: extern "efiapi" fn(this: *mut TextOutput, text: *const u16) -> usize,
}

// The firmware services that only exist until the kernel takes over.
// Only the two this kernel needs are named; the rest are skipped.
#[repr(C)]
struct BootServices {
    header: [u8; 24],
    skipped_1: [usize; 4],
    get_memory_map: extern "efiapi" fn(
        map_size: *mut usize,
        map: *mut u8,
        map_key: *mut usize,
        entry_size: *mut usize,
        entry_version: *mut u32,
    ) -> usize,
    skipped_2: [usize; 21],
    exit_boot_services: extern "efiapi" fn(image: *mut c_void, map_key: usize) -> usize,
}

// The table of services the firmware hands your kernel at startup.
#[repr(C)]
struct SystemTable {
    header: [u8; 24],
    firmware_vendor: *const u16,
    firmware_revision: u32,
    console_in_handle: *mut c_void,
    console_in: *mut c_void,
    console_out_handle: *mut c_void,
    console_out: *mut TextOutput,
    standard_error_handle: *mut c_void,
    standard_error: *mut c_void,
    runtime_services: *mut c_void,
    boot_services: *mut BootServices,
}

// One line of the memory map: a stretch of memory and what it is used for.
#[repr(C)]
struct MemoryEntry {
    kind: u32,
    physical_start: u64,
    virtual_start: u64,
    page_count: u64,
    attribute: u64,
}

// Space for the memory map (32 KB).
static mut MEMORY_MAP: [u64; 4096] = [0; 4096];

// ---------- Printing through the firmware (only before the takeover) ----------

fn print(table: *mut SystemTable, text: &str) {
    let out = unsafe { (*table).console_out };
    for unit in text.encode_utf16() {
        let letter = [unit, 0];
        unsafe { ((*out).output_string)(out, letter.as_ptr()) };
    }
}

// ---------- Printing through the serial port (works before and after the takeover) ----------

// The PC's first serial port answers at this port number.
const COM1: u16 = 0x3F8;

// Whether a working serial port was found at startup.
static mut SERIAL_FOUND: bool = false;

fn port_write(port: u16, value: u8) {
    unsafe { asm!("out dx, al", in("dx") port, in("al") value) };
}

fn port_read(port: u16) -> u8 {
    let value: u8;
    unsafe { asm!("in al, dx", in("dx") port, out("al") value) };
    value
}

// Sets the serial port's speed and letter format, then checks it is really there.
// QEMU's port works without this. A real PC's port does not.
fn serial_setup() {
    port_write(COM1 + 1, 0x00); // The port must not send signals of its own.
    port_write(COM1 + 3, 0x80); // Unlock the speed setting.
    port_write(COM1, 0x01); // Speed: 115200 bits per second (low half of the setting),
    port_write(COM1 + 1, 0x00); // (high half).
    port_write(COM1 + 3, 0x03); // Lock it again. A letter is 8 bits, 1 stop bit, no check bit.
    port_write(COM1 + 2, 0xC7); // Switch on the port's small queues and empty them.

    // Test: in loop-back mode, a byte sent out comes straight back in.
    port_write(COM1 + 4, 0x10);
    port_write(COM1, 0xA5);
    let mut tries = 0;
    while port_read(COM1 + 5) & 0x01 == 0 && tries < 100_000 {
        tries += 1;
    }
    let found = port_read(COM1) == 0xA5;

    // Back to normal mode, telling the other side that this one is ready.
    port_write(COM1 + 4, 0x03);
    unsafe { SERIAL_FOUND = found };
}

fn serial_print(text: &str) {
    // Without a serial port there is nowhere to print to.
    if !unsafe { SERIAL_FOUND } {
        return;
    }
    for byte in text.bytes() {
        // Wait until the serial port is ready for the next letter.
        while port_read(COM1 + 5) & 0x20 == 0 {}
        port_write(COM1, byte);
    }
}

// Lets `write!` print text and numbers through the serial port.
struct Serial;

impl Write for Serial {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        serial_print(text);
        Ok(())
    }
}

// ---------- Taking over the machine ----------

// Asks the firmware for the memory map, then tells it to step aside.
// Returns how many bytes of the map are filled and the size of one entry.
fn take_over(image: *mut c_void, table: *mut SystemTable) -> (usize, usize) {
    let boot = unsafe { (*table).boot_services };
    let map = (&raw mut MEMORY_MAP) as *mut u8;
    loop {
        let mut map_size: usize = 4096 * 8;
        let mut map_key: usize = 0;
        let mut entry_size: usize = 0;
        let mut entry_version: u32 = 0;
        let status = unsafe {
            ((*boot).get_memory_map)(
                &mut map_size,
                map,
                &mut map_key,
                &mut entry_size,
                &mut entry_version,
            )
        };
        if status != 0 {
            serial_print("Could not get the memory map.\r\n");
            loop {}
        }
        let status = unsafe { ((*boot).exit_boot_services)(image, map_key) };
        if status == 0 {
            return (map_size, entry_size);
        }
        // The map changed in between, so ask again.
    }
}

// ---------- Catching the processor's failures ----------

// The segment table (GDT) tells the processor what kind of code and data the
// kernel uses. The firmware's copy lives in memory the kernel does not own, so
// the kernel brings its own: an empty entry, one for code and one for data.
static SEGMENT_TABLE: [u64; 3] = [0, 0x00AF_9B00_0000_FFFF, 0x00CF_9300_0000_FFFF];
const CODE_SEGMENT: u16 = 8; // The second entry (each entry is 8 bytes).
const DATA_SEGMENT: u16 = 16; // The third entry.

// How the processor is told where a table is: its last byte and its address.
#[repr(C, packed)]
struct TablePointer {
    last_byte: u16,
    address: u64,
}

// One line of the interrupt table (IDT): which code to jump to for one event.
// The address is stored in three pieces.
#[derive(Clone, Copy)]
#[repr(C)]
struct InterruptEntry {
    address_low: u16,
    code_segment: u16,
    spare_stack: u8,
    kind: u8,
    address_middle: u16,
    address_high: u32,
    unused: u32,
}

// The interrupt table: one line for each of the 256 events the processor knows.
// A line left empty means "nothing to call".
static mut INTERRUPT_TABLE: [InterruptEntry; 256] = [InterruptEntry {
    address_low: 0,
    code_segment: 0,
    spare_stack: 0,
    kind: 0,
    address_middle: 0,
    address_high: 0,
    unused: 0,
}; 256];

// What the processor writes down on the stack when something fails.
#[repr(C)]
struct FaultNotes {
    detail_code: u64,
    address: u64,
    code_segment: u64,
    flags: u64,
    stack: u64,
    stack_segment: u64,
}

// Stops the processor for good.
fn stop() -> ! {
    loop {
        unsafe { asm!("cli", "hlt") };
    }
}

// Every failure ends up here: print its name and where it happened, then stop.
extern "sysv64" fn report_fault(number: u64, notes: &FaultNotes) -> ! {
    let mut serial = Serial;
    let name = FAULTS[number as usize].0;
    write!(serial, "CPU fault: {} at {:#x}", name, notes.address).ok();
    if number == 14 {
        // For a page fault the processor keeps the address that was touched.
        let touched: u64;
        unsafe { asm!("mov {}, cr2", out(reg) touched) };
        write!(serial, ", touching {:#x}", touched).ok();
    }
    if notes.detail_code != 0 {
        write!(serial, ", detail code {:#x}", notes.detail_code).ok();
    }
    write!(serial, "\r\n").ok();
    stop()
}

// Writes the few machine instructions the processor jumps to for one failure.
// They note which failure it was and where the processor's notes are, then
// hand over to `report_fault`.
macro_rules! fault_entry {
    // Most failures come without a detail code, so a zero is put in its place.
    ($number:literal) => {
        fault_entry!($number, "push 0")
    };
    // A few failures get a detail code from the processor itself.
    ($number:literal, has_code) => {
        fault_entry!($number, "")
    };
    ($number:literal, $first_step:literal) => {{
        #[unsafe(naked)]
        extern "sysv64" fn entry() {
            naked_asm!(
                $first_step,
                "mov edi, {number}",
                "mov rsi, rsp",
                "call {report}",
                number = const $number,
                report = sym report_fault,
            )
        }
        entry
    }};
}

// The name of each failure and the code to jump to for it, in the processor's
// own numbering (0 to 31).
static FAULTS: [(&str, extern "sysv64" fn()); 32] = [
    ("divide by zero", fault_entry!(0)),
    ("debug", fault_entry!(1)),
    ("non-maskable interrupt", fault_entry!(2)),
    ("breakpoint", fault_entry!(3)),
    ("overflow", fault_entry!(4)),
    ("bound range exceeded", fault_entry!(5)),
    ("invalid instruction", fault_entry!(6)),
    ("device not available", fault_entry!(7)),
    ("double fault", fault_entry!(8, has_code)),
    ("reserved", fault_entry!(9)),
    ("invalid task state", fault_entry!(10, has_code)),
    ("segment not present", fault_entry!(11, has_code)),
    ("stack segment fault", fault_entry!(12, has_code)),
    ("general protection fault", fault_entry!(13, has_code)),
    ("page fault", fault_entry!(14, has_code)),
    ("reserved", fault_entry!(15)),
    ("floating point fault", fault_entry!(16)),
    ("alignment check", fault_entry!(17, has_code)),
    ("machine check", fault_entry!(18)),
    ("SIMD floating point fault", fault_entry!(19)),
    ("virtualization fault", fault_entry!(20)),
    ("control protection fault", fault_entry!(21, has_code)),
    ("reserved", fault_entry!(22)),
    ("reserved", fault_entry!(23)),
    ("reserved", fault_entry!(24)),
    ("reserved", fault_entry!(25)),
    ("reserved", fault_entry!(26)),
    ("reserved", fault_entry!(27)),
    ("hypervisor injection", fault_entry!(28)),
    ("VMM communication fault", fault_entry!(29, has_code)),
    ("security fault", fault_entry!(30, has_code)),
    ("reserved", fault_entry!(31)),
];

// Hands the processor the kernel's segment table and switches over to it.
fn load_segment_table() {
    let pointer = TablePointer {
        last_byte: (size_of_val(&SEGMENT_TABLE) - 1) as u16,
        address: (&raw const SEGMENT_TABLE) as u64,
    };
    unsafe {
        asm!(
            "lgdt [{pointer}]",
            // The code segment can only change during a jump, so "return" to
            // the next line through the new one.
            "push {code}",
            "lea {next}, [rip + 2f]",
            "push {next}",
            "retfq",
            "2:",
            // The data segments can simply be set.
            "mov ds, {data:x}",
            "mov es, {data:x}",
            "mov fs, {data:x}",
            "mov gs, {data:x}",
            "mov ss, {data:x}",
            pointer = in(reg) &pointer,
            code = in(reg) CODE_SEGMENT as u64,
            data = in(reg) DATA_SEGMENT,
            next = out(reg) _,
        );
    }
}

// ---------- Listening to devices ----------

// A device that wants attention sends a signal (an "interrupt"). The signals
// first reach the interrupt controller (PIC): a pair of chips with 8 input
// lines each, 16 lines in all. It passes the signals on to the processor one
// at a time. The timer is wired to line 0 and the keyboard to line 1.
const CONTROLLER_1_COMMAND: u16 = 0x20;
const CONTROLLER_1_SETTING: u16 = 0x21;
const CONTROLLER_2_COMMAND: u16 = 0xA0;
const CONTROLLER_2_SETTING: u16 = 0xA1;

// The 16 device lines use lines 32 to 47 of the interrupt table, right after
// the 32 failures.
const FIRST_DEVICE_ENTRY: usize = 32;
const TIMER_LINE: usize = 0;
const KEYBOARD_LINE: usize = 1;

// Sets up the interrupt controller from scratch, so that nothing depends on
// how the firmware left it.
fn controller_setup() {
    // "Start over. Three settings follow."
    port_write(CONTROLLER_1_COMMAND, 0x11);
    port_write(CONTROLLER_2_COMMAND, 0x11);
    // Setting 1: the line of the interrupt table that each chip's first line uses.
    port_write(CONTROLLER_1_SETTING, FIRST_DEVICE_ENTRY as u8);
    port_write(CONTROLLER_2_SETTING, FIRST_DEVICE_ENTRY as u8 + 8);
    // Setting 2: how the chips are wired. The second chip hangs off line 2 of the first.
    port_write(CONTROLLER_1_SETTING, 0x04);
    port_write(CONTROLLER_2_SETTING, 0x02);
    // Setting 3: work the way a PC expects.
    port_write(CONTROLLER_1_SETTING, 0x01);
    port_write(CONTROLLER_2_SETTING, 0x01);

    // Which lines to hold back: one bit per line, and a 1 means "hold back".
    // Only the timer (line 0) and the keyboard (line 1) are let through.
    port_write(CONTROLLER_1_SETTING, 0b1111_1100);
    port_write(CONTROLLER_2_SETTING, 0b1111_1111);
}

// Tells the interrupt controller that a signal has been dealt with. Until it
// hears this, it holds back the next one.
fn signal_done() {
    port_write(CONTROLLER_1_COMMAND, 0x20);
}

// Writes the machine instructions the processor jumps to for one device
// signal. A failure stops the kernel, but a signal only interrupts it: the
// code that was running must carry on afterwards as if nothing had happened.
// So these instructions save the registers that Rust code is free to change,
// call the handler, put the registers back and return.
macro_rules! device_entry {
    ($handler:ident) => {{
        #[unsafe(naked)]
        extern "sysv64" fn entry() {
            naked_asm!(
                "push rax",
                "push rcx",
                "push rdx",
                "push rsi",
                "push rdi",
                "push r8",
                "push r9",
                "push r10",
                "push r11",
                "cld", // Rust code expects text to be copied front to back.
                "call {handler}",
                "pop r11",
                "pop r10",
                "pop r9",
                "pop r8",
                "pop rdi",
                "pop rsi",
                "pop rdx",
                "pop rcx",
                "pop rax",
                "iretq", // Return to the interrupted code.
                handler = sym $handler,
            )
        }
        entry
    }};
}

// For the device lines nobody listens to: go straight back.
#[unsafe(naked)]
extern "sysv64" fn ignore_signal() {
    naked_asm!("iretq")
}

// ----- The timer -----

// The timer chip (PIT) counts down from a number of your choice, 1,193,182
// steps per second, and sends a signal each time it reaches zero. Counting
// down from 11,931 gives 100 signals ("ticks") per second.
const TIMER_STEPS_PER_SECOND: u64 = 1_193_182;
const TICKS_PER_SECOND: u64 = 100;

// How many ticks have arrived since the kernel started. It is an "atomic"
// number: one that both the main code and a signal handler may use, because
// every read or change of it happens in a single step that cannot be
// interrupted halfway.
static TICKS: AtomicU64 = AtomicU64::new(0);

fn timer_setup() {
    let count = (TIMER_STEPS_PER_SECOND / TICKS_PER_SECOND) as u16;
    port_write(0x43, 0x36); // "Counter 0, start again after each zero. The count follows."
    port_write(0x40, count as u8); // The count's low half,
    port_write(0x40, (count >> 8) as u8); // and its high half.
}

// Runs on every tick.
extern "sysv64" fn on_timer() {
    TICKS.fetch_add(1, Ordering::Relaxed);
    signal_done();
}

// ----- The keyboard -----

// The keyboard controller hands over key numbers at one port, and reports its
// state and takes commands at another.
const KEYBOARD_DATA: u16 = 0x60;
const KEYBOARD_COMMAND: u16 = 0x64;

// A waiting line for keys. The handler only puts the key's number here, and
// the main loop picks it up later. That keeps the handler short, so other
// signals are not held back for long.
static KEY_QUEUE: [AtomicU8; 16] = [const { AtomicU8::new(0) }; 16];
static KEYS_ARRIVED: AtomicUsize = AtomicUsize::new(0); // How many were ever put in.
static KEYS_TAKEN: AtomicUsize = AtomicUsize::new(0); // How many were ever picked up.

fn keyboard_setup() {
    // When nothing answers at a port, every bit reads as 1. No real keyboard
    // controller reports that, so it means there is none.
    if port_read(KEYBOARD_COMMAND) == 0xFF {
        return;
    }

    // Wait until the controller is ready to listen, then give it new settings.
    let mut tries = 0;
    while port_read(KEYBOARD_COMMAND) & 0x02 != 0 && tries < 100_000 {
        tries += 1;
    }
    port_write(KEYBOARD_COMMAND, 0x60); // "New settings follow."
    tries = 0;
    while port_read(KEYBOARD_COMMAND) & 0x02 != 0 && tries < 100_000 {
        tries += 1;
    }
    // Keyboard on, a signal for each key, the classic key numbers, mouse off.
    port_write(KEYBOARD_DATA, 0x65);

    // Throw away any key that arrived before the kernel was listening. The
    // controller sends no new signal while an old key is still waiting.
    tries = 0;
    while port_read(KEYBOARD_COMMAND) & 0x01 != 0 && tries < 100_000 {
        port_read(KEYBOARD_DATA);
        tries += 1;
    }
}

// Runs each time a key is pressed or let go.
extern "sysv64" fn on_keyboard() {
    // Check that a key number is really waiting, then take it. Taking it also
    // lets the controller send the next one.
    if port_read(KEYBOARD_COMMAND) & 0x01 != 0 {
        let key = port_read(KEYBOARD_DATA);
        let arrived = KEYS_ARRIVED.load(Ordering::Relaxed);
        let taken = KEYS_TAKEN.load(Ordering::Relaxed);
        // If the waiting line is full, the key is dropped.
        if arrived - taken < KEY_QUEUE.len() {
            KEY_QUEUE[arrived % KEY_QUEUE.len()].store(key, Ordering::Relaxed);
            KEYS_ARRIVED.store(arrived + 1, Ordering::Relaxed);
        }
    }
    signal_done();
}

// Picks up the key that has waited longest, if any.
fn next_key() -> Option<u8> {
    let taken = KEYS_TAKEN.load(Ordering::Relaxed);
    if taken == KEYS_ARRIVED.load(Ordering::Relaxed) {
        return None;
    }
    let key = KEY_QUEUE[taken % KEY_QUEUE.len()].load(Ordering::Relaxed);
    KEYS_TAKEN.store(taken + 1, Ordering::Relaxed);
    Some(key)
}

// Turns a key number into its letter on a US keyboard. A key number says where
// the key sits, not what is printed on it: the keys are numbered row by row.
// Letting a key go sends its number plus 128, which has no letter here.
fn key_letter(key: u8) -> Option<u8> {
    let (first_key, row): (u8, &[u8]) = match key {
        2..=13 => (2, b"1234567890-="),
        16..=27 => (16, b"qwertyuiop[]"),
        28 => return Some(b'\n'), // Enter.
        30..=41 => (30, b"asdfghjkl;'`"),
        43..=53 => (43, b"\\zxcvbnm,./"),
        57 => return Some(b' '), // The space bar.
        _ => return None,
    };
    Some(row[(key - first_key) as usize])
}

// ---------- Filling in the interrupt table ----------

// Fills in one line of the interrupt table: the code to jump to for one event.
fn set_interrupt_entry(number: usize, code: extern "sysv64" fn()) {
    let address = code as usize as u64;
    let entry = InterruptEntry {
        address_low: address as u16,
        code_segment: CODE_SEGMENT,
        spare_stack: 0,
        kind: 0x8E, // "In use, kernel only, no other signals while it runs."
        address_middle: (address >> 16) as u16,
        address_high: (address >> 32) as u32,
        unused: 0,
    };
    unsafe { (*(&raw mut INTERRUPT_TABLE))[number] = entry };
}

// Fills in the interrupt table's lines for the 32 failures and the 16 device
// lines, then hands the table to the processor.
fn load_interrupt_table() {
    for (number, fault) in FAULTS.iter().enumerate() {
        set_interrupt_entry(number, fault.1);
    }

    // Only the timer and the keyboard are listened to. A signal on any other
    // device line is ignored, instead of counting as a failure.
    for line in 0..16 {
        set_interrupt_entry(FIRST_DEVICE_ENTRY + line, ignore_signal);
    }
    set_interrupt_entry(FIRST_DEVICE_ENTRY + TIMER_LINE, device_entry!(on_timer));
    set_interrupt_entry(FIRST_DEVICE_ENTRY + KEYBOARD_LINE, device_entry!(on_keyboard));

    let pointer = TablePointer {
        last_byte: (size_of::<[InterruptEntry; 256]>() - 1) as u16,
        address: (&raw const INTERRUPT_TABLE) as u64,
    };
    unsafe { asm!("lidt [{}]", in(reg) &pointer) };
}

// ---------- Managing memory ----------

// Memory is handed out in "frames": pieces of 4096 bytes. The processor's
// page tables work in pieces of that size too.
const FRAME_SIZE: u64 = 4096;

// ----- Frames -----

// The pile of free frames. It takes no space of its own: each free frame
// holds, in its first 8 bytes, the address of the next free frame. Only the
// address of the frame on top is kept here, and 0 means the pile is empty.
static mut TOP_FREE_FRAME: u64 = 0;
static mut FREE_FRAMES: u64 = 0; // How many frames are on the pile.

// Puts a frame on the pile.
fn frame_give_back(frame: u64) {
    unsafe {
        *(frame as *mut u64) = TOP_FREE_FRAME;
        TOP_FREE_FRAME = frame;
        FREE_FRAMES += 1;
    }
}

// Takes a frame off the pile and returns its address.
fn frame_take() -> u64 {
    unsafe {
        let frame = TOP_FREE_FRAME;
        if frame == 0 {
            panic!("the machine is out of memory");
        }
        TOP_FREE_FRAME = *(frame as *const u64);
        FREE_FRAMES -= 1;
        frame
    }
}

// Walks the saved memory map once and puts every frame of free memory on the
// pile. Returns the address where the machine's memory ends.
fn frames_setup(map_size: usize, entry_size: usize) -> u64 {
    let map = (&raw const MEMORY_MAP) as *const u8;
    let mut memory_end = 0;
    let mut offset = 0;
    while offset < map_size {
        let entry = unsafe { &*(map.add(offset) as *const MemoryEntry) };
        let end = entry.physical_start + entry.page_count * FRAME_SIZE;

        // Kinds 1 to 7, 9 and 10 are real memory. The other kinds are devices
        // and stretches nobody can use, often far above the memory itself.
        if matches!(entry.kind, 1..=7 | 9 | 10) && end > memory_end {
            memory_end = end;
        }

        // Kind 7 is free memory. The first megabyte is left alone: it holds
        // leftovers of the old PC design, and skipping it keeps address 0
        // free to mean "no frame".
        if entry.kind == 7 {
            let mut frame = entry.physical_start;
            while frame < end {
                if frame >= 0x10_0000 {
                    frame_give_back(frame);
                }
                frame += FRAME_SIZE;
            }
        }
        offset += entry_size;
    }
    memory_end
}

// ----- Page tables -----

// The processor never uses an address as it is. It looks every address up in
// the page tables, which say what really sits behind it. The lookup goes down
// through four tables, from level 4 at the top to level 1. Each table is one
// frame holding 512 lines of 8 bytes, and each level uses its own 9 bits of
// the address to pick a line. A line at level 1 names one frame. A line at
// level 2 may instead name a "big page", 2 MB of memory in one go.
const BIG_PAGE: u64 = 2 * 1024 * 1024;
const GIGABYTE: u64 = 1024 * 1024 * 1024;

// A line of a page table holds an address and a few yes/no marks.
const IN_USE: u64 = 0x01;
const WRITABLE: u64 = 0x02;
const IS_BIG_PAGE: u64 = 0x80;
const ADDRESS_PART: u64 = 0x000F_FFFF_FFFF_F000;

// The address of the kernel's top table (level 4).
static mut TOP_TABLE: u64 = 0;

// Takes a frame and fills it with zeros, which makes it a table of empty lines.
fn empty_table() -> u64 {
    let table = frame_take();
    unsafe { core::ptr::write_bytes(table as *mut u8, 0, FRAME_SIZE as usize) };
    table
}

// Finds the line that `address` uses in a table of the given level.
fn table_line(table: u64, level: u32, address: u64) -> *mut u64 {
    let line_number = (address >> (12 + 9 * (level - 1))) & 511;
    (table + line_number * 8) as *mut u64
}

// Follows a line down to the table below it. If the line is still empty, a
// new table is made for it first.
fn table_below(line: *mut u64) -> u64 {
    unsafe {
        if *line & IN_USE == 0 {
            *line = empty_table() | IN_USE | WRITABLE;
        }
        *line & ADDRESS_PART
    }
}

// Makes the 4096 bytes starting at `address` lead to `frame`.
fn map_page(address: u64, frame: u64) {
    let level_3 = table_below(table_line(unsafe { TOP_TABLE }, 4, address));
    let level_2 = table_below(table_line(level_3, 3, address));
    let level_1 = table_below(table_line(level_2, 2, address));
    unsafe { *table_line(level_1, 1, address) = frame | IN_USE | WRITABLE };
}

// Makes the 2 MB starting at `address` lead to the 2 MB of memory starting at `memory`.
fn map_big_page(address: u64, memory: u64) {
    let level_3 = table_below(table_line(unsafe { TOP_TABLE }, 4, address));
    let level_2 = table_below(table_line(level_3, 3, address));
    unsafe { *table_line(level_2, 2, address) = memory | IN_USE | WRITABLE | IS_BIG_PAGE };
}

// Builds the kernel's own page tables and switches the processor over to
// them. In these tables every address leads to itself, as in the firmware's
// tables, so all the addresses already in use keep working. Returns how many
// bytes the tables cover.
fn page_tables_setup(memory_end: u64) -> u64 {
    unsafe { TOP_TABLE = empty_table() };

    // Cover the first 4 GB, which is where a PC keeps its devices, and all of
    // the memory if the machine has more than that, rounded up to a whole GB.
    let covered = memory_end.max(4 * GIGABYTE).next_multiple_of(GIGABYTE);
    let mut address = 0;
    while address < covered {
        map_big_page(address, address);
        address += BIG_PAGE;
    }

    // The processor keeps the address of the top table in its register "cr3".
    unsafe { asm!("mov cr3, {}", in(reg) TOP_TABLE) };
    covered
}

// ----- The heap -----

// The heap hands out memory in pieces of any size, where frames only come in
// one size. It lives at made-up addresses far above the real memory, starting
// 64 TB up. The page tables make those addresses lead to whichever frames
// were free, so scattered frames look like one unbroken stretch.
const HEAP_START: u64 = 0x4000_0000_0000;
static mut HEAP_END: u64 = HEAP_START; // Where the next new piece is cut.
static mut HEAP_MAPPED: u64 = HEAP_START; // How far the heap has frames behind it.

// Pieces come in the sizes 16, 32, 64, ... bytes, each double the one before.
// Every size has a pile of returned pieces, built like the pile of frames.
// Pile 4 holds the pieces of 16 bytes, pile 5 those of 32, and so on.
static mut HEAP_PILES: [u64; 64] = [0; 64];

// The size of the piece that is handed out for a request. `align` is the
// number the piece's address must be a multiple of.
fn heap_piece_size(size: usize, align: usize) -> u64 {
    size.max(align).max(16).next_power_of_two() as u64
}

// Hands out a piece of memory of at least `size` bytes.
fn heap_take(size: usize, align: usize) -> *mut u8 {
    let piece = heap_piece_size(size, align);
    let pile = piece.trailing_zeros() as usize;
    unsafe {
        // Hand out a returned piece of this size if there is one.
        let returned = HEAP_PILES[pile];
        if returned != 0 {
            HEAP_PILES[pile] = *(returned as *const u64);
            return returned as *mut u8;
        }

        // Otherwise cut a new piece from the end of the heap, at an address
        // that is a multiple of the piece's own size. That may skip some
        // addresses, and no frames are spent on the ones skipped.
        let start = HEAP_END.next_multiple_of(piece);
        if HEAP_MAPPED < start {
            HEAP_MAPPED = start;
        }
        while HEAP_MAPPED < start + piece {
            map_page(HEAP_MAPPED, frame_take());
            HEAP_MAPPED += FRAME_SIZE;
        }
        HEAP_END = start + piece;
        start as *mut u8
    }
}

// Takes a piece back, to be handed out again later.
fn heap_give_back(piece: *mut u8, size: usize, align: usize) {
    let pile = heap_piece_size(size, align).trailing_zeros() as usize;
    unsafe {
        *(piece as *mut u64) = HEAP_PILES[pile];
        HEAP_PILES[pile] = piece as u64;
    }
}

// Tells Rust's `alloc` library to get its memory from this heap and to return
// it there. A `Vec` (a list) or a `String` (a text) calls these by itself.
struct KernelHeap;

unsafe impl GlobalAlloc for KernelHeap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        heap_take(layout.size(), layout.align())
    }

    unsafe fn dealloc(&self, piece: *mut u8, layout: Layout) {
        heap_give_back(piece, layout.size(), layout.align());
    }
}

#[global_allocator]
static KERNEL_HEAP: KernelHeap = KernelHeap;

// ---------- The kernel starts here ----------

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
