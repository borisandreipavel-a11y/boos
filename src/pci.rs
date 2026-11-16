//! The PCI list: every card and built-in device of the machine, and the facts
//! each one states about itself. Notes: `docs/network.md`.

use crate::processor::{port_read_32, port_write_32, signals_back, signals_off};

// A PC keeps its cards and built-in devices on the PCI list. A place on the
// list is named by three numbers: the bus (a row of slots), the device (one
// slot of that row) and the function (one of up to 8 devices that share a
// slot). Most slots are empty.
#[derive(Clone, Copy)]
pub struct PciPlace {
    pub bus: u8,
    pub device: u8,
    pub function: u8,
}

// Each place holds a small table of facts about its device. The table is read
// 4 bytes at a time, in two steps: say which place and which 4 bytes at one
// port, then read the answer at another.
const PCI_WHICH: u16 = 0xCF8;
const PCI_ANSWER: u16 = 0xCFC;

// The number that says which place, and which 4 bytes of its table, are meant.
fn pci_which(place: PciPlace, offset: u8) -> u32 {
    0x8000_0000
        | (place.bus as u32) << 16
        | (place.device as u32) << 11
        | (place.function as u32) << 8
        | (offset & 0xFC) as u32
}

// Reads 4 bytes of a place's table of facts, starting `offset` bytes in.
pub fn pci_read(place: PciPlace, offset: u8) -> u32 {
    // The two steps belong together: no other task may ask in between.
    let were_on = signals_off();
    port_write_32(PCI_WHICH, pci_which(place, offset));
    let answer = port_read_32(PCI_ANSWER);
    signals_back(were_on);
    answer
}

// Reads the single byte `offset` bytes into a place's table of facts.
pub fn pci_read_8(place: PciPlace, offset: u8) -> u8 {
    (pci_read(place, offset) >> ((offset & 3) * 8)) as u8
}

// Writes 4 bytes into a place's table of facts. A few of them are settings
// the kernel may change, such as whether the device may use its memory.
pub fn pci_write(place: PciPlace, offset: u8, value: u32) {
    let were_on = signals_off();
    port_write_32(PCI_WHICH, pci_which(place, offset));
    port_write_32(PCI_ANSWER, value);
    signals_back(were_on);
}

// A device says where its ports and its memory are in six "address fields",
// 4 bytes each, starting 16 bytes into its table. This returns the memory
// address in one of them.
pub fn pci_memory_address(place: PciPlace, field: u8) -> u64 {
    let low_half = pci_read(place, 16 + field * 4);
    // The lowest 4 bits are not part of the address. They tell its kind.
    let mut address = (low_half & 0xFFFF_FFF0) as u64;
    // Bits 1 and 2 holding the number 2 mean a 64-bit address, whose upper
    // half is in the next field.
    if low_half & 0b110 == 0b100 {
        address |= (pci_read(place, 16 + (field + 1) * 4) as u64) << 32;
    }
    address
}

// Looks through the whole list for a device by its maker and its model, the
// two numbers every device states first. Returns the place it was found at.
pub fn pci_find(maker: u16, model: u16) -> Option<PciPlace> {
    for bus in 0..=255 {
        for device in 0..32 {
            for function in 0..8 {
                let place = PciPlace { bus, device, function };
                // The first 4 bytes are the maker (low half) and the model
                // (high half). An empty place answers with every bit set.
                let maker_and_model = pci_read(place, 0);
                if maker_and_model == (model as u32) << 16 | maker as u32 {
                    return Some(place);
                }
                // An empty slot has no further functions. A filled one has
                // them only if function 0 says so, with one bit at byte 14.
                if function == 0 && (maker_and_model == 0xFFFF_FFFF || pci_read(place, 12) & 0x0080_0000 == 0) {
                    break;
                }
            }
        }
    }
    None
}
