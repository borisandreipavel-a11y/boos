//! The tools: what the kernel can do when the model asks for it. Every line
//! typed in the chat box goes to the model (see `chat.rs` and `model.rs`), and
//! with it goes a list of tools, each with a name, one sentence and what it
//! needs to be told (`chat_tools`), and what was said before it (see
//! `conversation.rs`). The model answers in words, or asks for one of the
//! tools; the kernel then does it and says in one plain sentence how that
//! went (`tool_do`). What the model asks for comes from outside the kernel,
//! and is checked before anything is done. Only the main loop may call these
//! functions.
//! Notes: `docs/tools.md`.

use alloc::format;
use alloc::string::String;

use crate::apps::{app_make, app_run};
use crate::apps_kept::{REQUEST_MOST, app_kept, apps_listed, apps_page_turn, apps_pages};
use crate::chat::chat_say;
use crate::conversation::{conversation_forget, conversation_remembers};
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
// and `pick_look` always; `run_app` while any app is kept; `turn_page` while
// the panel of apps has more than one page; `forget` while anything that was
// said is remembered.
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

// Does what the model asked for with a tool, and says in the chat box how
// that went. Only the names of the tools above count. What the model gave the
// tool is read with the JSON reader, which takes nothing on trust; a number
// may come written as a text of digits.
pub fn tool_do(call: &ToolCall) {
    match call.name.as_str() {
        "make_app" => match input_text(&call.inputs, "request") {
            Some(request) => chat_say(&app_make(&request_cleaned(&request))),
            None => chat_say("the model asked for an app, but I could not read what the app should do."),
        },
        "run_app" => match input_number(&call.inputs, "app") {
            Some(number) => match app_kept(number) {
                Ok((request, script)) => {
                    chat_say(&format!("I am running the app made for \"{}\".", request));
                    let (sentence, _) = app_run(&script);
                    chat_say(&sentence);
                }
                Err(sentence) => chat_say(&sentence),
            },
            None => chat_say("the model asked to run a kept app, but I could not read which one."),
        },
        "pick_look" => match input_number(&call.inputs, "look") {
            Some(number) => {
                let (said, changed) = look_pick(number);
                chat_say(&said);
                if changed {
                    look_paint();
                }
            }
            None => chat_say("the model asked for another look, but I could not read which one."),
        },
        "turn_page" => match input_number(&call.inputs, "page") {
            Some(page) => chat_say(&apps_page_turn(page)),
            None => chat_say("the model asked for another page of the panel of apps, but I could not read which one."),
        },
        // Everything said is forgotten first, the line that asked for it
        // too, so the row that says so is not remembered either.
        "forget" => {
            conversation_forget();
            chat_say("I forgot what was said so far. The next line starts afresh.");
        }
        // The name was cleaned and cut by `model.rs`.
        other => chat_say(&format!("the model asked for something I cannot do: \"{}\".", other)),
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
