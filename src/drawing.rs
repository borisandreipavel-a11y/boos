//! The table in the frame beside the apps. The model describes a table in
//! words. The kernel checks how much fits, paints it and keeps it in memory
//! so it can be painted again with the next look. Only the main loop uses it.
//! Notes: docs/screen.md.

mod chart;
mod diagram;

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::fmt::Write;

use crate::apps_kept::apps_panel_bounds;
use crate::chat::chat_edges;
use crate::documents::{document_keep_cell_edit, documents_paint};
use crate::keyboard::{BACKSPACE, Key};
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::light_values::LIGHT;
use crate::look::look;
use crate::screen::{Colour, screen_rectangle, screen_size, screen_text};

pub const TABLE_TEXT_MOST: usize = 2048;
pub const TABLE_INPUTS_MOST: usize = 4096;
pub const DIAGRAM_SHAPES_MOST: usize = diagram::SHAPES_MOST;
const COLUMNS: usize = 6;
const GAP: u32 = 20;
const FRAME: u32 = 3;
const PADDING: u32 = 10;
const TEXT_SIZE: u32 = 2;
const SIGN: u32 = TEXT_SIZE * (LETTER_WIDTH + 1);
const ROW_HEIGHT: u32 = 28;
const CELL_SIDE: u32 = 4;
const GRID_DOT: u32 = 1;

struct Place {
    left: u32,
    top: u32,
    width: u32,
    height: u32,
}

impl Place {
    fn inside_width(&self) -> u32 {
        self.width - 2 * (FRAME + PADDING)
    }

    fn signs(&self, columns: usize) -> u32 {
        (self.inside_width() - columns as u32 * (2 * CELL_SIDE + GRID_DOT) - GRID_DOT) / SIGN
    }

    fn rows(&self) -> usize {
        // Leave one row each for the title and the column headings.
        ((self.height - 2 * (FRAME + PADDING) - GRID_DOT) / ROW_HEIGHT - 2) as usize
    }
}

fn table_place() -> Option<Place> {
    let (screen_width, _) = screen_size()?;
    let (right, chat_top) = chat_edges()?;
    let (_, top, apps_right, _) = apps_panel_bounds();
    let left = apps_right + GAP;
    let width = right.checked_sub(left)?;
    let height = chat_top.checked_sub(top + GAP)?;
    let least_width = 2 * (FRAME + PADDING) + (SIGN + 2 * CELL_SIDE + GRID_DOT) * COLUMNS as u32 + GRID_DOT;
    let least_height = 2 * (FRAME + PADDING) + 3 * ROW_HEIGHT + GRID_DOT;
    if screen_width < 1000 || width < least_width || height < least_height {
        return None;
    }
    Some(Place { left, top, width, height })
}

// What the model needs to know before laying out its columns.
pub fn table_room() -> Option<(usize, [u32; COLUMNS])> {
    let place = table_place()?;
    let signs = core::array::from_fn(|column| place.signs(column + 1));
    Some((place.rows(), signs))
}

#[derive(Default)]
struct Colours {
    head: Option<Colour>,
    head_letters: Option<Colour>,
    rows: Option<Colour>,
    letters: Option<Colour>,
    lines: Option<Colour>,
}

impl Colours {
    fn read(&mut self, rest: &str) {
        let mut words = rest.split_ascii_whitespace();
        while let (Some(name), Some(value)) = (words.next(), words.next()) {
            let colour = read_colour(value);
            match name {
                "head" => self.head = colour,
                "head-letters" => self.head_letters = colour,
                "rows" => self.rows = colour,
                "letters" => self.letters = colour,
                "lines" => self.lines = colour,
                _ => {}
            }
        }
    }
}

fn read_colour(value: &str) -> Option<Colour> {
    let hex = value.strip_prefix('#')?;
    if hex.len() != 6 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }
    let light = u32::from_str_radix(hex, 16).ok()?;
    Some(Colour { red: (light >> 16) as u8, green: (light >> 8) as u8, blue: light as u8 })
}

pub struct Table {
    saved: Option<String>,
    source: String,
    title: String,
    colours: Colours,
    widths: Vec<u32>,
    explicit_widths: bool,
    head: Vec<String>,
    rows: Vec<Vec<String>>,
}

static mut TABLE: Option<Table> = None;
static mut PREVIEW: Option<Table> = None;
static mut VIEW: Option<DrawingView> = None;

enum DrawingView {
    Chart(chart::Chart),
    Diagram(diagram::Diagram),
}
static mut SELECTED_CELL: Option<CellSelection> = None;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
struct CellPosition {
    row: usize,
    column: usize,
}

#[derive(Default)]
struct CellSelection {
    position: CellPosition,
    edit: Option<CellEdit>,
}

struct CellEdit {
    original: String,
    changed: Option<String>,
}

impl CellEdit {
    fn shown(&self, width: usize) -> &str {
        let value = self.changed.as_deref().unwrap_or(&self.original);
        &value[value.len().saturating_sub(width)..]
    }

    fn backspace(&mut self) -> bool {
        if self.original.is_empty() && self.changed.is_none() {
            return false;
        }
        self.changed.get_or_insert_with(|| self.original.clone()).pop().is_some()
    }

    fn type_sign(&mut self, sign: u8, width: usize) -> bool {
        let value = self.changed.get_or_insert_with(String::new);
        if value.len() >= width {
            return false;
        }
        value.push(sign as char);
        true
    }
}

impl CellSelection {
    // Reports changes to the editor. The caller checks selection movement.
    fn key(&mut self, key: &Key, rows: usize, columns: usize, width: usize) -> Result<bool, String> {
        if let Some(edit) = &mut self.edit {
            match key {
                Key::Text(b'\n') => {
                    if let Some(value) = &edit.changed {
                        save_cell(self.position, value.trim())?;
                    }
                    self.edit = None;
                }
                Key::Escape => self.edit = None,
                Key::Text(BACKSPACE) => return Ok(edit.backspace()),
                Key::Text(sign) if (b' '..=b'~').contains(sign) && *sign != b'|' => {
                    return Ok(edit.type_sign(*sign, width));
                }
                _ => return Ok(false),
            }
            return Ok(true);
        }
        match key {
            Key::Up => self.position.row = self.position.row.saturating_sub(1),
            Key::Down => self.position.row = (self.position.row + 1).min(rows - 1),
            Key::Left => self.position.column = self.position.column.saturating_sub(1),
            Key::Right => self.position.column = (self.position.column + 1).min(columns - 1),
            Key::Text(b'\n') => {
                self.edit = Some(CellEdit { original: cell_value(self.position), changed: None });
                return Ok(true);
            }
            _ => {}
        }
        Ok(false)
    }
}

pub fn table_edit_hint() -> Option<&'static str> {
    let selection = unsafe { &*(&raw const SELECTED_CELL) }.as_ref()?;
    Some(if selection.edit.is_some() {
        "Type to replace. Backspace deletes. Enter saves. Esc cancels."
    } else {
        "Arrows move. Enter edits. Esc returns to chat."
    })
}

// Only the main loop holds this selection. Restore it before painting so
// the cells reflect the latest focus, including an edit whose save failed.
pub fn table_key(key: &Key) -> Result<bool, String> {
    if matches!(key, Key::Tab | Key::Escape) && unsafe { (*(&raw mut VIEW)).take().is_some() } {
        paint_view(true);
        return Ok(true);
    }
    let Some(table) = unsafe { &*(&raw const TABLE) }.as_ref().filter(|table| !table.rows.is_empty()) else {
        return Ok(false);
    };
    let previous = unsafe { (*(&raw mut SELECTED_CELL)).take() };
    let old = previous.as_ref().map(|cell| cell.position);
    let mut result = Ok(false);
    let selection = match (previous, key) {
        (None, Key::Tab) => Some(CellSelection::default()),
        (None, _) => return Ok(false),
        (Some(cell), Key::Escape | Key::Tab) if cell.edit.is_none() => None,
        (Some(mut cell), _) => {
            let width = table.widths[cell.position.column] as usize;
            result = cell.key(key, table.rows.len(), table.widths.len(), width);
            Some(cell)
        }
    };
    let new = selection.as_ref().map(|cell| cell.position);
    unsafe { SELECTED_CELL = selection };
    if result? || old != new {
        repaint_selection(old, new);
    }
    Ok(true)
}

// The editor needs the whole value when the displayed cell is clipped.
fn cell_value(position: CellPosition) -> String {
    let table = unsafe { &*(&raw const TABLE) }.as_ref().expect("a table being edited");
    let CellPosition { row, column } = position;
    let value = table.source.lines().filter_map(|line| {
        let (word, content) = table_line(line);
        (word == "row").then_some(content)
    }).nth(row).and_then(|content| content.split('|').nth(column)).unwrap_or("");
    clean(value, TABLE_TEXT_MOST as u32, &mut Cuts::default())
}

// Replace one cell in the description, preserving lines outside its row.
// Use the complete description, including rows and cells off screen.
fn replace_cell(text: &str, row: usize, column: usize, value: &str) -> Option<String> {
    let mut description = String::new();
    let mut remaining = row;
    let mut replaced = false;
    for raw in text.split_inclusive('\n') {
        let (word, content) = table_line(raw);
        if word != "row" || replaced {
            description.push_str(raw);
            continue;
        }
        if remaining > 0 {
            remaining -= 1;
            description.push_str(raw);
            continue;
        }
        let mut cells: Vec<_> = content.split('|').collect();
        if cells.get(column).copied().unwrap_or("").trim() == value {
            return None;
        }
        cells.resize(cells.len().max(column + 1), "");
        cells[column] = value;
        description.push_str("row ");
        description.push_str(&cells.join("|"));
        description.push_str(&raw[raw.trim_end_matches(['\r', '\n']).len()..]);
        replaced = true;
    }
    replaced.then_some(description)
}

fn save_cell(position: CellPosition, value: &str) -> Result<(), String> {
    let CellPosition { row, column } = position;
    let table = unsafe { &mut *(&raw mut TABLE) }.as_mut().expect("a table being edited");
    let Some(description) = replace_cell(&table.source, row, column, value) else {
        return Ok(());
    };
    if description.len() > TABLE_TEXT_MOST {
        return Err(String::from("the table description was too long."));
    }

    // The edit changes a single validated value within the fitted column.
    // Keep the new version before changing the displayed value.
    let list_changed = if let Some(name) = &table.saved {
        document_keep_cell_edit(name, &description)?
    } else {
        false
    };
    table.source = description;
    table.rows[row][column] = clean(value, table.widths[column], &mut Cuts::default());
    if list_changed {
        documents_paint();
    }
    Ok(())
}

// Reports every kind of change that affected the visible table.
#[derive(Default)]
struct Cuts {
    text: bool,
    columns: bool,
    widths: bool,
    rows: bool,
}

impl Cuts {
    fn sentence(self, unfinished: bool) -> (String, bool) {
        let mut details = Vec::new();
        if self.text {
            details.push("some text was shortened");
        }
        if self.columns {
            details.push("extra cells were left out");
        }
        if self.widths {
            details.push("column widths were changed to fit");
        }
        if self.rows {
            details.push("rows below the frame were left out");
        }
        if unfinished {
            details.push("the answer ended early and only complete rows were used");
        }
        if details.is_empty() {
            (String::from("I drew the table."), false)
        } else {
            let mut description = details.join(", ");
            description[0..1].make_ascii_uppercase();
            (format!("I drew the table. {}.", description), true)
        }
    }
}

fn clean(text: &str, room: u32, cuts: &mut Cuts) -> String {
    let text = text.trim();
    cuts.text |= text.len() > room as usize;
    text.bytes().take(room as usize).map(|byte| if (b' '..=b'~').contains(&byte) { byte as char } else { '.' }).collect()
}

fn fit_cells(row: &str, widths: &[u32], cuts: &mut Cuts) -> Vec<String> {
    let mut cells = row.split('|');
    let fitted = widths.iter().map(|&width| clean(cells.next().unwrap_or(""), width, cuts)).collect();
    cuts.columns |= cells.next().is_some();
    fitted
}

fn read_widths(text: Option<&str>, columns: usize, room: u32, cuts: &mut Cuts) -> Vec<u32> {
    if let Some(text) = text {
        let widths: Vec<_> = text.split_ascii_whitespace().map(|word| word.parse::<u16>().map(u32::from).unwrap_or(0)).collect();
        if widths.len() == columns && widths.iter().all(|&width| width > 0) && widths.iter().sum::<u32>() <= room {
            return widths;
        }
        cuts.widths = true;
    }
    let even = room / columns as u32;
    let extra = (room % columns as u32) as usize;
    (0..columns).map(|column| even + u32::from(column < extra)).collect()
}

// The description has already been decoded and had the key hidden by model.rs.
// Shape lines stop taking effect at the first row. Keep only the cells there
// is room to paint. A refused description leaves the last table in place.
pub fn table_draw(text: &str, unfinished: bool) -> Result<(String, bool), &'static str> {
    let (table, said, clipped) = table_read(text, unfinished)?;
    table_show(table, None);
    Ok((said, clipped))
}

fn table_line(line: &str) -> (&str, &str) {
    let line = line.trim();
    line.split_once(' ').unwrap_or((line, ""))
}

pub fn table_read(text: &str, unfinished: bool) -> Result<(Table, String, bool), &'static str> {
    let place = table_place().ok_or("this screen has no room for a table.")?;
    if text.len() > TABLE_TEXT_MOST {
        return Err("the table description was too long.");
    }
    let mut title = "";
    let mut colours = Colours::default();
    let mut widths = None;
    let mut head = None;
    let mut rows = Vec::new();
    let mut started = false;
    let mut cuts = Cuts::default();

    for line in text.lines() {
        let (word, rest) = table_line(line);
        match word {
            "row" => {
                started = true;
                if rows.len() < place.rows() {
                    rows.push(rest);
                } else {
                    cuts.rows = true;
                }
            }
            "title" if !started => title = rest,
            "colours" if !started => colours.read(rest),
            "widths" if !started => widths = Some(rest),
            "head" if !started => head = Some(rest),
            _ => {}
        }
    }
    let head = head.filter(|text| !text.trim().is_empty()).ok_or("the table had no column headings.")?;
    let columns = head.split('|').count().min(COLUMNS);
    let fitted_widths = read_widths(widths, columns, place.signs(columns), &mut cuts);
    let explicit_widths = widths.is_some() && !cuts.widths;
    let title = clean(title, place.inside_width() / SIGN, &mut cuts);
    let head = fit_cells(head, &fitted_widths, &mut cuts);
    let rows = rows.into_iter().map(|row| fit_cells(row, &fitted_widths, &mut cuts)).collect();
    let table = Table {
        saved: None,
        source: String::from(text),
        title,
        colours,
        widths: fitted_widths,
        explicit_widths,
        head,
        rows,
    };
    let (said, clipped) = cuts.sentence(unfinished);
    Ok((table, said, clipped))
}

// A table has already been checked on this screen before it reaches here.
// The name travels with a saved document.
pub fn table_show(mut table: Table, saved: Option<String>) {
    table.saved = saved;
    unsafe {
        TABLE = Some(table);
        PREVIEW = None;
        VIEW = None;
        SELECTED_CELL = None;
    }
    table_again();
    documents_paint();
}

pub fn table_name() -> Option<String> {
    let table = unsafe { &*(&raw const TABLE) }.as_ref()?;
    table.saved.clone()
}

pub fn table_rename(old: &str, new: &str) {
    let table = unsafe { &mut *(&raw mut TABLE) };
    if let Some(name) = table.as_mut().and_then(|table| table.saved.as_mut()) {
        if name == old {
            *name = String::from(new);
        }
    }
}

pub fn table_chart_columns() -> Option<usize> {
    table_place().filter(chart::fits)?;
    let table = unsafe { &*(&raw const TABLE) }.as_ref()?;
    (!table.rows.is_empty() && table.head.len() >= 2).then_some(table.head.len())
}

pub fn table_chart(label_column: u64, value_column: u64) -> Result<String, String> {
    let place = table_place().filter(chart::fits).ok_or("this screen has no room for a bar chart.")?;
    let table = unsafe { &*(&raw const TABLE) }.as_ref()
        .ok_or("open a table before drawing a bar chart.")?;
    let columns = table.head.len() as u64;
    if label_column == value_column || !(1..=columns).contains(&label_column) || !(1..=columns).contains(&value_column) {
        return Err(format!("choose two different columns from 1 to {} for the bar chart.", columns));
    }
    let (chart, shown, total) = chart::read(&table.source, label_column as usize - 1, value_column as usize - 1, &place)?;
    unsafe {
        VIEW = Some(DrawingView::Chart(chart));
        PREVIEW = None;
    }
    table_again();
    let mut said = String::from("I drew a bar chart from the open table.");
    if shown < total {
        let _ = write!(said, " Showing the first {} of {} rows.", shown, total);
    }
    Ok(said)
}

pub fn diagram_room() -> Option<(u32, u32)> {
    table_place().map(|place| diagram::room(&place))
}

pub fn diagram_draw(text: &str) -> Result<String, String> {
    let place = table_place().ok_or("this screen has no room for a diagram.")?;
    let drawing = diagram::read(text, diagram::room(&place))?;
    unsafe {
        PREVIEW = None;
        VIEW = Some(DrawingView::Diagram(drawing));
        SELECTED_CELL = None;
    }
    table_again();
    Ok(String::from("I drew the diagram. Press Esc to close it."))
}

pub fn diagram_context() -> String {
    match unsafe { &*(&raw const VIEW) } {
        Some(DrawingView::Diagram(drawing)) => drawing.source().into(),
        _ => String::new(),
    }
}

pub fn table_context() -> String {
    let description = table_description();
    if let Some(name) = table_name() {
        format!("Saved document: {}\n{}", name, description)
    } else {
        description
    }
}

// Only complete rows arrive here. After the first row the shape is fixed,
// so a growing preview only needs to paint the new part of the grid.
pub fn table_preview(text: &str) {
    let Some(place) = table_place() else { return };
    let Ok((table, _, _)) = table_read(text, false) else { return };
    if table.rows.is_empty() {
        return;
    }
    let previous = unsafe { &*(&raw const PREVIEW) }.as_ref();
    match previous {
        Some(old) if table.rows.starts_with(&old.rows) => {
            if table.rows.len() > old.rows.len() {
                paint_grid(&place, &table, old.rows.len() + 1);
                paint_cells(&place, &table, |number, _| number > old.rows.len());
            }
        }
        _ => paint(&place, &table),
    }
    unsafe { PREVIEW = Some(table) };
}

pub fn table_preview_clear() {
    let was_shown = unsafe { (*(&raw mut PREVIEW)).take().is_some() };
    if was_shown {
        paint_view(true);
    }
}

pub fn table_again() {
    paint_view(false);
}

fn paint_view(erase_if_empty: bool) {
    // No other task can replace the picture while it is being painted.
    let Some(place) = table_place() else { return };
    let preview = unsafe { &*(&raw const PREVIEW) };
    let view = unsafe { &*(&raw const VIEW) };
    let table = unsafe { &*(&raw const TABLE) };
    if let Some(preview) = preview {
        paint(&place, preview);
    } else if let Some(view) = view {
        match view {
            DrawingView::Chart(chart) => chart.paint(&place),
            DrawingView::Diagram(drawing) => drawing.paint(&place),
        }
    } else if let Some(table) = table {
        paint(&place, table);
    } else if erase_if_empty {
        screen_rectangle(place.left, place.top, place.width, place.height, look().background);
    }
}

// Copy what was drawn into the same line format the tool accepts. Missing
// colours and widths keep following the look and the screen. Compact rows
// leave out trailing empty cells so the copy stays within the tool's limit.
pub fn table_description() -> String {
    let Some(table) = (unsafe { &*(&raw const TABLE) }) else {
        return String::new();
    };
    if table.saved.is_some() {
        return table.source.clone();
    }
    let mut text = String::new();
    if !table.title.is_empty() {
        let _ = writeln!(text, "title {}", table.title);
    }
    let colours = &table.colours;
    let choices = [
        ("head", colours.head), ("head-letters", colours.head_letters),
        ("rows", colours.rows), ("letters", colours.letters), ("lines", colours.lines),
    ];
    if choices.iter().any(|(_, colour)| colour.is_some()) {
        text.push_str("colours");
        for (name, colour) in choices {
            if let Some(colour) = colour {
                let _ = write!(text, " {} #{:02x}{:02x}{:02x}", name, colour.red, colour.green, colour.blue);
            }
        }
        text.push('\n');
    }
    if table.explicit_widths {
        text.push_str("widths");
        for width in &table.widths {
            let _ = write!(text, " {}", width);
        }
        text.push('\n');
    }
    text.push_str("head ");
    text.push_str(&table.head.join("|"));
    for row in &table.rows {
        text.push_str("\nrow");
        if let Some(last) = row.iter().rposition(|cell| !cell.is_empty()) {
            text.push(' ');
            text.push_str(&row[..=last].join("|"));
        }
    }
    text
}

// Forgetting the conversation also clears the table it was sending back.
// Paint over the frame in its own space, leaving the rest of the screen.
pub fn table_forget() {
    let was_drawn = unsafe {
        SELECTED_CELL = None;
        let preview = (*(&raw mut PREVIEW)).take().is_some();
        let view = (*(&raw mut VIEW)).take().is_some();
        let table = (*(&raw mut TABLE)).take().is_some();
        preview || view || table
    };
    if was_drawn {
        paint_view(true);
        documents_paint();
    }
}

// WCAG relative luminance, with one million for full white. LIGHT keeps
// the conversion from sRGB in the build so the kernel needs no fractions.
fn luminance(colour: Colour) -> u64 {
    let red = LIGHT[colour.red as usize] as u64;
    let green = LIGHT[colour.green as usize] as u64;
    let blue = LIGHT[colour.blue as usize] as u64;
    (2126 * red + 7152 * green + 722 * blue) / 10_000
}

fn readable(ink: Colour, paper: Colour) -> Colour {
    const OFFSET: u64 = 50_000;
    const WHITE: u64 = 1_000_000;
    let ink_light = luminance(ink) + OFFSET;
    let paper_light = luminance(paper) + OFFSET;
    // Give rounding in the channel table and weighted sum a small margin.
    let lighter = ink_light.max(paper_light) - 1;
    let darker = ink_light.min(paper_light) + 2;
    if 2 * lighter >= 9 * darker {
        return ink;
    }
    let value = if paper_light * paper_light >= OFFSET * (WHITE + OFFSET) { 0 } else { 255 };
    Colour { red: value, green: value, blue: value }
}

fn paint_frame(place: &Place) {
    let look = look();
    screen_rectangle(place.left, place.top, place.width, place.height, look.panel_frame);
    screen_rectangle(place.left + FRAME, place.top + FRAME, place.width - 2 * FRAME, place.height - 2 * FRAME, look.panel_inside);
}

fn paint(place: &Place, table: &Table) {
    let look = look();
    paint_frame(place);
    let left = place.left + FRAME + PADDING;
    let top = place.top + FRAME + PADDING;
    let text_down = (ROW_HEIGHT - TEXT_SIZE * LETTER_HEIGHT) / 2;
    screen_text(left, top + text_down, &table.title, TEXT_SIZE, look.panel_text);

    paint_grid(place, table, 0);
    paint_cells(place, table, |_, _| true);
}

fn paint_grid(place: &Place, table: &Table, start_row: usize) {
    let left = place.left + FRAME + PADDING;
    let top = place.top + FRAME + PADDING + ROW_HEIGHT * (start_row as u32 + 1);
    let lines = table.colours.lines.unwrap_or(look().panel_frame);
    let width: u32 = table.widths.iter().map(|width| width * SIGN + 2 * CELL_SIDE + GRID_DOT).sum::<u32>() + GRID_DOT;
    let height = ROW_HEIGHT * (table.rows.len() + 1 - start_row) as u32 + GRID_DOT;
    screen_rectangle(left, top, width, height, lines);
}

fn repaint_selection(old: Option<CellPosition>, new: Option<CellPosition>) {
    let table = unsafe { &*(&raw const TABLE) };
    if let (Some(place), Some(table)) = (table_place(), table) {
        paint_cells(&place, table, |number, column| {
            let Some(row) = number.checked_sub(1) else { return false };
            let position = Some(CellPosition { row, column });
            position == old || position == new
        });
    }
}

fn paint_cells(place: &Place, table: &Table, should_paint: impl Fn(usize, usize) -> bool) {
    let left = place.left + FRAME + PADDING;
    let grid_top = place.top + FRAME + PADDING + ROW_HEIGHT;
    let text_down = (ROW_HEIGHT - TEXT_SIZE * LETTER_HEIGHT) / 2;
    let look = look();
    let colours = &table.colours;
    let head = colours.head.unwrap_or(look.panel_frame);
    let head_letters = readable(colours.head_letters.unwrap_or(look.panel_text), head);
    let rows = colours.rows.unwrap_or(look.panel_inside);
    let letters = readable(colours.letters.unwrap_or(look.panel_text), rows);
    let selected = unsafe { &*(&raw const SELECTED_CELL) }.as_ref();
    for (number, cells) in core::iter::once(&table.head).chain(&table.rows).enumerate() {
        let (paper, ink) = if number == 0 { (head, head_letters) } else { (rows, letters) };
        let row_top = grid_top + number as u32 * ROW_HEIGHT;
        let mut x = left + GRID_DOT;
        for (column, (cell, width)) in cells.iter().zip(&table.widths).enumerate() {
            let cell_width = width * SIGN + 2 * CELL_SIDE;
            if !should_paint(number, column) {
                x += cell_width + GRID_DOT;
                continue;
            }
            let focus = selected.filter(|cell| cell.position.row + 1 == number && cell.position.column == column);
            let (paper, ink) = if focus.is_some() { (readable(paper, paper), paper) } else { (paper, ink) };
            let edit = focus.and_then(|cell| cell.edit.as_ref());
            let text = edit.map_or(cell.as_str(), |edit| edit.shown(*width as usize));
            let text_left = x + CELL_SIDE;
            let text_top = row_top + text_down;
            screen_rectangle(x, row_top + GRID_DOT, cell_width, ROW_HEIGHT - GRID_DOT, paper);
            screen_text(text_left, text_top, text, TEXT_SIZE, ink);
            if edit.is_some() {
                screen_rectangle(text_left + text.len() as u32 * SIGN, text_top, TEXT_SIZE, TEXT_SIZE * LETTER_HEIGHT, ink);
            }
            x += cell_width + GRID_DOT;
        }
    }
}
