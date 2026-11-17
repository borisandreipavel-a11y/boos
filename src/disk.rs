//! The disk: finding the controller that the machine's disks are plugged
//! into. Notes: `docs/disk.md`.

use crate::pci::{PciPlace, pci_find_kind};

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
