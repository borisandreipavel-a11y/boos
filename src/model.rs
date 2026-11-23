//! Asking the model: one question goes to the provider, a service on the
//! internet that passes it on to a model, and the answer comes back as text.
//! The question is a line typed in the chat box, sent with the list of what
//! the kernel can do (see `tools.rs`) and the record of what was said before
//! it (see `conversation.rs`), whose answer is the model's words or a tool it
//! asks for; a request for an app, whose answer is a script (see
//! `apps.rs`); or the one fixed question, with which a key typed at the
//! onboarding is tried. The provider wants a key with every question, which
//! is the secret that the person at the machine typed. This is the one file
//! that may borrow that secret, and it sends it to one site only, over an
//! encrypted link.
//! Notes: `docs/model.md`, `docs/tools.md`, `docs/apps.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

use smoltcp::iface::{Interface, SocketSet};
use smoltcp::wire::Ipv4Address;

use crate::apps::{APP_INSTRUCTIONS, APP_LEAD, app_script};
use crate::json::{NOT_A_TEXT, NOT_THERE, Step, json_find_number, json_find_text, json_text};
use crate::tools::{AGAIN_LEAD, CHAT_INSTRUCTIONS, LAST_ASK, RECORD_LEAD};
use crate::network::Card;
use crate::page::{plain_text, site_exchange};
use crate::secret::{SECRET_LIMIT, secret_lend, trial_lend, wipe};

// The provider's site, and the place on it where questions go.
pub const MODEL_SITE: &str = "api.orcarouter.ai";
const MODEL_PATH: &str = "/v1/chat/completions";

// The model that is asked, by the name the provider knows it by.
const MODEL_NAME: &str = "deepseek/deepseek-v4.1-flash-1017";

// The one fixed question, with which a key typed at the onboarding is tried.
pub const QUESTION: &str = "Say hello in five words.";

// The longest answer the model may give to the fixed question. Models count
// in tokens, which are pieces of words; a token is about three quarters of a
// word. A model that thinks before it answers may spend tokens on that too,
// so there is room for far more than a short answer needs. The provider is
// paid by the token used, not by this limit.
const ANSWER_TOKENS: usize = 1000;

// The longest answer the model may give to a line typed in the chat box: room
// for its thinking and a table it describes with the tool `draw_table` (see
// `drawing.rs`).
const LINE_TOKENS: usize = 4000;

// The longest answer the model may give when it is asked for an app. A script
// is longer than a greeting, and a model that thinks first pays its thinking
// out of the same tokens. 4000 tokens are about 16 KB of text, so the thoughts
// and the script together stay well inside the room for the answer below.
const APP_TOKENS: usize = 4000;

// How many seconds the greeting and the answer together may take. A model
// needs longer for its answer than a site needs for a page.
const MODEL_WAIT: u64 = 60;

// How many bytes of the provider's answer are kept. An answer that is longer
// is not read at all.
const ANSWER_ROOM: usize = 64 * 1024;

// How many signs of the provider's or the model's words are said.
const WORDS_SHOWN: usize = 300;

// How many signs of the beginning of a good answer are said when the model's
// words cannot be found in it.
const BEGINNING_SHOWN: usize = 160;

// A piece of the key this long or longer is not passed on if the provider
// repeats it in its answer (see `key_hide`).
const KEY_PIECE: usize = 6;

// The pass that `secret_lend` and `trial_lend` ask for. What is inside the
// brackets is private to this file, so no other file can make one.
pub struct KeyPass(());

// How the provider took the key, as far as the number in its answer says.
// The meanings are the provider's own, from its documentation.
#[derive(Clone, Copy, PartialEq)]
pub enum KeyVerdict {
    // It answered the question (200): the key works.
    Works,
    // It does not know the key (401): mistyped, or past its expiry date.
    Unknown,
    // It knows the key, but did not answer with it: no credit is left (402),
    // or the key is held back by a limit of its own (403). Only when the
    // provider's reason can be read; a 403 page from somewhere on the way
    // says nothing about the key.
    Known,
    // The answer does not say: any other number, or no answer at all.
    NotTold,
}

// A tool the model asked for in its answer to a line: the tool's name, what
// the model gives it, as a text that is itself JSON, and whether that text
// was cut off, because the answer reached its limit of tokens or the text its
// bound. Both texts come from outside the kernel: the name is cleaned and the
// key is hidden in both, and the main loop checks them before anything is
// done (see `tools.rs`).
#[derive(Clone, PartialEq)]
pub struct ToolCall {
    pub name: String,
    pub inputs: String,
    pub cut_off: bool,
}

// What the model answered to a line typed in the chat box: its words, if it
// said any, cleaned, with the key hidden and cut at `WORDS_SHOWN` signs; the
// first tool it asked for, if it asked for one; and whether it asked for more
// than one.
pub struct ChatReply {
    pub words: Option<String>,
    pub tool: Option<ToolCall>,
    pub more: bool,
}

// Asks the model the question and says in one sentence how that went: what
// the model answered, why the provider turned the question down, or why no
// answer came; and how the provider took the key. Called by the network's
// task when it runs an errand; the sentence is the errand's answer. Words
// from outside in it were cleaned. With `trying`, the key that goes with the
// question is the one being tried at the onboarding (see `secret.rs`), not
// the one kept.
pub fn model_tell(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    trying: bool,
) -> (String, KeyVerdict) {
    // The key is borrowed once, into a room of this function's own, and that
    // copy serves the whole asking: it goes into the request, and it is what
    // is looked for in the answer afterwards. Borrowing is short that way,
    // and a new key typed while the answer is awaited changes nothing about
    // this asking. The room is wiped before this function ends.
    let mut key_room = [0u8; SECRET_LIMIT];
    let key_length = key_copy(trying, &mut key_room);
    let told = if key_length == 0 {
        (String::from("no answer came, because no key is kept"), KeyVerdict::NotTold)
    } else {
        question_ask(interface, card, sockets, name_server, &key_room[..key_length])
    };
    wipe(&mut key_room);
    told
}

// Sends a line typed in the chat box to the model, with the list of what the
// kernel can do for it (`tools`, the JSON that `chat_tools` in `tools.rs`
// made when the line was sent, or nothing for the last ask about a line), the
// record of what was said before it (`record`, from `conversation.rs`, empty
// when nothing was) and, when the model is asked about the line again, what
// came of it so far (`done`, empty for the line's first ask). Gives back what
// the kernel has to say about the answer in one sentence: nothing when the
// model answered as it should, otherwise why the provider turned the line
// down, why no answer came, or what was wrong with it. Beside it, what the
// model answered, the terminal's line about how many tokens that took, and
// the line as it was sent, with the key starred, which the conversation
// remembers; nothing when no request was put together. The key is the one
// that is kept, borrowed as for the fixed question. Called by the network's
// task when it runs an errand.
pub fn model_chat(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    line: &str,
    tools: &str,
    record: &str,
    done: &str,
) -> (String, Option<ChatReply>, Option<String>, Option<String>) {
    let mut key_room = [0u8; SECRET_LIMIT];
    let key_length = key_copy(false, &mut key_room);
    let told = if key_length == 0 {
        (String::from("no answer came, because no key is kept"), None, None, None)
    } else {
        chat_question_ask(interface, card, sockets, name_server, &key_room[..key_length], line, tools, record, done)
    };
    wipe(&mut key_room);
    told
}

// Asks the model to write an app, and says in one sentence how that went:
// what the model wrote, or why it is no app, why the provider turned the
// question down, or why no answer came. Beside the sentence it gives back the
// script, if the model wrote one that passed the checks (see `apps.rs`), and
// the terminal's line about how many tokens the answer took. `wanted` is the
// request the model gave with the tool `make_app`. The key is the one that is
// kept, borrowed as for the fixed question. Called by the network's task when
// it runs an errand.
pub fn model_app(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    wanted: &str,
) -> (String, Option<String>, Option<String>) {
    let mut key_room = [0u8; SECRET_LIMIT];
    let key_length = key_copy(false, &mut key_room);
    let told = if key_length == 0 {
        (String::from("no answer came, because no key is kept"), None, None)
    } else {
        app_question_ask(interface, card, sockets, name_server, &key_room[..key_length], wanted)
    };
    wipe(&mut key_room);
    told
}

// Borrows the key into `room`, a room of the caller's own, and says how many
// signs it has: none when no key is kept. With `trying`, the key is the one
// being tried at the onboarding. The caller wipes the room when it is done.
fn key_copy(trying: bool, room: &mut [u8; SECRET_LIMIT]) -> usize {
    let mut length = 0;
    let mut borrower = |key: &[u8]| {
        length = key.len().min(SECRET_LIMIT);
        room[..length].copy_from_slice(&key[..length]);
    };
    if trying {
        trial_lend(&KeyPass(()), &mut borrower);
    } else {
        secret_lend(&KeyPass(()), &mut borrower);
    }
    length
}

// The fixed question, with the key in hand.
fn question_ask(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    key: &[u8],
) -> (String, KeyVerdict) {
    // What is asked, the JSON way. `json_text` puts each text in quotes and
    // takes care of signs that have a meaning of their own in JSON.
    // `"stream":false` asks for the whole answer in one piece, not word by
    // word as it is written.
    let body = format!(
        "{{\"model\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}],\"max_tokens\":{},\"stream\":false}}",
        json_text(MODEL_NAME),
        json_text(QUESTION),
        ANSWER_TOKENS
    );
    match provider_exchange(interface, card, sockets, name_server, key, &body) {
        Err(sentence) => (sentence, KeyVerdict::NotTold),
        Ok((answer, whole)) => answer_sentence(&answer, whole, key),
    }
}

// A line typed in the chat box, with the key in hand. The request holds two
// messages: first the instruction text, as the "system" message, which tells
// a model how to behave before it reads what it is asked, with the record of
// what was said before the line behind it; then the line, as the "user"
// message, as it was typed. Behind them comes the list of tools: what the
// kernel can do when the model asks for it. When the model is asked about
// the line again (see `chat.rs`), the instruction text goes on with what came
// of the line so far, behind `AGAIN_LEAD`; the last such ask goes without the
// list of tools, and says so (`LAST_ASK`). The key goes to the provider in
// the notes only: a key typed into a line by mistake, or remembered in the
// record, is starred in both before they go, as in the provider's answer
// (see `key_hide`).
fn chat_question_ask(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    key: &[u8],
    line: &str,
    tools: &str,
    record: &str,
    done: &str,
) -> (String, Option<ChatReply>, Option<String>, Option<String>) {
    let sent = key_starred(line, key);
    let mut told = String::from(CHAT_INSTRUCTIONS);
    if !record.is_empty() {
        told.push_str(RECORD_LEAD);
        told.push_str(&key_starred(record, key));
    }
    if !done.is_empty() {
        told.push_str(AGAIN_LEAD);
        told.push_str(&key_starred(done, key));
    }
    let offered = if tools.is_empty() {
        told.push_str(LAST_ASK);
        String::new()
    } else {
        format!(",\"tools\":{}", tools)
    };
    let body = format!(
        "{{\"model\":{},\"messages\":[{{\"role\":\"system\",\"content\":{}}},{{\"role\":\"user\",\"content\":{}}}]{},\"max_tokens\":{},\"stream\":false}}",
        json_text(MODEL_NAME),
        json_text(&told),
        json_text(&sent),
        offered,
        LINE_TOKENS
    );
    match provider_exchange(interface, card, sockets, name_server, key, &body) {
        Err(sentence) => (sentence, None, None, Some(sent)),
        Ok((answer, whole)) => {
            let (sentence, reply) = chat_reply(&answer, whole, key);
            (sentence, reply, answer_tokens(&answer), Some(sent))
        }
    }
}

// A text of the kernel's that goes to the provider, with a star over every
// piece of the key in it (see `key_hide`). A line typed in the chat box and
// the remembered rows hold plain signs only, one byte each, and a key's signs
// are plain too, so the stars leave proper text.
fn key_starred(text: &str, key: &[u8]) -> String {
    let mut signs = text.as_bytes().to_vec();
    key_hide(&mut signs, key);
    String::from_utf8_lossy(&signs).into_owned()
}

// A text of plain signs from an app, with a star over every piece of the key
// that is kept: what an app left behind, before it is remembered and goes to
// the model with the line it answers (see `chat_remember` in `chat.rs`). An
// app cannot read the key, but the model may have written it into the
// script in pieces too short to be starred there, which the app then puts
// together. The key is borrowed as for a question, and wiped after.
pub fn key_starred_kept(text: &str) -> String {
    let mut key_room = [0u8; SECRET_LIMIT];
    let key_length = key_copy(false, &mut key_room);
    let starred = key_starred(text, &key_room[..key_length]);
    wipe(&mut key_room);
    starred
}

// The request for an app, with the key in hand. It holds two messages: first
// the instruction text, as the "system" message, which tells a model how to
// behave before it reads what it is asked; then the request, as the "user"
// message, with `APP_LEAD` in front of it.
fn app_question_ask(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    key: &[u8],
    wanted: &str,
) -> (String, Option<String>, Option<String>) {
    let body = format!(
        "{{\"model\":{},\"messages\":[{{\"role\":\"system\",\"content\":{}}},{{\"role\":\"user\",\"content\":{}}}],\"max_tokens\":{},\"stream\":false}}",
        json_text(MODEL_NAME),
        json_text(APP_INSTRUCTIONS),
        json_text(&format!("{}{}", APP_LEAD, wanted)),
        APP_TOKENS
    );
    match provider_exchange(interface, card, sockets, name_server, key, &body) {
        Err(sentence) => (sentence, None, None),
        Ok((answer, whole)) => {
            let (sentence, script) = app_sentence(&answer, whole, key);
            (sentence, script, answer_tokens(&answer))
        }
    }
}

// One exchange with the provider: the request is put together around `body`
// with the key, sent, and the answer collected whole. Gives back the answer
// and whether the provider said, through the encrypted link, that it had sent
// everything; or the sentence that says why no answer came that can be read.
fn provider_exchange(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    key: &[u8],
    body: &str,
) -> Result<(Vec<u8>, bool), String> {
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
        Err(reason) => Err(format!("no answer came, because {}", reason)),
        Ok(_) if too_long => Err(String::from("no answer came that I could read, because the provider's answer is larger than the room for it")),
        Ok(whole) => Ok((answer, whole)),
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

// Says in one sentence what the provider's answer holds, and how the
// provider took the key. `whole` says whether the provider said, through the
// encrypted link, that it had sent everything. `key` is the key that went
// with the question: it is kept out of the words that are passed on.
fn answer_sentence(answer: &[u8], whole: bool, key: &[u8]) -> (String, KeyVerdict) {
    if answer.is_empty() {
        return ("no answer came, because the provider sent nothing".into(), KeyVerdict::NotTold);
    }
    let Some(parts) = answer_parts(answer) else {
        return (
            "no answer came that I could read, because what the provider sent does not begin as an answer on the web does".into(),
            KeyVerdict::NotTold,
        );
    };
    let cut_short = if whole { "" } else { " Its answer did not come whole." };

    if parts.number == 200 {
        return (model_sentence(parts.body, key, cut_short), KeyVerdict::Works);
    }

    // Any other number means the question was not answered. A number from
    // 500 on says the trouble is on the provider's side, or the model's; any
    // other says the provider turned the question down. The provider says
    // why in the body, in one of these places.
    let what = if (500..600).contains(&parts.number) { "the provider could not answer" } else { "the provider turned the question down" };
    let places: [&[Step]; 3] = [&[Step::Name("error"), Step::Name("message")], &[Step::Name("error")], &[Step::Name("message")]];
    for path in places {
        if let Ok(words) = json_find_text(parts.body, path) {
            let verdict = match parts.number {
                401 => KeyVerdict::Unknown,
                402 | 403 => KeyVerdict::Known,
                _ => KeyVerdict::NotTold,
            };
            return (format!("{} ({}): \"{}\".{}", what, parts.number, words_shown(&words, key), cut_short), verdict);
        }
    }
    // No reason could be read. A 401 still says that the key is not known;
    // a 402 or 403 without the provider's reason may come from somewhere on
    // the way, and says nothing about the key.
    let verdict = if parts.number == 401 { KeyVerdict::Unknown } else { KeyVerdict::NotTold };
    (format!("{} ({}), and I could not read why.{}", what, parts.number, cut_short), verdict)
}

// The places in a good answer's body that are read, from the provider's
// documentation. The model's words are at choices, the first of them,
// message, content. The documentation allows a second form there: a list of
// pieces, whose first holds the text. How the answer ended is at choices,
// the first of them, finish_reason.
const WORDS: &[Step<'static>] = &[Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("content")];
const FIRST_PIECE: &[Step<'static>] =
    &[Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("content"), Step::Place(0), Step::Name("text")];
const ENDING: &[Step<'static>] = &[Step::Name("choices"), Step::Place(0), Step::Name("finish_reason")];

// A model that thinks before it answers may send what it thought beside its
// words, in one of these places. It is only looked at to say whether it is
// there; it is never shown.
const THOUGHTS: [&[Step<'static>]; 2] = [
    &[Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("reasoning_content")],
    &[Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("reasoning")],
];

// Says in one sentence what the body of a good answer (the number 200)
// holds: the model's words, and whether its answer was cut off or held back.
fn model_sentence(body: &[u8], key: &[u8], cut_short: &str) -> String {
    // How the answer ended. Two ways need saying: "length", the answer
    // reached the limit of tokens, and "content_filter", the provider held
    // something back. Any other way, or none, counts as an ordinary end.
    // What stands there is compared and never said itself.
    let ending = json_find_text(body, ENDING).ok();
    let out_of_room = ending.as_deref() == Some("length");
    let held_back = ending.as_deref() == Some("content_filter");

    // The model's words, without the spaces and line ends before and after.
    let found = model_words(body);
    let words = match &found {
        Ok(words) => Ok(words.trim()),
        Err(reason) => Err(*reason),
    };

    match words {
        Ok(words) if !words.is_empty() => {
            let said = words_shown(words, key);
            if out_of_room {
                format!("the model answered \"{}\", but it was cut off at the limit of {} tokens.{}", said, ANSWER_TOKENS, cut_short)
            } else if held_back {
                format!("the model answered \"{}\", but the provider held part of it back.{}", said, cut_short)
            } else {
                format!("the model answered \"{}\".{}", said, cut_short)
            }
        }
        // No words: an empty text, or a text of nothing but spaces.
        Ok(_) => empty_sentence(body, out_of_room, held_back, cut_short, ANSWER_TOKENS),
        // Something else where the words belong (`null`, say), or nothing
        // there at all. That counts as an answer with no words only if the
        // answer also says how it ended: that text is read with the check
        // that the rest of the answer closes properly, which finding
        // something that is not a text does not make.
        Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => empty_sentence(body, out_of_room, held_back, cut_short, ANSWER_TOKENS),
        Err(reason) => words_not_found(body, key, reason, cut_short),
    }
}

// Says in one sentence what the answer to the request for an app holds, and
// gives back the script if the model wrote one that can be used: one that
// came whole, that `app_script` in `apps.rs` takes out of the model's words
// and accepts, and in which the key is hidden like in every other word from
// the provider. Any answer but a good one (the number 200) is said exactly as
// for the fixed question.
fn app_sentence(answer: &[u8], whole: bool, key: &[u8]) -> (String, Option<String>) {
    let Some(parts) = answer_parts(answer).filter(|parts| parts.number == 200) else {
        return (answer_sentence(answer, whole, key).0, None);
    };
    let body = parts.body;
    let cut_short = if whole { "" } else { " Its answer did not come whole." };

    // How the answer ended, read as for the fixed question.
    let ending = json_find_text(body, ENDING).ok();
    let out_of_room = ending.as_deref() == Some("length");
    let held_back = ending.as_deref() == Some("content_filter");

    let found = model_words(body);
    let words = match &found {
        Ok(words) => Ok(words.trim()),
        Err(reason) => Err(*reason),
    };
    match words {
        // A script that was cut off at the limit, or held back in part by
        // the provider, is not whole, and is not taken.
        Ok(words) if !words.is_empty() && out_of_room => {
            (format!("the model's app was cut off at the limit of {} tokens, so it is not whole.{}", APP_TOKENS, cut_short), None)
        }
        Ok(words) if !words.is_empty() && held_back => {
            (format!("the provider held part of the model's app back, so it is not whole.{}", cut_short), None)
        }
        Ok(words) if !words.is_empty() => match app_script(words) {
            Ok(script) => {
                let mut signs = script.into_bytes();
                key_hide(&mut signs, key);
                // Only signs of the key, which are plain signs, became stars,
                // so the text is still proper text.
                let script = String::from_utf8_lossy(&signs).into_owned();
                let lines = script.lines().count();
                let sentence =
                    format!("the model wrote an app of {} {}. It is shown in the terminal.{}", lines, if lines == 1 { "line" } else { "lines" }, cut_short);
                (sentence, Some(script))
            }
            Err(reason) => (format!("the model's answer is no app, because {}.{}", reason, cut_short), None),
        },
        Ok(_) => (empty_sentence(body, out_of_room, held_back, cut_short, APP_TOKENS), None),
        Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => (empty_sentence(body, out_of_room, held_back, cut_short, APP_TOKENS), None),
        Err(reason) => (words_not_found(body, key, reason, cut_short), None),
    }
}

// The places in a good answer's body where a tool the model asks for stands,
// from the provider's documentation: a list of tool calls in the message,
// beside its words or in their place. Each names a tool and gives it what it
// needs, as a text that is itself JSON. Only the first is done; whether there
// is a second is only looked at.
const TOOL_NAME: &[Step<'static>] =
    &[Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("tool_calls"), Step::Place(0), Step::Name("function"), Step::Name("name")];
const TOOL_INPUTS: &[Step<'static>] = &[
    Step::Name("choices"),
    Step::Place(0),
    Step::Name("message"),
    Step::Name("tool_calls"),
    Step::Place(0),
    Step::Name("function"),
    Step::Name("arguments"),
];
const SECOND_TOOL: &[Step<'static>] =
    &[Step::Name("choices"), Step::Place(0), Step::Name("message"), Step::Name("tool_calls"), Step::Place(1), Step::Name("function"), Step::Name("name")];

// The most signs of a tool's name that are kept, and the most bytes of what
// the model gives the tool. Every tool of this kernel's has a short name and
// needs a few words at most, but for the table that `draw_table` is given;
// what is longer is given to the tool as nothing, and a table is cut off at
// its bound.
const TOOL_NAME_LONGEST: usize = 64;
const TOOL_INPUTS_LONGEST: usize = 1024;
const TABLE_INPUTS_LONGEST: usize = 4096;

// Says what the kernel has to say about the answer to a line typed in the
// chat box, and gives back what the model answered: its words, the tool it
// asked for, or both. Nothing needs saying when the model answered as it
// should. An answer that was cut off or held back is said, and a good answer
// with neither words nor a tool in it is said as for the fixed question. Any
// answer but a good one (the number 200) is said exactly as for the fixed
// question, and holds nothing from the model.
fn chat_reply(answer: &[u8], whole: bool, key: &[u8]) -> (String, Option<ChatReply>) {
    let Some(parts) = answer_parts(answer).filter(|parts| parts.number == 200) else {
        return (answer_sentence(answer, whole, key).0, None);
    };
    let body = parts.body;
    let cut_short = if whole { "" } else { " Its answer did not come whole." };

    // How the answer ended, read as for the fixed question.
    let ending = json_find_text(body, ENDING).ok();
    let out_of_room = ending.as_deref() == Some("length");
    let held_back = ending.as_deref() == Some("content_filter");

    // The first tool the model asked for. Its name is cleaned like every word
    // from the provider. What it gives the tool is JSON, which cleaning would
    // spoil: it is only held to its bound, with the key hidden in it. A table
    // past its bound is cut there, and counts as cut off, as everything the
    // tool is given does when the answer reached its limit of tokens.
    let tool = json_find_text(body, TOOL_NAME).ok().map(|name| {
        let mut inputs = json_find_text(body, TOOL_INPUTS).unwrap_or_default().into_bytes();
        let mut cut_off = out_of_room;
        if name == "draw_table" {
            if inputs.len() > TABLE_INPUTS_LONGEST {
                inputs.truncate(TABLE_INPUTS_LONGEST);
                cut_off = true;
            }
        } else if inputs.len() > TOOL_INPUTS_LONGEST {
            inputs.clear();
        }
        key_hide(&mut inputs, key);
        // Only signs of the key, which are plain signs, became stars, so the
        // text is still proper text; a sign that the bound cut in two becomes
        // the sign for "unknown".
        ToolCall { name: words_cut(&name, key, TOOL_NAME_LONGEST), inputs: String::from_utf8_lossy(&inputs).into_owned(), cut_off }
    });
    let more = tool.is_some() && json_find_text(body, SECOND_TOOL).is_ok();

    // The model's words, without the spaces and line ends before and after.
    let found = model_words(body);
    let words = match &found {
        Ok(words) if !words.trim().is_empty() => Some(words_shown(words.trim(), key)),
        _ => None,
    };

    let sentence = if words.is_some() || tool.is_some() {
        if out_of_room {
            format!("the model's answer was cut off at the limit of {} tokens.{}", LINE_TOKENS, cut_short)
        } else if held_back {
            format!("the provider held part of the model's answer back.{}", cut_short)
        } else if !whole {
            String::from("the provider's answer did not come whole.")
        } else {
            String::new()
        }
    } else {
        match found {
            Ok(_) => empty_sentence(body, out_of_room, held_back, cut_short, LINE_TOKENS),
            Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => empty_sentence(body, out_of_room, held_back, cut_short, LINE_TOKENS),
            Err(reason) => words_not_found(body, key, reason, cut_short),
        }
    };
    (sentence, Some(ChatReply { words, tool, more }))
}

// The places in a good answer's body that say how many tokens it took, which
// is what the provider is paid for: those of the question; how many of them
// the provider had kept from an earlier question, which costs far less (the
// model's maker and the provider name two places for that); those of the
// answer; and how many of them went on thinking.
const TOKENS_IN: &[Step<'static>] = &[Step::Name("usage"), Step::Name("prompt_tokens")];
const TOKENS_REPEATED: [&[Step<'static>]; 2] = [
    &[Step::Name("usage"), Step::Name("prompt_cache_hit_tokens")],
    &[Step::Name("usage"), Step::Name("prompt_tokens_details"), Step::Name("cached_tokens")],
];
const TOKENS_OUT: &[Step<'static>] = &[Step::Name("usage"), Step::Name("completion_tokens")];
const TOKENS_THINKING: &[Step<'static>] = &[Step::Name("usage"), Step::Name("completion_tokens_details"), Step::Name("reasoning_tokens")];

// The terminal's line about how many tokens a good answer (the number 200)
// took; nothing for any other answer.
fn answer_tokens(answer: &[u8]) -> Option<String> {
    let parts = answer_parts(answer).filter(|parts| parts.number == 200)?;
    let body = parts.body;
    let (Ok(asked), Ok(answered)) = (json_find_number(body, TOKENS_IN), json_find_number(body, TOKENS_OUT)) else {
        return Some(String::from("Tokens: the provider did not say how many this answer took"));
    };
    let mut line = format!("Tokens: {} in", asked);
    if let Some(repeated) = TOKENS_REPEATED.iter().find_map(|path| json_find_number(body, path).ok()) {
        line.push_str(&format!(", {} of them repeated", repeated));
    }
    line.push_str(&format!("; {} out", answered));
    if let Ok(thinking) = json_find_number(body, TOKENS_THINKING) {
        line.push_str(&format!(", {} of them thinking", thinking));
    }
    Some(line)
}

// The model's words in the body of a good answer: the text at `WORDS`, or
// the first piece of a list there.
fn model_words(body: &[u8]) -> Result<String, &'static str> {
    match json_find_text(body, WORDS) {
        Err(NOT_A_TEXT) => json_find_text(body, FIRST_PIECE).map_err(|_| NOT_A_TEXT),
        other => other,
    }
}

// The sentence for a good answer in which the model's words cannot be found:
// the answer has another shape than the provider's documentation describes.
// Its beginning is said too, cleaned and with the key hidden, so that the
// shape can be seen without asking again.
fn words_not_found(body: &[u8], key: &[u8], reason: &str, cut_short: &str) -> String {
    let beginning = words_cut(&String::from_utf8_lossy(body), key, BEGINNING_SHOWN);
    let shown = if beginning.is_empty() { String::new() } else { format!(" It begins \"{}\".", beginning) };
    format!("the provider answered, but I could not find the model's words in its answer, because {}.{}{}", reason, shown, cut_short)
}

// The sentence for a good answer that holds no words, with the reason if
// the answer gives one. `tokens` is the limit the question was asked with.
fn empty_sentence(body: &[u8], out_of_room: bool, held_back: bool, cut_short: &str, tokens: usize) -> String {
    let thought = THOUGHTS.iter().any(|path| json_find_text(body, path).map(|text| !text.trim().is_empty()).unwrap_or(false));
    let why = if out_of_room && thought {
        format!(", because it spent all of its {} tokens thinking", tokens)
    } else if out_of_room {
        format!(", because it reached the limit of {} tokens", tokens)
    } else if held_back {
        String::from(", because the provider held it back")
    } else {
        String::new()
    };
    format!("the model's answer was empty{}.{}", why, cut_short)
}

// ---------- Words from outside ----------

// Makes words that came from the provider fit to be said: cleaned like every
// text from outside, with the key hidden in them, and cut at `WORDS_SHOWN`
// signs.
fn words_shown(words: &str, key: &[u8]) -> String {
    words_cut(words, key, WORDS_SHOWN)
}

// The same, cut at `longest` signs. The key is hidden before the cut, so
// that the cut cannot leave the beginning of the key standing at the end.
// Only the signs that are said, and as many behind them as the key is long,
// are cleaned and searched: a piece of the key that begins among the signs
// that are said ends among those.
fn words_cut(words: &str, key: &[u8], longest: usize) -> String {
    let mut signs = plain_text(words, longest.saturating_add(key.len())).into_bytes();
    key_hide(&mut signs, key);
    signs.truncate(longest);
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
