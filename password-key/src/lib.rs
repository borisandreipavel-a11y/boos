//! Turning a password into a key: PBKDF2 with HMAC-SHA256, as RFC 8018,
//! section 5.2, writes it. It is slow on purpose. The key is the end of many
//! rounds, and someone who guesses passwords has to go through all of them for
//! every guess.
//!
//! This crate belongs to the kernel and was written for it. It lives apart
//! only so that it is built to run fast, like the outside crates: the kernel's
//! own code is built the plain way, and these rounds ran about sixteen times
//! slower there. Notes: `docs/lock.md` in the kernel's folder.

#![no_std]

use core::ptr::write_volatile;

use hmac::{KeyInit, Mac};

// One block of the key is as long as one fingerprint of SHA-256: 32 bytes.
const BLOCK: usize = 32;

// Fills `key` with the key made from `password` and `salt` in `rounds`
// rounds. A key of any length can be asked for; it is made 32 bytes at a time.
// A count of 0 rounds does what 1 does: the standard counts from 1.
pub fn password_key(password: &[u8], salt: &[u8], rounds: u32, key: &mut [u8]) {
    // A keyed fingerprint (HMAC) with the password as its key. HMAC takes a
    // key of any length, so this cannot fail.
    let keyed = hmac::Hmac::<sha2::Sha256>::new_from_slice(password).expect("HMAC takes a key of any length");

    for (index, block) in key.chunks_mut(BLOCK).enumerate() {
        // The first round fingerprints the salt and the block's number,
        // counted from 1, as four bytes with the highest byte first.
        let mut round = keyed.clone();
        round.update(salt);
        round.update(&(index as u32 + 1).to_be_bytes());
        let mut last = [0u8; BLOCK];
        last.copy_from_slice(&round.finalize().into_bytes());

        // Every further round fingerprints what the round before gave. The
        // block is all of the rounds' results laid over each other with
        // exclusive or.
        let mut sum = last;
        for _ in 1..rounds {
            let mut round = keyed.clone();
            round.update(&last);
            last.copy_from_slice(&round.finalize().into_bytes());
            for (sum_byte, last_byte) in sum.iter_mut().zip(last.iter()) {
                *sum_byte ^= *last_byte;
            }
        }
        block.copy_from_slice(&sum[..block.len()]);

        // What the rounds left behind lies on the stack; write over it.
        wipe(&mut last);
        wipe(&mut sum);
    }
}

// Writes zeros over bytes that held something derived from a password.
// `write_volatile` tells the compiler that these writes matter: it may
// otherwise leave out a write to memory that is never read again.
fn wipe(bytes: &mut [u8]) {
    for byte in bytes.iter_mut() {
        unsafe { write_volatile(byte, 0) };
    }
}
