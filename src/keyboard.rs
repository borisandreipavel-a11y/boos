//! The keyboard: taking key numbers from its controller, keeping them in a
//! waiting line, and turning them into letters. Notes: `docs/interrupts.md`.

use core::sync::atomic::{AtomicU8, AtomicUsize, Ordering};

use crate::controller::signal_done;
use crate::processor::{port_read, port_write};

// The keyboard controller hands over key numbers at one port, and reports its
// state and takes commands at another.
const KEYBOARD_DATA: u16 = 0x60;
const KEYBOARD_COMMAND: u16 = 0x64;

// A waiting line for keys. The handler only puts the key's number here, and
// the main loop picks it up later. That keeps the handler short, so other
// signals are not held back for long.
static KEY_QUEUE: [AtomicU8; 16] = [const { AtomicU8::new(0) }; 16];
static KEYS_ARRIVED: AtomicUsize = AtomicUsize::new(0); // How many were ever put in.
static KEYS_TAKEN: AtomicUsize = AtomicUsize::new(0); // How many were ever picked up.

pub fn keyboard_setup() {
    // When nothing answers at a port, every bit reads as 1. No real keyboard
    // controller reports that, so it means there is none.
    if port_read(KEYBOARD_COMMAND) == 0xFF {
        return;
    }

    // Wait until the controller is ready to listen, then give it new settings.
    let mut tries = 0;
    while port_read(KEYBOARD_COMMAND) & 0x02 != 0 && tries < 100_000 {
        tries += 1;
    }
    port_write(KEYBOARD_COMMAND, 0x60); // "New settings follow."
    tries = 0;
    while port_read(KEYBOARD_COMMAND) & 0x02 != 0 && tries < 100_000 {
        tries += 1;
    }
    // Keyboard on, a signal for each key, the classic key numbers, mouse off.
    port_write(KEYBOARD_DATA, 0x65);

    // Throw away any key that arrived before the kernel was listening. The
    // controller sends no new signal while an old key is still waiting.
    tries = 0;
    while port_read(KEYBOARD_COMMAND) & 0x01 != 0 && tries < 100_000 {
        port_read(KEYBOARD_DATA);
        tries += 1;
    }
}

// Runs each time a key is pressed or let go.
pub extern "sysv64" fn on_keyboard() {
    // Check that a key number is really waiting, then take it. Taking it also
    // lets the controller send the next one.
    if port_read(KEYBOARD_COMMAND) & 0x01 != 0 {
        let key = port_read(KEYBOARD_DATA);
        let arrived = KEYS_ARRIVED.load(Ordering::Relaxed);
        let taken = KEYS_TAKEN.load(Ordering::Relaxed);
        // If the waiting line is full, the key is dropped.
        if arrived - taken < KEY_QUEUE.len() {
            KEY_QUEUE[arrived % KEY_QUEUE.len()].store(key, Ordering::Relaxed);
            KEYS_ARRIVED.store(arrived + 1, Ordering::Relaxed);
        }
    }
    signal_done();
}

// Picks up the key that has waited longest, if any.
pub fn next_key() -> Option<u8> {
    let taken = KEYS_TAKEN.load(Ordering::Relaxed);
    if taken == KEYS_ARRIVED.load(Ordering::Relaxed) {
        return None;
    }
    let key = KEY_QUEUE[taken % KEY_QUEUE.len()].load(Ordering::Relaxed);
    KEYS_TAKEN.store(taken + 1, Ordering::Relaxed);
    Some(key)
}

// Turns a key number into its letter on a US keyboard. A key number says where
// the key sits, not what is printed on it: the keys are numbered row by row.
// Letting a key go sends its number plus 128, which has no letter here.
pub fn key_letter(key: u8) -> Option<u8> {
    let (first_key, row): (u8, &[u8]) = match key {
        2..=13 => (2, b"1234567890-="),
        16..=27 => (16, b"qwertyuiop[]"),
        28 => return Some(b'\n'), // Enter.
        30..=41 => (30, b"asdfghjkl;'`"),
        43..=53 => (43, b"\\zxcvbnm,./"),
        57 => return Some(b' '), // The space bar.
        _ => return None,
    };
    Some(row[(key - first_key) as usize])
}
