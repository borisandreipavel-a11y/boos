#![no_std]
#![no_main]
#![allow(dead_code)]

use core::arch::{asm, naked_asm};
use core::ffi::c_void;
use core::fmt::{self, Write};
use core::panic::PanicInfo;

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

// Fills in the interrupt table's lines for the 32 failures and hands the
// table to the processor.
fn load_interrupt_table() {
    let table = &raw mut INTERRUPT_TABLE;
    for (number, fault) in FAULTS.iter().enumerate() {
        let address = fault.1 as usize as u64;
        let entry = InterruptEntry {
            address_low: address as u16,
            code_segment: CODE_SEGMENT,
            spare_stack: 0,
            kind: 0x8E, // "In use, kernel only, no other signals while it runs."
            address_middle: (address >> 16) as u16,
            address_high: (address >> 32) as u32,
            unused: 0,
        };
        unsafe { (*table)[number] = entry };
    }
    let pointer = TablePointer {
        last_byte: (size_of::<[InterruptEntry; 256]>() - 1) as u16,
        address: table as u64,
    };
    unsafe { asm!("lidt [{}]", in(reg) &pointer) };
}

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

    // Add up the free memory listed in the map.
    let map = (&raw const MEMORY_MAP) as *const u8;
    let mut free_pages: u64 = 0;
    let mut offset = 0;
    while offset < map_size {
        let entry = unsafe { &*(map.add(offset) as *const MemoryEntry) };
        if entry.kind == 7 {
            free_pages += entry.page_count;
        }
        offset += entry_size;
    }
    write!(serial, "Free memory: {} MB\r\n", free_pages * 4096 / (1024 * 1024)).ok();

    loop {}
}

// Runs when Rust code gives up, for example on a list index that is out of range.
#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    let mut serial = Serial;
    if let Some(place) = info.location() {
        write!(serial, "Kernel panic: {}:{}: ", place.file(), place.line()).ok();
    }
    write!(serial, "{}\r\n", info.message()).ok();
    stop()
}