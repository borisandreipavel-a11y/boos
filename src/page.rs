//! Fetching one page from the web over an encrypted link: look up the site's
//! name, connect, let the site prove who it is, ask for the page, show how it
//! begins. Notes: `docs/network.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::cell::Cell;
use core::sync::atomic::Ordering;

use smoltcp::iface::{Interface, SocketHandle, SocketSet};
use smoltcp::socket::dns::{self, GetQueryResultError};
use smoltcp::socket::tcp;
use smoltcp::wire::{DnsQueryType, IpAddress, Ipv4Address};

use crate::network::{Card, now};
use crate::processor::time_stamp;
use crate::serial::serial_print;
use crate::tasks::task_wait;
use crate::timer::{TICKS, TICKS_PER_SECOND};
use crate::tls::{LinkEnd, Wire, secure_exchange, secure_ready};

// The site whose page is fetched. Its owners keep it for examples like this.
pub const SITE: &str = "example.com";

// A machine can hold many conversations at once. A port is the number that
// says which conversation a packet belongs to. Sites wait for requests over
// an encrypted link on port 443, and for requests in the open on port 80.
const WEB_PORT: u16 = 443;

// How much of the page is shown: so many rows of so many characters.
const ROWS_SHOWN: usize = 8;
const ROW_LENGTH: usize = 72;

// How long each wait may last, in seconds, before the fetch gives up.
const LOOKUP_WAIT: u64 = 5;
const CONNECT_WAIT: u64 = 5;
const ANSWER_WAIT: u64 = 15; // The greeting and the answer together.
const GOODBYE_WAIT: u64 = 1;

// Room for the connection's bytes: those that have arrived and are not read
// yet, and those that wait to be sent.
const ARRIVAL_ROOM: usize = 4096;
const SENDING_ROOM: usize = 512;

// Gets the site's page: looks its name up, connects, and has the
// conversation over an encrypted link. Whatever goes wrong comes back as a
// reason in words. On the way it prints which address the name belongs to.
fn page_get(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>) -> Result<Answer, String> {
    // `let Some(..) = .. else` means: if there is one, go on with it;
    // if there is none, do what stands in the braces.
    // The request, in the web's own language (HTTP): "GET /" asks for the
    // site's front page, "Host" names the site, because one machine can serve
    // many, and the empty line says that the request ends here. With
    // "HTTP/1.0" the site closes the connection once the page is sent.
    let request = format!("GET / HTTP/1.0\r\nHost: {}\r\n\r\n", SITE);

    // The piece of code between the bars (a closure) is what takes each piece
    // of the answer as it comes in.
    let mut answer = Answer::new();
    let site_finished = site_exchange(interface, card, sockets, name_server, SITE, request.as_bytes(), Waits::one(ANSWER_WAIT), &mut |bytes| {
        for byte in bytes {
            answer.take(*byte);
        }
        true
    })?;
    // The page counts as whole only if the site said, through the encrypted
    // link itself, that it had sent everything.
    answer.complete = site_finished;
    answer.finish();
    if answer.length == 0 {
        return Err("the site sent nothing".into());
    }
    Ok(answer)
}

// How long an exchange may take, in seconds, counted from the moment the site
// agreed to the connection: `first` for the greeting and the first piece of
// the answer, and `rest` for the whole answer, or, when `restarts` is set,
// for each next piece after the one before it.
#[derive(Clone, Copy)]
pub struct Waits {
    pub first: u64,
    pub rest: u64,
    pub restarts: bool,
}

impl Waits {
    // One wait for the greeting and the whole answer together.
    pub const fn one(seconds: u64) -> Waits {
        Waits { first: seconds, rest: seconds, restarts: false }
    }
}

// One exchange with a site over an encrypted link: looks the site's name up,
// connects, lets the site prove who it is, sends `request`, and hands every
// piece of the answer to `taker`, which says whether it wants more: when it
// says no, this side says goodbye through the link and the exchange ends
// there. `waits` says how long the exchange may take. Answers "true" if the
// site said through the link itself that it had sent everything. Whatever goes
// wrong comes back as a reason in words. On the way it prints which address
// the name belongs to. Only the network's task may call this.
pub fn site_exchange(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Option<Ipv4Address>,
    site: &str,
    request: &[u8],
    waits: Waits,
    taker: &mut dyn FnMut(&[u8]) -> bool,
) -> Result<bool, String> {
    let Some(name_server) = name_server else {
        return Err("the network named no name server".into());
    };

    // The exchange happens over an encrypted link or not at all. If this
    // machine cannot encrypt, nothing is sent, not even the site's name.
    secure_ready()?;

    let address = name_lookup(interface, card, sockets, name_server, site)?;
    serial_print(&format!("Network: the name {} belongs to the address {}\r\n", site, address));

    // A connection is an agreement between two machines to pass bytes back
    // and forth so that none is lost and all arrive in order: each side
    // numbers its bytes, the other side confirms what has arrived, and what
    // is not confirmed is sent again. The network stack does all of that.
    // This opens a connection to the site, has the conversation, and ends the
    // connection again.
    let connection = sockets.add(tcp::Socket::new(
        tcp::SocketBuffer::new(vec![0; ARRIVAL_ROOM]),
        tcp::SocketBuffer::new(vec![0; SENDING_ROOM]),
    ));
    let result = conversation(interface, card, sockets, connection, address, site, request, waits, taker);

    // Say goodbye. If the site finished properly, or this side had what it
    // wanted and said so through the link, finish properly too. Otherwise
    // tell the site that this side has dropped the connection.
    let socket = sockets.get_mut::<tcp::Socket>(connection);
    match &result {
        Ok(LinkEnd::Goodbye | LinkEnd::Stopped) => socket.close(),
        _ => socket.abort(),
    }
    let end = wait_end(GOODBYE_WAIT);
    loop {
        stack_turn(interface, card, sockets);
        if !sockets.get_mut::<tcp::Socket>(connection).is_active() || wait_is_over(end) {
            break;
        }
    }
    sockets.remove(connection);
    result.map(|end| end == LinkEnd::Goodbye)
}

// Fetches the site's page and prints how it begins. Called once by the
// network's task, as soon as this machine has an address.
pub fn page_fetch(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>) {
    let answer = match page_get(interface, card, sockets, name_server) {
        Ok(answer) => answer,
        Err(reason) => {
            serial_print(&format!("Network: no page fetched, because {}\r\n", reason));
            return;
        }
    };

    // The report is put together first and printed in one go, so that another
    // task's line cannot land in the middle of it.
    let mut report = format!("Network: {} answered \"{}\". Its page begins:\r\n", SITE, answer.first_line);
    for row in &answer.rows {
        report.push_str("    ");
        report.push_str(row);
        report.push_str("\r\n");
    }
    if answer.complete {
        report.push_str(&format!("Network: the whole page is {} bytes long.\r\n", answer.page_length));
    } else {
        report.push_str(&format!(
            "Network: the page is not whole: the connection broke or took too long. {} bytes of it came.\r\n",
            answer.page_length
        ));
    }
    serial_print(&report);
}

// ---------- Waiting for the network ----------

// Lets the network stack take in and send packets once, then waits a tick.
// Everything below waits for the network by doing this again and again.
fn stack_turn(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet) {
    interface.poll(now(), card, sockets);
    task_wait(1);
}

// No wait below is endless. This says at which tick a wait that starts now
// is over.
fn wait_end(seconds: u64) -> u64 {
    TICKS.load(Ordering::Relaxed) + seconds * TICKS_PER_SECOND
}

fn wait_is_over(end: u64) -> bool {
    TICKS.load(Ordering::Relaxed) >= end
}

// ---------- Looking up the name ----------

// Machines on the internet are reached by network address, but sites are
// known by name. A name server is a machine that knows which address belongs
// to which name. This asks it, and waits for the answer.
fn name_lookup(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    name_server: Ipv4Address,
    site: &str,
) -> Result<IpAddress, &'static str> {
    let asker = sockets.add(dns::Socket::new(&[IpAddress::Ipv4(name_server)], vec![]));
    let question = match sockets.get_mut::<dns::Socket>(asker).start_query(interface.context(), site, DnsQueryType::A) {
        Ok(question) => question,
        Err(_) => {
            sockets.remove(asker);
            return Err("the name could not be asked for");
        }
    };

    // Keep the stack going until the answer is in.
    let end = wait_end(LOOKUP_WAIT);
    let answer = loop {
        stack_turn(interface, card, sockets);
        match sockets.get_mut::<dns::Socket>(asker).get_query_result(question) {
            Ok(addresses) => match addresses.first() {
                Some(address) => break Ok(*address),
                None => break Err("the name server knows no address for the name"),
            },
            Err(GetQueryResultError::Pending) => {
                if wait_is_over(end) {
                    break Err("the name server did not answer in time");
                }
            }
            Err(GetQueryResultError::Failed) => break Err("the name server does not know the name"),
        }
    };
    sockets.remove(asker);
    answer
}

// ---------- The conversation ----------

// The conversation itself: connect, then greet the site, send the request and
// take in the answer over an encrypted link.
fn conversation(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    connection: SocketHandle,
    address: IpAddress,
    site: &str,
    request: &[u8],
    waits: Waits,
    taker: &mut dyn FnMut(&[u8]) -> bool,
) -> Result<LinkEnd, String> {
    // This side needs a port number too. Any number from the range kept for
    // this use will do. The processor's count of its own steps picks one, so
    // that it differs from one start of the kernel to the next.
    let own_port = 49152 + (time_stamp() % 16384) as u16;
    let socket = sockets.get_mut::<tcp::Socket>(connection);
    if socket.connect(interface.context(), (address, WEB_PORT), own_port).is_err() {
        return Err("the connection could not be started".into());
    }

    // Wait until the site has agreed to the connection.
    let end = wait_end(CONNECT_WAIT);
    loop {
        stack_turn(interface, card, sockets);
        let socket = sockets.get_mut::<tcp::Socket>(connection);
        if socket.may_send() {
            break;
        }
        if !socket.is_active() {
            return Err("the site refused the connection".into());
        }
        if wait_is_over(end) {
            return Err("the site did not agree to a connection in time".into());
        }
    }

    // From here on nothing travels in the open. The encrypted link greets the
    // site, checks its certificate, sends the request scrambled, and hands
    // over the answer unscrambled, piece by piece. The first piece of the
    // answer is noted, because from then on the second wait counts.
    let begun = Cell::new(false);
    let mut wire = ConnectionWire {
        interface,
        card,
        sockets,
        connection,
        first_end: wait_end(waits.first),
        rest_end: wait_end(waits.rest),
        waits,
        begun: &begun,
    };
    let mut noting = |bytes: &[u8]| {
        begun.set(true);
        taker(bytes)
    };
    secure_exchange(site, request, &mut wire, &mut noting)
}

// The connection, in the form the encrypted link wants it: something that
// sends bytes and receives bytes, waiting where it has to. The `'a`, `'b` and
// `'c` are lifetimes: labels for how long the borrowed things stay valid.
struct ConnectionWire<'a, 'b, 'c> {
    interface: &'a mut Interface,
    card: &'a mut Card,
    sockets: &'a mut SocketSet<'b>,
    connection: SocketHandle,
    // The tick by which the greeting and the first piece of the answer must
    // have come, and the one by which the rest must; with `waits.restarts`
    // the second moves on whenever bytes arrive after the answer has begun.
    first_end: u64,
    rest_end: u64,
    waits: Waits,
    // Whether a piece of the answer has come.
    begun: &'c Cell<bool>,
}

impl ConnectionWire<'_, '_, '_> {
    // The tick at which the exchange gives up now.
    fn end(&self) -> u64 {
        if self.begun.get() { self.rest_end } else { self.first_end }
    }
}

impl Wire for ConnectionWire<'_, '_, '_> {
    fn send(&mut self, mut bytes: &[u8]) -> Result<(), &'static str> {
        // The connection takes as many bytes as it has room for. The rest
        // waits for the next turn.
        while !bytes.is_empty() {
            let socket = self.sockets.get_mut::<tcp::Socket>(self.connection);
            if !socket.may_send() {
                return Err("the connection broke");
            }
            let taken = socket.send_slice(bytes).map_err(|_| "the connection broke")?;
            bytes = &bytes[taken..];
            stack_turn(self.interface, self.card, self.sockets);
            if wait_is_over(self.end()) {
                return Err("the site took too long");
            }
        }
        Ok(())
    }

    fn receive(&mut self, room: &mut [u8]) -> Result<usize, &'static str> {
        loop {
            let socket = self.sockets.get_mut::<tcp::Socket>(self.connection);
            if socket.can_recv() {
                let count = socket.recv_slice(room).map_err(|_| "the connection broke")?;
                if self.waits.restarts && self.begun.get() {
                    self.rest_end = wait_end(self.waits.rest);
                }
                return Ok(count);
            }
            if !socket.may_recv() {
                // Nothing more will come.
                return Ok(0);
            }
            if wait_is_over(self.end()) {
                return Err("the site took too long");
            }
            stack_turn(self.interface, self.card, self.sockets);
        }
    }
}

// ---------- Reading the answer ----------

// A site's answer is one long run of bytes in three parts: a first line that
// says how it went ("200 OK" means: here is the page), then lines of notes
// about the page, then an empty line, and after it the page itself.
enum Part {
    FirstLine,
    Notes,
    Page,
}

// Takes the answer in byte by byte and keeps what will be shown: the first
// line and the first rows of the page. The rest is only counted.
struct Answer {
    part: Part,
    // The first line of the answer.
    first_line: String,
    // How long the line of notes being read is so far.
    note_length: usize,
    // The rows of the page that will be shown, and the one being collected.
    rows: Vec<String>,
    row: String,
    // How many bytes came in all, and how many of them were the page.
    length: usize,
    page_length: usize,
    // Whether the site said that it had sent everything.
    complete: bool,
}

impl Answer {
    fn new() -> Answer {
        Answer {
            part: Part::FirstLine,
            first_line: String::new(),
            note_length: 0,
            rows: Vec::new(),
            row: String::new(),
            length: 0,
            page_length: 0,
            complete: false,
        }
    }

    // Takes in the next byte. Byte 10 (`\n`) ends a line.
    fn take(&mut self, byte: u8) {
        self.length += 1;
        match self.part {
            Part::FirstLine => {
                if byte == b'\n' {
                    self.part = Part::Notes;
                } else if self.first_line.len() < ROW_LENGTH {
                    if let Some(sign) = plain_sign(byte) {
                        self.first_line.push(sign);
                    }
                }
            }
            Part::Notes => {
                if byte == b'\n' {
                    // An empty line: the notes are over and the page begins.
                    if self.note_length == 0 {
                        self.part = Part::Page;
                    }
                    self.note_length = 0;
                } else if byte != b'\r' {
                    self.note_length += 1;
                }
            }
            Part::Page => {
                self.page_length += 1;
                if self.rows.len() < ROWS_SHOWN {
                    if byte == b'\n' {
                        self.row_end();
                    } else if let Some(sign) = plain_sign(byte) {
                        self.row.push(sign);
                        // A long line goes on in the next row.
                        if self.row.len() == ROW_LENGTH {
                            self.row_end();
                        }
                    }
                }
            }
        }
    }

    // Puts the row that is being collected with the rows to show. Empty rows
    // are left out.
    fn row_end(&mut self) {
        if !self.row.is_empty() {
            // `take` empties `self.row` and hands over what was in it.
            self.rows.push(core::mem::take(&mut self.row));
        }
    }

    // Called when no more bytes will come: the last row may have no line end.
    fn finish(&mut self) {
        if self.rows.len() < ROWS_SHOWN {
            self.row_end();
        }
    }
}

// ---------- Reading the head of an answer, as it arrives ----------

// The most bytes the first line and the lines of notes of an answer may take
// together. A site that sends more is not read further.
const HEAD_MOST: usize = 16 * 1024;
// The most signs kept of the words behind the number and of the kind of what
// is sent, and the longest address a site may send one on to.
const WORDS_KEPT: usize = 40;
const KIND_KEPT: usize = 100;
const LOCATION_MOST: usize = 2048;

// How long the answer's body is, as its notes say.
#[derive(Clone, Copy, PartialEq)]
pub enum Length {
    // No note says it.
    Unsaid,
    // So many bytes.
    Said(u64),
    // A note says it in a way that cannot be read, or two notes differ.
    Unreadable,
}

// What the head of an answer says, as far as the kernel looks at it: the
// number in the first line (200 means: here it is) and the words behind it,
// and five notes: what kind of thing is sent (Content-Type, in small
// letters), how long it is (Content-Length), whether it is sent in pieces
// with their lengths in between (Transfer-Encoding), whether it is packed
// (Content-Encoding), and where the site sends one on to (Location). All of
// it comes from outside: the texts are cleaned to plain signs and cut, and an
// address that holds anything but plain signs, or is longer than
// `LOCATION_MOST`, is kept as an empty text, which no address reads as.
pub struct Head {
    pub number: u16,
    pub words: String,
    pub content_type: Option<String>,
    pub length: Length,
    pub transfer_coding: Option<String>,
    pub content_coding: Option<String>,
    pub location: Option<String>,
}

impl Head {
    fn empty() -> Head {
        Head {
            number: 0,
            words: String::new(),
            content_type: None,
            length: Length::Unsaid,
            transfer_coding: None,
            content_coding: None,
            location: None,
        }
    }
}

// What a piece of the answer brought to the reader of its head.
pub enum HeadRead {
    // The head is not over yet.
    More,
    // The head is over: what it says, and the place in this piece where the
    // body begins.
    Done(Head, usize),
    // The answer is not one the reader can go on with, and why.
    Wrong(&'static str),
}

// Reads the head of an answer from its pieces as they arrive, however they
// are cut: the first line, then the lines of notes up to the empty line. A
// line ends in byte 10, with or without byte 13 before it.
pub struct HeadReader {
    line: Vec<u8>,
    taken: usize,
    first: bool,
    head: Head,
}

impl HeadReader {
    pub fn new() -> HeadReader {
        HeadReader { line: Vec::new(), taken: 0, first: true, head: Head::empty() }
    }

    // Takes the next piece of the answer. Once the head is over, the rest of
    // the piece is the body's, from the place given back.
    pub fn take(&mut self, piece: &[u8]) -> HeadRead {
        for (place, byte) in piece.iter().enumerate() {
            self.taken += 1;
            if self.taken > HEAD_MOST {
                return HeadRead::Wrong("its notes are longer than I read");
            }
            if *byte != b'\n' {
                self.line.push(*byte);
                continue;
            }
            if self.line.last() == Some(&b'\r') {
                self.line.pop();
            }
            let line = core::mem::take(&mut self.line);
            if self.first {
                self.first = false;
                if !self.first_line(&line) {
                    return HeadRead::Wrong("its answer does not begin the way an answer on the web does");
                }
            } else if line.is_empty() {
                return HeadRead::Done(core::mem::replace(&mut self.head, Head::empty()), place + 1);
            } else {
                self.note(&line);
            }
        }
        HeadRead::More
    }

    // The first line reads like "HTTP/1.1 200 OK": the number is the three
    // digits behind the first space, and the words follow behind another.
    fn first_line(&mut self, line: &[u8]) -> bool {
        if !line.starts_with(b"HTTP/") {
            return false;
        }
        let Some(space) = line.iter().position(|byte| *byte == b' ') else {
            return false;
        };
        let Some(digits) = line.get(space + 1..space + 4) else {
            return false;
        };
        if !digits.iter().all(|digit| digit.is_ascii_digit()) {
            return false;
        }
        self.head.number = digits.iter().fold(0, |number, digit| number * 10 + (*digit - b'0') as u16);
        if let Some(words) = line.get(space + 5..) {
            self.head.words = plain_bytes(words, WORDS_KEPT);
        }
        true
    }

    // A line of notes: a name, a colon, and what it says. Names are told
    // apart without regard to capital letters. A note the reader does not
    // look at is passed over, and so is a line without a colon or one that
    // begins with a space (a note that goes on from the line before, which
    // the web no longer allows).
    fn note(&mut self, line: &[u8]) {
        if line.first().is_some_and(|byte| *byte == b' ' || *byte == b'\t') {
            return;
        }
        let Some(colon) = line.iter().position(|byte| *byte == b':') else {
            return;
        };
        let name = &line[..colon];
        let value = trimmed(&line[colon + 1..]);
        if name.eq_ignore_ascii_case(b"content-type") {
            if self.head.content_type.is_none() {
                self.head.content_type = Some(plain_bytes(value, KIND_KEPT).to_ascii_lowercase());
            }
        } else if name.eq_ignore_ascii_case(b"content-length") {
            let said = digits_read(value);
            self.head.length = match (self.head.length, said) {
                (Length::Unsaid, Some(length)) => Length::Said(length),
                (Length::Said(before), Some(length)) if before == length => Length::Said(length),
                _ => Length::Unreadable,
            };
        } else if name.eq_ignore_ascii_case(b"transfer-encoding") {
            joined(&mut self.head.transfer_coding, value);
        } else if name.eq_ignore_ascii_case(b"content-encoding") {
            joined(&mut self.head.content_coding, value);
        } else if name.eq_ignore_ascii_case(b"location") && self.head.location.is_none() {
            let usable = value.len() <= LOCATION_MOST && value.iter().all(|byte| (b'!'..=b'~').contains(byte));
            self.head.location = Some(if usable { value.iter().map(|byte| *byte as char).collect() } else { String::new() });
        }
    }
}

// A note's value without the spaces and tabs at either end.
fn trimmed(value: &[u8]) -> &[u8] {
    let blank = |byte: &u8| *byte == b' ' || *byte == b'\t';
    let start = value.iter().position(|byte| !blank(byte)).unwrap_or(value.len());
    let end = value.iter().rposition(|byte| !blank(byte)).map_or(start, |end| end + 1);
    &value[start..end]
}

// A number written as digits alone, if it fits; nothing for anything else.
fn digits_read(value: &[u8]) -> Option<u64> {
    if value.is_empty() || !value.iter().all(|digit| digit.is_ascii_digit()) {
        return None;
    }
    value.iter().try_fold(0u64, |number, digit| number.checked_mul(10)?.checked_add((*digit - b'0') as u64))
}

// Adds a note's value to what notes of the same name said before, parted by
// a comma, as the web reads several such notes; cleaned and cut.
fn joined(kept: &mut Option<String>, value: &[u8]) {
    let value = plain_bytes(value, WORDS_KEPT);
    let whole = match kept.take() {
        Some(before) if !before.is_empty() => format!("{}, {}", before, value),
        _ => value,
    };
    *kept = Some(whole.chars().take(WORDS_KEPT).collect());
}

// Cleans bytes from outside as `plain_text` cleans a text.
fn plain_bytes(bytes: &[u8], longest: usize) -> String {
    bytes.iter().copied().filter_map(plain_sign).take(longest).collect()
}

// Cleans a whole text from outside in the same way as the function below
// cleans one byte, and cuts it at `longest` signs.
pub fn plain_text(text: &str, longest: usize) -> String {
    text.bytes().filter_map(plain_sign).take(longest).collect()
}

// The answer is text from outside, written by somebody else. Only plain
// letters, digits and signs are passed on to the screen. Byte 13 (`\r`),
// which comes before each line end, is dropped, and anything else becomes a
// dot, so that a page cannot send commands to the terminal.
fn plain_sign(byte: u8) -> Option<char> {
    match byte {
        b'\r' => None,
        b' '..=b'~' => Some(byte as char),
        _ => Some('.'),
    }
}
