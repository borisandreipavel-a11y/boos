//! Asking the model: one question goes to the provider, a service on the
//! internet that passes it on to a model, and the answer comes back as text.
//! The provider wants a key with every question, which is the secret that the
//! person at the machine typed. This is the one file that may borrow that
//! secret, and it sends it to one site only, over an encrypted link.
//! Notes: `docs/model.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

use smoltcp::iface::{Interface, SocketSet};
use smoltcp::wire::Ipv4Address;

use crate::json::{Step, json_find_text, json_text};
use crate::network::Card;
use crate::page::{plain_text, site_exchange};
use crate::secret::{SECRET_LIMIT, secret_lend, wipe};

// The provider's site, and the place on it where questions go.
pub const MODEL_SITE: &str = "api.orcarouter.ai";
const MODEL_PATH: &str = "/v1/chat/completions";

// The model that is asked, by the name the provider knows it by.
const MODEL_NAME: &str = "deepseek/deepseek-v4.1-flash-1017";

// The one question that is asked for now.
pub const QUESTION: &str = "Say hello in five words.";

// The longest answer the model may give. Models count in tokens, which are
// pieces of words; a token is about three quarters of a word.
const ANSWER_TOKENS: usize = 300;

// How many seconds the greeting and the answer together may take. A model
// needs longer for its answer than a site needs for a page.
const MODEL_WAIT: u64 = 60;

// How many bytes of the provider's answer are kept. An answer that is longer
// is not read at all.
const ANSWER_ROOM: usize = 64 * 1024;

// How many signs of the provider's or the model's words are said.
const WORDS_SHOWN: usize = 300;

// A piece of the key this long or longer is not passed on if the provider
// repeats it in its answer (see `key_hide`).
const KEY_PIECE: usize = 6;

// The pass that `secret_lend` asks for. What is inside the brackets is
// private to this file, so no other file can make one.
pub struct KeyPass(());

// Asks the model the question and says in one sentence how that went: what
// the model answered, why the provider turned the question down, or why no
// answer came. Called by the network's task when it runs an errand; the
// sentence is the errand's answer. Words from outside in it were cleaned.
pub fn model_tell(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>) -> String {
    // The key is borrowed once, into a room of this function's own, and that
    // copy serves the whole asking: it goes into the request, and it is what
    // is looked for in the answer afterwards. Borrowing is short that way,
    // and a new key typed while the answer is awaited changes nothing about
    // this asking. The room is wiped before this function ends.
    let mut key_room = [0u8; SECRET_LIMIT];
    let mut key_length = 0;
    secret_lend(&KeyPass(()), &mut |key| {
        key_length = key.len().min(SECRET_LIMIT);
        key_room[..key_length].copy_from_slice(&key[..key_length]);
    });
    let sentence = if key_length == 0 {
        String::from("no answer came, because no key is kept")
    } else {
        question_ask(interface, card, sockets, name_server, &key_room[..key_length])
    };
    wipe(&mut key_room);
    sentence
}

// The asking itself, with the key in hand.
fn question_ask(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>, key: &[u8]) -> String {
    // What is asked, the JSON way. `json_text` puts each text in quotes and
    // takes care of signs that have a meaning of their own in JSON.
    let body = format!(
        "{{\"model\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}],\"max_tokens\":{}}}",
        json_text(MODEL_NAME),
        json_text(QUESTION),
        ANSWER_TOKENS
    );

    // The request, in the web's own language: "POST" hands something in, at
    // the place named behind it. Then come lines of notes: which site is
    // meant, what form the body has, how many bytes long it is, that the
    // connection may be closed after the answer, and the key. An empty line
    // ends the notes, and the body follows.
    let head = format!(
        "POST {} HTTP/1.0\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nAuthorization: Bearer ",
        MODEL_PATH,
        MODEL_SITE,
        body.len()
    );

    // The request holds the key, so it is put together in a room that is
    // large enough from the start: a list that has to grow moves, and would
    // leave a copy of the key behind. The room is wiped when the request has
    // been sent, however the sending went.
    let mut request: Vec<u8> = Vec::with_capacity(head.len() + key.len() + 4 + body.len());
    request.extend_from_slice(head.as_bytes());
    request.extend_from_slice(key);
    request.extend_from_slice(b"\r\n\r\n");
    request.extend_from_slice(body.as_bytes());

    // The answer is collected whole, up to the room there is for it.
    let mut answer: Vec<u8> = Vec::new();
    let mut too_long = false;
    let result = site_exchange(interface, card, sockets, name_server, MODEL_SITE, &request, MODEL_WAIT, &mut |bytes| {
        if answer.len() + bytes.len() <= ANSWER_ROOM {
            answer.extend_from_slice(bytes);
        } else {
            too_long = true;
        }
    });
    wipe(&mut request);

    match result {
        Err(reason) => format!("no answer came, because {}", reason),
        Ok(_) if too_long => String::from("no answer came that I could read, because the provider's answer is larger than the room for it"),
        Ok(whole) => answer_sentence(&answer, whole, key),
    }
}

// ---------- Reading the answer ----------

// The provider's answer is bytes from outside. Everything below reads them
// with `get`, which gives nothing where there is no byte, so that no answer,
// however broken, can make the kernel reach outside the answer.

// What an answer on the web is made of: a number in its first line that says
// how it went (200 means: here it is; 401 means: I do not know you), and,
// after the lines of notes and an empty line, the body.
struct Parts<'a> {
    number: u32,
    body: &'a [u8],
}

// Where the line that begins at `from` ends: the place of its line end (byte
// 10), or nothing if the answer stops before one.
fn line_end(answer: &[u8], from: usize) -> Option<usize> {
    let rest = answer.get(from..)?;
    Some(from + rest.iter().position(|byte| *byte == b'\n')?)
}

// A line without the byte 13 that comes before each line end.
fn line_bare(line: &[u8]) -> &[u8] {
    match line.split_last() {
        Some((b'\r', rest)) => rest,
        _ => line,
    }
}

// Takes an answer apart. Gives nothing if it does not begin the way an
// answer on the web does, or if it stops before its body begins.
fn answer_parts(answer: &[u8]) -> Option<Parts<'_>> {
    // The first line reads like "HTTP/1.1 401 Unauthorized": the number is
    // the three digits behind the first space.
    let first_end = line_end(answer, 0)?;
    let first = line_bare(answer.get(..first_end)?);
    if !first.starts_with(b"HTTP/") {
        return None;
    }
    let space = first.iter().position(|byte| *byte == b' ')?;
    let digits = first.get(space + 1..space + 4)?;
    let mut number = 0;
    for digit in digits {
        if !digit.is_ascii_digit() {
            return None;
        }
        number = number * 10 + (*digit - b'0') as u32;
    }

    // The lines of notes are passed over, up to the empty line.
    let mut place = first_end + 1;
    loop {
        let end = line_end(answer, place)?;
        let line = line_bare(answer.get(place..end)?);
        place = end + 1;
        if line.is_empty() {
            break;
        }
    }
    Some(Parts { number, body: answer.get(place..)? })
}

// Says in one sentence what the provider's answer holds. `whole` says
// whether the provider said, through the encrypted link, that it had sent
// everything. `key` is the key that went with the question: it is kept out
// of the words that are passed on.
fn answer_sentence(answer: &[u8], whole: bool, key: &[u8]) -> String {
    if answer.is_empty() {
        return "no answer came, because the provider sent nothing".into();
    }
    let Some(parts) = answer_parts(answer) else {
        return "no answer came that I could read, because what the provider sent does not begin as an answer on the web does".into();
    };
    let cut_short = if whole { "" } else { " Its answer did not come whole." };

    if parts.number == 200 {
        // The model's words are in the body at: choices, the first of them,
        // message, content.
        let path = [Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("content")];
        return match json_find_text(parts.body, &path) {
            Ok(words) => format!("the model answered \"{}\".{}", words_shown(&words, key), cut_short),
            Err(reason) => format!("the provider answered, but I could not find the model's words in its answer, because {}.{}", reason, cut_short),
        };
    }

    // Any other number is a refusal. The provider says why in the body, in
    // one of these places.
    let places: [&[Step]; 3] = [&[Step::Name("error"), Step::Name("message")], &[Step::Name("error")], &[Step::Name("message")]];
    for path in places {
        if let Ok(words) = json_find_text(parts.body, path) {
            return format!("the provider turned the question down ({}): \"{}\".{}", parts.number, words_shown(&words, key), cut_short);
        }
    }
    format!("the provider turned the question down ({}), and I could not read why.{}", parts.number, cut_short)
}

// ---------- Words from outside ----------

// Makes words that came from the provider fit to be said: cleaned like every
// text from outside, with the key hidden in them, and cut at `WORDS_SHOWN`
// signs. The key is hidden before the cut, so that the cut cannot leave the
// beginning of the key standing at the end.
fn words_shown(words: &str, key: &[u8]) -> String {
    let mut signs = plain_text(words, usize::MAX).into_bytes();
    key_hide(&mut signs, key);
    signs.truncate(WORDS_SHOWN);
    // Only plain signs are left, one byte each, so this cannot fail.
    String::from_utf8_lossy(&signs).into_owned()
}

// A provider may repeat the key, or a piece of it, in its answer. What the
// kernel says is shown on the screen and printed in the terminal, where the
// key must not turn up. This writes a star over every sign in `signs` that
// belongs to a piece of the key: a run of signs that stands in the key and
// is `KEY_PIECE` signs long or longer, or the whole key if it is shorter
// than that.
fn key_hide(signs: &mut [u8], key: &[u8]) {
    let least = KEY_PIECE.min(key.len());
    if least == 0 {
        return;
    }
    // First mark, then write the stars: a star written at once would spoil
    // the search for a piece that begins inside another.
    let mut hidden = vec![false; signs.len()];
    for start in 0..signs.len() {
        for key_start in 0..key.len() {
            // How many signs from here on are the same in both.
            let mut same = 0;
            while let (Some(sign), Some(key_sign)) = (signs.get(start + same), key.get(key_start + same)) {
                if sign != key_sign {
                    break;
                }
                same += 1;
            }
            if same >= least {
                for mark in hidden.iter_mut().skip(start).take(same) {
                    *mark = true;
                }
            }
        }
    }
    for (sign, mark) in signs.iter_mut().zip(hidden.iter()) {
        if *mark {
            *sign = b'*';
        }
    }
}
