//! The locked box: runs an app so that it can touch nothing outside its own
//! memory, and the system API: the short list of things an app may ask the
//! kernel to do. An app is a WebAssembly program, and the outside library
//! wasmi carries it out one small step at a time. (The file is not called
//! `box.rs` because `box` is a word Rust keeps for itself.)
//! Notes: `docs/box.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;

use wasmi::{Caller, Config, Engine, Error, Extern, Instance, Linker, Module, Store, StoreLimits, StoreLimitsBuilder};

use crate::page::plain_text;
use crate::screen::screen_panel;
use crate::serial::serial_print;

// The most memory one app may have, in bytes. An app's memory comes in pieces
// of 64 KB (WebAssembly calls them pages), so this is 16 of them. Without a
// limit an app could ask for more than the machine has, and a request for
// memory that cannot be met stops the whole kernel.
const APP_MEMORY_LIMIT: usize = 1024 * 1024;

// The longest list of functions one app may keep (WebAssembly calls it a
// table). Each place costs the kernel a few bytes, so this needs a limit for
// the same reason as the memory.
const APP_TABLE_LIMIT: usize = 4096;

// The most work one run of an app may do. wasmi counts the app's steps in
// "fuel", roughly one unit per step. When the fuel is used up the app is
// stopped, so an app with a loop that never ends cannot hold the processor
// for good.
const APP_FUEL: u64 = 10_000_000;

// The most work one script may do. A script is not run by the box directly:
// a program in the box, the interpreter, carries it out, and that costs far
// more fuel than an app written by hand: five lines of script cost over four
// million units, and one round of a loop about 24 thousand. So a script gets
// ten times an app's budget. The number is a stopgap, set by measuring. Fuel
// counts steps, not time: this much is used up in under half a second by an
// empty loop and in about a second and a half by a script that joins texts
// without end. (When the number was chosen, the code that runs apps was
// built the slow way and those were two seconds and half a minute.) It also
// stops a harmless loop after about four thousand rounds.
const SCRIPT_FUEL: u64 = 100_000_000;

// The longest script the kernel hands over, in bytes. The script is copied
// into the program's memory, which is limited, so a script that could never
// fit is turned away before anything is started. A script the model writes
// is held to it as soon as it comes (see `apps.rs`).
pub const SCRIPT_LIMIT: usize = 32 * 1024;

// The longest text an app may hand to the kernel to print, in bytes, and the
// most texts it may print in one run. Printing costs the kernel time, and an
// app that printed without end would bury everything else on the screen.
const APP_TEXT_LIMIT: usize = 200;
const APP_PRINT_LIMIT: usize = 100;

// The longest text an app may ask to have shown on the screen, in bytes, and
// how often it may ask in one run. The text has to fit on one line of the
// box it is shown in. Every showing paints that whole box again, which costs
// the kernel time, so an app that showed without end has to be stopped too.
const APP_SHOWN_TEXT_LIMIT: usize = 40;
const APP_SHOW_LIMIT: usize = 20;

// The smallest app there is: one function, `add`, which takes two whole
// numbers and gives back their sum. No compiler made these bytes; they are
// written out by hand, in the form every WebAssembly program has: a heading,
// then numbered sections, each with its length in front.
pub const ADDING_APP: [u8; 41] = [
    // The heading: the four bytes "\0asm", then the version, 1.
    0x00, 0x61, 0x73, 0x6d,
    0x01, 0x00, 0x00, 0x00,
    // Section 1, the kinds of function. 7 bytes follow.
    0x01, 0x07,
    0x01, // One kind:
    0x60, // a function
    0x02, 0x7f, 0x7f, // that takes two values, both whole numbers of 32 bits (0x7f),
    0x01, 0x7f, // and gives back one, a whole number of 32 bits.
    // Section 3, the functions. 2 bytes follow.
    0x03, 0x02,
    0x01, // One function,
    0x00, // of kind 0, the one above.
    // Section 7, what the app shows to the outside. 7 bytes follow.
    0x07, 0x07,
    0x01, // One thing:
    0x03, 0x61, 0x64, 0x64, // its name has 3 letters, "add";
    0x00, 0x00, // it is a function, and it is function 0.
    // Section 10, the code. 9 bytes follow.
    0x0a, 0x09,
    0x01, // The code of one function,
    0x07, // 7 bytes long.
    0x00, // It has no variables of its own.
    0x20, 0x00, // Take the first value handed in.
    0x20, 0x01, // Take the second.
    0x6a, // Add the two.
    0x0b, // The end. What is left over, the sum, is the answer.
];

// An app that says hello. It keeps a text in its memory and asks the kernel
// to print it. Written out by hand like the one above, with three sections
// more: what it asks of the kernel, its memory, and what the memory holds at
// the start.
pub const GREETING_APP: [u8; 111] = [
    // The heading: "\0asm", version 1.
    0x00, 0x61, 0x73, 0x6d,
    0x01, 0x00, 0x00, 0x00,
    // Section 1, the kinds of function. 9 bytes follow.
    0x01, 0x09,
    0x02, // Two kinds.
    0x60, 0x02, 0x7f, 0x7f, 0x00, // Kind 0: takes two whole numbers, gives back nothing.
    0x60, 0x00, 0x00, // Kind 1: takes nothing, gives back nothing.
    // Section 2, what the app asks of the kernel. 16 bytes follow.
    0x02, 0x10,
    0x01, // One thing:
    0x06, 0x6b, 0x65, 0x72, 0x6e, 0x65, 0x6c, // from the one called "kernel" (6 letters),
    0x05, 0x70, 0x72, 0x69, 0x6e, 0x74, // the thing called "print" (5 letters),
    0x00, 0x00, // which is a function of kind 0. It becomes function 0.
    // Section 3, the app's own functions. 2 bytes follow.
    0x03, 0x02,
    0x01, // One function,
    0x01, // of kind 1. It becomes function 1.
    // Section 5, the memory. 3 bytes follow.
    0x05, 0x03,
    0x01, // One memory.
    0x00, 0x01, // "No upper limit named", and it starts with 1 page (64 KB).
    // Section 7, what the app shows to the outside. 18 bytes follow.
    0x07, 0x12,
    0x02, // Two things.
    0x06, 0x6d, 0x65, 0x6d, 0x6f, 0x72, 0x79, // "memory" (6 letters):
    0x02, 0x00, // it is a memory, memory 0. The kernel reads the text from it.
    0x05, 0x73, 0x74, 0x61, 0x72, 0x74, // "start" (5 letters):
    0x00, 0x01, // it is a function, function 1. The kernel calls it to run the app.
    // Section 10, the code. 10 bytes follow.
    0x0a, 0x0a,
    0x01, // The code of one function,
    0x08, // 8 bytes long.
    0x00, // It has no variables of its own.
    0x41, 0x00, // The number 0: where the text begins in the app's memory.
    0x41, 0x19, // The number 25: how many bytes long the text is.
    0x10, 0x00, // Call function 0 with those two: the kernel's print.
    0x0b, // The end.
    // Section 11, what the memory holds at the start. 31 bytes follow.
    0x0b, 0x1f,
    0x01, // One piece:
    0x00, // it goes into memory 0,
    0x41, 0x00, 0x0b, // at the address 0,
    0x19, // and is 25 bytes long: "Hello from inside the box".
    0x48, 0x65, 0x6c, 0x6c, 0x6f, 0x20, // "Hello "
    0x66, 0x72, 0x6f, 0x6d, 0x20, // "from "
    0x69, 0x6e, 0x73, 0x69, 0x64, 0x65, 0x20, // "inside "
    0x74, 0x68, 0x65, 0x20, // "the "
    0x62, 0x6f, 0x78, // "box"
];

// The same app again, with two things changed: it asks the kernel for `show`
// instead of `print`, and its text is another one. The kernel shows the text
// on the screen, in a box.
pub const SHOWING_APP: [u8; 113] = [
    // The heading: "\0asm", version 1.
    0x00, 0x61, 0x73, 0x6d,
    0x01, 0x00, 0x00, 0x00,
    // Section 1, the kinds of function. 9 bytes follow.
    0x01, 0x09,
    0x02, // Two kinds.
    0x60, 0x02, 0x7f, 0x7f, 0x00, // Kind 0: takes two whole numbers, gives back nothing.
    0x60, 0x00, 0x00, // Kind 1: takes nothing, gives back nothing.
    // Section 2, what the app asks of the kernel. 15 bytes follow.
    0x02, 0x0f,
    0x01, // One thing:
    0x06, 0x6b, 0x65, 0x72, 0x6e, 0x65, 0x6c, // from the one called "kernel" (6 letters),
    0x04, 0x73, 0x68, 0x6f, 0x77, // the thing called "show" (4 letters),
    0x00, 0x00, // which is a function of kind 0. It becomes function 0.
    // Section 3, the app's own functions. 2 bytes follow.
    0x03, 0x02,
    0x01, // One function,
    0x01, // of kind 1. It becomes function 1.
    // Section 5, the memory. 3 bytes follow.
    0x05, 0x03,
    0x01, // One memory.
    0x00, 0x01, // "No upper limit named", and it starts with 1 page (64 KB).
    // Section 7, what the app shows to the outside. 18 bytes follow.
    0x07, 0x12,
    0x02, // Two things.
    0x06, 0x6d, 0x65, 0x6d, 0x6f, 0x72, 0x79, // "memory" (6 letters):
    0x02, 0x00, // it is a memory, memory 0. The kernel reads the text from it.
    0x05, 0x73, 0x74, 0x61, 0x72, 0x74, // "start" (5 letters):
    0x00, 0x01, // it is a function, function 1. The kernel calls it to run the app.
    // Section 10, the code. 10 bytes follow.
    0x0a, 0x0a,
    0x01, // The code of one function,
    0x08, // 8 bytes long.
    0x00, // It has no variables of its own.
    0x41, 0x00, // The number 0: where the text begins in the app's memory.
    0x41, 0x1c, // The number 28: how many bytes long the text is.
    0x10, 0x00, // Call function 0 with those two: the kernel's show.
    0x0b, // The end.
    // Section 11, what the memory holds at the start. 34 bytes follow.
    0x0b, 0x22,
    0x01, // One piece:
    0x00, // it goes into memory 0,
    0x41, 0x00, 0x0b, // at the address 0,
    0x1c, // and is 28 bytes long: "Hello from an app in the box".
    0x48, 0x65, 0x6c, 0x6c, 0x6f, 0x20, // "Hello "
    0x66, 0x72, 0x6f, 0x6d, 0x20, // "from "
    0x61, 0x6e, 0x20, // "an "
    0x61, 0x70, 0x70, 0x20, // "app "
    0x69, 0x6e, 0x20, // "in "
    0x74, 0x68, 0x65, 0x20, // "the "
    0x62, 0x6f, 0x78, // "box"
];

// What the kernel keeps for an app while it runs: the limits it holds the app
// to, and how many texts the app has printed and shown so far.
struct AppState {
    limits: StoreLimits,
    texts_printed: usize,
    texts_shown: usize,
}

// Fetches a text that an app handed over, for the two calls below. The app
// says where the text begins in its own memory and how many bytes long it
// is; `limit` is the longest it may be, and `doing` is the word for what the
// app asked for, "print" or "show", used in the reasons.
//
// The text comes from outside the kernel, so nothing about it is taken on
// trust. A text that is too long, or that does not lie wholly inside the
// app's memory, is not handed on, and the app is stopped with the reason.
// Only plain letters, digits and signs are kept; every other byte becomes a
// dot, so an app cannot send commands to the terminal or begin a line of its
// own that looks like the kernel's.
fn app_text(caller: &Caller<'_, AppState>, start: i32, length: i32, limit: usize, doing: &str) -> Result<String, Error> {
    if length < 0 || length as usize > limit {
        return Err(Error::new(format!("it asked to {} a text that is too long", doing)));
    }

    // The app's memory, found under the name the app shows it by.
    let memory = caller
        .get_export("memory")
        .and_then(Extern::into_memory)
        .ok_or_else(|| Error::new(format!("it asked to {}, but shows no memory called `memory`", doing)))?;

    // Copy the text out of the app's memory. `read` refuses if any part of
    // it lies outside. A start below zero becomes a very large address here,
    // which is outside too.
    let mut bytes = vec![0u8; length as usize];
    memory
        .read(caller, start as u32 as usize, &mut bytes)
        .map_err(|_| Error::new(format!("it asked to {} a text that lies outside its memory", doing)))?;

    // Clean the text.
    let mut text = String::new();
    for &byte in bytes.iter() {
        text.push(if (b' '..=b'~').contains(&byte) { byte as char } else { '.' });
    }
    Ok(text)
}

// The system API's first call. An app reaches it as `print` of `kernel`, and
// hands over two whole numbers: where a text begins in its own memory, and
// how many bytes long the text is. The kernel prints that text as one line
// with "App: " in front, in one go.
fn kernel_print(mut caller: Caller<'_, AppState>, start: i32, length: i32) -> Result<(), Error> {
    if caller.data().texts_printed >= APP_PRINT_LIMIT {
        return Err(Error::new("it printed too many texts"));
    }
    let text = app_text(&caller, start, length, APP_TEXT_LIMIT, "print")?;
    serial_print(&format!("App: {}\r\n", text));
    caller.data_mut().texts_printed += 1;
    Ok(())
}

// The second call. An app reaches it as `show` of `kernel` and hands over a
// text in the same way. The kernel shows the text on the screen, in a box.
// The app says only what it wants shown. How the box looks and where it sits
// is the kernel's business: see `screen_panel`. On a machine without a
// usable screen nothing is shown, and the app carries on all the same.
fn kernel_show(mut caller: Caller<'_, AppState>, start: i32, length: i32) -> Result<(), Error> {
    if caller.data().texts_shown >= APP_SHOW_LIMIT {
        return Err(Error::new("it showed too many texts"));
    }
    let text = app_text(&caller, start, length, APP_SHOWN_TEXT_LIMIT, "show")?;
    screen_panel(&text);
    caller.data_mut().texts_shown += 1;
    Ok(())
}

// Gets an app ready to run: checks its program, sets its limits, offers it
// the system API and starts it. Gives back the two things a call into the
// app needs: the store, which holds everything that belongs to the running
// app, and the app itself.
fn box_start(program: &[u8]) -> Result<(Store<AppState>, Instance), String> {
    // The engine does the work of running apps. Each run gets an engine of
    // its own, which goes away with the store at the end: an engine keeps
    // every program it has translated for as long as it lives.
    let mut settings = Config::default();
    settings.consume_fuel(true); // "Count the app's steps."
    let engine = Engine::new(&settings);

    // Check the program against WebAssembly's rules and translate it into the
    // engine's own steps. A program that breaks a rule is refused here,
    // before any of it has run.
    let module = Module::new(&engine, program).map_err(reason)?;

    // The store, with the limits the app is held to: one memory of at most
    // `APP_MEMORY_LIMIT` bytes and one table of at most `APP_TABLE_LIMIT`
    // places.
    let limits = StoreLimitsBuilder::new()
        .memory_size(APP_MEMORY_LIMIT)
        .memories(1)
        .table_elements(APP_TABLE_LIMIT)
        .tables(1)
        .instances(1)
        .build();
    let mut store = Store::new(&engine, AppState { limits, texts_printed: 0, texts_shown: 0 });
    store.limiter(|state| &mut state.limits);
    store.set_fuel(APP_FUEL).map_err(reason)?;

    // The linker holds the system API: what an app may ask the kernel for.
    // That is two things so far. An app that asks for anything else, or for
    // one of the two in another shape, is not started.
    let mut linker = <Linker<AppState>>::new(&engine);
    linker.func_wrap("kernel", "print", kernel_print).map_err(|problem| reason(Error::from(problem)))?;
    linker.func_wrap("kernel", "show", kernel_show).map_err(|problem| reason(Error::from(problem)))?;

    let app = linker.instantiate_and_start(&mut store, &module).map_err(reason)?;
    Ok((store, app))
}

// Runs an app in the box: gets it ready and calls its function `start`,
// which takes nothing and gives back nothing. Whatever goes wrong comes back
// as a reason in words: a program that breaks WebAssembly's rules, an app
// that asks for something the kernel does not offer, an app without a
// `start`, or an app that is stopped while it runs.
pub fn box_run(program: &[u8]) -> Result<(), String> {
    let (mut store, app) = box_start(program)?;
    let start = app.get_typed_func::<(), ()>(&store, "start").map_err(reason)?;
    start.call(&mut store, ()).map_err(reason)
}

// Asks whether the box would take a program that is not an app with a
// `start`, without running any of it: gets the program ready as for a run,
// with the same check and the same limits, and then looks whether it shows
// the outside a memory called `memory` and a function under each of the
// names in `functions`. The interpreter is such a program: it is not run
// once from a `start`, but handed a script and told to carry it out.
pub fn box_accepts(program: &[u8], functions: &[&str]) -> Result<(), String> {
    let (store, app) = box_start(program)?;
    if app.get_memory(&store, "memory").is_none() {
        return Err(String::from("it shows no memory called `memory`"));
    }
    for name in functions {
        if app.get_func(&store, name).is_none() {
            return Err(format!("it shows no function called `{}`", name));
        }
    }
    Ok(())
}

// Hands a script to a program in the box that can carry scripts out, and has
// it carried out. Such a program, the interpreter, is not run once from a
// `start`. It shows the outside two functions instead:
//
// - `room`, which takes the script's length in bytes and gives back where in
//   the program's own memory the kernel should write the script;
// - `run`, which takes the length again, carries the script out, and gives
//   back 0 if the script ran to its end.
//
// The program is got ready exactly as an app is, with the same check, the
// same limits and the same system API. Nothing it says is taken on trust:
// the place it names for the script is written to through `write`, which
// refuses if any byte of it lies outside the program's memory.
pub fn box_script(program: &[u8], script: &str) -> Result<(), String> {
    if script.len() > SCRIPT_LIMIT {
        return Err(String::from("the script is too long"));
    }
    let length = script.len() as i32;

    let (mut store, app) = box_start(program)?;
    let room = app.get_typed_func::<i32, i32>(&store, "room").map_err(reason)?;
    let run = app.get_typed_func::<i32, i32>(&store, "run").map_err(reason)?;
    let memory = app.get_memory(&store, "memory").ok_or_else(|| String::from("it shows no memory called `memory`"))?;

    // From here on the program's own code runs, on the budget for a script.
    store.set_fuel(SCRIPT_FUEL).map_err(reason)?;
    let place = room.call(&mut store, length).map_err(reason)?;
    memory
        .write(&mut store, place as u32 as usize, script.as_bytes())
        .map_err(|_| String::from("it gave room for the script outside its own memory"))?;
    match run.call(&mut store, length).map_err(reason)? {
        0 => Ok(()),
        _ => Err(String::from("the script made a mistake, which is told in the line before")),
    }
}

// wasmi's own words for what went wrong, or the kernel's from `kernel_print`.
// wasmi's can hold names taken from the program, which is text from outside,
// so they are cleaned before they are shown and cut at 120 signs.
fn reason(error: Error) -> String {
    plain_text(&format!("{}", error), 120)
}

// The check at startup that the box works at all: run the smallest app and
// see what 2 + 3 comes to.
pub fn box_check() -> Result<i32, String> {
    let (mut store, app) = box_start(&ADDING_APP)?;
    let add = app.get_typed_func::<(i32, i32), i32>(&store, "add").map_err(reason)?;
    add.call(&mut store, (2, 3)).map_err(reason)
}
