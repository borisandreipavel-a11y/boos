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

use crate::download::Fetched;
use crate::model::{ChatReply, KeyVerdict};
use crate::processor::{signals_back, signals_off};

// What can be asked for.
#[derive(Clone, PartialEq)]
pub enum Errand {
    // Try a key typed at the onboarding: ask the model the fixed question
    // with it, and say what came back and how the provider took the key.
    KeyTry,
    // Send a line typed in the chat box to the model, with the list of what
    // the kernel can do for it: the JSON that `chat_tools` in `tools.rs` made
    // when the line was sent, or nothing for the last ask about a line (see
    // `chat.rs`); with the record of what was said before it
    // (`conversation_record` in `conversation.rs`), which may be empty; and,
    // when the model is asked about the line again, with what came of it so
    // far (`conversation_split`), which is empty for the line's first ask.
    ChatLine { line: String, tools: String, record: String, done: String },
    // Ask the model to write an app. The text says which app: the request the
    // model gave with the tool `make_app` (see `tools.rs`).
    AppRequest(String),
    // Fetch one hop of a file from the web: the address, as `files.rs` read
    // and checked it (see `download.rs`).
    Download(String),
}

// The answer to an errand: which errand it answers; what the kernel has to
// say about it, in one sentence (for a line the model answered as it should,
// nothing); for the try of a key how the provider took the key; for an app
// the script the model wrote, if it passed the checks; for a line what the
// model answered; for a line or an app the provider answered, the terminal's
// line about how many tokens that took; and for a line, the line as it was
// sent to the model, with the key starred, or nothing when no request was
// put together for it; for a hop of a fetch, what it brought.
pub struct Answer {
    pub errand: Errand,
    pub sentence: String,
    pub key: KeyVerdict,
    pub script: Option<String>,
    pub reply: Option<ChatReply>,
    pub tokens: Option<String>,
    pub sent: Option<String>,
    pub fetched: Option<Fetched>,
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
static mut ANSWER: Option<Answer> = None;

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
pub fn errand_answer(answer: Answer) {
    let were_on = signals_off();
    unsafe { ANSWER = Some(answer) };
    STATE.store(ANSWERED, Ordering::Relaxed);
    signals_back(were_on);
}

// The main loop picks up the answer, if one lies ready. After that the next
// errand can be asked for. What was left of the answer's words as they came
// (below) goes with it: the answer itself says them now.
pub fn errand_answer_take() -> Option<Answer> {
    let were_on = signals_off();
    let (answer, grown) = if STATE.load(Ordering::Relaxed) == ANSWERED {
        STATE.store(NONE, Ordering::Relaxed);
        unsafe { ((*(&raw mut ANSWER)).take(), (*(&raw mut GROWN)).take()) }
    } else {
        (None, None)
    };
    signals_back(were_on);
    drop(grown);
    answer
}

// ---------- The words of an answer as they come ----------

// While the model's answer to a line comes in, piece by piece (see
// `model.rs`), the network's task leaves here what of its words can be shown
// so far, and whether the model is thinking before its first word. The main
// loop takes the newest when it paints the chat box (see `chat_grow` in
// `chat.rs`); a newer one put here before that takes the place of the older.
// Two tasks reach this, so it is touched only with device signals off.
static mut GROWN: Option<(String, bool)> = None;

// The network's task leaves what of the answer can be shown so far.
pub fn errand_grow(words: &str, thinking: bool) {
    let grown = Some((String::from(words), thinking));
    let were_on = signals_off();
    let older = unsafe { core::mem::replace(&mut *(&raw mut GROWN), grown) };
    signals_back(were_on);
    drop(older);
}

// The main loop takes what of the answer can be shown so far, if anything new
// was left since it took the last.
pub fn errand_grown() -> Option<(String, bool)> {
    let were_on = signals_off();
    let grown = unsafe { (*(&raw mut GROWN)).take() };
    signals_back(were_on);
    grown
}
