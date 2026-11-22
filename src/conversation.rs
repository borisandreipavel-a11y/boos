//! The conversation: the last lines that went to the model and what came of
//! each, which go with every new line, so that the model can understand a
//! line that only makes sense after the ones before it, such as "make it roll
//! two dice". A line is remembered as it was sent, with the key starred (see
//! `model.rs`), as a row of the person's ("Person: ..."), and after it the
//! rows its answers brought: the model's words and the kernel's own
//! sentences, as the chat box said them, and, where what a tool did went back
//! to the model, what an app left behind, which the chat box does not say
//! (see `chat.rs`). Each answer about the line, the first and those to the
//! model being asked about it again, adds to that one piece. Nothing else is
//! remembered: not `key` or `setup`, not the answers to the kernel's
//! questions, not a line that was turned away. It lasts until the machine is
//! switched off, or until the model forgets it with the tool `forget`, or
//! `setup` is sent. Only the main loop may call these functions.
//! Notes: `docs/tools.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

// How many lines are remembered, each with what came of it. When a newer one
// comes, the oldest goes.
const LINES_REMEMBERED: usize = 10;

// How many bytes the remembered rows may take together, each with its line
// end. Everything remembered goes to the provider again with every line, and
// is paid for each time: this holds what that costs, and the request's
// length, below a bound that is known. When the rows do not fit, the oldest
// lines go first.
const BYTES_REMEMBERED: usize = 8000;

// The lines remembered, oldest first. Each is a list of rows: the person's
// line, then what came of it.
static mut EXCHANGES: Vec<Vec<String>> = Vec::new();

// Whether the rows the kernel says now belong to the newest line: from the
// moment the answer to a line comes, until the answer to the next line comes
// or everything is forgotten. The answer to a request for an app comes after
// the answer to its line, and its rows belong to that line too.
static mut OPEN: bool = false;

// Whether a line has gone to the model and its answer has not come yet; and
// whether everything was forgotten meanwhile (`setup` may be sent while an
// answer is awaited), in which case that line is not remembered when its
// answer comes: it belongs to what was forgotten.
static mut AWAITED: bool = false;
static mut FORGOTTEN_WHILE_AWAITED: bool = false;

// The list is taken out of its place, changed, and put back, each time by
// value, so that no reference to it is ever handed out. `core::ptr::replace`
// leaves an empty list in its place, which costs nothing.
fn exchanges_take() -> Vec<Vec<String>> {
    unsafe { core::ptr::replace(&raw mut EXCHANGES, Vec::new()) }
}

fn exchanges_put(exchanges: Vec<Vec<String>>) {
    unsafe { EXCHANGES = exchanges };
}

// How many bytes the remembered rows take, each with its line end.
fn bytes_of(exchanges: &[Vec<String>]) -> usize {
    exchanges.iter().flatten().map(|row| row.len() + 1).sum()
}

// Lets the oldest lines go until the rows fit. Says whether anything is left;
// the newest line goes last.
fn fit(exchanges: &mut Vec<Vec<String>>) -> bool {
    while !exchanges.is_empty() && bytes_of(exchanges) > BYTES_REMEMBERED {
        exchanges.remove(0);
    }
    !exchanges.is_empty()
}

// A line has gone to the model: its answer is awaited.
pub fn conversation_sent() {
    unsafe {
        AWAITED = true;
        FORGOTTEN_WHILE_AWAITED = false;
    }
}

// The answer to a line has come: the line, as it was sent to the model with
// the key starred, begins a new piece of the conversation, and the rows that
// the kernel says from now on belong to it. Given nothing, no request was put
// together for the line, so nothing of it is remembered, and the rows that
// follow belong to no line; the same when everything was forgotten while the
// answer was awaited.
pub fn conversation_line(sent: Option<&str>) {
    let forgotten = unsafe { FORGOTTEN_WHILE_AWAITED };
    unsafe {
        AWAITED = false;
        FORGOTTEN_WHILE_AWAITED = false;
    }
    let Some(line) = sent.filter(|_| !forgotten) else {
        unsafe { OPEN = false };
        return;
    };
    let mut exchanges = exchanges_take();
    exchanges.push(vec![format!("Person: {}", line)]);
    while exchanges.len() > LINES_REMEMBERED {
        exchanges.remove(0);
    }
    let open = fit(&mut exchanges);
    exchanges_put(exchanges);
    unsafe { OPEN = open };
}

// The answer to another ask about the newest line has come (see `chat.rs`):
// its rows belong to that line, as the rows before them did, and begin no
// piece of their own. When everything was forgotten while the answer was
// awaited, they belong to no line, as nothing does after forgetting.
pub fn conversation_again() {
    unsafe {
        AWAITED = false;
        FORGOTTEN_WHILE_AWAITED = false;
    }
}

// A row the kernel says in answer to a line: the model's words, which begin
// with "Model:", or a sentence of the kernel's own, which begins with
// "Kernel:". It is remembered with the newest line, if the rows said now
// belong to it.
pub fn conversation_row(row: &str) {
    if !unsafe { OPEN } {
        return;
    }
    let mut exchanges = exchanges_take();
    if let Some(newest) = exchanges.last_mut() {
        newest.push(String::from(row));
    }
    let open = fit(&mut exchanges);
    exchanges_put(exchanges);
    unsafe { OPEN = open };
}

// Forgets everything that was said: the tool `forget`, and the line `setup`,
// which may mean that another person is at the machine. A line whose answer
// is still awaited is forgotten too, when its answer comes.
pub fn conversation_forget() {
    exchanges_put(Vec::new());
    unsafe {
        OPEN = false;
        FORGOTTEN_WHILE_AWAITED = AWAITED;
    }
}

// Whether anything is remembered. The tool `forget` is offered only then.
pub fn conversation_remembers() -> bool {
    let exchanges = exchanges_take();
    let any = !exchanges.is_empty();
    exchanges_put(exchanges);
    any
}

// The remembered rows, oldest first, one to a line, as they go with the next
// line (see `tools.rs`). Empty when nothing is remembered.
pub fn conversation_record() -> String {
    let exchanges = exchanges_take();
    let record = rows_joined(exchanges.iter().flatten());
    exchanges_put(exchanges);
    record
}

// What goes with another ask about the newest line (see `chat.rs`): the
// record of the lines before it, as far as they are still remembered, and
// the rows the newest line has brought so far, without the person's row,
// since the line itself goes with the ask. Nothing when the rows said now
// belong to no line, because everything was forgotten.
pub fn conversation_split() -> Option<(String, String)> {
    if !unsafe { OPEN } {
        return None;
    }
    let exchanges = exchanges_take();
    let split = exchanges.split_last().map(|(newest, earlier)| (rows_joined(earlier.iter().flatten()), rows_joined(newest.iter().skip(1))));
    exchanges_put(exchanges);
    split
}

// Rows one to a line, with no line end after the last.
fn rows_joined<'a>(rows: impl Iterator<Item = &'a String>) -> String {
    let mut joined = String::new();
    for row in rows {
        if !joined.is_empty() {
            joined.push('\n');
        }
        joined.push_str(row);
    }
    joined
}
