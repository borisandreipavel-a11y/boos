//! Named tables saved in the notebook. The notebook keeps the last whole
//! version of each document, and the drawing code fits it to the current screen.
//! Only the main loop handles the open document and its list.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::apps_kept::apps_panel_bounds;
use crate::chat::chat_edges;
use crate::drawing::{TABLE_TEXT_MOST, table_description, table_forget, table_name, table_read, table_rename, table_show};
use crate::letters::LETTER_HEIGHT;
use crate::look::look;
use crate::notebook::{NAME_MOST, notebook_find, notebook_keep, notebook_names};
use crate::screen::{app_box_bottom, screen_rectangle, screen_text};

const LEGACY_PREFIX: &str = "table ";
const PREFIX: &str = "document ";
const LEGACY_FORM: u8 = 1;
const NAMED_FORM: u8 = 2;
const DELETED_FORM: u8 = 3;
pub const DOCUMENT_NAME_MOST: usize = NAME_MOST - LEGACY_PREFIX.len();

const GAP: u32 = 20;
const FRAME: u32 = 3;
const PADDING: u32 = 4;
const SIZE: u32 = 2;
const LINE: u32 = SIZE * LETTER_HEIGHT + 2;
const PAGE_MOST: usize = 8;

#[derive(Clone)]
struct Document {
    key: String,
    name: String,
}

// The newest complete versions first. Only the main loop holds references
// to this list, and none cross a change to the list or a repaint.
static mut DOCUMENTS: Vec<Document> = Vec::new();
static mut PAGE: usize = 0;

fn documents() -> &'static mut Vec<Document> {
    unsafe { &mut *(&raw mut DOCUMENTS) }
}

fn valid_name(name: &str) -> bool {
    !name.is_empty() && name.len() <= DOCUMENT_NAME_MOST && name.bytes().all(|byte| (b' '..=b'~').contains(&byte))
}

fn checked_name(name: &str) -> Result<&str, String> {
    let name = name.trim();
    if valid_name(name) {
        Ok(name)
    } else {
        Err(format!("give the document a name of 1 to {} plain characters.", DOCUMENT_NAME_MOST))
    }
}

// A legacy record took its display name from the notebook key. A named
// record stores it with the table so the key stays put through a rename.
fn decode<'a>(key: &'a str, data: &'a [u8]) -> Option<(&'a str, &'a str)> {
    let (&form, rest) = data.split_first()?;
    let (name, text) = match form {
        LEGACY_FORM => (key.strip_prefix(LEGACY_PREFIX)?, rest),
        NAMED_FORM => {
            let (&length, rest) = rest.split_first()?;
            let (name, text) = rest.split_at_checked(length as usize)?;
            (core::str::from_utf8(name).ok()?, text)
        }
        _ => return None,
    };
    if !valid_name(name) || name.trim() != name || text.len() > TABLE_TEXT_MOST ||
        !text.iter().all(|&byte| matches!(byte, b'\n' | b'\r' | b' '..=b'~'))
    {
        return None;
    }
    Some((name, core::str::from_utf8(text).ok()?))
}

pub fn documents_begin() {
    let mut found = Vec::new();
    for key in notebook_names().into_iter().rev() {
        if !key.starts_with(PREFIX) && !key.starts_with(LEGACY_PREFIX) {
            continue;
        }
        if let Ok(Some(data)) = notebook_find(&key) {
            if let Some((name, _)) = decode(&key, &data) {
                let name = String::from(name);
                found.push(Document { key, name });
            }
        }
    }
    unsafe {
        DOCUMENTS = found;
        PAGE = 0;
    }
}

fn position(name: &str) -> Option<usize> {
    documents().iter().position(|saved| saved.name.eq_ignore_ascii_case(name))
}

fn find(name: &str) -> Result<(usize, Document), String> {
    let name = checked_name(name)?;
    let place = position(name).ok_or_else(|| format!("I could not find a document called \"{}\".", name))?;
    Ok((place, documents()[place].clone()))
}

fn new_key() -> Result<String, String> {
    // Includes removed documents, whose notebook keys still exist.
    let last = notebook_names().iter().filter_map(|key| key.strip_prefix(PREFIX)?.parse::<u64>().ok()).max().unwrap_or(0);
    let next = last.checked_add(1).ok_or_else(|| String::from("the notebook has run out of document numbers."))?;
    Ok(format!("{}{}", PREFIX, next))
}

fn remember(document: Document) {
    let list = documents();
    list.retain(|saved| saved.key != document.key);
    list.insert(0, document);
    unsafe { PAGE = 0 };
}

// The panel occupies the left column below the app's output and stops
// above the chat. The number of rows can change with the screen height.
struct Panel {
    left: u32,
    top: u32,
    width: u32,
    per_page: usize,
}

fn panel() -> Option<Panel> {
    let (right, chat_top) = chat_edges()?;
    let (left, _, apps_right, _) = apps_panel_bounds();
    let top = app_box_bottom() + GAP;
    let height = chat_top.checked_sub(top + GAP)?;
    let lines = height.checked_sub(2 * (FRAME + PADDING))? / LINE;
    if lines < 2 || apps_right > right {
        return None;
    }
    Some(Panel { left, top, width: apps_right - left, per_page: ((lines - 1) as usize).min(PAGE_MOST) })
}

fn per_page() -> usize {
    panel().map_or(PAGE_MOST, |place| place.per_page)
}

// The model can also tell the person what is on the current page. Sending
// one page keeps the request small even if many tables are on the disk.
pub fn documents_page() -> (usize, usize, Vec<String>) {
    let list = documents();
    let per_page = per_page();
    let pages = list.len().div_ceil(per_page);
    let shown = unsafe { PAGE }.min(pages.saturating_sub(1));
    let names = list.iter().skip(shown * per_page).take(per_page).map(|saved| saved.name.clone()).collect();
    (shown + 1, pages, names)
}

pub fn documents_turn(page: u64) -> Result<String, String> {
    let (_, pages, _) = documents_page();
    if page == 0 || page > pages as u64 {
        return Err(format!("there is no documents page {}. The list has {} pages.", page, pages));
    }
    unsafe { PAGE = page as usize - 1 };
    documents_paint();
    Ok(format!("The documents list shows page {} of {}.", page, pages))
}

pub fn documents_paint() {
    let Some(place) = panel() else { return };
    let (page, pages, names) = documents_page();
    let look = look();
    let height = 2 * (FRAME + PADDING) + (1 + place.per_page as u32) * LINE;
    if names.is_empty() {
        screen_rectangle(place.left, place.top, place.width, height, look.background);
        return;
    }
    screen_rectangle(place.left, place.top, place.width, height, look.panel_frame);
    screen_rectangle(place.left + FRAME, place.top + FRAME, place.width - 2 * FRAME, height - 2 * FRAME, look.panel_inside);
    let left = place.left + FRAME + PADDING;
    let top = place.top + FRAME + PADDING;
    screen_text(left, top, &format!("Documents: page {} of {}", page, pages), SIZE, look.panel_text);
    let open = table_name();
    for (row, name) in names.iter().enumerate() {
        let marker = if open.as_ref() == Some(name) { '>' } else { '-' };
        screen_text(left, top + (row as u32 + 1) * LINE, &format!("{} {}", marker, name), SIZE, look.panel_text);
    }
}

fn read(document: &Document) -> Result<String, String> {
    let data = notebook_find(&document.key)
        .map_err(|reason| format!("I could not read \"{}\", because {}.", document.name, reason))?;
    data.as_deref().and_then(|bytes| decode(&document.key, bytes))
        .filter(|(name, _)| *name == document.name)
        .map(|(_, text)| String::from(text))
        .ok_or_else(|| format!("the saved document \"{}\" could not be read as a table.", document.name))
}

fn keep(key: &str, name: &str, description: &str) -> Result<(), &'static str> {
    let mut data = Vec::with_capacity(2 + name.len() + description.len());
    data.extend_from_slice(&[NAMED_FORM, name.len() as u8]);
    data.extend_from_slice(name.as_bytes());
    data.extend_from_slice(description.as_bytes());
    notebook_keep(key, &data)
}

fn keep_version(document: Document, description: &str) -> Result<(), String> {
    keep(&document.key, &document.name, description)
        .map_err(|reason| format!("I could not save \"{}\", because {}.", document.name, reason))?;
    remember(document);
    Ok(())
}

// The drawing editor has already validated the one cell that changed.
// Report whether it needs to repaint the list after keeping the version.
pub fn document_keep_cell_edit(name: &str, description: &str) -> Result<bool, String> {
    let (place, document) = find(name)?;
    let list_changed = place != 0 || unsafe { PAGE != 0 };
    keep_version(document, description)?;
    Ok(list_changed)
}

// Validate the complete description before touching the notebook. Store
// even the rows that do not fit on this screen.
fn write(document: Document, description: &str, action: &str) -> Result<String, String> {
    let description: String = description.bytes().map(|byte| match byte {
        b'\n' | b'\r' | b' '..=b'~' => byte as char,
        b'\t' => ' ',
        _ => '.',
    }).collect();
    let (table, _, clipped) = table_read(&description, false).map_err(String::from)?;
    let name = document.name.clone();
    keep_version(document, &description)?;
    let said = format!("I {} \"{}\".", action, name);
    table_show(table, Some(name));
    Ok(with_fit(said, clipped))
}

fn with_fit(mut said: String, clipped: bool) -> String {
    if clipped {
        said.push_str(" Only part of the full document fits on this screen.");
    }
    said
}

pub fn document_save(name: &str, description: Option<&str>) -> Result<String, String> {
    let name = checked_name(name)?;
    if position(name).is_some() {
        return Err(format!("a document called \"{}\" already exists. Open it before editing it.", name));
    }
    let current;
    let description = match description {
        Some(text) => text,
        None => {
            current = table_description();
            if current.is_empty() {
                return Err(String::from("there is no table on screen to save."));
            }
            &current
        }
    };
    let document = Document { key: new_key()?, name: String::from(name) };
    write(document, description, "saved")
}

pub fn document_open(name: &str) -> Result<String, String> {
    let (place, document) = find(name)?;
    let text = read(&document)?;
    let (table, _, clipped) = table_read(&text, false)
        .map_err(|reason| format!("I could not open \"{}\": {}", document.name, reason))?;
    unsafe { PAGE = place / per_page() };
    let said = format!("I opened \"{}\".", document.name);
    table_show(table, Some(document.name));
    Ok(with_fit(said, clipped))
}

pub fn document_update(description: &str) -> Result<String, String> {
    let Some(name) = table_name() else {
        return Err(String::from("open a saved document before updating it."));
    };
    let (_, document) = find(&name)?;
    if description == table_description() {
        return Ok(format!("\"{}\" is already saved with those contents.", name));
    }
    write(document, description, "updated")
}

pub fn document_rename(name: &str, new_name: &str) -> Result<String, String> {
    let (place, mut document) = find(name)?;
    let new_name = checked_name(new_name)?;
    if new_name == document.name {
        return Ok(format!("\"{}\" already has that name.", document.name));
    }
    if position(new_name).is_some_and(|other| other != place) {
        return Err(format!("a document called \"{}\" already exists.", new_name));
    }
    let text = read(&document)?;
    keep(&document.key, new_name, &text)
        .map_err(|reason| format!("I could not rename \"{}\", because {}.", document.name, reason))?;
    let old_name = core::mem::replace(&mut document.name, String::from(new_name));
    remember(document);
    table_rename(&old_name, new_name);
    documents_paint();
    Ok(format!("I renamed \"{}\" to \"{}\".", old_name, new_name))
}

pub fn document_delete(name: &str) -> Result<String, String> {
    let (place, document) = find(name)?;
    notebook_keep(&document.key, &[DELETED_FORM])
        .map_err(|reason| format!("I could not remove \"{}\", because {}.", document.name, reason))?;
    let remaining = documents();
    remaining.remove(place);
    let last_page = remaining.len().div_ceil(per_page()).saturating_sub(1);
    unsafe { PAGE = PAGE.min(last_page) };
    if table_name().as_deref() == Some(document.name.as_str()) {
        table_forget();
    } else {
        documents_paint();
    }
    Ok(format!("I removed \"{}\" from the documents list.", document.name))
}
