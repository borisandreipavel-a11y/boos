//! Receives the provider's chat event stream. Holds partial answers in the
//! network task and hands only safe previews to the main loop.

use super::{
    ANSWER_ROOM, ANSWER_TOKENS, ChatReply, KEY_PIECE, MODEL_SITE, MODEL_WAIT, TABLE_INPUTS_MOST, WORDS_SHOWN,
    answer_parts, answer_tokens, chat_reply, empty_answer, key_hide, key_starred, line_bare, provider_request,
    table_input, tokens_line, tool_call, words_shown,
};
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use smoltcp::iface::{Interface, SocketSet};
use smoltcp::wire::Ipv4Address;

use crate::errand::{ChatProgress, errand_progress};
use crate::json::{NOT_THERE, Step, json_find_number, json_find_text, json_find_value};
use crate::network::Card;
use crate::page::{plain_text, site_exchange_while};
use crate::secret::wipe;

pub(super) fn ask(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    key: &[u8],
    body: &str,
) -> (String, Option<ChatReply>, Option<String>) {
    let mut request = provider_request(key, body, "1.1");
    let mut response = Response::default();
    let result = site_exchange_while(interface, card, sockets, name_server, MODEL_SITE, &request, MODEL_WAIT, &mut |bytes| {
        response.take(bytes, key)
    });
    wipe(&mut request);

    if matches!(response.input, Input::Events(_)) {
        return response.events.finish(key);
    }
    match result {
        Err(reason) => (format!("no answer came, because {}", reason), None, None),
        Ok(_) if response.too_long => (
            String::from("no answer came that I could read, because the provider's answer is larger than the room for it"),
            None,
            None,
        ),
        Ok(whole) => {
            let (sentence, reply) = chat_reply(&response.buffer, whole, key);
            (sentence, reply, answer_tokens(&response.buffer))
        }
    }
}

#[derive(Default)]
enum Input {
    #[default]
    Head,
    Whole,
    Events(Body),
}

#[derive(Default)]
struct Response {
    input: Input,
    buffer: Vec<u8>,
    events: Events,
    too_long: bool,
}

impl Response {
    fn take(&mut self, mut bytes: &[u8], key: &[u8]) -> bool {
        while matches!(self.input, Input::Head) {
            let Some((&byte, rest)) = bytes.split_first() else { return true };
            bytes = rest;
            if self.buffer.len() == ANSWER_ROOM {
                self.too_long = true;
                return false;
            }
            self.buffer.push(byte);
            if byte == b'\n' && (self.buffer.ends_with(b"\n\r\n") || self.buffer.ends_with(b"\n\n")) {
                self.input = match event_body(&self.buffer) {
                    Ok(Some(body)) => Input::Events(body),
                    Ok(None) => Input::Whole,
                    Err(reason) => {
                        self.events.fail(reason);
                        self.input = Input::Events(Body::Plain(None));
                        return false;
                    }
                };
            }
        }
        let Input::Events(body) = &mut self.input else {
            if self.buffer.len() + bytes.len() > ANSWER_ROOM {
                self.too_long = true;
                return false;
            }
            self.buffer.extend_from_slice(bytes);
            return true;
        };
        let more = body.take(bytes, &mut self.events);
        if more {
            self.events.publish(key);
        }
        more
    }
}

// HTTP headers are complete here. Plain JSON answers still use the
// existing buffered reader, including HTTP errors before the stream.
fn event_body(head: &[u8]) -> Result<Option<Body>, &'static str> {
    if !answer_parts(head).is_some_and(|parts| parts.number == 200) {
        return Ok(None);
    }
    let mut event = false;
    let mut encoding = None;
    let mut length = None;
    for line in head.split(|&byte| byte == b'\n').skip(1).map(line_bare) {
        let Some(colon) = line.iter().position(|&byte| byte == b':') else { continue };
        let name = &line[..colon];
        let value = line[colon + 1..].trim_ascii();
        if name.eq_ignore_ascii_case(b"content-type") {
            event = value.split(|&byte| byte == b';').next()
                .is_some_and(|kind| kind.trim_ascii().eq_ignore_ascii_case(b"text/event-stream"));
        } else if name.eq_ignore_ascii_case(b"transfer-encoding") {
            encoding = Some(value);
        } else if name.eq_ignore_ascii_case(b"content-length") {
            length = Some(core::str::from_utf8(value).ok().and_then(|value| value.parse::<usize>().ok()));
        }
    }
    if !event {
        return Ok(None);
    }
    if let Some(encoding) = encoding {
        if encoding.eq_ignore_ascii_case(b"chunked") {
            return Ok(Some(Body::Chunked(Chunked::default())));
        }
        return Err("the provider used a transfer encoding the kernel could not read");
    }
    let length = length.map(|length| length.ok_or("the provider sent an invalid stream length")).transpose()?;
    Ok(Some(Body::Plain(length)))
}

enum Body {
    Plain(Option<usize>),
    Chunked(Chunked),
}

impl Body {
    fn take(&mut self, bytes: &[u8], events: &mut Events) -> bool {
        match self {
            Self::Plain(Some(length)) => {
                let taken = bytes.len().min(*length);
                *length -= taken;
                events.take(&bytes[..taken]) && *length > 0
            }
            Self::Plain(None) => events.take(bytes),
            Self::Chunked(chunks) => chunks.take(bytes, events),
        }
    }
}

const CHUNK_LINE_MOST: usize = 1024;

#[derive(Default)]
enum ChunkPart {
    #[default]
    Size,
    Data(usize),
    Return,
    Newline,
}

#[derive(Default)]
struct Chunked {
    line: Vec<u8>,
    part: ChunkPart,
}

impl Chunked {
    fn take(&mut self, mut bytes: &[u8], events: &mut Events) -> bool {
        while let Some((&first, rest)) = bytes.split_first() {
            match self.part {
                ChunkPart::Size if first == b'\n' => {
                    let Some(size) = self.size() else { break };
                    if size == 0 {
                        return false;
                    }
                    self.part = ChunkPart::Data(size);
                    bytes = rest;
                }
                ChunkPart::Size if self.line.len() < CHUNK_LINE_MOST => {
                    self.line.push(first);
                    bytes = rest;
                }
                ChunkPart::Data(left) => {
                    let used = bytes.len().min(left);
                    if !events.take(&bytes[..used]) {
                        return false;
                    }
                    self.part = if left == used { ChunkPart::Return } else { ChunkPart::Data(left - used) };
                    bytes = &bytes[used..];
                }
                ChunkPart::Return if first == b'\r' => {
                    self.part = ChunkPart::Newline;
                    bytes = rest;
                }
                ChunkPart::Newline if first == b'\n' => {
                    self.part = ChunkPart::Size;
                    bytes = rest;
                }
                _ => break,
            }
        }
        if bytes.is_empty() {
            true
        } else {
            events.fail("the provider sent an invalid HTTP chunk");
            false
        }
    }

    fn size(&mut self) -> Option<usize> {
        let line = core::mem::take(&mut self.line);
        let size = line.strip_suffix(b"\r")?.split(|&byte| byte == b';').next()?;
        if size.is_empty() || !size.iter().all(u8::is_ascii_hexdigit) {
            return None;
        }
        usize::from_str_radix(core::str::from_utf8(size).ok()?, 16).ok()
    }
}

#[derive(Default)]
struct Events {
    line: Vec<u8>,
    words: String,
    tool: Option<String>,
    inputs: String,
    inputs_too_long: bool,
    more_tools: bool,
    thought: bool,
    ending: Option<String>,
    tokens: Option<String>,
    done: bool,
    error: Option<String>,
    last_preview: Option<ChatProgress>,
    preview_dirty: bool,
}

impl Events {
    fn take(&mut self, bytes: &[u8]) -> bool {
        for piece in bytes.split_inclusive(|&byte| byte == b'\n') {
            if self.line.len() + piece.len() > ANSWER_ROOM {
                self.fail("the provider sent a stream event larger than the room for it");
                return false;
            }
            self.line.extend_from_slice(piece);
            if piece.ends_with(b"\n") {
                let mut line = core::mem::take(&mut self.line);
                if let Some(data) = line.trim_ascii_end().strip_prefix(b"data:") {
                    if data.trim_ascii() == b"[DONE]" {
                        self.done = true;
                        return false;
                    }
                    if let Err(reason) = self.event(data.trim_ascii_start()) {
                        self.fail(reason);
                    }
                }
                line.clear();
                self.line = line;
                if self.error.is_some() {
                    return false;
                }
            }
        }
        true
    }

    fn event(&mut self, event: &[u8]) -> Result<(), &'static str> {
        const BAD_EVENT: &str = "the provider sent an unreadable stream event";
        let event = json_find_value(event, &[]).map_err(|_| BAD_EVENT)?;
        if !event.starts_with(b"{") {
            return Err(BAD_EVENT);
        }
        if let Ok(error) = json_find_value(event, &[Step::Name("error")]) {
            if error != b"null" {
                self.error = Some(json_find_text(error, &[Step::Name("message")])
                    .unwrap_or_else(|_| String::from("the provider reported an error")));
                return Ok(());
            }
        }
        if json_find_number(event, super::TOKENS_IN).is_ok() {
            self.tokens = Some(tokens_line(event));
        }

        let choice = match json_find_value(event, &[Step::Name("choices"), Step::Place(0)]) {
            Ok(choice) => choice,
            Err(NOT_THERE) => return Ok(()),
            Err(_) => return Err(BAD_EVENT),
        };
        if let Ok(ending) = json_find_text(choice, &[Step::Name("finish_reason")]) {
            self.ending = Some(ending);
        }
        let Ok(delta) = json_find_value(choice, &[Step::Name("delta")]) else { return Ok(()) };
        if let Ok(text) = json_find_text(delta, &[Step::Name("content")]) {
            if self.words.len() + text.len() > ANSWER_ROOM {
                return Err("the model's streamed text was larger than the room for it");
            }
            self.words.push_str(&text);
            self.preview_dirty |= !text.is_empty();
        }
        self.thought |= json_find_text(delta, &[Step::Name("reasoning_content")])
            .is_ok_and(|text| !text.trim().is_empty());
        if let Ok(calls) = json_find_value(delta, &[Step::Name("tool_calls")]) {
            self.tools(calls)?;
        }
        Ok(())
    }

    fn tools(&mut self, calls: &[u8]) -> Result<(), &'static str> {
        const MAX_CALLS_PER_EVENT: usize = 16;
        const BAD_TOOL: &str = "the provider sent an unreadable streamed tool call";
        if calls == b"null" {
            return Ok(());
        }
        for place in 0..MAX_CALLS_PER_EVENT {
            let call = match json_find_value(calls, &[Step::Place(place)]) {
                Ok(call) => call,
                Err(NOT_THERE) => return Ok(()),
                Err(_) => return Err(BAD_TOOL),
            };
            let index = json_find_number(call, &[Step::Name("index")]).map_err(|_| BAD_TOOL)?;
            if index != 0 {
                self.more_tools = true;
                continue;
            }
            let Ok(function) = json_find_value(call, &[Step::Name("function")]) else { continue };
            if let Ok(name) = json_find_text(function, &[Step::Name("name")]) {
                if !name.is_empty() {
                    if self.tool.as_ref().is_some_and(|old| *old != name) {
                        return Err(BAD_TOOL);
                    }
                    self.tool = Some(name);
                    self.preview_dirty = true;
                }
            }
            if let Ok(arguments) = json_find_text(function, &[Step::Name("arguments")]) {
                if self.inputs.len() + arguments.len() > TABLE_INPUTS_MOST {
                    self.inputs_too_long = true;
                    self.inputs.clear();
                }
                if !self.inputs_too_long {
                    self.inputs.push_str(&arguments);
                }
                self.preview_dirty |= !arguments.is_empty();
            }
        }
        // Already recorded any other calls in the usual, bounded prefix.
        // Reject an extra one since it could carry a conflicting first tool.
        if json_find_value(calls, &[Step::Place(MAX_CALLS_PER_EVENT)]).is_ok() {
            return Err("the provider sent too many streamed tool calls at once");
        }
        Ok(())
    }

    fn fail(&mut self, reason: &str) {
        self.error = Some(String::from(reason));
    }

    fn publish(&mut self, key: &[u8]) {
        if !core::mem::take(&mut self.preview_dirty) || self.ending.as_deref() == Some("content_filter") {
            return;
        }
        // Hold back enough signs for a key fragment that spans two events.
        // Sanitise the joined prefix before dropping the held-back signs.
        let tail = KEY_PIECE.min(key.len()).saturating_sub(1);
        let mut words = plain_text(self.words.trim_start(), WORDS_SHOWN + tail).into_bytes();
        let show = words.len().saturating_sub(tail);
        key_hide(&mut words, key);
        words.truncate(show);
        let words = String::from_utf8(words).ok().filter(|words| !words.is_empty());

        let table = if self.tool.as_deref() == Some("draw_table") && !self.inputs_too_long {
            let (text, _) = table_input(&self.inputs, true);
            text.rfind('\n').map(|end| key_starred(&text[..=end], key))
        } else {
            None
        };
        let progress = ChatProgress { words, table };
        if self.last_preview.as_ref() != Some(&progress) &&
            (self.last_preview.is_some() || progress.words.is_some() || progress.table.is_some())
        {
            self.last_preview = Some(progress.clone());
            errand_progress(progress);
        }
    }

    fn finish(self, key: &[u8]) -> (String, Option<ChatReply>, Option<String>) {
        let out_of_room = self.ending.as_deref() == Some("length");
        let held_back = self.ending.as_deref() == Some("content_filter");
        let whole = self.done && self.error.is_none();
        let normal_end = matches!(self.ending.as_deref(), Some("stop" | "tool_calls"));
        let cut_draw = out_of_room && self.tool.as_deref() == Some("draw_table");
        let valid_inputs = json_find_value(self.inputs.as_bytes(), &[]).is_ok_and(|value| value.starts_with(b"{"));
        let tool_incomplete = whole && normal_end && self.tool.is_some() && !valid_inputs;
        let tool = if whole && ((normal_end && valid_inputs) || cut_draw) {
            self.tool.map(|name| tool_call(name, self.inputs, out_of_room, out_of_room, key))
        } else {
            None
        };
        let words = self.words.trim();
        let words = (!held_back && !words.is_empty()).then(|| words_shown(words, key));
        let sentence = if let Some(error) = self.error {
            format!("the provider's stream ended with an error: {}.", words_shown(&error, key))
        } else if !whole {
            String::from("the provider's stream ended before the answer was complete.")
        } else if matches!(self.ending.as_deref(), Some("aborted" | "insufficient_system_resource")) {
            String::from("the provider stopped the model's answer early.")
        } else if tool_incomplete {
            String::from("the model's streamed tool call was incomplete.")
        } else if words.is_none() && tool.is_none() {
            empty_answer(out_of_room, held_back, self.thought, "", ANSWER_TOKENS)
        } else if out_of_room {
            format!("the model's answer was cut off at the limit of {} tokens.", ANSWER_TOKENS)
        } else {
            String::new()
        };
        let reply = ChatReply { words, more: tool.is_some() && self.more_tools, tool };
        (sentence, Some(reply), Some(self.tokens.unwrap_or_else(|| tokens_line(&[]))))
    }
}
