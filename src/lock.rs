//! The lock: a secret locked with a password, scrambled so that only someone
//! who knows the password can read it back. The password is turned into a key
//! slowly (`password_key`, from the crate in the folder `password-key/`), and
//! the secret is scrambled with that key by ChaCha20-Poly1305, which also adds
//! a proof: a wrong password, or a changed byte, is noticed and refused.
//! Notes: `docs/lock.md`.

use alloc::vec::Vec;

use chacha20poly1305::ChaCha20Poly1305;
use chacha20poly1305::aead::{AeadInOut, KeyInit, Nonce as ScramblerNumber, Tag as ScramblerProof};
use password_key::password_key;

use crate::lock_values::*;
use crate::random::random_fill;
use crate::secret::{SECRET_LIMIT, wipe};

// How many rounds a password goes through on its way to a key when a secret
// is locked: the figure that OWASP's advice on passwords names for PBKDF2
// with HMAC-SHA256. About a second in QEMU on the test computer.
pub const LOCK_ROUNDS: u32 = 600_000;

// The most rounds a locked secret that is read back may ask for. A locked
// secret is data, and may come from outside the kernel; without this bound a
// changed one could hold the kernel up for hours. Ten million rounds are
// about 20 seconds in QEMU.
const MOST_ROUNDS: u32 = 10_000_000;

// A locked secret is these bytes, in this order:
//   1 byte    the version of this layout, 1;
//   1 byte    the way it was locked, 1: PBKDF2 with HMAC-SHA256 for the key,
//             then ChaCha20-Poly1305;
//   4 bytes   the count of rounds, lowest byte first;
//   16 bytes  the salt, drawn at random for every lock;
//   12 bytes  the number for the scrambling, drawn at random for every lock;
//   the scrambled secret, as long as the secret itself;
//   16 bytes  the proof.
// The first 34 bytes, the head, are not scrambled, but the proof covers them:
// a changed byte in the head is refused like a changed byte of the secret.
const VERSION: u8 = 1;
const WAY: u8 = 1;
const ROUNDS_AT: usize = 2;
const SALT_AT: usize = 6;
const SALT_LENGTH: usize = 16;
const NUMBER_AT: usize = 22;
const NUMBER_LENGTH: usize = 12;
const HEAD_LENGTH: usize = 34;
const PROOF_LENGTH: usize = 16;
const KEY_LENGTH: usize = 32;

// The longest locked secret: the head, the longest secret, and the proof.
pub const LOCKED_MOST: usize = HEAD_LENGTH + SECRET_LIMIT + PROOF_LENGTH;

// Why `unlock` refuses when the proof does not fit. A wrong password and a
// changed locked secret cannot be told apart, so it names both.
pub const NOT_UNLOCKED: &str = "the password is not the one it was locked with, or the locked secret was changed";

// The scrambler for a key of 32 bytes.
fn scrambler(key: &[u8; KEY_LENGTH]) -> Option<ChaCha20Poly1305> {
    ChaCha20Poly1305::new_from_slice(key).ok()
}

// Locks a secret with a password, with a new salt and number drawn at random
// and `LOCK_ROUNDS` rounds. Gives back the locked secret, or why it could not
// be locked. Without random numbers nothing is locked: a fixed salt or number
// would make the locks alike, which helps someone who guesses.
pub fn lock(password: &[u8], secret: &[u8]) -> Result<Vec<u8>, &'static str> {
    let mut salt = [0u8; SALT_LENGTH];
    let mut number = [0u8; NUMBER_LENGTH];
    if !random_fill(&mut salt) || !random_fill(&mut number) {
        return Err("this machine cannot make random numbers");
    }
    lock_with(password, secret, &salt, &number, LOCK_ROUNDS)
}

// Locks with a given salt, number and count of rounds. Only `lock` and the
// check at startup call this.
fn lock_with(
    password: &[u8],
    secret: &[u8],
    salt: &[u8; SALT_LENGTH],
    number: &[u8; NUMBER_LENGTH],
    rounds: u32,
) -> Result<Vec<u8>, &'static str> {
    if secret.len() > SECRET_LIMIT {
        return Err("the secret is longer than a secret can be");
    }
    if rounds == 0 || rounds > MOST_ROUNDS {
        return Err("that count of rounds is not taken");
    }

    // The room is as large as it will be from the start. A list that has to
    // grow moves, and would leave a copy of the secret behind.
    let mut locked: Vec<u8> = Vec::with_capacity(HEAD_LENGTH + secret.len() + PROOF_LENGTH);
    locked.push(VERSION);
    locked.push(WAY);
    locked.extend_from_slice(&rounds.to_le_bytes());
    locked.extend_from_slice(salt);
    locked.extend_from_slice(number);
    locked.extend_from_slice(secret);

    // The secret is scrambled where it lies, behind the head.
    let mut key = [0u8; KEY_LENGTH];
    password_key(password, salt, rounds, &mut key);
    let used_number: ScramblerNumber<ChaCha20Poly1305> = (*number).into();
    let (head, text) = locked.split_at_mut(HEAD_LENGTH);
    let proof = match scrambler(&key) {
        Some(scrambler) => scrambler.encrypt_inout_detached(&used_number, head, text.into()).ok(),
        None => None,
    };
    wipe(&mut key);

    match proof {
        Some(proof) => {
            locked.extend_from_slice(&proof);
            Ok(locked)
        }
        None => {
            wipe(&mut locked);
            Err("the secret could not be scrambled")
        }
    }
}

// Unlocks a locked secret with a password into `room`, and gives back how
// many signs the secret has, or why it could not be unlocked. A locked secret
// is data that may come from outside the kernel, so its head and its length
// are checked before anything is done with it. `room` is wiped first, and
// wiped again if the unlocking fails, so that it never holds part of a secret.
pub fn unlock(password: &[u8], locked: &[u8], room: &mut [u8; SECRET_LIMIT]) -> Result<usize, &'static str> {
    wipe(room);
    if locked.len() < HEAD_LENGTH + PROOF_LENGTH {
        return Err("it is too short to be a locked secret");
    }
    if locked.len() > LOCKED_MOST {
        return Err("it is too long to be a locked secret");
    }
    if locked[0] != VERSION {
        return Err("the locked secret is of a version this kernel does not know");
    }
    if locked[1] != WAY {
        return Err("the secret was locked in a way this kernel does not know");
    }
    let rounds = u32::from_le_bytes([locked[ROUNDS_AT], locked[ROUNDS_AT + 1], locked[ROUNDS_AT + 2], locked[ROUNDS_AT + 3]]);
    if rounds == 0 || rounds > MOST_ROUNDS {
        return Err("the locked secret asks for a count of rounds this kernel does not take");
    }

    // The lengths are now known to fit: the head, the secret, the proof.
    let length = locked.len() - HEAD_LENGTH - PROOF_LENGTH;
    let (head, rest) = locked.split_at(HEAD_LENGTH);
    let (text, proof) = rest.split_at(length);
    let (Ok(used_number), Ok(proof)) = (
        ScramblerNumber::<ChaCha20Poly1305>::try_from(&head[NUMBER_AT..NUMBER_AT + NUMBER_LENGTH]),
        ScramblerProof::<ChaCha20Poly1305>::try_from(proof),
    ) else {
        return Err("the locked secret could not be read");
    };

    // The secret is unscrambled where it lies, in the room. The proof is
    // checked first; if it does not fit, nothing is unscrambled.
    room[..length].copy_from_slice(text);
    let mut key = [0u8; KEY_LENGTH];
    password_key(password, &head[SALT_AT..SALT_AT + SALT_LENGTH], rounds, &mut key);
    let unlocked = match scrambler(&key) {
        Some(scrambler) => scrambler.decrypt_inout_detached(&used_number, head, (&mut room[..length]).into(), &proof).is_ok(),
        None => false,
    };
    wipe(&mut key);

    if unlocked {
        Ok(length)
    } else {
        wipe(room);
        Err(NOT_UNLOCKED)
    }
}

// ---------- The check at startup ----------

// Sees that the lock computes here what others compute. Gives back how many
// checks were right, and how many there are.
pub fn lock_check() -> (usize, usize) {
    let checks = [
        published_check(b"passwd", b"salt", 1, &PUBLISHED_1),
        published_check(b"Password", b"NaCl", 80_000, &PUBLISHED_2),
        locking_check(),
        unlocking_check(),
        wrong_password_check(),
        changed_byte_check(),
    ];
    (checks.iter().filter(|right| **right).count(), checks.len())
}

// A key of 64 bytes made from a password, against the published value.
fn published_check(password: &[u8], salt: &[u8], rounds: u32, published: &[u8; 64]) -> bool {
    let mut key = [0u8; 64];
    password_key(password, salt, rounds, &mut key);
    key == *published
}

// Locking the made-up secret gives what the other implementation gave.
fn locking_check() -> bool {
    match lock_with(CHECK_PASSWORD, CHECK_SECRET, &CHECK_SALT, &CHECK_NUMBER, CHECK_ROUNDS) {
        Ok(locked) => locked == CHECK_LOCKED,
        Err(_) => false,
    }
}

// Unlocking that gives the secret back.
fn unlocking_check() -> bool {
    let mut room = [0u8; SECRET_LIMIT];
    match unlock(CHECK_PASSWORD, &CHECK_LOCKED, &mut room) {
        Ok(length) => &room[..length] == CHECK_SECRET,
        Err(_) => false,
    }
}

// A password that differs in one sign is refused.
fn wrong_password_check() -> bool {
    let mut wrong = [0u8; 64];
    let length = CHECK_PASSWORD.len().min(wrong.len());
    wrong[..length].copy_from_slice(&CHECK_PASSWORD[..length]);
    wrong[0] ^= 1;
    let mut room = [0u8; SECRET_LIMIT];
    unlock(&wrong[..length], &CHECK_LOCKED, &mut room).is_err()
}

// One changed byte is refused: in the salt, in the scrambled secret, and in
// the proof.
fn changed_byte_check() -> bool {
    [SALT_AT, HEAD_LENGTH + 5, CHECK_LOCKED.len() - 1].iter().all(|place| {
        let mut changed = CHECK_LOCKED;
        changed[*place] ^= 1;
        let mut room = [0u8; SECRET_LIMIT];
        unlock(CHECK_PASSWORD, &changed, &mut room).is_err()
    })
}
