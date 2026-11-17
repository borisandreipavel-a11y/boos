//! A count of how often the kernel has started, kept on the disk. It is the
//! first thing the kernel writes, and shows that what it writes is still
//! there after the machine was switched off. Notes: `docs/disk.md`.

use crate::disk::BLOCK_SIZE;
use crate::parts::{check_value, part_read, part_size, part_write};

// The count is kept in the last block of the kernel's own part, so that the
// part's first blocks stay free for what will later be kept there. The block
// holds three things: these 16 letters, so that the kernel knows the block
// as its own; the count, as a number of 8 bytes; and a check value over
// those 24 bytes, so that a block that was only half written is noticed.
const SIGNATURE: [u8; 16] = *b"boos start count";
const COUNT_AT: usize = 16;
const CHECK_AT: usize = 24;

// Reads the count of starts from the disk, adds this start to it, and
// writes it back. Gives back this start's number, and whether the count had
// to begin again because the block held something the kernel does not know.
pub fn start_count() -> Result<(u64, bool), &'static str> {
    let size = part_size();
    if size == 0 {
        return Err("the kernel has no part of its own on the disk");
    }
    let place = size - 1;

    // What the block holds now. Everything read from a disk comes from
    // outside the kernel: it is believed only if the letters are there and
    // the check value fits.
    let mut block = [0u8; BLOCK_SIZE as usize];
    part_read(place, &mut block)?;
    let mut begun_again = false;
    let earlier_starts = if block.iter().all(|byte| *byte == 0) {
        // Nothing was ever written here: no start has been counted yet.
        0
    } else if block[..COUNT_AT] == SIGNATURE && number_at(&block, CHECK_AT, 4) == check_value(&block[..CHECK_AT]) as u64 {
        number_at(&block, COUNT_AT, 8)
    } else {
        begun_again = true;
        0
    };

    // This start's number. (`saturating_add` stops at the largest number
    // instead of wrapping round to 0, or stopping the kernel, if the count
    // on the disk is already the largest there is.)
    let this_start = earlier_starts.saturating_add(1);

    // The block as it is to be: zeros, then the letters, the count with its
    // lowest byte first, and the check value over both.
    let mut new_block = [0u8; BLOCK_SIZE as usize];
    new_block[..COUNT_AT].copy_from_slice(&SIGNATURE);
    new_block[COUNT_AT..CHECK_AT].copy_from_slice(&this_start.to_le_bytes());
    let check = check_value(&new_block[..CHECK_AT]);
    new_block[CHECK_AT..CHECK_AT + 4].copy_from_slice(&check.to_le_bytes());

    // Write it, then read it back. The number counts only if the disk
    // really holds what was written.
    part_write(place, &new_block)?;
    let mut read_back = [0u8; BLOCK_SIZE as usize];
    part_read(place, &mut read_back)?;
    if read_back != new_block {
        return Err("the disk did not hold what was written to it");
    }
    Ok((this_start, begun_again))
}

// Reads a number of `length` bytes out of a block, lowest byte first.
fn number_at(block: &[u8], at: usize, length: usize) -> u64 {
    let mut number = 0;
    for place in 0..length {
        number |= (block[at + place] as u64) << (8 * place);
    }
    number
}
