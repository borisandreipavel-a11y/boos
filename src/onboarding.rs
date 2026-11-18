//! The onboarding: what the kernel asks the person at the machine at a start
//! where it does not know them yet. Today that is one question: what to call
//! them. The answer is kept in the notebook on the disk. It stands in front of
//! the person's rows in the chat box, and every later start greets them by
//! it. The line `setup`, sent by itself, asks the question again.
//! Only the chat box calls these functions, so only the main loop may.
//! Notes: `docs/chat.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

use crate::notebook::{notebook_find, notebook_keep, notebook_ready};

// The line that, sent by itself, makes the kernel ask the question again.
pub const SETUP_WORD: &str = "setup";

// The name under which the answer is kept in the notebook. An entry under
// this name also tells a later start that the question was answered, even
// when the answer was to stay "You": then the entry holds no signs.
const NAME_ENTRY: &str = "name";

// The longest name that can be given, in signs.
pub const NAME_LIMIT: usize = 20;

// What stands in front of the person's rows while no name was given.
const NO_NAME: &str = "You";

// The name that was given (empty while none was), whether the kernel waits
// for the answer to its question, and whether the notebook holds an answer.
// Nothing protects these against a second task, so only the main loop may
// touch them.
static mut NAME: String = String::new();
static mut ASKING: bool = false;
static mut ANSWER_KEPT: bool = false;

// Rust refuses a plain reference to a `static mut`, so the name is reached
// through its address, as the lists in `chat.rs` are. The rule from there
// holds here too: do not keep what this gives back across a call of another
// function of this file.
fn name() -> &'static mut String {
    unsafe { &mut *(&raw mut NAME) }
}

// The name in front of the person's rows: the one that was given, or "You".
pub fn person_name() -> String {
    let given = name();
    if given.is_empty() { String::from(NO_NAME) } else { given.clone() }
}

// Whether the kernel waits for the answer to its question. While it does,
// the next line that is sent is that answer.
pub fn onboarding_asking() -> bool {
    unsafe { ASKING }
}

// The question, with the name that Enter alone leaves as it is. With the
// name "You" it fits on one row of the chat box on a screen 1280 dots wide.
fn question() -> String {
    format!("Kernel: what should I call you? Type a name and press Enter. Enter alone keeps \"{}\".", person_name())
}

// A name read from the disk comes from outside the kernel. At most as many
// signs are taken as a name may have, every byte that is not a plain sign
// becomes a dot, and spaces at either end are dropped.
fn name_clean(kept: &[u8]) -> String {
    let signs: String = kept.iter().take(NAME_LIMIT).map(|byte| if (b' '..=b'~').contains(byte) { *byte as char } else { '.' }).collect();
    String::from(signs.trim())
}

// What the kernel says at startup, once the notebook is opened: if the
// notebook holds a name, a greeting by it; if it holds none, the question.
// Gives back nothing when there is nothing to say: no name was kept and none
// could be, because the notebook cannot be added to.
pub fn onboarding_begin() -> Vec<String> {
    match notebook_find(NAME_ENTRY) {
        Ok(Some(kept)) => {
            *name() = name_clean(&kept);
            unsafe { ANSWER_KEPT = true };
            let greeting = if name().is_empty() { String::from("Kernel: welcome back.") } else { format!("Kernel: welcome back, {}.", name()) };
            vec![format!("{} Type a line and press Enter.", greeting)]
        }
        Ok(None) if notebook_ready() => {
            unsafe { ASKING = true };
            vec![String::from("Kernel: hello! I do not know your name yet, so I have one question before we begin."), question()]
        }
        Ok(None) => Vec::new(),
        Err(reason) => {
            // The notebook has an entry for the name, but it cannot be read
            // now. Ask again, if the answer can be kept.
            let trouble = format!("Kernel: I cannot read the name you gave before, because {}.", reason);
            if notebook_ready() {
                unsafe { ASKING = true };
                vec![trouble, question()]
            } else {
                vec![format!("{} Type a line and press Enter.", trouble)]
            }
        }
    }
}

// The line `setup`: the kernel asks the question again. Gives back the
// question.
pub fn onboarding_again() -> String {
    unsafe { ASKING = true };
    question()
}

// Takes the answer to the question: the line that was sent, which may be
// empty. Keeps it in the notebook, and gives back what the kernel says to it.
pub fn onboarding_answer(line: &str) -> String {
    unsafe { ASKING = false };

    // Spaces at either end do not count, and a line of nothing else is no
    // name. Without a name, the name stays as it is.
    let given = line.trim();
    let changed = !given.is_empty();
    if changed {
        *name() = String::from(given);
    } else if unsafe { ANSWER_KEPT } {
        // The name stays, and the notebook holds it already.
        return format!("Kernel: your name stays \"{}\". Type a line and press Enter.", person_name());
    }

    // Keep the answer. An entry that holds no signs means "You".
    let (opening, what) = if changed {
        (format!("Kernel: hello, {}.", given), "your name")
    } else {
        (format!("Kernel: I will call you \"{}\".", person_name()), "that")
    };
    match notebook_keep(NAME_ENTRY, name().as_bytes()) {
        Ok(()) => {
            unsafe { ANSWER_KEPT = true };
            let remembered = if changed { " I will remember your name." } else { "" };
            format!("{}{} Type a line and press Enter.", opening, remembered)
        }
        Err(reason) => format!("{} I could not keep {}, because {}, so it lasts only until the machine is switched off.", opening, what, reason),
    }
}
