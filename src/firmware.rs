//! What the firmware hands over at startup, printing through it, and the
//! takeover of the machine. Notes: `docs/startup.md`.

use core::ffi::c_void;

use crate::serial::serial_print;

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
pub struct SystemTable {
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
pub struct MemoryEntry {
    pub kind: u32,
    pub physical_start: u64,
    pub virtual_start: u64,
    pub page_count: u64,
    pub attribute: u64,
}

// Space for the memory map (32 KB).
pub static mut MEMORY_MAP: [u64; 4096] = [0; 4096];

// ---------- Printing through the firmware (only before the takeover) ----------

pub fn print(table: *mut SystemTable, text: &str) {
    let out = unsafe { (*table).console_out };
    for unit in text.encode_utf16() {
        let letter = [unit, 0];
        unsafe { ((*out).output_string)(out, letter.as_ptr()) };
    }
}

// ---------- Taking over the machine ----------

// Asks the firmware for the memory map, then tells it to step aside.
// Returns how many bytes of the map are filled and the size of one entry.
pub fn take_over(image: *mut c_void, table: *mut SystemTable) -> (usize, usize) {
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
