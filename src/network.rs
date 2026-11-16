//! The kernel's first words on the network, put together by hand: asking who
//! the gateway is. Notes: `docs/network.md`.

use crate::network_card::{LONGEST_PACKET, network_card_receive, network_card_send};

// Every machine on a network has two addresses. Its hardware address (6
// bytes) belongs to its network card. Its network address (4 bytes, written
// like 10.0.2.2) says where it is on the network. A packet is delivered by
// hardware address, so before talking to a machine one has to ask: "who has
// this network address?" The machine that has it answers with its hardware
// address.

// The gateway is the machine that passes packets on to the outside. On
// QEMU's built-in network it is at 10.0.2.2.
const GATEWAY: [u8; 4] = [10, 0, 2, 2];

// The kernel has not been given a network address yet. For this one question
// it assumes the address QEMU's network hands out first.
const ASSUMED_OWN_ADDRESS: [u8; 4] = [10, 0, 2, 15];

// How many times to look for the answer before giving up. Device signals are
// off at startup, so the tick count stands still and cannot time the wait.
const LOOKS: u32 = 2_000_000;

// Asks the whole network who has the gateway's network address, and waits
// for the answer. Returns the gateway's hardware address.
pub fn gateway_ask(card_address: [u8; 6]) -> Option<[u8; 6]> {
    // 60 bytes is the shortest packet a network carries. The question fills
    // 42 of them and the rest stays zero.
    let mut question = [0u8; 60];
    question[0..6].copy_from_slice(&[0xFF; 6]); // To: everybody on the network.
    question[6..12].copy_from_slice(&card_address); // From: this card.
    question[12..14].copy_from_slice(&[0x08, 0x06]); // Kind of packet: an address question or answer.
    question[14..16].copy_from_slice(&[0x00, 0x01]); // The hardware addresses are a network card's,
    question[16..18].copy_from_slice(&[0x08, 0x00]); // the network addresses the internet's,
    question[18] = 6; // 6 bytes long
    question[19] = 4; // and 4 bytes long.
    question[20..22].copy_from_slice(&[0x00, 0x01]); // 1 means question, 2 means answer.
    question[22..28].copy_from_slice(&card_address); // Who asks: hardware address
    question[28..32].copy_from_slice(&ASSUMED_OWN_ADDRESS); // and network address.
    // Bytes 32 to 37 stay zero: the hardware address that is being asked for.
    question[38..42].copy_from_slice(&GATEWAY); // Whose is it? The gateway's.

    if !network_card_send(&question) {
        return None;
    }

    // Look at every packet that arrives until the answer is among them. Other
    // packets may come first and are passed over.
    let mut packet = [0u8; LONGEST_PACKET];
    for _ in 0..LOOKS {
        if let Some(length) = network_card_receive(&mut packet) {
            let is_answer = length >= 42 && packet[12..14] == [0x08, 0x06] && packet[20..22] == [0x00, 0x02];
            if is_answer && packet[28..32] == GATEWAY {
                let mut gateway_address = [0u8; 6];
                gateway_address.copy_from_slice(&packet[22..28]);
                return Some(gateway_address);
            }
        }
    }
    None
}
