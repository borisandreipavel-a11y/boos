//! The locked box: runs an app so that it can touch nothing outside its own
//! memory. An app is a WebAssembly program, and the outside library wasmi
//! carries it out one small step at a time. (The file is not called `box.rs`
//! because `box` is a word Rust keeps for itself.) Notes: `docs/box.md`.

use alloc::format;
use alloc::string::String;

use wasmi::{Config, Engine, Linker, Module, Store, StoreLimits, StoreLimitsBuilder};

use crate::page::plain_text;

// The most memory one app may have, in bytes. An app's memory comes in pieces
// of 64 KB (WebAssembly calls them pages), so this is 16 of them. Without a
// limit an app could ask for more than the machine has, and a request for
// memory that cannot be met stops the whole kernel.
const APP_MEMORY_LIMIT: usize = 1024 * 1024;

// The longest list of functions one app may keep (WebAssembly calls it a
// table). Each place costs the kernel a few bytes, so this needs a limit for
// the same reason as the memory.
const APP_TABLE_LIMIT: usize = 4096;

// The most work one call into an app may do. wasmi counts the app's steps in
// "fuel", roughly one unit per step. When the fuel is used up the app is
// stopped, so an app with a loop that never ends cannot hold the processor
// for good.
const APP_FUEL: u64 = 10_000_000;

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

// What the kernel keeps for an app while it runs. So far that is only the
// limits it holds the app to.
struct AppState {
    limits: StoreLimits,
}

// Runs one function of a program inside the box: hands it two whole numbers
// and gives back the whole number it answers with. Whatever goes wrong comes
// back as a reason in words: a program that breaks WebAssembly's rules, an
// app that asks for something the kernel does not offer, a function that is
// not there, or an app that is stopped while it runs.
pub fn box_run(program: &[u8], function: &str, first: i32, second: i32) -> Result<i32, String> {
    // The engine does the work of running apps. Each run gets an engine of
    // its own, which is thrown away at the end: an engine keeps every program
    // it has translated for as long as it lives.
    let mut settings = Config::default();
    settings.consume_fuel(true); // "Count the app's steps."
    let engine = Engine::new(&settings);

    // Check the program against WebAssembly's rules and translate it into the
    // engine's own steps. A program that breaks a rule is refused here,
    // before any of it has run.
    let module = Module::new(&engine, program).map_err(reason)?;

    // The store holds everything that belongs to the running app, and the
    // limits it is held to: one memory of at most `APP_MEMORY_LIMIT` bytes
    // and one table of at most `APP_TABLE_LIMIT` places.
    let limits = StoreLimitsBuilder::new()
        .memory_size(APP_MEMORY_LIMIT)
        .memories(1)
        .table_elements(APP_TABLE_LIMIT)
        .tables(1)
        .instances(1)
        .build();
    let mut store = Store::new(&engine, AppState { limits });
    store.limiter(|state| &mut state.limits);
    store.set_fuel(APP_FUEL).map_err(reason)?;

    // The linker hands an app the things it asks the kernel for. Nothing is
    // offered yet, so an app that asks for anything at all is not started.
    let linker = <Linker<AppState>>::new(&engine);
    let app = linker.instantiate_and_start(&mut store, &module).map_err(reason)?;

    // Find the function by its name, see that it takes two whole numbers and
    // gives back one, and call it.
    let entry = app.get_typed_func::<(i32, i32), i32>(&store, function).map_err(reason)?;
    entry.call(&mut store, (first, second)).map_err(reason)
}

// wasmi's own words for what went wrong. They can hold names taken from the
// program, which is text from outside, so they are cleaned before they are
// shown and cut at 120 signs.
fn reason(error: wasmi::Error) -> String {
    plain_text(&format!("{}", error), 120)
}

// The check at startup: run the smallest app and see what 2 + 3 comes to.
pub fn box_check() -> Result<i32, String> {
    box_run(&ADDING_APP, "add", 2, 3)
}
