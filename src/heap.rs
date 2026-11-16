//! The heap: memory in pieces of any size, and the link that lets Rust's own
//! lists and text use it. Notes: `docs/memory.md`.

use core::alloc::{GlobalAlloc, Layout};

use crate::frames::{FRAME_SIZE, frame_take};
use crate::page_tables::map_page;
use crate::processor::{signals_back, signals_off};

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

// Hands out a piece of memory of at least `size` bytes. Call it, and
// `heap_give_back`, only with device signals off.
pub fn heap_take(size: usize, align: usize) -> *mut u8 {
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
pub fn heap_give_back(piece: *mut u8, size: usize, align: usize) {
    let pile = heap_piece_size(size, align).trailing_zeros() as usize;
    unsafe {
        *(piece as *mut u64) = HEAP_PILES[pile];
        HEAP_PILES[pile] = piece as u64;
    }
}

// Tells Rust's `alloc` library to get its memory from this heap and to return
// it there. A `Vec` (a list) or a `String` (a text) calls these by itself.
// Device signals are off meanwhile, so the timer cannot switch to another
// task while the heap is half-way through a change.
struct KernelHeap;

unsafe impl GlobalAlloc for KernelHeap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let were_on = signals_off();
        let piece = heap_take(layout.size(), layout.align());
        signals_back(were_on);
        piece
    }

    unsafe fn dealloc(&self, piece: *mut u8, layout: Layout) {
        let were_on = signals_off();
        heap_give_back(piece, layout.size(), layout.align());
        signals_back(were_on);
    }
}

#[global_allocator]
static KERNEL_HEAP: KernelHeap = KernelHeap;
