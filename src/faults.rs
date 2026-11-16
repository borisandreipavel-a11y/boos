//! Catching the processor's failures: each of the 32 gets a name and a few
//! machine instructions that lead to one report. Notes: `docs/interrupts.md`.

use core::arch::{asm, naked_asm};
use core::fmt::Write;

use crate::processor::stop;
use crate::serial::Serial;

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
pub static FAULTS: [(&str, extern "sysv64" fn()); 32] = [
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
