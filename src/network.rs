//! The network: one question put together by hand, and then the network
//! stack that does everything else. Notes: `docs/network.md`.

use alloc::format;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

use smoltcp::iface::{Config, Interface, SocketSet};
use smoltcp::phy::{Device, DeviceCapabilities, Medium, RxToken, TxToken};
use smoltcp::socket::dhcpv4;
use smoltcp::time::Instant;
use smoltcp::wire::{EthernetAddress, IpCidr, Ipv4Address};

use crate::network_card::{LONGEST_PACKET, network_card_receive, network_card_send};
use crate::errand::{Answer, Errand, errand_answer, errand_network_ready, errand_take};
use crate::model::{KeyVerdict, model_app, model_chat, model_tell};
use crate::page::page_fetch;
use crate::processor::time_stamp;
use crate::serial::serial_print;
use crate::tasks::{task_add, task_wait};
use crate::timer::{TICKS, TICKS_PER_SECOND};

// ---------- The first question, by hand ----------

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

// How many times to look for the answer before asking once more, and how many
// times to ask. Device signals are off at startup, so the tick count stands
// still and cannot time the wait; a round of looks lasts under a second in
// QEMU. QEMU's Intel card holds every arriving packet back for a second after
// receiving is switched on, so the answer to the first question comes just
// after the first round, and the second round takes it in.
const LOOKS: u32 = 2_000_000;
const ASKINGS: u32 = 2;

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

    let mut packet = [0u8; LONGEST_PACKET];
    for _ in 0..ASKINGS {
        if !network_card_send(&question) {
            return None;
        }

        // Look at every packet that arrives until the answer is among them.
        // Other packets may come first and are passed over.
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
    }
    None
}

// ---------- The network stack ----------

// From here on the work is done by smoltcp, a network stack that was not
// written for this kernel (see `vendor/README.md`). It knows the rules of the
// network: how to get an address, how to find other machines, how to keep a
// connection going. It needs three things from the kernel: a way to send and
// receive packets, the time, and somebody who calls it regularly.

// The way to send and receive packets: an adapter over the network card's
// driver. smoltcp describes what it needs as a "trait", a list of functions
// that a type has to offer, and `impl Device for Card` offers them. It is
// `pub` because `page.rs` uses it. The two token types below are `pub` only
// because Rust wants every type that a public type shows to be public too.
pub struct Card;

// smoltcp hands packets over as "tokens": a token for an arrived packet holds
// that packet, and a token for sending is the permission to send one.
pub struct ArrivedPacket {
    bytes: Vec<u8>,
}

pub struct PacketToSend;

impl Device for Card {
    // The `'a` is a lifetime: a label for how long a borrowed thing stays
    // valid. smoltcp's trait asks for it. These tokens borrow nothing, so it
    // plays no part here.
    type RxToken<'a>
        = ArrivedPacket
    where
        Self: 'a;
    type TxToken<'a>
        = PacketToSend
    where
        Self: 'a;

    // Asked on every call whether a packet has arrived. If one has, smoltcp
    // gets it, together with the permission to send an answer.
    fn receive(&mut self, _now: Instant) -> Option<(ArrivedPacket, PacketToSend)> {
        let mut room = [0u8; LONGEST_PACKET];
        // The `?` means: if nothing has arrived, answer "nothing" right away.
        let length = network_card_receive(&mut room)?;
        Some((ArrivedPacket { bytes: room[..length].to_vec() }, PacketToSend))
    }

    // Asked whenever smoltcp wants to send. The card always takes a packet.
    fn transmit(&mut self, _now: Instant) -> Option<PacketToSend> {
        Some(PacketToSend)
    }

    // What the card can do: it is an Ethernet card, a packet is at most 1514
    // bytes long, and packets go out one at a time.
    fn capabilities(&self) -> DeviceCapabilities {
        let mut capabilities = DeviceCapabilities::default();
        capabilities.medium = Medium::Ethernet;
        capabilities.max_transmission_unit = LONGEST_PACKET;
        capabilities.max_burst_size = Some(1);
        capabilities
    }
}

impl RxToken for ArrivedPacket {
    // smoltcp passes in a piece of its own code (a "closure", a function
    // handed over as a value) that reads the packet.
    fn consume<R, F>(self, read_it: F) -> R
    where
        F: FnOnce(&[u8]) -> R,
    {
        read_it(&self.bytes)
    }
}

impl TxToken for PacketToSend {
    // smoltcp says how long the packet will be and passes in a piece of its
    // own code that writes it. Then the driver sends it.
    fn consume<R, F>(self, length: usize, write_it: F) -> R
    where
        F: FnOnce(&mut [u8]) -> R,
    {
        let mut bytes = vec![0u8; length];
        let result = write_it(&mut bytes);
        network_card_send(&bytes);
        result
    }
}

// The time as smoltcp wants it: milliseconds since the kernel started. It
// comes from the tick count, so it moves in steps of 10.
pub fn now() -> Instant {
    Instant::from_millis((TICKS.load(Ordering::Relaxed) * 1000 / TICKS_PER_SECOND) as i64)
}

// The card's own address, kept for the task below.
static mut CARD_ADDRESS: [u8; 6] = [0; 6];

// Starts the network stack as a task of its own.
pub fn network_start(card_address: [u8; 6]) {
    unsafe { CARD_ADDRESS = card_address };
    task_add(network_task);
}

// The somebody who calls smoltcp regularly. Each call lets it take in the
// packets that have arrived and send the ones it has to send.
fn network_task() {
    let mut card = Card;
    let mut settings = Config::new(EthernetAddress(unsafe { CARD_ADDRESS }).into());
    // smoltcp wants a start number that differs at every start of the kernel.
    // The processor's count of its own steps does; it need not be a secret.
    settings.random_seed = time_stamp();
    let mut interface = Interface::new(settings, &mut card, now());
    let mut sockets = SocketSet::new(Vec::new());

    // Ask the network for an address. smoltcp does the asking, and repeats it
    // when the address is about to run out; this only has to listen for news.
    let address_request = sockets.add(dhcpv4::Socket::new());
    let mut has_address = false;
    // With the address the network also names a name server (see `page.rs`).
    let mut name_server: Option<Ipv4Address> = None;
    // The page is fetched once, the first time there is an address.
    let mut page_fetched = false;

    loop {
        interface.poll(now(), &mut card, &mut sockets);

        // Any news about the address?
        match sockets.get_mut::<dhcpv4::Socket>(address_request).poll() {
            // The network has given this machine an address, or a new one.
            Some(dhcpv4::Event::Configured(given)) => {
                interface.update_ip_addrs(|addresses| {
                    addresses.clear();
                    addresses.push(IpCidr::Ipv4(given.address)).ok();
                });
                // The gateway is where packets for the outside go.
                match given.router {
                    Some(gateway) => {
                        interface.routes_mut().add_default_ipv4_route(gateway).ok();
                    }
                    None => {
                        interface.routes_mut().remove_default_ipv4_route();
                    }
                }
                has_address = true;
                name_server = given.dns_servers.first().copied();
                serial_print(&format!(
                    "Network: this machine was given the address {} by {}\r\n",
                    given.address.address(),
                    given.server.address
                ));
            }
            // There is no address: not yet, or not any more.
            Some(dhcpv4::Event::Deconfigured) => {
                interface.update_ip_addrs(|addresses| addresses.clear());
                interface.routes_mut().remove_default_ipv4_route();
                if has_address {
                    has_address = false;
                    serial_print("Network: this machine's address has run out\r\n");
                }
            }
            None => {}
        }

        // Say whether errands can be run. This comes before this task's own
        // fetch below, which can take a while: an errand asked for in the
        // meantime then waits its turn instead of being turned away.
        errand_network_ready(has_address);

        // The first use of the address: fetch one page from the web.
        if has_address && !page_fetched {
            page_fetched = true;
            page_fetch(&mut interface, &mut card, &mut sockets, name_server);
        }

        // Errands: work that the main loop asks this task to do, because only
        // this task may use the network. Run the one that waits, and leave
        // the answer for the main loop to pick up. While an errand runs, this
        // task does nothing else.
        if let Some(errand) = errand_take() {
            let (sentence, key, script, reply, tokens, sent) = match &errand {
                // The try of a key asks the fixed question, with the key
                // being tried instead of the one kept.
                Errand::KeyTry if has_address => {
                    let (sentence, key) = model_tell(&mut interface, &mut card, &mut sockets, name_server, true);
                    (sentence, key, None, None, None, None)
                }
                // A line typed in the chat box, and an app, are asked about
                // with the key that is kept.
                Errand::ChatLine { line, tools, record } if has_address => {
                    let (sentence, reply, tokens, sent) = model_chat(&mut interface, &mut card, &mut sockets, name_server, line, tools, record);
                    (sentence, KeyVerdict::NotTold, None, reply, tokens, sent)
                }
                Errand::AppRequest(wanted) if has_address => {
                    let (sentence, script, tokens) = model_app(&mut interface, &mut card, &mut sockets, name_server, wanted);
                    (sentence, KeyVerdict::NotTold, script, None, tokens, None)
                }
                _ => ("no answer came, because this machine has lost its address on the network".into(), KeyVerdict::NotTold, None, None, None, None),
            };
            errand_answer(Answer { errand, sentence, key, script, reply, tokens, sent });
        }

        // The card sends no signals, so the only way to notice a packet is to
        // look again. Looking once per tick costs next to nothing.
        task_wait(1);
    }
}
