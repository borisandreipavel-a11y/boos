//! The disk: finding the controller that the machine's disks are plugged
//! into, setting it up, and asking the disk who it is. Notes: `docs/disk.md`.

use alloc::string::String;

use crate::frames::{FRAME_SIZE, frame_take};
use crate::page::plain_text;
use crate::page_tables::map_device_memory;
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

// The command that asks a disk who it is (IDENTIFY DEVICE). The disk answers
// with one block of facts about itself, as 256 numbers of 2 bytes each.
const WHO_ARE_YOU: u8 = 0xEC;

// Where some of those facts stand in the answer, counted in 2-byte numbers.
const NAME_AT: usize = 27; // The disk's name: 40 letters, in 20 numbers.
const NAME_LENGTH: usize = 40;
const BLOCKS_AT: usize = 60; // How many blocks, for disks that count them in 28 bits: 2 numbers.
const FEATURES_AT: usize = 83; // A list of features, one bit each.
const FEATURE_LONG_COUNT: u16 = 1 << 10; // In that list: the disk counts its blocks in 48 bits.
const LONG_BLOCKS_AT: usize = 100; // How many blocks, for those disks: 4 numbers.

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
    disk_command(socket, work, data, WHO_ARE_YOU)?;
    let (name, blocks) = disk_facts(data);
    if blocks == 0 || blocks >> 48 != 0 {
        return Err("the disk gave a number of blocks that cannot be true");
    }

    // Only now, with everything in place, remember the socket and the
    // frames for later use.
    unsafe {
        SOCKET_CONTROLS = socket;
        WORK_FRAME = work;
        DATA_FRAME = data;
    }
    Ok(Disk { socket: number, name, blocks })
}

// Hands the disk one command that makes it send back one block of data, and
// waits until the data is in the data frame. `socket` is where the socket's
// controls are, `work` and `data` are the two frames.
fn disk_command(socket: u64, work: u64, data: u64, command: u8) -> Result<(), &'static str> {
    let command_place = work + COMMAND_IN_FRAME;

    // Wipe the notes of earlier events, so that an old failure is not taken
    // for a failure of this command.
    device_write_32(socket + EVENTS, 0xFFFF_FFFF);

    // The packet for the disk: what kind of packet it is, that it carries a
    // command, and the command. The frame was filled with zeros, and every
    // other byte of the packet stays 0.
    device_write_8(command_place, PACKET_TO_DISK);
    device_write_8(command_place + 1, PACKET_IS_COMMAND);
    device_write_8(command_place + 2, command);

    // One place for the data: the data frame, and how many bytes may go
    // there. The count is written as one less than it is.
    let data_place = command_place + DATA_PLACES_IN_COMMAND;
    write_address(data_place, data);
    device_write_32(data_place + 12, BLOCK_SIZE as u32 - 1);

    // The first entry of the list of commands describes this command: how
    // long its packet is (in the lowest 5 bits), that it has one place for
    // data (in the upper half), and where the command lies. The bit that
    // would say "data goes to the disk" stays 0: this command only reads.
    device_write_32(work, PACKET_LENGTH | 1 << 16);
    device_write_32(work + 4, 0);
    write_address(work + 8, command_place);

    // "Command number 0 is ready." The socket clears the bit again when the
    // disk has finished the command.
    device_write_32(socket + COMMANDS_GIVEN, 1);
    for _ in 0..PATIENCE {
        if device_read_32(socket + EVENTS) & COMMAND_FAILED != 0 {
            return Err("the disk reported that it could not do what was asked");
        }
        if device_read_32(socket + COMMANDS_GIVEN) & 1 == 0 {
            // The command is finished. The controller has written into the
            // second 4 bytes of the entry how many bytes of data it passed
            // on. Only a whole block counts as an answer.
            if device_read_32(work + 4) != BLOCK_SIZE as u32 {
                return Err("the disk finished the command without sending a whole block");
            }
            return Ok(());
        }
    }
    Err("the disk did not answer in time")
}

// Reads the 2-byte number at place `number` of the disk's answer in the data
// frame. The lower byte comes first.
fn fact(data: u64, number: usize) -> u16 {
    let place = data + number as u64 * 2;
    device_read_8(place) as u16 | (device_read_8(place + 1) as u16) << 8
}

// Picks the disk's name and its number of blocks out of its answer to "who
// are you".
fn disk_facts(data: u64) -> (String, u64) {
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

    // A disk that counts its blocks in 48 bits says so in its list of
    // features, and gives the count in 4 numbers. An older or small one
    // gives it in 2.
    let blocks = if fact(data, FEATURES_AT) & FEATURE_LONG_COUNT != 0 {
        fact(data, LONG_BLOCKS_AT) as u64
            | (fact(data, LONG_BLOCKS_AT + 1) as u64) << 16
            | (fact(data, LONG_BLOCKS_AT + 2) as u64) << 32
            | (fact(data, LONG_BLOCKS_AT + 3) as u64) << 48
    } else {
        fact(data, BLOCKS_AT) as u64 | (fact(data, BLOCKS_AT + 1) as u64) << 16
    };
    (name, blocks)
}
