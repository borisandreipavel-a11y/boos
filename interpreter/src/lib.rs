//! The interpreter: a program for the locked box that understands the
//! language Lua. The kernel hands it a script as text and it carries the
//! script out. The work of understanding Lua is done by the outside library
//! omnilua; this file is the small piece between that library and the
//! kernel. A script can ask the kernel for two things so far: to print a
//! line, and to show a text on the screen.
//! Notes: `docs/interpreter.md`.

use omnilua::Lua;

// What the kernel offers to a program in the box. This program uses both
// calls of it: `print` of `kernel`, which prints a text as a line, and `show`
// of `kernel`, which shows a text on the screen. Each takes where the text
// begins in this program's memory and how many bytes long it is.
#[link(wasm_import_module = "kernel")]
unsafe extern "C" {
    fn print(start: *const u8, length: usize);
    fn show(start: *const u8, length: usize);
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

// Hands a text to the kernel's show, whole. The kernel shows one line of at
// most 40 signs and stops an app that asks for more. That rule is the
// kernel's, so nothing is cut here: a script that shows a longer text is
// stopped, and the kernel says why.
fn show_text(text: &str) {
    let bytes = text.as_bytes();
    unsafe { show(bytes.as_ptr(), bytes.len()) };
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
// have. This one, written in Lua itself, joins what it is given and hands
// the line to the kernel through `say`. Lua's own puts a tab between two
// values; this one puts a space, because the kernel prints plain signs only
// and would show a tab as a dot.
// (Written line by line, each with its line end spelt out, so that the built
// program does not depend on which kind of line end this file has.)
const PRINT_IN_LUA: &str = concat!(
    "function print(...)\n",
    "  local parts = {}\n",
    "  for i = 1, select(\"#\", ...) do\n",
    "    parts[i] = tostring((select(i, ...)))\n",
    "  end\n",
    "  say(table.concat(parts, \" \"))\n",
    "end\n",
);

// `show` as a script sees it, written in Lua too. The function this program
// puts under that name first takes a text and nothing else, so `show(42)`
// would stop the script. This one turns whatever it is given into text, as
// `print` does, and then hands it on. The first function is kept where only
// this piece of Lua can reach it.
const SHOW_IN_LUA: &str = concat!(
    "local hand_over = show\n",
    "function show(value)\n",
    "  hand_over(tostring(value))\n",
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

    // `show(text)` in a script: the text appears on the screen, in the box
    // the kernel keeps for an app's text. The script says only which text.
    let show_function = lua
        .create_function(|_, text: String| {
            show_text(&text);
            Ok(())
        })
        .map_err(|problem| problem.to_string())?;
    lua.globals().set("show", show_function).map_err(|problem| problem.to_string())?;

    lua.load(PRINT_IN_LUA).exec().map_err(|problem| problem.to_string())?;
    lua.load(SHOW_IN_LUA).exec().map_err(|problem| problem.to_string())?;
    lua.load(text).set_name("app").exec().map_err(|problem| problem.to_string())
}

// What `run` gives back to the kernel: whether the script was carried out to
// its end, or stopped by a mistake.
const RAN_TO_ITS_END: i32 = 0;
const STOPPED: i32 = 1;

// The kernel calls this after writing a script of `length` bytes into the
// room. A script that cannot be carried out to its end is reported as a
// printed line, and the kernel is told through the number given back. Either
// way this program itself ends in the ordinary way.
#[unsafe(no_mangle)]
pub extern "C" fn run(length: usize) -> i32 {
    let script = unsafe { &*(&raw const SCRIPT) };
    let Some(bytes) = script.get(..length) else {
        say("Lua: the script is longer than the room asked for");
        return STOPPED;
    };
    let Ok(text) = core::str::from_utf8(bytes) else {
        say("Lua: the script is not text");
        return STOPPED;
    };
    match run_script(text) {
        Ok(()) => RAN_TO_ITS_END,
        Err(problem) => {
            say(&format!("Lua stopped: {}", problem));
            STOPPED
        }
    }
}
