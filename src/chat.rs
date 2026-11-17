//! The chat box: the place on the screen where the person at the machine
//! types, with what was said so far above the line being typed.
//! Notes: `docs/chat.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::keyboard::BACKSPACE;
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::screen::{Colour, screen_rectangle, screen_size, screen_text};
use crate::serial::serial_print;

// The longest line that can be typed, in signs. A key pressed after that is
// ignored, until a sign is taken away again or the line is sent with Enter.
const CHAT_LINE_LIMIT: usize = 50;

// How the chat box looks. Everything about its look is decided here, in this
// one place: changing the look means changing these values and nothing else.
// From top to bottom the chat box is made of: the frame, some empty room,
// the rows of what was said, the row being typed, and the frame again.
struct ChatStyle {
    // How many rows of what was said are shown above the row being typed.
    rows: u32,
    // How far the chat box stays from the left, right and bottom edges of
    // the screen, in dots.
    margin: u32,
    // How many dots thick the frame round it is, and the frame's colour.
    frame: u32,
    frame_colour: Colour,
    // The colour behind what was said, and the colour behind the row being
    // typed.
    inside_colour: Colour,
    typing_colour: Colour,
    // The colour of the letters: of what the person said and types, and of
    // what the kernel said.
    person_colour: Colour,
    kernel_colour: Colour,
    // How large a dot of a letter is painted (see `screen_text`).
    text_size: u32,
    // How far the text stays from the frame, in dots.
    padding: u32,
    // How many empty dots lie between two rows of text.
    row_gap: u32,
}

// A light chat box with an orange frame, like the box that shows an app's
// text. What the person says is black, what the kernel says dark blue, and
// the row being typed is white behind its letters.
const CHAT_STYLE: ChatStyle = ChatStyle {
    rows: 6,
    margin: 40,
    frame: 3,
    frame_colour: Colour { red: 255, green: 150, blue: 0 },
    inside_colour: Colour { red: 232, green: 236, blue: 244 },
    typing_colour: Colour { red: 255, green: 255, blue: 255 },
    person_colour: Colour { red: 0, green: 0, blue: 0 },
    kernel_colour: Colour { red: 0, green: 60, blue: 140 },
    text_size: 2,
    padding: 10,
    row_gap: 4,
};

// Who said a row. It decides the colour of the row's letters.
#[derive(Clone, Copy)]
enum Speaker {
    Person,
    Kernel,
}

// What the chat box holds: the rows of what was said, oldest first, and the
// line being typed. Only the main loop may touch these two. Nothing protects
// them against a second task, so no other task may call a function of this
// file.
static mut CHAT_ROWS: Vec<(Speaker, String)> = Vec::new();
static mut CHAT_LINE: String = String::new();

// Rust refuses a plain reference to a `static mut`, so these two hand the
// lists out through their addresses (`&raw mut`). Rust cannot check what
// happens to a list handed out this way, so one rule has to be kept by hand:
// after calling another function of this file, do not go on using a list
// that was fetched before the call. That function fetches the list itself,
// and two holders changing one list at once would break it.
fn chat_rows() -> &'static mut Vec<(Speaker, String)> {
    unsafe { &mut *(&raw mut CHAT_ROWS) }
}

fn chat_line() -> &'static mut String {
    unsafe { &mut *(&raw mut CHAT_LINE) }
}

// Where the chat box sits on this screen and how much fits in it. All of it
// is worked out from the style and the screen's size, so that it fits a
// screen of any size.
struct ChatPlace {
    // The top left corner of the chat box, and how many dots it is across
    // and down.
    left: u32,
    top: u32,
    width: u32,
    height: u32,
    // How many dots lie between the top of one row of text and the next.
    row_height: u32,
    // Where the row being typed begins, counted from the top of the screen.
    typing_top: u32,
    // How many signs fit whole on one row.
    room: u32,
}

// Works out the chat box's place: along the bottom of the screen, as wide as
// the screen less the margins. Gives nothing on a machine without a usable
// screen. (`saturating_...` stops at the smallest or largest number instead
// of wrapping round, so odd values in the style cannot turn a small number
// into a huge one.)
fn chat_place() -> Option<ChatPlace> {
    let Some((screen_width, screen_height)) = screen_size() else {
        return None;
    };
    let style = CHAT_STYLE;

    // A row is as high as a letter, plus the gap to the next row.
    let row_height = style.text_size.saturating_mul(LETTER_HEIGHT).saturating_add(style.row_gap);
    let rows_height = style.rows.saturating_mul(row_height);

    let width = screen_width.saturating_sub(style.margin.saturating_mul(2));
    let height = style
        .frame
        .saturating_mul(2)
        .saturating_add(style.padding.saturating_mul(2))
        .saturating_add(rows_height)
        .saturating_add(row_height);
    let left = style.margin;
    let top = screen_height.saturating_sub(style.margin).saturating_sub(height);

    // The row being typed begins below the frame, the empty room and the
    // rows of what was said.
    let typing_top = top.saturating_add(style.frame).saturating_add(style.padding).saturating_add(rows_height);

    // A sign takes up its own width and one empty column. The text may use
    // the width that is left between the frame and the empty room on both
    // sides.
    let sign_width = style.text_size.saturating_mul(LETTER_WIDTH + 1);
    let text_width = width.saturating_sub(style.frame.saturating_mul(2)).saturating_sub(style.padding.saturating_mul(2));
    let room = if sign_width == 0 { 0 } else { text_width / sign_width };

    Some(ChatPlace { left, top, width, height, row_height, typing_top, room })
}

// How many signs the line being typed may have on this machine: the limit,
// or less if the screen is so narrow that fewer fit on the row. Three places
// of the row are taken: two by the "> " in front and one by the "_" behind.
// On a machine without a screen it is the limit itself.
fn chat_line_room() -> usize {
    match chat_place() {
        Some(place) => CHAT_LINE_LIMIT.min(place.room.saturating_sub(3) as usize),
        None => CHAT_LINE_LIMIT,
    }
}

// Writes one row of text into the chat box, with its top at `top`. Nothing
// may land outside the chat box, and `screen_text` stops only at the edges
// of the screen. So the text is held to the chat box here: only as many
// signs of it are written as fit whole on a row.
fn chat_write(place: &ChatPlace, top: u32, text: &str, colour: Colour) {
    let style = CHAT_STYLE;
    let shown = match text.char_indices().nth(place.room as usize) {
        Some((cut, _)) => &text[..cut],
        None => text,
    };
    let left = place.left.saturating_add(style.frame).saturating_add(style.padding);
    screen_text(left, top, shown, style.text_size, colour);
}

// Paints the rows of what was said: first their whole area in the inside
// colour, which wipes out what stood there, then each row's text.
fn chat_paint_rows() {
    let Some(place) = chat_place() else {
        return;
    };
    let style = CHAT_STYLE;

    // The area reaches from just inside the frame down to the row being
    // typed, and from just inside the frame on the left to just inside it
    // on the right.
    let inside_left = place.left.saturating_add(style.frame);
    let inside_top = place.top.saturating_add(style.frame);
    let inside_width = place.width.saturating_sub(style.frame.saturating_mul(2));
    screen_rectangle(inside_left, inside_top, inside_width, place.typing_top.saturating_sub(inside_top), style.inside_colour);

    let mut top = inside_top.saturating_add(style.padding);
    for (speaker, text) in chat_rows().iter() {
        let colour = match speaker {
            Speaker::Person => style.person_colour,
            Speaker::Kernel => style.kernel_colour,
        };
        chat_write(&place, top, text, colour);
        top = top.saturating_add(place.row_height);
    }
}

// Paints the row being typed: its area in its own colour, then "> ", the
// line typed so far, and a "_" that marks where the next sign will go.
fn chat_paint_typing() {
    let Some(place) = chat_place() else {
        return;
    };
    let style = CHAT_STYLE;

    // The area reaches from the end of the rows above down to the frame at
    // the bottom.
    let inside_left = place.left.saturating_add(style.frame);
    let inside_width = place.width.saturating_sub(style.frame.saturating_mul(2));
    let inside_bottom = place.top.saturating_add(place.height).saturating_sub(style.frame);
    let area_height = inside_bottom.saturating_sub(place.typing_top);
    screen_rectangle(inside_left, place.typing_top, inside_width, area_height, style.typing_colour);

    // The text goes in the middle between the area's top and bottom.
    let letter_height = style.text_size.saturating_mul(LETTER_HEIGHT);
    let top = place.typing_top.saturating_add(area_height.saturating_sub(letter_height) / 2);
    chat_write(&place, top, &format!("> {}_", chat_line()), style.person_colour);
}

// Adds a text to what was said. A text longer than a row goes on in the next
// row. When there are more rows than the chat box shows, the oldest go.
// Nothing is kept on a machine without a screen, where nothing is shown.
fn chat_add(speaker: Speaker, text: &str) {
    let Some(place) = chat_place() else {
        return;
    };
    if place.room == 0 {
        return;
    }
    let rows = chat_rows();

    // Cut the text into pieces of as many signs as fit on a row.
    let signs: Vec<char> = text.chars().collect();
    for piece in signs.chunks(place.room as usize) {
        rows.push((speaker, piece.iter().collect()));
    }
    while rows.len() > CHAT_STYLE.rows as usize {
        rows.remove(0);
    }
}

// Paints the chat box for the first time, with one row from the kernel that
// says what to do. Call it once at startup, after the screen is set up.
pub fn chat_setup() {
    let Some(place) = chat_place() else {
        return;
    };
    chat_add(Speaker::Kernel, "Kernel: type a line and press Enter.");

    // The frame: the whole chat box in the frame's colour. The two areas
    // inside it are painted over that, and leave the frame showing.
    screen_rectangle(place.left, place.top, place.width, place.height, CHAT_STYLE.frame_colour);
    chat_paint_rows();
    chat_paint_typing();
}

// Takes one typed key, given as its letter. A letter is added to the line
// being typed, Backspace takes the last one away, and Enter sends the line:
// it moves up into what was said, and the kernel answers by giving it back.
pub fn chat_key(letter: u8) {
    let line = chat_line();
    match letter {
        BACKSPACE => {
            // With nothing typed there is nothing to take away.
            if line.pop().is_none() {
                return;
            }
            chat_paint_typing();
        }
        b'\n' => {
            // An empty line is not sent.
            if line.is_empty() {
                return;
            }
            // Take the typed line out, which leaves an empty one behind.
            let said = core::mem::take(line);
            let mine = format!("You: {}", said);
            let answer = format!("Kernel: you said \"{}\"", said);

            // What is said in the chat box is repeated in the terminal, both
            // lines in one go so that no other task's line lands in between.
            serial_print(&format!("{}\r\n{}\r\n", mine, answer));

            chat_add(Speaker::Person, &mine);
            chat_add(Speaker::Kernel, &answer);
            chat_paint_rows();
            chat_paint_typing();
        }
        _ => {
            // A full line takes no more signs.
            if line.len() >= chat_line_room() {
                return;
            }
            line.push(letter as char);
            chat_paint_typing();
        }
    }
}
