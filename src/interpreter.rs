//! The interpreter: a program that understands the language Lua. It is not
//! part of the kernel. It is a WebAssembly program like any app, made from
//! the folder `interpreter/`, and the kernel carries the finished file inside
//! it. An app written as Lua text, a script, is run by handing that text to
//! the interpreter inside the locked box.
//! Notes: `docs/interpreter.md`.

use alloc::string::String;

use crate::app_box::{ScriptStop, box_accepts, box_script};

// The program, byte for byte the file that building the folder
// `interpreter/` makes. It is read in when the kernel is built, so the
// interpreter has to be built first: `run.bat` does both in that order. If
// the compiler stops here because it cannot read the file, the interpreter
// has not been built yet.
static INTERPRETER: &[u8] = include_bytes!("../interpreter/target/wasm32-unknown-unknown/release/interpreter.wasm");

// A whole app as a script, written by hand: it makes a greeting, adds three
// exclamation marks to it one at a time, and asks for the result to be
// printed and to be shown on the screen. Each line of the script is written
// out with its line end (`\n`).
pub const GREETING_SCRIPT: &str = concat!(
    "local greeting = \"Hello from a Lua script\"\n",
    "for count = 1, 3 do\n",
    "  greeting = greeting .. \"!\"\n",
    "end\n",
    "print(greeting)\n",
    "show(greeting)\n",
);

// The check at startup: would the box take the interpreter? The box checks
// the whole program against WebAssembly's rules, holds it to the limits every
// app is held to, and offers it the system API. Then the three functions the
// kernel calls are looked for by name: `room`, which makes room for a
// script's text, `seed`, which takes a number to start the script's random
// numbers from, and `run`, which carries the script out. None is called
// here. Gives back how many bytes long the program is.
pub fn interpreter_check() -> Result<usize, String> {
    box_accepts(INTERPRETER, &["room", "seed", "run"])?;
    Ok(INTERPRETER.len())
}

// Runs a script: the interpreter is got ready in the box, handed the script's
// text, and told to carry it out. What the script prints comes out as the
// kernel's `App: ` lines, as for any app. Whatever goes wrong comes back as a
// reason in words: an interpreter the box does not take, a script that is too
// long, a script that is stopped, or a script with a mistake in it.
pub fn script_run(script: &str) -> Result<(), String> {
    box_script(INTERPRETER, script, None).map(|_| ()).map_err(|stop| stop.reason)
}

// Runs a script that came from outside the kernel, such as an app the model
// wrote, in the same way, with `seed` as the number its random numbers start
// from, if there is one. Gives back how many texts it showed on the screen,
// or why it was stopped and what kind of stop it was (see `ScriptStop`).
pub fn script_run_seeded(script: &str, seed: Option<i64>) -> Result<usize, ScriptStop> {
    box_script(INTERPRETER, script, seed)
}
