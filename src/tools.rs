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
use alloc::vec::Vec;

use crate::app_inputs::{Input, inputs_listed, inputs_read, inputs_wanted, values_read, values_said, values_wanted};
use crate::apps::{app_make, app_run};
use crate::apps_kept::{REQUEST_MOST, app_kept, apps_listed, apps_page_turn, apps_pages};
use crate::chat::{chat_remember, chat_say};
use crate::conversation::{conversation_forget, conversation_remembers};
use crate::documents::{document_draw, document_open, document_reopen, documents_listed, documents_usable, documents_wanted};
use crate::drawing::{drawing_room, drawing_table, drawing_wanted};
use crate::files::{download_start, file_open_start, files_listed, files_openable, files_usable, remove_ask};
use crate::json::{Step, json_find_number, json_find_text, json_text};
use crate::look::{look_paint, look_pick, looks_told};
use crate::model::ToolCall;

// What the model is told before the line, every time: what it is, that it
// gets the newest line and a record of what was said before it, that only
// the tool `forget` forgets that record, how to answer, when to use the tools
// for apps, and what to do about an app's inputs. It names no project and no
// person. (A real model, asked to forget, once said in words that it had, and
// used no tool.)
pub const CHAT_INSTRUCTIONS: &str = concat!(
    "You are the voice of a small home-made operating system. ",
    "The person at the machine types one line at a time into its chat box. ",
    "You get the newest line, and below these instructions a record of the last lines before it and what came of them, if there were any. ",
    "If the person asks you to forget what was said or to start over, use forget: saying so in words forgets nothing. ",
    "Answer in plain words, in one or two short sentences, or use one of the tools when the person wants something done that a tool does. ",
    "Use run_app for a kept app that fits the wish, and make_app only when none fits. ",
    "An app can take inputs, such as a distance to convert: give them to make_app as its inputs, each with its value, never in its request; ",
    "for a kept app that fits the wish, use run_app with the new values. ",
    "If the person has not said a value an app needs and there is no obvious one, ask them for it in plain words."
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
// that writes an app gets nothing but its request and its inputs.
pub const AGAIN_LEAD: &str = concat!(
    "\n\nWhat came of the newest line so far, oldest first. ",
    "\"Model:\" is you, and \"Kernel:\" is the operating system saying what happened. ",
    "The person has typed nothing since. If what they wanted is done, say in plain words what came of it. ",
    "Use a tool again only if it is not done. A new app is written from its request and its inputs alone, ",
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

// The tool that has a new app written: the model gives a short request and
// the app's inputs, each with its value for this run, and the kernel asks the
// model again, with the text about writing apps (see `app_make` in
// `apps.rs`). The inputs are a text, one line for each, at most four, parted
// by `|`: the shape the real model fills well for a table. They are required,
// an empty text for an app without inputs: the real model left them out in
// three runs while they were not, as a list of sets of named things and as a
// text, and has filled every input it was required to. The kernel still takes
// a call without them as an app without inputs. An input without a value is
// turned down, see `app_inputs.rs`.
const MAKE_APP: &str = concat!(
    "{\"type\":\"function\",\"function\":{\"name\":\"make_app\",",
    "\"description\":\"Has a new app written for the person and runs it; an app that runs to its end is kept. ",
    "Use it only when the person wants an app and no kept app fits. ",
    "Give the app inputs for what a wish may change, such as a distance to convert, each with its value for this run.\",",
    "\"parameters\":{\"type\":\"object\",\"properties\":{\"request\":{\"type\":\"string\",",
    "\"description\":\"What the app does in general, without its inputs or this run's values, in at most 45 signs, such as: converts km to miles\"},",
    "\"inputs\":{\"type\":\"string\",\"description\":\"The inputs the app takes at every run, at most 4, one line each: ",
    "name | kind | what it is | its value for this run. A name has letters, digits or _ and begins with a letter; ",
    "a kind is number, text or yes/no. Such as: km | number | the distance in kilometres | 5. ",
    "Empty for an app that takes none.\"}},",
    "\"required\":[\"request\",\"inputs\"]}}}"
);

// The tool that runs a kept app again, with the kept apps by number and
// request, the one kept last first, and the inputs of each that has any.
// While any of them has inputs, the tool also takes their values, as a text
// with one line for each, `name | value`, required, as the inputs of
// `make_app` are; otherwise it is the same as before inputs existed.
fn run_app_tool(apps: &[(u32, String, Vec<Input>)]) -> String {
    let with_inputs = apps.iter().any(|(_, _, inputs)| !inputs.is_empty());
    let mut told = String::from("Runs one of the kept apps again, as it was written, without writing it anew");
    told.push_str(if with_inputs { ", with a value for each of its inputs. The kept apps, by number: " } else { ". The kept apps, by number: " });
    let mut numbers = String::new();
    for (place, (number, request, inputs)) in apps.iter().enumerate() {
        if place > 0 {
            told.push_str("; ");
            numbers.push(',');
        }
        told.push_str(&format!("{}: {}{}", number, request, inputs_listed(inputs)));
        numbers.push_str(&format!("{}", number));
    }
    told.push('.');
    let (values, required) = if with_inputs {
        (
            ",\"values\":{\"type\":\"string\",\"description\":\"A value for each input of the app, one line each: name | value, such as: km | 12. Empty for an app that takes none.\"}",
            "\"app\",\"values\"",
        )
    } else {
        ("", "\"app\"")
    };
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"run_app\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"app\":{{\"type\":\"integer\",\"enum\":[{}],\"description\":\"The number of the kept app\"}}{}}},\"required\":[{}]}}}}}}",
        json_text(&told),
        numbers,
        values,
        required
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
// one, and an example. Where documents can be kept (see `documents.rs`), it
// also says that every table is kept as a document, and how a table says
// which document it changes, and the example begins with that line.
fn draw_table_tool(rows: usize, columns: usize, signs: u32, documents: bool) -> String {
    let mut told = format!(
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
    let example = if documents {
        told.push_str(DOCUMENTS_TOLD);
        format!("{}document 0\n{}", TABLE_EXAMPLE_LEAD, TABLE_EXAMPLE)
    } else {
        format!("{}{}", TABLE_EXAMPLE_LEAD, TABLE_EXAMPLE)
    };
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"draw_table\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"table\":{{\"type\":\"string\",\"description\":{}}}}},\"required\":[\"table\"]}}}}}}",
        json_text(&told),
        json_text(&example)
    )
}

// What the tool `draw_table` says where documents can be kept: that every
// table is kept as a document, named by its title, and which first line a
// new table and a changed one begin with.
const DOCUMENTS_TOLD: &str = concat!(
    " Every table is kept on the disk as a document, named by its title. ",
    "Begin a new table with the line document 0; to change a kept document, write its whole table again, ",
    "beginning with document and its number."
);

// The example of a table that the tool `draw_table` gives the model, after
// its first words; where documents can be kept, the line `document 0` comes
// in front of it.
const TABLE_EXAMPLE_LEAD: &str = "The table, as lines, such as:\n";
const TABLE_EXAMPLE: &str = concat!(
    "title Fruit\n",
    "colours head #2e7d32 head-letters #ffffff\n",
    "widths 10 12\n",
    "head Fruit | Colour\n",
    "row Apple | red\n",
    "row Banana | yellow"
);

// The tool that opens a kept document in the frame (see `documents.rs`), with
// the kept documents by number and name, the one used last first. It is
// offered while any document is kept where documents can be kept.
fn open_document_tool(documents: &[(u32, String)]) -> String {
    let mut told = String::from(concat!(
        "Opens one of the kept documents in the frame on the screen, in place of what it shows; ",
        "its lines then go with every line, so that it can be changed. The kept documents, by number: "
    ));
    let mut numbers = String::new();
    for (place, (number, name)) in documents.iter().enumerate() {
        if place > 0 {
            told.push_str("; ");
            numbers.push(',');
        }
        told.push_str(&format!("{}: {}", number, name));
        numbers.push_str(&format!("{}", number));
    }
    told.push('.');
    format!(
        "{{\"type\":\"function\",\"function\":{{\"name\":\"open_document\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"document\":{{\"type\":\"integer\",\"enum\":[{}],\"description\":\"The number of the kept document\"}}}},\"required\":[\"document\"]}}}}}}",
        json_text(&told),
        numbers
    )
}

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

// The tool that opens a kept CSV file as a document: the kernel reads the
// file and sends its text to the model once, with the next ask about the line,
// and the model draws it as a table, which is kept as a document (see
// `files.rs` and `documents.rs`). It lists the files that can be opened, by
// number, name, kind and size, the one kept last first.
fn open_file_tool(files: &[(u32, String)]) -> String {
    let mut told = String::from(concat!(
        "Opens one of the kept CSV files as a table: its text, at most its first 64 KB, is sent to you once, with the next ask, ",
        "and you then draw it with draw_table as a new table, which is kept as a document; ",
        "a file opened before opens its table again. The kept CSV files, by number: "
    ));
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
        "{{\"type\":\"function\",\"function\":{{\"name\":\"open_file\",\"description\":{},\"parameters\":{{\"type\":\"object\",\"properties\":{{\"file\":{{\"type\":\"integer\",\"enum\":[{}],\"description\":\"The number of the kept file\"}}}},\"required\":[\"file\"]}}}}}}",
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
// the screen has room for a table, and `open_document` while any document is
// kept; `download_file` while files can be kept, `remove_file` while any
// file is kept, and `open_file` while a CSV file is kept where documents can
// be kept; `turn_page` while the panel of apps has more than one page;
// `forget` while anything that was said is remembered.
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
        tools.push_str(&draw_table_tool(rows, columns, signs, documents_usable()));
        let documents = documents_listed();
        if !documents.is_empty() {
            tools.push(',');
            tools.push_str(&open_document_tool(&documents));
        }
    }
    if files_usable() {
        tools.push(',');
        tools.push_str(DOWNLOAD_FILE);
        let files = files_listed();
        if !files.is_empty() {
            tools.push(',');
            tools.push_str(&remove_file_tool(&files));
        }
        let openable = if documents_usable() { files_openable() } else { Vec::new() };
        if !openable.is_empty() {
            tools.push(',');
            tools.push_str(&open_file_tool(&openable));
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
        // The app's inputs and their values are read and checked before the
        // model is asked to write it (see `app_inputs.rs`).
        "make_app" => match input_text(&call.inputs, "request") {
            Some(request) => match inputs_read(&call.inputs) {
                Ok((inputs, values)) => match app_make(&request_cleaned(&request), inputs, values) {
                    Ok(said) => {
                        chat_say(&said);
                        return ToolDone::Awaited;
                    }
                    Err(said) => said,
                },
                Err(said) => said,
            },
            None => String::from("the model asked for an app, but I could not read what the app should do."),
        },
        // The values are checked against the inputs kept with the app.
        "run_app" => match input_number(&call.inputs, "app") {
            Some(number) => match app_kept(number) {
                Ok((request, inputs, script)) => match values_read(&call.inputs, &inputs, &request) {
                    Ok(values) => {
                        chat_say(&format!("I am running the app made for \"{}\"{}.", request, values_said(&values)));
                        let run = app_run(&script, &values);
                        chat_say(&run.sentence);
                        // A kept app that ran to its end ends the line, as it
                        // did before; one that was stopped goes back, with
                        // what it left behind.
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
        // model can say so or draw a smaller one. Where documents can be
        // kept, the table is kept as one, or changes the open one (see
        // `documents.rs`).
        "draw_table" => match if documents_usable() { document_draw(&call.inputs, call.cut_off) } else { drawing_table(&call.inputs, call.cut_off) } {
            Ok((said, whole)) => {
                chat_say(&said);
                return if whole { ToolDone::Ended } else { ToolDone::Back };
            }
            Err(said) => said,
        },
        // A kept document opened goes back, so that the model, which sees its
        // lines with the next ask, can change it in the same line, or say
        // what it opened.
        "open_document" => match input_number(&call.inputs, "document") {
            Some(number) => match document_open(number) {
                Ok(said) => {
                    chat_say(&said);
                    return ToolDone::Back;
                }
                Err(said) => said,
            },
            None => String::from("the model asked to open a kept document, but I could not read which one."),
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
        // A kept CSV file opened as a document: read on the machine, its text
        // kept for the next ask about the line, which carries it to the model
        // once, so that the model can draw it as a table (see `files.rs`).
        // A file that a document was made from before opens that document
        // instead, and its text is not sent again (see `documents.rs`).
        // Either way it goes back, so the ask follows at once.
        "open_file" => match input_number(&call.inputs, "file") {
            Some(number) if !documents_usable() => format!("the model asked to open file {}, but documents cannot be kept here.", number),
            Some(number) => {
                let kept = files_openable().iter().any(|(file, _)| u64::from(*file) == number);
                let reopened = if kept { u32::try_from(number).ok().and_then(document_reopen) } else { None };
                match reopened.unwrap_or_else(|| file_open_start(number)) {
                    Ok(said) => {
                        chat_say(&said);
                        return ToolDone::Back;
                    }
                    Err(said) => said,
                }
            }
            None => String::from("the model asked to open a kept file, but I could not read which one."),
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
// written: the tool's name, and what it was given as the kernel reads it; for
// an app, its inputs and values too, so that a request turned down for them
// and given again with others is done. No tool is done twice for one line
// (see `chat.rs`).
pub fn tool_wanted(call: &ToolCall) -> String {
    let given = match call.name.as_str() {
        "make_app" => input_text(&call.inputs, "request").map(|request| format!("{}{}", request_cleaned(&request), inputs_wanted(&call.inputs))),
        "run_app" => input_number(&call.inputs, "app").map(|number| format!("{}{}", number, values_wanted(&call.inputs))),
        "pick_look" => input_number(&call.inputs, "look").map(|number| format!("{}", number)),
        "turn_page" => input_number(&call.inputs, "page").map(|number| format!("{}", number)),
        "draw_table" => drawing_wanted(&call.inputs, call.cut_off),
        "open_document" => input_number(&call.inputs, "document").map(|number| format!("{}", number)),
        "download_file" => input_text(&call.inputs, "address").map(|address| String::from(address.trim())),
        "remove_file" => input_number(&call.inputs, "file").map(|number| format!("{}", number)),
        "open_file" => input_number(&call.inputs, "file").map(|number| format!("{}", number)),
        _ => None,
    };
    // A change of a kept document counts as the same thing again only while
    // the same document is open (see `documents.rs`).
    let given = if call.name == "draw_table" { given.map(documents_wanted) } else { given };
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
