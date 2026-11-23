//! The chat box: the place on the screen where the person at the machine
//! types, with what was said so far above the line being typed. Every line
//! that is sent goes to the model, except the two the kernel keeps for
//! itself, `key` and `setup`; the model's words come back as rows of their
//! own, and a tool it asks for is done (see `tools.rs`). When what a tool did
//! needs the model, it is asked about the line again, at most three times in
//! all. What a line brought is remembered, and goes with the next lines (see
//! `conversation.rs`).
//! Notes: `docs/chat.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::apps::{app_print_script, app_run};
use crate::apps_kept::{app_keep, apps_kept_begin};
use crate::conversation::{
    conversation_again, conversation_forget, conversation_line, conversation_record, conversation_row, conversation_sent, conversation_split,
};
use crate::errand::{Answer, Errand, errand_ask};
use crate::files::{download_answer, files_answer, files_asking, files_setup};
use crate::keyboard::BACKSPACE;
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::look::{look, look_answer, look_asking, look_begin, look_paint};
use crate::notebook::{notebook_find, notebook_keep, notebook_ready};
use crate::onboarding::{
    NAME_LIMIT, SETUP_WORD, onboarding_again, onboarding_answer, onboarding_asking, onboarding_begin, onboarding_secret, onboarding_tried,
    onboarding_trying, onboarding_waiting, onboarding_wants_secret, person_name,
};
use crate::screen::{Colour, screen_rectangle, screen_size, screen_text};
use crate::secret::{SECRET_LIMIT, secret_keep, secret_length, wipe};
use crate::model::key_starred_kept;
use crate::page::plain_text;
use crate::serial::serial_print;
use crate::tools::{ToolDone, chat_tools, tool_do, tool_wanted};

// The longest line that can be typed, in signs. A key pressed after that is
// ignored, until a sign is taken away again or the line is sent with Enter.
const CHAT_LINE_LIMIT: usize = 50;

// How many times the model may be asked about one line, the first ask
// included, and not counting the requests that write an app. The last ask
// goes without the list of tools, so that its answer is words.
const ASKS_MOST: usize = 3;

// How many signs of what the model gave a tool the terminal shows.
const TOOL_SHOWN: usize = 300;

// The line whose asks are under way, from its first ask until it ends: how
// many asks went out; the line as it was sent to the model, with the key
// starred, known once the first answer has come; and what the tools the
// model asked for were asked to do (`tool_wanted`), so that none is done
// twice for one line. `setup` ends it, and so does every answer after which
// the model is not asked again. Only the main loop may touch it; it is taken
// out of its place and put back by value.
struct Asks {
    made: usize,
    sent: String,
    wanted: Vec<String>,
}
static mut ASKS: Option<Asks> = None;

fn asks_take() -> Option<Asks> {
    unsafe { (*(&raw mut ASKS)).take() }
}

fn asks_put(asks: Asks) {
    unsafe { ASKS = Some(asks) };
}

// The name under which the last line that was sent is kept in the notebook
// on the disk, so that it is still known after the machine was switched off.
const LAST_LINE: &str = "last line";

// The line that, sent by itself, makes the kernel ask for a secret: a text
// such as the key of a paid service, which must not be seen by anybody else.
const SECRET_WORD: &str = "key";

// While a secret is typed, each sign shows as a star. At most this many stars
// are shown; behind them the row says how many more signs there are.
const STARS_SHOWN: usize = 30;

// How the chat box is laid out. Its sizes are decided here, in this one
// place, and its colours come from the look in use (`look.rs`): changing how
// it looks means changing these values or picking another look, and nothing
// else. From top to bottom the chat box is made of: the frame, some empty
// room, the rows of what was said, the row being typed, and the frame again.
struct ChatStyle {
    // How many rows of what was said are shown above the row being typed.
    rows: u32,
    // How far the chat box stays from the left, right and bottom edges of
    // the screen, in dots.
    margin: u32,
    // How many dots thick the frame round it is.
    frame: u32,
    // How large a dot of a letter is painted (see `screen_text`).
    text_size: u32,
    // How far the text stays from the frame, in dots.
    padding: u32,
    // How many empty dots lie between two rows of text.
    row_gap: u32,
}

// Six rows of what was said, letters twice the size of their pictures.
const CHAT_STYLE: ChatStyle = ChatStyle {
    rows: 6,
    margin: 40,
    frame: 3,
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

// A secret being typed: whether the kernel has asked for one, the signs typed
// so far, and how many they are. The signs are not kept in the line above. A
// text that grows moves in memory as it grows and leaves copies of itself
// behind; this room has a fixed size and a fixed place, and is wiped as soon
// as the secret is handed over.
static mut SECRET_ASKED: bool = false;
static mut SECRET_TYPED: [u8; SECRET_LIMIT] = [0; SECRET_LIMIT];
static mut SECRET_SIGNS: usize = 0;

// Whether signs were typed, and not taken, while the onboarding tried a key.
// The kernel says so when the answer to the try comes.
static mut TYPED_WHILE_TRYING: bool = false;

fn secret_typed() -> &'static mut [u8; SECRET_LIMIT] {
    unsafe { &mut *(&raw mut SECRET_TYPED) }
}

// Whether what is typed now shows as stars: a secret asked for with the line
// "key", or a key or a password that the onboarding asks for (see
// `onboarding.rs`). Both are typed into the room above.
fn stars_wanted() -> bool {
    let asked = unsafe { SECRET_ASKED };
    asked || onboarding_wants_secret()
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

// Where the chat box sits on this screen: its left and top edges, and how
// many dots it is across and down. Gives nothing on a machine without a
// usable screen. The frame of a table is placed above it (see `drawing.rs`).
pub fn chat_box_place() -> Option<(u32, u32, u32, u32)> {
    chat_place().map(|place| (place.left, place.top, place.width, place.height))
}

// How many signs the line being typed may have on this machine: the limit,
// or less if the screen is so narrow that fewer fit on the row. Three places
// of the row are taken: two by the "> " in front and one by the "_" behind.
// On a machine without a screen it is the limit itself. While the kernel
// waits for a name, the limit is the longest name.
fn chat_line_room() -> usize {
    let limit = if onboarding_asking() { NAME_LIMIT } else { CHAT_LINE_LIMIT };
    match chat_place() {
        Some(place) => limit.min(place.room.saturating_sub(3) as usize),
        None => limit,
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
    let look = look();

    // The area reaches from just inside the frame down to the row being
    // typed, and from just inside the frame on the left to just inside it
    // on the right.
    let inside_left = place.left.saturating_add(style.frame);
    let inside_top = place.top.saturating_add(style.frame);
    let inside_width = place.width.saturating_sub(style.frame.saturating_mul(2));
    screen_rectangle(inside_left, inside_top, inside_width, place.typing_top.saturating_sub(inside_top), look.chat_inside);

    let mut top = inside_top.saturating_add(style.padding);
    for (speaker, text) in chat_rows().iter() {
        let colour = match speaker {
            Speaker::Person => look.chat_person,
            Speaker::Kernel => look.chat_kernel,
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
    let look = look();

    // The area reaches from the end of the rows above down to the frame at
    // the bottom.
    let inside_left = place.left.saturating_add(style.frame);
    let inside_width = place.width.saturating_sub(style.frame.saturating_mul(2));
    let inside_bottom = place.top.saturating_add(place.height).saturating_sub(style.frame);
    let area_height = inside_bottom.saturating_sub(place.typing_top);
    screen_rectangle(inside_left, place.typing_top, inside_width, area_height, look.chat_typing);

    // The text goes in the middle between the area's top and bottom.
    let letter_height = style.text_size.saturating_mul(LETTER_HEIGHT);
    let top = place.typing_top.saturating_add(area_height.saturating_sub(letter_height) / 2);
    let text = if stars_wanted() { secret_row() } else { format!("> {}_", chat_line()) };
    chat_write(&place, top, &text, look.chat_person);
}

// What the row being typed shows while a secret is typed: a star for each
// sign, never the sign itself. Past `STARS_SHOWN` stars it says how many more
// signs there are, so that a long secret can be counted without being seen.
fn secret_row() -> String {
    let signs = unsafe { SECRET_SIGNS };
    let mut row = String::from("> ");
    for _ in 0..signs.min(STARS_SHOWN) {
        row.push('*');
    }
    if signs > STARS_SHOWN {
        row.push_str(&format!(" and {} more", signs - STARS_SHOWN));
    }
    row.push('_');
    row
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
    chat_add(Speaker::Kernel, "Kernel: type a line and press Enter.");
    chat_paint();
}

// Paints the whole chat box: the frame, the rows of what was said and the row
// being typed. The look calls it when it paints the whole screen again.
pub fn chat_paint() {
    let Some(place) = chat_place() else {
        return;
    };
    // The frame: the whole chat box in the frame's colour. The two areas
    // inside it are painted over that, and leave the frame showing.
    screen_rectangle(place.left, place.top, place.width, place.height, look().chat_frame);
    chat_paint_rows();
    chat_paint_typing();
}

// Says what the kernel has to say once the notebook is opened: a greeting by
// the person's name, or, at a start that does not know their name yet, the
// question for it (see `onboarding.rs`); and the last line that was sent
// before the machine was switched off, if the notebook on the disk holds one.
// Before that, it puts the look kept in the notebook in use, so that all of
// it shows in that look. Last, it finds the apps kept on the disk, for the
// panel that lists them (see `apps_kept.rs`). Call it once at startup, after
// the notebook is opened. Nothing is painted here: the kernel's own lines
// cover the screen while it starts, and when the start is over the whole
// usual picture is painted in the look in use (see `lines.rs`).
pub fn chat_begin() {
    let look_trouble = look_begin();
    let mut rows = onboarding_begin();
    if !rows.is_empty() {
        // The greeting or the question takes the place of the row that
        // `chat_setup` put up, which says what to do.
        chat_rows().clear();
    }
    // A row about a kept look that cannot be used, and the row of the last
    // line. While the kernel waits for an answer, its question stays last.
    let mut more = Vec::new();
    more.extend(look_trouble);
    more.extend(recall_row());
    if onboarding_waiting() || look_asking() {
        more.extend(rows);
        rows = more;
    } else {
        rows.extend(more);
    }
    for row in rows.iter() {
        serial_print(&format!("{}\r\n", row));
        chat_add(Speaker::Kernel, row);
    }
    apps_kept_begin();
}

// The row that says the last line that was sent before the machine was
// switched off, or nothing if the notebook holds none.
fn recall_row() -> Option<String> {
    match notebook_find(LAST_LINE) {
        Ok(Some(kept)) => {
            // What comes from the disk comes from outside the kernel: at
            // most as many signs as a line may have are taken, and every
            // byte that is not a plain sign becomes a dot.
            let said: String = kept.iter().take(CHAT_LINE_LIMIT).map(|byte| if (b' '..=b'~').contains(byte) { *byte as char } else { '.' }).collect();
            Some(format!("Kernel: last time you said \"{}\"", said))
        }
        // Nothing was kept yet: there is nothing to say.
        Ok(None) => None,
        Err(reason) => Some(format!("Kernel: I cannot read what you said last time, because {}", reason)),
    }
}

// Says something in the chat box that is not an answer to the line just
// sent: adds it to what was said as a row of the kernel's and repeats it in
// the terminal. `chat_answer` calls this when the answer to an errand has
// come in, and `tools.rs` when it does what the model asked for. The row is
// remembered with the line it answers (see `conversation.rs`). A text that
// comes from outside the kernel must be cleaned before it is handed over.
pub fn chat_say(text: &str) {
    let row = format!("Kernel: {}", text);
    serial_print(&format!("{}\r\n", row));
    chat_add(Speaker::Kernel, &row);
    chat_paint_rows();
    conversation_row(&row);
}

// Says the model's own words in the chat box, as a row that begins with
// "Model:", so that they cannot be taken for the kernel's own sentences, and
// repeats it in the terminal. The words were cleaned in `model.rs`. The row
// is remembered with the line it answers.
fn model_say(words: &str) {
    let row = format!("Model: {}", words);
    serial_print(&format!("{}\r\n", row));
    chat_add(Speaker::Kernel, &row);
    chat_paint_rows();
    conversation_row(&row);
}

// Remembers a sentence of the kernel's with the line it answers, as a row
// that begins with "Kernel:", without saying it in the chat box or the
// terminal: what an app left behind, which goes back to the model when it is
// asked about the line again (see `ask_again`). The screen and the terminal
// show it already, in the app's box and in the app's own lines. It came from
// the app, through the box, which cleaned it and held it to its bound; a
// piece of the key in it is starred here, before it is remembered.
pub fn chat_remember(text: &str) {
    conversation_row(&format!("Kernel: {}", key_starred_kept(text)));
}

// Every line that is sent, but for `key` and `setup`, goes to the model, with
// the list of what the kernel can do for it (see `tools.rs`) and the record
// of what was said before it (see `conversation.rs`). That needs a key, and
// it is an errand for the network's task: the answer comes later, as rows of
// its own (see `chat_answer`). Gives back the row that says what happens now.
fn model_ask(said: &str) -> String {
    if secret_length() == 0 {
        return String::from("Kernel: I cannot ask the model, because no key is kept. Send the line \"key\" first.");
    }
    match errand_ask(Errand::ChatLine { line: String::from(said), tools: chat_tools(), record: conversation_record(), done: String::new() }) {
        Ok(()) => {
            conversation_sent();
            asks_put(Asks { made: 1, sent: String::new(), wanted: Vec::new() });
            String::from("Kernel: I am asking the model.")
        }
        Err(reason) => format!("Kernel: I cannot ask the model, because {}", reason),
    }
}

// Asks the model about the line again, because what a tool did needs it: a
// new app, an app that was stopped, a tool the kernel turned down, or a
// second tool it did not do. The ask has the line's first ask's shape: the
// line, as it was sent, as the person's message; the instruction text with
// the record of the lines before it, and behind that what came of the line
// so far (`conversation_split`); the list of tools as it stands now, or none
// for the last ask. The chat box gets no row for it, and the terminal one
// line of its own. Nothing is asked when nothing of the line is remembered
// any more, because everything was forgotten. When the ask cannot go, the
// kernel says why, and the line ends there.
fn ask_again(mut asks: Asks) {
    let Some((record, done)) = conversation_split() else {
        return;
    };
    asks.made += 1;
    let last = asks.made >= ASKS_MOST;
    let tools = if last { String::new() } else { chat_tools() };
    match errand_ask(Errand::ChatLine { line: asks.sent.clone(), tools, record, done }) {
        Ok(()) => {
            conversation_sent();
            let without = if last { ", without tools" } else { "" };
            serial_print(&format!("Round {} of {}: the model is asked again, with what came of the line so far{}\r\n", asks.made, ASKS_MOST, without));
            asks_put(asks);
        }
        Err(reason) => chat_say(&format!("I cannot ask the model again, because {}", reason)),
    }
}

// What comes of a tool done for a line, for the line's asks: a line that
// waits keeps them, one whose tool goes back asks the model again, and one
// that ends lets them go. Nothing is asked again once `setup` ended the asks.
fn asks_after(outcome: ToolDone) {
    let Some(asks) = asks_take() else {
        return;
    };
    match outcome {
        ToolDone::Awaited => asks_put(asks),
        ToolDone::Back => ask_again(asks),
        ToolDone::Ended => {}
    }
}

// Says the answer to an errand, which the main loop picks up from the
// network's task. The answer to the try of a key goes to the onboarding,
// which says what comes of it. For a line, the line as it was sent is
// remembered first (see `conversation.rs`); the answer to another ask about
// it adds to what is remembered of it. Then the model's words come, then
// what the kernel has to say about the answer, if anything, and then the
// tool the model asked for is done. For an app, the row about the answer
// comes first; a script that the model wrote is shown in the terminal below
// that row, then run, and a second row says how the run went (see `apps.rs`).
// An app that ran to its end is kept on the disk; a third row comes only if
// that failed (see `apps_kept.rs`). The terminal's line about the tokens a
// good answer took follows the row about the answer. When what came of a
// tool needs the model, it is asked about the line again (`ask_again`).
pub fn chat_answer(answer: Answer) {
    if let Errand::ChatLine { done, .. } = &answer.errand {
        let first = done.is_empty();
        if first {
            conversation_line(answer.sent.as_deref());
        } else {
            conversation_again();
        }
        let reply = answer.reply;
        if let Some(words) = reply.as_ref().and_then(|reply| reply.words.as_deref()) {
            model_say(words);
        }
        if !answer.sentence.is_empty() {
            chat_say(&answer.sentence);
        }
        if let Some(tokens) = &answer.tokens {
            serial_print(&format!("{}\r\n", tokens));
        }
        // A line ends at every answer that brings no tool, and at every
        // answer that was no good one: what was done stays done.
        let asks = asks_take();
        let Some(call) = reply.as_ref().and_then(|reply| reply.tool.as_ref()) else {
            return;
        };
        // What the model asked a tool for, as it asked it, in the terminal:
        // the tool's name and what it gave the tool, in which the key was
        // starred already (see `model.rs`), cleaned and cut at `TOOL_SHOWN`
        // signs. It is not said in the chat box, and not remembered.
        if call.inputs.is_empty() {
            serial_print(&format!("Tool: {}\r\n", call.name));
        } else {
            serial_print(&format!("Tool: {} {}\r\n", call.name, plain_text(&call.inputs, TOOL_SHOWN)));
        }
        let more = reply.as_ref().is_some_and(|reply| reply.more);
        let Some(mut asks) = asks else {
            // `setup` was sent while the answer was awaited: the tool is
            // still done, as before, but the model is not asked again.
            if more {
                chat_say("the model asked for more than one thing at once, so I do only the first.");
            }
            tool_do(call);
            return;
        };
        if asks.made >= ASKS_MOST {
            chat_say("the model asked for a tool in its last answer about this line, when none was offered, so I did nothing.");
            return;
        }
        if first {
            asks.sent = answer.sent.unwrap_or_default();
        }
        if more {
            chat_say("the model asked for more than one thing at once, so I do only the first.");
        }
        let wanted = tool_wanted(call);
        let outcome = if asks.wanted.contains(&wanted) {
            chat_say("the model asked for the same thing again for this line, so I did not do it twice.");
            ToolDone::Back
        } else {
            asks.wanted.push(wanted);
            tool_do(call)
        };
        // A second tool that was not done goes back too.
        match outcome {
            ToolDone::Awaited => asks_put(asks),
            ToolDone::Back => ask_again(asks),
            ToolDone::Ended if more => ask_again(asks),
            ToolDone::Ended => {}
        }
        return;
    }
    // A hop of a file the person wants (see `files.rs`).
    if let Errand::Download(_) = &answer.errand {
        let outcome = download_answer(answer.fetched, &answer.sentence);
        asks_after(outcome);
        return;
    }
    if let Errand::AppRequest { request, inputs, values } = &answer.errand {
        let asks = asks_take();
        chat_say(&answer.sentence);
        if let Some(tokens) = &answer.tokens {
            serial_print(&format!("{}\r\n", tokens));
        }
        if let Some(script) = &answer.script {
            app_print_script(script);
            let run = app_run(script, values);
            chat_say(&run.sentence);
            if asks.is_some() {
                for told in run.told.iter() {
                    chat_remember(told);
                }
            }
            if run.ran {
                if let Some(trouble) = app_keep(request, inputs, script) {
                    chat_say(&trouble);
                }
            }
        }
        // What came of a new app goes back to the model: the app's run, or
        // why the model's answer is no app. Not when the provider gave no
        // good answer (only a good one brings a line about tokens): a
        // request that fails ends the line, as every one does. Nor when
        // `setup` was sent while the app was awaited.
        if let Some(asks) = asks {
            if answer.tokens.is_some() {
                ask_again(asks);
            }
        }
        return;
    }
    let mut rows = onboarding_tried(answer.key, &answer.sentence);
    if unsafe { TYPED_WHILE_TRYING } {
        unsafe { TYPED_WHILE_TRYING = false };
        rows.insert(0, String::from("Kernel: what was typed while I tried the key was not taken."));
    }
    kernel_rows(&rows);
}

// Says rows of the kernel's: repeats them in the terminal in one go, so that
// no other task's line lands in between, adds them to what was said, and
// paints the chat box again.
fn kernel_rows(rows: &[String]) {
    let mut repeated = String::new();
    for row in rows.iter() {
        repeated.push_str(row);
        repeated.push_str("\r\n");
    }
    serial_print(&repeated);
    for row in rows.iter() {
        chat_add(Speaker::Kernel, row);
    }
    chat_paint_rows();
    chat_paint_typing();
}

// Takes one typed key, given as its letter. A letter is added to the line
// being typed, Backspace takes the last one away, and Enter sends the line:
// it moves up into what was said, and goes to the model, unless it is one of
// the two lines the kernel keeps for itself.
// While the kernel waits for the answer to its question (see
// `onboarding.rs`), or for the number of a look (see `look.rs`), the line
// that is sent is that answer.
pub fn chat_key(letter: u8) {
    // While the kernel waits for a secret, a key or a password, the keys go
    // there and nowhere else.
    if stars_wanted() {
        secret_key(letter);
        return;
    }
    let line = chat_line();
    match letter {
        BACKSPACE => {
            // With nothing typed there is nothing to take away.
            if line.pop().is_none() {
                return;
            }
            chat_paint_typing();
        }
        b'\n' if files_asking() => {
            // The answer to a question about a fetch or a kept file (see
            // `files.rs`): "yes", or anything else for no. It is shown, but
            // not remembered, not kept as the last line, and not sent to the
            // model; what comes of it is said, and the line goes on or ends.
            let said = core::mem::take(line);
            let mine = format!("{}: {}", person_name(), said);
            serial_print(&format!("{}\r\n", mine));
            chat_add(Speaker::Person, &mine);
            chat_paint_rows();
            chat_paint_typing();
            asks_after(files_answer(&said));
        }
        b'\n' if onboarding_asking() || look_asking() => {
            // The answer to a question: the name the onboarding asks for, or
            // the number of a look. It may be empty: Enter alone leaves the
            // name or the look as it is. It is not given back, and it is not
            // kept as the last line; the onboarding or the look keeps what it
            // needs, and says what comes next.
            let said = core::mem::take(line);
            let mut rows = Vec::new();
            if !said.is_empty() {
                rows.push((Speaker::Person, format!("{}: {}", person_name(), said)));
            }
            let (answer, look_changed) = if look_asking() { look_answer(&said) } else { (onboarding_answer(&said), false) };
            for row in answer {
                rows.push((Speaker::Kernel, row));
            }

            // Repeated in the terminal in one go, like any other line.
            let mut repeated = String::new();
            for (_, row) in rows.iter() {
                repeated.push_str(row);
                repeated.push_str("\r\n");
            }
            serial_print(&repeated);
            for (speaker, row) in rows.iter() {
                chat_add(*speaker, row);
            }
            // A look that was just tried shows on the whole screen at once.
            if look_changed {
                look_paint();
            } else {
                chat_paint_rows();
                chat_paint_typing();
            }
        }
        b'\n' => {
            // An empty line is not sent.
            if line.is_empty() {
                return;
            }
            // Take the typed line out, which leaves an empty one behind.
            let said = core::mem::take(line);
            let mine = format!("{}: {}", person_name(), said);

            // Two lines stay with the kernel and never go to the model. The
            // word that asks the kernel to take a secret: from the next key
            // on, what is typed is the secret, until Enter.
            let asks_for_secret = said == SECRET_WORD;
            let answer = if asks_for_secret {
                String::from("Kernel: type the secret and press Enter. It shows as stars.")
            } else if said == SETUP_WORD {
                // And the word that asks the questions of the onboarding
                // again: the kernel asks for the person's name, and the next
                // line is the answer. Another person may be at the machine
                // now, so what was said before is forgotten, and the model is
                // not asked again about a line whose asks are under way.
                asks_take();
                files_setup();
                conversation_forget();
                onboarding_again()
            } else {
                // Every other line goes to the model.
                model_ask(&said)
            };
            if asks_for_secret {
                unsafe { SECRET_ASKED = true };
            }

            // What is said in the chat box is repeated in the terminal, both
            // lines in one go so that no other task's line lands in between.
            serial_print(&format!("{}\r\n{}\r\n", mine, answer));

            chat_add(Speaker::Person, &mine);
            chat_add(Speaker::Kernel, &answer);

            // Keep the line on the disk, if there is a notebook to keep it
            // in. When that works nothing is said about it. When it does
            // not, the kernel says so, and the chat goes on as before.
            if notebook_ready() {
                if let Err(reason) = notebook_keep(LAST_LINE, said.as_bytes()) {
                    let trouble = format!("Kernel: I could not keep that line, because {}", reason);
                    serial_print(&format!("{}\r\n", trouble));
                    chat_add(Speaker::Kernel, &trouble);
                }
            }
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

// Takes one typed key while the kernel waits for a secret, or for a key or a
// password that the onboarding asks for. The signs are counted and shown as
// stars. They are never printed, never put into a row of what was said and
// never kept on the disk as they are. Enter hands them over, and the room
// they were typed into is wiped: a secret goes to the place where it is kept
// in memory, and a key or a password goes to the onboarding. Enter with
// nothing typed takes no secret and leaves the one kept before as it was.
fn secret_key(letter: u8) {
    // While the onboarding tries a key with the provider, nothing typed is
    // taken: it would stand ready as the answer to a question that is not
    // asked yet, and could go to the provider as a key. Enter says why, and
    // the answer to the try says that something was not taken.
    if onboarding_trying() && letter != b'\n' {
        unsafe { TYPED_WHILE_TRYING = true };
        return;
    }
    let typed = secret_typed();
    let signs = unsafe { SECRET_SIGNS };
    match letter {
        BACKSPACE => {
            if signs == 0 {
                return;
            }
            // The sign that is taken away is wiped too.
            wipe(&mut typed[signs - 1..signs]);
            unsafe { SECRET_SIGNS = signs - 1 };
            chat_paint_typing();
        }
        b'\n' if unsafe { SECRET_ASKED } => {
            let answer = if signs == 0 {
                String::from("Kernel: no secret was taken.")
            } else {
                let replaced = secret_length() > 0;
                let taken = secret_keep(&typed[..signs]);
                wipe(typed);
                format!(
                    "Kernel: I took a secret of {} {}. It is kept in memory only.{}",
                    taken,
                    if taken == 1 { "sign" } else { "signs" },
                    if replaced { " The one before is gone." } else { "" }
                )
            };
            unsafe {
                SECRET_SIGNS = 0;
                SECRET_ASKED = false;
            }
            serial_print(&format!("{}\r\n", answer));
            chat_add(Speaker::Kernel, &answer);
            chat_paint_rows();
            chat_paint_typing();
        }
        b'\n' => {
            // A key or a password that the onboarding asked for (see
            // `onboarding.rs`). The signs go there straight from this room,
            // which is wiped afterwards. The row being typed is emptied
            // first, so that it shows no stars while a password is turned
            // into a key; the onboarding says what it is doing meanwhile.
            unsafe { SECRET_SIGNS = 0 };
            let rows = onboarding_secret(&typed[..signs], &mut |row: &str| {
                serial_print(&format!("{}\r\n", row));
                chat_add(Speaker::Kernel, row);
                chat_paint_rows();
                chat_paint_typing();
            });
            wipe(typed);
            kernel_rows(&rows);
        }
        _ => {
            // A secret of the longest size takes no more signs.
            if signs >= SECRET_LIMIT {
                return;
            }
            typed[signs] = letter;
            unsafe { SECRET_SIGNS = signs + 1 };
            chat_paint_typing();
        }
    }
}
