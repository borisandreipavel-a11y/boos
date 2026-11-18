//! The notebook: named things kept on the disk, in the kernel's own part.
//! Notes: `docs/notebook.md`.

use alloc::string::String;
use alloc::vec::Vec;

use crate::disk::BLOCK_SIZE;
use crate::parts::{check_value, part_read, part_size, part_write};

// The notebook is like a notebook that is only ever added to. A thing is
// kept by writing a new entry behind the last one: its name and its data.
// Nothing already written is changed. If a name is kept again, the newer
// entry is the one that counts.
//
// How the kernel's part is used: block 0 holds the notebook's head, the
// blocks after it hold the entries, one entry in one block, and the part's
// last block is left to the count of starts (see `starts.rs`).

// The head: these 16 letters, then the version of the layout as a number of
// 4 bytes, then a check value of those 20 bytes. A kernel that finds another
// version leaves the part alone.
const HEAD_LETTERS: [u8; 16] = *b"boos notebook   ";
const HEAD_VERSION_AT: usize = 16;
const HEAD_CHECK_AT: usize = 20;
const VERSION: u32 = 1;

// An entry, in its one block: these 8 letters; the entry's number, counted
// from 1, in 8 bytes; how long the name is, in 2 bytes; how long the data
// is, in 2 bytes; a check value of the whole block, in 4 bytes, worked out
// with its own place holding zeros; and, 32 bytes in, the name and right
// behind it the data. The rest of the block is zeros.
const ENTRY_LETTERS: [u8; 8] = *b"boosnote";
const ENTRY_NUMBER_AT: usize = 8;
const ENTRY_NAME_LENGTH_AT: usize = 16;
const ENTRY_DATA_LENGTH_AT: usize = 18;
const ENTRY_CHECK_AT: usize = 20;
const ENTRY_TEXT_AT: usize = 32;

// The longest name and the most data one entry can hold. Together with the
// 32 bytes in front they fill one block.
pub const NAME_MOST: usize = 32;
pub const DATA_MOST: usize = 448;

// How many blocks behind the notebook's end the kernel looks at to see that
// nothing is there. Unused room in the notebook is zeros.
const LOOK_AHEAD: u64 = 8;

// One name, and the block of the part where its newest entry is.
struct Kept {
    name: String,
    block: u64,
}

// What the kernel remembers about the notebook once it is opened. Only the
// startup code and the main loop may use the notebook; nothing protects
// these against a second task.
static mut KEPT: Vec<Kept> = Vec::new();
static mut NEXT_BLOCK: u64 = 0; // The block the next entry goes into. It is also that entry's number.
static mut LAST_BLOCK: u64 = 0; // The last block entries may use.
static mut CAN_KEEP: bool = false; // Whether the notebook may be added to.

// Rust refuses a plain reference to a `static mut`, so this hands the list
// out through its address. As in `chat.rs`: after calling another function
// of this file, do not go on using a list fetched before the call.
fn kept() -> &'static mut Vec<Kept> {
    unsafe { &mut *(&raw mut KEPT) }
}

// What `notebook_open` found.
pub struct NotebookFacts {
    // How many entries the notebook holds.
    pub entries: u64,
    // How many more entries there is room for.
    pub room: u64,
    // Whether the notebook was begun just now, on a part that held nothing.
    pub new: bool,
    // Whether something lies behind the notebook's end that the kernel
    // cannot read. Such a notebook is read and not added to.
    pub damaged: bool,
}

// Reads a number of `length` bytes out of a block, lowest byte first.
fn number_at(block: &[u8], at: usize, length: usize) -> u64 {
    let mut number = 0;
    for place in 0..length {
        number |= (block[at + place] as u64) << (8 * place);
    }
    number
}

// Writes a number of `length` bytes into a block, lowest byte first.
fn number_into(block: &mut [u8], at: usize, length: usize, number: u64) {
    for place in 0..length {
        block[at + place] = (number >> (8 * place)) as u8;
    }
}

// Says whether every sign of a name is a plain one, and the name neither
// empty nor too long.
fn name_fits(name: &[u8]) -> bool {
    !name.is_empty() && name.len() <= NAME_MOST && name.iter().all(|sign| (b' '..=b'~').contains(sign))
}

// Looks at a block as an entry. If it is a whole entry with the number
// `number`, gives back where in the block its name and its data are.
// Everything in the block comes from outside the kernel, so the lengths are
// held to their limits before they are used, and the check value must fit.
fn entry_read(block: &[u8; BLOCK_SIZE as usize], number: u64) -> Option<(usize, usize)> {
    if block[..8] != ENTRY_LETTERS || number_at(block, ENTRY_NUMBER_AT, 8) != number {
        return None;
    }
    let name_length = number_at(block, ENTRY_NAME_LENGTH_AT, 2) as usize;
    let data_length = number_at(block, ENTRY_DATA_LENGTH_AT, 2) as usize;
    if name_length > NAME_MOST || data_length > DATA_MOST {
        return None;
    }
    if !name_fits(&block[ENTRY_TEXT_AT..ENTRY_TEXT_AT + name_length]) {
        return None;
    }
    let mut copy = *block;
    copy[ENTRY_CHECK_AT..ENTRY_CHECK_AT + 4].fill(0);
    if check_value(&copy) as u64 != number_at(block, ENTRY_CHECK_AT, 4) {
        return None;
    }
    Some((name_length, data_length))
}

// Opens the notebook: reads its head, or begins a new notebook on a part
// that holds nothing, and goes through the entries from the first to the
// last. If the part holds something the kernel does not know, the reason
// comes back in words, and nothing at all is written to the part.
pub fn notebook_open() -> Result<NotebookFacts, &'static str> {
    let size = part_size();
    if size == 0 {
        return Err("the kernel has no part of its own on the disk");
    }
    if size < 4 {
        return Err("my part is too small for a notebook");
    }
    // Entries may use the blocks from 1 to the last but one.
    let last_block = size - 2;
    let mut block = [0u8; BLOCK_SIZE as usize];

    part_read(0, &mut block)?;
    let mut new = false;
    if block.iter().all(|byte| *byte == 0) {
        // No head. That is a part nothing was ever kept in only if no
        // entries are there either. A head that has gone missing in front of
        // entries is something else, and the kernel does not begin a new
        // notebook over them.
        let mut behind = [0u8; BLOCK_SIZE as usize];
        for number in 1..=LOOK_AHEAD.min(last_block) {
            part_read(number, &mut behind)?;
            if behind.iter().any(|byte| *byte != 0) {
                return Err("my part holds something, but no notebook begins it");
            }
        }
        // Begin a new notebook: write the head, and see that it is there.
        let mut head = [0u8; BLOCK_SIZE as usize];
        head[..16].copy_from_slice(&HEAD_LETTERS);
        number_into(&mut head, HEAD_VERSION_AT, 4, VERSION as u64);
        let check = check_value(&head[..HEAD_CHECK_AT]);
        number_into(&mut head, HEAD_CHECK_AT, 4, check as u64);
        part_write(0, &head)?;
        part_read(0, &mut block)?;
        if block != head {
            return Err("the disk did not hold what was written to it");
        }
        new = true;
    } else if block[..16] != HEAD_LETTERS || check_value(&block[..HEAD_CHECK_AT]) as u64 != number_at(&block, HEAD_CHECK_AT, 4) {
        return Err("the first block of my part holds something I do not know");
    } else if number_at(&block, HEAD_VERSION_AT, 4) != VERSION as u64 {
        return Err("the notebook is of a version this kernel does not know");
    }

    // Go through the entries, one block each, from the first. Entry number 1
    // is in block 1, number 2 in block 2, and so on. The first block that is
    // not the next whole entry is the notebook's end.
    let names = kept();
    names.clear();
    let mut next_block = 1;
    while next_block <= last_block {
        part_read(next_block, &mut block)?;
        let Some((name_length, _)) = entry_read(&block, next_block) else {
            break;
        };
        // The name is plain signs, so it is good text.
        let name: String = block[ENTRY_TEXT_AT..ENTRY_TEXT_AT + name_length].iter().map(|sign| *sign as char).collect();
        // A newer entry for a name takes the place of the older one.
        match names.iter_mut().find(|kept| kept.name == name) {
            Some(kept) => kept.block = next_block,
            None => names.push(Kept { name, block: next_block }),
        }
        next_block += 1;
    }

    // Behind the end there must be nothing. The block at the end itself may
    // be zeros, or an entry that a power cut spoiled while it was written;
    // the next entry goes over it. But if a block behind it holds anything,
    // then entries lie behind a block that cannot be read, and writing at
    // the end would write over them. Such a notebook is not added to.
    let mut damaged = false;
    for number in next_block + 1..=(next_block + LOOK_AHEAD).min(last_block) {
        part_read(number, &mut block)?;
        if block.iter().any(|byte| *byte != 0) {
            damaged = true;
        }
    }

    let entries = next_block - 1;
    unsafe {
        NEXT_BLOCK = next_block;
        LAST_BLOCK = last_block;
        CAN_KEEP = !damaged;
    }
    Ok(NotebookFacts { entries, room: if damaged { 0 } else { last_block + 1 - next_block }, new, damaged })
}

// Says whether things can be kept in the notebook right now.
pub fn notebook_ready() -> bool {
    unsafe { CAN_KEEP }
}

// Keeps a thing under a name: writes a new entry behind the last one. If the
// name was kept before, this entry now counts for it.
pub fn notebook_keep(name: &str, data: &[u8]) -> Result<(), &'static str> {
    if !unsafe { CAN_KEEP } {
        return Err("the notebook cannot be added to");
    }
    if !name_fits(name.as_bytes()) {
        return Err("the name is not one the notebook can hold");
    }
    if data.len() > DATA_MOST {
        return Err("the thing is too long for the notebook");
    }
    let (next_block, last_block) = unsafe { (NEXT_BLOCK, LAST_BLOCK) };
    if next_block > last_block {
        return Err("the notebook is full");
    }

    // The entry's block: the letters, the entry's number, the two lengths,
    // the name and the data, and last the check value over all of it.
    let mut block = [0u8; BLOCK_SIZE as usize];
    block[..8].copy_from_slice(&ENTRY_LETTERS);
    number_into(&mut block, ENTRY_NUMBER_AT, 8, next_block);
    number_into(&mut block, ENTRY_NAME_LENGTH_AT, 2, name.len() as u64);
    number_into(&mut block, ENTRY_DATA_LENGTH_AT, 2, data.len() as u64);
    let data_at = ENTRY_TEXT_AT + name.len();
    block[ENTRY_TEXT_AT..data_at].copy_from_slice(name.as_bytes());
    block[data_at..data_at + data.len()].copy_from_slice(data);
    let check = check_value(&block);
    number_into(&mut block, ENTRY_CHECK_AT, 4, check as u64);

    // Write it and read it back. The thing counts as kept only if the disk
    // holds exactly what was written.
    part_write(next_block, &block)?;
    let mut read_back = [0u8; BLOCK_SIZE as usize];
    part_read(next_block, &mut read_back)?;
    if read_back != block {
        return Err("the disk did not hold what was written to it");
    }

    // Only now does the kernel remember the entry.
    let names = kept();
    match names.iter_mut().find(|kept| kept.name == name) {
        Some(kept) => kept.block = next_block,
        None => names.push(Kept { name: String::from(name), block: next_block }),
    }
    unsafe { NEXT_BLOCK = next_block + 1 };
    Ok(())
}

// Finds the thing kept under a name. Gives back its data, or nothing if no
// thing has that name.
pub fn notebook_find(name: &str) -> Result<Option<Vec<u8>>, &'static str> {
    let Some(place) = kept().iter().find(|kept| kept.name == name).map(|kept| kept.block) else {
        return Ok(None);
    };
    // Read the entry again, and believe it only as far as it checks out now.
    let mut block = [0u8; BLOCK_SIZE as usize];
    part_read(place, &mut block)?;
    let Some((name_length, data_length)) = entry_read(&block, place) else {
        return Err("the entry for that name can no longer be read");
    };
    let data_at = ENTRY_TEXT_AT + name_length;
    Ok(Some(block[data_at..data_at + data_length].to_vec()))
}
