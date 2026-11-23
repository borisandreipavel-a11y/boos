//! Inputs of apps: the values an app is given at each run, filled in by the
//! model, such as the distance a converter converts. When the model asks for
//! a new app with the tool `make_app`, it may name the app's inputs, each with
//! a name, a kind and one sentence, and give each its value for this run; when
//! it runs a kept app with `run_app`, it gives the values again (see
//! `tools.rs`). Both come as lines of text, one for each input, the shape the
//! real model fills well for a table, after it left a list of sets of named
//! things empty in two runs. The model that writes the app is told the inputs, never the
//! values. The inputs are kept on the disk with the app's script (see
//! `apps_kept.rs`), and the values reach the script as data, in a table called
//! `input`, never as part of its text (see `interpreter/src/lib.rs`).
//! Everything here comes from outside the kernel, from the model or from the
//! disk, and is checked before anything is done with it.
//! Notes: `docs/apps.md` ("Inputs").

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::json::{NOT_A_TEXT, NOT_THERE, Step, json_find_text, json_find_word};

// What the kernel says when the model gives an app's inputs, or a kept app's
// values, in another shape than a text: a list, a set of named things, a
// number. The sentence names the shape wanted, so that the model can give
// them again in the same line (see "When what a tool did goes back" in
// `docs/tools.md`).
const INPUTS_NOT_LINES: &str = "the model asked for an app, but did not give its inputs as lines of text, one for each input: name | kind | what it is | value.";
const VALUES_NOT_LINES: &str = "the model asked to run a kept app, but did not give its values as lines of text, one for each: name | value.";

// The lines of the text at `at` that hold anything, each without the spaces
// and a `|` at either end, which a model may write around a line as around a
// row of a table. Nothing there, or `null`, means no lines; anything but a
// text is turned down with `not_lines`, and JSON that cannot be read with
// `unread`.
fn lines_at(json: &[u8], at: &[Step], not_lines: &str, unread: &str) -> Result<Vec<String>, String> {
    let text = match json_find_text(json, at) {
        Ok(text) => text,
        Err(NOT_THERE) => return Ok(Vec::new()),
        Err(NOT_A_TEXT) if matches!(json_find_word(json, at).as_deref(), Ok("null")) => return Ok(Vec::new()),
        Err(NOT_A_TEXT) => return Err(String::from(not_lines)),
        Err(_) => return Err(String::from(unread)),
    };
    Ok(text
        .lines()
        .map(|line| String::from(line.trim().trim_start_matches('|').trim_end_matches('|').trim()))
        .filter(|line| !line.is_empty())
        .collect())
}

// A line of values parted into a name and a value: at the first `|`, or,
// in a line without one, at the first `=` or `:`, both trimmed. Nothing for
// a line with none of them.
fn value_line(line: &str) -> Option<(&str, &str)> {
    let (name, value) = line.split_once('|').or_else(|| line.split_once('=')).or_else(|| line.split_once(':'))?;
    Some((name.trim(), value.trim()))
}

// The most inputs an app may have.
pub const INPUTS_MOST: usize = 4;

// The longest name of an input, in signs. A name is made of letters, digits
// and `_`, and begins with a letter, so that a script can read it as
// `input.km`.
const NAME_MOST: usize = 20;

// The longest sentence that says what an input is, in signs. A longer one is
// cut, as a request is.
const ABOUT_MOST: usize = 80;

// The longest text an input of the kind text may be given, in signs.
pub const TEXT_MOST: usize = 100;

// The most digits a number may be written with, before and after its point
// together. Fifteen digits are kept exactly by a whole number of Lua's and by
// a number with a point alike.
const DIGITS_MOST: usize = 15;

// How many signs of a value, or of what the model gave as one, the kernel's
// sentences show. The app gets the whole value.
const SHOWN_MOST: usize = 40;

// The words Lua keeps for itself, which cannot be the name of an input: a
// script could not write `input.end`. The list is the one the interpreter on
// board refuses as names (`test-tools/lua/numbers.lua`).
const LUA_WORDS: [&str; 22] = [
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if", "in", "local", "nil", "not", "or", "repeat",
    "return", "then", "true", "until", "while",
];

// The three kinds of input.
#[derive(Clone, Copy, PartialEq)]
pub enum Kind {
    // A number, which may have a point and may be below zero, such as 5,
    // -3 or 2.5.
    Number,
    // A text of at most `TEXT_MOST` signs.
    Text,
    // Yes or no.
    YesNo,
}

impl Kind {
    // The word for the kind, as the model gives it.
    fn word(self) -> &'static str {
        match self {
            Kind::Number => "number",
            Kind::Text => "text",
            Kind::YesNo => "yes/no",
        }
    }

    // The kind the model named, in small letters or capitals.
    fn from_word(word: &str) -> Option<Kind> {
        let word = word.trim();
        [Kind::Number, Kind::Text, Kind::YesNo].into_iter().find(|kind| kind.word().eq_ignore_ascii_case(word))
    }

    // The kind's letter, as the disk keeps it and the interpreter takes it.
    fn letter(self) -> u8 {
        match self {
            Kind::Number => b'n',
            Kind::Text => b't',
            Kind::YesNo => b'y',
        }
    }

    fn from_letter(letter: u8) -> Option<Kind> {
        [Kind::Number, Kind::Text, Kind::YesNo].into_iter().find(|kind| kind.letter() == letter)
    }
}

// An input of an app: its name, its kind, and the sentence that says what it
// is.
#[derive(Clone, PartialEq)]
pub struct Input {
    pub name: String,
    pub kind: Kind,
    pub about: String,
}

// A value for an input, checked against its kind: a number as it was
// written, a text cleaned like every text from outside, a yes/no as `yes` or
// `no`.
#[derive(Clone, PartialEq)]
pub struct Value {
    pub name: String,
    pub kind: Kind,
    pub given: String,
}

// ---------- What the model gives ----------

// Reads what the model gave the tool `make_app` about the new app's inputs:
// the text `inputs`, one line for each input, its name, its kind, the
// sentence that says what it is, and its value for this run, parted by `|`:
// `km | number | the distance in kilometres | 5`. The value is the rest of
// the line, so that a text may hold a `|`. No `inputs`, `null`, or a text
// without lines means no inputs; anything but a text is turned down, not
// passed over, so that the model hears of it. Gives back the inputs and
// their values, in the order the model gave them, or what the kernel says
// when it turns them down: the app is then not written. Every input needs a
// value, since an app is run as soon as it is written; an empty value counts
// as none.
pub fn inputs_read(given: &str) -> Result<(Vec<Input>, Vec<Value>), String> {
    let lines = lines_at(given.as_bytes(), &[Step::Name("inputs")], INPUTS_NOT_LINES, "the model asked for an app, but I could not read its inputs.")?;
    if lines.len() > INPUTS_MOST {
        return Err(format!("the model asked for an app with more than {} inputs.", INPUTS_MOST));
    }
    let mut inputs: Vec<Input> = Vec::new();
    let mut values = Vec::new();
    for (place, line) in lines.iter().enumerate() {
        let mut parts = line.splitn(4, '|').map(str::trim);
        let (Some(name), Some(kind), Some(about)) = (parts.next(), parts.next(), parts.next()) else {
            return Err(format!(
                "the model gave the app's input {} as \"{}\", but an input is written as name | kind | what it is | value.",
                place + 1,
                shown(line)
            ));
        };
        if !name_fits(name) {
            return Err(format!(
                "the model named an input \"{}\", but a name has letters, digits and _ only, begins with a letter, has at most {} signs, and is no word of Lua's own.",
                shown(name),
                NAME_MOST
            ));
        }
        if inputs.iter().any(|input| input.name == name) {
            return Err(format!("the model gave two inputs the name \"{}\".", name));
        }
        let Some(kind) = Kind::from_word(kind) else {
            return Err(format!("the model gave the input \"{}\" the kind \"{}\", but an input is a number, a text or a yes/no.", name, shown(kind)));
        };
        let about = about_cleaned(about);
        if about.is_empty() {
            return Err(format!("the model gave the input \"{}\" no sentence that says what it is.", name));
        }
        let input = Input { name: String::from(name), kind, about };
        let value = match parts.next().filter(|value| !value.is_empty()) {
            Some(raw) => value_checked(&input, raw)?,
            None => return Err(format!("the model asked for an app with the input \"{}\", but gave it no value, so the app was not written.", input.name)),
        };
        inputs.push(input);
        values.push(value);
    }
    Ok((inputs, values))
}

// Reads the values the model gave the tool `run_app` for a kept app's
// inputs: the text `values`, one line for each, its name and its value
// parted by `|` (or by `=` or `:` in a line without one): `km | 12`. No
// `values`, `null`, or a text without lines means no values; anything but a
// text is turned down. Each value is checked against the input of its name, a
// name the app has no input for is turned down, and so is a name given
// twice; every input needs its value. Gives back the values in the order of
// the app's inputs, or what the kernel says when it turns them down.
pub fn values_read(given: &str, inputs: &[Input], request: &str) -> Result<Vec<Value>, String> {
    let lines = lines_at(given.as_bytes(), &[Step::Name("values")], VALUES_NOT_LINES, "the model asked to run a kept app, but I could not read its values.")?;
    let mut found: Vec<Value> = Vec::new();
    for (place, line) in lines.iter().enumerate() {
        let Some((name, raw)) = value_line(line) else {
            return Err(format!("the model gave the value {} as \"{}\", but a value is written as name | value.", place + 1, shown(line)));
        };
        let Some(input) = inputs.iter().find(|input| input.name == name) else {
            return Err(if inputs.is_empty() {
                format!("the model gave a value for \"{}\", but the app made for \"{}\" takes no inputs.", shown(name), request)
            } else {
                format!("the model gave a value for \"{}\", but the app made for \"{}\" has no input of that name.", shown(name), request)
            });
        };
        if found.iter().any(|value| value.name == name) {
            return Err(format!("the model gave the input \"{}\" two values.", name));
        }
        if raw.is_empty() {
            return Err(format!("the model gave the input \"{}\" no value.", name));
        }
        found.push(value_checked(input, raw)?);
    }
    let mut values = Vec::new();
    for input in inputs {
        match found.iter().find(|value| value.name == input.name) {
            Some(value) => values.push(value.clone()),
            None => return Err(format!("the model asked to run the app made for \"{}\", but gave no value for its input \"{}\".", request, input.name)),
        }
    }
    Ok(values)
}

// Checks a value against its input's kind. A number is written with digits,
// at most one point with digits on both sides of it, and a minus sign in
// front at most, with at most `DIGITS_MOST` digits; spaces around it are
// dropped. A text is cleaned like every text from outside (every byte that
// is not a plain sign becomes a dot) and may have `TEXT_MOST` signs. A
// yes/no is yes, no, true or false, in small letters or capitals.
fn value_checked(input: &Input, raw: &str) -> Result<Value, String> {
    let given = match input.kind {
        Kind::Number => {
            let written = raw.trim();
            if !number_fits(written) {
                return Err(format!("the model gave the input \"{}\" the value \"{}\", which is not a number written with digits.", input.name, shown(raw)));
            }
            String::from(written)
        }
        Kind::Text => {
            let text = plain(raw);
            if text.len() > TEXT_MOST {
                return Err(format!("the model gave the input \"{}\" a text of {} signs, and an input takes at most {}.", input.name, text.len(), TEXT_MOST));
            }
            text
        }
        Kind::YesNo => match raw.trim().to_ascii_lowercase().as_str() {
            "yes" | "true" => String::from("yes"),
            "no" | "false" => String::from("no"),
            _ => return Err(format!("the model gave the input \"{}\" the value \"{}\", which is not yes or no.", input.name, shown(raw))),
        },
    };
    Ok(Value { name: input.name.clone(), kind: input.kind, given })
}

// Whether a number is written as an input's number may be.
fn number_fits(written: &str) -> bool {
    let unsigned = written.strip_prefix('-').unwrap_or(written);
    let (whole, part) = match unsigned.split_once('.') {
        Some((whole, part)) => (whole, Some(part)),
        None => (unsigned, None),
    };
    let digits = |piece: &str| !piece.is_empty() && piece.bytes().all(|sign| sign.is_ascii_digit());
    digits(whole) && part.map_or(true, digits) && whole.len() + part.map_or(0, str::len) <= DIGITS_MOST
}

// Whether a name is one an input may have.
fn name_fits(name: &str) -> bool {
    let bytes = name.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= NAME_MOST
        && bytes[0].is_ascii_alphabetic()
        && bytes.iter().all(|sign| sign.is_ascii_alphanumeric() || *sign == b'_')
        && !LUA_WORDS.contains(&name)
}

// Every byte that is not a plain sign becomes a dot, as in every text from
// outside.
fn plain(text: &str) -> String {
    text.bytes().map(|byte| if (b' '..=b'~').contains(&byte) { byte as char } else { '.' }).collect()
}

// A sentence about an input, made fit to be kept and told: cleaned, spaces at
// either end dropped, and cut at `ABOUT_MOST` signs, as a request is.
fn about_cleaned(about: &str) -> String {
    let plain = plain(about);
    let kept: String = plain.trim().chars().take(ABOUT_MOST).collect();
    String::from(kept.trim_end())
}

// What the model gave, as the kernel's sentences show it: cleaned, and cut at
// `SHOWN_MOST` signs with "..." behind when it is longer.
fn shown(given: &str) -> String {
    let plain = plain(given);
    if plain.len() > SHOWN_MOST { format!("{}...", &plain[..SHOWN_MOST]) } else { plain }
}

// ---------- What is said and told ----------

// The values as the kernel's sentences name them, behind the request: ", with
// km 5", ", with word "hello" and loud yes", or nothing when there are none.
pub fn values_said(values: &[Value]) -> String {
    let mut said = String::new();
    for (place, value) in values.iter().enumerate() {
        said.push_str(if place == 0 {
            ", with "
        } else if place + 1 == values.len() {
            " and "
        } else {
            ", "
        });
        match value.kind {
            Kind::Text => said.push_str(&format!("{} \"{}\"", value.name, shown(&value.given))),
            _ => said.push_str(&format!("{} {}", value.name, value.given)),
        }
    }
    said
}

// The inputs as the model that writes the app is told them, behind the
// request: a line that says so, then one line for each, such as
// "- km, a number: the distance in kilometres". Nothing when there are none.
pub fn inputs_told(inputs: &[Input]) -> String {
    if inputs.is_empty() {
        return String::new();
    }
    let mut told = String::from("\nIts inputs:");
    for input in inputs {
        told.push_str(&format!("\n- {}, a {}: {}", input.name, input.kind.word(), input.about));
    }
    told
}

// The inputs as the tool `run_app` lists them behind a kept app's request:
// ", taking km (a number: the distance in kilometres)", or nothing when the
// app has none.
pub fn inputs_listed(inputs: &[Input]) -> String {
    let mut listed = String::new();
    for (place, input) in inputs.iter().enumerate() {
        listed.push_str(if place == 0 {
            ", taking "
        } else if place + 1 == inputs.len() {
            " and "
        } else {
            ", "
        });
        listed.push_str(&format!("{} (a {}: {})", input.name, input.kind.word(), input.about));
    }
    listed
}

// What the model asked a tool for, about inputs and values, written so that
// two requests for the same thing give the same text (see `tool_wanted` in
// `tools.rs`): for `make_app` the inputs with their values, for `run_app` the
// values, each as the kernel reads it; or, when they cannot be read, what the
// model gave the tool, as it gave it.
pub fn inputs_wanted(given: &str) -> String {
    match inputs_read(given) {
        Ok((inputs, values)) => {
            let mut wanted = String::new();
            for (input, value) in inputs.iter().zip(values.iter()) {
                wanted.push_str(&format!(" [{} {} {} = {}]", input.name, input.kind.word(), input.about, value.given));
            }
            wanted
        }
        Err(_) => format!(" {}", given),
    }
}

pub fn values_wanted(given: &str) -> String {
    let Ok(lines) = lines_at(given.as_bytes(), &[Step::Name("values")], "", "") else {
        return format!(" {}", given);
    };
    let mut wanted = String::new();
    for line in lines.iter() {
        match value_line(line) {
            Some((name, value)) => wanted.push_str(&format!(" [{} = {}]", name, value)),
            None => return format!(" {}", given),
        }
    }
    wanted
}

// ---------- Kept with the script, and handed to the box ----------

// The first byte of a kept script that has inputs: one that no proper text
// (UTF-8) ever holds, so that a kernel from before inputs, which wants the
// whole thing as proper text, refuses to run such an app instead of reading
// its inputs as Lua. Then the form of what follows, so that later forms can
// say more.
const HEAD_MARK: u8 = 0xFF;
const HEAD_FORM: u8 = 1;

// What is kept on the disk for an app: its script alone when it has no
// inputs, exactly as before inputs existed; otherwise a head in front of it
// with its inputs: the mark, the form, how many inputs, and for each its
// kind's letter, its name's length and name, its sentence's length and
// sentence. Both are kept as one thing, in one write, so that the inputs and
// the script never get out of step.
pub fn inputs_kept(inputs: &[Input], script: &str) -> Vec<u8> {
    let mut thing = Vec::new();
    if !inputs.is_empty() {
        thing.push(HEAD_MARK);
        thing.push(HEAD_FORM);
        thing.push(inputs.len() as u8);
        for input in inputs {
            thing.push(input.kind.letter());
            thing.push(input.name.len() as u8);
            thing.extend_from_slice(input.name.as_bytes());
            thing.push(input.about.len() as u8);
            thing.extend_from_slice(input.about.as_bytes());
        }
    }
    thing.extend_from_slice(script.as_bytes());
    thing
}

// Takes a kept thing apart into the app's inputs and its script. A thing
// without the mark is a script alone, with no inputs. The head comes from the
// disk, from outside the kernel, and is held to every rule the model's
// inputs are held to; a head that breaks one gives nothing.
pub fn inputs_found(thing: &[u8]) -> Option<(Vec<Input>, &[u8])> {
    let Some((&HEAD_MARK, rest)) = thing.split_first() else {
        return Some((Vec::new(), thing));
    };
    let (&form, rest) = rest.split_first()?;
    let (&count, mut rest) = rest.split_first()?;
    if form != HEAD_FORM || !(1..=INPUTS_MOST).contains(&(count as usize)) {
        return None;
    }
    let mut inputs: Vec<Input> = Vec::new();
    for _ in 0..count {
        let (&letter, after) = rest.split_first()?;
        let (name, after) = piece(after)?;
        let (about, after) = piece(after)?;
        let kind = Kind::from_letter(letter)?;
        if !name_fits(name) || inputs.iter().any(|input| input.name == name) || about.is_empty() || about != about_cleaned(about) {
            return None;
        }
        inputs.push(Input { name: String::from(name), kind, about: String::from(about) });
        rest = after;
    }
    Some((inputs, rest))
}

// A piece of a head: its length in one byte, then that many bytes of plain
// signs.
fn piece(bytes: &[u8]) -> Option<(&str, &[u8])> {
    let (&length, rest) = bytes.split_first()?;
    let (piece, rest) = rest.split_at_checked(length as usize)?;
    if !piece.iter().all(|byte| (b' '..=b'~').contains(byte)) {
        return None;
    }
    Some((core::str::from_utf8(piece).ok()?, rest))
}

// The values as the interpreter takes them, behind the script (see
// `interpreter/src/lib.rs`): for each, its kind's letter, its name's length
// and name, its value's length and value, as text.
pub fn values_handed(values: &[Value]) -> Vec<u8> {
    let mut handed = Vec::new();
    for value in values {
        handed.push(value.kind.letter());
        handed.push(value.name.len() as u8);
        handed.extend_from_slice(value.name.as_bytes());
        handed.push(value.given.len() as u8);
        handed.extend_from_slice(value.given.as_bytes());
    }
    handed
}
