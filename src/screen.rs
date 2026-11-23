//! Drawing on the screen: filling it, filled rectangles, text, the background
//! with its sentence, and the box in which an app's text is shown. Their
//! colours come from the look in use (`look.rs`). While the kernel's own lines
//! cover the screen (`lines.rs`), this usual picture waits. Notes:
//! `docs/screen.md`. (The chat box is drawn with these pieces by `chat.rs`,
//! and the frame of a table by `drawing.rs`.)

use crate::apps_kept::apps_panel_place;
use crate::firmware::{ColourOrder, Screen};
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH, letter_shape};
use crate::look::look;
use crate::page_tables::map_device_memory;
use crate::processor::device_write_32;

// A colour is three amounts of light, each from 0 (none) to 255 (full):
// red, green and blue. All three at 0 give black, all three at 255 white.
#[derive(Clone, Copy)]
pub struct Colour {
    pub red: u8,
    pub green: u8,
    pub blue: u8,
}

// The screen to draw on. It stays `None` on a machine without a usable
// screen, and then the drawing functions do nothing.
static mut SCREEN: Option<Screen> = None;

// Takes the screen that the firmware described, so that it can be drawn on.
// Call it once, right after the takeover: until the kernel's own page tables
// are in place, the firmware's still lead to the screen's memory, where the
// firmware wrote its own text a moment before.
pub fn screen_setup(screen: Screen) {
    unsafe { SCREEN = Some(screen) };
}

// Makes the screen's memory reachable through the kernel's own page tables.
// Call it right after `page_tables_setup`, before anything is painted again.
pub fn screen_reach() {
    // The screen's memory belongs to a device, the display card. It may lie
    // above the range the page tables cover, so make sure it can be reached.
    if let Some(screen) = unsafe { SCREEN } {
        map_device_memory(screen.memory_start, screen.memory_size);
    }
}

// Whether the kernel's own lines cover the screen (see `lines.rs`). While
// they do, the usual picture waits: the background, the chat box, the box
// with an app's text and the table go on keeping what they show, but none of
// it is painted until the lines go and `look_paint` paints all of it at once.
// The lines are painted with `screen_rectangle_over` and `screen_text_over`,
// which do not wait. Only the startup code and the main loop change this.
static mut COVERED: bool = false;

pub fn screen_cover(covered: bool) {
    unsafe { COVERED = covered };
}

pub fn screen_covered() -> bool {
    unsafe { COVERED }
}

// Says how many dots the screen is across and down. Gives nothing on a
// machine without a usable screen.
pub fn screen_size() -> Option<(u32, u32)> {
    let Some(screen) = (unsafe { SCREEN }) else {
        return None;
    };
    Some((screen.width, screen.height))
}

// Turns a colour into the number that is written into the screen's memory.
// A dot is four bytes. The lowest byte of a number is the one that lands
// first in memory, so the colour that the screen wants first goes lowest.
// The fourth byte is not used and stays 0.
fn dot_value(order: ColourOrder, colour: Colour) -> u32 {
    let (first, third) = match order {
        ColourOrder::RedGreenBlue => (colour.red, colour.blue),
        ColourOrder::BlueGreenRed => (colour.blue, colour.red),
    };
    first as u32 | (colour.green as u32) << 8 | (third as u32) << 16
}

// Paints a filled rectangle of the usual picture. `left` and `top` say where
// its top left corner is, counted in dots from the top left corner of the
// screen. `width` and `height` say how many dots it is across and down. While
// the kernel's lines cover the screen it paints nothing.
pub fn screen_rectangle(left: u32, top: u32, width: u32, height: u32, colour: Colour) {
    if unsafe { COVERED } {
        return;
    }
    rectangle_paint(left, top, width, height, colour);
}

// The same for the kernel's own lines (`lines.rs`), which are painted while
// they cover the screen.
pub fn screen_rectangle_over(left: u32, top: u32, width: u32, height: u32, colour: Colour) {
    rectangle_paint(left, top, width, height, colour);
}

fn rectangle_paint(left: u32, top: u32, width: u32, height: u32, colour: Colour) {
    let Some(screen) = (unsafe { SCREEN }) else {
        return;
    };

    // A rectangle that reaches past the edge of the screen is cut off there.
    // Without this, dots would be written past the end of a row, or past
    // the end of the screen's memory into whatever lies behind it.
    // (`saturating_add` stops at the largest number instead of wrapping
    // round to a small one.)
    let right = left.saturating_add(width).min(screen.width);
    let bottom = top.saturating_add(height).min(screen.height);

    let value = dot_value(screen.colours, colour);
    for y in top..bottom {
        // Where row `y` begins in the screen's memory. A row can take up
        // more dots in memory than the picture is wide, so rows are counted
        // in `row_length`, not in `width`.
        let row = screen.memory_start + y as u64 * screen.row_length as u64 * 4;
        for x in left..right {
            device_write_32(row + x as u64 * 4, value);
        }
    }
}

// Writes one line of text of the usual picture. `left` and `top` say where
// the top left corner of the first sign goes. `size` says how large a dot of
// a letter is painted: with 1 it is one dot of the screen, with 2 a block of
// 2 by 2 dots, and so on, which makes the letters twice as large. Only the
// dots of the letters are painted. What lies between them stays as it was.
// While the kernel's lines cover the screen it paints nothing.
pub fn screen_text(left: u32, top: u32, text: &str, size: u32, colour: Colour) {
    if unsafe { COVERED } {
        return;
    }
    text_paint(left, top, text, size, colour);
}

// The same for the kernel's own lines (`lines.rs`), which are painted while
// they cover the screen.
pub fn screen_text_over(left: u32, top: u32, text: &str, size: u32, colour: Colour) {
    text_paint(left, top, text, size, colour);
}

fn text_paint(left: u32, top: u32, text: &str, size: u32, colour: Colour) {
    let mut sign_left = left;
    for sign in text.chars() {
        // Go through the sign's picture row by row, and paint a small
        // square for every `#` in it.
        let shape = letter_shape(sign);
        for (row, dots) in shape.iter().enumerate() {
            for (column, dot) in dots.iter().enumerate() {
                if *dot == b'#' {
                    // (`saturating_mul` and `saturating_add` stop at the
                    // largest number instead of wrapping round. A square
                    // that lands outside the screen is not painted:
                    // `rectangle_paint` sees to that.)
                    let square_left = sign_left.saturating_add(size.saturating_mul(column as u32));
                    let square_top = top.saturating_add(size.saturating_mul(row as u32));
                    rectangle_paint(square_left, square_top, size, size, colour);
                }
            }
        }
        // The next sign starts one sign's width further right, plus one
        // empty column so that the signs do not touch.
        sign_left = sign_left.saturating_add(size.saturating_mul(LETTER_WIDTH + 1));
    }
}

// How the box looks in which an app's text is shown. The code calls that box
// a "panel", because "box" already means the locked box that apps run in.
// An app only says which text it wants shown. Its sizes are decided here, in
// this one place, and its colours come from the look in use (`look.rs`), so
// that changing the look of every app means changing these values or picking
// another look, and nothing else.
struct PanelStyle {
    // How many dots the panel is across and down.
    width: u32,
    height: u32,
    // How many dots thick the frame round it is.
    frame: u32,
    // How large a dot of a letter is painted (see `screen_text`).
    text_size: u32,
    // How far the text begins from the panel's left and top edges.
    text_left: u32,
    text_top: u32,
    // How many dots it stays below the panel of apps.
    gap: u32,
}

// A panel that holds one line of 40 signs at this width and letter size.
const PANEL_STYLE: PanelStyle = PanelStyle {
    width: 520,
    height: 60,
    frame: 3,
    text_size: 2,
    text_left: 20,
    text_top: 21,
    gap: 20,
};

// What the panel shows, so that it can be painted again in another look:
// whether an app has shown a text since the start, and the signs it shows, as
// many as fit on the panel's line. The room holds 160 bytes, enough for 40
// signs of any kind. Only the startup code and the main loop may touch these.
const PANEL_TEXT_MOST: usize = 160;
static mut PANEL_SHOWN: bool = false;
static mut PANEL_TEXT: [u8; PANEL_TEXT_MOST] = [0; PANEL_TEXT_MOST];
static mut PANEL_TEXT_LENGTH: usize = 0;

// Shows a text in the panel: paints the panel and writes the text in it, on
// one line, and remembers what it wrote. Painting the whole panel each time
// wipes out what it showed before. Where the panel sits is decided here as
// well: under the panel of apps, on every screen.
pub fn screen_panel(text: &str) {
    if (unsafe { SCREEN }).is_none() {
        return;
    }
    let shown = panel_paint(text);

    // Remember the signs that were written, cut at the end of a whole sign
    // if they do not fit the room.
    let mut length = shown.len().min(PANEL_TEXT_MOST);
    while !shown.is_char_boundary(length) {
        length -= 1;
    }
    let mut room = [0u8; PANEL_TEXT_MOST];
    room[..length].copy_from_slice(&shown.as_bytes()[..length]);
    unsafe {
        PANEL_TEXT = room;
        PANEL_TEXT_LENGTH = length;
        PANEL_SHOWN = true;
    }
}

// Paints the panel again with the text it showed last, in the look in use.
// Does nothing if no app has shown a text since the start.
pub fn screen_panel_again() {
    let (shown, room, length) = unsafe { (PANEL_SHOWN, PANEL_TEXT, PANEL_TEXT_LENGTH) };
    if !shown {
        return;
    }
    panel_paint(core::str::from_utf8(&room[..length.min(PANEL_TEXT_MOST)]).unwrap_or(""));
}

// Where the panel sits: its left and top edges, and how many dots it is
// across and down. Under the panel of apps, at its left edge, whether or not
// any app is kept, so that it never covers the frame of a table beside the
// panel; the panel of documents goes under it (see `documents.rs`).
pub fn screen_panel_place() -> (u32, u32, u32, u32) {
    let style = PANEL_STYLE;
    let (apps_left, apps_top, _, apps_height) = apps_panel_place();
    (apps_left, apps_top.saturating_add(apps_height).saturating_add(style.gap), style.width, style.height)
}

// Paints the panel and the text in it, and gives back the part of the text
// that was written: as many signs as fit.
fn panel_paint(text: &str) -> &str {
    if (unsafe { SCREEN }).is_none() {
        return "";
    }
    let style = PANEL_STYLE;
    let look = look();
    let (left, top, _, _) = screen_panel_place();

    // The frame: the whole panel in the frame's colour first, then the
    // inside painted over it, smaller by the frame's thickness on each side.
    screen_rectangle(left, top, style.width, style.height, look.panel_frame);
    screen_rectangle(
        left.saturating_add(style.frame),
        top.saturating_add(style.frame),
        style.width.saturating_sub(style.frame.saturating_mul(2)),
        style.height.saturating_sub(style.frame.saturating_mul(2)),
        look.panel_inside,
    );

    // Nothing an app shows may land outside the panel. `screen_text` stops
    // only at the screen's edges, so the text is held to the panel here: it
    // is written only if a line of letters fits between top and bottom, and
    // only as many signs of it as fit whole between left and right.
    let sign_width = style.text_size.saturating_mul(LETTER_WIDTH + 1);
    let line_height = style.text_size.saturating_mul(LETTER_HEIGHT);
    if sign_width == 0 || style.text_top.saturating_add(line_height) > style.height {
        return "";
    }
    let room = style.width.saturating_sub(style.text_left.saturating_mul(2)) / sign_width;
    let shown = match text.char_indices().nth(room as usize) {
        Some((cut, _)) => &text[..cut],
        None => text,
    };
    screen_text(left.saturating_add(style.text_left), top.saturating_add(style.text_top), shown, style.text_size, look.panel_text);
    shown
}

// Paints the whole screen in one colour.
pub fn screen_fill(colour: Colour) {
    let Some(screen) = (unsafe { SCREEN }) else {
        return;
    };
    screen_rectangle(0, 0, screen.width, screen.height, colour);
}

// The sentence near the top left corner of the screen, which shows that the
// kernel draws its own letters.
const SENTENCE: &str = "Hello from my kernel! I draw my own letters now.";

// Paints the background: the whole screen in the look's colour for it, and
// the sentence, 40 dots from the left and from the top, with every dot of a
// letter a block of 2 by 2 dots. It covers everything that was on the
// screen, so whatever stands in front of it is painted after it.
pub fn screen_background() {
    let look = look();
    screen_fill(look.background);
    screen_text(40, 40, SENTENCE, 2, look.sentence);
}
