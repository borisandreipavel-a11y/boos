//! The tools: what the kernel can do when the model asks for it. Every line
//! typed in the chat box goes to the model (see `chat.rs` and `model.rs`), and
//! with it goes a list of tools, each with a name, one sentence and what it
//! needs to be told (`chat_tools`), and what was said before it (see
//! `conversation.rs`). The model answers in words, or asks for one of the
//! tools; the kernel then does it, says in one plain sentence how that went,
//! and gives back whether what came of it needs the model (`tool_do`), which
//! is then asked about the line again (see `chat.rs`). What the model asks
//! for comes from outside the kernel, and is checked before anything is
//! done. Only the main loop may call these functions.
//! Notes: `docs/tools.md`.

use alloc::format;
use alloc::string::String;

use crate::apps::{app_make, app_run};
use crate::apps_kept::{REQUEST_MOST, app_kept, apps_listed, apps_page_turn, apps_pages};
use crate::chat::{chat_remember, chat_say};
use crate::conversation::{conversation_forget, conversation_remembers};
use crate::drawing::{drawing_room, drawing_table, drawing_wanted};
use crate::files::{download_start, files_listed, files_usable, remove_ask};
use crate::json::{Step, json_find_number, json_find_text, json_text};
use crate::look::{look_paint, look_pick, looks_told};
use crate::model::ToolCall;

// What the model is told before the line, every time: what it is, that it
// gets the newest line and a record of what was said before it, that only
// the tool `forget` forgets that record, how to answer, and when to use the
// tools for apps. It names no project and no person. (A real model, asked to
// forget, once said in words that it had, and used no tool.)
pub const CHAT_INSTRUCTIONS: &str = concat!(
    "You are the voice of a small home-made operating system. ",
    "The person at the machine types one line at a time into its chat box. ",
    "You get the newest line, and below these instructions a record of the last lines before it and what came of them, if there were any. ",
    "If the person asks you to forget what was said or to start over, use forget: saying so in words forgets nothing. ",
    "Answer in plain words, in one or two short sentences, or use one of the tools when the person wants something done that a tool does. ",
    "Use run_app for a kept app that fits the wish, and make_app only when none fits."
);

// What stands between the instructions and the record of what was said
// before the line, when anything was (see `conversation.rs`). The record
// follows it, one row to a line, oldest first.
pub const RECORD_LEAD: &str = concat!(
    "\n\nWhat was said before the newest line, oldest first. ",
    "\"Person:\" is the person at the machine, \"Model:\" is you, and \"Kernel:\" is the operating system saying what happened.\n"
);

// What stands before the rows the newest line has brought so far, when the
// model is asked about that line again because what a tool did needs it
// (see `chat.rs`). It comes behind the instructions and the record of the
// lines before, if there were any. It says what the rows are, that the
// person has typed nothing since, and how an app can be fixed: the model
// that writes an app gets nothing but its request.
pub const AGAIN_LEAD: &str = concat!(
    "\n\nWhat came of the newest line so far, oldest first. ",
    "\"Model:\" is you, and \"Kernel:\" is the operating system saying what happened. ",
    "The person has typed nothing since. If what they wanted is done, say in plain words what came of it. ",
    "Use a tool again only if it is not done. A new app is written from its request alone, ",
    "so to fix an app, use make_app with a request that says what to do differently.\n"
);

// What ends the instruction text when the model is asked about a line for
// the last time. That ask goes without the list of tools, so that its answer
// is words.
pub const LAST_ASK: &str = "\n\nYou are asked about this line for the last time, and no tools are offered now: answer in plain words.";

// The tool that forgets what was said, so that the next line starts afresh.
// It needs no inputs. It is offered only while something is remembered.
const FORGET: &str = concat!(
    "{\"type\":\"function\",\"function\":{\"name\":\"forget\",",
    "\"description\":\"Forgets everything said before the newest line, so that the next line starts afresh. ",
    "Only this tool makes the system forget; saying so in words does not. ",
    "Use it whenever the person asks to forget what was said, to start over, or for a clean slate.\",",
    "\"parameters\":{\"type\":\"object\",\"properties\":{}}}}"
);

// The tool that has a new app written: the model gives a short request, and
// the kernel asks the model again, with the text about writing apps (see
// `app_make` in `apps.rs`).
const MAKE_APP: &str = concat!(
    "{\"type\":\"function\",\"function\":{\"name\":\"make_app\",",
    "\"description\":\"Has a new app written for the person and runs it; an app that runs to its end is kept. ",
    "Use it only when the person wants an app and no kept app fits.\",",
    "\"parameters\":{\"type\":\"object\",\"properties\":{\"request\":{\"type\":\"string\",",
    "\"description\":\"What the app does, in at most 45 signs, such as: a dice that rolls\"}},\"required\":[\"request\"]}}}"
);

// The tool that runs a kept app again, with the kept apps by number and
// request, the one kept last first.
fn run_app_tool(apps: &[(u32, String)]) -> String {
    let mut told = String::from("Runs one of the kept apps again, as it was written, without writing it anew. The kept apps, by number: ");
    let mut numbers = String::new();
    for (place, (number, request)) in apps.iter().enumerate() {
        if place > 0 {
            told.push_str("; ");
            numbers.push(',');
        }
        told.push_str(&format!("{}: {}", number, request));
        numbers.push_str(&format!("{}", number));
    }
    told.push('.');
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"run_app\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"app\":{{\"type\":\"integer\",\"enum\":[{}],\"description\":\"The number of the kept app\"}}}},\"required\":[\"app\"]}}}}}}",
        json_text(&told),
        numbers
    )
}

// The tool that picks one of the looks, which are listed in it.
fn pick_look_tool() -> String {
    let (looks, count) = looks_told();
    let mut numbers = String::new();
    for number in 1..=count {
        if number > 1 {
            numbers.push(',');
        }
        numbers.push_str(&format!("{}", number));
    }
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"pick_look\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"look\":{{\"type\":\"integer\",\"enum\":[{}],\"description\":\"The number of the look\"}}}},\"required\":[\"look\"]}}}}}}",
        json_text(&format!("Changes the colours of the whole screen to one of these looks, and keeps it for later starts: {}.", looks)),
        numbers
    )
}

// The tool that draws a table in the frame beside the panel of apps (see
// `drawing.rs`): how a table is written, with the room this screen has for
// one, and an example.
fn draw_table_tool(rows: usize, columns: usize, signs: u32) -> String {
    let told = format!(
        concat!(
            "Draws a table in a frame on the screen, beside the panel of apps, in place of the table shown before. ",
            "Use it when the person wants something shown as a table. ",
            "The table is written as lines, one thing to a line, each beginning with the word that says what it is: ",
            "title and the table's name; ",
            "colours and any of head, head-letters, rows, letters and lines (the head's background and letters, the rows' background and letters, and the lines between the cells), ",
            "each followed by its colour as # and six hex digits, picked to fit the wish; ",
            "widths and the number of signs each column needs; head and the head's cells; then row and a row's cells, one line for each row. ",
            "Cells are parted by |. Everything but the rows comes before the first row. ",
            "This screen has room for the head and {} rows, at most {} columns, and {} signs across all columns together; ",
            "longer cells are cut, and rows that do not fit are left out."
        ),
        rows, columns, signs
    );
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"draw_table\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"table\":{{\"type\":\"string\",\"description\":{}}}}},\"required\":[\"table\"]}}}}}}",
        json_text(&told),
        json_text(TABLE_EXAMPLE)
    )
}

// The example of a table that the tool `draw_table` gives the model.
const TABLE_EXAMPLE: &str = concat!(
    "The table, as lines, such as:\n",
    "title Fruit\n",
    "colours head #2e7d32 head-letters #ffffff\n",
    "widths 10 12\n",
    "head Fruit | Colour\n",
    "row Apple | red\n",
    "row Banana | yellow"
);

// The tool that fetches a file from the web and keeps it on the disk (see
// `files.rs` and `download.rs`). It is offered while files can be kept.
const DOWNLOAD_FILE: &str = concat!(
    "{\"type\":\"function\",\"function\":{\"name\":\"download_file\",",
    "\"description\":\"Fetches a file from the internet over an encrypted link and keeps it on the disk: ",
    "a PDF, a Word or Excel file (.docx, .xlsx), plain text or CSV, of at most 4 MB. ",
    "Use it when the person wants a file fetched or downloaded from an address, and give the address exactly as the person gave it. ",
    "The person is asked before a site is contacted for the first time.\",",
    "\"parameters\":{\"type\":\"object\",\"properties\":{\"address\":{\"type\":\"string\",",
    "\"description\":\"The file's address, beginning with https://\"}},\"required\":[\"address\"]}}}"
);

// The tool that removes a kept file, with the kept files by number, name,
// kind and size, the one kept last first. The person is asked first.
fn remove_file_tool(files: &[(u32, String)]) -> String {
    let mut told = String::from("Removes one of the kept files from the disk for good, once the person says yes. The kept files, by number: ");
    let mut numbers = String::new();
    for (place, (number, file)) in files.iter().enumerate() {
        if place > 0 {
            told.push_str("; ");
            numbers.push(',');
        }
        told.push_str(&format!("{}: {}", number, file));
        numbers.push_str(&format!("{}", number));
    }
    told.push('.');
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"remove_file\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"file\":{{\"type\":\"integer\",\"enum\":[{}],\"description\":\"The number of the kept file\"}}}},\"required\":[\"file\"]}}}}}}",
        json_text(&told),
        numbers
    )
}

// The tool that turns the page of the panel of apps.
fn turn_page_tool(pages: usize, shown: usize) -> String {
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"turn_page\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"page\":{{\"type\":\"integer\",\"description\":\"The number of the page, from 1 to {}\"}}}},\"required\":[\"page\"]}}}}}}",
        json_text(&format!(
            "Shows another page of the panel of kept apps near the top left of the screen. It has {} pages, the app kept last first, and shows page {} now.",
            pages, shown
        )),
        pages
    )
}

// The list of tools that goes to the model with a line, as JSON: `make_app`
// and `pick_look` always; `run_app` while any app is kept; `draw_table` while
// the screen has room for a table; `download_file` while files can be kept,
// and `remove_file` while any file is kept; `turn_page` while the panel of
// apps has more than one page; `forget` while anything that was said is
// remembered.
pub fn chat_tools() -> String {
    let mut tools = String::from("[");
    tools.push_str(MAKE_APP);
    let apps = apps_listed();
    if !apps.is_empty() {
        tools.push(',');
        tools.push_str(&run_app_tool(&apps));
    }
    tools.push(',');
    tools.push_str(&pick_look_tool());
    if let Some((rows, columns, signs)) = drawing_room() {
        tools.push(',');
        tools.push_str(&draw_table_tool(rows, columns, signs));
    }
    if files_usable() {
        tools.push(',');
        tools.push_str(DOWNLOAD_FILE);
        let files = files_listed();
        if !files.is_empty() {
            tools.push(',');
            tools.push_str(&remove_file_tool(&files));
        }
    }
    let (pages, shown) = apps_pages();
    if pages > 1 {
        tools.push(',');
        tools.push_str(&turn_page_tool(pages, shown));
    }
    if conversation_remembers() {
        tools.push(',');
        tools.push_str(FORGET);
    }
    tools.push(']');
    tools
}

// What came of a tool the model asked for, as far as the line it answers is
// concerned: whether it needs the model, which is then asked about the line
// again, with what came of it (see `chat.rs`). Each tool says which.
#[derive(Clone, Copy, PartialEq)]
pub enum ToolDone {
    // Done, and nothing in what came of it needs the model: the line ends.
    Ended,
    // What came of it goes back to the model: the kernel turned the request
    // down, a kept app was stopped, a table was not drawn whole, or a file
    // was not fetched or kept.
    Back,
    // A new app is being written, a file is being fetched, or the person is
    // asked first: what comes of it is known later, and the line waits for it
    // (see `chat_answer` and `chat_key` in `chat.rs`).
    Awaited,
}

// Does what the model asked for with a tool, says in the chat box how that
// went, and gives back whether what came of it goes back to the model. Only
// the names of the tools above count. What the model gave the tool is read
// with the JSON reader, which takes nothing on trust; a number may come
// written as a text of digits. Whatever the kernel turns down goes back.
pub fn tool_do(call: &ToolCall) -> ToolDone {
    let turned_down = match call.name.as_str() {
        "make_app" => match input_text(&call.inputs, "request") {
            Some(request) => match app_make(&request_cleaned(&request)) {
                Ok(said) => {
                    chat_say(&said);
                    return ToolDone::Awaited;
                }
                Err(said) => said,
            },
            None => String::from("the model asked for an app, but I could not read what the app should do."),
        },
        "run_app" => match input_number(&call.inputs, "app") {
            Some(number) => match app_kept(number) {
                Ok((request, script)) => {
                    chat_say(&format!("I am running the app made for \"{}\".", request));
                    let run = app_run(&script);
                    chat_say(&run.sentence);
                    // A kept app that ran to its end ends the line, as it
                    // did before; one that was stopped goes back, with what
                    // it left behind.
                    if run.ran {
                        return ToolDone::Ended;
                    }
                    for told in run.told.iter() {
                        chat_remember(told);
                    }
                    return ToolDone::Back;
                }
                Err(said) => said,
            },
            None => String::from("the model asked to run a kept app, but I could not read which one."),
        },
        "pick_look" => match input_number(&call.inputs, "look") {
            Some(number) => match look_pick(number) {
                Ok((said, changed)) => {
                    chat_say(&said);
                    if changed {
                        look_paint();
                    }
                    return ToolDone::Ended;
                }
                Err(said) => said,
            },
            None => String::from("the model asked for another look, but I could not read which one."),
        },
        "turn_page" => match input_number(&call.inputs, "page") {
            Some(page) => match apps_page_turn(page) {
                Ok(said) => {
                    chat_say(&said);
                    return ToolDone::Ended;
                }
                Err(said) => said,
            },
            None => String::from("the model asked for another page of the panel of apps, but I could not read which one."),
        },
        // A table drawn whole ends the line. One that was not, because rows
        // or columns did not fit or it was cut off, goes back, so that the
        // model can say so or draw a smaller one.
        "draw_table" => match drawing_table(&call.inputs, call.cut_off) {
            Ok((said, whole)) => {
                chat_say(&said);
                return if whole { ToolDone::Ended } else { ToolDone::Back };
            }
            Err(said) => said,
        },
        // A file from the web: `files.rs` says how it goes, and whether the
        // line waits for the fetch or for the person's answer.
        "download_file" => match input_text(&call.inputs, "address") {
            Some(address) => return download_start(&address),
            None => String::from("the model asked me to fetch a file, but I could not read its address."),
        },
        // A kept file removed, once the person says yes.
        "remove_file" => match input_number(&call.inputs, "file") {
            Some(number) => return remove_ask(number),
            None => String::from("the model asked to remove a kept file, but I could not read which one."),
        },
        // Everything said is forgotten first, the line that asked for it
        // too, so the row that says so is not remembered either, and nothing
        // of the line is left to go back.
        "forget" => {
            conversation_forget();
            chat_say("I forgot what was said so far. The next line starts afresh.");
            return ToolDone::Ended;
        }
        // The name was cleaned and cut by `model.rs`.
        other => format!("the model asked for something I cannot do: \"{}\".", other),
    };
    chat_say(&turned_down);
    ToolDone::Back
}

// What the model asks the kernel to do with a tool, written so that two
// requests for the same thing give the same text, however the inputs were
// written: the tool's name, and what it was given as the kernel reads it.
// No tool is done twice for one line (see `chat.rs`).
pub fn tool_wanted(call: &ToolCall) -> String {
    let given = match call.name.as_str() {
        "make_app" => input_text(&call.inputs, "request").map(|request| request_cleaned(&request)),
        "run_app" => input_number(&call.inputs, "app").map(|number| format!("{}", number)),
        "pick_look" => input_number(&call.inputs, "look").map(|number| format!("{}", number)),
        "turn_page" => input_number(&call.inputs, "page").map(|number| format!("{}", number)),
        "draw_table" => drawing_wanted(&call.inputs, call.cut_off),
        "download_file" => input_text(&call.inputs, "address").map(|address| String::from(address.trim())),
        "remove_file" => input_number(&call.inputs, "file").map(|number| format!("{}", number)),
        _ => None,
    };
    match given {
        Some(given) => format!("{}: {}", call.name, given),
        None => call.name.clone(),
    }
}

// The text that the model gave a tool under this name, if it gave one.
fn input_text(inputs: &str, name: &str) -> Option<String> {
    json_find_text(inputs.as_bytes(), &[Step::Name(name)]).ok()
}

// The whole number that the model gave a tool under this name, written as a
// number or as a text of digits alone, with spaces around them at most.
fn input_number(inputs: &str, name: &str) -> Option<u64> {
    if let Ok(number) = json_find_number(inputs.as_bytes(), &[Step::Name(name)]) {
        return Some(number);
    }
    let text = input_text(inputs, name)?;
    let digits = text.trim();
    if digits.is_empty() || !digits.bytes().all(|sign| sign.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

// A request that the model gave, made fit to be kept, shown and sent on: every
// byte that is not a plain sign becomes a dot, as in every text from outside,
// spaces at either end go, and no more than `REQUEST_MOST` signs are kept.
// The key was hidden in it already, with everything else the model's answer
// holds (see `model.rs`).
fn request_cleaned(request: &str) -> String {
    let plain: String = request.bytes().map(|byte| if (b' '..=b'~').contains(&byte) { byte as char } else { '.' }).collect();
    let kept: String = plain.trim().chars().take(REQUEST_MOST).collect();
    String::from(kept.trim_end())
}
