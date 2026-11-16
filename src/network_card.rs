//! The network card: finding it and setting it up. It does not send or
//! receive packets yet. Notes: `docs/network.md`.

use crate::frames::{FRAME_SIZE, frame_take};
use crate::page_tables::map_device_memory;
use crate::pci::{PciPlace, pci_find, pci_memory_address, pci_read, pci_read_8, pci_write};
use crate::processor::{
    device_read_8, device_read_16, device_read_32, device_write_8, device_write_16,
    device_write_32, signals_back, signals_off,
};

// The network card QEMU offers is a "virtio" card: one that exists only in
// virtual machines and is made to be simple to drive. Its maker's number is
// 0x1AF4. Its model is 0x1000, or 0x1041 for the kind that only knows the
// newer way of working.
const VIRTIO_MAKER: u16 = 0x1AF4;
const VIRTIO_NETWORK_CARD: u16 = 0x1000;
const VIRTIO_NETWORK_CARD_NEWER: u16 = 0x1041;

// Looks for the network card and returns its place on the PCI list.
pub fn network_card_find() -> Option<PciPlace> {
    if let Some(place) = pci_find(VIRTIO_MAKER, VIRTIO_NETWORK_CARD) {
        return Some(place);
    }
    pci_find(VIRTIO_MAKER, VIRTIO_NETWORK_CARD_NEWER)
}

// ---------- Where the card's controls are ----------

// A virtio card keeps its controls in memory, in groups. A list in the card's
// PCI facts says where each group is. These are the numbers of the three
// groups this driver uses.
const GROUP_COMMON: u8 = 1; // The handshake and the waiting lines.
const GROUP_KNOCK: u8 = 2; // Where to knock when a waiting line has news.
const GROUP_CARD: u8 = 4; // Facts about this very card, such as its address.

// The memory address of each group, once found, and the distance between the
// knocking places of two waiting lines.
static mut COMMON: u64 = 0;
static mut KNOCK: u64 = 0;
static mut KNOCK_STEP: u64 = 0;
static mut CARD: u64 = 0;

// The controls of the common group, as distances from its start. Each has a
// width of 1, 2 or 4 bytes and must be read and written at that width.
const CARD_FEATURES_HALF: u64 = 0x00; // 4 bytes: which half of the card's features to show.
const CARD_FEATURES: u64 = 0x04; // 4 bytes: that half.
const DRIVER_FEATURES_HALF: u64 = 0x08; // 4 bytes: which half the driver is about to state.
const DRIVER_FEATURES: u64 = 0x0C; // 4 bytes: that half.
const STATE: u64 = 0x14; // 1 byte: how far the handshake has got.
const LINE_CHOICE: u64 = 0x16; // 2 bytes: which waiting line the next controls are about.
const LINE_SIZE: u64 = 0x18; // 2 bytes: how many packets it holds.
const LINE_ON: u64 = 0x1C; // 2 bytes: 1 switches it on.
const LINE_KNOCK: u64 = 0x1E; // 2 bytes: which knocking place is its own.
const LINE_DESCRIPTIONS: u64 = 0x20; // 8 bytes: the address of its first area,
const LINE_FROM_DRIVER: u64 = 0x28; // 8 bytes: of its second,
const LINE_FROM_CARD: u64 = 0x30; // 8 bytes: and of its third.

// ---------- The handshake ----------

// Driver and card go through fixed steps before the card works. The driver
// reports each step by adding a mark to the card's state.
const NOTICED: u8 = 1; // "I have noticed you."
const CAN_DRIVE: u8 = 2; // "I know how to drive you."
const FEATURES_AGREED: u8 = 8; // "These are the features we will use."
const READY: u8 = 4; // "Setup is done. Go."
const GAVE_UP: u8 = 0x80; // The driver's mark for "I am giving up on you."
const IN_TROUBLE: u8 = 0x40; // The card's own mark for "something went wrong on my side."

// The card offers 64 yes/no features, shown in two halves of 32. The driver
// states the ones it will use. These are the two this driver needs.
const FEATURE_OWN_ADDRESS: u32 = 1 << 5; // Lower half: the card has an address of its own.
const FEATURE_NEWER_WAY: u32 = 1 << 0; // Upper half: the newer way of working.

// ---------- Waiting lines ----------

// Packets pass between driver and card through waiting lines: one for packets
// coming in, one for packets going out. A waiting line is three areas of
// memory that both sides read and write. Each area gets a frame of its own.
#[derive(Clone, Copy)]
struct WaitingLine {
    size: u16,         // How many packets it can hold.
    descriptions: u64, // Says where each packet's memory is, and how long.
    from_driver: u64,  // The driver lists here what it hands to the card.
    from_card: u64,    // The card lists here what it hands back.
    knock: u64,        // Where to write to tell the card there is news.
}

const NO_LINE: WaitingLine = WaitingLine {
    size: 0,
    descriptions: 0,
    from_driver: 0,
    from_card: 0,
    knock: 0,
};

static mut RECEIVE_LINE: WaitingLine = NO_LINE;
static mut SEND_LINE: WaitingLine = NO_LINE;

// Takes a frame and fills it with zeros.
fn empty_frame() -> u64 {
    let frame = frame_take();
    unsafe { core::ptr::write_bytes(frame as *mut u8, 0, FRAME_SIZE as usize) };
    frame
}

// Tells the card where one of a waiting line's areas is. The address is
// 8 bytes, written as two halves of 4.
fn write_address(control: u64, address: u64) {
    device_write_32(control, address as u32);
    device_write_32(control + 4, (address >> 32) as u32);
}

// Sets up one waiting line: number 0 receives, number 1 sends.
fn waiting_line_setup(number: u16) -> Result<WaitingLine, &'static str> {
    let common = unsafe { COMMON };
    device_write_16(common + LINE_CHOICE, number);

    // The card says how long the line may be. One frame holds 256
    // descriptions, so the driver asks for no more than that.
    let mut size = device_read_16(common + LINE_SIZE);
    if size == 0 {
        return Err("the card lacks a waiting line");
    }
    if size > 256 {
        size = 256;
        device_write_16(common + LINE_SIZE, size);
    }

    // The card reads and writes the areas by their real addresses. It knows
    // nothing of the kernel's page tables, so these must be frames.
    let line = WaitingLine {
        size,
        descriptions: empty_frame(),
        from_driver: empty_frame(),
        from_card: empty_frame(),
        knock: unsafe { KNOCK + device_read_16(common + LINE_KNOCK) as u64 * KNOCK_STEP },
    };
    // "Do not send a signal when you hand something back. I will look myself."
    unsafe { *(line.from_driver as *mut u16) = 1 };

    write_address(common + LINE_DESCRIPTIONS, line.descriptions);
    write_address(common + LINE_FROM_DRIVER, line.from_driver);
    write_address(common + LINE_FROM_CARD, line.from_card);
    device_write_16(common + LINE_ON, 1);
    Ok(line)
}

// ---------- Setting the card up ----------

// Sets the card up and returns its address: the six bytes by which other
// machines on the network know it. If something does not fit, it returns the
// reason instead.
pub fn network_card_setup(place: PciPlace) -> Result<[u8; 6], &'static str> {
    // The steps take frames and change the page tables, so no task switch meanwhile.
    let were_on = signals_off();
    let result = setup_steps(place);
    signals_back(were_on);
    result
}

fn setup_steps(place: PciPlace) -> Result<[u8; 6], &'static str> {
    // Three settings in the card's PCI facts: it may use its memory (bit 1),
    // it may read and write the machine's memory (bit 2), and it sends no
    // signals of its own (bit 10). The upper half of these 4 bytes is not a
    // setting and is written as zeros.
    let settings = pci_read(place, 4) & 0xFFFF;
    pci_write(place, 4, settings | 0x0406);

    // Walk the list of groups in the card's PCI facts. Each entry says what
    // it is and where the next entry starts; 0 ends the list.
    let mut entry = pci_read_8(place, 0x34);
    let mut entries_seen = 0;
    while entry != 0 && entries_seen < 48 {
        // Entries of kind 9 describe a group of virtio controls: which group,
        // in which address field, how far in, and how long.
        if pci_read_8(place, entry) == 0x09 {
            let group = pci_read_8(place, entry + 3);
            let field = pci_read_8(place, entry + 4);
            let memory_field = field < 6 && pci_read(place, 16 + field * 4) & 1 == 0;
            let wanted = group == GROUP_COMMON || group == GROUP_KNOCK || group == GROUP_CARD;
            if wanted && memory_field {
                let address = pci_memory_address(place, field) + pci_read(place, entry + 8) as u64;
                map_device_memory(address, pci_read(place, entry + 12) as u64);
                unsafe {
                    if group == GROUP_COMMON && COMMON == 0 {
                        COMMON = address;
                    } else if group == GROUP_KNOCK && KNOCK == 0 {
                        KNOCK = address;
                        KNOCK_STEP = pci_read(place, entry + 16) as u64;
                    } else if group == GROUP_CARD && CARD == 0 {
                        CARD = address;
                    }
                }
            }
        }
        entry = pci_read_8(place, entry + 1);
        entries_seen += 1;
    }
    let (common, card) = unsafe { (COMMON, CARD) };
    if common == 0 || card == 0 || unsafe { KNOCK } == 0 {
        return Err("it does not offer the newer way of working");
    }

    // The handshake. Writing 0 makes the card start over.
    device_write_8(common + STATE, 0);
    let mut tries = 0;
    while device_read_8(common + STATE) != 0 && tries < 100_000 {
        tries += 1;
    }
    if device_read_8(common + STATE) != 0 {
        return Err("it did not start over when asked");
    }
    device_write_8(common + STATE, NOTICED);
    device_write_8(common + STATE, NOTICED | CAN_DRIVE);

    // Read both halves of what the card offers, and state what will be used.
    device_write_32(common + CARD_FEATURES_HALF, 0);
    let lower_half = device_read_32(common + CARD_FEATURES);
    device_write_32(common + CARD_FEATURES_HALF, 1);
    let upper_half = device_read_32(common + CARD_FEATURES);
    if lower_half & FEATURE_OWN_ADDRESS == 0 || upper_half & FEATURE_NEWER_WAY == 0 {
        device_write_8(common + STATE, NOTICED | CAN_DRIVE | GAVE_UP);
        return Err("it lacks a feature this driver needs");
    }
    device_write_32(common + DRIVER_FEATURES_HALF, 0);
    device_write_32(common + DRIVER_FEATURES, FEATURE_OWN_ADDRESS);
    device_write_32(common + DRIVER_FEATURES_HALF, 1);
    device_write_32(common + DRIVER_FEATURES, FEATURE_NEWER_WAY);
    device_write_8(common + STATE, NOTICED | CAN_DRIVE | FEATURES_AGREED);
    // The card keeps the mark only if it accepts the choice.
    if device_read_8(common + STATE) & FEATURES_AGREED == 0 {
        return Err("it did not accept the features this driver chose");
    }

    // The two waiting lines. The `?` means: if this failed, stop here and
    // return the same reason.
    let receive_line = waiting_line_setup(0)?;
    let send_line = waiting_line_setup(1)?;
    unsafe {
        RECEIVE_LINE = receive_line;
        SEND_LINE = send_line;
    }

    device_write_8(common + STATE, NOTICED | CAN_DRIVE | FEATURES_AGREED | READY);
    if device_read_8(common + STATE) & (GAVE_UP | IN_TROUBLE) != 0 {
        return Err("it reported a failure at the end of the setup");
    }

    // The card's address is the first six bytes of the facts about itself.
    let mut address = [0u8; 6];
    for (number, byte) in address.iter_mut().enumerate() {
        *byte = device_read_8(card + number as u64);
    }
    Ok(address)
}
