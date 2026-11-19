//! A secret: one text that the person at the machine typed and that nobody
//! else should get to see, such as the key that a paid service asks for. It
//! is kept here, in memory, and is gone when the machine is switched off.
//! Nothing in this file prints it or shows it, and nothing may be added that
//! does. It leaves this file in two ways only: lent to the file that sends it
//! to the service it belongs to (`model.rs`), and locked with a password
//! (`lock.rs`), which scrambles it so that it can be kept on the disk. A
//! secret that is unlocked again comes straight back here.
//! A password chosen to lock the secret with is kept here too, for the short
//! time between the two times it is typed.
//! Notes: `docs/chat.md`, `docs/model.md` and `docs/lock.md`.

use alloc::vec::Vec;
use core::ptr::write_volatile;

use crate::lock::{lock, unlock};
use crate::model::KeyPass;
use crate::processor::{signals_back, signals_off};

// The longest secret that is taken, in signs. A password may be as long.
pub const SECRET_LIMIT: usize = 200;

// The secret and how many signs long it is. The room for it has a fixed size
// and a fixed place. A list that grows would move as it grows and leave
// copies of the secret behind in memory that nothing wipes.
//
// Two tasks reach these: the main loop keeps a secret, and the network's task
// borrows it. So each function below touches them only with device signals
// off: the timer cannot then switch to the other task half-way through.
static mut SECRET: [u8; SECRET_LIMIT] = [0; SECRET_LIMIT];
static mut SECRET_LENGTH: usize = 0;

// A password chosen to lock the secret with, and how many signs long it is,
// kept between the first time it is typed and the second. Only the main loop
// reaches it, but it is handled like the secret: a room of a fixed size,
// touched with device signals off, and wiped when it is forgotten.
static mut PASSWORD: [u8; SECRET_LIMIT] = [0; SECRET_LIMIT];
static mut PASSWORD_LENGTH: usize = 0;

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
    let were_on = signals_off();
    let room = unsafe { &mut *(&raw mut SECRET) };
    wipe(room);
    let length = signs.len().min(SECRET_LIMIT);
    room[..length].copy_from_slice(&signs[..length]);
    unsafe { SECRET_LENGTH = length };
    signals_back(were_on);
    length
}

// How many signs long the kept secret is. 0 means that none is kept.
pub fn secret_length() -> usize {
    let were_on = signals_off();
    let length = unsafe { SECRET_LENGTH };
    signals_back(were_on);
    length
}

// Lends the secret to `borrower`, a piece of code that is run with the
// secret in hand and must be short, because device signals are off while it
// runs. Whoever calls this has to show a pass, and only `model.rs` can make
// one: that is how the compiler sees to it that no other file gets at the
// secret. What the borrower copies out of it, the borrower must wipe.
pub fn secret_lend(_pass: &KeyPass, borrower: &mut dyn FnMut(&[u8])) {
    let were_on = signals_off();
    let room = unsafe { &*(&raw const SECRET) };
    let length = unsafe { SECRET_LENGTH };
    borrower(&room[..length]);
    signals_back(were_on);
}

// Keeps a password chosen to lock the secret with, in place of one kept
// before, and gives back how many signs of it were taken.
pub fn password_keep(signs: &[u8]) -> usize {
    let were_on = signals_off();
    let room = unsafe { &mut *(&raw mut PASSWORD) };
    wipe(room);
    let length = signs.len().min(SECRET_LIMIT);
    room[..length].copy_from_slice(&signs[..length]);
    unsafe { PASSWORD_LENGTH = length };
    signals_back(were_on);
    length
}

// Whether `signs` are exactly the password that was kept.
pub fn password_same(signs: &[u8]) -> bool {
    let were_on = signals_off();
    let room = unsafe { &*(&raw const PASSWORD) };
    let length = unsafe { PASSWORD_LENGTH };
    let same = length > 0 && signs == &room[..length];
    signals_back(were_on);
    same
}

// Forgets the password that was kept: wipes its room.
pub fn password_forget() {
    let were_on = signals_off();
    wipe(unsafe { &mut *(&raw mut PASSWORD) });
    unsafe { PASSWORD_LENGTH = 0 };
    signals_back(were_on);
}

// Locks the secret with the password that was kept (see `lock.rs`), and gives
// back the locked secret, which may be kept where others can see it, or why
// it could not be locked. Locking takes more than a second, far too long for
// device signals to be off. So the secret and the password are copied into
// rooms of this function's own with signals off, locked from there with
// signals on, and those rooms are wiped at the end.
pub fn secret_lock() -> Result<Vec<u8>, &'static str> {
    let mut secret = [0u8; SECRET_LIMIT];
    let mut password = [0u8; SECRET_LIMIT];
    let were_on = signals_off();
    let secret_length = unsafe { SECRET_LENGTH };
    let password_length = unsafe { PASSWORD_LENGTH };
    let kept_secret = unsafe { &*(&raw const SECRET) };
    let kept_password = unsafe { &*(&raw const PASSWORD) };
    secret[..secret_length].copy_from_slice(&kept_secret[..secret_length]);
    password[..password_length].copy_from_slice(&kept_password[..password_length]);
    signals_back(were_on);

    let locked = if secret_length == 0 {
        Err("no secret is kept")
    } else if password_length == 0 {
        Err("no password is kept")
    } else {
        lock(&password[..password_length], &secret[..secret_length])
    };
    wipe(&mut secret);
    wipe(&mut password);
    locked
}

// Unlocks a locked secret with a password, and keeps it in place of the
// secret kept before. Gives back how many signs it has, or why it could not
// be unlocked; then the secret kept before stays as it was. Unlocking takes
// more than a second, so it runs with device signals on, into a room of this
// function's own; only the finished secret is kept, with signals off, and
// the room is wiped.
pub fn secret_unlock(password: &[u8], locked: &[u8]) -> Result<usize, &'static str> {
    let mut room = [0u8; SECRET_LIMIT];
    let kept = match unlock(password, locked, &mut room) {
        Ok(length) => Ok(secret_keep(&room[..length])),
        Err(reason) => Err(reason),
    };
    wipe(&mut room);
    kept
}
