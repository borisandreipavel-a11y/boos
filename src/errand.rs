//! Errands: how the main loop asks the network's task to do something for
//! it and gets the answer back. An errand is a piece of work that one part
//! of the kernel hands to another. Only the network's task may use the
//! network, and only the main loop may use the chat box, so a line typed in
//! the chat box that needs the network has to travel from one to the other,
//! and the answer has to travel back. This file is the place where both are
//! left for the other side to pick up.
//! Notes: `docs/tasks.md`.

use alloc::string::String;
use core::sync::atomic::{AtomicBool, AtomicU8, Ordering};

use crate::processor::{signals_back, signals_off};

// What can be asked for.
pub enum Errand {
    // Fetch the example page from the web and say how the site answered.
    ExamplePage,
    // Ask the model the one question and say what came back.
    ModelQuestion,
}

// How far the one errand has got. There is room for one at a time.
const NONE: u8 = 0; // Nothing is asked for.
const WAITING: u8 = 1; // Asked for, and not picked up by the network's task yet.
const UNDER_WAY: u8 = 2; // The network's task is at work on it.
const ANSWERED: u8 = 3; // The answer lies ready for the main loop.
static STATE: AtomicU8 = AtomicU8::new(NONE);

// The errand that waits, and the answer that lies ready. Two tasks reach
// these, so each is touched only with device signals off: the timer cannot
// then switch to the other task half-way through.
static mut ERRAND: Option<Errand> = None;
static mut ANSWER: String = String::new();

// Whether the network's task is there and this machine has an address. Without
// that nobody would ever pick an errand up.
static NETWORK_READY: AtomicBool = AtomicBool::new(false);

// The network's task says here whether errands can be run.
pub fn errand_network_ready(ready: bool) {
    NETWORK_READY.store(ready, Ordering::Relaxed);
}

// The main loop asks for an errand. It is turned away, with the reason in
// words, if nobody could run it or if the one before is not finished.
pub fn errand_ask(errand: Errand) -> Result<(), &'static str> {
    if !NETWORK_READY.load(Ordering::Relaxed) {
        return Err("this machine has no address on the network");
    }
    let were_on = signals_off();
    let free = STATE.load(Ordering::Relaxed) == NONE;
    if free {
        unsafe { ERRAND = Some(errand) };
        STATE.store(WAITING, Ordering::Relaxed);
    }
    signals_back(were_on);
    if free { Ok(()) } else { Err("the answer to what I asked before has not come yet") }
}

// The network's task picks up the errand that waits, if there is one.
pub fn errand_take() -> Option<Errand> {
    let were_on = signals_off();
    let errand = if STATE.load(Ordering::Relaxed) == WAITING {
        STATE.store(UNDER_WAY, Ordering::Relaxed);
        unsafe { (*(&raw mut ERRAND)).take() }
    } else {
        None
    };
    signals_back(were_on);
    errand
}

// The network's task leaves the answer to the errand it picked up.
pub fn errand_answer(answer: String) {
    let were_on = signals_off();
    unsafe { ANSWER = answer };
    STATE.store(ANSWERED, Ordering::Relaxed);
    signals_back(were_on);
}

// The main loop picks up the answer, if one lies ready. After that the next
// errand can be asked for.
pub fn errand_answer_take() -> Option<String> {
    let were_on = signals_off();
    let answer = if STATE.load(Ordering::Relaxed) == ANSWERED {
        STATE.store(NONE, Ordering::Relaxed);
        Some(core::mem::take(unsafe { &mut *(&raw mut ANSWER) }))
    } else {
        None
    };
    signals_back(were_on);
    answer
}
