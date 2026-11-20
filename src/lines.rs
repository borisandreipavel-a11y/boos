//! The kernel's own lines on the screen. Everything the kernel says goes out
//! through the serial port, and a PC may have none: then the screen is the
//! only place to read it. So every line that is printed is kept here too,
//! the last ones in a room of fixed size, and shown on the screen: on the
//! whole screen while the machine starts, again when the F1 key is pressed,
//! and with the reason when the kernel stops on a failure or gives up (a
//! panic). Notes: `docs/screen.md` ("The kernel's lines").

use crate::keyboard::F1_KEY;
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::look::look_paint;
use crate::processor::{signals_back, signals_off};
use crate::screen::{Colour, screen_cover, screen_covered, screen_rectangle_over, screen_size, screen_text_over};

// How many of the kernel's last lines are kept, and how many signs of each.
// The rest of a longer line goes to the serial port only.
const LINES_KEPT: usize = 100;
const LINE_LONGEST: usize = 300;

// How the lines are laid out: letters at size 2, as large as the chat box's
// (every dot of a letter a block of 2 by 2 dots), 8 dots from the screen's
// edges. A row is as high as a letter and one empty row of its dots, so that
// the tails of one row do not touch the tops of the next.
const LINES_SIZE: u32 = 2;
const LINES_MARGIN: u32 = 8;
const SIGN_WIDTH: u32 = LINES_SIZE * (LETTER_WIDTH + 1);
const ROW_HEIGHT: u32 = LINES_SIZE * (LETTER_HEIGHT + 1);

// The colours. They do not follow the look: the start is painted before the
// look kept on the disk is known, and nothing may make the report of a
// failure hard to read. White letters stand out from the dark blue that
// every start began with by a contrast ratio of 14.5, and from the dark red
// of a stop by 9.9 (the measure is the one the looks are held to; see "The
// look" in docs/screen.md).
const LINES_BACKGROUND: Colour = Colour { red: 0, green: 40, blue: 90 };
const LINES_LETTERS: Colour = Colour { red: 255, green: 255, blue: 255 };
const STOP_BACKGROUND: Colour = Colour { red: 140, green: 0, blue: 0 };
const STOP_LETTERS: Colour = Colour { red: 255, green: 255, blue: 255 };

// What a byte that is not a plain sign is kept as: a sign that has no
// picture, so that it shows as the empty box (see `letters.rs`).
const NO_PICTURE: u8 = 127;

// The room: the last lines, each in a place of its own. `ADDED` counts every
// line ever kept; line number n, counted from 0, sits in place n % LINES_KEPT
// for as long as it is one of the last LINES_KEPT, and then a newer line
// takes its place. Any task may keep a line, so these are changed with
// device signals off (`serial_print` sees to that) and read the same way.
static mut KEPT: [[u8; LINE_LONGEST]; LINES_KEPT] = [[0; LINE_LONGEST]; LINES_KEPT];
static mut KEPT_LENGTH: [usize; LINES_KEPT] = [0; LINES_KEPT];
static mut ADDED: usize = 0;

// The line being put together. `write!` hands a line over in several pieces,
// and a line is kept once its end, "\n", comes.
static mut GROWING: [u8; LINE_LONGEST] = [0; LINE_LONGEST];
static mut GROWING_LENGTH: usize = 0;

// What the screen shows: the usual picture, the lines while the machine
// starts, or the lines because F1 was pressed.
#[derive(Clone, Copy, PartialEq)]
enum Showing {
    Picture,
    Start,
    Asked,
}

// What the screen shows now; where the next row of lines goes, counted in
// rows from the top of the screen; and how many of the lines kept are on the
// screen or were passed over. Only the startup code and the main loop touch
// these.
static mut SHOWING: Showing = Showing::Picture;
static mut NEXT_ROW: u32 = 0;
static mut PAINTED: usize = 0;

// Whether F1 is held down. A key held down sends its number again and again
// until it is let go, and F1 held down must not take the lines away again.
// Only the main loop touches it.
static mut F1_HELD: bool = false;

// Whether a line is painted the moment it is kept. That is so while the
// machine starts, when nothing else runs. Once other tasks run, the main loop
// paints the lines they print, because only the main loop draws then (see
// "Drawing from tasks" in docs/screen.md).
static mut AT_ONCE: bool = true;

// Whether the kernel is stopping on a failure or a panic, so that nothing but
// the stop screen is painted; and whether that screen was painted, so that a
// failure inside the painting does not start it over and over.
static mut STOPPING: bool = false;
static mut STOP_PAINTED: bool = false;

// Keeps what the kernel prints, line by line. `serial_print` hands every text
// over, whether or not the machine has a serial port, with device signals
// off, so that the lines of two tasks do not mix. A "\r" is left out. While
// the machine starts and the lines cover the screen, a line is painted as
// soon as it is whole.
pub fn lines_keep(text: &str) {
    for byte in text.bytes() {
        match byte {
            b'\r' => {}
            b'\n' => line_end(),
            _ => {
                // A sign past the longest line is not kept.
                let length = unsafe { GROWING_LENGTH };
                if length < LINE_LONGEST {
                    let sign = if (b' '..=b'~').contains(&byte) { byte } else { NO_PICTURE };
                    unsafe {
                        GROWING[length] = sign;
                        GROWING_LENGTH = length + 1;
                    }
                }
            }
        }
    }
}

// Keeps the line put together so far as a whole line, in the place of the
// oldest, and paints it if lines are painted at once.
fn line_end() {
    unsafe {
        let place = ADDED % LINES_KEPT;
        KEPT[place] = GROWING;
        KEPT_LENGTH[place] = GROWING_LENGTH;
        GROWING_LENGTH = 0;
        ADDED += 1;
    }
    if unsafe { AT_ONCE && !STOPPING } {
        lines_paint_new();
    }
}

// A copy of line number `number` and how many signs it has. The line must be
// one of those kept. Call it with device signals off.
fn kept_line(number: usize) -> ([u8; LINE_LONGEST], usize) {
    let place = number % LINES_KEPT;
    unsafe { (KEPT[place], KEPT_LENGTH[place].min(LINE_LONGEST)) }
}

// How many signs fit on a row of this screen, and how many rows fit. Worked
// out from the screen's size each time, so that a screen of any size works.
// Gives nothing on a machine without a usable screen, or on one too small
// for a single sign.
fn lines_place() -> Option<(u32, u32)> {
    let (width, height) = screen_size()?;
    let room = width.saturating_sub(2 * LINES_MARGIN) / SIGN_WIDTH;
    let rows = height.saturating_sub(2 * LINES_MARGIN) / ROW_HEIGHT;
    if room == 0 || rows == 0 {
        return None;
    }
    Some((room, rows))
}

// How many rows a line of `length` signs takes when `room` signs fit on a
// row. A longer line goes on in the next row. An empty line takes one row,
// so that it shows as an empty row.
fn rows_of(length: usize, room: u32) -> u32 {
    let room = (room as usize).max(1);
    length.div_ceil(room).max(1) as u32
}

// Paints one line from screen row `row` down, as many signs to a row as fit,
// and gives back the row below it. Rows below the screen's last are left out.
fn line_paint(line: &[u8], row: u32, room: u32, rows: u32, colour: Colour) -> u32 {
    let mut row = row;
    let mut rest = line;
    loop {
        if row >= rows {
            return row;
        }
        let (piece, after) = rest.split_at(rest.len().min(room as usize));
        // Only plain signs are kept (see `lines_keep`), so the bytes are a
        // text. The fixed texts of the stop screen are plain too.
        let text = core::str::from_utf8(piece).unwrap_or("");
        let top = LINES_MARGIN.saturating_add(row.saturating_mul(ROW_HEIGHT));
        screen_text_over(LINES_MARGIN, top, text, LINES_SIZE, colour);
        row += 1;
        rest = after;
        if rest.is_empty() {
            return row;
        }
    }
}

// The number of the first of the newest kept lines before line number `end`
// that fit together in `rows_room` rows. Lines that are no longer kept are
// not counted. Call it with device signals off.
fn newest_first(end: usize, rows_room: u32, room: u32) -> usize {
    let oldest = unsafe { ADDED }.saturating_sub(LINES_KEPT);
    let mut first = end;
    let mut used: u32 = 0;
    while first > oldest {
        let length = unsafe { KEPT_LENGTH[(first - 1) % LINES_KEPT] };
        let needed = rows_of(length, room);
        if used.saturating_add(needed) > rows_room {
            break;
        }
        used += needed;
        first -= 1;
    }
    first
}

// Paints the whole screen in the lines' colour, and on it the newest kept
// lines before line number `end` that fit together in `rows_room` rows, the
// oldest at the top. The next line goes below them.
fn lines_paint_newest(end: usize, rows_room: u32, room: u32, rows: u32) {
    let Some((width, height)) = screen_size() else {
        return;
    };
    screen_rectangle_over(0, 0, width, height, LINES_BACKGROUND);
    let were_on = signals_off();
    let first = newest_first(end, rows_room, room);
    signals_back(were_on);
    let mut row = 0;
    for number in first..end {
        let were_on = signals_off();
        let (line, length) = kept_line(number);
        signals_back(were_on);
        row = line_paint(&line[..length], row, room, rows, LINES_LETTERS);
    }
    unsafe { NEXT_ROW = row };
}

// Paints the lines kept since the last painting, below those on the screen,
// while the lines cover the screen. When a line does not fit below them, the
// older half goes at once: the screen is painted again with the newest lines
// that fill half of it, and the line goes below those. While the machine
// starts it is called for each line as it is kept; after that the main loop
// calls it at every turn.
pub fn lines_paint_new() {
    if !screen_covered() {
        return;
    }
    let Some((room, rows)) = lines_place() else {
        return;
    };
    loop {
        // Take the next line out of the room, with device signals off, since
        // another task may be keeping one meanwhile. A line that is no longer
        // kept is passed over.
        let were_on = signals_off();
        let added = unsafe { ADDED };
        let number = unsafe { PAINTED }.max(added.saturating_sub(LINES_KEPT));
        if number >= added {
            signals_back(were_on);
            return;
        }
        let (line, length) = kept_line(number);
        unsafe { PAINTED = number + 1 };
        signals_back(were_on);

        if unsafe { NEXT_ROW }.saturating_add(rows_of(length, room)) > rows {
            lines_paint_newest(number, rows / 2, room, rows);
        }
        let row = line_paint(&line[..length], unsafe { NEXT_ROW }, room, rows, LINES_LETTERS);
        unsafe { NEXT_ROW = row };
    }
}

// Covers the screen with the kernel's lines: the whole screen in the lines'
// colour, with the newest lines kept so far on it, as many as fit. Every
// later line is added as it comes. The usual picture waits meanwhile
// (`screen_cover`): what it shows is kept, and painted at once when the
// lines go.
fn lines_cover(showing: Showing) {
    let Some((room, rows)) = lines_place() else {
        return;
    };
    unsafe { SHOWING = showing };
    screen_cover(true);
    let were_on = signals_off();
    let end = unsafe { ADDED };
    unsafe { PAINTED = end };
    signals_back(were_on);
    lines_paint_newest(end, rows, room, rows);
}

// The lines go, and the usual picture is painted in their place, all of it at
// once, in the look in use.
fn lines_uncover() {
    unsafe { SHOWING = Showing::Picture };
    screen_cover(false);
    look_paint();
}

// Covers the screen with the kernel's lines while the machine starts. Called
// once by `efi_main`, as soon as the screen is known.
pub fn lines_begin() {
    lines_cover(Showing::Start);
}

// Called right before other tasks get their first turn: from then on a line
// is not painted when it is kept, but by the main loop (`lines_paint_new`).
pub fn lines_tasks_start() {
    unsafe { AT_ONCE = false };
}

// The start is over: the usual picture takes the place of the lines, unless
// F1 asked for them meanwhile. Called once by the main loop, just before it
// asks for typing.
pub fn lines_start_over() {
    if unsafe { SHOWING } == Showing::Start {
        lines_uncover();
    }
}

// Takes every key number, before it is turned into a letter; the main loop
// calls it. A key pressed while the lines cover the screen brings the usual
// picture back, and is then typed as usual. F1 pressed while the usual
// picture shows covers the screen with the lines again.
pub fn lines_key(key: u8) {
    // A key that comes up sends its number and 128 more (see `keyboard.rs`):
    // F1 was let go.
    if key == F1_KEY + 128 {
        unsafe { F1_HELD = false };
        return;
    }
    // The numbers 1 to 127 say that a key went down; 224 is the mark that
    // some keys send first.
    if !(1..128).contains(&key) {
        return;
    }
    // F1 held down counts once, until it is let go or another key goes down
    // (the keyboard then repeats that key instead).
    if key == F1_KEY && unsafe { F1_HELD } {
        return;
    }
    unsafe { F1_HELD = key == F1_KEY };
    if unsafe { SHOWING } != Showing::Picture {
        lines_uncover();
    } else if key == F1_KEY {
        lines_cover(Showing::Asked);
    }
}

// The kernel is stopping on a failure or a panic: from here on nothing but
// the stop screen is painted. A line half put together is kept as it is, so
// that the report starts a line of its own. Called first thing by the
// failure report and by the panic handler, with device signals off.
pub fn lines_stopping() {
    unsafe { STOPPING = true };
    if unsafe { GROWING_LENGTH } > 0 {
        line_end();
    }
}

// Paints the screen that says why the kernel stopped: the whole screen dark
// red; at the top "The kernel stopped:" and the report, which is the newest
// line kept, printed just before; and below them the lines the kernel said
// before it, as many as fit. Called by the failure report and by the panic
// handler, with device signals off. It uses no heap, because a failure can
// come in the middle of a change to the heap, and it paints only once: a
// failure inside the painting goes to the serial port only.
pub fn lines_stop_screen() {
    if unsafe { STOP_PAINTED } {
        return;
    }
    unsafe { STOP_PAINTED = true };
    let (Some((room, rows)), Some((width, height))) = (lines_place(), screen_size()) else {
        return;
    };
    screen_rectangle_over(0, 0, width, height, STOP_BACKGROUND);
    let added = unsafe { ADDED };
    let mut row = line_paint(b"The kernel stopped:", 0, room, rows, STOP_LETTERS);
    if added > 0 {
        let (report, length) = kept_line(added - 1);
        row = line_paint(&report[..length], row, room, rows, STOP_LETTERS);
    }
    // An empty row, and then what came before the report.
    row = line_paint(b"What the kernel said before that:", row.saturating_add(1), room, rows, STOP_LETTERS);
    let end = added.saturating_sub(1);
    let first = newest_first(end, rows.saturating_sub(row), room);
    for number in first..end {
        let (line, length) = kept_line(number);
        row = line_paint(&line[..length], row, room, rows, STOP_LETTERS);
    }
}
