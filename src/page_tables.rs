//! The kernel's own page tables: what sits behind each address.
//! Notes: `docs/memory.md`.

use core::arch::asm;

use crate::frames::{FRAME_SIZE, frame_take};
use crate::processor::{signals_back, signals_off};

// The processor never uses an address as it is. It looks every address up in
// the page tables, which say what really sits behind it. The lookup goes down
// through four tables, from level 4 at the top to level 1. Each table is one
// frame holding 512 lines of 8 bytes, and each level uses its own 9 bits of
// the address to pick a line. A line at level 1 names one frame. A line at
// level 2 may instead name a "big page", 2 MB of memory in one go.
const BIG_PAGE: u64 = 2 * 1024 * 1024;
pub const GIGABYTE: u64 = 1024 * 1024 * 1024;

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
pub fn map_page(address: u64, frame: u64) {
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
pub fn page_tables_setup(memory_end: u64) -> u64 {
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
    unsafe { COVERED = covered };
    covered
}

// How many bytes, counted from address 0, lead to themselves through 2 MB pages.
static mut COVERED: u64 = 0;

// Makes a device's memory reachable: `size` bytes starting at `address`, with
// every address leading to itself. A device's controls may sit far above the
// range that `page_tables_setup` covered.
pub fn map_device_memory(address: u64, size: u64) {
    let were_on = signals_off();
    let mut page = address & !(FRAME_SIZE - 1);
    while page < address + size {
        // Inside the covered range the address leads to itself already, and
        // `map_page` must not be used where 2 MB pages are.
        if page >= unsafe { COVERED } {
            map_page(page, page);
        }
        page += FRAME_SIZE;
    }
    signals_back(were_on);
}
