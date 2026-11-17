//! Drawing on the screen: filling it, and filled rectangles.
//! Notes: `docs/screen.md`.

use crate::firmware::{ColourOrder, Screen};
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

// Paints the whole screen in one colour.
pub fn screen_fill(colour: Colour) {
    let Some(screen) = (unsafe { SCREEN }) else {
        return;
    };
    screen_rectangle(0, 0, screen.width, screen.height, colour);
}
