//! The parts of the disk: reading the list at the disk's start that says how
//! the disk is divided, and finding the part that is this kernel's own.
//! Notes: `docs/disk.md`.

use alloc::vec::Vec;

use crate::disk::{BLOCK_SIZE, disk_read};

// A PC's disk is divided into parts (the usual word is "partitions"), and a
// list at the start of the disk says where each part begins and ends and
// what kind of part it is. The kernel keeps its things in one part only, the
// one whose kind is the number below. It was made up once, at random, for
// this kernel: 261e771e-cc8b-4a7f-96d1-b57fd92eafea. These are its 16 bytes
// as they stand on a disk, where the first three groups are written with
// their lowest byte first.
const OWN_KIND: [u8; 16] = [0x1e, 0x77, 0x1e, 0x26, 0x8b, 0xcc, 0x7f, 0x4a, 0x96, 0xd1, 0xb5, 0x7f, 0xd9, 0x2e, 0xaf, 0xea];

// Block 0 holds an old-style list of four entries, 16 bytes each, starting
// 446 bytes in. On a disk divided the newer way, one of them has this kind
// and says that it begins at block 1.
const OLD_LIST_AT: usize = 446;
const OLD_ENTRY_SIZE: usize = 16;
const OLD_KIND_AT: usize = 4; // Where an old-style entry states its kind,
const OLD_FIRST_AT: usize = 8; // and where its first block.
const OLD_KIND_NEWER_WAY: u8 = 0xEE; // The kind that says "divided the newer way".

// Block 1 holds the head of the list. These say how far into it each fact
// stands; the name the UEFI specification gives it is in brackets.
const HEAD_BLOCK: u64 = 1;
const HEAD_SIGNATURE: [u8; 8] = *b"EFI PART"; // The first 8 bytes of every such head.
const HEAD_VERSION_AT: usize = 8; // The version of the list (Revision).
const HEAD_VERSION: u32 = 0x0001_0000; // Version 1.0, the only one there is.
const HEAD_SIZE_AT: usize = 12; // How many bytes long the head is (HeaderSize).
const HEAD_SIZE_LEAST: usize = 92;
const HEAD_CHECK_AT: usize = 16; // The head's check value (CRC32).
const HEAD_OWN_BLOCK_AT: usize = 24; // The block the head says it lies in (MyLBA).
const HEAD_OTHER_COPY_AT: usize = 32; // The block where the head of the list's second copy lies (AlternateLBA).
const HEAD_FIRST_USABLE_AT: usize = 40; // The first block a part may use (FirstUsableLBA),
const HEAD_LAST_USABLE_AT: usize = 48; // and the last (LastUsableLBA).
const HEAD_ENTRIES_AT: usize = 72; // The block where the entries begin (PartitionEntryLBA).
const HEAD_ENTRY_COUNT_AT: usize = 80; // How many entries there are (NumberOfPartitionEntries),
const HEAD_ENTRY_SIZE_AT: usize = 84; // how many bytes each is long (SizeOfPartitionEntry),
const HEAD_ENTRIES_CHECK_AT: usize = 88; // and the check value of all of them (PartitionEntryArrayCRC32).

// An entry describes one part. These say how far into an entry each fact
// stands.
const ENTRY_SIZE_LEAST: usize = 128;
const ENTRY_KIND_AT: usize = 0; // The part's kind, 16 bytes. All zeros: the entry is not in use.
const ENTRY_FIRST_AT: usize = 32; // The part's first block,
const ENTRY_LAST_AT: usize = 40; // and its last.

// The most the kernel is prepared to read for the entries. The usual list
// has 128 entries of 128 bytes, 16 KB. A list that claims more than this is
// not read at all, so that a damaged head cannot make the kernel read, or
// ask the heap for, some enormous amount.
const ENTRIES_MOST: u64 = 128 * 1024;

// The kernel's own part: the block of the disk it begins at, and how many
// blocks it is long. Both stay 0 until `part_find` has found it.
static mut PART_FIRST: u64 = 0;
static mut PART_BLOCKS: u64 = 0;

// Where the kernel's own part is.
pub struct Part {
    // The block of the disk it begins at, and the block it ends at.
    pub first: u64,
    pub last: u64,
    // How many blocks it is long.
    pub blocks: u64,
}

// Reads a number of 4 bytes out of a list of bytes, lowest byte first.
fn number_32(bytes: &[u8], at: usize) -> u32 {
    bytes[at] as u32 | (bytes[at + 1] as u32) << 8 | (bytes[at + 2] as u32) << 16 | (bytes[at + 3] as u32) << 24
}

// The same for a number of 8 bytes.
fn number_64(bytes: &[u8], at: usize) -> u64 {
    number_32(bytes, at) as u64 | (number_32(bytes, at + 4) as u64) << 32
}

// Works out the check value of some bytes (CRC-32, the kind the list uses).
// Whoever wrote the list worked out the same value and stored it. If a byte
// has changed since, the two no longer agree.
fn check_value(bytes: &[u8]) -> u32 {
    let mut check: u32 = 0xFFFF_FFFF;
    for byte in bytes {
        check ^= *byte as u32;
        for _ in 0..8 {
            check = if check & 1 != 0 { (check >> 1) ^ 0xEDB8_8320 } else { check >> 1 };
        }
    }
    !check
}

// Reads the disk's list of parts and finds the part that is this kernel's
// own. `disk_blocks` is how many blocks the disk holds. Nothing is written.
//
// Everything in the list comes from outside the kernel, and the next step,
// writing, will trust what is found here. So nothing is taken on trust: the
// list must be whole, and the part must lie where a part may lie and must
// not share a block with any other part.
pub fn part_find(disk_blocks: u64) -> Result<Part, &'static str> {
    let mut block = [0u8; BLOCK_SIZE as usize];

    // Block 0: is this disk divided the newer way at all?
    disk_read(0, &mut block)?;
    let mut divided = false;
    for entry in 0..4 {
        let at = OLD_LIST_AT + entry * OLD_ENTRY_SIZE;
        if block[at + OLD_KIND_AT] == OLD_KIND_NEWER_WAY && number_32(&block, at + OLD_FIRST_AT) == 1 {
            divided = true;
        }
    }
    if !divided {
        return Err("it has no list of parts");
    }

    // Block 1: the head of the list. It must begin with its signature, be
    // of the version the kernel knows, be at least as long as a head is and
    // no longer than a block, and say that it lies in block 1.
    disk_read(HEAD_BLOCK, &mut block)?;
    let head_size = number_32(&block, HEAD_SIZE_AT) as usize;
    if block[..8] != HEAD_SIGNATURE
        || number_32(&block, HEAD_VERSION_AT) != HEAD_VERSION
        || head_size < HEAD_SIZE_LEAST
        || head_size > BLOCK_SIZE as usize
        || number_64(&block, HEAD_OWN_BLOCK_AT) != HEAD_BLOCK
    {
        return Err("the head of its list of parts is not as it must be");
    }

    // The head's check value is worked out over the head with the place for
    // the value itself holding zeros.
    let stored_check = number_32(&block, HEAD_CHECK_AT);
    let mut head = block;
    head[HEAD_CHECK_AT..HEAD_CHECK_AT + 4].fill(0);
    if check_value(&head[..head_size]) != stored_check {
        return Err("the head of its list of parts is damaged");
    }

    // What the head says about the entries and about where parts may lie.
    let other_copy = number_64(&block, HEAD_OTHER_COPY_AT);
    let first_usable = number_64(&block, HEAD_FIRST_USABLE_AT);
    let last_usable = number_64(&block, HEAD_LAST_USABLE_AT);
    let entries_at = number_64(&block, HEAD_ENTRIES_AT);
    let entry_count = number_32(&block, HEAD_ENTRY_COUNT_AT) as u64;
    let entry_size = number_32(&block, HEAD_ENTRY_SIZE_AT) as u64;
    let entries_check = number_32(&block, HEAD_ENTRIES_CHECK_AT);

    // An entry is 128 bytes long or that doubled some number of times. (A
    // number is doubled 128 if, of its bits, exactly one is set.)
    if entry_count == 0 || entry_size < ENTRY_SIZE_LEAST as u64 || entry_size.count_ones() != 1 {
        return Err("the head of its list of parts is not as it must be");
    }
    // Both numbers are below 2 to the 32, so their product fits.
    let entries_length = entry_count * entry_size;
    if entries_length > ENTRIES_MOST {
        return Err("its list of parts is longer than the kernel is prepared to read");
    }
    // The blocks a part may use, the blocks of the entries, and the block of
    // the second copy's head must all be blocks the disk has.
    let entries_blocks = entries_length.div_ceil(BLOCK_SIZE);
    if first_usable > last_usable
        || last_usable >= disk_blocks
        || entries_at <= HEAD_BLOCK
        || entries_at >= disk_blocks
        || entries_blocks > disk_blocks - entries_at
        || other_copy >= disk_blocks
    {
        return Err("the head of its list of parts names blocks the disk does not have");
    }

    // The head's check value shows that the head was not changed by
    // accident. It does not show that whoever wrote the list wrote it
    // right. A part is checked against the usable blocks further down, so
    // the usable blocks themselves must not lie on the list: not on its
    // entries, which end one block before `entries_end`, and not on its
    // second copy, whose own entries lie just in front of its head.
    let entries_end = entries_at + entries_blocks;
    let on_the_entries = first_usable < entries_end && entries_at <= last_usable;
    let on_the_second_copy = other_copy <= last_usable || other_copy - last_usable <= entries_blocks;
    if on_the_entries || on_the_second_copy {
        return Err("the head of its list of parts lets a part lie on the list itself");
    }

    // Read the entries, block by block, and see that their check value is
    // the one the head states.
    let mut entries: Vec<u8> = Vec::with_capacity((entries_blocks * BLOCK_SIZE) as usize);
    for number in 0..entries_blocks {
        disk_read(entries_at + number, &mut block)?;
        entries.extend_from_slice(&block);
    }
    entries.truncate(entries_length as usize);
    if check_value(&entries) != entries_check {
        return Err("the entries of its list of parts are damaged");
    }

    // Go through the entries. An entry whose kind is all zeros is not in
    // use. Of the others, note the one that is this kernel's own.
    let mut own: Option<(u64, u64)> = None;
    for entry in entries.chunks(entry_size as usize) {
        let kind = &entry[ENTRY_KIND_AT..ENTRY_KIND_AT + 16];
        if kind == OWN_KIND {
            // Two parts of the kernel's kind: which is meant cannot be known.
            if own.is_some() {
                return Err("its list of parts names more than one part as mine");
            }
            own = Some((number_64(entry, ENTRY_FIRST_AT), number_64(entry, ENTRY_LAST_AT)));
        }
    }
    let Some((first, last)) = own else {
        return Err("its list of parts names no part as mine");
    };

    // The part must lie where the head says parts may lie.
    if first > last || first < first_usable || last > last_usable {
        return Err("the part named as mine does not lie where a part may lie");
    }

    // And it must not share a block with any other part in use. Two parts
    // share a block if each begins before the other ends.
    let mut own_seen = false;
    for entry in entries.chunks(entry_size as usize) {
        let kind = &entry[ENTRY_KIND_AT..ENTRY_KIND_AT + 16];
        if kind.iter().all(|byte| *byte == 0) {
            continue;
        }
        // Pass over the kernel's own entry itself, once.
        if kind == OWN_KIND && !own_seen {
            own_seen = true;
            continue;
        }
        let other_first = number_64(entry, ENTRY_FIRST_AT);
        let other_last = number_64(entry, ENTRY_LAST_AT);
        if other_first <= last && first <= other_last {
            return Err("the part named as mine shares blocks with another part");
        }
    }

    // `last` is below the disk's number of blocks and `first` is not above
    // `last`, so this sum cannot overflow.
    let blocks = last - first + 1;
    unsafe {
        PART_FIRST = first;
        PART_BLOCKS = blocks;
    }
    Ok(Part { first, last, blocks })
}

// Reads one block of the kernel's own part into `into`. Blocks are numbered
// from 0 at the part's beginning. This is the one place where "block of my
// part" becomes a block of the disk, and a number past the part's end is
// refused here, so that nothing outside the part can be reached through it.
pub fn part_read(block: u64, into: &mut [u8; BLOCK_SIZE as usize]) -> Result<(), &'static str> {
    let (first, blocks) = unsafe { (PART_FIRST, PART_BLOCKS) };
    if blocks == 0 {
        return Err("the kernel has no part of its own on the disk");
    }
    if block >= blocks {
        return Err("my part has no block with that number");
    }
    disk_read(first + block, into)
}
