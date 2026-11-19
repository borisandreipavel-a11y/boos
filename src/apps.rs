//! Apps made on request: the person at the machine says in the chat box what
//! app they want, with the line `make` and a few words, and the model writes
//! the app as a Lua script. This file holds what the model is told about
//! writing an app for this kernel, what the chat box answers to such a line,
//! how the script is taken out of the model's words and checked, how it is
//! shown in the terminal, and how it is run. The asking itself is done by
//! `model.rs`, the one file that may borrow the key.
//! Notes: `docs/apps.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::app_box::{SCRIPT_LIMIT, StopKind};
use crate::errand::{Errand, errand_ask};
use crate::interpreter::script_run_seeded;
use crate::page::plain_text;
use crate::random::random_number;
use crate::secret::secret_length;
use crate::serial::serial_print;

// The word that, at the start of a line sent in the chat box, asks the model
// to write an app. What follows it says which app.
pub const MAKE_WORD: &str = "make";

// What the model is told before the request, every time: which language to
// write in, what the script can and cannot do, and the two functions it has
// for saying something. Each line is written out with its line end (`\n`),
// so that the text does not depend on the kind of line end this file has.
// Everything it says was checked against the interpreter on board.
pub const APP_INSTRUCTIONS: &str = concat!(
    "You write small apps for a home-made operating system. Each app is one script in the language Lua 5.4. ",
    "Answer with the script only: no words before or after it, and no ``` marks around it.\n",
    "\n",
    "The script runs once, from its first line to its last, and then ends. It runs in a locked box: it cannot read keys, ",
    "files, the clock or the network, and it cannot wait. Lua's string, table and math libraries are there; io, os, ",
    "require, debug, coroutine and utf8 are not. math.random works.\n",
    "\n",
    "Two functions put out what the app has to say:\n",
    "- show(text) puts one line of at most 40 characters in a box in the middle of the screen. This is what the person ",
    "at the machine sees. Each show replaces the line shown before, and the last one stays on the screen after the ",
    "script has ended. A longer text is cut at 40 characters, and a 21st show stops the script.\n",
    "- print(...) writes one line to a log beside the screen. A line longer than 200 characters is cut, and a 101st ",
    "print stops the script.\n",
    "\n",
    "Use only plain English letters, digits and the signs of a US keyboard; any other character comes out as a dot.\n",
    "\n",
    "The script's budget of work is small, about four thousand rounds of a simple loop in all, so keep loops short. ",
    "A script longer than 32 KB is refused.\n",
    "\n",
    "If the request cannot be done with these, write a script that shows in a few words what cannot be done.\n",
);

// What stands in front of the person's words in the request, so that the
// model reads them as the app to make.
pub const APP_LEAD: &str = "Make this app: ";

// How many signs of a line of the script are shown in the terminal.
const SCRIPT_LINE_SHOWN: usize = 200;

// Whether a line sent in the chat box asks for an app: the word by itself, or
// followed by a space and what to make. Gives back what follows the word,
// without spaces at either end. A line such as "makes" or "Make a dice" is an
// ordinary line.
pub fn app_wanted(line: &str) -> Option<&str> {
    let rest = line.strip_prefix(MAKE_WORD)?;
    if rest.is_empty() || rest.starts_with(' ') { Some(rest.trim()) } else { None }
}

// What the chat box answers to a line that asks for an app. The asking is an
// errand for the network's task, like "ask"; the model's answer comes later,
// as a row of its own (see `chat_answer` in `chat.rs`). Only the main loop
// may call this, as every function the chat box calls.
pub fn app_ask(wanted: &str) -> String {
    if wanted.is_empty() {
        return format!("Kernel: write what app to make after the word, such as \"{} a dice\".", MAKE_WORD);
    }
    if secret_length() == 0 {
        return String::from("Kernel: I cannot ask the model for an app, because no key is kept. Send the line \"key\" first.");
    }
    match errand_ask(Errand::AppRequest(String::from(wanted))) {
        Ok(()) => format!("Kernel: I am asking the model to make \"{}\".", wanted),
        Err(reason) => format!("Kernel: I cannot ask the model for an app, because {}", reason),
    }
}

// Takes the script out of the model's words, and sees that the box could take
// it. The instruction text asks for the script alone, but a model may still
// put it between two lines that begin with ``` marks, with words around them:
// then only what stands between the first two such lines is taken. With one
// such line only, what stands after it is taken if nothing but empty lines
// comes before it, and what stands before it otherwise. Spaces and empty
// lines at either end are dropped. Gives back the reason in words when there
// is no script, or when it is longer than the box takes.
pub fn app_script(words: &str) -> Result<String, String> {
    let lines: Vec<&str> = words.lines().collect();
    let marks: Vec<usize> = lines
        .iter()
        .enumerate()
        .filter(|(_, line)| line.trim_start().starts_with("```"))
        .map(|(place, _)| place)
        .collect();
    let kept: &[&str] = match marks.as_slice() {
        [] => &lines,
        [only] => {
            if lines[..*only].iter().all(|line| line.trim().is_empty()) {
                &lines[*only + 1..]
            } else {
                &lines[..*only]
            }
        }
        [first, second, ..] => &lines[*first + 1..*second],
    };
    let joined = kept.join("\n");
    let script = joined.trim();
    if script.is_empty() {
        return Err(String::from("there is no script in it"));
    }
    if script.len() > SCRIPT_LIMIT {
        return Err(format!("the script is {} bytes long, and the box takes at most {}", script.len(), SCRIPT_LIMIT));
    }
    Ok(String::from(script))
}

// Shows a script the model wrote in the terminal, line by line, with the
// line's number in front, so that the person at the machine can read what the
// model wrote. The number is the one that Lua names when a script stops at a
// mistake. The script came from outside the kernel: each line is cleaned like
// every text from outside, with a tab first turned into two spaces, and cut
// at `SCRIPT_LINE_SHOWN` signs. Each line is printed on its own, so that the
// device signals are never held off for long.
pub fn app_print_script(script: &str) {
    for (place, line) in script.lines().enumerate() {
        let shown = plain_text(&line.replace('\t', "  "), SCRIPT_LINE_SHOWN);
        if shown.is_empty() {
            serial_print(&format!("Script {}:\r\n", place + 1));
        } else {
            serial_print(&format!("Script {}: {}\r\n", place + 1, shown));
        }
    }
}

// Runs a script the model wrote, in the box, and says in one plain sentence
// how the run went. What the script shows appears in the box in the middle
// of the screen, and what it prints comes out in the terminal as `App: `
// lines, as for any app. It runs here, in the main loop, which is the one
// part of the kernel that paints the screen after startup, so the app's box
// and the chat box are never painted at the same time. While it runs, keys
// wait in the keyboard's line (see `docs/apps.md`). Only the main loop may
// call this.
pub fn app_run(script: &str) -> String {
    // A new number to start the script's random numbers from at every run,
    // from the processor's random numbers. It is halved, so that it stays a
    // whole number above zero when Lua reads it. A machine without random
    // numbers would give none, and the script's random numbers would then
    // start where they always do; but such a machine cannot make the
    // encrypted link, so no app comes to it.
    let seed = random_number().map(|number| (number >> 1) as i64);
    match script_run_seeded(script, seed) {
        Ok(0) => String::from("the app ran to its end, but it showed nothing on the screen."),
        Ok(_) => String::from("the app ran to its end."),
        Err(stop) => match stop.kind {
            StopKind::Mistake => String::from("the app was stopped, because it has a mistake in it; the terminal says which."),
            StopKind::OutOfFuel => String::from("the app was stopped, because it did too much work."),
            StopKind::GaveUp => String::from("the app was stopped, because the interpreter gave up, most likely for lack of memory."),
            StopKind::Other => format!("the app was stopped, because {}.", stop.reason),
        },
    }
}
