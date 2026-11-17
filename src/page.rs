//! Fetching one page from the web over an encrypted link: look up the site's
//! name, connect, let the site prove who it is, ask for the page, show how it
//! begins. Notes: `docs/network.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
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
use crate::tls::{Wire, secure_exchange, secure_ready};

// The site whose page is fetched. Its owners keep it for examples like this.
const SITE: &str = "example.com";

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

// Fetches the site's page and prints how it begins. Called once by the
// network's task, as soon as this machine has an address.
pub fn page_fetch(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, name_server: Option<Ipv4Address>) {
    // `let Some(..) = .. else` means: if there is one, go on with it;
    // if there is none, do what stands in the braces.
    let Some(name_server) = name_server else {
        serial_print("Network: no page fetched, because the network named no name server\r\n");
        return;
    };

    // The page is fetched over an encrypted link or not at all. If this
    // machine cannot encrypt, nothing is sent, not even the site's name.
    if let Err(reason) = secure_ready() {
        serial_print(&format!("Network: no page fetched, because {}\r\n", reason));
        return;
    }

    let address = match name_lookup(interface, card, sockets, name_server) {
        Ok(address) => address,
        Err(reason) => {
            serial_print(&format!("Network: no page fetched, because {}\r\n", reason));
            return;
        }
    };
    serial_print(&format!("Network: the name {} belongs to the address {}\r\n", SITE, address));

    let answer = match page_ask(interface, card, sockets, address) {
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
) -> Result<IpAddress, &'static str> {
    let asker = sockets.add(dns::Socket::new(&[IpAddress::Ipv4(name_server)], vec![]));
    let question = match sockets.get_mut::<dns::Socket>(asker).start_query(interface.context(), SITE, DnsQueryType::A) {
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

// ---------- Asking for the page ----------

// A connection is an agreement between two machines to pass bytes back and
// forth so that none is lost and all arrive in order: each side numbers its
// bytes, the other side confirms what has arrived, and what is not confirmed
// is sent again. The network stack does all of that. This opens a connection
// to the site, has the conversation, and ends the connection again.
fn page_ask(interface: &mut Interface, card: &mut Card, sockets: &mut SocketSet, address: IpAddress) -> Result<Answer, String> {
    let connection = sockets.add(tcp::Socket::new(
        tcp::SocketBuffer::new(vec![0; ARRIVAL_ROOM]),
        tcp::SocketBuffer::new(vec![0; SENDING_ROOM]),
    ));
    let result = conversation(interface, card, sockets, connection, address);

    // Say goodbye. If the site finished properly, finish properly too.
    // Otherwise tell the site that this side has dropped the connection.
    let socket = sockets.get_mut::<tcp::Socket>(connection);
    match &result {
        Ok(answer) if answer.complete => socket.close(),
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
    result
}

// The conversation itself: connect, then greet the site, send the request and
// take in the answer over an encrypted link.
fn conversation(
    interface: &mut Interface,
    card: &mut Card,
    sockets: &mut SocketSet,
    connection: SocketHandle,
    address: IpAddress,
) -> Result<Answer, String> {
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

    // The request, in the web's own language (HTTP): "GET /" asks for the
    // site's front page, "Host" names the site, because one machine can serve
    // many, and the empty line says that the request ends here. With
    // "HTTP/1.0" the site closes the connection once the page is sent.
    let request = format!("GET / HTTP/1.0\r\nHost: {}\r\n\r\n", SITE);

    // From here on nothing travels in the open. The encrypted link greets the
    // site, checks its certificate, sends the request scrambled, and hands
    // over the answer unscrambled, piece by piece. The piece of code between
    // the bars (a closure) is what takes each piece of the answer.
    let mut answer = Answer::new();
    let mut wire = ConnectionWire { interface, card, sockets, connection, end: wait_end(ANSWER_WAIT) };
    let site_finished = secure_exchange(SITE, request.as_bytes(), &mut wire, &mut |bytes| {
        for byte in bytes {
            answer.take(*byte);
        }
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

// The connection, in the form the encrypted link wants it: something that
// sends bytes and receives bytes, waiting where it has to. The `'a` and `'b`
// are lifetimes: labels for how long the borrowed things stay valid.
struct ConnectionWire<'a, 'b> {
    interface: &'a mut Interface,
    card: &'a mut Card,
    sockets: &'a mut SocketSet<'b>,
    connection: SocketHandle,
    end: u64, // The tick at which the whole exchange gives up.
}

impl Wire for ConnectionWire<'_, '_> {
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
            if wait_is_over(self.end) {
                return Err("the site took too long");
            }
        }
        Ok(())
    }

    fn receive(&mut self, room: &mut [u8]) -> Result<usize, &'static str> {
        loop {
            let socket = self.sockets.get_mut::<tcp::Socket>(self.connection);
            if socket.can_recv() {
                return socket.recv_slice(room).map_err(|_| "the connection broke");
            }
            if !socket.may_recv() {
                // Nothing more will come.
                return Ok(0);
            }
            if wait_is_over(self.end) {
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
