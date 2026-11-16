//! The network card. So far the kernel only finds it. Notes: `docs/network.md`.

use crate::pci::{PciPlace, pci_find};

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
