//! Fetching a file from the web for the person: an address read and checked,
//! one request to the site it names, and the answer read as it arrives: the
//! file, an address the site sends one on to, or why there is no file. One
//! such step, a hop, is one errand of the network's task (see `errand.rs`);
//! the main loop decides whether to go on to the next (see `files.rs`).
//! Notes: `docs/network.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use smoltcp::iface::{Interface, SocketSet};
use smoltcp::wire::Ipv4Address;

use crate::network::Card;
use crate::page::{Head, HeadRead, HeadReader, Length, Waits, site_exchange};
use crate::serial::serial_print;

// The largest file taken: 4 MB.
pub const FILE_MOST: usize = 4 * 1024 * 1024;

// The longest address taken, in signs.
const ADDRESS_MOST: usize = 1000;

// The longest name of a site, and of one of its parts between dots, in signs.
const SITE_NAME_MOST: usize = 253;
const SITE_PART_MOST: usize = 63;

// How long one hop may take, in seconds: the greeting and the first piece of
// the answer, and the whole answer.
const FIRST_WAIT: u64 = 15;
const WHOLE_WAIT: u64 = 180;

// How many signs of an address the terminal's line about a hop shows.
const ADDRESS_SHOWN: usize = 120;

// An address of a file on the web, read and checked: the site's name, in
// small letters, and what is asked of it there (its path and its query). What
// follows a # in an address is never sent, and is not kept.
#[derive(Clone, PartialEq)]
pub struct Address {
    pub site: String,
    pub path: String,
}

impl Address {
    // The address written out whole, as it is shown, compared and sent across
    // to the network's task.
    pub fn whole(&self) -> String {
        format!("https://{}{}", self.site, self.path)
    }

    // The last part of the path, without the query: the file's name as the
    // address gives it, which may be empty.
    pub fn last_part(&self) -> &str {
        let path = self.path.split('?').next().unwrap_or("");
        path.rsplit('/').next().unwrap_or("")
    }
}

// Reads an address that came from outside: from the model, or from a site
// that sends one on. Only an address of the web's encrypted kind is taken,
// on its usual port, with a site's name (not a number) and no name and
// password in it, of plain signs only and at most 1000 of them. What is
// wrong comes back in words that can follow "but" or "because".
pub fn address_read(text: &str) -> Result<Address, &'static str> {
    if text.len() > ADDRESS_MOST {
        return Err("it is longer than 1000 signs");
    }
    if text.is_empty() || !text.bytes().all(|byte| (b'!'..=b'~').contains(&byte)) {
        return Err("it holds signs an address may not have");
    }
    let Some(rest) = after_ignoring_case(text, "https://") else {
        return Err(if after_ignoring_case(text, "http://").is_some() {
            "it is not an encrypted address (https)"
        } else {
            "it is no address that begins with https://"
        });
    };
    // What follows a # stays on this side.
    let rest = rest.split('#').next().unwrap_or("");
    let end = rest.find(['/', '?']).unwrap_or(rest.len());
    let (authority, path) = rest.split_at(end);
    if authority.contains('@') {
        return Err("it holds a name and a password");
    }
    let (site, port) = match authority.rsplit_once(':') {
        Some((site, port)) => (site, port),
        None => (authority, ""),
    };
    if !port.is_empty() && port != "443" {
        return Err("it names a port other than 443");
    }
    let site = site.to_ascii_lowercase();
    if !site_name_fits(&site) {
        return Err("its site's name is not one I can look up");
    }
    // The path, with its steps of "." and ".." worked out, and the query
    // behind it as it came.
    let (path, query) = match path.split_once('?') {
        Some((path, query)) => (path, Some(query)),
        None => (path, None),
    };
    let path = dots_removed(if path.is_empty() { "/" } else { path });
    let path = match query {
        Some(query) => format!("{}?{}", path, query),
        None => path,
    };
    Ok(Address { site, path })
}

// What follows `start` at the beginning of `text`, compared without regard
// to capital letters.
fn after_ignoring_case<'a>(text: &'a str, start: &str) -> Option<&'a str> {
    let head = text.get(..start.len())?;
    if head.eq_ignore_ascii_case(start) { text.get(start.len()..) } else { None }
}

// A site's name as the name system takes it: parts of letters, digits and
// hyphens between dots, at least two parts, none empty, none beginning or
// ending with a hyphen, and the last not of digits alone, so that a machine's
// number is not taken for a name.
fn site_name_fits(site: &str) -> bool {
    if site.is_empty() || site.len() > SITE_NAME_MOST {
        return false;
    }
    let parts: Vec<&str> = site.split('.').collect();
    if parts.len() < 2 {
        return false;
    }
    let part_fits = |part: &&str| {
        !part.is_empty()
            && part.len() <= SITE_PART_MOST
            && part.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
            && !part.starts_with('-')
            && !part.ends_with('-')
    };
    parts.iter().all(part_fits) && !parts[parts.len() - 1].bytes().all(|byte| byte.is_ascii_digit())
}

// The address a site sends one on to, read against the address that was asked
// for, as the web's rules for addresses say (RFC 3986, section 5.2): a whole
// address stands by itself; one that begins with // names another site; one
// that begins with / is on the same site; an empty one, or one of a query
// alone, keeps the path; any other is read from the folder of the address
// asked for. Steps of "." and ".." are worked out. The result is read and
// checked as every address is.
pub fn address_join(base: &Address, location: &str) -> Result<Address, &'static str> {
    if location.is_empty() {
        return Err("it is no address I can read");
    }
    if has_scheme(location) {
        return address_read(location);
    }
    if let Some(rest) = location.strip_prefix("//") {
        return address_read(&format!("https://{}", rest));
    }
    let location = location.split('#').next().unwrap_or("");
    let (base_path, base_query) = match base.path.split_once('?') {
        Some((path, query)) => (path, Some(query)),
        None => (base.path.as_str(), None),
    };
    let (path, query) = match location.split_once('?') {
        Some((path, query)) => (path, Some(query)),
        None => (location, None),
    };
    let (path, query) = if path.is_empty() {
        // The same path, with the new query if there is one, or else the old.
        (String::from(base_path), if query.is_some() { query } else { base_query })
    } else if path.starts_with('/') {
        (String::from(path), query)
    } else {
        // The folder of the path asked for, then this path.
        let folder = &base_path[..base_path.rfind('/').map_or(0, |at| at + 1)];
        (format!("{}{}", folder, path), query)
    };
    // Reading the whole address works out the steps of "." and "..".
    match query {
        Some(query) => address_read(&format!("https://{}{}?{}", base.site, path, query)),
        None => address_read(&format!("https://{}{}", base.site, path)),
    }
}

// Whether an address begins with a kind of its own ("https:", "http:" and
// the like): a letter, then letters, digits, "+", "-" or ".", then a colon,
// before any "/", "?" or "#".
fn has_scheme(text: &str) -> bool {
    let Some(colon) = text.find(':') else {
        return false;
    };
    let scheme = &text[..colon];
    scheme.as_bytes().first().is_some_and(|byte| byte.is_ascii_alphabetic())
        && scheme.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'+' || byte == b'-' || byte == b'.')
}

// A path with its steps of "." and ".." worked out, as RFC 3986 section
// 5.2.4 describes it: what is still to be read is taken from the front, and
// what is done is built up behind.
fn dots_removed(path: &str) -> String {
    let mut input = String::from(path);
    let mut output = String::new();
    while !input.is_empty() {
        if input.starts_with("../") {
            input.drain(..3);
        } else if input.starts_with("./") {
            input.drain(..2);
        } else if input.starts_with("/./") {
            input.replace_range(..3, "/");
        } else if input == "/." {
            input = String::from("/");
        } else if input.starts_with("/../") || input == "/.." {
            let length = if input == "/.." { 3 } else { 4 };
            input.replace_range(..length, "/");
            match output.rfind('/') {
                Some(at) => output.truncate(at),
                None => output.clear(),
            }
        } else if input == "." || input == ".." {
            input.clear();
        } else {
            // The first step, with its "/" in front if it has one, up to the
            // next "/".
            let from = if input.starts_with('/') { 1 } else { 0 };
            let end = input[from..].find('/').map_or(input.len(), |at| at + from);
            output.push_str(&input[..end]);
            input.drain(..end);
        }
    }
    if output.is_empty() { String::from("/") } else { output }
}

// What one hop brought.
pub enum Fetched {
    // The file, whole, and what kind of thing the site said it is.
    File { bytes: Vec<u8>, content_type: Option<String> },
    // The site sends one on: the address it gives, as it wrote it, or an
    // empty text when that cannot be read.
    SentOn(String),
    // No file, and why, in words that can follow "because".
    Refused(String),
}

// Where reading the answer of a hop has got to.
enum Hop {
    // The head of the answer is still being read.
    Head,
    // The file is coming: how long the site said it is, if it did, and what
    // kind of thing it said it is.
    Body { length: Option<u64>, content_type: Option<String> },
    // Decided before the answer was over.
    Over(Fetched),
}

// Says how big something is, in words: bytes, KB or MB.
pub fn size_words(bytes: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = 1024 * 1024;
    if bytes == 1 {
        String::from("1 byte")
    } else if bytes < KB {
        format!("{} bytes", bytes)
    } else if bytes < MB {
        format!("{} KB", (bytes + KB / 2) / KB)
    } else {
        let tenths = (bytes * 10 + MB / 2) / MB;
        if tenths % 10 == 0 { format!("{} MB", tenths / 10) } else { format!("{}.{} MB", tenths / 10, tenths % 10) }
    }
}

// What the head of an answer means for the file: it is coming (with its
// length if the site said it), or the hop is over (the site sends one on,
// or there is no file, and why).
fn head_judged(head: &Head) -> Hop {
    match head.number {
        200 => {
            if head.transfer_coding.is_some() {
                return Hop::Over(Fetched::Refused(String::from(
                    "it sent the file in pieces with their lengths in between (\"chunked\"), which it should not for this kind of request",
                )));
            }
            if let Some(coding) = &head.content_coding {
                if !coding.is_empty() && !coding.eq_ignore_ascii_case("identity") {
                    return Hop::Over(Fetched::Refused(format!("it sent the file packed (\"{}\"), which I do not take", coding)));
                }
            }
            let length = match head.length {
                Length::Unsaid => None,
                Length::Said(length) => Some(length),
                Length::Unreadable => return Hop::Over(Fetched::Refused(String::from("it gave a length I cannot read"))),
            };
            if let Some(length) = length {
                if length > FILE_MOST as u64 {
                    return Hop::Over(Fetched::Refused(format!("the file is {}, more than the {} I take", size_words(length), size_words(FILE_MOST as u64))));
                }
            }
            Hop::Body { length, content_type: head.content_type.clone() }
        }
        301 | 302 | 303 | 307 | 308 => match &head.location {
            Some(location) => Hop::Over(Fetched::SentOn(location.clone())),
            None => Hop::Over(Fetched::Refused(String::from("it sends me on, but does not say where"))),
        },
        number => Hop::Over(Fetched::Refused(format!("it answered {} {}", number, head.words).trim_end().into())),
    }
}

// One hop: asks the site that `text` names for it, and reads the answer as
// it arrives. The request says HTTP/1.0, so the site sends the file plain and
// closes the connection after it, and it asks for the file unpacked. Nothing
// else is sent: no line names the kernel, the machine or the person. Prints
// one line about the hop in the terminal. Only the network's task may call
// this.
pub fn download_hop(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>, text: &str) -> Fetched {
    let fetched = match address_read(text) {
        Ok(address) => hop(interface, card, sockets, name_server, &address),
        Err(why) => Fetched::Refused(String::from(why)),
    };
    let told = match &fetched {
        Fetched::File { bytes, .. } => format!("the file, {} bytes, whole", bytes.len()),
        Fetched::SentOn(location) => format!("sent on to {}", location.chars().take(ADDRESS_SHOWN).collect::<String>()),
        Fetched::Refused(why) => format!("no file, because {}", why),
    };
    serial_print(&format!("Download: {}: {}\r\n", text.chars().take(ADDRESS_SHOWN).collect::<String>(), told));
    fetched
}

fn hop(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>, address: &Address) -> Fetched {
    let request = format!("GET {} HTTP/1.0\r\nHost: {}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n", address.path, address.site);
    let mut reader = HeadReader::new();
    let mut state = Hop::Head;
    let mut body: Vec<u8> = Vec::new();
    let mut taken_any = false;
    let waits = Waits { first: FIRST_WAIT, rest: WHOLE_WAIT, restarts: false };
    let result = site_exchange(interface, card, sockets, name_server, &address.site, request.as_bytes(), waits, &mut |piece| {
        taken_any = true;
        let mut piece = piece;
        if let Hop::Head = state {
            match reader.take(piece) {
                HeadRead::More => return true,
                HeadRead::Wrong(why) => {
                    state = Hop::Over(Fetched::Refused(String::from(why)));
                    return false;
                }
                HeadRead::Done(head, from) => {
                    state = head_judged(&head);
                    piece = &piece[from..];
                    match &state {
                        Hop::Body { length: Some(length), .. } => body.reserve_exact(*length as usize),
                        Hop::Body { .. } => {}
                        _ => return false,
                    }
                }
            }
        }
        let Hop::Body { length, .. } = &state else {
            return false;
        };
        let length = *length;
        if body.len() + piece.len() > FILE_MOST {
            body = Vec::new();
            state = Hop::Over(Fetched::Refused(format!("it is larger than the {} I take", size_words(FILE_MOST as u64))));
            return false;
        }
        body.extend_from_slice(piece);
        match length {
            Some(length) if body.len() as u64 > length => {
                body = Vec::new();
                state = Hop::Over(Fetched::Refused(String::from("it sent more than the length it gave")));
                false
            }
            // All of it is here, by the length the site gave.
            Some(length) if body.len() as u64 == length => false,
            _ => true,
        }
    });
    match (state, result) {
        (Hop::Over(fetched), _) => fetched,
        (_, Err(reason)) => Fetched::Refused(format!("no answer came: {}", reason)),
        (Hop::Head, Ok(_)) => Fetched::Refused(String::from(if taken_any { "its answer ended before its notes were over" } else { "it sent nothing" })),
        (Hop::Body { length: Some(length), content_type }, Ok(_)) => {
            if body.len() as u64 == length {
                Fetched::File { bytes: body, content_type }
            } else {
                Fetched::Refused(format!("the file did not come whole: {} of {} bytes came", body.len(), length))
            }
        }
        (Hop::Body { length: None, content_type }, Ok(goodbye)) => {
            if goodbye {
                Fetched::File { bytes: body, content_type }
            } else {
                Fetched::Refused(String::from("the file did not come whole: the connection ended without the site's goodbye"))
            }
        }
    }
}
