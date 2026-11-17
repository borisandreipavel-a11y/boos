//! What the firmware hands over at startup, printing through it, asking it
//! about the screen, and the takeover of the machine. Notes: `docs/startup.md`.

use core::ffi::c_void;

use crate::serial::serial_print;

// The firmware service that writes text to the screen.
#[repr(C)]
struct TextOutput {
    reset: usize,
    output_string: extern "efiapi" fn(this: *mut TextOutput, text: *const u16) -> usize,
}

// The firmware names each of its services by 16 bytes, written in four groups.
#[repr(C)]
struct ServiceName {
    first: u32,
    second: u16,
    third: u16,
    rest: [u8; 8],
}

// The name of the graphics service (GOP), which knows about the screen.
const GRAPHICS_SERVICE: ServiceName = ServiceName {
    first: 0x9042a9de,
    second: 0x23dc,
    third: 0x4a38,
    rest: [0x96, 0xfb, 0x7a, 0xde, 0xd0, 0x80, 0x51, 0x6a],
};

// What the graphics service hands out. Its first three entries are functions
// this kernel does not call. The fourth points to the facts about the screen.
#[repr(C)]
struct GraphicsService {
    skipped: [usize; 3],
    mode: *const GraphicsMode,
}

// How the screen is set up right now, and where its memory is.
#[repr(C)]
struct GraphicsMode {
    mode_count: u32,
    mode_number: u32,
    details: *const GraphicsDetails,
    details_size: usize,
    memory_start: u64,
    memory_size: usize,
}

// The size of the screen and the way a dot's colour is written.
#[repr(C)]
struct GraphicsDetails {
    version: u32,
    width: u32,
    height: u32,
    colour_form: u32,
    colour_masks: [u32; 4],
    row_length: u32,
}

// The firmware services that only exist until the kernel takes over.
// Only the three this kernel needs are named; the rest are skipped.
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
    skipped_3: [usize; 10],
    // Finds a service by its name and hands back a pointer to it.
    locate_protocol: extern "efiapi" fn(
        name: *const ServiceName,
        registration: *mut c_void,
        service: *mut *mut c_void,
    ) -> usize,
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

// ---------- Asking about the screen (only before the takeover) ----------

// A picture on the screen is a grid of dots (pixels). Every dot has a place in
// the screen's memory (the framebuffer): four bytes that hold how much red,
// green and blue the dot shows. This says which of the three comes first.
pub enum ColourOrder {
    RedGreenBlue,
    BlueGreenRed,
}

// What the kernel knows about the screen.
pub struct Screen {
    // Where the screen's memory starts, and how many bytes it is.
    pub memory_start: u64,
    pub memory_size: u64,
    // How many dots the picture is wide and high.
    pub width: u32,
    pub height: u32,
    // How many dots one row takes up in the memory. It can be more than
    // `width`: then the dots at the end of each row are not shown.
    pub row_length: u32,
    pub colours: ColourOrder,
}

// Asks the firmware's graphics service about the screen. The answer has to be
// fetched now, because the service is gone after the takeover. Nothing is
// drawn and nothing about the screen is changed. If there is no usable
// screen, the answer is the reason in words.
pub fn screen_find(table: *mut SystemTable) -> Result<Screen, &'static str> {
    let boot = unsafe { (*table).boot_services };
    let mut service: *mut c_void = core::ptr::null_mut();
    let status = unsafe {
        ((*boot).locate_protocol)(&GRAPHICS_SERVICE, core::ptr::null_mut(), &mut service)
    };
    // The firmware answers 0 for "found".
    if status != 0 || service.is_null() {
        return Err("none found, the firmware has no graphics service");
    }

    let mode = unsafe { (*(service as *const GraphicsService)).mode };
    if mode.is_null() {
        return Err("found but not usable, the firmware says nothing about it");
    }
    let details = unsafe { (*mode).details };
    let details_size = unsafe { (*mode).details_size };
    if details.is_null() || details_size < size_of::<GraphicsDetails>() {
        return Err("found but not usable, the firmware says nothing about it");
    }

    // These facts lie in the firmware's memory, so they are copied out here.
    let memory_start = unsafe { (*mode).memory_start };
    let memory_size = unsafe { (*mode).memory_size } as u64;
    let width = unsafe { (*details).width };
    let height = unsafe { (*details).height };
    let row_length = unsafe { (*details).row_length };
    let colours = match unsafe { (*details).colour_form } {
        0 => ColourOrder::RedGreenBlue,
        1 => ColourOrder::BlueGreenRed,
        // "The screen can only be drawn on through the firmware's own functions."
        3 => return Err("found but not usable, the firmware gives no memory to draw into"),
        _ => return Err("found but not usable, its colours are written in a way this kernel does not know"),
    };

    // The memory must hold every row, at four bytes a dot.
    let needed = row_length as u64 * height as u64 * 4;
    if memory_start == 0 || width == 0 || height == 0 || row_length < width || memory_size < needed {
        return Err("found but not usable, the firmware's facts about it do not fit together");
    }

    Ok(Screen { memory_start, memory_size, width, height, row_length, colours })
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
