//! Drawing: a table that the model describes in a few lines of text, with the
//! tool `draw_table` (see `tools.rs`), drawn by the kernel in a frame of its
//! own beside the panel of apps, up to the chat box's right edge and above
//! it. The frame never covers the chat box or the panel of apps. The frame
//! and the title are in the look in use; the table's colours are the model's,
//! but letters too faint to read on their background become black or white.
//! The table drawn last is kept in memory, and painted again with the rest of
//! the screen (`look_paint`); a new table takes its place, and `setup` empties
//! the frame. Where documents can be kept, the description itself is kept on
//! the disk too and drawn again from there (see `documents.rs`). A document of
//! text, laid out in pages in the same frame, is drawn here too, with the kept
//! pictures it names, PNG pictures and JPEG photos. Only the startup code and
//! the main loop may call these functions.
//! Notes: `docs/screen.md` ("The table", "A document of text", "Documents"),
//! `docs/tools.md` (`draw_table`, `write_document`) and `docs/pictures.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

use pictures::Picture;

use crate::apps_kept::apps_panel_place;
use crate::chat::chat_box_place;
use crate::drawing_values::LINEAR;
use crate::files::file_picture;
use crate::json::{Step, json_find_text, json_find_text_unfinished};
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::look::look;
use crate::model::key_starred_kept;
use crate::screen::{Colour, screen_rectangle, screen_row, screen_size, screen_text};

// How the frame and the table in it are laid out. The sizes are decided here,
// in this one place. The colours of the frame and the title come from the
// look in use, and those of the table from the model.
struct TableStyle {
    // How many dots the frame stays from the panel of apps on its left and
    // from the chat box below it.
    gap: u32,
    // How many dots thick the frame is, and how far what is inside it stays
    // from the frame.
    frame: u32,
    padding: u32,
    // How large a dot of a letter is painted (see `screen_text`): the chat
    // box's size.
    text_size: u32,
    // How many dots thick each line of the table is.
    line: u32,
    // How far a cell's text stays from the line on its left, from the line
    // on its right, and from the lines above and below it. A sign carries
    // one empty column of its own on its right, so the text looks as far
    // from the lines on both sides.
    cell_left: u32,
    cell_right: u32,
    cell_top: u32,
    cell_bottom: u32,
    // The most columns a table has, and the narrowest screen that gets a
    // frame.
    columns_most: usize,
    narrowest: u32,
}

const TABLE_STYLE: TableStyle = TableStyle {
    gap: 20,
    frame: 3,
    padding: 10,
    text_size: 2,
    line: 2,
    cell_left: 5,
    cell_right: 3,
    cell_top: 4,
    cell_bottom: 4,
    columns_most: 6,
    narrowest: 1000,
};

// How many dots a sign takes across, its empty column included, and how
// many dots a row of the table takes down: the line above it, the room above
// the letters, the letters, and the room below them. The title takes a row
// of the same height above the table.
fn sign_width() -> u32 {
    TABLE_STYLE.text_size.saturating_mul(LETTER_WIDTH + 1)
}

fn row_height() -> u32 {
    let style = TABLE_STYLE;
    style
        .line
        .saturating_add(style.cell_top)
        .saturating_add(style.text_size.saturating_mul(LETTER_HEIGHT))
        .saturating_add(style.cell_bottom)
}

// Where the frame sits on this screen: its left and top edges, and how many
// dots it is across and down. Its left edge is 20 dots right of the panel of
// apps, its top edge level with the panel's, its right edge the chat box's,
// and its bottom 20 dots above the chat box. Gives nothing on a machine
// without a usable screen, and on a screen narrower than 1000 dots.
struct FramePlace {
    left: u32,
    top: u32,
    width: u32,
    height: u32,
}

fn frame_place() -> Option<FramePlace> {
    let (screen_width, _) = screen_size()?;
    let style = TABLE_STYLE;
    if screen_width < style.narrowest {
        return None;
    }
    let (panel_left, panel_top, panel_width, _) = apps_panel_place();
    let (chat_left, chat_top, chat_width, _) = chat_box_place()?;
    let left = panel_left.saturating_add(panel_width).saturating_add(style.gap);
    let right = chat_left.saturating_add(chat_width);
    let bottom = chat_top.saturating_sub(style.gap);
    if right <= left || bottom <= panel_top {
        return None;
    }
    Some(FramePlace { left, top: panel_top, width: right - left, height: bottom - panel_top })
}

// The room inside the frame: where the title and the table begin, how many
// dots across the table may take, and how many rows fit, the head among
// them. A frame without room for the head and one row, or for one sign in
// each of the most columns, counts as none.
struct Room {
    left: u32,
    title_top: u32,
    table_top: u32,
    width: u32,
    rows: usize,
    bottom: u32,
}

fn room() -> Option<(FramePlace, Room)> {
    let place = frame_place()?;
    let style = TABLE_STYLE;
    let inner = style.frame.saturating_add(style.padding);
    let left = place.left.saturating_add(inner);
    let title_top = place.top.saturating_add(inner);
    let table_top = title_top.saturating_add(row_height());
    let width = place.width.saturating_sub(inner.saturating_mul(2));
    let bottom = place.top.saturating_add(place.height).saturating_sub(inner);
    // The table ends with a line below its last row.
    let rows = (bottom.saturating_sub(table_top).saturating_sub(style.line) / row_height().max(1)) as usize;
    if rows < 2 || signs_across(width, style.columns_most) < style.columns_most as u32 {
        return None;
    }
    Some((place, Room { left, title_top, table_top, width, rows, bottom }))
}

// How many signs fit across a table this many dots wide, all its columns
// together: what is left of the width once the lines and the room on both
// sides of every cell are taken out.
fn signs_across(width: u32, columns: usize) -> u32 {
    let style = TABLE_STYLE;
    let per_column = style.line.saturating_add(style.cell_left).saturating_add(style.cell_right);
    width.saturating_sub(style.line).saturating_sub(per_column.saturating_mul(columns as u32)) / sign_width().max(1)
}

// The room the model is told about with the tool `draw_table`: how many rows
// fit below the head, the most columns, and how many signs fit across with
// the most columns, which fit with fewer too. Gives nothing when this screen
// has no room for a table, and then the tool is not offered.
pub fn drawing_room() -> Option<(usize, usize, u32)> {
    let (_, room) = room()?;
    let columns = TABLE_STYLE.columns_most;
    Some((room.rows - 1, columns, signs_across(room.width, columns)))
}

// The parts of a table whose colours the model may pick, by the names it
// gives them: the head's background and letters, the rows' background and
// letters, and the lines between the cells. Their places in this list are
// their places in `Described::colours` and `Table::colours`.
const PARTS: [&str; 5] = ["head", "head-letters", "rows", "letters", "lines"];
const HEAD: usize = 0;
const HEAD_LETTERS: usize = 1;
const ROWS: usize = 2;
const LETTERS: usize = 3;
const LINES: usize = 4;

// A table as the model described it, read line by line: which kept document
// it changes, if it says (0 for a new one), its title, the colours it picked,
// the widths it asked for, its head, and its rows, each row its cells.
struct Described {
    document: Option<u64>,
    title: Option<String>,
    colours: [Option<Colour>; 5],
    widths: Option<Vec<u32>>,
    head: Option<Vec<String>>,
    rows: Vec<Vec<String>>,
}

// One line of a description: its first word, which says what the line is,
// without a colon right behind it, and the rest. Spaces, tabs and a return at
// either end of the line do not count.
fn line_parts(line: &str) -> (&str, &str) {
    let line = line.trim_matches(|sign| sign == ' ' || sign == '\t' || sign == '\r');
    let (word, rest) = match line.find([' ', '\t']) {
        Some(end) => (&line[..end], line[end..].trim_start_matches([' ', '\t'])),
        None => (line, ""),
    };
    (word.strip_suffix(':').unwrap_or(word), rest)
}

// Reads the lines of a table's description. Each line says one thing, and
// its first word says what: `document`, `title`, `colours`, `widths`, `head`
// or `row`, in capitals or not. The line `row` adds a row; the others count
// only before the first row: after it they are skipped, so that a
// description cut off anywhere is a smaller table whose shape is whole. Of
// a line given twice the later counts; colours given on two lines are all
// taken. A line with any other first word, and an empty line, is skipped.
fn described(text: &str) -> Described {
    let mut found = Described { document: None, title: None, colours: [None; 5], widths: None, head: None, rows: Vec::new() };
    for line in text.split('\n') {
        let (word, rest) = line_parts(line);
        if word.eq_ignore_ascii_case("row") {
            found.rows.push(cells(rest));
        } else if !found.rows.is_empty() {
            continue;
        } else if word.eq_ignore_ascii_case("document") {
            found.document = document_number(rest);
        } else if word.eq_ignore_ascii_case("title") {
            found.title = Some(String::from(rest));
        } else if word.eq_ignore_ascii_case("head") {
            found.head = Some(cells(rest));
        } else if word.eq_ignore_ascii_case("widths") {
            found.widths = widths(rest);
        } else if word.eq_ignore_ascii_case("colours") || word.eq_ignore_ascii_case("colors") {
            colours(rest, &mut found.colours);
        }
    }
    found
}

// The number on a `document` line: a whole number of at most nine digits, and
// nothing else. Anything else says no number.
fn document_number(rest: &str) -> Option<u64> {
    if rest.is_empty() || rest.len() > 9 || !rest.bytes().all(|sign| sign.is_ascii_digit()) {
        return None;
    }
    rest.parse().ok()
}

// The cells of a head or a row: parted by `|`, each without the spaces and
// tabs at either end. A `|` at the very beginning or end, as tables are often
// written, parts nothing off.
fn cells(rest: &str) -> Vec<String> {
    let mut rest = rest.trim_matches([' ', '\t']);
    rest = rest.strip_prefix('|').unwrap_or(rest);
    rest = rest.strip_suffix('|').unwrap_or(rest);
    rest.split('|').map(|cell| String::from(cell.trim_matches([' ', '\t']))).collect()
}

// The widths the model asked for, in signs, one for each column: whole
// numbers from 1 on, parted by spaces or commas, each counted as 999 at
// most. A line with anything else in it asks for nothing, and the columns
// share the room equally.
fn widths(rest: &str) -> Option<Vec<u32>> {
    let mut asked = Vec::new();
    for given in rest.split([' ', '\t', ',']).filter(|given| !given.is_empty()) {
        if !given.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        let width = given.trim_start_matches('0');
        let number = if width.len() > 3 { 999 } else { width.parse::<u32>().unwrap_or(0) };
        if number == 0 {
            return None;
        }
        asked.push(number);
    }
    if asked.is_empty() { None } else { Some(asked) }
}

// The colours the model picked: the name of a part, then its colour as `#`
// and six digits that count to sixteen, two each for red, green and blue,
// parted by spaces, commas, colons or equals signs. A colour written any
// other way, or behind a name that is no part's, is skipped, and that part
// keeps the look's colour.
fn colours(rest: &str, found: &mut [Option<Colour>; 5]) {
    let words: Vec<&str> = rest.split([' ', '\t', ',', ':', '=']).filter(|word| !word.is_empty()).collect();
    let mut at = 0;
    while at < words.len() {
        let part = PARTS.iter().position(|part| words[at].eq_ignore_ascii_case(part));
        match (part, words.get(at + 1).and_then(|given| colour_read(given))) {
            (Some(part), Some(colour)) => {
                found[part] = Some(colour);
                at += 2;
            }
            _ => at += 1,
        }
    }
}

fn colour_read(given: &str) -> Option<Colour> {
    let digits = given.strip_prefix('#')?.as_bytes();
    if digits.len() != 6 {
        return None;
    }
    let mut amounts = [0u8; 3];
    for (place, pair) in digits.chunks(2).enumerate() {
        let high = (pair[0] as char).to_digit(16)?;
        let low = (pair[1] as char).to_digit(16)?;
        amounts[place] = (high * 16 + low) as u8;
    }
    Some(Colour { red: amounts[0], green: amounts[1], blue: amounts[2] })
}

// The text the model gave a tool under `name` (`table` for `draw_table`,
// `lines` for `write_document`), and whether it came whole. It is read with
// the JSON reader, which takes nothing on trust. When the model's answer was
// cut off (at its limit of tokens, or at the bound on what a tool is given,
// see `model.rs`), a text cut off before its closing quote is taken as far as
// it goes; otherwise such a text cannot be read at all.
fn given_text(inputs: &str, cut_off: bool, name: &str) -> Option<(String, bool)> {
    let path = [Step::Name(name)];
    if let Ok(text) = json_find_text(inputs.as_bytes(), &path) {
        return Some((text, true));
    }
    if !cut_off {
        return None;
    }
    json_find_text_unfinished(inputs.as_bytes(), &path).ok()
}

// What the model asked to be drawn, written so that two requests for the
// same table give the same text: the text as the kernel reads it. No tool is
// done twice for one line (see `chat.rs`).
pub fn drawing_wanted(inputs: &str, cut_off: bool) -> Option<String> {
    given_text(inputs, cut_off, "table").map(|(text, _)| text)
}

// A table as it is drawn and kept: its title, the colours the model picked,
// how many signs each column holds, its head, if it has one, and the rows
// that fit, every cell made fit to be shown and cut to its column.
struct Table {
    title: String,
    colours: [Option<Colour>; 5],
    widths: Vec<u32>,
    head: Option<Vec<String>>,
    rows: Vec<Vec<String>>,
}

// What the frame shows: the table drawn last, or the document of text written
// or opened last, laid out in pages, with the page shown. One thing at a
// time: each takes the other's place. It is kept until the machine is
// switched off, so that it can be painted again in another look. Only the
// startup code and the main loop may touch it; it is taken out of its place
// and put back by value.
enum InFrame {
    Table(Table),
    Text(Pages),
}
static mut IN_FRAME: Option<InFrame> = None;

fn frame_take() -> Option<InFrame> {
    unsafe { (*(&raw mut IN_FRAME)).take() }
}

fn frame_put(shown: InFrame) {
    unsafe { IN_FRAME = Some(shown) };
}

// The tool `draw_table` where no documents can be kept: reads the table the
// model described in what it gave the tool, draws it in the frame in place of
// the one shown before, and keeps it in memory. Gives back what the kernel
// says, and whether the table was drawn whole: with every row, every column
// and every line the model wrote. A table that cannot be drawn changes
// nothing; the kernel says why, as the model's request turned down.
pub fn drawing_table(inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    let (text, whole) = drawing_text(inputs, cut_off)?;
    let drawn = drawing_show(&text).map_err(|not| drawing_refused(not, whole))?;
    Ok((drawing_said(&drawn, whole), drawn.whole() && whole))
}

// The text the model gave `draw_table`, as far as it counts, and whether it
// came whole; or what the kernel says when it cannot be read. A piece of the
// key in the text is starred, however it was written in the JSON. Of a text
// that was cut off, only the lines that came whole count: what follows its
// last line end may be half a line.
pub fn drawing_text(inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    if room().is_none() {
        return Err(String::from("the model asked to draw a table, but this screen has no room for one."));
    }
    let Some((text, whole)) = given_text(inputs, cut_off, "table") else {
        return Err(String::from("the model asked to draw a table, but I could not read it."));
    };
    let mut text = key_starred_kept(&text);
    if !whole {
        let end = text.rfind('\n').unwrap_or(0);
        text.truncate(end);
    }
    Ok((text, whole))
}

// Why a description was not drawn: this screen has no room for a table, or
// the description has no head and no rows.
pub enum NotDrawn {
    NoRoom,
    Empty,
}

// What the kernel says when the model's table was not drawn, for a text that
// came whole or one that was cut off.
pub fn drawing_refused(not: NotDrawn, whole: bool) -> String {
    String::from(match not {
        NotDrawn::NoRoom => "the model asked to draw a table, but this screen has no room for one.",
        NotDrawn::Empty if whole => "the model asked to draw a table, but it has no head and no rows.",
        NotDrawn::Empty => "the model asked to draw a table, but it was cut off before any of its rows came whole.",
    })
}

// What came of drawing a description: its title as the model wrote it, if it
// gave one, and as drawn; how many columns it has and how many were drawn;
// how many rows were drawn, and how many did not fit.
pub struct Drawn {
    pub title_written: Option<String>,
    pub title: String,
    columns: usize,
    drawn_columns: usize,
    rows: usize,
    left_out: usize,
}

impl Drawn {
    // Whether every row and every column the description holds was drawn.
    pub fn whole(&self) -> bool {
        self.left_out == 0 && self.columns == self.drawn_columns
    }
}

// The number on the description's `document` line, if it has one before its
// first row: which kept document the table changes, or 0 for a new one.
pub fn drawing_document(text: &str) -> Option<u64> {
    described(text).document
}

// A description as a document keeps it: every line as the model wrote it,
// but the `document` lines before the first row, which say only which
// document it is.
pub fn drawing_lines_kept(text: &str) -> String {
    let mut kept = String::new();
    let mut rows_begun = false;
    for line in text.split('\n') {
        let (word, _) = line_parts(line);
        rows_begun = rows_begun || word.eq_ignore_ascii_case("row");
        if !rows_begun && word.eq_ignore_ascii_case("document") {
            continue;
        }
        if !kept.is_empty() {
            kept.push('\n');
        }
        kept.push_str(line);
    }
    kept
}

// Reads a description and draws it in the frame, in place of the table shown
// before, and keeps the table drawn in memory. A description that cannot be
// drawn changes nothing.
pub fn drawing_show(text: &str) -> Result<Drawn, NotDrawn> {
    let Some((place, room)) = room() else {
        return Err(NotDrawn::NoRoom);
    };
    let found = described(text);

    // The head says how many columns the table has, or else its first row.
    let columns = match (&found.head, found.rows.first()) {
        (Some(head), _) => head.len(),
        (None, Some(row)) => row.len(),
        (None, None) => 0,
    };
    if columns == 0 {
        return Err(NotDrawn::Empty);
    }
    let style = TABLE_STYLE;
    let drawn_columns = columns.min(style.columns_most);

    // Rows that do not fit below the head are left out.
    let fit = room.rows - if found.head.is_some() { 1 } else { 0 };
    let drawn_rows = found.rows.len().min(fit);
    let left_out = found.rows.len() - drawn_rows;

    // How many signs the longest cell of each column has, the head's among
    // them, in the rows that are drawn. Every byte of a cell is shown as one
    // sign.
    let mut longest = vec![0u32; drawn_columns];
    for cells in found.head.iter().chain(found.rows.iter().take(drawn_rows)) {
        for (place, cell) in cells.iter().take(drawn_columns).enumerate() {
            longest[place] = longest[place].max(cell.len() as u32);
        }
    }
    let widths = widths_worked_out(&found.widths, &longest, signs_across(room.width, drawn_columns));

    let title_room = (room.width / sign_width().max(1)) as usize;
    let title = found.title.as_deref().map(|title| shown(title, title_room)).unwrap_or_default();
    let fitted = |cells: &Vec<String>| -> Vec<String> {
        widths.iter().enumerate().map(|(place, width)| shown(cells.get(place).map(String::as_str).unwrap_or(""), *width as usize)).collect()
    };
    let table = Table {
        title,
        colours: found.colours,
        widths: widths.clone(),
        head: found.head.as_ref().map(&fitted),
        rows: found.rows.iter().take(drawn_rows).map(&fitted).collect(),
    };
    table_paint(&place, &room, &table);
    let drawn = Drawn { title_written: found.title, title: table.title.clone(), columns, drawn_columns, rows: drawn_rows, left_out };
    frame_put(InFrame::Table(table));
    Ok(drawn)
}

// What the kernel says about a table it drew: the table, by its title, its
// size, and what of it did not fit or did not come.
pub fn drawing_said(drawn: &Drawn, whole: bool) -> String {
    let size = format!("{} and {}", counted(drawn.drawn_columns, "column", "columns"), rows_said(drawn.rows));
    let mut said = if drawn.title.is_empty() {
        format!("I drew a table with {}", size)
    } else {
        format!("I drew the table \"{}\", with {}", drawn.title, size)
    };
    said.push_str(&drawing_fit(drawn));
    if !whole {
        said.push_str("; it was cut off, so I drew only the rows that came whole");
    }
    said.push('.');
    said
}

// What of a table did not fit, as the kernel says it behind what it drew or
// opened: rows left out, and columns past the most it draws. Nothing when
// all of it fit.
pub fn drawing_fit(drawn: &Drawn) -> String {
    let mut said = String::new();
    if drawn.left_out > 0 {
        let (verb, were) = if drawn.left_out == 1 { ("row did", "was") } else { ("rows did", "were") };
        said.push_str(&format!("; {} more {} not fit and {} left out", drawn.left_out, verb, were));
    }
    if drawn.columns > drawn.drawn_columns {
        said.push_str(&format!("; only the first {} of its {} columns fit", drawn.drawn_columns, drawn.columns));
    }
    said
}

// `setup` empties the frame: the table or the document of text it showed is
// forgotten, and where it was, the screen's background is painted, as a
// whole new picture would show it there.
pub fn drawing_clear() {
    if frame_take().is_none() {
        return;
    }
    if let Some(place) = frame_place() {
        screen_rectangle(place.left, place.top, place.width, place.height, look().background);
    }
}

// "1 column", "3 columns", and so on.
fn counted(count: usize, one: &str, more: &str) -> String {
    format!("{} {}", count, if count == 1 { one } else { more })
}

fn rows_said(count: usize) -> String {
    if count == 0 { String::from("no rows") } else { counted(count, "row", "rows") }
}

// A text from the model made fit to be shown: every byte that is not a plain
// sign becomes a dot, as in every text from outside, and no more signs are
// kept than fit.
fn shown(text: &str, room: usize) -> String {
    text.bytes().take(room).map(|byte| if (b' '..=b'~').contains(&byte) { byte as char } else { '.' }).collect()
}

// How many signs each column holds, from the signs of its longest cell and
// the room across. A column wants as many signs as its longest cell, or as
// the model asked if that is more (with a width asked for every column), and
// at least one. If what the columns want fits across together, each gets it,
// and no cell is cut. If not, each column gets what it wants up to an equal
// share of the room, and the signs left are shared among the columns that
// want more, in proportion to how many more they want, rounded down: so a
// column of short cells stays whole beside one of long cells.
fn widths_worked_out(asked: &Option<Vec<u32>>, longest: &[u32], across: u32) -> Vec<u32> {
    let columns = longest.len();
    let asked = asked.as_ref().filter(|asked| asked.len() >= columns);
    let wanted: Vec<u32> =
        longest.iter().enumerate().map(|(place, signs)| (*signs).max(asked.map(|asked| asked[place]).unwrap_or(0)).max(1)).collect();
    let total: u32 = wanted.iter().sum();
    if total <= across {
        return wanted;
    }
    let share = across / (columns as u32).max(1);
    let given: Vec<u32> = wanted.iter().map(|want| (*want).min(share)).collect();
    let left = across.saturating_sub(given.iter().sum()) as u64;
    let more: u64 = wanted.iter().zip(given.iter()).map(|(want, got)| (want - got) as u64).sum();
    wanted.iter().zip(given.iter()).map(|(want, got)| got + (left * (want - got) as u64 / more.max(1)) as u32).collect()
}

// Paints the frame as the other boxes have it: the whole of it in the frame's
// colour, then the inside painted over it, which wipes out what it showed.
fn frame_paint(place: &FramePlace) {
    let style = TABLE_STYLE;
    let look = look();
    screen_rectangle(place.left, place.top, place.width, place.height, look.panel_frame);
    screen_rectangle(
        place.left.saturating_add(style.frame),
        place.top.saturating_add(style.frame),
        place.width.saturating_sub(style.frame.saturating_mul(2)),
        place.height.saturating_sub(style.frame.saturating_mul(2)),
        look.panel_inside,
    );
}

// Paints the frame, the title in the look's letters, and the table. The
// frame is painted whole, which wipes out what it showed before.
fn table_paint(place: &FramePlace, room: &Room, table: &Table) {
    frame_paint(place);
    screen_text(room.left, room.title_top, &table.title, TABLE_STYLE.text_size, look().panel_text);
    grid_paint(room.left, room.table_top, &table.widths, table.head.as_ref(), &table.rows, &table.colours);
}

// Paints a table's head, if it has one, and rows, from `left` and `top`, each
// column `widths` signs wide.
fn grid_paint(left: u32, top: u32, widths: &[u32], head: Option<&Vec<String>>, rows: &[Vec<String>], colours: &[Option<Colour>; 5]) {
    let style = TABLE_STYLE;
    let look = look();

    // The colours: those the model picked, or the look's for the parts it
    // left out: the head in the frame's colour, the rows in the inside's, the
    // letters in the look's, and the lines in the frame's. Letters that would
    // be too faint on their background become black or white.
    let picked = |part: usize, otherwise: Colour| colours[part].unwrap_or(otherwise);
    let head_back = picked(HEAD, look.panel_frame);
    let head_letters = readable(picked(HEAD_LETTERS, look.panel_text), head_back);
    let rows_back = picked(ROWS, look.panel_inside);
    let letters = readable(picked(LETTERS, look.panel_text), rows_back);
    let lines = picked(LINES, look.panel_frame);

    // The whole table in the colour of its lines first; each cell is painted
    // over it and leaves the lines showing between the cells and round them.
    let cell_widths: Vec<u32> =
        widths.iter().map(|width| style.cell_left.saturating_add(width.saturating_mul(sign_width())).saturating_add(style.cell_right)).collect();
    let width = cell_widths.iter().fold(style.line, |sum, cell| sum.saturating_add(cell.saturating_add(style.line)));
    let count = rows.len() + if head.is_some() { 1 } else { 0 };
    let height = row_height().saturating_mul(count as u32).saturating_add(style.line);
    screen_rectangle(left, top, width, height, lines);

    let mut row_top = top;
    let head = head.into_iter().map(|cells| (cells, head_back, head_letters));
    for (cells, back, front) in head.chain(rows.iter().map(|cells| (cells, rows_back, letters))) {
        let mut cell_left = left;
        for (cell, cell_width) in cells.iter().zip(cell_widths.iter()) {
            let inner_left = cell_left.saturating_add(style.line);
            let inner_top = row_top.saturating_add(style.line);
            screen_rectangle(inner_left, inner_top, *cell_width, row_height().saturating_sub(style.line), back);
            screen_text(inner_left.saturating_add(style.cell_left), inner_top.saturating_add(style.cell_top), cell, style.text_size, front);
            cell_left = inner_left.saturating_add(*cell_width);
        }
        row_top = row_top.saturating_add(row_height());
    }
}

// Paints what the frame shows again, in the look in use: the table drawn
// last, or the page shown of the document of text. Does nothing while the
// frame shows nothing. The look calls it when it paints the whole screen
// again.
pub fn drawing_paint_again() {
    let Some(shown) = frame_take() else {
        return;
    };
    if let Some((place, room)) = room() {
        match &shown {
            InFrame::Table(table) => table_paint(&place, &room, table),
            InFrame::Text(pages) => pages_paint(&place, &room, pages),
        }
    }
    frame_put(shown);
}

// ---------- A document of text ----------
//
// The tool `write_document` (see `tools.rs` and `documents.rs`): paragraphs,
// tables and pictures of kept files, in the order the model wrote them, laid
// out in the frame's room and cut into pages, one page shown at a time. The
// rules are those of "A document of text" in docs/screen.md.

// How high a row of text is: a letter, and two dots below it.
fn text_row() -> u32 {
    TABLE_STYLE.text_size.saturating_mul(LETTER_HEIGHT + 1)
}

// The most pictures a document of text shows: each is read from the disk and
// shrunk when the document is written or opened, and its dots are kept in
// memory while it is shown (see "In the kernel" in docs/pictures.md).
const PICTURES_MOST: usize = 4;

// A block of a document of text: a paragraph as the model wrote it; a table:
// its head, if it has one, and its rows, each row its cells; or a picture: the
// number of the kept file it shows, and its caption, if it has one.
enum Block {
    Paragraph(String),
    Table { head: Option<Vec<String>>, rows: Vec<Vec<String>> },
    Picture { file: u64, caption: Option<String> },
}

// A document of text as the model wrote it, read line by line: which kept
// document it changes, if it says (0 for a new one), its title, and its
// blocks.
struct WrittenLines {
    document: Option<u64>,
    title: Option<String>,
    blocks: Vec<Block>,
}

// Reads the lines of a document of text: `document` and `title` count only
// before anything else; `text` is a paragraph; `head` begins a new table;
// `row` adds a row to the table begun last, or begins a table without a head
// when a paragraph or a picture stands since; `picture` is a picture (see
// `picture_line`). Any other line is skipped. Nothing is read from the disk
// here: the pictures are read when the document is laid out.
fn writing_read(text: &str) -> WrittenLines {
    let mut found = WrittenLines { document: None, title: None, blocks: Vec::new() };
    for line in text.split('\n') {
        let (word, rest) = line_parts(line);
        if word.eq_ignore_ascii_case("text") {
            found.blocks.push(Block::Paragraph(String::from(rest)));
        } else if word.eq_ignore_ascii_case("picture") {
            if let Some(picture) = picture_line(rest) {
                found.blocks.push(picture);
            }
        } else if word.eq_ignore_ascii_case("head") {
            found.blocks.push(Block::Table { head: Some(cells(rest)), rows: Vec::new() });
        } else if word.eq_ignore_ascii_case("row") {
            match found.blocks.last_mut() {
                Some(Block::Table { rows, .. }) => rows.push(cells(rest)),
                _ => found.blocks.push(Block::Table { head: None, rows: vec![cells(rest)] }),
            }
        } else if !found.blocks.is_empty() {
            continue;
        } else if word.eq_ignore_ascii_case("document") {
            found.document = document_number(rest);
        } else if word.eq_ignore_ascii_case("title") {
            found.title = Some(String::from(rest));
        }
    }
    found
}

// The rest of a `picture` line: the number of the kept file it shows, a whole
// number of at most nine digits, as on a `document` line, and behind a `|`
// its caption, the spaces and tabs at either end of each not counting; an
// empty caption is none. A line whose number cannot be read is skipped, as a
// line a kernel from before pictures does not know.
fn picture_line(rest: &str) -> Option<Block> {
    let (number, caption) = match rest.split_once('|') {
        Some((number, caption)) => (number, Some(caption)),
        None => (rest, None),
    };
    let file = document_number(number.trim_matches([' ', '\t']))?;
    let caption = caption.map(|caption| caption.trim_matches([' ', '\t'])).filter(|caption| !caption.is_empty()).map(String::from);
    Some(Block::Picture { file, caption })
}

// A part of a page: rows of text, a table, or a picture, so many dots below
// the top of the page; a table with its columns' widths, its head (drawn
// again at the top of every page it goes on to) and the rows on this page; a
// picture with its dots as shown, shrunk to fit.
enum PagePart {
    Text { top: u32, rows: Vec<String> },
    Table { top: u32, widths: Vec<u32>, head: Option<Vec<String>>, rows: Vec<Vec<String>> },
    Picture { top: u32, picture: Picture },
}

// A document of text laid out: its title as drawn, its pages, and the page
// shown, counted from 0.
struct Pages {
    title: String,
    pages: Vec<Vec<PagePart>>,
    shown: usize,
}

// What came of writing a document of text: its title as the model wrote it,
// if it gave one, and as drawn; how many pages it has; whether a table in it
// had more columns than fit, which were left out; the pictures shown, each by
// its file's number with the picture's own width and height in dots; and the
// pictures not shown, each by its file's number with why, in words to stand
// after "because".
pub struct Written {
    pub title_written: Option<String>,
    pub title: String,
    pub pages: usize,
    columns_left_out: bool,
    pub pictures: Vec<(u64, u32, u32)>,
    pub pictures_not_shown: Vec<(u64, String)>,
}

impl Written {
    // Whether all of it was drawn: every column of every table, and every
    // picture.
    pub fn whole(&self) -> bool {
        !self.columns_left_out && self.pictures_not_shown.is_empty()
    }
}

// A document of text laid out in pages, its pictures read and shrunk, and not
// shown yet (see `writing_laid` and `writing_put`), with what came of it.
pub struct Laid {
    pages: Pages,
    pub written: Written,
}

// A paragraph set into rows of at most `across` signs: parted into words at
// runs of spaces and tabs, each word cleaned byte by byte; as many whole
// words to a row as fit, parted by one space; a word longer than a row cut
// into pieces as long as a row, each on a row of its own. A paragraph with no
// words is one empty row.
fn rows_of(text: &str, across: usize) -> Vec<String> {
    let across = across.max(1);
    let mut rows = Vec::new();
    let mut row = String::new();
    for word in text.split([' ', '\t']).filter(|word| !word.is_empty()) {
        let word = shown(word, word.len());
        if word.len() > across {
            if !row.is_empty() {
                rows.push(core::mem::take(&mut row));
            }
            // Only plain signs are left, one byte each, so the pieces are
            // whole signs.
            for piece in word.as_bytes().chunks(across) {
                rows.push(String::from_utf8_lossy(piece).into_owned());
            }
            continue;
        }
        if row.is_empty() {
            row = word;
        } else if row.len() + 1 + word.len() <= across {
            row.push(' ');
            row.push_str(&word);
        } else {
            rows.push(core::mem::replace(&mut row, word));
        }
    }
    if !row.is_empty() || rows.is_empty() {
        rows.push(row);
    }
    rows
}

// Rows of text laid out from `used`, the dots of the last page taken so far,
// as a paragraph's: a row that does not fit goes on at the top of the next
// page, and rows that follow one another on a page are one part of it.
fn text_rows_laid(pages: &mut Vec<Vec<PagePart>>, used: &mut u32, height: u32, rows: Vec<String>) {
    for row in rows {
        if used.saturating_add(text_row()) > height {
            pages.push(Vec::new());
            *used = 0;
        }
        if let Some(page) = pages.last_mut() {
            match page.last_mut() {
                Some(PagePart::Text { top, rows }) if top.saturating_add(text_row().saturating_mul(rows.len() as u32)) == *used => rows.push(row),
                _ => page.push(PagePart::Text { top: *used, rows: vec![row] }),
            }
        }
        *used = used.saturating_add(text_row());
    }
}

// A document of text laid out: its pages, whether a table had more columns
// than fit, and the pictures shown and not shown (as in `Written`).
struct Layout {
    pages: Vec<Vec<PagePart>>,
    columns_left_out: bool,
    pictures: Vec<(u64, u32, u32)>,
    pictures_not_shown: Vec<(u64, String)>,
}

// Lays the blocks out in pages of the room's height below the title's row:
// one empty row between two blocks where the page has room for more below
// it, none at the top of a page; a paragraph's rows that do not fit going on
// at the top of the next page; a table beginning on the next page unless its
// head and first row fit, and its rows that do not fit going on to the next
// page under its head drawn again; a picture, with its caption under it,
// read from its file and shrunk to fit a whole page, beginning on the next
// page unless it fits whole on this one, or, when it cannot be shown, rows
// that say why in its place.
fn laid_out(found: &WrittenLines, room: &Room) -> Layout {
    let style = TABLE_STYLE;
    let height = room.bottom.saturating_sub(room.table_top);
    let across = (room.width / sign_width().max(1)) as usize;
    let mut pages: Vec<Vec<PagePart>> = vec![Vec::new()];
    let mut used: u32 = 0;
    let mut columns_left_out = false;
    let mut pictures_tried = 0;
    let mut pictures = Vec::new();
    let mut pictures_not_shown = Vec::new();
    for (place, block) in found.blocks.iter().enumerate() {
        if place > 0 && used > 0 {
            if used.saturating_add(text_row()) >= height {
                pages.push(Vec::new());
                used = 0;
            } else {
                used = used.saturating_add(text_row());
            }
        }
        match block {
            Block::Paragraph(text) => text_rows_laid(&mut pages, &mut used, height, rows_of(text, across)),
            Block::Picture { file, caption } => {
                // The caption is one row under the picture, cut to the row.
                let caption_rows: Vec<String> = caption.iter().map(|caption| shown(caption, across)).collect();
                let caption_height = text_row().saturating_mul(caption_rows.len() as u32);
                pictures_tried += 1;
                let got = if pictures_tried > PICTURES_MOST {
                    Err(format!("a document shows at most {} pictures", PICTURES_MOST))
                } else {
                    file_picture(*file, room.width, height.saturating_sub(caption_height))
                };
                match got {
                    Ok((width, tall, picture)) => {
                        let picture_height = picture.height;
                        if used > 0 && used.saturating_add(picture_height).saturating_add(caption_height) > height {
                            pages.push(Vec::new());
                            used = 0;
                        }
                        if let Some(page) = pages.last_mut() {
                            page.push(PagePart::Picture { top: used, picture });
                        }
                        used = used.saturating_add(picture_height);
                        text_rows_laid(&mut pages, &mut used, height, caption_rows);
                        pictures.push((*file, width, tall));
                    }
                    Err(why) => {
                        let mut rows = rows_of(&format!("picture of file {}: {}", file, why), across);
                        rows.extend(caption_rows);
                        text_rows_laid(&mut pages, &mut used, height, rows);
                        pictures_not_shown.push((*file, why));
                    }
                }
            }
            Block::Table { head, rows } => {
                // The head says how many columns the table has, or else its
                // first row.
                let columns = match (head, rows.first()) {
                    (Some(head), _) => head.len(),
                    (None, Some(row)) => row.len(),
                    (None, None) => 0,
                };
                if columns == 0 {
                    continue;
                }
                let drawn_columns = columns.min(style.columns_most);
                columns_left_out = columns_left_out || columns > drawn_columns;
                let mut longest = vec![0u32; drawn_columns];
                for cells in head.iter().chain(rows.iter()) {
                    for (column, cell) in cells.iter().take(drawn_columns).enumerate() {
                        longest[column] = longest[column].max(cell.len() as u32);
                    }
                }
                let widths = widths_worked_out(&None, &longest, signs_across(room.width, drawn_columns));
                let fitted = |cells: &Vec<String>| -> Vec<String> {
                    widths.iter().enumerate().map(|(column, width)| shown(cells.get(column).map(String::as_str).unwrap_or(""), *width as usize)).collect()
                };
                let head = head.as_ref().map(&fitted);
                let rows: Vec<Vec<String>> = rows.iter().map(&fitted).collect();
                let head_height = if head.is_some() { row_height() } else { 0 };
                let first = if rows.is_empty() { 0 } else { row_height() };
                if used > 0 && used.saturating_add(head_height).saturating_add(first).saturating_add(style.line) > height {
                    pages.push(Vec::new());
                    used = 0;
                }
                let mut from = 0;
                loop {
                    let room_rows =
                        (height.saturating_sub(used).saturating_sub(head_height).saturating_sub(style.line) / row_height().max(1)) as usize;
                    let mut take = room_rows.min(rows.len() - from);
                    // A page that holds no row at all still takes one, so that
                    // the laying out ends.
                    if take == 0 && from < rows.len() && used == 0 {
                        take = 1;
                    }
                    if let Some(page) = pages.last_mut() {
                        page.push(PagePart::Table { top: used, widths: widths.clone(), head: head.clone(), rows: rows[from..from + take].to_vec() });
                    }
                    used = used
                        .saturating_add(head_height)
                        .saturating_add(row_height().saturating_mul(take as u32))
                        .saturating_add(style.line);
                    from += take;
                    if from >= rows.len() {
                        break;
                    }
                    pages.push(Vec::new());
                    used = 0;
                }
            }
        }
    }
    Layout { pages, columns_left_out, pictures, pictures_not_shown }
}

// The mark of the page shown, `page 2 of 5`, for a document of more than one
// page.
fn page_mark(shown: usize, count: usize) -> String {
    format!("page {} of {}", shown + 1, count)
}

// Paints the frame, the title's row and the page shown of a document of text.
// The frame is painted whole, which wipes out what it showed before. The page
// mark stands at the right end of the title's row, its last sign in the
// row's last place.
fn pages_paint(place: &FramePlace, room: &Room, pages: &Pages) {
    let style = TABLE_STYLE;
    let look = look();
    frame_paint(place);
    screen_text(room.left, room.title_top, &pages.title, style.text_size, look.panel_text);
    if pages.pages.len() > 1 {
        let across = (room.width / sign_width().max(1)) as usize;
        let mark = page_mark(pages.shown, pages.pages.len());
        let left = room.left.saturating_add((across.saturating_sub(mark.len()) as u32).saturating_mul(sign_width()));
        screen_text(left, room.title_top, &mark, style.text_size, look.panel_text);
    }
    let Some(page) = pages.pages.get(pages.shown) else {
        return;
    };
    for part in page {
        match part {
            PagePart::Text { top, rows } => {
                for (index, row) in rows.iter().enumerate() {
                    let row_top = room.table_top.saturating_add(*top).saturating_add(text_row().saturating_mul(index as u32));
                    screen_text(room.left, row_top, row, style.text_size, look.panel_text);
                }
            }
            PagePart::Table { top, widths, head, rows } => {
                grid_paint(room.left, room.table_top.saturating_add(*top), widths, head.as_ref(), rows, &[None; 5]);
            }
            PagePart::Picture { top, picture } => picture_paint(room.left, room.table_top.saturating_add(*top), picture, look.panel_inside),
        }
    }
}

// Paints a picture's dots from `left` and `top`, row by row, each over `back`,
// the colour of the frame's inside in the look in use, as much as its alpha
// says: (colour * alpha + back * (255 - alpha)) / 255, each of red, green and
// blue, rounded to the nearest. So a see-through part shows the look's
// colour, and changes with the look. The picture was shrunk to fit the room,
// so nothing of it lands outside the frame.
fn picture_paint(left: u32, top: u32, picture: &Picture, back: Colour) {
    let width = picture.width.max(1) as usize;
    let mut row: Vec<Colour> = Vec::with_capacity(width);
    for (y, dots) in picture.dots.chunks_exact(width * 4).enumerate() {
        row.clear();
        for dot in dots.chunks_exact(4) {
            let alpha = dot[3] as u32;
            let mix = |front: u8, behind: u8| ((front as u32 * alpha + behind as u32 * (255 - alpha) + 127) / 255) as u8;
            row.push(Colour { red: mix(dot[0], back.red), green: mix(dot[1], back.green), blue: mix(dot[2], back.blue) });
        }
        screen_row(left, top.saturating_add(y as u32), &row);
    }
}

// The room a page of a document of text has, which the tool `write_document`
// tells the model: how many rows of text a page holds, and how many signs a
// row. Gives nothing when this screen has no room for the frame.
pub fn writing_room() -> Option<(usize, u32)> {
    let (_, room) = room()?;
    let rows = (room.bottom.saturating_sub(room.table_top) / text_row().max(1)) as usize;
    Some((rows, room.width / sign_width().max(1)))
}

// The text the model gave `write_document`, as far as it counts, and whether
// it came whole; or what the kernel says when it cannot be read. As for a
// table: a piece of the key in it is starred, and of a text that was cut off
// only the lines that came whole count.
pub fn writing_text(inputs: &str, cut_off: bool) -> Result<(String, bool), String> {
    if room().is_none() {
        return Err(String::from("the model asked to write a document, but this screen has no room for one."));
    }
    let Some((text, whole)) = given_text(inputs, cut_off, "lines") else {
        return Err(String::from("the model asked to write a document, but I could not read it."));
    };
    let mut text = key_starred_kept(&text);
    if !whole {
        let end = text.rfind('\n').unwrap_or(0);
        text.truncate(end);
    }
    Ok((text, whole))
}

// What the model asked to be written, so that two requests for the same
// document give the same text (see `drawing_wanted`).
pub fn writing_wanted(inputs: &str, cut_off: bool) -> Option<String> {
    given_text(inputs, cut_off, "lines").map(|(text, _)| text)
}

// The number on the document's `document` line, if it has one before
// anything else: which kept document it changes, or 0 for a new one.
pub fn writing_document(text: &str) -> Option<u64> {
    writing_read(text).document
}

// A document of text as a document keeps it: every line as the model wrote
// it, but the `document` lines before anything else, which say only which
// document it is.
pub fn writing_lines_kept(text: &str) -> String {
    let mut kept: Vec<&str> = Vec::new();
    let mut begun = false;
    for line in text.split('\n') {
        let (word, rest) = line_parts(line);
        begun = begun
            || ["text", "head", "row"].iter().any(|block| word.eq_ignore_ascii_case(block))
            || (word.eq_ignore_ascii_case("picture") && picture_line(rest).is_some());
        if !begun && word.eq_ignore_ascii_case("document") {
            continue;
        }
        kept.push(line);
    }
    kept.join("\n")
}

// Reads a document of text, lays it out in pages, and shows its first page in
// the frame, in place of what it showed, keeping it in memory. A document
// that cannot be written changes nothing.
pub fn writing_show(text: &str) -> Result<Written, NotDrawn> {
    Ok(writing_put(writing_laid(text)?))
}

// Reads a document of text and lays it out in pages, its pictures read from
// their files and shrunk, without showing it: so that what came of it can be
// looked at first (see `document_of_picture` in `documents.rs`). Nothing
// changes on the screen or in memory.
pub fn writing_laid(text: &str) -> Result<Laid, NotDrawn> {
    let Some((_, room)) = room() else {
        return Err(NotDrawn::NoRoom);
    };
    let found = writing_read(text);
    if found.blocks.is_empty() {
        return Err(NotDrawn::Empty);
    }
    let layout = laid_out(&found, &room);
    let count = layout.pages.len();
    // The title is cut so that it leaves room for the longest page mark, that
    // of the last page, and one sign more: so it stays the same as the pages
    // are turned.
    let across = (room.width / sign_width().max(1)) as usize;
    let mark_room = if count > 1 { page_mark(count - 1, count).len() + 1 } else { 0 };
    let title = found.title.as_deref().map(|title| shown(title, across.saturating_sub(mark_room))).unwrap_or_default();
    let written = Written {
        title_written: found.title,
        title: title.clone(),
        pages: count,
        columns_left_out: layout.columns_left_out,
        pictures: layout.pictures,
        pictures_not_shown: layout.pictures_not_shown,
    };
    Ok(Laid { pages: Pages { title, pages: layout.pages, shown: 0 }, written })
}

// Shows a document of text laid out by `writing_laid`: its first page in the
// frame, in place of what it showed, and keeps it in memory.
pub fn writing_put(laid: Laid) -> Written {
    if let Some((place, room)) = room() {
        pages_paint(&place, &room, &laid.pages);
    }
    frame_put(InFrame::Text(laid.pages));
    laid.written
}

// What the kernel says about a document of text it wrote: the document, by
// its title, how many pages it has, and what of it did not fit or did not
// come.
pub fn writing_said(written: &Written, whole: bool) -> String {
    let pages = counted(written.pages, "page", "pages");
    let mut said = if written.title.is_empty() {
        format!("I wrote a document of {}", pages)
    } else {
        format!("I wrote the document \"{}\", {}", written.title, pages)
    };
    said.push_str(&writing_fit(written));
    if !whole {
        said.push_str("; it was cut off, so I wrote only the lines that came whole");
    }
    said.push('.');
    said
}

// What of a document of text did not fit, as the kernel says it behind what
// it wrote or opened: columns past the most it draws, and each picture not
// shown, with why. Nothing when all of it fit.
pub fn writing_fit(written: &Written) -> String {
    let mut said = if written.columns_left_out {
        format!("; a table had more columns than fit, and only its first {} were drawn", TABLE_STYLE.columns_most)
    } else {
        String::new()
    };
    for (file, why) in written.pictures_not_shown.iter() {
        said.push_str(&format!("; the picture of file {} is not shown, because {}", file, why));
    }
    said
}

// How the kernel says what it opened of a document of text: its pages, and
// what did not fit.
pub fn writing_pages(written: &Written) -> String {
    format!(", {}{}", counted(written.pages, "page", "pages"), writing_fit(written))
}

// What the kernel says when the model's document of text was not written, for
// a text that came whole or one that was cut off.
pub fn writing_refused(not: NotDrawn, whole: bool) -> String {
    String::from(match not {
        NotDrawn::NoRoom => "the model asked to write a document, but this screen has no room for one.",
        NotDrawn::Empty if whole => "the model asked to write a document, but it has nothing in it.",
        NotDrawn::Empty => "the model asked to write a document, but it was cut off before any of its lines came whole.",
    })
}

// Page Down and Page Up: shows the next page of the document of text the
// frame shows, or the one before, at once. Nothing changes at the last page
// or the first, or when the frame shows no document of text.
pub fn drawing_page_turn(forward: bool) {
    let Some(mut shown) = frame_take() else {
        return;
    };
    if let InFrame::Text(pages) = &mut shown {
        let next = if forward { pages.shown.checked_add(1) } else { pages.shown.checked_sub(1) };
        if let Some(next) = next.filter(|next| *next < pages.pages.len()) {
            pages.shown = next;
            if let Some((place, room)) = room() {
                pages_paint(&place, &room, pages);
            }
        }
    }
    frame_put(shown);
}

// How bright a colour is to the eye: its relative luminance, as WCAG 2 (the
// Web Content Accessibility Guidelines) has it, in whole numbers. Each amount
// of light is made linear with `LINEAR` (in millionths, made by a script),
// and the three are weighed 2126, 7152 and 722 ten-thousandths, so that white
// is 10,000,000,000.
fn brightness(colour: Colour) -> u64 {
    2126 * LINEAR[colour.red as usize] as u64 + 7152 * LINEAR[colour.green as usize] as u64 + 722 * LINEAR[colour.blue as usize] as u64
}

// The 0.05 that the measure adds to both brightnesses, in the same units.
const FLARE: u64 = 500_000_000;

const BLACK: Colour = Colour { red: 0, green: 0, blue: 0 };
const WHITE: Colour = Colour { red: 255, green: 255, blue: 255 };

// The colour letters are painted in on a background: the colour asked for if
// it stands out from the background by a contrast ratio of at least 4.5, the
// least for ordinary text and the measure the looks are held to; otherwise
// white, if white stands out more from the background than black, and black
// if not. The ratio is (lighter + 0.05) / (darker + 0.05), so "at least 4.5"
// is 2 * (lighter + 0.05) >= 9 * (darker + 0.05), and white stands out more
// than black when (1 + 0.05) * 0.05 > (background + 0.05) squared.
fn readable(letters: Colour, back: Colour) -> Colour {
    let (one, other) = (brightness(letters), brightness(back));
    let (lighter, darker) = if one >= other { (one, other) } else { (other, one) };
    if 2 * (lighter + FLARE) >= 9 * (darker + FLARE) {
        return letters;
    }
    let white = (brightness(WHITE) + FLARE) as u128 * FLARE as u128;
    let back = (other + FLARE) as u128;
    if white > back * back { WHITE } else { BLACK }
}
