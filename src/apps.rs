//! Apps made on request: the person at the machine asks for an app in the
//! chat box, in their own words; the model asks the kernel for it with the
//! tool `make_app` and a short request (see `tools.rs`), and is then asked to
//! write the app as a Lua script. This file holds what the model is told
//! about writing an app for this kernel, what the kernel says when the model
//! asks for one, how the script is taken out of the model's words and
//! checked, how it is shown in the terminal, and how it is run. The asking
//! itself is done by `model.rs`, the one file that may borrow the key.
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

// The tool `make_app`: has the model write the app for this request, as an
// errand for the network's task; the model's answer comes later, as a row of
// its own (see `chat_answer` in `chat.rs`). The request comes from the model,
// and was cleaned and cut by `tool_do` in `tools.rs`. Gives back what the
// kernel says at once: that the model is asked, or why it is not. Only the
// main loop may call this, as every function the chat box calls.
pub fn app_make(request: &str) -> Result<String, String> {
    if request.is_empty() {
        return Err(String::from("the model asked for an app, but did not say what it should do."));
    }
    if secret_length() == 0 {
        return Err(String::from("I cannot ask the model for an app, because no key is kept. Send the line \"key\" first."));
    }
    match errand_ask(Errand::AppRequest(String::from(request))) {
        Ok(()) => Ok(format!("I am asking the model to make \"{}\".", request)),
        Err(reason) => Err(format!("I cannot ask the model for an app, because {}", reason)),
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

// How the run of an app went: the sentence that says so, whether the app ran
// to its end, and what of the run goes back to the model when it is asked
// about the line again (see `chat.rs`), as sentences of the kernel's own:
// what the app left on the screen, if it showed anything in this run, and,
// for an app stopped at a mistake, the interpreter's line that says which.
pub struct AppRun {
    pub sentence: String,
    pub ran: bool,
    pub told: Vec<String>,
}

// Runs a script the model wrote, in the box, and says in one plain sentence
// how the run went, and whether it ran to its end. What the script shows
// appears in the box in the middle of the screen, and what it prints comes
// out in the terminal as `App: ` lines, as for any app. It runs here, in the
// main loop, which is the one part of the kernel that paints the screen after
// startup, so the app's box and the chat box are never painted at the same
// time. While it runs, keys wait in the keyboard's line (see `docs/apps.md`).
// Only the main loop may call this.
pub fn app_run(script: &str) -> AppRun {
    // A new number to start the script's random numbers from at every run,
    // from the processor's random numbers. It is halved, so that it stays a
    // whole number above zero when Lua reads it. A machine without random
    // numbers would give none, and the script's random numbers would then
    // start where they always do; but such a machine cannot make the
    // encrypted link, so no app comes to it.
    let seed = random_number().map(|number| (number >> 1) as i64);
    let (sentence, ran, texts, mistake) = match script_run_seeded(script, seed) {
        Ok(texts) if texts.shown.is_none() => (String::from("the app ran to its end, but it showed nothing on the screen."), true, texts, false),
        Ok(texts) => (String::from("the app ran to its end."), true, texts, false),
        Err(stop) => {
            let sentence = match stop.kind {
                StopKind::Mistake => String::from("the app was stopped, because it has a mistake in it; the terminal says which."),
                StopKind::OutOfFuel => String::from("the app was stopped, because it did too much work."),
                StopKind::GaveUp => String::from("the app was stopped, because the interpreter gave up, most likely for lack of memory."),
                StopKind::Other => format!("the app was stopped, because {}.", stop.reason),
            };
            (sentence, false, stop.texts, stop.kind == StopKind::Mistake)
        }
    };
    // Both texts were cleaned and held to their bounds when the app handed
    // them over: 40 signs on the screen, 200 in a printed line.
    let mut told = Vec::new();
    if let Some(shown) = texts.shown {
        told.push(format!("the app left this on the screen: \"{}\".", shown));
    }
    if let Some(printed) = texts.printed.filter(|_| mistake) {
        told.push(format!("the terminal says: \"{}\".", printed));
    }
    AppRun { sentence, ran, told }
}
