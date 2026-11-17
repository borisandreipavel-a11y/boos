//! The locked box: runs an app so that it can touch nothing outside its own
//! memory, and the system API: the short list of things an app may ask the
//! kernel to do. An app is a WebAssembly program, and the outside library
//! wasmi carries it out one small step at a time. (The file is not called
//! `box.rs` because `box` is a word Rust keeps for itself.)
//! Notes: `docs/box.md`.

use alloc::format;
use alloc::string::String;

use wasmi::{Caller, Config, Engine, Error, Extern, Instance, Linker, Module, Store, StoreLimits, StoreLimitsBuilder};

use crate::page::plain_text;
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

// The longest text an app may hand to the kernel to print, in bytes, and the
// most texts it may print in one run. Printing costs the kernel time, and an
// app that printed without end would bury everything else on the screen.
const APP_TEXT_LIMIT: usize = 200;
const APP_PRINT_LIMIT: usize = 100;

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

// What the kernel keeps for an app while it runs: the limits it holds the app
// to, and how many texts the app has printed so far.
struct AppState {
    limits: StoreLimits,
    texts_printed: usize,
}

// The system API's first call. An app reaches it as `print` of `kernel`, and
// hands over two whole numbers: where a text begins in its own memory, and
// how many bytes long the text is. The kernel prints that text as one line
// with "App: " in front.
//
// The text comes from outside the kernel, so nothing about it is taken on
// trust. A text that is too long, or that does not lie wholly inside the
// app's memory, is not printed, and the app is stopped with the reason.
// Only plain letters, digits and signs are printed; everything else becomes
// a dot, so an app cannot send commands to the terminal or begin a line of
// its own that looks like the kernel's.
fn kernel_print(mut caller: Caller<'_, AppState>, start: i32, length: i32) -> Result<(), Error> {
    if caller.data().texts_printed >= APP_PRINT_LIMIT {
        return Err(Error::new("it printed too many texts"));
    }
    if length < 0 || length as usize > APP_TEXT_LIMIT {
        return Err(Error::new("it asked to print a text that is too long"));
    }

    // The app's memory, found under the name the app shows it by.
    let memory = caller
        .get_export("memory")
        .and_then(Extern::into_memory)
        .ok_or_else(|| Error::new("it asked to print, but shows no memory called `memory`"))?;

    // Copy the text out of the app's memory. `read` refuses if any part of
    // it lies outside. A start below zero becomes a very large address here,
    // which is outside too.
    let mut room = [0u8; APP_TEXT_LIMIT];
    let text = &mut room[..length as usize];
    memory
        .read(&caller, start as u32 as usize, text)
        .map_err(|_| Error::new("it asked to print a text that lies outside its memory"))?;

    // Clean the text and print it as one line, in one go.
    let mut line = String::from("App: ");
    for &byte in text.iter() {
        line.push(if (b' '..=b'~').contains(&byte) { byte as char } else { '.' });
    }
    line.push_str("\r\n");
    serial_print(&line);

    caller.data_mut().texts_printed += 1;
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
    let mut store = Store::new(&engine, AppState { limits, texts_printed: 0 });
    store.limiter(|state| &mut state.limits);
    store.set_fuel(APP_FUEL).map_err(reason)?;

    // The linker holds the system API: what an app may ask the kernel for.
    // That is one thing so far. An app that asks for anything else, or for
    // `print` in another shape, is not started.
    let mut linker = <Linker<AppState>>::new(&engine);
    linker.func_wrap("kernel", "print", kernel_print).map_err(|problem| reason(Error::from(problem)))?;

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
