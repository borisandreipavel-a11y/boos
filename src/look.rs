//! The look: the colours of everything the kernel draws on the screen, picked
//! from a short list. When the person asks for another look, the model picks
//! one with the tool `pick_look` (see `tools.rs`): the whole screen is painted
//! again in it at once, and it is kept in the notebook on the disk, so that
//! every later start shows it too. The onboarding lists the looks and asks
//! for the number of one once its questions about the key are over, if the
//! notebook holds no answer about the look yet: a number tries that look, and
//! Enter alone keeps it (see `onboarding.rs`). The line `setup` brings the
//! first look back at once, so that no look can leave the screen unreadable
//! (see `look_reset`). Sizes and places are not part of a look: they stay in
//! `CHAT_STYLE` in `chat.rs` and `PANEL_STYLE` in `screen.rs`. Only the
//! startup code and the main loop may call these functions. Notes:
//! `docs/screen.md` ("The look") and `docs/chat.md` ("Picking a look").

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

use crate::apps_kept::apps_panel_again;
use crate::chat::chat_paint;
use crate::notebook::{notebook_find, notebook_keep, notebook_ready};
use crate::screen::{Colour, screen_background, screen_panel_again};

// The name under which the look in use is kept in the notebook. The entry
// holds the look's name, such as "Night". An entry that holds no signs means
// that the question for a look was answered without picking one: the first
// look stays, and later starts do not ask again. `setup` keeps such an entry
// when the notebook holds another look (see `look_reset`).
const LOOK_ENTRY: &str = "look";

// One look: the colour of everything the kernel draws.
#[derive(Clone, Copy)]
pub struct Look {
    // The name the look is listed by, and kept under in the notebook.
    pub name: &'static str,
    // The whole screen behind everything, and the sentence near its top left
    // corner.
    pub background: Colour,
    pub sentence: Colour,
    // The chat box: its frame, the colour behind what was said and behind
    // the row being typed, and the letters of what the person and the kernel
    // said.
    pub chat_frame: Colour,
    pub chat_inside: Colour,
    pub chat_typing: Colour,
    pub chat_person: Colour,
    pub chat_kernel: Colour,
    // The box that shows an app's text (the panel): its frame, the colour
    // inside it, and its letters.
    pub panel_frame: Colour,
    pub panel_inside: Colour,
    pub panel_text: Colour,
}

// The looks, in the order of their numbers: the first is number 1, and it is
// the look every start begins with. In every look, letters stand out from
// what lies behind them by a contrast ratio of at least 4.5, and the frames
// from the screen around them by at least 3 (see docs/testing.md).
const LOOKS: [Look; 4] = [
    // A dark blue screen, light boxes with orange frames, black and dark
    // blue letters.
    Look {
        name: "Blue",
        background: Colour { red: 0, green: 40, blue: 90 },
        sentence: Colour { red: 255, green: 255, blue: 255 },
        chat_frame: Colour { red: 255, green: 150, blue: 0 },
        chat_inside: Colour { red: 232, green: 236, blue: 244 },
        chat_typing: Colour { red: 255, green: 255, blue: 255 },
        chat_person: Colour { red: 0, green: 0, blue: 0 },
        chat_kernel: Colour { red: 0, green: 60, blue: 140 },
        panel_frame: Colour { red: 255, green: 150, blue: 0 },
        panel_inside: Colour { red: 240, green: 240, blue: 240 },
        panel_text: Colour { red: 0, green: 0, blue: 0 },
    },
    // An almost black screen, dark grey boxes with grey-blue frames, light
    // letters.
    Look {
        name: "Night",
        background: Colour { red: 18, green: 18, blue: 24 },
        sentence: Colour { red: 210, green: 210, blue: 220 },
        chat_frame: Colour { red: 110, green: 125, blue: 170 },
        chat_inside: Colour { red: 36, green: 38, blue: 48 },
        chat_typing: Colour { red: 52, green: 55, blue: 68 },
        chat_person: Colour { red: 240, green: 240, blue: 240 },
        chat_kernel: Colour { red: 140, green: 190, blue: 255 },
        panel_frame: Colour { red: 110, green: 125, blue: 170 },
        panel_inside: Colour { red: 36, green: 38, blue: 48 },
        panel_text: Colour { red: 240, green: 240, blue: 240 },
    },
    // A white screen, white boxes with grey frames, black and dark brown
    // letters, like a printed page.
    Look {
        name: "Paper",
        background: Colour { red: 246, green: 244, blue: 236 },
        sentence: Colour { red: 30, green: 30, blue: 30 },
        chat_frame: Colour { red: 120, green: 120, blue: 120 },
        chat_inside: Colour { red: 255, green: 255, blue: 255 },
        chat_typing: Colour { red: 236, green: 236, blue: 230 },
        chat_person: Colour { red: 0, green: 0, blue: 0 },
        chat_kernel: Colour { red: 130, green: 40, blue: 20 },
        panel_frame: Colour { red: 120, green: 120, blue: 120 },
        panel_inside: Colour { red: 255, green: 255, blue: 255 },
        panel_text: Colour { red: 0, green: 0, blue: 0 },
    },
    // A black screen, black boxes with yellow frames, white and yellow
    // letters: the easiest to read.
    Look {
        name: "Contrast",
        background: Colour { red: 0, green: 0, blue: 0 },
        sentence: Colour { red: 255, green: 255, blue: 0 },
        chat_frame: Colour { red: 255, green: 255, blue: 0 },
        chat_inside: Colour { red: 0, green: 0, blue: 0 },
        chat_typing: Colour { red: 40, green: 40, blue: 40 },
        chat_person: Colour { red: 255, green: 255, blue: 255 },
        chat_kernel: Colour { red: 255, green: 255, blue: 0 },
        panel_frame: Colour { red: 255, green: 255, blue: 0 },
        panel_inside: Colour { red: 0, green: 0, blue: 0 },
        panel_text: Colour { red: 255, green: 255, blue: 255 },
    },
];

// Which look is in use, as its place in the list, counted from 0; whether the
// kernel waits for the number of a look; whether a look was tried since it
// asked, so that it is shown but not kept yet; which look the notebook holds,
// if it holds one this kernel knows; whether the notebook holds an answer
// about the look at all: a look this kernel knows, or an entry with no signs;
// and, when `setup` could not keep the first look on the disk, why, and the
// place of the look the notebook still holds, until that is said. Nothing
// protects these against a second task, so only the startup code and the
// main loop may touch them.
static mut IN_USE: usize = 0;
static mut ASKING: bool = false;
static mut TRIED: bool = false;
static mut KEPT: Option<usize> = None;
static mut ANSWERED: bool = false;
static mut RESET_TROUBLE: Option<(&'static str, usize)> = None;

// The look in use. Every piece of drawing asks for it each time it paints.
pub fn look() -> Look {
    // `IN_USE` is only ever set to a place in the list. Should that fail,
    // the first look stands in, rather than the kernel stopping.
    let in_use = unsafe { IN_USE };
    *LOOKS.get(in_use).unwrap_or(&LOOKS[0])
}

// The look in use, named the way the kernel says it: "look 2, Night".
fn look_named() -> String {
    place_named(unsafe { IN_USE })
}

// A look of the list, by its place, named the way the kernel says it.
fn place_named(place: usize) -> String {
    format!("look {}, {}", place + 1, LOOKS.get(place).unwrap_or(&LOOKS[0]).name)
}

// Whether the kernel waits for the number of a look. While it does, the next
// line that is sent is the answer.
pub fn look_asking() -> bool {
    unsafe { ASKING }
}

// Whether the onboarding should ask for a look when its questions about the
// key are over: the answer can be kept, and either the notebook holds none
// yet or the questions are asked again because of `setup`.
pub fn look_due(setting_up: bool) -> bool {
    notebook_ready() && (setting_up || !unsafe { ANSWERED })
}

// The question for a look, at the end of the onboarding: lists the looks and
// asks for the number of one. Gives back the
// row that says so. From then on the next line that is sent is the answer
// (see `look_answer`). With four looks the row fits on one row of the chat
// box on a screen 1280 dots wide.
pub fn look_question() -> String {
    unsafe {
        ASKING = true;
        TRIED = false;
    }
    let mut list = String::new();
    for (place, one) in LOOKS.iter().enumerate() {
        if place > 0 {
            list.push_str(", ");
        }
        list.push_str(&format!("{} {}", place + 1, one.name));
    }
    format!("Kernel: pick a look by number: {}. Enter alone keeps this one.", list)
}

// Takes the answer to the question for a look: the line that was sent, which
// may be empty. A number from the list puts that look in use at once, and the
// kernel waits for the next answer, so that another look can be tried. Enter
// alone ends the question and keeps the look in use (see `look_keep`). Gives
// back what the kernel says, and whether the look in use changed, in which
// case the whole screen must be painted again (`look_paint`).
pub fn look_answer(line: &str) -> (Vec<String>, bool) {
    // Spaces at either end do not count.
    let given = line.trim();
    if given.is_empty() {
        unsafe { ASKING = false };
        return (look_keep(), false);
    }
    // Only digits make a number here. A number too large for the kernel to
    // hold is no number of a look either.
    let number = if given.bytes().all(|byte| byte.is_ascii_digit()) { given.parse::<usize>().ok() } else { None };
    match number {
        Some(number) if (1..=LOOKS.len()).contains(&number) => {
            let changed = unsafe { IN_USE } != number - 1;
            unsafe {
                IN_USE = number - 1;
                TRIED = true;
            }
            (vec![format!("Kernel: this is {}. Enter alone keeps it; another number tries that one.", look_named())], changed)
        }
        _ => (vec![format!("Kernel: that is not the number of a look. Type 1 to {}, or Enter alone to keep this one.", LOOKS.len())], false),
    }
}

// Enter alone at the question for a look: the look in use stays. It is kept
// in the notebook if it was tried and the notebook does not hold it already;
// if that fails, it lasts until the machine is switched off. If nothing is
// kept and the notebook holds no answer about the look yet, an entry with no
// signs notes the answer, so that later starts do not ask again. Gives back
// what the kernel says.
fn look_keep() -> Vec<String> {
    let in_use = unsafe { IN_USE };
    let (tried, kept, answered) = unsafe { (TRIED, KEPT, ANSWERED) };
    if tried && kept != Some(in_use) {
        return match notebook_keep(LOOK_ENTRY, look().name.as_bytes()) {
            Ok(()) => {
                unsafe {
                    KEPT = Some(in_use);
                    ANSWERED = true;
                }
                vec![format!("Kernel: {}, is kept on the disk. Type a line and press Enter.", look_named())]
            }
            Err(reason) => vec![
                format!("Kernel: I could not keep {}, because {}.", look_named(), reason),
                String::from("Kernel: so it lasts only until the machine is switched off. Type a line and press Enter."),
            ],
        };
    }
    let mut rows = vec![format!("Kernel: {}, stays. Type a line and press Enter.", look_named())];
    if !answered && notebook_ready() {
        match notebook_keep(LOOK_ENTRY, &[]) {
            Ok(()) => unsafe { ANSWERED = true },
            Err(reason) => rows.push(format!("Kernel: I could not note that, because {}, so I will ask again at the next start.", reason)),
        }
    }
    rows
}

// Puts the look kept in the notebook in use. Called once at startup, once the
// notebook is opened, before the greeting, while the kernel's own lines still
// cover the screen: the whole usual picture is painted in the look in use
// when the start is over (see `lines.rs`). Gives back a row to say when the
// kept look cannot be used. A look that cannot be used counts as no answer,
// so that the onboarding asks again.
pub fn look_begin() -> Option<String> {
    match notebook_find(LOOK_ENTRY) {
        // Nothing kept: the first look stays, and the question is still to
        // be asked.
        Ok(None) => None,
        // An entry that holds no signs: the question was answered, and the
        // first look stays.
        Ok(Some(kept)) if kept.is_empty() => {
            unsafe { ANSWERED = true };
            None
        }
        Ok(Some(kept)) => {
            // What comes from the disk comes from outside the kernel. It is
            // only compared with the names in the list, and never shown.
            match LOOKS.iter().position(|one| one.name.as_bytes() == kept.as_slice()) {
                Some(place) => {
                    unsafe {
                        IN_USE = place;
                        KEPT = Some(place);
                        ANSWERED = true;
                    }
                    None
                }
                None => Some(format!("Kernel: the look kept on the disk is not one I know, so the screen keeps {}.", look_named())),
            }
        }
        Err(reason) => Some(format!("Kernel: I cannot read the look kept on the disk, because {}.", reason)),
    }
}

// The line `setup`: puts the first look in use at once, before anything is
// asked, and paints the whole screen again in it, so that every question
// after it can be read, whatever look was in use. If the notebook holds
// another look, an entry with no signs is kept under `look` at once, so that
// the next start shows the first look too, even when the machine is switched
// off before the questions are over; the question for a look at the end of
// `setup` can keep another. If that entry cannot be written, the first look
// lasts until the machine is switched off, and `look_reset_trouble` says so
// when the questions are over. With the first look in use and no other in the
// notebook, nothing changes and nothing is written.
pub fn look_reset() {
    let changed = unsafe { IN_USE } != 0;
    unsafe { IN_USE = 0 };
    if changed {
        look_paint();
    }
    match unsafe { KEPT } {
        Some(place) if place != 0 => match notebook_keep(LOOK_ENTRY, &[]) {
            // The notebook now says what Enter alone says at a first start:
            // no look was picked, so the first look shows. `KEPT` follows
            // it; otherwise a look picked again at the end of `setup` would
            // count as kept already, and would not be written.
            Ok(()) => unsafe {
                KEPT = None;
                ANSWERED = true;
            },
            Err(reason) => unsafe { RESET_TROUBLE = Some((reason, place)) },
        },
        // Nothing kept, an entry with no signs, a name the kernel does not
        // know, or the first look: the next start shows the first look
        // already.
        _ => {}
    }
}

// What the kernel says, once the questions of `setup` are over, when the
// first look could not be kept on the disk there: why, and which look the
// next start will show instead. Gives back nothing otherwise, and nothing the
// second time it is asked.
pub fn look_reset_trouble() -> Vec<String> {
    let Some((reason, place)) = (unsafe { RESET_TROUBLE }) else {
        return Vec::new();
    };
    unsafe { RESET_TROUBLE = None };
    vec![
        format!("Kernel: I could not keep {}, on the disk, because {}.", place_named(0), reason),
        format!("Kernel: so the next start shows {}, again.", place_named(place)),
    ]
}

// Paints the whole screen again in the look in use: the background and the
// sentence, then the chat box with everything in it, then the box with an
// app's text, if an app has shown one, and the panel of apps, if any app is
// kept. The background is painted first because it covers everything.
pub fn look_paint() {
    screen_background();
    chat_paint();
    screen_panel_again();
    apps_panel_again();
}

// The looks as the model is told about them with the tool `pick_look` (see
// `tools.rs`): each with its number, its name and a few words on its colours;
// and how many there are.
pub fn looks_told() -> (String, usize) {
    let mut told = String::new();
    for (place, one) in LOOKS.iter().enumerate() {
        if place > 0 {
            told.push_str("; ");
        }
        told.push_str(&format!("{} {} ({})", place + 1, one.name, LOOK_WORDS.get(place).unwrap_or(&"")));
    }
    (told, LOOKS.len())
}

// A few words on each look's colours, in the order of the list.
const LOOK_WORDS: [&str; 4] = [
    "a dark blue screen, light boxes with orange frames",
    "an almost black screen, dark grey boxes, light letters",
    "a white screen, white boxes with grey frames, like a printed page",
    "black and yellow, the easiest to read",
];

// The tool `pick_look`: puts the look with this number in use at once, and
// keeps it in the notebook, so that later starts show it too. Gives back what
// the kernel says, and whether the look in use changed, in which case the
// whole screen must be painted again (`look_paint`). A number that is not on
// the list changes nothing: the kernel says why, as the model's request
// turned down. Without a notebook that can be added to, the look lasts until
// the machine is switched off.
pub fn look_pick(number: u64) -> Result<(String, bool), String> {
    let Some(place) = number.checked_sub(1).and_then(|place| usize::try_from(place).ok()).filter(|place| *place < LOOKS.len()) else {
        return Err(format!("the model asked for look {}, but there are only {} looks.", number, LOOKS.len()));
    };
    let changed = unsafe { IN_USE } != place;
    unsafe { IN_USE = place };
    let said = if !notebook_ready() {
        format!("this is {}. It lasts until the machine is switched off, because there is no notebook to keep it in.", look_named())
    } else if unsafe { KEPT } == Some(place) {
        format!("this is {}, which is kept on the disk already.", look_named())
    } else {
        match notebook_keep(LOOK_ENTRY, look().name.as_bytes()) {
            Ok(()) => {
                unsafe {
                    KEPT = Some(place);
                    ANSWERED = true;
                }
                format!("this is {}. It is kept on the disk.", look_named())
            }
            Err(reason) => format!("this is {}, but I could not keep it, because {}, so it lasts only until the machine is switched off.", look_named(), reason),
        }
    };
    Ok((said, changed))
}
