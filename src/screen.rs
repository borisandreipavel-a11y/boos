//! Drawing on the screen: filling it, filled rectangles, text, and the box
//! in which an app's text is shown. Notes: `docs/screen.md`. (The chat box
//! is drawn with these pieces by `chat.rs`.)

use crate::firmware::{ColourOrder, Screen};
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH, letter_shape};
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

// Takes the screen that the firmware described and gets it ready to be
// drawn on. Call it once, after the kernel's own page tables are in place.
pub fn screen_setup(screen: Screen) {
    // The screen's memory belongs to a device, the display card. It may lie
    // above the range the page tables cover, so make sure it can be reached.
    map_device_memory(screen.memory_start, screen.memory_size);
    unsafe { SCREEN = Some(screen) };
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

// Paints a filled rectangle. `left` and `top` say where its top left corner
// is, counted in dots from the top left corner of the screen. `width` and
// `height` say how many dots it is across and down.
pub fn screen_rectangle(left: u32, top: u32, width: u32, height: u32, colour: Colour) {
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

// Writes one line of text. `left` and `top` say where the top left corner of
// the first sign goes. `size` says how large a dot of a letter is painted:
// with 1 it is one dot of the screen, with 2 a block of 2 by 2 dots, and so
// on, which makes the letters twice as large. Only the dots of the letters
// are painted. What lies between them stays as it was.
pub fn screen_text(left: u32, top: u32, text: &str, size: u32, colour: Colour) {
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
                    // `screen_rectangle` sees to that.)
                    let square_left = sign_left.saturating_add(size.saturating_mul(column as u32));
                    let square_top = top.saturating_add(size.saturating_mul(row as u32));
                    screen_rectangle(square_left, square_top, size, size, colour);
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
// An app only says which text it wants shown. Everything about the look is
// decided here, in this one place, so that changing the look of every app
// means changing these values and nothing else.
struct PanelStyle {
    // How many dots the panel is across and down.
    width: u32,
    height: u32,
    // How many dots thick the frame round it is, and the frame's colour.
    frame: u32,
    frame_colour: Colour,
    // The colour inside the frame, and the colour of the letters.
    inside_colour: Colour,
    text_colour: Colour,
    // How large a dot of a letter is painted (see `screen_text`).
    text_size: u32,
    // How far the text begins from the panel's left and top edges.
    text_left: u32,
    text_top: u32,
}

// A light panel with an orange frame and black letters. At this width and
// letter size it holds one line of 40 signs.
const PANEL_STYLE: PanelStyle = PanelStyle {
    width: 520,
    height: 60,
    frame: 3,
    frame_colour: Colour { red: 255, green: 150, blue: 0 },
    inside_colour: Colour { red: 240, green: 240, blue: 240 },
    text_colour: Colour { red: 0, green: 0, blue: 0 },
    text_size: 2,
    text_left: 20,
    text_top: 21,
};

// Shows a text in the panel: paints the panel and writes the text in it, on
// one line. Painting the whole panel each time wipes out what it showed
// before. Where the panel sits is part of the look as well: in the middle of
// the screen.
pub fn screen_panel(text: &str) {
    let Some(screen) = (unsafe { SCREEN }) else {
        return;
    };
    let style = PANEL_STYLE;

    // Half the screen's width less half the panel's puts it in the middle.
    let left = (screen.width / 2).saturating_sub(style.width / 2);
    let top = (screen.height / 2).saturating_sub(style.height / 2);

    // The frame: the whole panel in the frame's colour first, then the
    // inside painted over it, smaller by the frame's thickness on each side.
    screen_rectangle(left, top, style.width, style.height, style.frame_colour);
    screen_rectangle(
        left.saturating_add(style.frame),
        top.saturating_add(style.frame),
        style.width.saturating_sub(style.frame.saturating_mul(2)),
        style.height.saturating_sub(style.frame.saturating_mul(2)),
        style.inside_colour,
    );

    // Nothing an app shows may land outside the panel. `screen_text` stops
    // only at the screen's edges, so the text is held to the panel here: it
    // is written only if a line of letters fits between top and bottom, and
    // only as many signs of it as fit whole between left and right.
    let sign_width = style.text_size.saturating_mul(LETTER_WIDTH + 1);
    let line_height = style.text_size.saturating_mul(LETTER_HEIGHT);
    if sign_width == 0 || style.text_top.saturating_add(line_height) > style.height {
        return;
    }
    let room = style.width.saturating_sub(style.text_left.saturating_mul(2)) / sign_width;
    let shown = match text.char_indices().nth(room as usize) {
        Some((cut, _)) => &text[..cut],
        None => text,
    };
    screen_text(left.saturating_add(style.text_left), top.saturating_add(style.text_top), shown, style.text_size, style.text_colour);
}

// Paints the whole screen in one colour.
pub fn screen_fill(colour: Colour) {
    let Some(screen) = (unsafe { SCREEN }) else {
        return;
    };
    screen_rectangle(0, 0, screen.width, screen.height, colour);
}
