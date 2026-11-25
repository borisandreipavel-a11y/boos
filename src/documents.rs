//! Documents: tables the model described, and documents of text and tables
//! it wrote, kept on the disk as their lines, so that they can be opened and
//! changed again by a wish.
//! Where documents can be kept (a notebook that can be added to, and a screen
//! with room for the frame of a table), every table that is drawn is kept at
//! once as a document: its lines as the model wrote them, under a number, and
//! named by its title. A change is a new version of the same document: only
//! the newest counts, and the older stay on the disk. The document the frame
//! shows is the open one: its lines go with every line to the model, so that
//! it can be changed, and a change is done only to the open document. A panel
//! on the left lists the documents used last. A table drawn from a kept file
//! that was opened for the line (see `files.rs`) is a document made from that
//! file, and its note says which; opening the file again opens it. Only the
//! startup code and the main loop may call these functions.
//! Notes: `docs/screen.md` ("Documents"), `docs/tools.md` (`draw_table`,
//! `open_document` and `open_file`) and `docs/notebook.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::chat::chat_box_place;
use crate::drawing::{
    Charted, Drawn, NotDrawn, Written, charting_document, charting_fit, charting_lines_kept, charting_refused, charting_said, charting_show,
    charting_text, drawing_clear, drawing_document, drawing_fit, drawing_lines_kept, drawing_refused, drawing_room, drawing_said, drawing_show,
    drawing_text, writing_document, writing_laid, writing_lines_kept, writing_pages, writing_put, writing_refused, writing_said, writing_show,
    writing_text,
};
use crate::files::{file_opening_forget, file_opening_number};
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::look::look;
use crate::notebook::{notebook_find, notebook_keep, notebook_names, notebook_ready};
use crate::screen::{screen_panel_place, screen_rectangle, screen_size, screen_text};
use crate::serial::serial_print;

// Each kept document is things in the notebook under names made from its
// number: "document 3 v2" holds the lines of its second version, and
// "document 3" a note that says which version is the newest. A version's
// lines are kept first and the note last, so the version a note names was on
// the disk whole first.
const NAME_START: &str = "document ";
const VERSION_MARK: &str = " v";

// The highest number a document or a version can have: nine digits, so that
// both names fit the notebook's 32 signs ("document 999999999 v999999999" is
// 29) and the number fits its type.
const NUMBER_DIGITS_MOST: usize = 9;
const NUMBER_MOST: u32 = 999_999_999;

// The first byte of a note says what form the rest has, so that later forms
// can say more. Form 1: a byte for the kind of document (1, a table, written
// with `draw_table`; 2, a document of text and tables, written with
// `write_document`), the newest version's number in four bytes, lowest
// first, and the document's name. Form 2, for a document made from a kept
// file (see `files.rs`): the same, with the file's number in four bytes,
// lowest first, between the version's number and the name. A document made
// from no file is kept in form 1, as before form 2 existed. The kind is the
// newest version's: a change written with the other tool changes it.
const NOTE_FORM: u8 = 1;
const NOTE_FORM_FILE: u8 = 2;
const KIND_TABLE: u8 = 1;
const KIND_TEXT: u8 = 2;
const KIND_CHART: u8 = 3;
const NOTE_HEAD: usize = 6;
const NOTE_HEAD_FILE: usize = 10;

// The kind of a document: what its lines are read and drawn as.
#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Table,
    Text,
    Chart,
}

impl Kind {
    fn byte(self) -> u8 {
        match self {
            Kind::Table => KIND_TABLE,
            Kind::Text => KIND_TEXT,
            Kind::Chart => KIND_CHART,
        }
    }

    fn of_byte(byte: u8) -> Option<Kind> {
        match byte {
            KIND_TABLE => Some(Kind::Table),
            KIND_TEXT => Some(Kind::Text),
            KIND_CHART => Some(Kind::Chart),
            _ => None,
        }
    }
}

// What came of drawing a kept document in the frame: a table, a document of
// text laid out in pages, or a chart.
enum Opened {
    Table(Drawn),
    Text(Written),
    Chart(Charted),
}

impl Opened {
    // What the kernel says behind "I opened ...": rows or columns that did
    // not fit, for a table; the pages, for a document of text; the bars,
    // for a chart.
    fn fit(&self) -> String {
        match self {
            Opened::Table(drawn) => drawing_fit(drawn),
            Opened::Text(written) => writing_pages(written),
            Opened::Chart(charted) => charting_fit(charted),
        }
    }
}

// The longest name, in signs: a document is named by its title, and the panel
// of documents shows a name of 45 signs whole behind the "- " in front of it.
const NAME_MOST: usize = 45;

// A document found in the notebook or kept since the start: its number, the
// number of its newest version, its name (nothing for a table without a
// title), whether that version's lines were found whole, the number of the
// kept file it was made from, if it was, and its kind. Only documents whose
// lines are whole are listed; the others still hold on to their number.
struct KeptDocument {
    number: u32,
    version: u32,
    name: String,
    whole: bool,
    file: Option<u32>,
    kind: Kind,
}

// The kept documents, the one used last first: kept, changed or opened. Only
// the startup code and the main loop may touch it.
static mut DOCUMENTS: Vec<KeptDocument> = Vec::new();

// Rust refuses a plain reference to a `static mut`, so this hands the list
// out through its address. As in `chat.rs`: after calling another function
// of this file, do not go on using a list fetched before the call.
fn kept_documents() -> &'static mut Vec<KeptDocument> {
    unsafe { &mut *(&raw mut DOCUMENTS) }
}

// The open document: the kept document the frame shows, by its number, with
// the lines of its newest version, which go with every line to the model.
// Nothing is open after a start, after `setup`, and while the frame shows a
// table that is not kept. It is taken out of its place and put back by value.
struct OpenDocument {
    number: u32,
    lines: String,
}
static mut OPEN: Option<OpenDocument> = None;

fn open_take() -> Option<OpenDocument> {
    unsafe { (*(&raw mut OPEN)).take() }
}

fn open_put(open: Option<OpenDocument>) {
    unsafe { OPEN = open };
}

fn open_number() -> Option<u32> {
    let open = open_take();
    let number = open.as_ref().map(|open| open.number);
    open_put(open);
    number
}

// The names of a document's note and of a version's lines.
fn note_name(number: u32) -> String {
    format!("{}{}", NAME_START, number)
}

fn lines_name(number: u32, version: u32) -> String {
    format!("{}{}{}{}", NAME_START, number, VERSION_MARK, version)
}

// The number in the name of a document's note, such as 3 in "document 3":
// one to nine digits, without a 0 in front. Gives nothing for any other name,
// such as that of a version's lines.
fn note_number(name: &str) -> Option<u32> {
    let digits = name.strip_prefix(NAME_START)?;
    if digits.is_empty() || digits.len() > NUMBER_DIGITS_MOST || digits.starts_with('0') || !digits.bytes().all(|sign| sign.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

// A name made fit to be kept, listed and shown: every byte that is not a plain
// sign becomes a dot, as in every text from outside, spaces at either end go,
// and no more than `NAME_MOST` signs are kept.
fn name_cleaned(bytes: &[u8]) -> String {
    let plain: String = bytes.iter().map(|byte| if (b' '..=b'~').contains(byte) { *byte as char } else { '.' }).collect();
    let kept: String = plain.trim().chars().take(NAME_MOST).collect();
    String::from(kept.trim_end())
}

// A note read from the disk, which comes from outside the kernel: the newest
// version's number, the name, cleaned and cut, for form 2 the number of the
// file the document was made from, and the kind. Gives nothing for a note of
// another form or kind, or one that names no version or no file.
fn note_read(note: &[u8]) -> Option<(u32, String, Option<u32>, Kind)> {
    let (head, file) = match note.first() {
        Some(&NOTE_FORM) => (NOTE_HEAD, None),
        Some(&NOTE_FORM_FILE) if note.len() >= NOTE_HEAD_FILE => {
            let file = u32::from_le_bytes([note[6], note[7], note[8], note[9]]);
            if file == 0 || file > NUMBER_MOST {
                return None;
            }
            (NOTE_HEAD_FILE, Some(file))
        }
        _ => return None,
    };
    if note.len() < head {
        return None;
    }
    let kind = Kind::of_byte(note[1])?;
    let version = u32::from_le_bytes([note[2], note[3], note[4], note[5]]);
    if version == 0 || version > NUMBER_MOST {
        return None;
    }
    Some((version, name_cleaned(&note[head..]), file, kind))
}

// The name a document is listed and shown by: its own, or "document 3" for
// one whose table has no title.
fn name_shown(document: &KeptDocument) -> String {
    if document.name.is_empty() { format!("document {}", document.number) } else { document.name.clone() }
}

// How the kernel calls a document in what it says: `document 3, "Planets"`,
// or `document 3` for one whose table has no title.
fn called(document: &KeptDocument) -> String {
    if document.name.is_empty() {
        format!("document {}", document.number)
    } else {
        format!("document {}, \"{}\"", document.number, document.name)
    }
}

// Finds the documents kept in the notebook, and says in the terminal which
// they are. Call it once at startup, after the notebook is opened. Nothing is
// open then. When no document is kept, nothing is said.
pub fn documents_begin() {
    open_put(None);
    if !notebook_ready() {
        return;
    }
    // The notebook gives its names in the order in which their things were
    // kept, the oldest first; a note is kept again with every version, so the
    // document changed last comes last.
    let names = notebook_names();
    let mut found: Vec<(usize, KeptDocument)> = Vec::new();
    let mut trouble = String::new();
    for (place, name) in names.iter().enumerate() {
        let Some(number) = note_number(name) else {
            continue;
        };
        let read = match notebook_find(name) {
            Ok(Some(note)) => note_read(&note),
            _ => None,
        };
        let Some((version, kept_name, file, kind)) = read else {
            continue;
        };
        let lines = lines_name(number, version);
        let document = KeptDocument { number, version, name: kept_name, whole: names.iter().any(|other| *other == lines), file, kind };
        if !document.whole {
            trouble.push_str(&format!("Documents: {}: its lines are not whole, so it is left out\r\n", called(&document)));
        }
        found.push((place, document));
    }
    found.sort_by(|(one, _), (other, _)| other.cmp(one));

    let documents = kept_documents();
    documents.clear();
    documents.extend(found.into_iter().map(|(_, document)| document));

    let listed = documents.iter().filter(|document| document.whole).count();
    let mut said = String::new();
    if listed > 0 {
        said.push_str(&format!("Documents: {} {} kept on the disk:\r\n", listed, if listed == 1 { "is" } else { "are" }));
        for document in documents.iter().filter(|document| document.whole) {
            said.push_str(&format!("Documents: {}\r\n", called(document)));
        }
    }
    said.push_str(&trouble);
    if !said.is_empty() {
        serial_print(&said);
    }
}

// Whether documents can be kept: a notebook that can be added to, and a
// screen with room for the frame of a table.
pub fn documents_usable() -> bool {
    notebook_ready() && drawing_room().is_some()
}

// The kept documents the model may open, by number and name, the one used
// last first: what the tool `open_document` lists with every line (see
// `tools.rs`). None where documents cannot be kept.
pub fn documents_listed() -> Vec<(u32, String)> {
    if !documents_usable() {
        return Vec::new();
    }
    kept_documents().iter().filter(|document| document.whole).map(|document| (document.number, name_shown(document))).collect()
}

// What the model is told about the open document, behind the instruction
// text of every request for a line (see `model.rs`): which it is, how it is
// changed, and the lines of its newest version. Nothing while none is open.
pub fn documents_told() -> String {
    let Some(number) = open_number() else {
        return String::new();
    };
    let Some(document) = kept_documents().iter().find(|document| document.number == number) else {
        return String::new();
    };
    let named = called(document);
    let kind = document.kind;
    let open = open_take();
    let lines = open.as_ref().map(|open| open.lines.clone()).unwrap_or_default();
    open_put(open);
    match kind {
        Kind::Table => format!(
            "\n\nThe document open on the screen is {}. To change it, write its whole table again with draw_table, beginning with the line document {}. Its lines now:\n{}",
            named, number, lines
        ),
        Kind::Text => format!(
            "\n\nThe document open on the screen is {}, a document of text and tables. To change it, write it whole again with write_document, beginning with the line document {}. Its lines now:\n{}",
            named, number, lines
        ),
        Kind::Chart => format!(
            "\n\nThe document open on the screen is {}, a bar chart. To change it, write it whole again with draw_chart, beginning with the line document {}. Its lines now:\n{}",
            named, number, lines
        ),
    }
}

// What the model asked for with `draw_table`, `write_document` or
// `draw_chart`, as
// `tool_wanted` in `tools.rs` compares it so that nothing is done twice for
// one line: the text as the kernel reads it, and for a change of a kept
// document, which document was open when it was asked for. So a change that
// was not done because its document was not open, and whose document the
// kernel opened instead, may be asked for again once it is open; a new
// document asked for again is the same thing again, and is not kept twice.
// What any other tool was asked for is given back as it is.
pub fn documents_wanted(tool: &str, text: String) -> String {
    let asked = match tool {
        "draw_table" => drawing_document(&text),
        "write_document" => writing_document(&text),
        "draw_chart" => charting_document(&text),
        _ => return text,
    };
    match asked {
        Some(asked) if asked > 0 => format!("{}\nwhile open: {}", text, open_number().unwrap_or(0)),
        _ => text,
    }
}

// The kept document whose lines are whole with this number, if there is one.
fn kept_number(asked: u64) -> Option<u32> {
    kept_documents().iter().find(|document| document.whole && u64::from(document.number) == asked).map(|document| document.number)
}

// The tool `draw_table` where documents can be kept: a table.
pub fn document_draw(inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    document_made(Kind::Table, inputs, cut_off)
}

// The tool `write_document`: a document of text and tables. It is offered
// only where documents can be kept (see `tools.rs`).
pub fn document_written(inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    if !documents_usable() {
        return Err(String::from("the model asked to write a document, but documents cannot be kept on this machine."));
    }
    document_made(Kind::Text, inputs, cut_off)
}

// The tool `draw_chart`: a bar chart. It is offered only where documents can
// be kept (see `tools.rs`).
pub fn document_charted(inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    if !documents_usable() {
        return Err(String::from("the model asked to draw a chart, but documents cannot be kept on this machine."));
    }
    document_made(Kind::Chart, inputs, cut_off)
}

// A document drawn or written by the model. Reads what the model gave the
// tool. Lines whose `document` line names a kept document change it, and
// only the open one: another is opened instead, and the model is asked again
// with its lines. A change that did not come whole is not drawn, and the
// document stays as it was. Anything else is a new document: one that did
// not come whole is drawn as far as it came, but not kept. A document drawn
// whole, or with rows or columns that did not fit, is kept with all of its
// lines, as the tool's kind, and is the open document from then on. Gives
// back what the kernel says, and whether it was drawn whole, or what it says
// when it turned the model's request down.
fn document_made(kind: Kind, inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    let (text, whole) = match kind {
        Kind::Table => drawing_text(inputs, cut_off)?,
        Kind::Text => writing_text(inputs, cut_off)?,
        Kind::Chart => charting_text(inputs, cut_off)?,
    };
    let asked = match kind {
        Kind::Table => drawing_document(&text),
        Kind::Text => writing_document(&text),
        Kind::Chart => charting_document(&text),
    };
    let changes = match asked {
        Some(asked) if asked > 0 => match kept_number(asked) {
            Some(number) => Some(number),
            None => return Err(format!("the model asked to change document {}, but no kept document has that number.", asked)),
        },
        _ => None,
    };
    if let Some(number) = changes {
        // A change that did not come whole changes nothing, not even which
        // document is open: an answer that broke off ends the line, so the
        // model would not see the lines of a document opened for it.
        if !whole {
            return Err(match kind {
                Kind::Table => format!("the new table for document {} was cut off, so I left the document as it was.", number),
                Kind::Text => format!("the new lines for document {} were cut off, so I left the document as it was.", number),
                Kind::Chart => format!("the new chart for document {} was cut off, so I left the document as it was.", number),
            });
        }
        if open_number() != Some(number) {
            open_inner(number)?;
            return Err(format!(
                "the model asked to change document {}, which was not open, so I did not change it; I opened it, and its lines go with the next ask.",
                number
            ));
        }
    }
    let (mut said, drawn_whole, title_written) = match kind {
        Kind::Table => {
            let drawn = drawing_show(&text).map_err(|not| drawing_refused(not, whole))?;
            let said = drawing_said(&drawn, whole);
            let drawn_whole = drawn.whole();
            (said, drawn_whole, drawn.title_written)
        }
        Kind::Text => {
            let written = writing_show(&text).map_err(|not| writing_refused(not, whole))?;
            let said = writing_said(&written, whole);
            let written_whole = written.whole();
            (said, written_whole, written.title_written)
        }
        Kind::Chart => {
            let charted = charting_show(&text).map_err(|not| charting_refused(not, whole))?;
            let said = charting_said(&charted, whole);
            let charted_whole = charted.whole();
            (said, charted_whole, charted.title_written)
        }
    };
    if !whole {
        open_put(None);
        said.push_str(" It is not kept.");
        documents_panel_again();
        return Ok((said, false));
    }
    let name = title_written.as_deref().map(|title| name_cleaned(title.as_bytes())).unwrap_or_default();
    let lines = match kind {
        Kind::Table => drawing_lines_kept(&text),
        Kind::Text => writing_lines_kept(&text),
        Kind::Chart => charting_lines_kept(&text),
    };
    // A new document drawn for a line that a kept file was opened for is
    // made from that file (see `files.rs`), and its note says so.
    let from_file = if changes.is_none() { file_opening_number() } else { None };
    match version_keep(kind, changes, &name, &lines, from_file) {
        Ok(number) => {
            if from_file.is_some() {
                file_opening_forget();
            }
            said.push_str(&match changes {
                Some(_) => format!(" It is kept as document {}, in place of the one before.", number),
                None => format!(" It is kept as document {}.", number),
            });
            open_put(Some(OpenDocument { number, lines }));
        }
        Err(reason) => {
            said.push_str(&format!(" I could not keep it, because {}.", reason));
            open_put(None);
        }
    }
    documents_panel_again();
    Ok((said, drawn_whole))
}

// Keeps a new version of a document, of this kind: of the kept one with this
// number, or of a new one, numbered after the highest, made from the kept
// file `from_file` if it was. Its lines first, read back byte for byte, then
// the note that names it as the newest; a document made from a file keeps
// saying so in the note of every version. Gives back the document's number,
// or why it could not be kept; then nothing changed in what counts.
fn version_keep(kind: Kind, changes: Option<u32>, name: &str, lines: &str, from_file: Option<u32>) -> Result<u32, String> {
    if !notebook_ready() {
        return Err(String::from("the notebook cannot be added to"));
    }
    let documents = kept_documents();
    let (number, version, file) = match changes.and_then(|number| documents.iter().find(|document| document.number == number)) {
        Some(document) if document.version >= NUMBER_MOST => return Err(String::from("the numbers for its versions have run out")),
        Some(document) => (document.number, document.version + 1, document.file),
        None => {
            let highest = documents.iter().map(|document| document.number).max().unwrap_or(0);
            if highest >= NUMBER_MOST {
                return Err(String::from("the numbers for documents have run out"));
            }
            (highest + 1, 1, from_file)
        }
    };

    // The lines first, then read back.
    let kept = lines_name(number, version);
    notebook_keep(&kept, lines.as_bytes()).map_err(String::from)?;
    match notebook_find(&kept) {
        Ok(Some(back)) if back == lines.as_bytes() => {}
        Ok(_) => return Err(String::from("the disk did not give its lines back as they were written")),
        Err(reason) => return Err(String::from(reason)),
    }

    // Then the note that names this version as the newest: in form 2, with
    // the file's number, for a document made from a file, and in form 1
    // otherwise.
    let mut note = Vec::with_capacity(NOTE_HEAD_FILE + name.len());
    note.push(if file.is_some() { NOTE_FORM_FILE } else { NOTE_FORM });
    note.push(kind.byte());
    note.extend_from_slice(&version.to_le_bytes());
    if let Some(file) = file {
        note.extend_from_slice(&file.to_le_bytes());
    }
    note.extend_from_slice(name.as_bytes());
    notebook_keep(&note_name(number), &note).map_err(String::from)?;

    // The document goes to the top of the list.
    let documents = kept_documents();
    documents.retain(|document| document.number != number);
    documents.insert(0, KeptDocument { number, version, name: String::from(name), whole: true, file, kind });
    serial_print(&format!("Documents: version {} of document {} is kept on the disk\r\n", version, number));
    Ok(number)
}

// The tool `open_document`: draws the newest version of the kept document
// with this number in the frame, in place of what it showed, and makes it the
// open document. Gives back what the kernel says, or why it could not.
pub fn document_open(asked: u64) -> Result<String, String> {
    let Some(number) = kept_number(asked) else {
        return Err(format!("the model asked for document {}, but no kept document has that number.", asked));
    };
    let opened = open_inner(number)?;
    let named = kept_documents().iter().find(|document| document.number == number).map(called).unwrap_or_default();
    Ok(format!("I opened {}{}.", named, opened.fit()))
}

// The tool `open_file`, for a kept file that a document was made from before:
// that document is opened, as with `open_document`, instead of sending the
// file to the model again. Gives nothing when no document whose lines are
// whole was made from the file; otherwise what the kernel says, or why it
// could not open the document. The newest such document counts.
pub fn document_reopen(file: u32) -> Option<Result<String, String>> {
    let number = kept_documents()
        .iter()
        .filter(|document| document.whole && document.file == Some(file))
        .map(|document| document.number)
        .max()?;
    Some(open_inner(number).map(|opened| {
        let named = kept_documents().iter().find(|document| document.number == number).map(called).unwrap_or_default();
        format!("I opened {}, made from file {} before{}.", named, file, opened.fit())
    }))
}

// The tool `open_file` for a kept picture, a PNG picture or a JPEG photo
// (`told`, its kind in words): a picture opened before opens
// the newest document made from it, as any file does (`document_reopen`).
// Otherwise the picture is shown in the frame as a new document of text of
// its own, its title the file's name and its one block the line `picture`
// with the file's number, kept as made from that file (form 2 of the note),
// and the open document from then on. Nothing of the picture goes to the
// model. Gives back what the kernel says, or, when the picture cannot be
// shown, why: then nothing is kept, and the frame and the open document stay
// as they were.
pub fn document_of_picture(file: u32, name: &str, told: &str) -> Result<String, String> {
    if let Some(reopened) = document_reopen(file) {
        return reopened;
    }
    let lines = format!("title {}\npicture {}", name, file);
    let laid = match writing_laid(&lines) {
        Ok(laid) => laid,
        Err(NotDrawn::NoRoom) => return Err(String::from("the model asked to open a picture, but this screen has no room for one.")),
        Err(NotDrawn::Empty) => return Err(format!("I could not open file {}, \"{}\".", file, name)),
    };
    if let Some((_, why)) = laid.written.pictures_not_shown.first() {
        return Err(format!("I did not open file {}, \"{}\", because {}.", file, name, why));
    }
    let written = writing_put(laid);
    let size = match written.pictures.first() {
        Some((_, width, height)) => format!(", {} of {} by {} dots", told, width, height),
        None => String::new(),
    };
    let said = match version_keep(Kind::Text, None, &name_cleaned(name.as_bytes()), &lines, Some(file)) {
        Ok(number) => {
            open_put(Some(OpenDocument { number, lines }));
            format!("I opened file {}, \"{}\"{}, as document {}.", file, name, size, number)
        }
        Err(reason) => {
            open_put(None);
            format!("I showed file {}, \"{}\"{}, but I could not keep it as a document, because {}.", file, name, size, reason)
        }
    };
    documents_panel_again();
    Ok(said)
}

// Reads the newest version of a kept document from the disk, draws it by its
// kind, makes it the open document and puts it at the top of the list. Its
// lines come from the disk, so from outside: they are drawn as any
// description is, and cleaned there. Gives back what came of drawing it, or
// what the kernel says when it could not.
fn open_inner(number: u32) -> Result<Opened, String> {
    let Some(document) = kept_documents().iter().find(|document| document.number == number) else {
        return Err(format!("the model asked for document {}, but no kept document has that number.", number));
    };
    let named = called(document);
    let kind = document.kind;
    let lines = match notebook_find(&lines_name(number, document.version)) {
        Ok(Some(bytes)) => match String::from_utf8(bytes) {
            Ok(lines) => lines,
            Err(_) => return Err(format!("I could not open {}, because its lines on the disk are not proper text.", named)),
        },
        Ok(None) => return Err(format!("I could not open {}, because its lines are not on the disk.", named)),
        Err(reason) => return Err(format!("I could not open {}, because {}.", named, reason)),
    };
    let no_room = || String::from("the model asked to open a document, but this screen has no room for one.");
    let opened = match kind {
        Kind::Table => match drawing_show(&lines) {
            Ok(drawn) => Opened::Table(drawn),
            Err(NotDrawn::NoRoom) => return Err(no_room()),
            Err(NotDrawn::Empty) => return Err(format!("I could not open {}, because it has no head and no rows.", named)),
        },
        Kind::Text => match writing_show(&lines) {
            Ok(written) => Opened::Text(written),
            Err(NotDrawn::NoRoom) => return Err(no_room()),
            Err(NotDrawn::Empty) => return Err(format!("I could not open {}, because it has nothing in it.", named)),
        },
        Kind::Chart => match charting_show(&lines) {
            Ok(charted) => Opened::Chart(charted),
            Err(NotDrawn::NoRoom) => return Err(no_room()),
            Err(NotDrawn::Empty) => return Err(format!("I could not open {}, because it has no bar with a number I could read.", named)),
        },
    };
    open_put(Some(OpenDocument { number, lines }));
    let documents = kept_documents();
    if let Some(place) = documents.iter().position(|document| document.number == number) {
        let document = documents.remove(place);
        documents.insert(0, document);
    }
    documents_panel_again();
    Ok(opened)
}

// `setup` was sent: another person may be at the machine now, so the open
// document is closed and the frame empties. Its lines stop going to the model;
// the documents stay kept and listed.
pub fn documents_setup() {
    open_put(None);
    drawing_clear();
    documents_panel_again();
}

// How the panel of documents is laid out: as the panel of apps, under the box
// that shows an app's text. Its sizes are decided here, in this one place,
// and its colours are those of the panel of apps, from the look in use. From
// top to bottom it holds the frame, some empty room, a row that says how many
// documents are kept, a row for each document shown, and the frame again.
struct DocumentsPanelStyle {
    // How many dots it stays below the box with an app's text, and above the
    // chat box.
    gap: u32,
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
    // How many documents it shows: those used last.
    shown: u32,
}

const DOCUMENTS_PANEL_STYLE: DocumentsPanelStyle = DocumentsPanelStyle {
    gap: 20,
    width: 600,
    frame: 3,
    padding: 10,
    text_size: 2,
    row_gap: 4,
    shown: 5,
};

// Where the panel of documents sits: its left and top edges, and how many
// dots it is across and down: 20 dots under the box with an app's text, at
// its left edge. Gives nothing on a machine without a usable screen, on a
// screen without room for the frame of a table, and where it would come
// nearer than 20 dots to the chat box.
fn documents_panel_place() -> Option<(u32, u32, u32, u32)> {
    screen_size()?;
    drawing_room()?;
    let style = DOCUMENTS_PANEL_STYLE;
    let row_height = style.text_size.saturating_mul(LETTER_HEIGHT).saturating_add(style.row_gap);
    let height = style
        .frame
        .saturating_mul(2)
        .saturating_add(style.padding.saturating_mul(2))
        .saturating_add(style.shown.saturating_add(1).saturating_mul(row_height));
    let (box_left, box_top, _, box_height) = screen_panel_place();
    let top = box_top.saturating_add(box_height).saturating_add(style.gap);
    let (_, chat_top, _, _) = chat_box_place()?;
    if top.saturating_add(height).saturating_add(style.gap) > chat_top {
        return None;
    }
    Some((box_left, top, style.width, height))
}

// Paints the panel of documents as it is: a row that says how many are kept,
// and the documents used last, the open one marked with "> " and the others
// with "- ", in the look in use. Paints nothing while no document is listed,
// and nothing where the panel has no place. The look calls it when it paints
// the whole screen again.
pub fn documents_panel_again() {
    let listed = documents_listed();
    if listed.is_empty() {
        return;
    }
    let Some((left, top, width, height)) = documents_panel_place() else {
        return;
    };
    let style = DOCUMENTS_PANEL_STYLE;
    let look = look();
    let open = open_number();

    // The frame: the whole panel in the frame's colour first, then the
    // inside painted over it, smaller by the frame's thickness on each side.
    screen_rectangle(left, top, width, height, look.panel_frame);
    screen_rectangle(
        left.saturating_add(style.frame),
        top.saturating_add(style.frame),
        width.saturating_sub(style.frame.saturating_mul(2)),
        height.saturating_sub(style.frame.saturating_mul(2)),
        look.panel_inside,
    );

    let mut rows_said = Vec::new();
    rows_said.push(format!("Documents: {} kept", listed.len()));
    for (number, name) in listed.iter().take(style.shown as usize) {
        let mark = if open == Some(*number) { "> " } else { "- " };
        rows_said.push(format!("{}{}", mark, name));
    }

    // Nothing may land outside the panel: only as many signs of a row are
    // written as fit whole between the frame and the empty room on both
    // sides.
    let row_height = style.text_size.saturating_mul(LETTER_HEIGHT).saturating_add(style.row_gap);
    let sign_width = style.text_size.saturating_mul(LETTER_WIDTH + 1);
    let text_width = width.saturating_sub(style.frame.saturating_mul(2)).saturating_sub(style.padding.saturating_mul(2));
    let room = if sign_width == 0 { 0 } else { (text_width / sign_width) as usize };
    let text_left = left.saturating_add(style.frame).saturating_add(style.padding);
    let mut text_top = top.saturating_add(style.frame).saturating_add(style.padding);
    for row in rows_said.iter() {
        let shown = match row.char_indices().nth(room) {
            Some((cut, _)) => &row[..cut],
            None => row.as_str(),
        };
        screen_text(text_left, text_top, shown, style.text_size, look.panel_text);
        text_top = text_top.saturating_add(row_height);
    }
}
