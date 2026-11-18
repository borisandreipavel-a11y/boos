//! The interpreter: a program that understands the language Lua. It is not
//! part of the kernel. It is a WebAssembly program like any app, made from
//! the folder `interpreter/`, and the kernel carries the finished file inside
//! it. An app written as Lua text, a script, is run by handing that text to
//! the interpreter inside the locked box.
//! Notes: `docs/interpreter.md`.

use alloc::string::String;

use crate::app_box::{box_accepts, box_script};

// The program, byte for byte the file that building the folder
// `interpreter/` makes. It is read in when the kernel is built, so the
// interpreter has to be built first: `run.bat` does both in that order. If
// the compiler stops here because it cannot read the file, the interpreter
// has not been built yet.
static INTERPRETER: &[u8] = include_bytes!("../interpreter/target/wasm32-unknown-unknown/release/interpreter.wasm");

// A whole app as a script, written by hand: it makes a greeting, adds three
// exclamation marks to it one at a time, and asks for the result to be
// printed. Each line of the script is written out with its line end (`\n`).
pub const GREETING_SCRIPT: &str = concat!(
    "local greeting = \"Hello from a Lua script\"\n",
    "for count = 1, 3 do\n",
    "  greeting = greeting .. \"!\"\n",
    "end\n",
    "print(greeting)\n",
);

// The check at startup: would the box take the interpreter? The box checks
// the whole program against WebAssembly's rules, holds it to the limits every
// app is held to, and offers it the system API. Then the two functions the
// kernel calls are looked for by name: `room`, which makes room for a
// script's text, and `run`, which carries the script out. Neither is called
// here. Gives back how many bytes long the program is.
pub fn interpreter_check() -> Result<usize, String> {
    box_accepts(INTERPRETER, &["room", "run"])?;
    Ok(INTERPRETER.len())
}

// Runs a script: the interpreter is got ready in the box, handed the script's
// text, and told to carry it out. What the script prints comes out as the
// kernel's `App: ` lines, as for any app. Whatever goes wrong comes back as a
// reason in words: an interpreter the box does not take, a script that is too
// long, a script that is stopped, or a script with a mistake in it.
pub fn script_run(script: &str) -> Result<(), String> {
    box_script(INTERPRETER, script)
}
