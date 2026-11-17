//! Random numbers: numbers that nobody can guess. Encryption needs them, and
//! the processor makes them. Notes: `docs/random-and-date.md`.

use core::arch::asm;

use crate::processor::processor_ask;

// Whether this processor can make random numbers, and the first ones it made
// looked sound. Set once at startup.
static mut RANDOM_FOUND: bool = false;

// The processor may answer "none ready yet". Its makers advise asking up to
// ten times before giving up.
const TRIES: u32 = 10;

// Asks the processor for one random number (the instruction RDRAND). The
// processor gathers them from noise in its own circuits. It says through its
// carry flag, one of its yes-or-no marks, whether it had a number ready.
fn processor_random() -> Option<u64> {
    for _ in 0..TRIES {
        let number: u64;
        let ready: u8;
        // "setc" copies the carry flag into `ready`: 1 for yes, 0 for no.
        unsafe { asm!("rdrand {0}", "setc {1}", out(reg) number, out(reg_byte) ready) };
        if ready == 1 {
            return Some(number);
        }
    }
    None
}

// Finds out whether this processor can make random numbers, and tries it out.
pub fn random_setup() {
    // Not every processor has the instruction, and using it where it is
    // missing is a failure. Bit 30 of the third number in the answer to
    // question 1 says whether it is there.
    if processor_ask(1)[2] & (1 << 30) == 0 {
        return;
    }

    // A broken source hands out the same number again and again. Draw a few:
    // each must arrive, and they must not all be the same.
    let Some(first) = processor_random() else {
        return;
    };
    let mut all_same = true;
    for _ in 0..4 {
        match processor_random() {
            Some(next) if next != first => all_same = false,
            Some(_) => {}
            None => return,
        }
    }
    unsafe { RANDOM_FOUND = !all_same };
}

// Fills a piece of memory with random bytes and says whether it could. On
// "no", what stands in that memory must not be used.
pub fn random_fill(bytes: &mut [u8]) -> bool {
    // Each random number gives 8 bytes. The last piece may be shorter.
    for piece in bytes.chunks_mut(8) {
        let Some(number) = random_number() else {
            return false;
        };
        piece.copy_from_slice(&number.to_le_bytes()[..piece.len()]);
    }
    true
}

// One random number. Answers with nothing if this machine cannot make them,
// and never with a number that only looks random.
pub fn random_number() -> Option<u64> {
    if !unsafe { RANDOM_FOUND } {
        return None;
    }
    processor_random()
}
