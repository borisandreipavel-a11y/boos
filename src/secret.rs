//! A secret: one text that the person at the machine typed and that nobody
//! else should get to see, such as the key that a paid service asks for. It
//! is kept here, in memory only, and is gone when the machine is switched
//! off. Nothing in this file prints it, shows it or writes it to the disk,
//! and nothing may be added that does.
//! Notes: `docs/chat.md`.

use core::ptr::write_volatile;

// The longest secret that is taken, in signs.
pub const SECRET_LIMIT: usize = 200;

// The secret and how many signs long it is. The room for it has a fixed size
// and a fixed place. A list that grows would move as it grows and leave
// copies of the secret behind in memory that nothing wipes.
static mut SECRET: [u8; SECRET_LIMIT] = [0; SECRET_LIMIT];
static mut SECRET_LENGTH: usize = 0;

// Writes zeros over a stretch of memory that held a secret. `write_volatile`
// tells the compiler that these writes matter: it may otherwise leave out a
// write to memory that is never read again.
pub fn wipe(signs: &mut [u8]) {
    for sign in signs.iter_mut() {
        unsafe { write_volatile(sign, 0) };
    }
}

// Keeps a secret, in place of the one kept before, and gives back how many
// signs of it were taken. The whole room is wiped first, so that nothing of a
// longer secret from before is left behind a shorter new one.
pub fn secret_keep(signs: &[u8]) -> usize {
    let room = unsafe { &mut *(&raw mut SECRET) };
    wipe(room);
    let length = signs.len().min(SECRET_LIMIT);
    room[..length].copy_from_slice(&signs[..length]);
    unsafe { SECRET_LENGTH = length };
    length
}

// How many signs long the kept secret is. 0 means that none is kept.
pub fn secret_length() -> usize {
    unsafe { SECRET_LENGTH }
}
