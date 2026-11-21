//! Intel's network cards of the 8254x family: finding one, setting it up, and
//! sending and receiving packets through it. Two models are known, the ones
//! that virtual machines play: the 82540EM and the 82545EM. What the card
//! wants comes from Intel's manual for the family, the "PCI/PCI-X Family of
//! Gigabit Ethernet Controllers Software Developer's Manual". Notes:
//! `docs/network.md`, "Intel's network card".

use core::sync::atomic::{Ordering, compiler_fence};

use crate::frames::{FRAME_SIZE, frame_take};
use crate::network_card::LONGEST_PACKET;
use crate::page_tables::map_device_memory;
use crate::pci::{PciPlace, pci_find, pci_memory_address, pci_read, pci_write};
use crate::processor::{
    device_read_8, device_read_16, device_read_32, device_write_8, device_write_32, signals_back, signals_off,
    time_stamp,
};

// Intel's maker number, and the models this driver knows, each with the name
// the kernel says. The numbers are from the manual's list of models (its
// Table 5-1), where the 82540EM has two.
const INTEL: u16 = 0x8086;
const MODELS: [(u16, &str); 3] = [(0x100E, "82540EM"), (0x1015, "82540EM"), (0x100F, "82545EM")];

// Looks for an Intel card of a known model, and returns its place on the PCI
// list with the model's name.
pub fn intel_card_find() -> Option<(PciPlace, &'static str)> {
    for (model, name) in MODELS {
        if let Some(place) = pci_find(INTEL, model) {
            return Some((place, name));
        }
    }
    None
}

// ---------- Where the card's controls are ----------

// The card keeps its controls in memory, in the 128 KB that its first address
// field names. Each control is 4 bytes wide. These are their distances from
// the start, with the manual's short names in brackets.
const CONTROLS_SIZE: u64 = 128 * 1024;
const MAIN_SETTINGS: u64 = 0x0000; // The card's main settings (CTRL).
const EEPROM_READ: u64 = 0x0014; // Reads one word of the card's small memory chip (EERD).
const SIGNALS_OFF: u64 = 0x00D8; // Switches the card's signals off (IMC).
const RECEIVING: u64 = 0x0100; // How the card receives (RCTL).
const SENDING: u64 = 0x0400; // How the card sends (TCTL).
const SENDING_GAP: u64 = 0x0410; // The pause between two packets it sends (TIPG).
const RECEIVE_RING: u64 = 0x2800; // The ring for arriving packets: the first of its controls (RDBAL).
const RECEIVE_WRITE_BACK: u64 = 0x2828; // When the card writes back what it did in that ring (RXDCTL).
const SEND_RING: u64 = 0x3800; // The ring for packets going out: the first of its controls (TDBAL).
const GROUP_TABLE: u64 = 0x5200; // 128 lines that pick packets sent to groups of machines (MTA).
const OWN_ADDRESS_LOW: u64 = 0x5400; // The card's own address: its first four bytes (RAL0),
const OWN_ADDRESS_HIGH: u64 = 0x5404; // and its last two, with a mark (RAH0).

// A ring is described by five controls, at these distances from its first.
const RING_START_LOW: u64 = 0x00; // Where its descriptions are: the low half of the address,
const RING_START_HIGH: u64 = 0x04; // and the high half.
const RING_LENGTH: u64 = 0x08; // How many bytes its descriptions take.
const RING_HEAD: u64 = 0x10; // The card's place in it.
const RING_TAIL: u64 = 0x18; // The kernel's place in it.

// Flow control, which this driver does not use: four controls that the manual
// says to set to zero then (FCAL, FCAH, FCT, FCTTV).
const FLOW_CONTROLS: [u64; 4] = [0x0028, 0x002C, 0x0030, 0x0170];

// ---------- What the controls are told ----------

// Bits of the main settings.
const LINK_RESET: u32 = 1 << 3; // Restarts the link of fibre models; the manual wants it 0.
const AUTO_SPEED: u32 = 1 << 5; // "Find out the link's speed by yourself."
const SET_LINK_UP: u32 = 1 << 6; // "Take the link that the cable part reports."
const INVERT_LOSS: u32 = 1 << 7; // Turns the link signal upside down; 0 for the card's own cable part.
const FORCE_SPEED: u32 = 1 << 11; // "Use the speed I name": off, so the card finds it.
const FORCE_DUPLEX: u32 = 1 << 12; // Likewise for talking both ways at once.
const RESET: u32 = 1 << 26; // "Start over": the whole card, but not its PCI facts. Clears itself.
const TAGS_MODE: u32 = 1 << 30; // Packets with tags for parts of a network, not used.
const CABLE_PART_RESET: u32 = 1 << 31; // Holds the cable part (the PHY) in reset; must be 0.

// Reading the memory chip, in the layout of the 82540EM and the 82545EM. The
// other models of the family read it another way, or not like this at all.
const EEPROM_START: u32 = 1 << 0; // "Read the word whose number is in bits 8 to 15."
const EEPROM_DONE: u32 = 1 << 4; // Set by the card when the word is in bits 16 to 31.

// The mark in the high half of the card's own address: "this address counts".
const ADDRESS_VALID: u32 = 1 << 31;

// Bits of the receive settings. The size of a buffer stays at the card's own,
// 2048 bytes (bits 16, 17 and 25 all 0).
const RECEIVE_ON: u32 = 1 << 1; // "Receive."
const TAKE_BROADCASTS: u32 = 1 << 15; // "Take packets sent to everybody, too."
const STRIP_CHECK: u32 = 1 << 26; // "Leave off the 4-byte check at a packet's end."

// When the card writes back what it did with slots of the receive ring: the
// manual's default holds them back until more than one is done. Counted in
// slots (bit 24), and zero held back: each one at once, since the kernel looks
// for them itself.
const WRITE_BACK_EACH: u32 = 1 << 24;

// Bits of the send settings, with the numbers that chapter 14 of the manual
// names: 10h tries after a collision, and a collision distance of 40h. Both
// matter only on a cable that cannot talk both ways at once.
const SEND_ON: u32 = 1 << 1; // "Send."
const PAD_SHORT: u32 = 1 << 3; // "Fill up packets that are too short."
const COLLISION_TRIES: u32 = 0x10 << 4;
const COLLISION_DISTANCE: u32 = 0x40 << 12;

// The pause between two packets, in the three parts the manual's table in
// chapter 14 gives for these models: 10, 10 and 10.
const GAP: u32 = 10 | 10 << 10 | 10 << 20;

// ---------- The rings ----------

// Packets pass between the kernel and the card through two rings: one for
// packets coming in, one for packets going out. A ring is a list of slots that
// the card goes round in a circle. Each slot has a description of 16 bytes:
// where its buffer is (8 bytes), and what is or should be done with it.
// The kernel's place in a ring (the tail) is where it hands the next slot
// over; the card's place (the head) is the next slot it works on.
const DESCRIPTION_SIZE: u64 = 16;
const RECEIVE_SLOTS: usize = 64;
const SEND_SLOTS: usize = 8; // The fewest a ring may have: its length must be a multiple of 128 bytes.

// Each slot has a buffer of 2048 bytes, two to a frame.
const BUFFER_SIZE: u64 = 2048;

// Where things are in a description of the receive ring...
const RECEIVED_LENGTH: u64 = 8; // 2 bytes: how many bytes the card wrote into the buffer.
// ...and of the send ring.
const SEND_LENGTH: u64 = 8; // 2 bytes: how many bytes to send from the buffer.
const SEND_COMMAND: u64 = 11; // 1 byte: what to do with them.
// In both, the byte that says how it went.
const STATUS: u64 = 12;

// Bits of that byte.
const DONE: u8 = 1 << 0; // The card is done with the slot.
const PACKET_END: u8 = 1 << 1; // Receive ring: the packet ends in this slot.

// Bits of the send command.
const COMMAND_PACKET_END: u8 = 1 << 0; // "The packet ends in this slot."
const COMMAND_ADD_CHECK: u8 = 1 << 1; // "Add the 4-byte check at its end."
const COMMAND_SAY_DONE: u8 = 1 << 3; // "Set the done mark when you have it."

// The shortest packet a network carries, without its 4-byte check.
const SHORTEST_PACKET: usize = 60;

// Where the controls are, whether the card is set up, and where the rings,
// their buffers and the kernel's place in each are.
static mut CONTROLS: u64 = 0;
static mut READY: bool = false;
static mut RECEIVE_DESCRIPTIONS: u64 = 0;
static mut RECEIVE_BUFFERS: [u64; RECEIVE_SLOTS] = [0; RECEIVE_SLOTS];
static mut RECEIVE_NEXT: usize = 0;
static mut SEND_DESCRIPTIONS: u64 = 0;
static mut SEND_BUFFERS: [u64; SEND_SLOTS] = [0; SEND_SLOTS];
static mut SEND_NEXT: usize = 0;

// Whether an Intel card was set up. It is then the card the network uses.
pub fn intel_card_ready() -> bool {
    unsafe { READY }
}

// Takes a frame and fills it with zeros.
fn empty_frame() -> u64 {
    let frame = frame_take();
    unsafe { core::ptr::write_bytes(frame as *mut u8, 0, FRAME_SIZE as usize) };
    frame
}

// The buffer of a slot: slots 0 and 1 share a new frame, 2 and 3 the next...
fn buffer_for(slot: usize, frame: &mut u64) -> u64 {
    if slot % 2 == 0 {
        *frame = frame_take();
    }
    *frame + (slot % 2) as u64 * BUFFER_SIZE
}

// Writes an 8-byte address into memory the card reads, as two halves of 4.
fn write_address(place: u64, address: u64) {
    device_write_32(place, address as u32);
    device_write_32(place + 4, (address >> 32) as u32);
}

// Tells the card where a ring is, how long it is, and where both places in it are.
fn ring_tell(controls: u64, descriptions: u64, slots: usize, tail: usize) {
    write_address(controls + RING_START_LOW, descriptions);
    device_write_32(controls + RING_LENGTH, (slots as u64 * DESCRIPTION_SIZE) as u32);
    device_write_32(controls + RING_HEAD, 0);
    device_write_32(controls + RING_TAIL, tail as u32);
}

// Waits until the processor has counted 100,000 of its own steps: at least
// ten microseconds on any processor slower than 10 GHz. Device signals are off
// while the card is set up, so the tick count stands still and cannot time it.
fn pause() {
    let start = time_stamp();
    while time_stamp().wrapping_sub(start) < 100_000 {}
}

// Reads one word of the card's small memory chip (its EEPROM): asks for the
// word by its number, then looks until the card says it is done.
fn eeprom_word(controls: u64, word: u32) -> Result<u16, &'static str> {
    device_write_32(controls + EEPROM_READ, word << 8 | EEPROM_START);
    for _ in 0..1_000_000 {
        let answer = device_read_32(controls + EEPROM_READ);
        if answer & EEPROM_DONE != 0 {
            return Ok((answer >> 16) as u16);
        }
    }
    Err("it did not read its own address from its memory chip")
}

// ---------- Setting the card up ----------

// Sets the card up and returns its address: the six bytes by which other
// machines on the network know it. If something does not fit, it returns the
// reason instead. The steps follow chapter 14 of the manual.
pub fn intel_card_setup(place: PciPlace) -> Result<[u8; 6], &'static str> {
    // The steps take frames and change the page tables, so no task switch meanwhile.
    let were_on = signals_off();
    let result = setup_steps(place);
    signals_back(were_on);
    result
}

fn setup_steps(place: PciPlace) -> Result<[u8; 6], &'static str> {
    // Three settings in the card's PCI facts, as for the virtio card: it may
    // use its memory (bit 1), it may read and write the machine's memory
    // (bit 2), and it sends no signals of its own (bit 10).
    let settings = pci_read(place, 4) & 0xFFFF;
    pci_write(place, 4, settings | 0x0406);

    // The controls are in the memory that address field 0 names. Its bit 0
    // set would mean ports instead.
    if pci_read(place, 16) & 1 != 0 {
        return Err("its first address field names ports, not memory");
    }
    let controls = pci_memory_address(place, 0);
    if controls == 0 {
        return Err("its controls have no address");
    }
    map_device_memory(controls, CONTROLS_SIZE);
    unsafe { CONTROLS = controls };

    // "Send no signals": every one of the card's own signals is masked. The
    // kernel looks for arriving packets itself.
    device_write_32(controls + SIGNALS_OFF, 0xFFFF_FFFF);

    // The firmware may have used the card, to look for a system on the
    // network. Then it is stopped and told to start over: the manual says
    // that a receiver switched off must start over before it is switched on
    // again. Receiving or sending switched on, or a ring set up, shows such
    // use; a card switched on and not used since has all four at zero. A card
    // nobody used is not started over: it is in the state the manual's setup
    // begins from, and VirtualBox, for one, keeps its card's link down for
    // five seconds after every start-over.
    let used = device_read_32(controls + RECEIVING) & RECEIVE_ON != 0
        || device_read_32(controls + SENDING) & SEND_ON != 0
        || device_read_32(controls + RECEIVE_RING + RING_LENGTH) != 0
        || device_read_32(controls + SEND_RING + RING_LENGTH) != 0;
    if used {
        // Stop receiving and sending, so that no packet is on its way into
        // memory while it starts over, and give it a moment.
        device_write_32(controls + RECEIVING, 0);
        device_write_32(controls + SENDING, 0);
        pause();

        // "Start over." The manual asks for a pause of about a microsecond
        // before the card is touched again; then the bit clears itself when
        // it is done.
        device_write_32(controls + MAIN_SETTINGS, device_read_32(controls + MAIN_SETTINGS) | RESET);
        pause();
        let mut tries = 0;
        while device_read_32(controls + MAIN_SETTINGS) & RESET != 0 && tries < 1_000_000 {
            tries += 1;
        }
        if device_read_32(controls + MAIN_SETTINGS) & RESET != 0 {
            return Err("it did not start over when asked");
        }
        device_write_32(controls + SIGNALS_OFF, 0xFFFF_FFFF);
    }

    // The main settings: take the link and its speed as the cable part finds
    // them, and leave everything this driver does not use switched off.
    let mut main = device_read_32(controls + MAIN_SETTINGS);
    main |= SET_LINK_UP | AUTO_SPEED;
    main &= !(LINK_RESET | INVERT_LOSS | FORCE_SPEED | FORCE_DUPLEX | TAGS_MODE | CABLE_PART_RESET);
    device_write_32(controls + MAIN_SETTINGS, main);
    for control in FLOW_CONTROLS {
        device_write_32(controls + control, 0);
    }

    // The card's own address is in the first three words of its memory chip,
    // each word holding two bytes of it, the first byte low.
    let mut address = [0u8; 6];
    for word in 0..3 {
        let value = eeprom_word(controls, word as u32)?;
        address[word * 2] = value as u8;
        address[word * 2 + 1] = (value >> 8) as u8;
    }
    // All zeros, all ones, or an address for a group of machines (the lowest
    // bit of its first byte set) is no card's own.
    if address == [0; 6] || address == [0xFF; 6] || address[0] & 1 != 0 {
        return Err("the address in its memory chip is not one a card can have");
    }
    // The card takes packets for the address in its first receive address.
    // The manual says to write the low half first.
    device_write_32(controls + OWN_ADDRESS_LOW, u32::from_le_bytes([address[0], address[1], address[2], address[3]]));
    device_write_32(controls + OWN_ADDRESS_HIGH, u32::from_le_bytes([address[4], address[5], 0, 0]) | ADDRESS_VALID);
    // No group of machines is listened to.
    for line in 0..128 {
        device_write_32(controls + GROUP_TABLE + line * 4, 0);
    }

    // The ring for arriving packets: one frame holds its descriptions. Every
    // slot gets a buffer, and the card gets all slots but one: its place and
    // the kernel's must never meet, because that means "no slot for you".
    let receive = empty_frame();
    let mut frame = 0;
    for slot in 0..RECEIVE_SLOTS {
        let buffer = buffer_for(slot, &mut frame);
        unsafe { RECEIVE_BUFFERS[slot] = buffer };
        write_address(receive + slot as u64 * DESCRIPTION_SIZE, buffer);
    }
    unsafe {
        RECEIVE_DESCRIPTIONS = receive;
        RECEIVE_NEXT = 0;
    }
    ring_tell(controls + RECEIVE_RING, receive, RECEIVE_SLOTS, RECEIVE_SLOTS - 1);
    device_write_32(controls + RECEIVE_WRITE_BACK, WRITE_BACK_EACH);
    // The manual says to switch receiving on only when the ring is ready.
    device_write_32(controls + RECEIVING, RECEIVE_ON | TAKE_BROADCASTS | STRIP_CHECK);

    // The ring for packets going out. Every slot starts with the done mark,
    // which this driver takes to mean "free".
    let send = empty_frame();
    for slot in 0..SEND_SLOTS {
        let buffer = buffer_for(slot, &mut frame);
        unsafe { SEND_BUFFERS[slot] = buffer };
        let description = send + slot as u64 * DESCRIPTION_SIZE;
        write_address(description, buffer);
        device_write_8(description + STATUS, DONE);
    }
    unsafe {
        SEND_DESCRIPTIONS = send;
        SEND_NEXT = 0;
    }
    ring_tell(controls + SEND_RING, send, SEND_SLOTS, 0);
    device_write_32(controls + SENDING, SEND_ON | PAD_SHORT | COLLISION_TRIES | COLLISION_DISTANCE);
    device_write_32(controls + SENDING_GAP, GAP);

    unsafe { READY = true };
    Ok(address)
}

// ---------- Packets ----------

// Sends one packet, given as it travels on the network, without its 4-byte
// check, which the card adds. Says whether the packet was handed to the card.
pub fn intel_card_send(packet: &[u8]) -> bool {
    let were_on = signals_off();
    let mut handed_over = false;
    unsafe {
        if READY && packet.len() <= LONGEST_PACKET {
            let slot = SEND_NEXT;
            let next = (slot + 1) % SEND_SLOTS;
            // One slot always stays free, or the kernel's place would catch up
            // with the card's, and the card would take a full ring for an
            // empty one. So wait until the card is done with the slot after
            // this one. It does the slots in order, so it is then done with
            // this one too.
            let after = SEND_DESCRIPTIONS + next as u64 * DESCRIPTION_SIZE;
            let mut tries = 0;
            while device_read_8(after + STATUS) & DONE == 0 && tries < 1_000_000 {
                tries += 1;
            }
            if device_read_8(after + STATUS) & DONE != 0 {
                // The packet into the slot's buffer, filled up with zeros to
                // the shortest length a network carries.
                let buffer = SEND_BUFFERS[slot] as *mut u8;
                core::ptr::copy_nonoverlapping(packet.as_ptr(), buffer, packet.len());
                let length = packet.len().max(SHORTEST_PACKET);
                core::ptr::write_bytes(buffer.add(packet.len()), 0, length - packet.len());

                // Its description: the buffer, the length, what to do, and
                // the done mark cleared.
                let description = SEND_DESCRIPTIONS + slot as u64 * DESCRIPTION_SIZE;
                write_address(description, SEND_BUFFERS[slot]);
                device_write_32(description + SEND_LENGTH, length as u32);
                device_write_8(description + SEND_COMMAND, COMMAND_PACKET_END | COMMAND_ADD_CHECK | COMMAND_SAY_DONE);
                device_write_32(description + STATUS, 0);

                // Everything above must be in memory before the card is told.
                compiler_fence(Ordering::SeqCst);
                SEND_NEXT = next;
                device_write_32(CONTROLS + SEND_RING + RING_TAIL, next as u32);
                handed_over = true;
            }
        }
    }
    signals_back(were_on);
    handed_over
}

// Picks up one arrived packet, if there is one: the slot after the last one
// picked up, if the card is done with it. The packet is copied into `into`
// and its length is returned. It does not wait.
pub fn intel_card_receive(into: &mut [u8]) -> Option<usize> {
    let were_on = signals_off();
    let mut length = None;
    unsafe {
        if READY {
            let slot = RECEIVE_NEXT;
            let description = RECEIVE_DESCRIPTIONS + slot as u64 * DESCRIPTION_SIZE;
            let status = device_read_8(description + STATUS);
            if status & DONE != 0 {
                // Nothing of the packet may be read before the done mark was.
                compiler_fence(Ordering::SeqCst);
                // A packet that does not end in its slot would be longer than
                // the card takes (1522 bytes); it is passed over. Never copy
                // more than a buffer holds or than `into` has room for.
                if status & PACKET_END != 0 {
                    let written = device_read_16(description + RECEIVED_LENGTH) as usize;
                    let bytes = written.min(BUFFER_SIZE as usize).min(into.len());
                    core::ptr::copy_nonoverlapping(RECEIVE_BUFFERS[slot] as *const u8, into.as_mut_ptr(), bytes);
                    length = Some(bytes);
                }

                // Make the slot ready for its next packet: its buffer, and
                // everything else cleared. Then move the kernel's place onto
                // it. The card uses the slots from its own place up to the one
                // before the kernel's, so the slot picked up before this one
                // is the card's again now, and this one will be at the next.
                write_address(description, RECEIVE_BUFFERS[slot]);
                device_write_32(description + RECEIVED_LENGTH, 0);
                device_write_32(description + STATUS, 0);
                compiler_fence(Ordering::SeqCst);
                device_write_32(CONTROLS + RECEIVE_RING + RING_TAIL, slot as u32);
                RECEIVE_NEXT = (slot + 1) % RECEIVE_SLOTS;
            }
        }
    }
    signals_back(were_on);
    length
}
