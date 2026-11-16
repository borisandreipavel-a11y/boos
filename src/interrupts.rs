//! The interrupt table (IDT): which code the processor jumps to for each
//! failure and each device signal, and the machine instructions that wrap a
//! device handler. Notes: `docs/interrupts.md`.

use core::arch::{asm, naked_asm};

use crate::controller::{FIRST_DEVICE_ENTRY, KEYBOARD_LINE, TIMER_LINE};
use crate::faults::FAULTS;
use crate::keyboard::on_keyboard;
use crate::processor::TablePointer;
use crate::segments::CODE_SEGMENT;
use crate::tasks::{WAIT_ENTRY, timer_entry, wait_entry};

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
pub fn load_interrupt_table() {
    for (number, fault) in FAULTS.iter().enumerate() {
        set_interrupt_entry(number, fault.1);
    }

    // Only the timer and the keyboard are listened to. A signal on any other
    // device line is ignored, instead of counting as a failure.
    for line in 0..16 {
        set_interrupt_entry(FIRST_DEVICE_ENTRY + line, ignore_signal);
    }
    set_interrupt_entry(FIRST_DEVICE_ENTRY + TIMER_LINE, timer_entry);
    set_interrupt_entry(FIRST_DEVICE_ENTRY + KEYBOARD_LINE, device_entry!(on_keyboard));

    // One more line, not for a device: a task uses it to ask to be set aside.
    set_interrupt_entry(WAIT_ENTRY, wait_entry);

    let pointer = TablePointer {
        last_byte: (size_of::<[InterruptEntry; 256]>() - 1) as u16,
        address: (&raw const INTERRUPT_TABLE) as u64,
    };
    unsafe { asm!("lidt [{}]", in(reg) &pointer) };
}
