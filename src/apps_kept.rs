//! Apps kept on the disk. An app the model made is kept in the notebook once
//! it has run to its end, so that it is still there after the machine was
//! switched off: its script, exactly as it ran, and a note with the request it
//! was made for. An app made for the same request again takes the place of the
//! one kept for it. At every start the kept apps are found again, and the
//! panel of apps, near the top left of the screen, lists them a page at a
//! time, the one kept last first. The model is told about them with every
//! line, and can run one again or turn the panel's page (see `tools.rs`).
//! Only the startup code and the main loop may call these functions.
//! Notes: `docs/apps.md` ("Keeping an app" and "The panel of apps").

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::app_box::SCRIPT_LIMIT;
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::look::look;
use crate::notebook::{THING_MOST, notebook_find, notebook_keep, notebook_names, notebook_ready};
use crate::screen::{screen_rectangle, screen_size, screen_text};
use crate::serial::serial_print;

// Each kept app is two things in the notebook, under names made from its
// number: "app 3 script" holds its script, and "app 3" a note about it. The
// script is kept first and the note last, so an app whose note is there had
// its whole script there first.
const APP_NAME_START: &str = "app ";
const SCRIPT_NAME_END: &str = " script";

// The highest number an app can have: nine digits, so that both names fit
// the notebook's 32 signs and the number fits its type.
const NUMBER_DIGITS_MOST: usize = 9;
const NUMBER_MOST: u32 = 999_999_999;

// The first byte of a note says what form the rest of it has, so that later
// forms can say more about an app. Form 1: the rest is the request, the few
// words that say what the app does.
const NOTE_FORM: u8 = 1;

// The longest request, in signs. A request read from the disk comes from
// outside the kernel, and no more of it than this is taken; the same holds
// for a request the model gives (see `tools.rs`). It was what was left of the
// chat box's line of 50 signs after the word `make` and its space.
pub const REQUEST_MOST: usize = 45;

// Every script the box takes fits in the notebook as one thing.
const _: () = assert!(SCRIPT_LIMIT <= THING_MOST);

// An app found in the notebook: its number, the request it was made for, and
// whether its script was found whole. Only apps with a whole script are
// listed; the others still hold on to their number.
struct KeptApp {
    number: u32,
    request: String,
    whole: bool,
}

// The kept apps, the one kept last first, and which page of them the panel
// shows, counted from 0. Only the startup code and the main loop may touch
// these.
static mut KEPT_APPS: Vec<KeptApp> = Vec::new();
static mut PAGE: usize = 0;

// Rust refuses a plain reference to a `static mut`, so this hands the list
// out through its address. As in `chat.rs`: after calling another function
// of this file, do not go on using a list fetched before the call.
fn kept_apps() -> &'static mut Vec<KeptApp> {
    unsafe { &mut *(&raw mut KEPT_APPS) }
}

// The name of an app's note, and of its script.
fn note_name(number: u32) -> String {
    format!("{}{}", APP_NAME_START, number)
}

fn script_name(number: u32) -> String {
    format!("{}{}{}", APP_NAME_START, number, SCRIPT_NAME_END)
}

// The number in the name of an app's note, such as 3 in "app 3": one to nine
// digits, without a 0 in front. Gives nothing for any other name.
fn note_number(name: &str) -> Option<u32> {
    let digits = name.strip_prefix(APP_NAME_START)?;
    if digits.is_empty() || digits.len() > NUMBER_DIGITS_MOST || digits.starts_with('0') || !digits.bytes().all(|sign| sign.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

// The request in a note read from the disk, which comes from outside the
// kernel: at most `REQUEST_MOST` bytes of it, with every byte that is not a
// plain sign turned into a dot. Gives nothing for a note of another form, or
// one without a request.
fn note_request(note: &[u8]) -> Option<String> {
    let (&form, rest) = note.split_first()?;
    if form != NOTE_FORM || rest.is_empty() {
        return None;
    }
    Some(rest.iter().take(REQUEST_MOST).map(|byte| if (b' '..=b'~').contains(byte) { *byte as char } else { '.' }).collect())
}

// Finds the apps kept in the notebook, says in the terminal which they are,
// and shows the panel of apps if any is kept. Call it once at startup, after
// the notebook is opened. When no app is kept, nothing is said and nothing
// is shown.
pub fn apps_kept_begin() {
    // The notebook gives its names in the order in which their things were
    // kept, the oldest first, and it knows only things it found whole: an
    // app's script that it knows is a whole script. An app counts from when
    // its script was kept.
    let names = notebook_names();
    let mut found: Vec<(Option<usize>, KeptApp)> = Vec::new();
    let mut trouble = String::new();
    for name in names.iter() {
        let Some(number) = note_number(name) else {
            continue;
        };
        let request = match notebook_find(name) {
            Ok(Some(note)) => match note_request(&note) {
                Some(request) => request,
                None => continue,
            },
            _ => continue,
        };
        let script = script_name(number);
        let place = names.iter().position(|other| *other == script);
        if place.is_none() {
            trouble.push_str(&format!("Apps: the script kept for \"{}\" is not whole, so that app is left out\r\n", request));
        }
        found.push((place, KeptApp { number, request, whole: place.is_some() }));
    }
    // The app whose script was kept last first, and apps without a whole
    // script last of all.
    found.sort_by(|(one, _), (other, _)| other.cmp(one));

    let apps = kept_apps();
    apps.clear();
    apps.extend(found.into_iter().map(|(_, app)| app));
    unsafe { PAGE = 0 };

    // The terminal lists them in one go, the newest first.
    let listed = apps.iter().filter(|app| app.whole).count();
    let mut said = String::new();
    if listed > 0 {
        said.push_str(&format!("Apps: {} {} kept on the disk:\r\n", listed, if listed == 1 { "is" } else { "are" }));
        for app in apps.iter().filter(|app| app.whole) {
            said.push_str(&format!("Apps: \"{}\"\r\n", app.request));
        }
    }
    said.push_str(&trouble);
    if !said.is_empty() {
        serial_print(&said);
    }
    apps_panel_again();
}

// Keeps an app that has just run to its end: its script, exactly as it ran,
// and a note with the request it was made for. An app made for exactly the
// same request as a kept one takes that one's number, so that its script
// takes the place of the old one; any other app gets the number after the
// highest. The script is read back, and the app counts as kept only if it
// comes back byte for byte. Then the panel shows its first page, with this
// app at the top. Gives back what the chat box is to say: nothing when the app
// was kept, or when there is no notebook it can be added to (the lines at
// startup have said why); the reason when keeping it failed. Only the main
// loop may call this.
pub fn app_keep(request: &str, script: &str) -> Option<String> {
    if !notebook_ready() {
        return None;
    }
    let apps = kept_apps();
    let same = apps.iter().find(|app| app.request == request).map(|app| app.number);
    let highest = apps.iter().map(|app| app.number).max().unwrap_or(0);
    let number = match same {
        Some(number) => number,
        None if highest < NUMBER_MOST => highest + 1,
        None => return Some(String::from("I could not keep the app, because the numbers for apps have run out.")),
    };

    // The script first, then read back.
    let script_kept = script_name(number);
    if let Err(reason) = notebook_keep(&script_kept, script.as_bytes()) {
        return Some(format!("I could not keep the app, because {}.", reason));
    }
    match notebook_find(&script_kept) {
        Ok(Some(back)) if back == script.as_bytes() => {}
        Ok(_) => return Some(String::from("I could not keep the app, because the disk did not give its script back as it was written.")),
        Err(reason) => return Some(format!("I could not keep the app, because {}.", reason)),
    }

    // Then the note, unless the app kept for the same request has it already.
    if same.is_none() {
        let mut note = Vec::with_capacity(1 + request.len());
        note.push(NOTE_FORM);
        note.extend_from_slice(request.as_bytes());
        if let Err(reason) = notebook_keep(&note_name(number), &note) {
            return Some(format!("I could not keep the app, because {}.", reason));
        }
    }

    // The app goes to the top of the list, whole, and the panel shows the
    // first page.
    let apps = kept_apps();
    apps.retain(|app| app.number != number);
    apps.insert(0, KeptApp { number, request: String::from(request), whole: true });
    unsafe { PAGE = 0 };
    serial_print(&format!("Apps: the app made for \"{}\" is kept on the disk\r\n", request));
    apps_panel_again();
    None
}

// The kept apps the model may run, by number and request, the one kept last
// first: what `chat_tools` in `tools.rs` lists with every line.
pub fn apps_listed() -> Vec<(u32, String)> {
    kept_apps().iter().filter(|app| app.whole).map(|app| (app.number, app.request.clone())).collect()
}

// How many pages the panel of apps has, and which of them it shows, both
// counted from 1. No pages while no app is listed.
pub fn apps_pages() -> (usize, usize) {
    let listed = kept_apps().iter().filter(|app| app.whole).count();
    let pages = listed.div_ceil(APPS_PANEL_STYLE.apps_on_a_page.max(1) as usize);
    (pages, unsafe { PAGE }.min(pages.saturating_sub(1)) + 1)
}

// The tool `turn_page`: shows the page of the panel of apps with this
// number, counted from 1, if there is one. Gives back what the kernel says:
// the page shown, or why the model's request was turned down.
pub fn apps_page_turn(page: u64) -> Result<String, String> {
    let (pages, _) = apps_pages();
    if pages == 0 {
        return Err(String::from("the model asked for another page of the panel of apps, but no app is kept."));
    }
    match usize::try_from(page) {
        Ok(page) if (1..=pages).contains(&page) => {
            unsafe { PAGE = page - 1 };
            apps_panel_again();
            Ok(format!("the panel of apps shows page {} of {}.", page, pages))
        }
        _ => Err(format!("the model asked for page {} of the panel of apps, but it has {} {}.", page, pages, if pages == 1 { "page" } else { "pages" })),
    }
}

// The request and the script of the kept app with this number, read from the
// notebook, so that the app can run again; or what the kernel says when it
// cannot be had. The script comes from the disk, and the box checks it like
// any script before it runs.
pub fn app_kept(number: u64) -> Result<(String, String), String> {
    let Some(app) = kept_apps().iter().find(|app| app.whole && u64::from(app.number) == number) else {
        return Err(format!("the model asked for app {}, but no kept app has that number.", number));
    };
    let request = app.request.clone();
    match notebook_find(&script_name(app.number)) {
        Ok(Some(script)) => match String::from_utf8(script) {
            Ok(script) => Ok((request, script)),
            Err(_) => Err(format!("I could not run the app made for \"{}\", because its script on the disk is not proper text.", request)),
        },
        Ok(None) => Err(format!("I could not run the app made for \"{}\", because its script is not on the disk.", request)),
        Err(reason) => Err(format!("I could not run the app made for \"{}\", because {}.", request, reason)),
    }
}

// How the panel of apps is laid out. Its sizes are decided here, in this one
// place, and its colours are those of the box that shows an app's text, from
// the look in use. From top to bottom it holds the frame, some empty room, a
// row that says which page is shown, a row for each app on that page, and the
// frame again.
struct AppsPanelStyle {
    // Where its top left corner is, in dots from the top left corner of the
    // screen.
    left: u32,
    top: u32,
    // How many dots it is across.
    width: u32,
    // How many dots thick the frame round it is.
    frame: u32,
    // How far the text stays from the frame, in dots.
    padding: u32,
    // How large a dot of a letter is painted (see `screen_text`).
    text_size: u32,
    // How many empty dots lie between two rows of text.
    row_gap: u32,
    // How many apps one page holds.
    apps_on_a_page: u32,
}

// Under the sentence near the top left corner, five apps a page, letters
// twice the size of their pictures. A row holds 47 signs, so a request of 45
// fits whole behind the "- " in front of it. The panel is 158 dots high; the
// box with an app's text lies under it, and the frame of a table beside it.
const APPS_PANEL_STYLE: AppsPanelStyle = AppsPanelStyle {
    left: 40,
    top: 80,
    width: 600,
    frame: 3,
    padding: 10,
    text_size: 2,
    row_gap: 4,
    apps_on_a_page: 5,
};

// How high the panel of apps is, in dots. A row is as high as a letter, plus
// the gap to the next row. The panel holds the row about the page and a full
// page of apps, whatever the page shown holds, so that it always has the
// same size.
fn apps_panel_height() -> u32 {
    let style = APPS_PANEL_STYLE;
    let row_height = style.text_size.saturating_mul(LETTER_HEIGHT).saturating_add(style.row_gap);
    let rows = style.apps_on_a_page.saturating_add(1);
    style.frame.saturating_mul(2).saturating_add(style.padding.saturating_mul(2)).saturating_add(rows.saturating_mul(row_height))
}

// Where the panel of apps sits: its left and top edges, and how many dots it
// is across and down. It is the same on every screen, whether or not any app
// is kept, so that the box with an app's text can go under it and the frame
// of a table beside it (see `screen.rs` and `drawing.rs`).
pub fn apps_panel_place() -> (u32, u32, u32, u32) {
    let style = APPS_PANEL_STYLE;
    (style.left, style.top, style.width, apps_panel_height())
}

// Paints the panel of apps as it is: the row that says which page is shown,
// and the apps on that page, in the look in use. Paints nothing while no app
// is listed, and nothing on a machine without a usable screen. The look calls
// it when it paints the whole screen again.
pub fn apps_panel_again() {
    if screen_size().is_none() {
        return;
    }
    let apps = kept_apps();
    let listed: Vec<&KeptApp> = apps.iter().filter(|app| app.whole).collect();
    if listed.is_empty() {
        return;
    }
    let style = APPS_PANEL_STYLE;
    let look = look();
    let row_height = style.text_size.saturating_mul(LETTER_HEIGHT).saturating_add(style.row_gap);
    let height = apps_panel_height();

    // The frame: the whole panel in the frame's colour first, then the
    // inside painted over it, smaller by the frame's thickness on each side.
    screen_rectangle(style.left, style.top, style.width, height, look.panel_frame);
    screen_rectangle(
        style.left.saturating_add(style.frame),
        style.top.saturating_add(style.frame),
        style.width.saturating_sub(style.frame.saturating_mul(2)),
        height.saturating_sub(style.frame.saturating_mul(2)),
        look.panel_inside,
    );

    // Which page: the one asked for, or the last if there are fewer pages
    // now.
    let on_a_page = style.apps_on_a_page.max(1) as usize;
    let pages = listed.len().div_ceil(on_a_page);
    let page = unsafe { PAGE }.min(pages - 1);
    let mut rows_said = Vec::new();
    rows_said.push(format!("Apps: page {} of {}", page + 1, pages));
    for app in listed.iter().skip(page * on_a_page).take(on_a_page) {
        rows_said.push(format!("- {}", app.request));
    }

    // Nothing may land outside the panel, and `screen_text` stops only at
    // the screen's edges. So each row is held to the panel here: only as
    // many signs of it are written as fit whole between the frame and the
    // empty room on both sides.
    let sign_width = style.text_size.saturating_mul(LETTER_WIDTH + 1);
    let text_width = style.width.saturating_sub(style.frame.saturating_mul(2)).saturating_sub(style.padding.saturating_mul(2));
    let room = if sign_width == 0 { 0 } else { (text_width / sign_width) as usize };
    let left = style.left.saturating_add(style.frame).saturating_add(style.padding);
    let mut top = style.top.saturating_add(style.frame).saturating_add(style.padding);
    for row in rows_said.iter() {
        let shown = match row.char_indices().nth(room) {
            Some((cut, _)) => &row[..cut],
            None => row.as_str(),
        };
        screen_text(left, top, shown, style.text_size, look.panel_text);
        top = top.saturating_add(row_height);
    }
}
