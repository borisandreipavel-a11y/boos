//! The onboarding: what the kernel asks the person at the machine at a start
//! where it does not know them yet, and what it asks at every start after
//! that. It asks two things itself: what to call them, and the key for the model,
//! which is locked with a password they choose (see `lock.rs`). A key that is
//! typed is first tried with one question to the model, and asked for again
//! if the provider does not know it. Both answers are kept in the notebook on
//! the disk, the name as it was given and the key only locked. The name
//! stands in front of the person's rows in the chat box, and every later
//! start greets them by it. A start where a key is locked on the disk asks
//! for the password, which unlocks it. The line `setup`, sent by itself,
//! brings the first look back at once and asks both things again. When the
//! questions about the key are over, the question for the look follows, if
//! the notebook holds no answer about the look yet, and always after `setup`
//! (see `look.rs`).
//! Only the chat box calls these functions, so only the main loop may.
//! Notes: `docs/chat.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

use crate::errand::{Errand, errand_ask};
use crate::lock::NOT_UNLOCKED;
use crate::look::{look_due, look_question, look_reset, look_reset_trouble};
use crate::model::KeyVerdict;
use crate::notebook::{notebook_find, notebook_keep, notebook_ready};
use crate::random::random_number;
use crate::secret::{password_forget, password_keep, password_same, secret_lock, secret_unlock, trial_forget, trial_keep, trial_take};

// The line that, sent by itself, makes the kernel ask its questions again.
pub const SETUP_WORD: &str = "setup";

// The name under which the answer to the first question is kept in the
// notebook. An entry under this name also tells a later start that the
// question was answered, even when the answer was to stay "You": then the
// entry holds no signs.
const NAME_ENTRY: &str = "name";

// The longest name that can be given, in signs.
pub const NAME_LIMIT: usize = 20;

// What stands in front of the person's rows while no name was given.
const NO_NAME: &str = "You";

// The name under which the locked key is kept in the notebook. An entry that
// holds no signs means that the question for the key was answered without
// one, so that later starts do not ask it again.
const KEY_ENTRY: &str = "locked key";

// The fewest signs a password may have. The password is meant to keep out
// somebody who uses the machine, not somebody who has a copy of the disk
// (see docs/open-points.md).
pub const PASSWORD_LEAST: usize = 4;

// What the kernel waits for. While it waits for a name, the next line that
// is sent is the name. While it waits for a key or a password, what is typed
// shows as stars, and Enter hands it to `onboarding_secret`. While it waits
// for the provider's answer to the try of a key (`Trying`), nothing typed is
// taken.
#[derive(Clone, Copy, PartialEq)]
enum Waiting {
    Nothing,
    Name,
    Key,
    Trying,
    NewPassword,
    SamePassword,
    Password,
}

// The name that was given (empty while none was); what the kernel waits for;
// whether the notebook holds a name, and an answer to the question for the
// key; the locked key it holds (empty if none); and whether the questions are
// asked again because of `setup`. Nothing protects these against a second
// task, so only the main loop may touch them.
static mut NAME: String = String::new();
static mut WAITING: Waiting = Waiting::Nothing;
static mut NAME_KEPT: bool = false;
static mut KEY_ANSWERED: bool = false;
static mut LOCKED: Vec<u8> = Vec::new();
static mut SETTING_UP: bool = false;

// The words that say that the chat box is free again: at the end of a row, or
// as a row of their own.
const TYPE_A_LINE: &str = " Type a line and press Enter.";
const TYPE_A_LINE_ROW: &str = "Kernel: type a line and press Enter.";

// The first row at a start that does not know the person yet: one question
// when only the name is asked, a few when the key is asked after it.
const HELLO_ONE: &str = "Kernel: hello! I do not know your name yet, so I have one question before we begin.";
const HELLO_FEW: &str = "Kernel: hello! I do not know you yet, so I have a few questions before we begin.";

// What the kernel says about the key. Each fits on one row of the chat box
// on a screen 1280 dots wide.
const KEY_WHY: &str = "Kernel: to ask the model I need your key. I lock it with a password and keep it on the disk.";
const KEY_QUESTION: &str = "Kernel: type the key and press Enter. It shows as stars. Enter alone goes on without a key.";
const KEY_QUESTION_AGAIN: &str = "Kernel: type a new key and press Enter. Enter alone keeps the one locked on the disk.";
const PASSWORD_QUESTION: &str = "Kernel: type your password and press Enter to unlock the key. Enter alone goes on without it.";

// What the kernel says about the try of a key, when the provider's answer
// does not say whether the key is right, and while the try is under way.
const CANNOT_TELL: &str = "Kernel: so I cannot tell whether the key is right. I keep it all the same.";
const STILL_TRYING: &str = "Kernel: I am still trying the key. Wait for its answer, then type.";

// Rust refuses a plain reference to a `static mut`, so the name and the
// locked key are reached through their addresses, as the lists in `chat.rs`
// are. The rule from there holds here too: do not keep what these give back
// across a call of another function of this file.
fn name() -> &'static mut String {
    unsafe { &mut *(&raw mut NAME) }
}

fn locked_key() -> &'static mut Vec<u8> {
    unsafe { &mut *(&raw mut LOCKED) }
}

fn waiting() -> Waiting {
    unsafe { WAITING }
}

fn wait_for(what: Waiting) {
    unsafe { WAITING = what };
}

// The questions about the name and the key, and a `setup`, are over: nothing
// more is waited for here. If the look is still to be asked (see `look.rs`),
// its question follows `rows`, in place of the words that say the chat box is
// free. If `setup` could not keep the first look on the disk, the rows that
// say so come last, before that question (see `look_reset_trouble`). Gives
// back the rows to say.
fn finish(mut rows: Vec<String>) -> Vec<String> {
    let setting_up = unsafe { SETTING_UP };
    unsafe {
        WAITING = Waiting::Nothing;
        SETTING_UP = false;
    }
    let mut trouble = look_reset_trouble();
    if look_due(setting_up) {
        free_words_drop(&mut rows);
        rows.append(&mut trouble);
        rows.push(look_question());
    } else if let Some(last) = trouble.last_mut() {
        // No question follows. Such rows come here only from a notebook that
        // cannot be added to, and then nothing in `rows` says that the chat
        // box is free, so their last row says it.
        last.push_str(TYPE_A_LINE);
        rows.append(&mut trouble);
    }
    rows
}

// Takes away the words that say the chat box is free: the last row that is
// only those words, or those words at the end of the last row that has them.
fn free_words_drop(rows: &mut Vec<String>) {
    for place in (0..rows.len()).rev() {
        if rows[place] == TYPE_A_LINE_ROW {
            rows.remove(place);
            return;
        }
        if let Some(kept) = rows[place].strip_suffix(TYPE_A_LINE) {
            rows[place] = String::from(kept);
            return;
        }
    }
}

// The name in front of the person's rows: the one that was given, or "You".
pub fn person_name() -> String {
    let given = name();
    if given.is_empty() { String::from(NO_NAME) } else { given.clone() }
}

// Whether the kernel waits for a name. While it does, the next line that is
// sent is that name.
pub fn onboarding_asking() -> bool {
    waiting() == Waiting::Name
}

// Whether the kernel waits for a key or a password, or for the answer to the
// try of a key. While it does, nothing typed goes into an ordinary line: a
// key or a password shows as stars and goes to `onboarding_secret`, and while
// a key is tried nothing typed is taken.
pub fn onboarding_wants_secret() -> bool {
    matches!(waiting(), Waiting::Key | Waiting::Trying | Waiting::NewPassword | Waiting::SamePassword | Waiting::Password)
}

// Whether the kernel waits for the provider's answer to the try of a key.
// While it does, nothing typed is taken.
pub fn onboarding_trying() -> bool {
    waiting() == Waiting::Trying
}

// Whether the kernel waits for anything at all.
pub fn onboarding_waiting() -> bool {
    waiting() != Waiting::Nothing
}

// The question for the name, with the name that Enter alone leaves as it is.
// With the name "You" it fits on one row of the chat box on a screen 1280
// dots wide.
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

// What the notebook holds under the name of the locked key.
enum KeyKept {
    Locked(Vec<u8>),
    NoKey,
    Nothing,
    Unreadable(&'static str),
}

fn key_kept() -> KeyKept {
    match notebook_find(KEY_ENTRY) {
        Ok(Some(locked)) if !locked.is_empty() => KeyKept::Locked(locked),
        Ok(Some(_)) => KeyKept::NoKey,
        Ok(None) => KeyKept::Nothing,
        Err(reason) => KeyKept::Unreadable(reason),
    }
}

// Whether something will be asked after the name, at a start: the password if
// a key is locked on the disk, the key if the notebook holds no answer about
// it yet and a key can be locked and kept, or else the look, if the notebook
// holds no answer about the look yet (see `look.rs`).
fn more_follows() -> bool {
    let key_follows = match key_kept() {
        KeyKept::Locked(_) => true,
        KeyKept::NoKey => false,
        KeyKept::Nothing | KeyKept::Unreadable(_) => notebook_ready() && random_number().is_some(),
    };
    key_follows || look_due(false)
}

// What the kernel says at startup, once the notebook is opened: if the
// notebook holds a name, a greeting by it, and then what it asks about the
// key; if it holds none, the question for the name. Gives back nothing when
// there is nothing to say: no name was kept, none could be, and no key is
// locked on the disk.
pub fn onboarding_begin() -> Vec<String> {
    match notebook_find(NAME_ENTRY) {
        Ok(Some(kept)) => {
            *name() = name_clean(&kept);
            unsafe { NAME_KEPT = true };
            let greeting = if name().is_empty() { String::from("Kernel: welcome back.") } else { format!("Kernel: welcome back, {}.", name()) };
            then_key(vec![greeting])
        }
        Ok(None) if notebook_ready() => {
            let hello = if more_follows() { HELLO_FEW } else { HELLO_ONE };
            wait_for(Waiting::Name);
            vec![String::from(hello), question()]
        }
        // No name, and none can be kept: nothing is asked, unless a key is
        // locked on the disk.
        Ok(None) => key_rows(),
        Err(reason) => {
            // The notebook has an entry for the name, but it cannot be read
            // now. Ask again, if the answer can be kept.
            let trouble = format!("Kernel: I cannot read the name you gave before, because {}.", reason);
            if notebook_ready() {
                wait_for(Waiting::Name);
                vec![trouble, question()]
            } else {
                then_key(vec![trouble])
            }
        }
    }
}

// Adds what the kernel asks about the key behind `rows`. If it asks nothing,
// the last row says instead that the chat box is free.
fn then_key(mut rows: Vec<String>) -> Vec<String> {
    let next = key_rows();
    if next.is_empty() {
        if let Some(last) = rows.last_mut() {
            last.push_str(TYPE_A_LINE);
        }
    } else {
        rows.extend(next);
    }
    rows
}

// What the kernel asks about the key, after the name. At a start: the
// password if a key is locked on the disk, nothing if the notebook says that
// no key is wanted, and otherwise the key. After `setup`: the key. A key is
// asked for only if it can be locked and kept: the notebook can be added to,
// and the machine can make random numbers. When nothing is asked about the
// key, the question for the look may follow (see `finish`).
fn key_rows() -> Vec<String> {
    let setting_up = unsafe { SETTING_UP };
    let mut rows = Vec::new();
    match key_kept() {
        KeyKept::Locked(locked) => {
            *locked_key() = locked;
            unsafe { KEY_ANSWERED = true };
            if !setting_up {
                wait_for(Waiting::Password);
                rows.push(String::from(PASSWORD_QUESTION));
                return rows;
            }
        }
        KeyKept::NoKey => {
            unsafe { KEY_ANSWERED = true };
            if !setting_up {
                return finish(rows);
            }
        }
        KeyKept::Nothing => {}
        KeyKept::Unreadable(reason) => rows.push(format!("Kernel: I cannot read the key kept on the disk, because {}.", reason)),
    }
    if !notebook_ready() {
        return finish(rows);
    }
    if random_number().is_none() {
        rows.push(String::from("Kernel: I cannot lock a key on this machine, because it cannot make random numbers."));
        rows.push(String::from("Kernel: send \"key\" for a key that lasts until the machine is switched off."));
        return finish(rows);
    }
    wait_for(Waiting::Key);
    if !(setting_up && !locked_key().is_empty()) {
        rows.push(String::from(KEY_WHY));
    }
    rows.push(key_question());
    rows
}

// The question for the key: after `setup` with a key locked on the disk,
// Enter alone keeps that one; otherwise it goes on without a key.
fn key_question() -> String {
    let setting_up = unsafe { SETTING_UP };
    String::from(if setting_up && !locked_key().is_empty() { KEY_QUESTION_AGAIN } else { KEY_QUESTION })
}

// The row that asks for a password to lock the key with.
fn choose_password() -> String {
    format!("Kernel: now choose a password of at least {} signs to lock it with.", PASSWORD_LEAST)
}

// The line `setup`: the first look comes back on the screen at once, so that
// every question after it can be read whatever look was in use (see
// `look_reset`); then the kernel asks for the name again, and then about the
// key. Gives back the question for the name.
pub fn onboarding_again() -> String {
    look_reset();
    unsafe { SETTING_UP = true };
    wait_for(Waiting::Name);
    question()
}

// Takes the answer to the question for the name: the line that was sent,
// which may be empty. Keeps it in the notebook, and gives back what the
// kernel says to it, and what it asks next about the key.
pub fn onboarding_answer(line: &str) -> Vec<String> {
    wait_for(Waiting::Nothing);

    // Spaces at either end do not count, and a line of nothing else is no
    // name. Without a name, the name stays as it is.
    let given = line.trim();
    let changed = !given.is_empty();
    if changed {
        *name() = String::from(given);
    } else if unsafe { NAME_KEPT } {
        // The name stays, and the notebook holds it already.
        return then_key(vec![format!("Kernel: your name stays \"{}\".", person_name())]);
    }

    // Keep the answer. An entry that holds no signs means "You".
    let (opening, what) = if changed {
        (format!("Kernel: hello, {}.", given), "your name")
    } else {
        (format!("Kernel: I will call you \"{}\".", person_name()), "that")
    };
    match notebook_keep(NAME_ENTRY, name().as_bytes()) {
        Ok(()) => {
            unsafe { NAME_KEPT = true };
            let remembered = if changed { " I will remember your name." } else { "" };
            then_key(vec![format!("{}{}", opening, remembered)])
        }
        Err(reason) => {
            let mut rows = vec![format!("{} I could not keep {}, because {}, so it lasts only until the machine is switched off.", opening, what, reason)];
            rows.extend(key_rows());
            rows
        }
    }
}

// Takes what was typed as stars while the kernel waited for a key or a
// password, and gives back what the kernel says to it. `typed` is the room
// it was typed into; the chat box wipes it afterwards. Turning a password
// into a key takes more than a second, so before that work starts, `say`
// shows a row that says so.
pub fn onboarding_secret(typed: &[u8], say: &mut dyn FnMut(&str)) -> Vec<String> {
    match waiting() {
        Waiting::Key => key_answer(typed),
        Waiting::Trying => vec![String::from(STILL_TRYING)],
        Waiting::NewPassword => new_password(typed),
        Waiting::SamePassword => same_password(typed, say),
        Waiting::Password => password_answer(typed, say),
        Waiting::Nothing | Waiting::Name => Vec::new(),
    }
}

// The answer to the question for the key. A key that is typed is tried with
// the one question that "ask" asks: it waits apart from the key kept before
// (see `secret.rs`), and the network's task asks the model with it. Its
// answer comes later, to `onboarding_tried`. A key that cannot be tried now
// is kept all the same, and a password to lock it with is asked for. Enter
// alone keeps a key that is locked on the disk as it is, or else notes that
// no key is wanted.
fn key_answer(typed: &[u8]) -> Vec<String> {
    if typed.is_empty() {
        if !locked_key().is_empty() {
            return finish(vec![String::from("Kernel: the key locked on the disk stays as it was. Type a line and press Enter.")]);
        }
        let mut rows = vec![String::from("Kernel: then no key is kept. Send \"setup\" to give one later. Type a line and press Enter.")];
        rows.extend(no_key_noted());
        return finish(rows);
    }
    let taken = trial_keep(typed);
    let signs = if taken == 1 { "sign" } else { "signs" };
    match errand_ask(Errand::KeyTry) {
        Ok(()) => {
            wait_for(Waiting::Trying);
            vec![format!("Kernel: I took a key of {} {}, and I am trying it with one question to the model.", taken, signs)]
        }
        Err(reason) => {
            trial_take();
            wait_for(Waiting::NewPassword);
            vec![
                format!("Kernel: I took a key of {} {}, but I cannot try it now, because {}.", taken, signs, reason),
                String::from(CANNOT_TELL),
                choose_password(),
            ]
        }
    }
}

// Takes the provider's answer to the try of a key: `sentence` says what came
// back, as for "ask", and `verdict` how the provider took the key (see
// `model.rs`). Gives back what the kernel says to it. Only a provider that
// does not know the key makes the kernel ask for it again; that key is not
// kept. With any other answer the key is kept, and a password to lock it
// with is asked for.
pub fn onboarding_tried(verdict: KeyVerdict, sentence: &str) -> Vec<String> {
    let mut rows = vec![format!("Kernel: {}", sentence)];
    if waiting() != Waiting::Trying {
        // Nothing waits for this answer: the key that was tried is not kept.
        trial_forget();
        return rows;
    }
    if verdict == KeyVerdict::Unknown {
        trial_forget();
        wait_for(Waiting::Key);
        rows.push(String::from("Kernel: the provider does not know that key, so I did not keep it."));
        rows.push(key_question());
        return rows;
    }
    trial_take();
    wait_for(Waiting::NewPassword);
    match verdict {
        KeyVerdict::Works => rows.push(format!("Kernel: the key works. Now choose a password of at least {} signs to lock it with.", PASSWORD_LEAST)),
        KeyVerdict::Known => {
            rows.push(String::from("Kernel: the provider knows the key, so I keep it."));
            rows.push(choose_password());
        }
        KeyVerdict::Unknown | KeyVerdict::NotTold => {
            rows.push(String::from(CANNOT_TELL));
            rows.push(choose_password());
        }
    }
    rows
}

// Notes in the notebook that no key is to be kept, unless it holds an answer
// about the key already, so that later starts do not ask again. Gives back a
// row only if that could not be noted.
fn no_key_noted() -> Vec<String> {
    if unsafe { KEY_ANSWERED } {
        return Vec::new();
    }
    match notebook_keep(KEY_ENTRY, &[]) {
        Ok(()) => {
            unsafe { KEY_ANSWERED = true };
            Vec::new()
        }
        Err(reason) => vec![format!("Kernel: I could not note that, because {}, so I will ask again at the next start.", reason)],
    }
}

// The first time the password is typed. It must have at least
// `PASSWORD_LEAST` signs. It is kept until it is typed the second time.
fn new_password(typed: &[u8]) -> Vec<String> {
    if typed.is_empty() {
        return for_this_start();
    }
    if typed.len() < PASSWORD_LEAST {
        return vec![format!(
            "Kernel: that password has only {} {}, and it needs at least {}. Choose a longer one.",
            typed.len(),
            if typed.len() == 1 { "sign" } else { "signs" },
            PASSWORD_LEAST
        )];
    }
    password_keep(typed);
    wait_for(Waiting::SamePassword);
    vec![String::from("Kernel: type the same password again and press Enter.")]
}

// Enter alone instead of a password: the key that was typed is kept in
// memory for this start only. If the notebook holds no answer about the key
// yet, it notes that no key is to be kept.
fn for_this_start() -> Vec<String> {
    password_forget();
    let mut rows = vec![String::from("Kernel: then the key is kept for this start only, not on the disk. Type a line and press Enter.")];
    rows.extend(no_key_noted());
    finish(rows)
}

// The second time the password is typed. If it is the same as the first,
// the key is locked with it and kept on the disk; if not, the password is
// asked for again.
fn same_password(typed: &[u8], say: &mut dyn FnMut(&str)) -> Vec<String> {
    if typed.is_empty() {
        return for_this_start();
    }
    if !password_same(typed) {
        password_forget();
        wait_for(Waiting::NewPassword);
        return vec![String::from("Kernel: the two passwords differ. Choose a password again and press Enter.")];
    }
    say("Kernel: locking the key with your password. This takes a second or two.");
    let locked = secret_lock();
    password_forget();
    let rows = match locked {
        Ok(locked) => match notebook_keep(KEY_ENTRY, &locked) {
            Ok(()) => {
                *locked_key() = locked;
                unsafe { KEY_ANSWERED = true };
                vec![
                    String::from("Kernel: the key is locked and kept on the disk. Each start will ask for the password."),
                    String::from(TYPE_A_LINE_ROW),
                ]
            }
            Err(reason) => vec![format!("Kernel: I could not keep the locked key, because {}, so the key lasts only until the machine is switched off.", reason)],
        },
        Err(reason) => vec![format!("Kernel: I could not lock the key, because {}, so it lasts only until the machine is switched off.", reason)],
    };
    finish(rows)
}

// The password typed at a start where a key is locked on the disk. The right
// one unlocks the key, which is then kept in memory until the machine is
// switched off. After a wrong one the kernel asks again; Enter alone always
// leads out.
fn password_answer(typed: &[u8], say: &mut dyn FnMut(&str)) -> Vec<String> {
    if typed.is_empty() {
        return finish(vec![String::from("Kernel: going on without the key. Send \"setup\" to lock a new one. Type a line and press Enter.")]);
    }
    say("Kernel: unlocking the key. This takes a second or two.");
    match secret_unlock(typed, locked_key()) {
        Ok(_) => finish(vec![String::from("Kernel: the key is unlocked, so \"ask\" works. Type a line and press Enter.")]),
        Err(reason) if reason == NOT_UNLOCKED => vec![
            String::from("Kernel: the key could not be unlocked: the password is wrong, or the locked key was changed."),
            String::from("Kernel: type the password again, or press Enter alone to go on without the key."),
        ],
        Err(reason) => finish(vec![
            format!("Kernel: I cannot unlock the key kept on the disk, because {}.", reason),
            String::from("Kernel: send \"setup\" to lock a new one. Type a line and press Enter."),
        ]),
    }
}
