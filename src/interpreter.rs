//! The interpreter: a program that understands the language Lua. It is not
//! part of the kernel. It is a WebAssembly program like any app, made from
//! the folder `interpreter/`, and the kernel carries the finished file inside
//! it. An app written as Lua text will be run by handing that text to the
//! interpreter inside the locked box. So far the kernel only carries it and
//! sees at startup that the box would take it.
//! Notes: `docs/interpreter.md`.

use alloc::string::String;

use crate::app_box::box_accepts;

// The program, byte for byte the file that building the folder
// `interpreter/` makes. It is read in when the kernel is built, so the
// interpreter has to be built first: `run.bat` does both in that order. If
// the compiler stops here because it cannot read the file, the interpreter
// has not been built yet.
static INTERPRETER: &[u8] = include_bytes!("../interpreter/target/wasm32-unknown-unknown/release/interpreter.wasm");

// The check at startup: would the box take the interpreter? The box checks
// the whole program against WebAssembly's rules, holds it to the limits every
// app is held to, and offers it the system API. Then the two functions the
// kernel will call are looked for: `room`, which makes room for a script's
// text, and `run`, which carries the script out. Neither is called yet.
// Gives back how many bytes long the program is.
pub fn interpreter_check() -> Result<usize, String> {
    box_accepts(INTERPRETER, &["room", "run"])?;
    Ok(INTERPRETER.len())
}
