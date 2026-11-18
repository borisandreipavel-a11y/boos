//! JSON: the form in which many services on the internet send and expect
//! their data. It is text, with fixed ways to write a list (`[...]`), a set
//! of named things (`{"name": ...}`), a text (`"..."`), a number, and the
//! words `true`, `false` and `null`. This file does the two things the
//! kernel needs and no more: it writes a text the JSON way, and it finds one
//! text in a piece of JSON by its place.
//! Notes: `docs/json.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::json_values::*;

// One step on the way to a part of a piece of JSON: into the thing with this
// name in a set of named things, or into the thing at this place in a list,
// where the first place is 0.
pub enum Step<'a> {
    Name(&'a str),
    Place(usize),
}

// Why a text could not be found.
pub const NOT_JSON: &str = "it is not sound JSON";
pub const NOT_THERE: &str = "it has no such part";
pub const NOT_A_TEXT: &str = "that part of it is not a text";
pub const NOT_PROPER_TEXT: &str = "a text in it is not made of proper signs";

// Writes a text the JSON way: in double quotes, with every sign that has a
// meaning of its own in JSON written as a backslash and a letter, and every
// other sign below the space (the control signs) as `\u` and four digits.
// All other signs, letters with accents among them, go in as they are.
pub fn json_text(text: &str) -> String {
    let mut out = String::from("\"");
    for sign in text.chars() {
        match sign {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            sign if (sign as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", sign as u32)),
            sign => out.push(sign),
        }
    }
    out.push('"');
    out
}

// Finds one text in a piece of JSON. `path` says where: each step goes into
// a named thing or into a place of a list. The text is given back as plain
// text, with JSON's ways of writing special signs undone.
//
// The JSON comes from outside the kernel, as bytes that may be anything at
// all, so nothing about it is taken on trust. Every byte is reached through
// `get`, which gives nothing where there is no byte instead of stopping the
// kernel, and nothing here calls itself, so brackets nested ten thousand
// deep cost no more of the stack than two.
//
// A name counts where the path looks for it and nowhere else: not inside a
// text, and not one level further in. Of two things with the same name, the
// first is taken.
//
// A text is handed out only if what stands behind it closes properly: every
// bracket that was open is closed, every text has its closing quote, and
// nothing but spaces follows. An answer that was cut off, or damaged so that
// a text ends too early, is turned away whole instead of being believed as
// far as it goes. This is not a full check of the JSON: commas and colons in
// the parts that are passed over are not looked at.
pub fn json_find_text(json: &[u8], path: &[Step]) -> Result<String, &'static str> {
    let mut reader = Reader { bytes: json, at: 0 };
    for step in path {
        reader.skip_space();
        match step {
            Step::Name(name) => reader.go_to_name(name)?,
            Step::Place(place) => reader.go_to_place(*place)?,
        }
    }
    reader.skip_space();
    match reader.peek() {
        Some(b'"') => {
            reader.at += 1;
            let text = reader.text()?;
            // Each step of the path went into one list or set of names.
            reader.rest_closes(path.len())?;
            Ok(text)
        }
        Some(byte) if value_starts(byte) => Err(NOT_A_TEXT),
        _ => Err(NOT_JSON),
    }
}

// Whether a byte can be the first of a value in JSON: a set of named things,
// a list, a text, a number, or one of the words `true`, `false` and `null`.
// What begins with anything else, such as a page of a web site sent in place
// of an answer, is not JSON at all.
fn value_starts(byte: u8) -> bool {
    matches!(byte, b'{' | b'[' | b'"' | b'-' | b'0'..=b'9' | b't' | b'f' | b'n')
}

// A piece of JSON and how far it has been read.
struct Reader<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl Reader<'_> {
    // The byte that comes next, without taking it.
    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.at).copied()
    }

    // Takes the byte that comes next.
    fn take(&mut self) -> Option<u8> {
        let byte = self.peek()?;
        self.at += 1;
        Some(byte)
    }

    // Passes over spaces, tabs and line ends, which may stand between the
    // parts of JSON and mean nothing.
    fn skip_space(&mut self) {
        while let Some(b' ' | b'\t' | b'\n' | b'\r') = self.peek() {
            self.at += 1;
        }
    }

    // At the start of a set of named things: goes to the value of the thing
    // called `name`, passing over the others.
    fn go_to_name(&mut self, name: &str) -> Result<(), &'static str> {
        match self.take() {
            Some(b'{') => {}
            Some(byte) if value_starts(byte) => return Err(NOT_THERE),
            _ => return Err(NOT_JSON),
        }
        loop {
            self.skip_space();
            match self.take() {
                Some(b'"') => {}
                Some(b'}') => return Err(NOT_THERE),
                _ => return Err(NOT_JSON),
            }
            // The name is compared after its special signs are undone, so a
            // name written with `\u` still counts as itself.
            let found = self.text()?;
            self.skip_space();
            if self.take() != Some(b':') {
                return Err(NOT_JSON);
            }
            self.skip_space();
            if found == name {
                return Ok(());
            }
            self.skip_value()?;
            self.skip_space();
            match self.take() {
                Some(b',') => {}
                Some(b'}') => return Err(NOT_THERE),
                _ => return Err(NOT_JSON),
            }
        }
    }

    // At the start of a list: goes to the thing at `place`, passing over the
    // ones before it.
    fn go_to_place(&mut self, place: usize) -> Result<(), &'static str> {
        match self.take() {
            Some(b'[') => {}
            Some(byte) if value_starts(byte) => return Err(NOT_THERE),
            _ => return Err(NOT_JSON),
        }
        let mut passed = 0;
        loop {
            self.skip_space();
            match self.peek() {
                Some(b']') => return Err(NOT_THERE),
                Some(_) => {}
                None => return Err(NOT_JSON),
            }
            if passed == place {
                return Ok(());
            }
            self.skip_value()?;
            passed += 1;
            self.skip_space();
            match self.take() {
                Some(b',') => {}
                Some(b']') => return Err(NOT_THERE),
                _ => return Err(NOT_JSON),
            }
        }
    }

    // Passes over one whole value, whatever it is. A list or a set of named
    // things is passed by counting brackets, opening ones up and closing
    // ones down, until the count is back where it began. Brackets inside a
    // text do not count, so texts are passed over as wholes.
    fn skip_value(&mut self) -> Result<(), &'static str> {
        match self.peek() {
            Some(b'"') => {
                self.at += 1;
                self.skip_text()
            }
            Some(b'{' | b'[') => {
                let mut open: usize = 0;
                loop {
                    match self.take() {
                        Some(b'{' | b'[') => open += 1,
                        Some(b'}' | b']') => {
                            open -= 1;
                            if open == 0 {
                                return Ok(());
                            }
                        }
                        Some(b'"') => self.skip_text()?,
                        Some(_) => {}
                        None => return Err(NOT_JSON),
                    }
                }
            }
            // A number or one of the words: it ends where the next comma,
            // closing bracket or space stands.
            Some(_) => {
                let start = self.at;
                while let Some(byte) = self.peek() {
                    if matches!(byte, b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r') {
                        break;
                    }
                    self.at += 1;
                }
                if self.at == start { Err(NOT_JSON) } else { Ok(()) }
            }
            None => Err(NOT_JSON),
        }
    }

    // Behind a value that lies `open` lists or sets of names deep: sees that
    // the rest of the JSON closes them all, in whole texts and matching
    // counts of brackets, and that nothing but spaces follows the last one.
    fn rest_closes(&mut self, mut open: usize) -> Result<(), &'static str> {
        while open > 0 {
            match self.take() {
                Some(b'{' | b'[') => open += 1,
                Some(b'}' | b']') => open -= 1,
                Some(b'"') => self.skip_text()?,
                Some(_) => {}
                None => return Err(NOT_JSON),
            }
        }
        self.skip_space();
        if self.peek().is_some() { Err(NOT_JSON) } else { Ok(()) }
    }

    // Behind the opening quote of a text: passes over the text without
    // keeping it. A backslash takes the sign behind it along, so that a
    // quote written as `\"` does not end the text.
    fn skip_text(&mut self) -> Result<(), &'static str> {
        loop {
            match self.take() {
                Some(b'"') => return Ok(()),
                Some(b'\\') => {
                    if self.take().is_none() {
                        return Err(NOT_JSON);
                    }
                }
                Some(_) => {}
                None => return Err(NOT_JSON),
            }
        }
    }

    // Behind the opening quote of a text: reads the text up to its closing
    // quote and gives it back as plain text.
    fn text(&mut self) -> Result<String, &'static str> {
        let mut out: Vec<u8> = Vec::new();
        loop {
            match self.take() {
                Some(b'"') => break,
                Some(b'\\') => {
                    let sign = match self.take() {
                        Some(b'"') => '"',
                        Some(b'\\') => '\\',
                        Some(b'/') => '/',
                        Some(b'n') => '\n',
                        Some(b'r') => '\r',
                        Some(b't') => '\t',
                        Some(b'b') => '\u{8}',
                        Some(b'f') => '\u{c}',
                        Some(b'u') => self.numbered_sign()?,
                        _ => return Err(NOT_JSON),
                    };
                    let mut room = [0u8; 4];
                    out.extend_from_slice(sign.encode_utf8(&mut room).as_bytes());
                }
                // A control sign may not stand in a text as it is.
                Some(byte) if byte < 0x20 => return Err(NOT_JSON),
                Some(byte) => out.push(byte),
                None => return Err(NOT_JSON),
            }
        }
        // The bytes between the quotes have to be proper text (UTF-8).
        String::from_utf8(out).map_err(|_| NOT_PROPER_TEXT)
    }

    // Behind `\u`: reads the four digits that give a sign's number. Signs
    // with large numbers are written as two such pieces, a first half and a
    // second half (a surrogate pair), which are joined here. A half that
    // stands alone is no sign at all; the sign for "unknown" takes its place.
    fn numbered_sign(&mut self) -> Result<char, &'static str> {
        const UNKNOWN: char = '\u{fffd}';
        let first = self.four_digits()?;
        if !(0xD800..=0xDFFF).contains(&first) {
            return Ok(char::from_u32(first).unwrap_or(UNKNOWN));
        }
        // A second half with no first half before it.
        if first >= 0xDC00 {
            return Ok(UNKNOWN);
        }
        // A first half: the second has to follow at once, as `\u` and four
        // digits. It is looked at before it is taken, so that whatever else
        // follows is read in the ordinary way.
        let before = self.at;
        if self.take() == Some(b'\\') && self.take() == Some(b'u') {
            if let Ok(second) = self.four_digits() {
                if (0xDC00..=0xDFFF).contains(&second) {
                    let number = 0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00);
                    return Ok(char::from_u32(number).unwrap_or(UNKNOWN));
                }
            }
        }
        self.at = before;
        Ok(UNKNOWN)
    }

    // Reads four digits of the kind that count to sixteen (0 to 9, a to f)
    // as one number.
    fn four_digits(&mut self) -> Result<u32, &'static str> {
        let mut number: u32 = 0;
        for _ in 0..4 {
            let digit = match self.take() {
                Some(byte @ b'0'..=b'9') => byte - b'0',
                Some(byte @ b'a'..=b'f') => byte - b'a' + 10,
                Some(byte @ b'A'..=b'F') => byte - b'A' + 10,
                _ => return Err(NOT_JSON),
            };
            number = number * 16 + digit as u32;
        }
        Ok(number)
    }
}

// The check at startup: does this file make and read JSON as another JSON
// reader does? The values it is held against are in `json_values.rs`, and
// were made by that other reader. Gives back how many checks were right and
// how many there are.
pub fn json_check() -> (usize, usize) {
    use Step::{Name, Place};
    let content = [Name("choices"), Place(0), Name("message"), Name("content")];
    let checks = [
        // Making.
        json_text(PLAIN) == PLAIN_AS_JSON,
        json_text(AWKWARD) == AWKWARD_AS_JSON,
        // Reading an answer of the shape a model's answer has.
        json_find_text(ANSWER, &content).as_deref() == Ok(ANSWER_CONTENT),
        json_find_text(ANSWER, &[Name("choices"), Place(0), Name("finish_reason")]).as_deref() == Ok("stop"),
        json_find_text(ANSWER, &[Name("model")]).as_deref() == Ok(ANSWER_MODEL),
        // Reading a refusal.
        json_find_text(REFUSAL, &[Name("error"), Name("message")]).as_deref() == Ok(REFUSAL_MESSAGE),
        // Every way of writing a special sign, undone.
        json_find_text(ESCAPES, &[Name("text")]).as_deref() == Ok(ESCAPES_TEXT),
        // A name counts only where the path looks for it.
        json_find_text(DECOYS, &content).as_deref() == Ok(DECOYS_CONTENT),
        // What is not there, what is no text, and what is cut off.
        json_find_text(ANSWER, &[Name("choices"), Place(1), Name("message")]) == Err(NOT_THERE),
        json_find_text(ANSWER, &[Name("usage"), Name("total_tokens")]) == Err(NOT_A_TEXT),
        json_find_text(CUT_OFF, &content) == Err(NOT_JSON),
        // A whole answer with something wrong behind the text looked for.
        json_find_text(ONE_TOO_MANY, &content) == Err(NOT_JSON),
        // What was made here is read back here.
        json_find_text(format!("{{\"text\": {}}}", json_text(AWKWARD)).as_bytes(), &[Name("text")]).as_deref() == Ok(AWKWARD),
    ];
    (checks.iter().filter(|right| **right).count(), checks.len())
}
