//! Free memory, kept as a pile of frames of 4096 bytes. Notes: `docs/memory.md`.

use crate::firmware::{MEMORY_MAP, MemoryEntry};

// Memory is handed out in "frames": pieces of 4096 bytes. The processor's
// page tables work in pieces of that size too.
pub const FRAME_SIZE: u64 = 4096;

// The pile of free frames. It takes no space of its own: each free frame
// holds, in its first 8 bytes, the address of the next free frame. Only the
// address of the frame on top is kept here, and 0 means the pile is empty.
static mut TOP_FREE_FRAME: u64 = 0;
pub static mut FREE_FRAMES: u64 = 0; // How many frames are on the pile.

// Puts a frame on the pile.
pub fn frame_give_back(frame: u64) {
    unsafe {
        *(frame as *mut u64) = TOP_FREE_FRAME;
        TOP_FREE_FRAME = frame;
        FREE_FRAMES += 1;
    }
}

// Takes a frame off the pile and returns its address.
pub fn frame_take() -> u64 {
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
pub fn frames_setup(map_size: usize, entry_size: usize) -> u64 {
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
