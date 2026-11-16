//! The segment table (GDT). Notes: `docs/interrupts.md`.

use core::arch::asm;

use crate::processor::TablePointer;

// The segment table (GDT) tells the processor what kind of code and data the
// kernel uses. The firmware's copy lives in memory the kernel does not own, so
// the kernel brings its own: an empty entry, one for code and one for data.
static SEGMENT_TABLE: [u64; 3] = [0, 0x00AF_9B00_0000_FFFF, 0x00CF_9300_0000_FFFF];
pub const CODE_SEGMENT: u16 = 8; // The second entry (each entry is 8 bytes).
pub const DATA_SEGMENT: u16 = 16; // The third entry.

// Hands the processor the kernel's segment table and switches over to it.
pub fn load_segment_table() {
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
