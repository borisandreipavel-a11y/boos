//! The interpreter: a program for the locked box that understands the
//! language Lua. The kernel hands it a script as text and it carries the
//! script out. The work of understanding Lua is done by the outside library
//! omnilua; this file is the small piece between that library and the
//! kernel. A script can ask the kernel for one thing so far: to print a line.
//! Notes: `docs/interpreter.md`.

use omnilua::Lua;

// What the kernel offers to a program in the box. This program uses one call
// of it: `print` of `kernel`, which takes where a text begins in this
// program's memory and how many bytes long it is.
#[link(wasm_import_module = "kernel")]
unsafe extern "C" {
    fn print(start: *const u8, length: usize);
}

// The longest text the kernel prints for an app. A longer one would get the
// whole program stopped, so it is cut here.
const LONGEST_LINE: usize = 200;

// Hands a text to the kernel's print.
fn say(text: &str) {
    let bytes = text.as_bytes();
    let length = bytes.len().min(LONGEST_LINE);
    unsafe { print(bytes.as_ptr(), length) };
}

// Where the kernel puts a script's text before it calls `run`.
static mut SCRIPT: Vec<u8> = Vec::new();

// The kernel asks for room for a script of `length` bytes, and gets back
// where in this program's memory to write it.
#[unsafe(no_mangle)]
pub extern "C" fn room(length: usize) -> *mut u8 {
    unsafe {
        let script = &mut *(&raw mut SCRIPT);
        *script = vec![0; length];
        script.as_mut_ptr()
    }
}

// Lua's own `print` writes to a screen that a program in the box does not
// have. This one, written in Lua itself, joins what it is given with tabs,
// as Lua's does, and hands the line to the kernel through `say`.
// (Written line by line, each with its line end spelt out, so that the built
// program does not depend on which kind of line end this file has.)
const PRINT_IN_LUA: &str = concat!(
    "function print(...)\n",
    "  local parts = {}\n",
    "  for i = 1, select(\"#\", ...) do\n",
    "    parts[i] = tostring((select(i, ...)))\n",
    "  end\n",
    "  say(table.concat(parts, \"\\t\"))\n",
    "end\n",
);

// Carries a script out. Whatever goes wrong, a mistake in how the script is
// written or one that turns up while it runs, comes back in words.
fn run_script(text: &str) -> Result<(), String> {
    let lua = Lua::new();
    let say_function = lua
        .create_function(|_, text: String| {
            say(&text);
            Ok(())
        })
        .map_err(|problem| problem.to_string())?;
    lua.globals().set("say", say_function).map_err(|problem| problem.to_string())?;
    lua.load(PRINT_IN_LUA).exec().map_err(|problem| problem.to_string())?;
    lua.load(text).set_name("app").exec().map_err(|problem| problem.to_string())
}

// The kernel calls this after writing a script of `length` bytes into the
// room. A script that cannot be carried out to its end is reported as a
// printed line, and this program ends in the ordinary way.
#[unsafe(no_mangle)]
pub extern "C" fn run(length: usize) {
    let script = unsafe { &*(&raw const SCRIPT) };
    let Some(bytes) = script.get(..length) else {
        say("Lua: the script is longer than the room asked for");
        return;
    };
    let Ok(text) = core::str::from_utf8(bytes) else {
        say("Lua: the script is not text");
        return;
    };
    if let Err(problem) = run_script(text) {
        say(&format!("Lua stopped: {}", problem));
    }
}
