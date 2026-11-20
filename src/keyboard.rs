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
    // The place is emptied as the key is taken out of it (`swap` gives back
    // what was there and puts 0 in). Otherwise the last keys that were
    // pressed would stay readable here, the keys of a typed secret too.
    let key = KEY_QUEUE[taken % KEY_QUEUE.len()].swap(0, Ordering::Relaxed);
    KEYS_TAKEN.store(taken + 1, Ordering::Relaxed);
    Some(key)
}

// What `key_letter` gives for the Backspace key, the key that takes the last
// typed sign away. It is the number computers have long used for it.
pub const BACKSPACE: u8 = 8;

// The key number of F1, the first of the keys along the top of the keyboard.
// It has no letter. The main loop hands every key number to `lines_key`,
// which shows the kernel's own lines on F1 (see `lines.rs`).
pub const F1_KEY: u8 = 59;

// The key numbers of the two Shift keys: the number each sends when it is
// pressed, and the number it sends when it is let go, which is 128 more.
const LEFT_SHIFT: u8 = 42;
const RIGHT_SHIFT: u8 = 54;
const LEFT_SHIFT_LET_GO: u8 = LEFT_SHIFT + 128;
const RIGHT_SHIFT_LET_GO: u8 = RIGHT_SHIFT + 128;

// Some keys, such as the arrows and Print Screen, send this number first and
// their own number after it. It marks the number that follows as belonging
// to such a key.
const MARK: u8 = 224;

// Whether each Shift key is held down right now, and whether the number
// taken last was the mark. Only `key_letter` reads and changes these, and
// only the main loop calls it.
static mut LEFT_SHIFT_HELD: bool = false;
static mut RIGHT_SHIFT_HELD: bool = false;
static mut AFTER_MARK: bool = false;

// Turns a key number into its letter on a US keyboard. A key number says where
// the key sits, not what is printed on it: the keys are numbered row by row.
// Letting a key go sends its number plus 128, which has no letter here.
// Enter and Backspace have no letter either; they come back as the numbers
// that stand for them, `b'\n'` and `BACKSPACE`.
//
// While a Shift key is held down, a key gives its second sign: a capital
// letter, or the sign printed above a digit. The Shift keys give no letter
// themselves; this function remembers whether they are down. So it must be
// handed every key number, in the order the numbers arrived.
pub fn key_letter(key: u8) -> Option<u8> {
    // The mark gives nothing. Remember it for the number that comes next.
    if key == MARK {
        unsafe { AFTER_MARK = true };
        return None;
    }
    let after_mark = unsafe { AFTER_MARK };
    unsafe { AFTER_MARK = false };

    // A Shift key going down or coming up. Some keyboards send a Shift
    // number behind the mark, around keys such as Print Screen, although
    // nobody touched Shift. Those are not the Shift keys and are passed over.
    if !after_mark {
        match key {
            LEFT_SHIFT => unsafe { LEFT_SHIFT_HELD = true },
            RIGHT_SHIFT => unsafe { RIGHT_SHIFT_HELD = true },
            LEFT_SHIFT_LET_GO => unsafe { LEFT_SHIFT_HELD = false },
            RIGHT_SHIFT_LET_GO => unsafe { RIGHT_SHIFT_HELD = false },
            _ => {}
        }
    }
    let shift = unsafe { LEFT_SHIFT_HELD || RIGHT_SHIFT_HELD };

    // Each row of keys, as it is without Shift and as it is with Shift.
    let (first_key, plain, shifted): (u8, &[u8], &[u8]) = match key {
        2..=13 => (2, b"1234567890-=", b"!@#$%^&*()_+"),
        14 => return Some(BACKSPACE),
        16..=27 => (16, b"qwertyuiop[]", b"QWERTYUIOP{}"),
        28 => return Some(b'\n'), // Enter.
        30..=41 => (30, b"asdfghjkl;'`", b"ASDFGHJKL:\"~"),
        43..=53 => (43, b"\\zxcvbnm,./", b"|ZXCVBNM<>?"),
        57 => return Some(b' '), // The space bar.
        _ => return None,
    };
    let row = if shift { shifted } else { plain };
    Some(row[(key - first_key) as usize])
}
