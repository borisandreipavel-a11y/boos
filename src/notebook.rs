//! The notebook: named things kept on the disk, in the kernel's own part.
//! Notes: `docs/notebook.md`.

use alloc::string::String;
use alloc::vec::Vec;

use crate::disk::BLOCK_SIZE;
use crate::parts::{check_value, part_read, part_size, part_write};

// The notebook is like a notebook that is only ever added to. A thing is
// kept by writing new entries behind the last one: its name and its data.
// Nothing already written is changed. If a name is kept again, the newer
// thing is the one that counts.
//
// How the kernel's part is used: block 0 holds the notebook's head, the
// blocks after it hold the entries, one entry in one block, and the part's
// last block is left to the count of starts (see `starts.rs`).
//
// A thing of up to 448 bytes is kept in one entry. A longer thing is kept in
// several entries one right behind the other, its pieces. Each piece is a
// whole entry of its own, with the thing's name, and says which piece of how
// many it is. The thing counts only once its last piece is there and a check
// value of all of its data fits. So a power cut in the middle of keeping it
// leaves whole entries of a thing that never got finished: they are passed
// over, and the thing kept under that name before still counts. Where the
// notebook ends is found exactly as it was before pieces existed: what a
// piece says decides whether a thing counts, never whether a block is an
// entry.

// The head: these 16 letters, then the version of the layout as a number of
// 4 bytes, then a check value of those 20 bytes. A kernel that finds another
// version leaves the part alone. Pieces did not change the version: a kernel
// from before them reads every piece as an entry of its own, under a name it
// never asks for, and adds its own entries behind the end as before.
const HEAD_LETTERS: [u8; 16] = *b"boos notebook   ";
const HEAD_VERSION_AT: usize = 16;
const HEAD_CHECK_AT: usize = 20;
const VERSION: u32 = 1;

// An entry, in its one block: these 8 letters; the entry's number, counted
// from 1, in 8 bytes; how long the name is, in 2 bytes; how long the data
// is, in 2 bytes; a check value of the whole block, in 4 bytes, worked out
// with its own place holding zeros; for a piece of a longer thing, which
// piece it is, counted from 1, in 2 bytes, how many pieces the thing has, in
// 2 bytes, and a check value of all of the thing's data, in 4 bytes, the
// same in every piece (all 8 bytes are zeros for a thing of one entry); and,
// 32 bytes in, the name and right behind it the data. The rest of the block
// is zeros.
const ENTRY_LETTERS: [u8; 8] = *b"boosnote";
const ENTRY_NUMBER_AT: usize = 8;
const ENTRY_NAME_LENGTH_AT: usize = 16;
const ENTRY_DATA_LENGTH_AT: usize = 18;
const ENTRY_CHECK_AT: usize = 20;
const ENTRY_PIECE_AT: usize = 24;
const ENTRY_PIECES_AT: usize = 26;
const ENTRY_WHOLE_CHECK_AT: usize = 28;
const ENTRY_TEXT_AT: usize = 32;

// The longest name and the most data one entry can hold. Together with the
// 32 bytes in front they fill one block.
pub const NAME_MOST: usize = 32;
pub const DATA_MOST: usize = 448;

// The most data one thing can hold: 32 KB, as much as the longest script the
// box takes. Kept in pieces of 448 bytes, that is at most 74 pieces.
pub const THING_MOST: usize = 32 * 1024;
const PIECES_MOST: usize = THING_MOST.div_ceil(DATA_MOST);

// How many blocks behind the notebook's end the kernel looks at to see that
// nothing is there. Unused room in the notebook is zeros.
const LOOK_AHEAD: u64 = 8;

// One name, and where its newest whole thing is: the block of its first
// entry, and how many entries it takes (1 for a thing of one entry).
struct Kept {
    name: String,
    block: u64,
    pieces: u64,
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
// The eight bytes for pieces are not looked at here: whether a block is an
// entry does not depend on them.
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

// What the eight bytes for pieces say about a whole entry.
enum Piece {
    // A thing of one entry: all eight bytes are zeros.
    Whole,
    // Piece number `piece` of a thing kept in `pieces` entries, all of whose
    // data has the check value `whole_check`.
    Part { piece: u64, pieces: u64, whole_check: u64 },
    // Anything else. Such an entry belongs to no thing.
    Odd,
}

// Reads the eight bytes for pieces of a whole entry whose data is
// `data_length` bytes long. They come from outside the kernel, so they are
// held to their limits here, before anything uses them: a piece is counted
// from 1, a thing has 2 to `PIECES_MOST` pieces, every piece but the last is
// full, the last holds at least one byte, and all of them together hold at
// most `THING_MOST` bytes. A thing that fits in one entry is always kept in
// one, so a thing in pieces is always longer than an entry.
fn piece_of(block: &[u8; BLOCK_SIZE as usize], data_length: usize) -> Piece {
    let piece = number_at(block, ENTRY_PIECE_AT, 2);
    let pieces = number_at(block, ENTRY_PIECES_AT, 2);
    let whole_check = number_at(block, ENTRY_WHOLE_CHECK_AT, 4);
    if piece == 0 && pieces == 0 && whole_check == 0 {
        return Piece::Whole;
    }
    if pieces < 2 || pieces > PIECES_MOST as u64 || piece == 0 || piece > pieces {
        return Piece::Odd;
    }
    if piece < pieces && data_length != DATA_MOST {
        return Piece::Odd;
    }
    // `pieces` is at most `PIECES_MOST` here, so this cannot overflow.
    if piece == pieces && (data_length == 0 || (pieces as usize - 1) * DATA_MOST + data_length > THING_MOST) {
        return Piece::Odd;
    }
    Piece::Part { piece, pieces, whole_check }
}

// A thing in pieces, being put together while its pieces come one after the
// other in the notebook: its name, the block of its first piece, how many
// pieces it has, the check value they state, and its data so far, which can
// never grow past `PIECES_MOST` full pieces.
struct Gathering {
    name: String,
    first: u64,
    pieces: u64,
    whole_check: u64,
    data: Vec<u8>,
}

// Notes that the newest whole thing for `name` begins at `block` and takes
// `pieces` entries. A newer thing for a name takes the place of the older.
fn remember(names: &mut Vec<Kept>, name: &str, block: u64, pieces: u64) {
    match names.iter_mut().find(|kept| kept.name == name) {
        Some(kept) => {
            kept.block = block;
            kept.pieces = pieces;
        }
        None => names.push(Kept { name: String::from(name), block, pieces }),
    }
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
    let mut gathering: Option<Gathering> = None;
    let mut next_block = 1;
    while next_block <= last_block {
        part_read(next_block, &mut block)?;
        let Some((name_length, data_length)) = entry_read(&block, next_block) else {
            break;
        };
        // The name is plain signs, so it is good text.
        let name: String = block[ENTRY_TEXT_AT..ENTRY_TEXT_AT + name_length].iter().map(|sign| *sign as char).collect();
        let data_at = ENTRY_TEXT_AT + name_length;
        match piece_of(&block, data_length) {
            Piece::Whole => {
                // A thing of one entry. A thing that was being put together
                // never got finished.
                gathering = None;
                remember(names, &name, next_block, 1);
            }
            Piece::Part { piece, pieces, whole_check } => {
                // The first piece begins a thing. Any other piece must be the
                // next one of the thing being put together, in the block right
                // behind the piece before it. If it is not, that thing never
                // got finished, and this piece belongs to nothing.
                if piece == 1 {
                    gathering = Some(Gathering { name, first: next_block, pieces, whole_check, data: Vec::new() });
                } else if !matches!(&gathering, Some(thing) if thing.name == name && thing.pieces == pieces
                    && thing.whole_check == whole_check && thing.first + piece - 1 == next_block)
                {
                    gathering = None;
                }
                // Add this piece's data. With the last piece the thing is
                // there, and it counts if the check value of all of its data
                // fits.
                let mut finished = false;
                if let Some(thing) = gathering.as_mut() {
                    thing.data.extend_from_slice(&block[data_at..data_at + data_length]);
                    if piece == pieces {
                        if check_value(&thing.data) as u64 == thing.whole_check {
                            remember(names, &thing.name, thing.first, pieces);
                        }
                        finished = true;
                    }
                }
                if finished {
                    gathering = None;
                }
            }
            Piece::Odd => gathering = None,
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

// Builds the block of one entry, writes it into block `number`, which is
// also the entry's number, and reads it back. The entry is there only if the
// block, read back, is exactly what was written. For a thing of one entry,
// `piece`, `pieces` and `whole_check` are 0.
fn entry_write(number: u64, name: &str, data: &[u8], piece: u64, pieces: u64, whole_check: u64) -> Result<(), &'static str> {
    // The entry's block: the letters, the entry's number, the two lengths,
    // what it says about pieces, the name and the data, and last the check
    // value over all of it.
    let mut block = [0u8; BLOCK_SIZE as usize];
    block[..8].copy_from_slice(&ENTRY_LETTERS);
    number_into(&mut block, ENTRY_NUMBER_AT, 8, number);
    number_into(&mut block, ENTRY_NAME_LENGTH_AT, 2, name.len() as u64);
    number_into(&mut block, ENTRY_DATA_LENGTH_AT, 2, data.len() as u64);
    number_into(&mut block, ENTRY_PIECE_AT, 2, piece);
    number_into(&mut block, ENTRY_PIECES_AT, 2, pieces);
    number_into(&mut block, ENTRY_WHOLE_CHECK_AT, 4, whole_check);
    let data_at = ENTRY_TEXT_AT + name.len();
    block[ENTRY_TEXT_AT..data_at].copy_from_slice(name.as_bytes());
    block[data_at..data_at + data.len()].copy_from_slice(data);
    let check = check_value(&block);
    number_into(&mut block, ENTRY_CHECK_AT, 4, check as u64);

    // Write it and read it back.
    part_write(number, &block)?;
    let mut read_back = [0u8; BLOCK_SIZE as usize];
    part_read(number, &mut read_back)?;
    if read_back != block {
        return Err("the disk did not hold what was written to it");
    }
    Ok(())
}

// Keeps a thing under a name: writes it behind the last entry, in one entry
// or, if it is longer than an entry holds, in pieces. If the name was kept
// before, this thing now counts for it.
pub fn notebook_keep(name: &str, data: &[u8]) -> Result<(), &'static str> {
    if !unsafe { CAN_KEEP } {
        return Err("the notebook cannot be added to");
    }
    if !name_fits(name.as_bytes()) {
        return Err("the name is not one the notebook can hold");
    }
    if data.len() > THING_MOST {
        return Err("the thing is too long for the notebook");
    }
    // How many entries it takes: one for up to 448 bytes, otherwise a piece
    // for every 448 bytes and one for the rest. All of them must fit before
    // the first is written.
    let pieces = if data.len() <= DATA_MOST { 1 } else { data.len().div_ceil(DATA_MOST) as u64 };
    let (next_block, last_block) = unsafe { (NEXT_BLOCK, LAST_BLOCK) };
    if next_block > last_block || pieces > last_block - next_block + 1 {
        return Err("the notebook is full");
    }

    if pieces == 1 {
        // One entry, with zeros where pieces are described: exactly the
        // entry a kernel from before pieces writes.
        entry_write(next_block, name, data, 0, 0, 0)?;
    } else {
        // The pieces, one after the other, each a whole entry. Once a piece
        // is on the disk, the next entry goes behind it, whatever happens to
        // the rest: so what the kernel remembers is always what opening the
        // notebook again would find. If a piece cannot be written, the
        // pieces before it stay as entries of a thing that never got
        // finished, and the thing kept under this name before still counts.
        let whole_check = check_value(data) as u64;
        for (index, piece_data) in data.chunks(DATA_MOST).enumerate() {
            let number = next_block + index as u64;
            entry_write(number, name, piece_data, index as u64 + 1, pieces, whole_check)?;
            unsafe { NEXT_BLOCK = number + 1 };
        }
    }

    // Only now does the kernel remember the thing.
    remember(kept(), name, next_block, pieces);
    unsafe { NEXT_BLOCK = next_block + pieces };
    Ok(())
}

// Finds the thing kept under a name. Gives back its data, or nothing if no
// thing has that name. A thing in pieces comes back whole, put together.
pub fn notebook_find(name: &str) -> Result<Option<Vec<u8>>, &'static str> {
    let Some((first, pieces)) = kept().iter().find(|kept| kept.name == name).map(|kept| (kept.block, kept.pieces)) else {
        return Ok(None);
    };
    // Read the entries again, and believe them only as far as they check out
    // now: each must still be a whole entry under this name, and each piece
    // the right piece of the same thing.
    let mut block = [0u8; BLOCK_SIZE as usize];
    let mut data = Vec::new();
    let mut whole = 0;
    for index in 0..pieces {
        let place = first + index;
        part_read(place, &mut block)?;
        let Some((name_length, data_length)) = entry_read(&block, place) else {
            return Err("the entry for that name can no longer be read");
        };
        if &block[ENTRY_TEXT_AT..ENTRY_TEXT_AT + name_length] != name.as_bytes() {
            return Err("the entry for that name can no longer be read");
        }
        match piece_of(&block, data_length) {
            Piece::Whole if pieces == 1 => {}
            Piece::Part { piece, pieces: of, whole_check } if piece == index + 1 && of == pieces && (index == 0 || whole_check == whole) => {
                whole = whole_check;
            }
            _ => return Err("the entry for that name can no longer be read"),
        }
        let data_at = ENTRY_TEXT_AT + name_length;
        data.extend_from_slice(&block[data_at..data_at + data_length]);
    }
    if pieces > 1 && check_value(&data) as u64 != whole {
        return Err("the thing kept under that name can no longer be read whole");
    }
    Ok(Some(data))
}

// Gives the names of the things kept, in the order in which their newest
// whole things were kept, the oldest first.
pub fn notebook_names() -> Vec<String> {
    let mut names: Vec<(u64, String)> = kept().iter().map(|kept| (kept.block, kept.name.clone())).collect();
    // No two things begin in the same block.
    names.sort_unstable_by_key(|(block, _)| *block);
    names.into_iter().map(|(_, name)| name).collect()
}
