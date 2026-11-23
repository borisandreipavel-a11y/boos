//! The disk: finding the controller that the machine's disks are plugged
//! into, setting it up, asking the disk who it is, and reading and writing a
//! block. Notes: `docs/disk.md`.

use alloc::string::String;

use crate::frames::{FRAME_SIZE, frame_take};
use crate::page::plain_text;
use crate::page_tables::map_device_memory;
use crate::parts::WriteTicket;
use crate::pci::{PciPlace, pci_find_kind, pci_memory_address, pci_read, pci_write};
use crate::processor::{device_read_8, device_read_32, device_write_8, device_write_32};

// A disk is not on the PCI list itself. It is plugged into a controller, and
// the controller is on the list. The kernel looks for a controller for SATA
// disks that is talked to in the way called AHCI, which is what PCs have had
// for many years. These are the three numbers such a controller states about
// its kind, whoever made it.
const KIND_STORES_DATA: u8 = 0x01; // The broad kind: something that stores data.
const KIND_SATA: u8 = 0x06; // The narrow kind: a controller for SATA disks.
const WAY_AHCI: u8 = 0x01; // The way it is talked to: AHCI.

// Looks for the disk controller on the PCI list. Returns its place, or
// nothing if the machine has none of this kind.
pub fn disk_controller_find() -> Option<PciPlace> {
    pci_find_kind(KIND_STORES_DATA, KIND_SATA, WAY_AHCI)
}

// A disk keeps its data in blocks of this many bytes, numbered from 0.
pub const BLOCK_SIZE: u64 = 512;

// What the kernel knows about the disk once it is set up.
pub struct Disk {
    // Which socket of the controller the disk is plugged into.
    pub socket: u32,
    // The name the disk gives itself, such as its maker's model name.
    pub name: String,
    // How many blocks it holds.
    pub blocks: u64,
}

// The controller's controls are in memory. The first ones belong to the
// controller as a whole. These say how far from the start each one is; the
// name the AHCI specification gives it is in brackets.
const ABILITIES: u64 = 0x00; // What the controller can do (CAP).
const SWITCHES: u64 = 0x04; // Switches for the whole controller (GHC).
const SOCKETS_THERE: u64 = 0x0C; // One bit for each socket that exists (PI).
const ABILITIES_2: u64 = 0x24; // More of what it can do (CAP2).
const HANDOVER: u64 = 0x28; // Who owns the controller, the firmware or the kernel (BOHC).

const CAN_USE_HIGH_MEMORY: u32 = 1 << 31; // In ABILITIES: memory above 4 GB can be named (S64A).
const AHCI_ON: u32 = 1 << 31; // In SWITCHES: "talk to me the AHCI way" (AE). With every other bit 0, the controller sends no signals.
const CAN_HAND_OVER: u32 = 1 << 0; // In ABILITIES_2: the controller has the HANDOVER control (BOH).
const FIRMWARE_OWNS: u32 = 1 << 0; // In HANDOVER: the firmware says the controller is its own (BOS).
const KERNEL_OWNS: u32 = 1 << 1; // In HANDOVER: the kernel asks for it (OOS).
const FIRMWARE_BUSY: u32 = 1 << 4; // In HANDOVER: the firmware is still finishing its work (BB).

// A disk is plugged into a socket of the controller (the specification says
// "port"). Each socket has a set of controls of its own. The first set starts
// 0x100 bytes after the start, and each set is 0x80 bytes long.
const FIRST_SOCKET: u64 = 0x100;
const SOCKET_STEP: u64 = 0x80;
const MOST_SOCKETS: u32 = 32;

// A socket's controls, counted from the start of its set.
const COMMAND_LIST: u64 = 0x00; // Where the list of commands is, 8 bytes (PxCLB, PxCLBU).
const ANSWER_AREA: u64 = 0x08; // Where the disk's short answers are to be put, 8 bytes (PxFB, PxFBU).
const EVENTS: u64 = 0x10; // What has happened at this socket (PxIS).
const EVENT_SIGNALS: u64 = 0x14; // Which of those events send a signal (PxIE).
const SOCKET_SWITCHES: u64 = 0x18; // Switches and state of this socket (PxCMD).
const DISK_STATE: u64 = 0x20; // The disk's own state, as it last reported it (PxTFD).
const SIGNATURE: u64 = 0x24; // What kind of thing is plugged in (PxSIG).
const LINK: u64 = 0x28; // Whether something is plugged in and answering (PxSSTS).
const LINK_ERRORS: u64 = 0x30; // Errors on the cable (PxSERR).
const COMMANDS_GIVEN: u64 = 0x38; // One bit for each command that is under way (PxCI).

// Bits in SOCKET_SWITCHES.
const RUN_COMMANDS: u32 = 1 << 0; // The socket carries out the commands in its list (ST).
const TAKE_ANSWERS: u32 = 1 << 4; // The socket writes the disk's answers into the answer area (FRE).
const TAKING_ANSWERS: u32 = 1 << 14; // It is doing so right now (FR).
const RUNNING_COMMANDS: u32 = 1 << 15; // It is working through its list right now (CR).

// Bits in DISK_STATE.
const DISK_BUSY: u32 = 1 << 7; // The disk is busy (BSY).
const DISK_WANTS_DATA: u32 = 1 << 3; // The disk is in the middle of passing data (DRQ).

// In EVENTS: the disk reported that a command failed (TFES).
const COMMAND_FAILED: u32 = 1 << 30;

// The lowest 4 bits of LINK read 3 when something is plugged in and the
// connection to it is up (DET).
const LINK_UP: u32 = 3;

// What SIGNATURE reads for a hard disk. A drive for CDs and DVDs gives
// another number, and is not a disk the kernel can use.
const SIGNATURE_OF_A_DISK: u32 = 0x0000_0101;

// A command is handed to the disk as a small packet of bytes (the
// specification calls it a FIS). These are for the kind that carries a
// command from the machine to the disk.
const PACKET_TO_DISK: u8 = 0x27; // The first byte: "this packet goes from the machine to the disk".
const PACKET_IS_COMMAND: u8 = 0x80; // In the second byte: "the packet carries a new command".
const PACKET_LENGTH: u32 = 5; // The packet is 5 times 4 bytes long.
const BY_BLOCK_NUMBER: u8 = 0x40; // In the eighth byte: "the place on the disk is given as a block number".

// The command that asks a disk who it is (IDENTIFY DEVICE). The disk answers
// with one block of facts about itself, as 256 numbers of 2 bytes each.
const WHO_ARE_YOU: u8 = 0xEC;

// The command that reads blocks from a disk that counts its blocks in 48
// bits (READ DMA EXT). The packet names the block and how many to read.
const READ_BLOCKS: u8 = 0x25;

// The command that writes blocks to such a disk (WRITE DMA EXT), and the
// command that makes the disk put down for good what it was told to write
// (FLUSH CACHE EXT). A disk may keep written blocks in a store of its own
// for a while, where a power cut would lose them; this command empties that
// store onto the disk itself.
const WRITE_BLOCKS: u8 = 0x35;
const PUT_DOWN: u8 = 0xEA;

// Which way a command's block of data goes.
#[derive(Clone, Copy, PartialEq)]
enum Passing {
    FromDisk, // The disk sends a block, which lands in the data frame.
    ToDisk,   // The block in the data frame is sent to the disk.
    Nothing,  // The command has no block of data.
}

// In the first entry of the list of commands: "this command's data goes to
// the disk" (W).
const DATA_GOES_TO_DISK: u32 = 1 << 6;

// Where some of those facts stand in the answer, counted in 2-byte numbers.
const NAME_AT: usize = 27; // The disk's name: 40 letters, in 20 numbers.
const NAME_LENGTH: usize = 40;
const BLOCKS_AT: usize = 60; // How many blocks, for disks that count them in 28 bits: 2 numbers.
const FEATURES_AT: usize = 83; // A list of features, one bit each.
const FEATURES_TRUE: u16 = 0xC000; // The list may be believed if, of its two top bits,
const FEATURES_TRUE_IS: u16 = 0x4000; // only the lower one is set.
const FEATURE_LONG_COUNT: u16 = 1 << 10; // In that list: the disk counts its blocks in 48 bits.
const LONG_BLOCKS_AT: usize = 100; // How many blocks, for those disks: 4 numbers.
const BLOCK_SIZE_AT: usize = 106; // Whether the disk's blocks have another size than 512 bytes.
const BLOCK_SIZE_STATED: u16 = 0xD000; // They have if, of these three bits,
const BLOCK_SIZE_STATED_IS: u16 = 0x5000; // exactly these two are set.
const BLOCK_SIZE_IS_AT: usize = 117; // Then this is the size, counted in 2-byte numbers: 2 numbers.

// Waiting for a device is done by looking again and again. This is how often
// the kernel looks before it gives up.
const PATIENCE: u32 = 3_000_000;

// The kernel lends the controller one frame, laid out like this: the list of
// commands at its start (1024 bytes), the answer area 1024 bytes in (256
// bytes), and the one command the kernel uses 2048 bytes in. A second frame
// takes the data a command reads from the disk.
const ANSWER_AREA_IN_FRAME: u64 = 0x400;
const COMMAND_IN_FRAME: u64 = 0x800;

// A command, as it lies in the frame: the packet for the disk comes first,
// and 0x80 bytes in stands the list of places for the data.
const DATA_PLACES_IN_COMMAND: u64 = 0x80;

// Where the chosen socket's controls are, and the two frames. `disk_setup`
// sets them once, at its very end, when the disk is ready. They stay 0 until
// then, and for good if the setup fails.
static mut SOCKET_CONTROLS: u64 = 0;
static mut WORK_FRAME: u64 = 0;
static mut DATA_FRAME: u64 = 0;

// What the disk said about itself: how many blocks it holds, and whether it
// counts them in 48 bits. Set together with the three above.
static mut DISK_BLOCKS: u64 = 0;
static mut DISK_COUNTS_LONG: bool = false;

// Looks at a control again and again until the bits picked out by `mask`
// read as `wanted`. Says whether that happened before the patience ran out.
fn wait_until(control: u64, mask: u32, wanted: u32) -> bool {
    for _ in 0..PATIENCE {
        if device_read_32(control) & mask == wanted {
            return true;
        }
    }
    false
}

// Writes an 8-byte address into a control or into a frame, as two halves
// of 4 bytes, the lower half first.
fn write_address(place: u64, address: u64) {
    device_write_32(place, address as u32);
    device_write_32(place + 4, (address >> 32) as u32);
}

// Takes a frame and fills it with zeros.
fn empty_frame() -> u64 {
    let frame = frame_take();
    unsafe { core::ptr::write_bytes(frame as *mut u8, 0, FRAME_SIZE as usize) };
    frame
}

// Sets the controller up, finds the first disk plugged into it, and asks
// that disk who it is. Nothing is written to any disk. If something goes
// wrong, the reason comes back in words.
pub fn disk_setup(place: PciPlace) -> Result<Disk, &'static str> {
    // Three settings in the controller's PCI facts, as for the network card:
    // it may use its memory (bit 1), it may read and write the machine's
    // memory (bit 2), and it sends no signals of its own (bit 10).
    let settings = pci_read(place, 4) & 0xFFFF;
    pci_write(place, 4, settings | 0x0406);

    // The controller's controls are in memory, at the address in the sixth
    // of its address fields. Make sure that memory can be reached: every
    // set of socket controls there may be, and the controller's own.
    let controls = pci_memory_address(place, 5);
    if controls == 0 {
        return Err("the controller does not say where its controls are");
    }
    map_device_memory(controls, FIRST_SOCKET + MOST_SOCKETS as u64 * SOCKET_STEP);

    // "Talk to me the AHCI way." It must be said before anything else. The
    // same write leaves the controller's signals switched off: the kernel
    // looks at the controller itself and wants no signals from it.
    device_write_32(controls + SWITCHES, AHCI_ON);

    // The firmware may still count the controller as its own. Ask for it,
    // and wait until the firmware has let go and finished its work.
    if device_read_32(controls + ABILITIES_2) & CAN_HAND_OVER != 0 {
        let handover = controls + HANDOVER;
        device_write_32(handover, device_read_32(handover) | KERNEL_OWNS);
        if !wait_until(handover, FIRMWARE_OWNS | FIRMWARE_BUSY, 0) {
            return Err("the firmware did not hand the controller over");
        }
    }

    // Go through the sockets that exist and take the first one with a disk
    // in it. A socket with nothing in it, or with something that is not a
    // disk, such as a drive for CDs, is passed over and left untouched.
    let sockets_there = device_read_32(controls + SOCKETS_THERE);
    let mut found = None;
    for number in 0..MOST_SOCKETS {
        if sockets_there & (1 << number) == 0 {
            continue;
        }
        let socket = controls + FIRST_SOCKET + number as u64 * SOCKET_STEP;
        let plugged_in = device_read_32(socket + LINK) & 0xF == LINK_UP;
        if plugged_in && device_read_32(socket + SIGNATURE) == SIGNATURE_OF_A_DISK {
            found = Some((number, socket));
            break;
        }
    }
    let Some((number, socket)) = found else {
        return Err("no disk is plugged into the controller");
    };

    // The firmware may have left the socket at work, with its own memory
    // named in it. Stop it: first the carrying out of commands, then the
    // taking of answers. Each stops a moment after its switch is put off.
    let switches = socket + SOCKET_SWITCHES;
    device_write_32(switches, device_read_32(switches) & !RUN_COMMANDS);
    if !wait_until(switches, RUNNING_COMMANDS, 0) {
        return Err("the disk's socket did not stop carrying out commands");
    }
    device_write_32(switches, device_read_32(switches) & !TAKE_ANSWERS);
    if !wait_until(switches, TAKING_ANSWERS, 0) {
        return Err("the disk's socket did not stop taking answers");
    }

    // Lend the controller its two frames. A controller that cannot name
    // memory above 4 GB must not be given a frame from up there.
    let work = empty_frame();
    let data = empty_frame();
    let can_use_high_memory = device_read_32(controls + ABILITIES) & CAN_USE_HIGH_MEMORY != 0;
    if !can_use_high_memory && (work >> 32 != 0 || data >> 32 != 0) {
        return Err("the controller cannot reach the memory the kernel has for it");
    }

    // Tell the socket where its list of commands and its answer area are,
    // and let it take answers again. Then wipe the notes of old errors and
    // old events (writing a 1 to such a bit clears it), and have no event
    // send a signal.
    write_address(socket + COMMAND_LIST, work);
    write_address(socket + ANSWER_AREA, work + ANSWER_AREA_IN_FRAME);
    device_write_32(switches, device_read_32(switches) | TAKE_ANSWERS);
    device_write_32(socket + LINK_ERRORS, 0xFFFF_FFFF);
    device_write_32(socket + EVENTS, 0xFFFF_FFFF);
    device_write_32(socket + EVENT_SIGNALS, 0);

    // The socket may carry out commands only once the disk is neither busy
    // nor in the middle of passing data.
    if !wait_until(socket + DISK_STATE, DISK_BUSY | DISK_WANTS_DATA, 0) {
        return Err("the disk stayed busy");
    }
    device_write_32(switches, device_read_32(switches) | RUN_COMMANDS);

    // Ask the disk who it is, and read its answer. The answer comes from
    // outside the kernel, so a count of blocks that cannot be true is not
    // believed: none at all, or more than 48 bits can count.
    disk_command(socket, work, data, WHO_ARE_YOU, None, 1, Passing::FromDisk)?;
    let (name, blocks, counts_long) = disk_facts(data)?;
    if blocks == 0 || blocks >> 48 != 0 {
        return Err("the disk gave a number of blocks that cannot be true");
    }

    // Only now, with everything in place, remember the socket, the frames
    // and what the disk said, for later use.
    unsafe {
        SOCKET_CONTROLS = socket;
        WORK_FRAME = work;
        DATA_FRAME = data;
        DISK_BLOCKS = blocks;
        DISK_COUNTS_LONG = counts_long;
    }
    Ok(Disk { socket: number, name, blocks })
}

// Reads one block from the disk into `into`. Blocks are numbered from 0.
// Nothing on the disk is changed. Today only the startup code calls this;
// nothing protects it against two tasks using the disk at once.
pub fn disk_read(block: u64, into: &mut [u8; BLOCK_SIZE as usize]) -> Result<(), &'static str> {
    let (socket, work, data) = unsafe { (SOCKET_CONTROLS, WORK_FRAME, DATA_FRAME) };
    if socket == 0 {
        return Err("the disk is not ready");
    }
    // A block the disk does not have is not asked for at all.
    if block >= unsafe { DISK_BLOCKS } {
        return Err("the disk has no block with that number");
    }
    // The command the kernel knows names a block in 48 bits. A disk that
    // counts in fewer does not know that command.
    if !unsafe { DISK_COUNTS_LONG } {
        return Err("the disk is of an older kind that the kernel cannot read");
    }

    disk_command(socket, work, data, READ_BLOCKS, Some(block), 1, Passing::FromDisk)?;

    // The block is in the data frame now. Copy it out.
    for (place, byte) in into.iter_mut().enumerate() {
        *byte = device_read_8(data + place as u64);
    }
    Ok(())
}

// Writes one block to the disk, and has the disk put it down for good.
//
// Writing asks for a ticket, and only the file `parts.rs` can make one. So
// no other code can write to the disk by a block's own number: everything
// that is written goes through `part_write` there, which keeps it inside
// the kernel's own part.
pub fn disk_write(_ticket: &WriteTicket, block: u64, from: &[u8; BLOCK_SIZE as usize]) -> Result<(), &'static str> {
    let (socket, work, data) = unsafe { (SOCKET_CONTROLS, WORK_FRAME, DATA_FRAME) };
    if socket == 0 {
        return Err("the disk is not ready");
    }
    // The same two refusals as for reading.
    if block >= unsafe { DISK_BLOCKS } {
        return Err("the disk has no block with that number");
    }
    if !unsafe { DISK_COUNTS_LONG } {
        return Err("the disk is of an older kind that the kernel cannot write");
    }

    // Put the block into the data frame, from where the disk takes it.
    for (place, byte) in from.iter().enumerate() {
        device_write_8(data + place as u64, *byte);
    }
    disk_command(socket, work, data, WRITE_BLOCKS, Some(block), 1, Passing::ToDisk)?;
    disk_command(socket, work, data, PUT_DOWN, None, 1, Passing::Nothing)
}

// How many blocks one command moves at most: as many as the data frame holds.
pub const BLOCKS_AT_ONCE: usize = (FRAME_SIZE / BLOCK_SIZE) as usize;

// The checks that a run of blocks starting at `block` is one the disk has,
// that it is from 1 to `BLOCKS_AT_ONCE` whole blocks long, and that the disk
// is ready and of the kind the kernel can use. Gives back how many blocks it
// is and where the socket and the two frames are.
fn run_checked(block: u64, bytes: usize) -> Result<(u32, u64, u64, u64), &'static str> {
    let (socket, work, data) = unsafe { (SOCKET_CONTROLS, WORK_FRAME, DATA_FRAME) };
    if socket == 0 {
        return Err("the disk is not ready");
    }
    if bytes == 0 || bytes % BLOCK_SIZE as usize != 0 || bytes / BLOCK_SIZE as usize > BLOCKS_AT_ONCE {
        return Err("a run of blocks must be from one to eight whole blocks");
    }
    let count = (bytes / BLOCK_SIZE as usize) as u32;
    if block >= unsafe { DISK_BLOCKS } || count as u64 > unsafe { DISK_BLOCKS } - block {
        return Err("the disk has no block with that number");
    }
    if !unsafe { DISK_COUNTS_LONG } {
        return Err("the disk is of an older kind that the kernel cannot use");
    }
    Ok((count, socket, work, data))
}

// Reads a run of up to `BLOCKS_AT_ONCE` neighbouring blocks with one command,
// from `block` on, into `into`, whose length is a whole number of blocks.
pub fn disk_read_blocks(block: u64, into: &mut [u8]) -> Result<(), &'static str> {
    let (count, socket, work, data) = run_checked(block, into.len())?;
    disk_command(socket, work, data, READ_BLOCKS, Some(block), count, Passing::FromDisk)?;
    for (place, byte) in into.iter_mut().enumerate() {
        *byte = device_read_8(data + place as u64);
    }
    Ok(())
}

// Writes a run of up to `BLOCKS_AT_ONCE` neighbouring blocks with one command,
// from `block` on. Unlike `disk_write`, it does not have the disk put them
// down for good: whoever writes a run of runs asks for that once, at the end,
// with `disk_put_down`. The same ticket as for `disk_write` is asked for.
pub fn disk_write_blocks(_ticket: &WriteTicket, block: u64, from: &[u8]) -> Result<(), &'static str> {
    let (count, socket, work, data) = run_checked(block, from.len())?;
    for (place, byte) in from.iter().enumerate() {
        device_write_8(data + place as u64, *byte);
    }
    disk_command(socket, work, data, WRITE_BLOCKS, Some(block), count, Passing::ToDisk)
}

// Has the disk put down for good everything it was told to write.
pub fn disk_put_down(_ticket: &WriteTicket) -> Result<(), &'static str> {
    let (socket, work, data) = unsafe { (SOCKET_CONTROLS, WORK_FRAME, DATA_FRAME) };
    if socket == 0 {
        return Err("the disk is not ready");
    }
    disk_command(socket, work, data, PUT_DOWN, None, 1, Passing::Nothing)
}

// Gives the text a block begins with: its bytes up to the first 0, at most
// `longest` of them. The bytes come from outside the kernel, so every one
// that is not a plain sign becomes a dot.
pub fn block_text(block: &[u8], longest: usize) -> String {
    let mut text = String::new();
    for byte in block.iter().take(longest) {
        match *byte {
            0 => break,
            b' '..=b'~' => text.push(*byte as char),
            _ => text.push('.'),
        }
    }
    text
}

// Gets a socket going again after a command has gone wrong: stop it, wipe
// the notes of the error, start it. A socket that has stopped over a failure
// takes no new command until this is done.
fn socket_restart(socket: u64) {
    let switches = socket + SOCKET_SWITCHES;
    device_write_32(switches, device_read_32(switches) & !RUN_COMMANDS);
    if !wait_until(switches, RUNNING_COMMANDS, 0) {
        return;
    }
    device_write_32(socket + LINK_ERRORS, 0xFFFF_FFFF);
    device_write_32(socket + EVENTS, 0xFFFF_FFFF);
    // A disk that is still busy would need a harder push, which the kernel
    // does not know how to give. The socket then stays stopped, and the next
    // command says so.
    if device_read_32(socket + DISK_STATE) & (DISK_BUSY | DISK_WANTS_DATA) != 0 {
        return;
    }
    device_write_32(switches, device_read_32(switches) | RUN_COMMANDS);
}

// Hands the disk one command and waits until the disk has finished it.
// `socket` is where the socket's controls are, `work` and `data` are the two
// frames. A command that is about a block of the disk names it in `block`,
// `count` how many neighbouring blocks it is about (at most as many as the
// data frame holds), and `passing` says which way the command's blocks of data
// go, if it has any.
fn disk_command(socket: u64, work: u64, data: u64, command: u8, block: Option<u64>, count: u32, passing: Passing) -> Result<(), &'static str> {
    let command_place = work + COMMAND_IN_FRAME;

    // A socket takes commands only while it is switched to carry them out.
    if device_read_32(socket + SOCKET_SWITCHES) & RUN_COMMANDS == 0 {
        return Err("the disk's socket is stopped");
    }

    // Wipe the notes of earlier events, so that an old failure is not taken
    // for a failure of this command. Before a command that reads, wipe the
    // place for the data as well, so that what an earlier command left there
    // cannot be taken for this one's answer. Before a command that writes,
    // the data frame holds the block to be written, and must stay as it is.
    device_write_32(socket + EVENTS, 0xFFFF_FFFF);
    if passing == Passing::FromDisk {
        unsafe { core::ptr::write_bytes(data as *mut u8, 0, count as usize * BLOCK_SIZE as usize) };
    }

    // The packet for the disk, 20 bytes. Start from zeros, so that nothing
    // of an earlier command is left in it. Then: what kind of packet it is,
    // that it carries a command, and the command.
    for byte in 0..PACKET_LENGTH as u64 * 4 {
        device_write_8(command_place + byte, 0);
    }
    device_write_8(command_place, PACKET_TO_DISK);
    device_write_8(command_place + 1, PACKET_IS_COMMAND);
    device_write_8(command_place + 2, command);

    // The block the command is about: its number in six bytes, the lowest
    // part first, with the eighth byte of the packet in between, which says
    // that a block number is meant. Then how many blocks.
    if let Some(block) = block {
        device_write_8(command_place + 4, block as u8);
        device_write_8(command_place + 5, (block >> 8) as u8);
        device_write_8(command_place + 6, (block >> 16) as u8);
        device_write_8(command_place + 7, BY_BLOCK_NUMBER);
        device_write_8(command_place + 8, (block >> 24) as u8);
        device_write_8(command_place + 9, (block >> 32) as u8);
        device_write_8(command_place + 10, (block >> 40) as u8);
        device_write_8(command_place + 12, count as u8);
    }

    // One place for the data: the data frame, and how many bytes may go
    // there. The count is written as one less than it is.
    let data_place = command_place + DATA_PLACES_IN_COMMAND;
    write_address(data_place, data);
    device_write_32(data_place + 12, count * BLOCK_SIZE as u32 - 1);

    // The first entry of the list of commands describes this command: how
    // long its packet is (in the lowest 5 bits), how many places for data it
    // has (in the upper half: one, or none for a command without data),
    // whether its data goes to the disk, and where the command lies.
    let description = match passing {
        Passing::FromDisk => PACKET_LENGTH | 1 << 16,
        Passing::ToDisk => PACKET_LENGTH | 1 << 16 | DATA_GOES_TO_DISK,
        Passing::Nothing => PACKET_LENGTH,
    };
    device_write_32(work, description);
    device_write_32(work + 4, 0);
    write_address(work + 8, command_place);

    // "Command number 0 is ready." The socket clears the bit again when the
    // disk has finished the command.
    device_write_32(socket + COMMANDS_GIVEN, 1);
    for _ in 0..PATIENCE {
        if device_read_32(socket + EVENTS) & COMMAND_FAILED != 0 {
            socket_restart(socket);
            return Err("the disk reported that it could not do what was asked");
        }
        if device_read_32(socket + COMMANDS_GIVEN) & 1 == 0 {
            // The command is finished. The controller has written into the
            // second 4 bytes of the entry how many bytes of data it passed
            // on. For a command with data, only all of its blocks count.
            if passing != Passing::Nothing && device_read_32(work + 4) != count * BLOCK_SIZE as u32 {
                return Err("the disk finished the command without passing a whole block");
            }
            return Ok(());
        }
    }
    socket_restart(socket);
    Err("the disk did not answer in time")
}

// Reads the 2-byte number at place `number` of the disk's answer in the data
// frame. The lower byte comes first.
fn fact(data: u64, number: usize) -> u16 {
    let place = data + number as u64 * 2;
    device_read_8(place) as u16 | (device_read_8(place + 1) as u16) << 8
}

// Picks out of the disk's answer to "who are you": its name, its number of
// blocks, and whether it counts its blocks in 48 bits. A disk whose blocks
// are not 512 bytes long is refused, because the kernel reckons with 512.
fn disk_facts(data: u64) -> Result<(String, u64, bool), &'static str> {
    // The name is 40 letters, two in each number, the first of the two in
    // the number's upper byte. It is filled up with spaces at the end. The
    // text comes from outside the kernel, so it is cleaned before use.
    let mut letters = String::new();
    for number in 0..NAME_LENGTH / 2 {
        let pair = fact(data, NAME_AT + number);
        letters.push((pair >> 8) as u8 as char);
        letters.push(pair as u8 as char);
    }
    let name = plain_text(letters.trim(), NAME_LENGTH);

    // A disk whose blocks have another size says so, and gives the size in
    // 2-byte numbers: 256 of them make the usual 512 bytes.
    if fact(data, BLOCK_SIZE_AT) & BLOCK_SIZE_STATED == BLOCK_SIZE_STATED_IS {
        let size = fact(data, BLOCK_SIZE_IS_AT) as u64 | (fact(data, BLOCK_SIZE_IS_AT + 1) as u64) << 16;
        if size * 2 != BLOCK_SIZE {
            return Err("the disk's blocks are not 512 bytes long");
        }
    }

    // A disk that counts its blocks in 48 bits says so in its list of
    // features, and gives the count in 4 numbers. An older or small one
    // gives it in 2. The list is believed only if its two top bits read as
    // they must, and the long count only if it is not 0.
    let features = fact(data, FEATURES_AT);
    let long_count = fact(data, LONG_BLOCKS_AT) as u64
        | (fact(data, LONG_BLOCKS_AT + 1) as u64) << 16
        | (fact(data, LONG_BLOCKS_AT + 2) as u64) << 32
        | (fact(data, LONG_BLOCKS_AT + 3) as u64) << 48;
    let counts_long = features & FEATURES_TRUE == FEATURES_TRUE_IS && features & FEATURE_LONG_COUNT != 0 && long_count != 0;
    let blocks = if counts_long { long_count } else { fact(data, BLOCKS_AT) as u64 | (fact(data, BLOCKS_AT + 1) as u64) << 16 };
    Ok((name, blocks, counts_long))
}
