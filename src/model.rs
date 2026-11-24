//! Asking the model: one question goes to the provider, a service on the
//! internet that passes it on to a model, and the answer comes back as text.
//! The question is a line typed in the chat box, sent with the list of what
//! the kernel can do (see `tools.rs`) and the record of what was said before
//! it (see `conversation.rs`), whose answer is the model's words or a tool it
//! asks for; a request for an app, whose answer is a script (see
//! `apps.rs`); or the one fixed question, with which a key typed at the
//! onboarding is tried. The provider wants a key with every question, which
//! is the secret that the person at the machine typed. This is the one file
//! that may borrow that secret, and it sends it only to the site of the
//! provider it belongs to, over an encrypted link. There are two providers,
//! OrcaRouter and Anthropic, one in use at a time (see `onboarding.rs`); each
//! has a form of its own for the question and the answer. The answer to a
//! line is asked for piece by piece, as the model writes it, and what of its
//! words has come is handed on as it comes (see `errand.rs`); every other
//! answer is collected whole.
//! Notes: `docs/model.md`, `docs/tools.md`, `docs/apps.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

use smoltcp::iface::{Interface, SocketSet};
use smoltcp::wire::Ipv4Address;

use crate::apps::{APP_INSTRUCTIONS, APP_LEAD, app_script};
use crate::errand::errand_grow;
use crate::json::{NOT_A_TEXT, NOT_THERE, Step, json_find_number, json_find_text, json_text};
use crate::tools::{AGAIN_LEAD, CHAT_INSTRUCTIONS, LAST_ASK, RECORD_LEAD, tools_anthropic};
use crate::network::Card;
use crate::page::{Head, HeadRead, HeadReader, Waits, plain_text, site_exchange};
use crate::secret::{SECRET_LIMIT, secret_lend, trial_lend, wipe};
use crate::timer::{TICKS, TICKS_PER_SECOND};

// The first provider's site, and the place on it where questions go.
pub const MODEL_SITE: &str = "api.orcarouter.ai";
const MODEL_PATH: &str = "/v1/chat/completions";

// The model that is asked there, by the name the provider knows it by.
const MODEL_NAME: &str = "deepseek/deepseek-v4.1-flash-1017";

// The second provider, Anthropic: its site, the place on it where questions
// go, the model that is asked there, and the version of its form of question
// and answer, which every question must name (from its documentation, read
// in November 2026).
pub const ANTHROPIC_SITE: &str = "api.anthropic.com";
const ANTHROPIC_PATH: &str = "/v1/messages";
const ANTHROPIC_MODEL: &str = "claude-haiku-5-5";
const ANTHROPIC_VERSION: &str = "2026-10-21";

// The providers the kernel can ask. Each has a site, a form of question and of
// answer, and a key of its own; one is in use at a time, and a key goes only
// to the site of the provider it belongs to (see `secret.rs`).
#[derive(Clone, Copy, PartialEq)]
pub enum Provider {
    // OrcaRouter, which passes questions on to many models, in the form many
    // providers share ("chat completions").
    OrcaRouter,
    // Anthropic, which makes the model it is asked about, in a form of its own
    // ("messages").
    Anthropic,
}

impl Provider {
    // The provider's site: where its questions go, and the name its
    // certificate must be made out to.
    pub fn site(self) -> &'static str {
        match self {
            Provider::OrcaRouter => MODEL_SITE,
            Provider::Anthropic => ANTHROPIC_SITE,
        }
    }

    // The provider's name, as the kernel says it.
    pub fn named(self) -> &'static str {
        match self {
            Provider::OrcaRouter => "OrcaRouter",
            Provider::Anthropic => "Anthropic",
        }
    }
}

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
// first tool it asked for, if it asked for one; whether it asked for more
// than one; whether its answer broke off before its end, when it came piece
// by piece; and for such an answer the terminal's line about how its pieces
// came.
pub struct ChatReply {
    pub words: Option<String>,
    pub tool: Option<ToolCall>,
    pub more: bool,
    pub broken: bool,
    pub stream: Option<String>,
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
    // this asking. The provider the key belongs to comes with it, in the same
    // moment, and decides where the question goes and in which form. The room
    // is wiped before this function ends.
    let mut key_room = [0u8; SECRET_LIMIT];
    let (provider, key_length) = key_copy(trying, &mut key_room);
    let told = if key_length == 0 {
        (String::from("no answer came, because no key is kept"), KeyVerdict::NotTold)
    } else {
        question_ask(interface, card, sockets, name_server, provider, &key_room[..key_length])
    };
    wipe(&mut key_room);
    told
}

// Sends a line typed in the chat box to the model, with the list of what the
// kernel can do for it (`tools`, the JSON that `chat_tools` in `tools.rs`
// made when the line was sent, or nothing for the last ask about a line), the
// record of what was said before it (`record`, from `conversation.rs`, empty
// when nothing was), what the model is told about the open document
// (`document`, from `documents.rs`, empty while none is open) and, when the
// model is asked about the line again, what came of it so far (`done`, empty
// for the line's first ask). Gives back what
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
    document: &str,
    done: &str,
) -> (String, Option<ChatReply>, Option<String>, Option<String>) {
    let mut key_room = [0u8; SECRET_LIMIT];
    let (provider, key_length) = key_copy(false, &mut key_room);
    let told = if key_length == 0 {
        (String::from("no answer came, because no key is kept"), None, None, None)
    } else {
        chat_question_ask(interface, card, sockets, name_server, provider, &key_room[..key_length], line, tools, record, document, done)
    };
    wipe(&mut key_room);
    told
}

// Asks the model to write an app, and says in one sentence how that went:
// what the model wrote, or why it is no app, why the provider turned the
// question down, or why no answer came. Beside the sentence it gives back the
// script, if the model wrote one that passed the checks (see `apps.rs`), and
// the terminal's line about how many tokens the answer took. `wanted` is the
// request the model gave with the tool `make_app`, with the app's inputs
// below it, if it has any (`app_wanted` in `apps.rs`). The key is the one that is
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
    let (provider, key_length) = key_copy(false, &mut key_room);
    let told = if key_length == 0 {
        (String::from("no answer came, because no key is kept"), None, None)
    } else {
        app_question_ask(interface, card, sockets, name_server, provider, &key_room[..key_length], wanted)
    };
    wipe(&mut key_room);
    told
}

// Borrows the key into `room`, a room of the caller's own, and says which
// provider it belongs to and how many signs it has: none when no key is kept.
// With `trying`, the key is the one being tried at the onboarding. The caller
// wipes the room when it is done.
fn key_copy(trying: bool, room: &mut [u8; SECRET_LIMIT]) -> (Provider, usize) {
    let mut length = 0;
    let mut owner = Provider::OrcaRouter;
    let mut borrower = |provider: Provider, key: &[u8]| {
        owner = provider;
        length = key.len().min(SECRET_LIMIT);
        room[..length].copy_from_slice(&key[..length]);
    };
    if trying {
        trial_lend(&KeyPass(()), &mut borrower);
    } else {
        secret_lend(&KeyPass(()), &mut borrower);
    }
    (owner, length)
}

// The fixed question, with the key in hand.
fn question_ask(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    provider: Provider,
    key: &[u8],
) -> (String, KeyVerdict) {
    // What is asked, the JSON way. `json_text` puts each text in quotes and
    // takes care of signs that have a meaning of their own in JSON.
    // `"stream":false` asks for the whole answer in one piece, not word by
    // word as it is written. Anthropic's form names the longest answer first;
    // the question is the same.
    let body = match provider {
        Provider::OrcaRouter => format!(
            "{{\"model\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}],\"max_tokens\":{},\"stream\":false}}",
            json_text(MODEL_NAME),
            json_text(QUESTION),
            ANSWER_TOKENS
        ),
        Provider::Anthropic => format!(
            "{{\"model\":{},\"max_tokens\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}],\"stream\":false}}",
            json_text(ANTHROPIC_MODEL),
            ANSWER_TOKENS,
            json_text(QUESTION)
        ),
    };
    match provider_exchange(interface, card, sockets, name_server, provider, key, &body, None) {
        Err(sentence) => (sentence, KeyVerdict::NotTold),
        Ok((answer, whole)) => answer_sentence(provider, &answer, whole, key),
    }
}

// A line typed in the chat box, with the key in hand. The request holds two
// messages: first the instruction text, as the "system" message, which tells
// a model how to behave before it reads what it is asked, with what it is
// told about the open document behind it, and the record of what was said
// before the line behind that; then the line, as the "user"
// message, as it was typed. Behind them comes the list of tools: what the
// kernel can do when the model asks for it. When the model is asked about
// the line again (see `chat.rs`), the instruction text goes on with what came
// of the line so far, behind `AGAIN_LEAD`; the last such ask goes without the
// list of tools, and says so (`LAST_ASK`). The key goes to the provider in
// the notes only: a key typed into a line by mistake, or remembered in the
// record, is starred in both before they go, as in the provider's answer
// (see `key_hide`). The answer is asked for piece by piece as the model
// writes it ("stream"), with the tokens it took in its last piece
// ("include_usage"), and read so as it comes (see "Reading an answer piece by
// piece" below); an answer that comes whole all the same is read as before.
// Anthropic's form holds the same texts in other places: the instruction text
// is its own part ("system") beside one message, the line; each tool is
// written in its form (`tools_anthropic`); and its answer always comes with the
// tokens it took.
fn chat_question_ask(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    provider: Provider,
    key: &[u8],
    line: &str,
    tools: &str,
    record: &str,
    document: &str,
    done: &str,
) -> (String, Option<ChatReply>, Option<String>, Option<String>) {
    let sent = key_starred(line, key);
    let mut told = String::from(CHAT_INSTRUCTIONS);
    // The open document comes before the record: while it does not change,
    // the beginning of the request stays the same from line to line.
    if !document.is_empty() {
        told.push_str(&key_starred(document, key));
    }
    if !record.is_empty() {
        told.push_str(RECORD_LEAD);
        told.push_str(&key_starred(record, key));
    }
    if !done.is_empty() {
        told.push_str(AGAIN_LEAD);
        told.push_str(&key_starred(done, key));
    }
    let tools = match provider {
        Provider::OrcaRouter => Some(String::from(tools)),
        Provider::Anthropic if tools.is_empty() => Some(String::new()),
        Provider::Anthropic => tools_anthropic(tools),
    };
    // The list of tools is the kernel's own, written by `chat_tools`; one that
    // cannot be put into Anthropic's form is a mistake in the kernel, and is
    // said as such rather than sent.
    let Some(tools) = tools else {
        let sentence = "no answer came, because I could not put the list of tools into the provider's form";
        return (String::from(sentence), None, None, Some(sent));
    };
    let offered = if tools.is_empty() {
        told.push_str(LAST_ASK);
        String::new()
    } else {
        format!(",\"tools\":{}", tools)
    };
    let body = match provider {
        Provider::OrcaRouter => format!(
            "{{\"model\":{},\"messages\":[{{\"role\":\"system\",\"content\":{}}},{{\"role\":\"user\",\"content\":{}}}]{},\"max_tokens\":{},\"stream\":true,\"stream_options\":{{\"include_usage\":true}}}}",
            json_text(MODEL_NAME),
            json_text(&told),
            json_text(&sent),
            offered,
            LINE_TOKENS
        ),
        Provider::Anthropic => format!(
            "{{\"model\":{},\"max_tokens\":{},\"system\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}]{},\"stream\":true}}",
            json_text(ANTHROPIC_MODEL),
            LINE_TOKENS,
            json_text(&told),
            json_text(&sent),
            offered
        ),
    };
    let mut stream = Stream::new(provider);
    let exchanged = provider_exchange(interface, card, sockets, name_server, provider, key, &body, Some(&mut stream));
    if stream.chunked {
        let sentence = "no answer came that I could read, because the provider sent its answer in pieces with their lengths in between (\"chunked\"), which it should not for this kind of request";
        return (String::from(sentence), None, None, Some(sent));
    }
    if stream.begun {
        let (sentence, reply, tokens) = stream_reply(&stream, key);
        return (sentence, Some(reply), Some(tokens), Some(sent));
    }
    match exchanged {
        Err(sentence) => (sentence, None, None, Some(sent)),
        Ok((answer, whole)) => {
            let (sentence, reply) = chat_reply(provider, &answer, whole, key);
            (sentence, reply, answer_tokens(provider, &answer), Some(sent))
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
    let (_, key_length) = key_copy(false, &mut key_room);
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
    provider: Provider,
    key: &[u8],
    wanted: &str,
) -> (String, Option<String>, Option<String>) {
    let body = match provider {
        Provider::OrcaRouter => format!(
            "{{\"model\":{},\"messages\":[{{\"role\":\"system\",\"content\":{}}},{{\"role\":\"user\",\"content\":{}}}],\"max_tokens\":{},\"stream\":false}}",
            json_text(MODEL_NAME),
            json_text(APP_INSTRUCTIONS),
            json_text(&format!("{}{}", APP_LEAD, wanted)),
            APP_TOKENS
        ),
        Provider::Anthropic => format!(
            "{{\"model\":{},\"max_tokens\":{},\"system\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}],\"stream\":false}}",
            json_text(ANTHROPIC_MODEL),
            APP_TOKENS,
            json_text(APP_INSTRUCTIONS),
            json_text(&format!("{}{}", APP_LEAD, wanted))
        ),
    };
    match provider_exchange(interface, card, sockets, name_server, provider, key, &body, None) {
        Err(sentence) => (sentence, None, None),
        Ok((answer, whole)) => {
            let (sentence, script) = app_sentence(provider, &answer, whole, key);
            (sentence, script, answer_tokens(provider, &answer))
        }
    }
}

// One exchange with the provider: the request is put together around `body`
// with the key, sent, and the answer collected whole. Gives back the answer
// and whether the provider said, through the encrypted link, that it had sent
// everything; or the sentence that says why no answer came that can be read.
// For a line, `stream` is given: the head of the answer is read as it comes,
// and when it says that the answer comes piece by piece, the pieces go to
// `stream` as they come, and nothing is collected (see `Stream` below).
fn provider_exchange(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    provider: Provider,
    key: &[u8],
    body: &str,
    mut stream: Option<&mut Stream>,
) -> Result<(Vec<u8>, bool), String> {
    // The request, in the web's own language: "POST" hands something in, at
    // the place named behind it. Then come lines of notes: which site is
    // meant, what form the body has, how many bytes long it is, that the
    // connection may be closed after the answer, and the key. An empty line
    // ends the notes, and the body follows. OrcaRouter takes the key in the
    // note `Authorization`; Anthropic in a note of its own, `x-api-key`, after
    // the version of its form, which every question to it must name.
    let head = match provider {
        Provider::OrcaRouter => format!(
            "POST {} HTTP/1.0\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nAuthorization: Bearer ",
            MODEL_PATH,
            MODEL_SITE,
            body.len()
        ),
        Provider::Anthropic => format!(
            "POST {} HTTP/1.0\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nanthropic-version: {}\r\nx-api-key: ",
            ANTHROPIC_PATH,
            ANTHROPIC_SITE,
            body.len(),
            ANTHROPIC_VERSION
        ),
    };

    // The request holds the key, so it is put together in a room that is
    // large enough from the start: a list that has to grow moves, and would
    // leave a copy of the key behind. The room is wiped when the request has
    // been sent, however the sending went.
    let mut request: Vec<u8> = Vec::with_capacity(head.len() + key.len() + 4 + body.len());
    request.extend_from_slice(head.as_bytes());
    request.extend_from_slice(key);
    request.extend_from_slice(b"\r\n\r\n");
    request.extend_from_slice(body.as_bytes());

    // The answer is collected whole, up to the room there is for it, unless
    // it is a line's, and its head says that it comes piece by piece.
    let mut answer: Vec<u8> = Vec::new();
    let mut too_long = false;
    let mut head = HeadReader::new();
    let mut head_over = false;
    let result = site_exchange(interface, card, sockets, name_server, provider.site(), &request, Waits::one(MODEL_WAIT), &mut |bytes| {
        if let Some(stream) = stream.as_deref_mut() {
            if stream.begun {
                return stream.take(bytes, key);
            }
            if !head_over {
                match head.take(bytes) {
                    HeadRead::More => {}
                    HeadRead::Wrong(_) => head_over = true,
                    HeadRead::Done(found, body_from) => {
                        head_over = true;
                        if stream.begins(&found) {
                            return stream.take(bytes.get(body_from..).unwrap_or(&[]), key);
                        }
                    }
                }
            }
        }
        if answer.len() + bytes.len() <= ANSWER_ROOM {
            answer.extend_from_slice(bytes);
        } else {
            too_long = true;
        }
        true
    });
    wipe(&mut request);

    match result {
        Err(reason) => {
            // Something went wrong after the pieces had begun to come: what
            // came of them stands, and the reason goes with it.
            if let Some(stream) = stream {
                stream.trouble = Some(reason.clone());
            }
            Err(format!("no answer came, because {}", reason))
        }
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
// with the question: it is kept out of the words that are passed on. A good
// answer is read in its provider's form; a refusal is read the same way for
// both, since both put their reason at `error`, `message`.
fn answer_sentence(provider: Provider, answer: &[u8], whole: bool, key: &[u8]) -> (String, KeyVerdict) {
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
        let sentence = match provider {
            Provider::OrcaRouter => model_sentence(parts.body, key, cut_short),
            Provider::Anthropic => anthropic_sentence(parts.body, key, cut_short),
        };
        return (sentence, KeyVerdict::Works);
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
fn app_sentence(provider: Provider, answer: &[u8], whole: bool, key: &[u8]) -> (String, Option<String>) {
    let Some(parts) = answer_parts(answer).filter(|parts| parts.number == 200) else {
        return (answer_sentence(provider, answer, whole, key).0, None);
    };
    let body = parts.body;
    let cut_short = if whole { "" } else { " Its answer did not come whole." };
    if provider == Provider::Anthropic {
        return anthropic_app_sentence(body, key, cut_short);
    }

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
        Ok(words) if !words.is_empty() => app_taken(words, key, cut_short),
        Ok(_) => (empty_sentence(body, out_of_room, held_back, cut_short, APP_TOKENS), None),
        Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => (empty_sentence(body, out_of_room, held_back, cut_short, APP_TOKENS), None),
        Err(reason) => (words_not_found(body, key, reason, cut_short), None),
    }
}

// The model's words in a whole answer to the request for an app, taken as a
// script if `app_script` in `apps.rs` accepts it, with the key hidden in it.
fn app_taken(words: &str, key: &[u8], cut_short: &str) -> (String, Option<String>) {
    match app_script(words) {
        Ok(script) => {
            let mut signs = script.into_bytes();
            key_hide(&mut signs, key);
            // Only signs of the key, which are plain signs, became stars, so
            // the text is still proper text.
            let script = String::from_utf8_lossy(&signs).into_owned();
            let lines = script.lines().count();
            let sentence = format!("the model wrote an app of {} {}. It is shown in the terminal.{}", lines, if lines == 1 { "line" } else { "lines" }, cut_short);
            (sentence, Some(script))
        }
        Err(reason) => (format!("the model's answer is no app, because {}.{}", reason, cut_short), None),
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
// needs a few words at most, but for an app's inputs with their values, which
// come to about 1,070 bytes at the most the kernel takes (see
// `app_inputs.rs`), and for the table that `draw_table` is given; what is
// longer is given to the tool as nothing, and a table is cut off at its
// bound.
const TOOL_NAME_LONGEST: usize = 64;
const TOOL_INPUTS_LONGEST: usize = 2048;
const TABLE_INPUTS_LONGEST: usize = 4096;

// Says what the kernel has to say about the answer to a line typed in the
// chat box, and gives back what the model answered: its words, the tool it
// asked for, or both. Nothing needs saying when the model answered as it
// should. An answer that was cut off or held back is said, and a good answer
// with neither words nor a tool in it is said as for the fixed question. Any
// answer but a good one (the number 200) is said exactly as for the fixed
// question, and holds nothing from the model.
fn chat_reply(provider: Provider, answer: &[u8], whole: bool, key: &[u8]) -> (String, Option<ChatReply>) {
    let Some(parts) = answer_parts(answer).filter(|parts| parts.number == 200) else {
        return (answer_sentence(provider, answer, whole, key).0, None);
    };
    let body = parts.body;
    let cut_short = if whole { "" } else { " Its answer did not come whole." };
    if provider == Provider::Anthropic {
        return anthropic_chat_reply(body, whole, key, cut_short);
    }

    // How the answer ended, read as for the fixed question.
    let ending = json_find_text(body, ENDING).ok();
    let out_of_room = ending.as_deref() == Some("length");
    let held_back = ending.as_deref() == Some("content_filter");

    // The first tool the model asked for. See `tool_made`.
    let tool = json_find_text(body, TOOL_NAME)
        .ok()
        .map(|name| tool_made(&name, json_find_text(body, TOOL_INPUTS).unwrap_or_default().into_bytes(), out_of_room, key));
    let more = tool.is_some() && json_find_text(body, SECOND_TOOL).is_ok();

    // The model's words, without the spaces and line ends before and after.
    let found = model_words(body);
    let words = match &found {
        Ok(words) if !words.trim().is_empty() => Some(words_shown(words.trim(), key)),
        _ => None,
    };

    let sentence = if words.is_some() || tool.is_some() {
        ending_said(out_of_room, held_back, whole, cut_short)
    } else {
        match found {
            Ok(_) => empty_sentence(body, out_of_room, held_back, cut_short, LINE_TOKENS),
            Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => empty_sentence(body, out_of_room, held_back, cut_short, LINE_TOKENS),
            Err(reason) => words_not_found(body, key, reason, cut_short),
        }
    };
    (sentence, Some(ChatReply { words, tool, more, broken: false, stream: None }))
}

// The tool the model asked for, made fit to be checked (see `tools.rs`): its
// name is cleaned like every word from the provider. What it gives the tool
// is JSON, which cleaning would spoil: it is only held to its bound, with the
// key hidden in it. A table past its bound is cut there, and counts as cut
// off, as everything the tool is given does when the answer reached its limit
// of tokens (`cut_off`) or broke off.
fn tool_made(name: &str, mut inputs: Vec<u8>, mut cut_off: bool, key: &[u8]) -> ToolCall {
    if name == "draw_table" {
        if inputs.len() > TABLE_INPUTS_LONGEST {
            inputs.truncate(TABLE_INPUTS_LONGEST);
            cut_off = true;
        }
    } else if inputs.len() > TOOL_INPUTS_LONGEST {
        inputs.clear();
    }
    key_hide(&mut inputs, key);
    // Only signs of the key, which are plain signs, became stars, so the text
    // is still proper text; a sign that the bound cut in two becomes the sign
    // for "unknown".
    ToolCall { name: words_cut(name, key, TOOL_NAME_LONGEST), inputs: String::from_utf8_lossy(&inputs).into_owned(), cut_off }
}

// What the kernel says about how an answer to a line with words or a tool in
// it ended: cut off at the limit, held back, not whole, or nothing.
fn ending_said(out_of_room: bool, held_back: bool, whole: bool, cut_short: &str) -> String {
    if out_of_room {
        format!("the model's answer was cut off at the limit of {} tokens.{}", LINE_TOKENS, cut_short)
    } else if held_back {
        format!("the provider held part of the model's answer back.{}", cut_short)
    } else if !whole {
        String::from("the provider's answer did not come whole.")
    } else {
        String::new()
    }
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
fn answer_tokens(provider: Provider, answer: &[u8]) -> Option<String> {
    let parts = answer_parts(answer).filter(|parts| parts.number == 200)?;
    Some(match provider {
        Provider::OrcaRouter => tokens_said(parts.body),
        Provider::Anthropic => anthropic_tokens_said(Some((parts.body, false)), Some(parts.body)),
    })
}

// The terminal's line about the tokens that `body` says an answer took: a
// good answer's body, or the piece of an answer that came piece by piece
// that holds the counts, where they stand in the same places.
fn tokens_said(body: &[u8]) -> String {
    let (Ok(asked), Ok(answered)) = (json_find_number(body, TOKENS_IN), json_find_number(body, TOKENS_OUT)) else {
        return String::from("Tokens: the provider did not say how many this answer took");
    };
    let mut line = format!("Tokens: {} in", asked);
    if let Some(repeated) = TOKENS_REPEATED.iter().find_map(|path| json_find_number(body, path).ok()) {
        line.push_str(&format!(", {} of them repeated", repeated));
    }
    line.push_str(&format!("; {} out", answered));
    if let Ok(thinking) = json_find_number(body, TOKENS_THINKING) {
        line.push_str(&format!(", {} of them thinking", thinking));
    }
    line
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
    empty_said(thought, out_of_room, held_back, cut_short, tokens)
}

// The same, for an answer of which it is known whether the model thought.
fn empty_said(thought: bool, out_of_room: bool, held_back: bool, cut_short: &str, tokens: usize) -> String {
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

// ---------- Anthropic's answers ----------

// A good answer in Anthropic's form (from its documentation, read in November
// 2026) holds a list of blocks at `content`, in the order the model wrote
// them: its thinking (`thinking`, whose text is left empty unless asked for,
// or `redacted_thinking`), its words (`text`, at `text`), and the tools it asks
// for (`tool_use`, with the tool's name at `name` and what it gives the tool at
// `input`, as JSON of its own). How it ended stands at `stop_reason`:
// `end_turn` and `tool_use` are ordinary ends; `max_tokens` is the limit of
// tokens; `model_context_window_exceeded` means the question and the answer
// grew larger than the model takes; `refusal` means the provider's checks
// stopped the answer. The counts stand at `usage`. Blocks are read by their
// kind, never by their place: thinking comes first.
const STOP_REASON: &[Step<'static>] = &[Step::Name("stop_reason")];

// How many blocks of an answer are looked at: far more than a model writes.
const BLOCKS_READ: usize = 16;

// What the kernel says when an answer of Anthropic's reached the model's
// context (`model_context_window_exceeded`), and when the provider's checks
// stopped it (`refusal`).
const WINDOW_WHY: &str = "because the question and the answer grew larger than the model takes";
const CHECKS_WHY: &str = "the provider's checks stopped";

// What the blocks of a good answer of Anthropic's hold: the words of its text
// blocks, in order; whether it had a text block at all; whether the model
// thought; the name of the first tool it asked for and how many it asked for;
// and why a block could not be read, if one could not.
struct Blocks {
    words: String,
    text: bool,
    thought: bool,
    tool: Option<String>,
    tools: usize,
    trouble: Option<&'static str>,
}

fn anthropic_blocks(body: &[u8]) -> Blocks {
    let mut blocks = Blocks { words: String::new(), text: false, thought: false, tool: None, tools: 0, trouble: None };
    for place in 0..BLOCKS_READ {
        let kind = json_find_text(body, &[Step::Name("content"), Step::Place(place), Step::Name("type")]);
        match kind.as_deref() {
            Ok("text") => match json_find_text(body, &[Step::Name("content"), Step::Place(place), Step::Name("text")]) {
                Ok(words) => {
                    blocks.words.push_str(&words);
                    blocks.text = true;
                }
                Err(reason) => {
                    blocks.trouble = Some(reason);
                    break;
                }
            },
            Ok("thinking" | "redacted_thinking") => blocks.thought = true,
            Ok("tool_use") => {
                blocks.tools += 1;
                if blocks.tool.is_none() {
                    blocks.tool = json_find_text(body, &[Step::Name("content"), Step::Place(place), Step::Name("name")]).ok();
                }
            }
            // A kind of block the kernel does not know is passed over.
            Ok(_) => {}
            Err(reason) if *reason == NOT_THERE => break,
            Err(reason) => {
                blocks.trouble = Some(reason);
                break;
            }
        }
    }
    blocks
}

// The sentence for the answer of Anthropic's to the fixed question, as
// `model_sentence` makes it for OrcaRouter's. An answer with no words counts as
// empty only if it says how it ended, which is read with the check that the
// rest of the answer closes properly, as for OrcaRouter's.
fn anthropic_sentence(body: &[u8], key: &[u8], cut_short: &str) -> String {
    let ending = json_find_text(body, STOP_REASON).ok();
    let blocks = anthropic_blocks(body);
    let words = blocks.words.trim();
    if blocks.text && !words.is_empty() {
        let said = words_shown(words, key);
        return match ending.as_deref() {
            Some("max_tokens") => format!("the model answered \"{}\", but it was cut off at the limit of {} tokens.{}", said, ANSWER_TOKENS, cut_short),
            Some("model_context_window_exceeded") => format!("the model answered \"{}\", but it was cut off, {}.{}", said, WINDOW_WHY, cut_short),
            Some("refusal") => format!("the model answered \"{}\", but {} it.{}", said, CHECKS_WHY, cut_short),
            _ => format!("the model answered \"{}\".{}", said, cut_short),
        };
    }
    if let Some(reason) = blocks.trouble {
        return words_not_found(body, key, reason, cut_short);
    }
    if ending.is_none() {
        return words_not_found(body, key, NOT_THERE, cut_short);
    }
    anthropic_empty(ending.as_deref(), blocks.thought, cut_short, ANSWER_TOKENS)
}

// The sentence for a good answer of Anthropic's with no words. `tokens` is the
// limit the question was asked with.
fn anthropic_empty(ending: Option<&str>, thought: bool, cut_short: &str, tokens: usize) -> String {
    match ending {
        Some("max_tokens") => empty_said(thought, true, false, cut_short, tokens),
        Some("model_context_window_exceeded") => format!("the model's answer was empty, {}.{}", WINDOW_WHY, cut_short),
        Some("refusal") => format!("the model's answer was empty, because {} it.{}", CHECKS_WHY, cut_short),
        _ => empty_said(thought, false, false, cut_short, tokens),
    }
}

// The sentence for the answer of Anthropic's to the request for an app, and
// the script, as `app_sentence` makes them for OrcaRouter's: a script that was
// cut off, or stopped by the provider's checks, is not whole, and is not taken.
fn anthropic_app_sentence(body: &[u8], key: &[u8], cut_short: &str) -> (String, Option<String>) {
    let ending = json_find_text(body, STOP_REASON).ok();
    let blocks = anthropic_blocks(body);
    let words = blocks.words.trim();
    if blocks.text && !words.is_empty() {
        return match ending.as_deref() {
            Some("max_tokens") => (format!("the model's app was cut off at the limit of {} tokens, so it is not whole.{}", APP_TOKENS, cut_short), None),
            Some("model_context_window_exceeded") => (format!("the model's app was cut off, {}, so it is not whole.{}", WINDOW_WHY, cut_short), None),
            Some("refusal") => (format!("{} the model's app, so it is not whole.{}", CHECKS_WHY, cut_short), None),
            _ => app_taken(words, key, cut_short),
        };
    }
    if let Some(reason) = blocks.trouble {
        return (words_not_found(body, key, reason, cut_short), None);
    }
    if ending.is_none() {
        return (words_not_found(body, key, NOT_THERE, cut_short), None);
    }
    (anthropic_empty(ending.as_deref(), blocks.thought, cut_short, APP_TOKENS), None)
}

// The answer of Anthropic's to a line when it came whole, though it was asked
// for piece by piece: its words are read. A tool asked for in it is not done:
// what the model gives a tool stands there as JSON of its own, which the
// kernel's reader does not hand out as a text, and the provider sends a
// line's answer piece by piece, as it is asked to, where it comes as a text.
fn anthropic_chat_reply(body: &[u8], whole: bool, key: &[u8], cut_short: &str) -> (String, Option<ChatReply>) {
    let ending = json_find_text(body, STOP_REASON).ok();
    let blocks = anthropic_blocks(body);
    let trimmed = blocks.words.trim();
    let words = if blocks.text && !trimmed.is_empty() { Some(words_shown(trimmed, key)) } else { None };
    let sentence = if blocks.tools > 0 {
        format!("the provider sent its answer whole, and a tool asked for in such an answer is not read.{}", cut_short)
    } else if words.is_some() {
        match ending.as_deref() {
            Some("max_tokens") => ending_said(true, false, whole, cut_short),
            Some("model_context_window_exceeded") => format!("the model's answer was cut off, {}.{}", WINDOW_WHY, cut_short),
            Some("refusal") => format!("{} the model's answer.{}", CHECKS_WHY, cut_short),
            _ => ending_said(false, false, whole, cut_short),
        }
    } else if let Some(reason) = blocks.trouble {
        words_not_found(body, key, reason, cut_short)
    } else if ending.is_none() {
        words_not_found(body, key, NOT_THERE, cut_short)
    } else {
        anthropic_empty(ending.as_deref(), blocks.thought, cut_short, LINE_TOKENS)
    };
    (sentence, Some(ChatReply { words, tool: None, more: false, broken: false, stream: None }))
}

// The terminal's line about the tokens an answer of Anthropic's took, in the
// same words as `tokens_said`. The counts of the question stand in `asked`, at
// `usage` in an answer that came whole, or at `message`, `usage` in the first
// piece of one that came piece by piece (`in_message`): those Anthropic counted
// afresh (`input_tokens`), and those it read from, or wrote to, what it kept
// from an earlier question (`cache_read_input_tokens`,
// `cache_creation_input_tokens`), which together are all of the question's;
// those read back count as repeated. The counts of the answer stand at `usage`
// in `answered`: `output_tokens`, and of them `output_tokens_details`,
// `thinking_tokens`.
fn anthropic_tokens_said(asked: Option<(&[u8], bool)>, answered: Option<&[u8]>) -> String {
    let asked_count = |name: &str| -> Option<u64> {
        let (json, in_message) = asked?;
        if in_message {
            json_find_number(json, &[Step::Name("message"), Step::Name("usage"), Step::Name(name)]).ok()
        } else {
            json_find_number(json, &[Step::Name("usage"), Step::Name(name)]).ok()
        }
    };
    let fresh = asked_count("input_tokens");
    let out = answered.and_then(|json| json_find_number(json, &[Step::Name("usage"), Step::Name("output_tokens")]).ok());
    let (Some(fresh), Some(out)) = (fresh, out) else {
        return String::from("Tokens: the provider did not say how many this answer took");
    };
    let read = asked_count("cache_read_input_tokens");
    let written = asked_count("cache_creation_input_tokens").unwrap_or(0);
    let all = fresh.saturating_add(read.unwrap_or(0)).saturating_add(written);
    let mut line = format!("Tokens: {} in", all);
    if let Some(read) = read {
        line.push_str(&format!(", {} of them repeated", read));
    }
    line.push_str(&format!("; {} out", out));
    let thinking = answered.and_then(|json| {
        json_find_number(json, &[Step::Name("usage"), Step::Name("output_tokens_details"), Step::Name("thinking_tokens")]).ok()
    });
    if let Some(thinking) = thinking {
        line.push_str(&format!(", {} of them thinking", thinking));
    }
    line
}

// ---------- Reading an answer piece by piece ----------

// The answer to a line is asked for piece by piece, as the model writes it.
// It comes as lines of text, from the provider's and the model's maker's
// documentation (read in November 2026): each piece on a line of its own that
// begins "data:", followed by JSON, with empty lines between them; the line
// "data: [DONE]" ends the answer. A line that begins ":" says only that the
// link is alive (the model's maker sends ": keep-alive" while a question
// waits), and is passed over, as is any other line. A piece holds a little:
// at `choices`, the first of them, `delta`, a few of the model's words
// (`content`), a little of its thinking (`reasoning_content`, or
// `reasoning`), or a part of a tool it asks for (`tool_calls`, each part with
// its place in the list of tools at `index`: the first part of a tool names
// it, the next ones bring pieces of what it gives the tool); the last says
// how the answer ended (`finish_reason`); and the last before "[DONE]" holds
// the tokens it took (`usage`), beside the rest or alone, with no choices. A
// piece with `error` in it says that the provider broke the answer off.
//
// Anthropic's answer comes in the same lines, with a line `event:` before each
// piece that names it; the piece names itself too, at `type`, and that is what
// is read (its documentation, read in November 2026). `message_start` holds the
// counts of the question; each block of the answer (see "Anthropic's answers"
// above) comes as `content_block_start`, which says its kind (and a tool's
// name), then `content_block_delta`s, which bring a little of it (`text_delta`,
// a few words at `text`; `thinking_delta`; `input_json_delta`, a piece of what
// the model gives a tool, at `partial_json`), then `content_block_stop`;
// `message_delta` says how it ended and holds the counts of the answer so far;
// and `message_stop` ends it, where OrcaRouter's ends at "[DONE]". `ping` only
// says that the link is alive, `error` breaks the answer off, and a piece of a
// kind not named here is passed over: Anthropic may add kinds.

// The most bytes one line of such an answer may take: far more than a piece
// with a few words, a part of a tool, or the counts, and the notes around
// them. A longer line stops the reading.
const PIECE_ROOM: usize = 64 * 1024;

// The most bytes of the model's words that are kept as they come, from the
// first that is not a space: far more than the signs that are said.
const WORDS_KEPT: usize = 16 * 1024;

// How many bytes of the beginning of such an answer are kept, to be said
// when nothing in it can be read.
const STREAM_BEGINNING: usize = 1024;

// How many parts of tools are looked for in one piece.
const TOOL_PARTS_READ: usize = 8;

// The places in a piece that are read, as in an answer that comes whole, but
// at `delta` instead of `message`; how the answer ended stands at `ENDING`,
// and the counts where `tokens_said` reads them.
const PIECE_WORDS: &[Step<'static>] = &[Step::Name("choices"), Step::Place(0), Step::Name("delta"), Step::Name("content")];
const PIECE_FIRST_PIECE: &[Step<'static>] =
    &[Step::Name("choices"), Step::Place(0), Step::Name("delta"), Step::Name("content"), Step::Place(0), Step::Name("text")];
const PIECE_THOUGHTS: [&[Step<'static>]; 2] = [
    &[Step::Name("choices"), Step::Place(0), Step::Name("delta"), Step::Name("reasoning_content")],
    &[Step::Name("choices"), Step::Place(0), Step::Name("delta"), Step::Name("reasoning")],
];

// Where a piece that breaks the answer off says why, as a refusal does, and
// two more places that only say that it does.
const BREAK_REASON: [&[Step<'static>]; 2] = [&[Step::Name("error"), Step::Name("message")], &[Step::Name("error")]];
const BREAK_KIND: &[Step<'static>] = &[Step::Name("error"), Step::Name("type")];
const BREAK_CODE: &[Step<'static>] = &[Step::Name("error"), Step::Name("code")];

// An answer to a line that comes piece by piece: what has come of it so far.
// The network's task fills it in as the pieces come (`take`), and hands on
// what of the words can be shown so far (`hand_on`); when the answer is over,
// `stream_reply` says what came of it.
struct Stream {
    // The provider whose form the pieces have.
    provider: Provider,
    // Whether the answer's head said that it comes piece by piece, and
    // whether it said too that it comes in pieces with their lengths in
    // between, which is not read.
    begun: bool,
    chunked: bool,
    // The line being collected, and the first bytes of the answer's body.
    line: Vec<u8>,
    beginning: Vec<u8>,
    // How many pieces came, and how many lines that only say that the link
    // is alive.
    pieces: usize,
    keep_alive: usize,
    // The model's words so far, from the first that is not a space, and
    // whether it thought.
    words: String,
    thought: bool,
    // The first tool asked for: its place in the list of tools, its name,
    // and what it gives the tool so far, held to the longest bound and a
    // byte; and whether the model asked for another one.
    tool_place: Option<u64>,
    tool_name: Option<String>,
    tool_inputs: Vec<u8>,
    more: bool,
    // How the answer ended, and the last piece that held the counts; for
    // Anthropic's, also the first piece, which holds those of the question,
    // and whether the answer reached the model's context or was stopped by the
    // provider's checks.
    ending: Option<String>,
    usage: Option<Vec<u8>>,
    usage_first: Option<Vec<u8>>,
    window: bool,
    checks: bool,
    // Whether a piece broke the answer off, and why; whether a line was too
    // long to read; whether "[DONE]" came; and what went wrong with the link
    // after the pieces had begun to come.
    failed: bool,
    error: Option<String>,
    too_long: bool,
    done: bool,
    trouble: Option<String>,
    // When the asking began, in ticks of the timer, and when things came,
    // in ticks from then: the last bytes, the first piece, the first
    // thinking, the first words, the parts of the tool, "[DONE]".
    started: u64,
    last_at: u64,
    first_at: Option<u64>,
    thinking_at: Option<u64>,
    words_at: Option<u64>,
    tool_from: Option<u64>,
    tool_to: Option<u64>,
    done_at: Option<u64>,
    // What was handed on last: the words that can be shown so far, and
    // whether the model was thinking before its first word.
    shown: String,
    shown_thinking: bool,
}

impl Stream {
    fn new(provider: Provider) -> Stream {
        Stream {
            provider,
            begun: false,
            chunked: false,
            line: Vec::new(),
            beginning: Vec::new(),
            pieces: 0,
            keep_alive: 0,
            words: String::new(),
            thought: false,
            tool_place: None,
            tool_name: None,
            tool_inputs: Vec::new(),
            more: false,
            ending: None,
            usage: None,
            usage_first: None,
            window: false,
            checks: false,
            failed: false,
            error: None,
            too_long: false,
            done: false,
            trouble: None,
            started: TICKS.load(Ordering::Relaxed),
            last_at: 0,
            first_at: None,
            thinking_at: None,
            words_at: None,
            tool_from: None,
            tool_to: None,
            done_at: None,
            shown: String::new(),
            shown_thinking: false,
        }
    }

    // Ticks since the asking began.
    fn now(&self) -> u64 {
        TICKS.load(Ordering::Relaxed).saturating_sub(self.started)
    }

    // Whether the answer whose head is `head` comes piece by piece: a good
    // answer (200) of the kind "text/event-stream", the provider's word for
    // it. Any other answer is collected whole, as every answer once was.
    fn begins(&mut self, head: &Head) -> bool {
        let piece_by_piece = head.number == 200 && head.content_type.as_deref().is_some_and(|kind| kind.starts_with("text/event-stream"));
        if piece_by_piece {
            self.begun = true;
            self.chunked = head.transfer_coding.is_some();
        }
        piece_by_piece
    }

    // Takes the next bytes of the answer's body, however the pieces are cut,
    // and hands on what of the words can be shown so far. Says whether more
    // is wanted: not after "[DONE]", which the link is told, nor after a line
    // too long to read, nor at all for an answer in pieces with their lengths
    // in between.
    fn take(&mut self, bytes: &[u8], key: &[u8]) -> bool {
        if self.chunked || self.done || self.too_long {
            return false;
        }
        if !bytes.is_empty() {
            self.last_at = self.now();
        }
        let room = STREAM_BEGINNING.saturating_sub(self.beginning.len()).min(bytes.len());
        self.beginning.extend_from_slice(&bytes[..room]);
        for byte in bytes {
            if *byte != b'\n' {
                if self.line.len() >= PIECE_ROOM {
                    self.too_long = true;
                    break;
                }
                self.line.push(*byte);
                continue;
            }
            let mut line = core::mem::take(&mut self.line);
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            self.line_read(&line);
            if self.done {
                break;
            }
        }
        self.hand_on(key);
        !self.done && !self.too_long
    }

    // One whole line of the answer.
    fn line_read(&mut self, line: &[u8]) {
        if line.first() == Some(&b':') {
            self.keep_alive += 1;
            return;
        }
        let Some(data) = line.strip_prefix(b"data:") else {
            return;
        };
        let data = data.strip_prefix(b" ").unwrap_or(data);
        if self.provider == Provider::Anthropic {
            self.anthropic_piece_read(data);
            return;
        }
        if data.trim_ascii() == b"[DONE]" {
            self.done = true;
            self.done_at = Some(self.now());
            return;
        }
        self.piece_read(data);
    }

    // One piece: JSON from outside, read with the JSON reader like every
    // answer. A piece that cannot be read gives nothing.
    fn piece_read(&mut self, piece: &[u8]) {
        let now = self.now();
        self.pieces += 1;
        self.first_at.get_or_insert(now);

        let reason = BREAK_REASON.iter().find_map(|path| json_find_text(piece, path).ok());
        if reason.is_some() || json_find_text(piece, BREAK_KIND).is_ok() || json_find_text(piece, BREAK_CODE).is_ok() || json_find_number(piece, BREAK_CODE).is_ok() {
            self.failed = true;
            if self.error.is_none() {
                self.error = reason;
            }
            return;
        }

        if let Ok(ending) = json_find_text(piece, ENDING) {
            self.ending = Some(ending);
        }
        if json_find_number(piece, TOKENS_IN).is_ok() || json_find_number(piece, TOKENS_OUT).is_ok() {
            self.usage = Some(piece.to_vec());
        }
        let words = match json_find_text(piece, PIECE_WORDS) {
            Err(NOT_A_TEXT) => json_find_text(piece, PIECE_FIRST_PIECE).ok(),
            found => found.ok(),
        };
        if let Some(words) = words {
            self.words_add(&words, now);
        }
        if PIECE_THOUGHTS.iter().any(|path| json_find_text(piece, path).is_ok_and(|text| !text.trim().is_empty())) {
            self.thought = true;
            self.thinking_at.get_or_insert(now);
        }

        // The parts of tools in the piece. Those of the first tool asked for
        // are put together; of any other, only whether it is there counts.
        for place in 0..TOOL_PARTS_READ {
            let index = json_find_number(
                piece,
                &[Step::Name("choices"), Step::Place(0), Step::Name("delta"), Step::Name("tool_calls"), Step::Place(place), Step::Name("index")],
            )
            .ok();
            let name = json_find_text(
                piece,
                &[
                    Step::Name("choices"),
                    Step::Place(0),
                    Step::Name("delta"),
                    Step::Name("tool_calls"),
                    Step::Place(place),
                    Step::Name("function"),
                    Step::Name("name"),
                ],
            )
            .ok();
            let inputs = json_find_text(
                piece,
                &[
                    Step::Name("choices"),
                    Step::Place(0),
                    Step::Name("delta"),
                    Step::Name("tool_calls"),
                    Step::Place(place),
                    Step::Name("function"),
                    Step::Name("arguments"),
                ],
            )
            .ok();
            if index.is_none() && name.is_none() && inputs.is_none() {
                break;
            }
            let first = *self.tool_place.get_or_insert(index.unwrap_or(0));
            if index.is_some_and(|index| index != first) {
                if name.is_some() {
                    self.more = true;
                }
                continue;
            }
            if self.tool_name.is_none() {
                self.tool_name = name;
            }
            if let Some(inputs) = inputs {
                let room = (TABLE_INPUTS_LONGEST + 1).saturating_sub(self.tool_inputs.len()).min(inputs.len());
                self.tool_inputs.extend_from_slice(&inputs.as_bytes()[..room]);
            }
            self.tool_from.get_or_insert(now);
            self.tool_to = Some(now);
        }
    }

    // One piece of an answer of Anthropic's: JSON from outside, read with the
    // JSON reader like every answer, by the kind it names at `type`. A piece
    // that cannot be read, or of a kind not named here, gives nothing.
    fn anthropic_piece_read(&mut self, piece: &[u8]) {
        let now = self.now();
        let kind = json_find_text(piece, &[Step::Name("type")]).unwrap_or_default();
        // A piece that only says that the link is alive is counted as such,
        // as OrcaRouter's lines that begin ":" are, and not as a piece.
        if kind == "ping" {
            self.keep_alive += 1;
            return;
        }
        self.pieces += 1;
        self.first_at.get_or_insert(now);
        let index = json_find_number(piece, &[Step::Name("index")]).ok();
        match kind.as_str() {
            "message_start" => {
                if json_find_number(piece, &[Step::Name("message"), Step::Name("usage"), Step::Name("input_tokens")]).is_ok() {
                    self.usage_first = Some(piece.to_vec());
                }
            }
            "content_block_start" => {
                let block = json_find_text(piece, &[Step::Name("content_block"), Step::Name("type")]).unwrap_or_default();
                match block.as_str() {
                    "thinking" | "redacted_thinking" => {
                        self.thought = true;
                        self.thinking_at.get_or_insert(now);
                    }
                    // The first tool asked for is put together; of any other,
                    // only that it is there counts. Its block holds an empty
                    // place for what it gives the tool, which comes in the
                    // pieces that follow.
                    "tool_use" if self.tool_place.is_none() => {
                        self.tool_place = Some(index.unwrap_or(0));
                        self.tool_name = json_find_text(piece, &[Step::Name("content_block"), Step::Name("name")]).ok();
                        self.tool_from.get_or_insert(now);
                        self.tool_to = Some(now);
                    }
                    "tool_use" => self.more = true,
                    _ => {}
                }
            }
            "content_block_delta" => {
                let delta = json_find_text(piece, &[Step::Name("delta"), Step::Name("type")]).unwrap_or_default();
                match delta.as_str() {
                    "text_delta" => {
                        if let Ok(words) = json_find_text(piece, &[Step::Name("delta"), Step::Name("text")]) {
                            self.words_add(&words, now);
                        }
                    }
                    "thinking_delta" => {
                        self.thought = true;
                        self.thinking_at.get_or_insert(now);
                    }
                    "input_json_delta" if self.tool_place.is_some() && index == self.tool_place => {
                        if let Ok(inputs) = json_find_text(piece, &[Step::Name("delta"), Step::Name("partial_json")]) {
                            let room = (TABLE_INPUTS_LONGEST + 1).saturating_sub(self.tool_inputs.len()).min(inputs.len());
                            self.tool_inputs.extend_from_slice(&inputs.as_bytes()[..room]);
                        }
                        self.tool_to = Some(now);
                    }
                    _ => {}
                }
            }
            "message_delta" => {
                // How it ended, in the words the rest of this file reads: the
                // limit of tokens is OrcaRouter's "length"; the model's
                // context and the provider's checks are noted apart.
                if let Ok(reason) = json_find_text(piece, &[Step::Name("delta"), Step::Name("stop_reason")]) {
                    self.window = reason == "model_context_window_exceeded";
                    self.checks = reason == "refusal";
                    self.ending = Some(if reason == "max_tokens" { String::from("length") } else { reason });
                }
                if json_find_number(piece, &[Step::Name("usage"), Step::Name("output_tokens")]).is_ok() {
                    self.usage = Some(piece.to_vec());
                }
            }
            "message_stop" => {
                self.done = true;
                self.done_at = Some(now);
            }
            "error" => {
                self.failed = true;
                if self.error.is_none() {
                    self.error = json_find_text(piece, &[Step::Name("error"), Step::Name("message")]).ok();
                }
            }
            _ => {}
        }
    }

    // Adds a few of the model's words, from the first that is not a space.
    fn words_add(&mut self, piece: &str, now: u64) {
        let piece = if self.words.is_empty() { piece.trim_start() } else { piece };
        if piece.is_empty() {
            return;
        }
        self.words_at.get_or_insert(now);
        let mut room = WORDS_KEPT.saturating_sub(self.words.len()).min(piece.len());
        while !piece.is_char_boundary(room) {
            room -= 1;
        }
        self.words.push_str(&piece[..room]);
    }

    // Hands on what of the words can be shown so far, and whether the model
    // is thinking before its first word, when either changed (see `errand.rs`).
    fn hand_on(&mut self, key: &[u8]) {
        let thinking = self.thought && self.words.is_empty();
        let mut changed = thinking != self.shown_thinking;
        if self.shown.len() < WORDS_SHOWN {
            let shown = words_so_far(&self.words, key);
            if shown != self.shown {
                self.shown = shown;
                changed = true;
            }
        }
        if changed {
            self.shown_thinking = thinking;
            errand_grow(&self.shown, thinking);
        }
    }

    // The terminal's line about how the pieces came: how many, and when,
    // counted from the asking.
    fn line_said(&self) -> String {
        let mut parts = Vec::new();
        if let Some(at) = self.first_at {
            parts.push(format!("the first after {}", seconds_said(at)));
        }
        if let Some(at) = self.thinking_at {
            parts.push(format!("thinking from {}", seconds_said(at)));
        }
        if let Some(at) = self.words_at {
            parts.push(format!("words from {}", seconds_said(at)));
        }
        if let (Some(from), Some(to)) = (self.tool_from, self.tool_to) {
            parts.push(format!("a tool from {} to {}", seconds_said(from), seconds_said(to)));
        }
        if self.keep_alive > 0 {
            parts.push(format!("{} {} that the link is alive", self.keep_alive, if self.keep_alive == 1 { "line" } else { "lines" }));
        }
        parts.push(match self.done_at {
            Some(at) => format!("the end mark after {}", seconds_said(at)),
            None => String::from("no end mark"),
        });
        let pieces = if self.pieces == 1 { "piece" } else { "pieces" };
        format!("Stream: {} {} in {}: {}.", self.pieces, pieces, seconds_said(self.last_at), parts.join(", "))
    }
}

// A count of ticks as seconds, to the hundredth.
fn seconds_said(ticks: u64) -> String {
    format!("{}.{:02} s", ticks / TICKS_PER_SECOND, ticks % TICKS_PER_SECOND * 100 / TICKS_PER_SECOND)
}

// What of the model's words can be shown while more of them may come:
// cleaned and with the key hidden, as `words_shown` makes them, but without
// the last signs, one fewer than the key is long. A piece of the key that a
// sign shown belongs to then lies whole among the signs that came, and is
// hidden; a piece that only begins among the last signs waits for the rest.
fn words_so_far(words: &str, key: &[u8]) -> String {
    let mut signs = plain_text(words, WORDS_SHOWN.saturating_add(key.len())).into_bytes();
    key_hide(&mut signs, key);
    let shown = signs.len().saturating_sub(key.len().saturating_sub(1)).min(WORDS_SHOWN);
    signs.truncate(shown);
    // Only plain signs are left, one byte each, so this cannot fail.
    String::from_utf8_lossy(&signs).into_owned()
}

// Says what the kernel has to say about an answer to a line that came piece
// by piece, and gives back what the model answered, as `chat_reply` does for
// one that came whole, and the terminal's line about its tokens. The answer
// is whole when "[DONE]" came after no piece that broke it off. It broke off
// when such a piece came, when the model's maker's word for how it ended
// says it was stopped ("aborted", "insufficient_system_resource"), when the
// link went wrong after the pieces had begun or a line was too long to read,
// and when it ended before the model said how it ended. Then the words that
// came are said, and why it broke off; a tool is not done, but for a table,
// whose rows that came whole are drawn (see `chat.rs`); and the line ends.
// Anthropic's answer is whole when `message_stop` came after no `error`. When
// its end says that the provider's checks stopped it, its words are said, and
// no tool is done, a table included: those checks can stop the answer in the
// middle of what the model gives a tool (its documentation says never to do
// the tools of such an answer). When it reached the model's context, it is
// read as one cut off at the limit, with a sentence of its own.
fn stream_reply(stream: &Stream, key: &[u8]) -> (String, ChatReply, String) {
    let ending = stream.ending.as_deref();
    let out_of_room = ending == Some("length") || stream.window;
    let held_back = ending == Some("content_filter") && stream.provider == Provider::OrcaRouter;
    let stopped = matches!(ending, Some("aborted" | "insufficient_system_resource")) && stream.provider == Provider::OrcaRouter;
    let whole = stream.done && !stream.failed;
    let broke = if let Some(reason) = &stream.trouble {
        Some(format!("the model's answer broke off, because {}", reason))
    } else if stream.failed {
        Some(match &stream.error {
            Some(reason) => format!("the provider broke the model's answer off: \"{}\"", words_shown(reason, key)),
            None => String::from("the provider broke the model's answer off, and I could not read why"),
        })
    } else if stream.too_long {
        Some(String::from("the model's answer broke off, because a piece of it is larger than the room for it"))
    } else if stopped {
        Some(String::from("the provider stopped the model's answer before its end"))
    } else if !stream.done && ending.is_none() {
        Some(String::from("the model's answer broke off before it was whole"))
    } else {
        None
    };
    let broken = broke.is_some();
    let checked = stream.checks && !broken;

    let tool = if checked {
        None
    } else {
        stream.tool_name.as_deref().map(|name| tool_made(name, stream.tool_inputs.clone(), out_of_room || broken, key))
    };
    let more = tool.is_some() && stream.more;
    let words = stream.words.trim_end();
    let words = if words.is_empty() { None } else { Some(words_shown(words, key)) };
    let cut_short = if whole { "" } else { " Its answer did not come whole." };

    let sentence = if let Some(broke) = broke {
        let undone = if tool.as_ref().is_some_and(|tool| tool.name != "draw_table") { ", so I did not do what it asked for" } else { "" };
        format!("{}{}.", broke, undone)
    } else if checked {
        let undone = if stream.tool_name.is_some() { ", so I did not do what it asked for" } else { "" };
        format!("{} the model's answer{}.{}", CHECKS_WHY, undone, cut_short)
    } else if stream.window && (words.is_some() || tool.is_some()) {
        format!("the model's answer was cut off, {}.{}", WINDOW_WHY, cut_short)
    } else if stream.window {
        format!("the model's answer was empty, {}.{}", WINDOW_WHY, cut_short)
    } else if words.is_some() || tool.is_some() {
        ending_said(out_of_room, held_back, whole, cut_short)
    } else if ending.is_some() {
        empty_said(stream.thought, out_of_room, held_back, cut_short, LINE_TOKENS)
    } else {
        words_not_found(&stream.beginning, key, NOT_THERE, cut_short)
    };
    let tokens = match (stream.provider, &stream.usage) {
        (Provider::OrcaRouter, Some(piece)) => tokens_said(piece),
        (Provider::Anthropic, _) => anthropic_tokens_said(stream.usage_first.as_deref().map(|piece| (piece, true)), stream.usage.as_deref()),
        (Provider::OrcaRouter, None) => String::from("Tokens: the provider did not say how many this answer took"),
    };
    (sentence, ChatReply { words, tool, more, broken, stream: Some(stream.line_said()) }, tokens)
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
