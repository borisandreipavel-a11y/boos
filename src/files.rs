//! Files fetched from the web and kept on the disk. They have a room of their
//! own in the back half of the kernel's own part, behind the notebook; each
//! file lies in one run of neighbouring blocks there, and the notebook keeps
//! a note about each (`file 1`, `file 2`, ...), written only once the file's
//! blocks are on the disk and read back. The notebook also keeps every site
//! the person allowed (`site 1`, `site 2`, ...): before the kernel contacts a
//! site for the first time, it asks. This file also leads a fetch from the
//! model's tool to the file kept, hop by hop (see `download.rs`), and asks
//! the person before a kept file is removed. Only the main loop may call
//! these functions, and the startup code the first two.
//! Notes: `docs/disk.md`, `docs/notebook.md`, `docs/tools.md`.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::chat::chat_say;
use crate::clock::clock_read;
use crate::disk::BLOCK_SIZE;
use crate::download::{Address, Fetched, address_join, address_read, size_words};
use crate::errand::{Errand, errand_ask};
use crate::notebook::{notebook_find, notebook_keep, notebook_names, notebook_ready};
use crate::parts::{check_value, part_read, part_read_run, part_size, part_write, part_write_run};
use crate::serial::serial_print;
use crate::tools::ToolDone;

// A part smaller than this many blocks (2 MB) has no room for files.
const PART_SMALLEST: u64 = 4096;

// The head of the room for files, in its first block: 16 letters, the
// version of the layout, and a check value of both, as in the notebook's
// head. It is written when the first file is kept.
const HEAD_LETTERS: [u8; 16] = *b"boos files      ";
const HEAD_VERSION_AT: usize = 16;
const HEAD_CHECK_AT: usize = 20;
const VERSION: u32 = 1;

// The names that notes about files and allowed sites are kept under in the
// notebook, with their number behind.
const FILE_NOTE: &str = "file ";
const SITE_NOTE: &str = "site ";

// How often one fetch may be sent on to another address.
const HOPS_MOST: usize = 5;

// How many signs of a file's name are kept and shown.
const NAME_MOST: usize = 40;

// The kinds of file that are kept.
#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Pdf,
    Word,
    Excel,
    Text,
    Csv,
}

impl Kind {
    // The word it is kept under in a file's note.
    fn word(self) -> &'static str {
        match self {
            Kind::Pdf => "pdf",
            Kind::Word => "docx",
            Kind::Excel => "xlsx",
            Kind::Text => "txt",
            Kind::Csv => "csv",
        }
    }

    fn from_word(word: &str) -> Option<Kind> {
        [Kind::Pdf, Kind::Word, Kind::Excel, Kind::Text, Kind::Csv].into_iter().find(|kind| kind.word() == word)
    }

    // What it is called in a sentence, with "a" or "an".
    fn told(self) -> &'static str {
        match self {
            Kind::Pdf => "a PDF",
            Kind::Word => "a Word file",
            Kind::Excel => "an Excel file",
            Kind::Text => "a text",
            Kind::Csv => "a CSV table",
        }
    }
}

// A kept file, as its note in the notebook says.
struct KeptFile {
    number: u32,
    first: u64,
    blocks: u64,
    bytes: u64,
    kind: Kind,
    name: String,
}

// The room for files on this start: the block of its head, and the last
// block a file may use (the last but one of the part; the last holds the
// count of starts). Files lie behind the head.
struct Room {
    head: u64,
    last: u64,
    begun: bool,
}

// What the kernel asks the person, and waits for an answer to.
enum Question {
    // Whether a site may be contacted, for the first time.
    Site(String),
    // Whether a kept file may be removed.
    Remove(u32),
}

// A fetch under way, from the model's tool until its file is kept or it
// ends: the address of the next hop, the file's name as the first address
// gave it, the addresses fetched so far, and sites allowed during this fetch
// whose yes could not be kept.
struct Fetch {
    address: Address,
    asked_name: String,
    seen: Vec<String>,
    allowed: Vec<String>,
}

// Everything here is the main loop's. Nothing protects it against a second
// task, so no other task may call a function of this file.
static mut ROOM: Option<Room> = None;
static mut NO_ROOM_WHY: &str = "there is no disk part of my own";
static mut FILES: Vec<KeptFile> = Vec::new();
static mut NEXT_FILE: u32 = 1;
static mut SITES: Vec<String> = Vec::new();
static mut NEXT_SITE: u32 = 1;
static mut ASKING: Option<Question> = None;
static mut FETCH: Option<Fetch> = None;

// As in `chat.rs`: these hand the lists out through their addresses, and
// after calling another function of this file, a list fetched before the
// call is not used again.
fn files() -> &'static mut Vec<KeptFile> {
    unsafe { &mut *(&raw mut FILES) }
}

fn sites() -> &'static mut Vec<String> {
    unsafe { &mut *(&raw mut SITES) }
}

fn room() -> Option<&'static mut Room> {
    unsafe { (*(&raw mut ROOM)).as_mut() }
}

// ---------- At startup ----------

// Looks, before the notebook is opened, at where the room for files would
// begin: the middle of the kernel's part. Gives back that block, and whether
// the room's head stands there already. A part too small for a room, or a
// room that holds something else, gives nothing, and the notebook keeps all
// of the part, as before there were files.
pub fn files_look() -> (Option<u64>, bool) {
    let size = part_size();
    if size == 0 {
        return (None, false);
    }
    if size < PART_SMALLEST {
        unsafe { NO_ROOM_WHY = "my part is too small for it" };
        return (None, false);
    }
    let head = size / 2;
    let mut block = [0u8; BLOCK_SIZE as usize];
    if part_read(head, &mut block).is_err() {
        unsafe { NO_ROOM_WHY = "the block where it begins cannot be read" };
        return (None, false);
    }
    if block.iter().all(|byte| *byte == 0) {
        unsafe { ROOM = Some(Room { head, last: size - 2, begun: false }) };
        return (Some(head), false);
    }
    if head_fits(&block) {
        unsafe { ROOM = Some(Room { head, last: size - 2, begun: true }) };
        return (Some(head), true);
    }
    unsafe { NO_ROOM_WHY = "the block where it begins holds something I do not know" };
    (None, false)
}

// The head of the room for files, as it is written.
fn head_block() -> [u8; BLOCK_SIZE as usize] {
    let mut block = [0u8; BLOCK_SIZE as usize];
    block[..16].copy_from_slice(&HEAD_LETTERS);
    block[HEAD_VERSION_AT..HEAD_VERSION_AT + 4].copy_from_slice(&VERSION.to_le_bytes());
    let check = check_value(&block[..HEAD_CHECK_AT]);
    block[HEAD_CHECK_AT..HEAD_CHECK_AT + 4].copy_from_slice(&check.to_le_bytes());
    block
}

fn head_fits(block: &[u8; BLOCK_SIZE as usize]) -> bool {
    *block == head_block()
}

// Once the notebook is open: whether it left the room to the files, then the
// notes about kept files and allowed sites. Prints one line about the room.
pub fn files_begin(files_room: bool) {
    if !files_room {
        if unsafe { (*(&raw const ROOM)).is_some() } {
            unsafe { NO_ROOM_WHY = "the notebook reaches into it" };
        }
        unsafe { ROOM = None };
        if part_size() > 0 {
            serial_print(&format!("Disk: no room for files, because {}\r\n", unsafe { NO_ROOM_WHY }));
        }
        return;
    }
    for name in notebook_names() {
        if let Some(number) = numbered(&name, FILE_NOTE) {
            unsafe { NEXT_FILE = NEXT_FILE.max(number.saturating_add(1)) };
            if let Ok(Some(note)) = notebook_find(&name) {
                if let Some(file) = note_read(number, &note) {
                    files().push(file);
                }
            }
        } else if let Some(number) = numbered(&name, SITE_NOTE) {
            unsafe { NEXT_SITE = NEXT_SITE.max(number.saturating_add(1)) };
            if let Ok(Some(site)) = notebook_find(&name) {
                if let Ok(site) = core::str::from_utf8(&site) {
                    if address_read(&format!("https://{}/", site)).is_ok_and(|address| address.site == site) && !sites().iter().any(|known| known == site) {
                        sites().push(String::from(site));
                    }
                }
            }
        }
    }
    let count = files().len();
    let free = free_blocks() * BLOCK_SIZE / 1024;
    let kept = if count == 1 { String::from("1 file") } else { format!("{} files", count) };
    if notebook_ready() {
        serial_print(&format!("Disk: the room for files holds {} and has room for {} KB more\r\n", kept, free));
    } else {
        serial_print(&format!("Disk: the room for files holds {}; no more are kept, since the notebook cannot be added to\r\n", kept));
    }
}

// The number behind a note's name, such as 3 for "file 3".
fn numbered(name: &str, lead: &str) -> Option<u32> {
    let digits = name.strip_prefix(lead)?;
    if digits.is_empty() || digits.len() > 9 || !digits.bytes().all(|digit| digit.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

// Reads a file's note. It comes from the disk, from outside the kernel, so
// it counts only if every line is as it is written and the file lies wholly
// inside the room. An empty note is a file that was removed.
fn note_read(number: u32, note: &[u8]) -> Option<KeptFile> {
    let room = room()?;
    let text = core::str::from_utf8(note).ok()?;
    let mut lines = text.lines();
    let mut places = lines.next()?.strip_prefix("blocks ")?.split(' ');
    let first: u64 = places.next()?.parse().ok()?;
    let blocks: u64 = places.next()?.parse().ok()?;
    let bytes: u64 = lines.next()?.strip_prefix("bytes ")?.parse().ok()?;
    let _check = u32::from_str_radix(lines.next()?.strip_prefix("check ")?, 16).ok()?;
    let kind = Kind::from_word(lines.next()?.strip_prefix("kind ")?)?;
    let name = lines.next()?.strip_prefix("name ")?;
    if blocks == 0 || bytes == 0 || bytes.div_ceil(BLOCK_SIZE) != blocks || first <= room.head || first > room.last || blocks > room.last + 1 - first {
        return None;
    }
    if name.is_empty() || name.len() > NAME_MOST || !name.bytes().all(|sign| (b' '..=b'~').contains(&sign)) {
        return None;
    }
    Some(KeptFile { number, first, blocks, bytes, kind, name: String::from(name) })
}

// ---------- The room ----------

// Whether files can be fetched and kept now.
pub fn files_usable() -> bool {
    room().is_some() && notebook_ready()
}

// The kept files, the one kept last first: each by its number, its name, its
// kind and its size, as the tool that removes one lists them.
pub fn files_listed() -> Vec<(u32, String)> {
    let mut listed: Vec<(u32, String)> =
        files().iter().map(|file| (file.number, format!("{}, {} of {}", file.name, file.kind.told(), size_words(file.bytes)))).collect();
    listed.sort_by(|one, other| other.0.cmp(&one.0));
    listed
}

// The runs of blocks no file uses, in order: (first block, how many).
fn free_runs() -> Vec<(u64, u64)> {
    let Some(room) = room() else {
        return Vec::new();
    };
    let mut used: Vec<(u64, u64)> = files().iter().map(|file| (file.first, file.blocks)).collect();
    used.sort_unstable();
    let mut runs = Vec::new();
    let mut next = room.head + 1;
    for (first, blocks) in used {
        if first > next {
            runs.push((next, first - next));
        }
        next = next.max(first + blocks);
    }
    if next <= room.last {
        runs.push((next, room.last + 1 - next));
    }
    runs
}

fn free_blocks() -> u64 {
    free_runs().iter().map(|(_, blocks)| blocks).sum()
}

// Keeps a file: finds the first run of free blocks it fits in, writes it
// there and reads it back, and only then writes its note into the notebook.
// A power cut before the note leaves the blocks free, as they were. Gives
// back the file's number, or why it was not kept.
fn file_keep(bytes: &[u8], kind: Kind, name: &str, address: &str) -> Result<u32, String> {
    if !files_usable() {
        return Err(String::from("there is no room for files that I can add to"));
    }
    let blocks = (bytes.len() as u64).div_ceil(BLOCK_SIZE);
    let Some((first, _)) = free_runs().into_iter().find(|(_, free)| *free >= blocks) else {
        let free = free_runs().iter().map(|(_, free)| *free).max().unwrap_or(0);
        return Err(format!("the room for files has {} free in one piece, and the file is {}", size_words(free * BLOCK_SIZE), size_words(bytes.len() as u64)));
    };
    let room = room().ok_or_else(|| String::from("there is no room for files"))?;
    if !room.begun {
        let head = head_block();
        part_write(room.head, &head).map_err(String::from)?;
        let mut back = [0u8; BLOCK_SIZE as usize];
        part_read(room.head, &mut back).map_err(String::from)?;
        if back != head {
            return Err(String::from("the disk did not hold what was written to it"));
        }
        room.begun = true;
    }
    part_write_run(first, bytes).map_err(String::from)?;
    // Read it back, a frame's worth at a time, and compare.
    let mut back = [0u8; 4096];
    for (index, piece) in bytes.chunks(back.len()).enumerate() {
        let at = first + (index * back.len()) as u64 / BLOCK_SIZE;
        part_read_run(at, &mut back[..piece.len()]).map_err(String::from)?;
        if &back[..piece.len()] != piece {
            return Err(String::from("the disk did not hold what was written to it"));
        }
    }
    let number = unsafe { NEXT_FILE };
    let date = match clock_read() {
        Some(date) => format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02}", date.year, date.month, date.day, date.hour, date.minute, date.second),
        None => String::from("unknown"),
    };
    let note = format!(
        "blocks {} {}\nbytes {}\ncheck {:08x}\nkind {}\nname {}\ndate {}\nfrom {}\n",
        first,
        blocks,
        bytes.len(),
        check_value(bytes),
        kind.word(),
        name,
        date,
        address
    );
    notebook_keep(&format!("{}{}", FILE_NOTE, number), note.as_bytes()).map_err(String::from)?;
    unsafe { NEXT_FILE = number + 1 };
    files().push(KeptFile { number, first, blocks, bytes: bytes.len() as u64, kind, name: String::from(name) });
    Ok(number)
}

// What kind of file this is, by its first bytes where the kind has a mark of
// its own: a PDF begins with "%PDF-" (RFC 8118), and a Word or an Excel file
// is a ZIP package that begins with the bytes 50 4b 03 04 (the IANA's
// registrations of both kinds); which of the two it is, the address's ending
// or the site's word for it says. Plain text and CSV have no mark: they are
// taken when the address's ending or the site's word says so, and only if
// every byte reads as text. Anything else is not kept.
fn kind_of(bytes: &[u8], last_part: &str, content_type: Option<&str>) -> Result<Kind, String> {
    if bytes.is_empty() {
        return Err(String::from("the site sent an empty file"));
    }
    let ending = match last_part.rsplit_once('.') {
        Some((_, ending)) => ending.to_ascii_lowercase(),
        None => String::new(),
    };
    let said = content_type.map(|kind| kind.split(';').next().unwrap_or("").trim()).unwrap_or("");
    if bytes.starts_with(b"%PDF-") {
        return Ok(Kind::Pdf);
    }
    if bytes.starts_with(&[0x50, 0x4b, 0x03, 0x04]) {
        if ending == "docx" || said == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" {
            return Ok(Kind::Word);
        }
        if ending == "xlsx" || said == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" {
            return Ok(Kind::Excel);
        }
        return Err(String::from("it is a packed file, but neither its address nor the site says it is a Word or an Excel file"));
    }
    let csv = ending == "csv" || said == "text/csv";
    if csv || ending == "txt" || said == "text/plain" {
        if bytes.contains(&0) || core::str::from_utf8(bytes).is_err() {
            return Err(String::from("it is said to be text, but it is not plain text"));
        }
        return Ok(if csv { Kind::Csv } else { Kind::Text });
    }
    let called = if said.is_empty() { String::from("nothing") } else { format!("\"{}\"", said) };
    Err(format!("it is a kind of file I do not keep (the site calls it {})", called))
}

// Removes a kept file: its note in the notebook is replaced by an empty one,
// and its blocks are free again. Gives back its name.
fn file_remove(number: u32) -> Result<String, String> {
    let Some(place) = files().iter().position(|file| file.number == number) else {
        return Err(String::from("no kept file has that number"));
    };
    notebook_keep(&format!("{}{}", FILE_NOTE, number), b"").map_err(String::from)?;
    Ok(files().remove(place).name)
}

// ---------- Sites ----------

fn site_allowed(site: &str) -> bool {
    sites().iter().any(|known| known == site) || unsafe { (*(&raw const FETCH)).as_ref() }.is_some_and(|fetch| fetch.allowed.iter().any(|known| known == site))
}

// Keeps a site the person allowed in the notebook, for good.
fn site_allow(site: &str) -> Result<(), &'static str> {
    let number = unsafe { NEXT_SITE };
    notebook_keep(&format!("{}{}", SITE_NOTE, number), site.as_bytes())?;
    unsafe { NEXT_SITE = number + 1 };
    sites().push(String::from(site));
    Ok(())
}

// ---------- A fetch, from the tool to the file kept ----------

// The name a file is shown and kept under: the last part of its address,
// cleaned and cut, or nothing.
fn name_of(address: &Address) -> String {
    let plain: String = address.last_part().bytes().map(|byte| if (b' '..=b'~').contains(&byte) { byte as char } else { '.' }).collect();
    plain.chars().take(NAME_MOST).collect()
}

// How a file is spoken of before it is kept: by its name, or as "the file".
fn spoken(name: &str) -> String {
    if name.is_empty() { String::from("the file") } else { String::from(name) }
}

// The model asked for a file with the tool `download_file`. The address is
// read and checked; then the first hop goes to the network's task, or, for a
// site not contacted before, the person is asked first. Says how it went in
// the chat box.
pub fn download_start(text: &str) -> ToolDone {
    let shown: String = text.bytes().map(|byte| if (b' '..=b'~').contains(&byte) { byte as char } else { '.' }).take(60).collect();
    let address = match address_read(text.trim()) {
        Ok(address) => address,
        Err(why) => {
            chat_say(&format!("the model asked me to fetch \"{}\", but {}.", shown, why));
            return ToolDone::Back;
        }
    };
    if !files_usable() {
        let why = if room().is_none() { unsafe { NO_ROOM_WHY } } else { "the notebook cannot be added to" };
        chat_say(&format!("I cannot keep files, because {}.", why));
        return ToolDone::Back;
    }
    if free_blocks() == 0 {
        chat_say("I cannot keep another file: the room for files is full.");
        return ToolDone::Back;
    }
    let asked_name = name_of(&address);
    unsafe { FETCH = Some(Fetch { address, asked_name, seen: Vec::new(), allowed: Vec::new() }) };
    hop_next(None)
}

// The next hop of the fetch under way: it goes to the network's task, or,
// when its site was not contacted before, the person is asked first. `from`
// is the site that sent the fetch on, for a hop that is not the first.
fn hop_next(from: Option<&str>) -> ToolDone {
    let Some(fetch) = (unsafe { (*(&raw const FETCH)).as_ref() }) else {
        return ToolDone::Ended;
    };
    let site = fetch.address.site.clone();
    if site_allowed(&site) {
        return hop_go();
    }
    match from {
        None => chat_say(&format!("{} is on {}, a site I have not fetched from before.", spoken(&fetch.asked_name), site)),
        Some(from) => chat_say(&format!("{} sends me on to {}, a site I have not fetched from before.", from, site)),
    }
    chat_say("may I? Type yes to allow it from now on; anything else is a no.");
    unsafe { ASKING = Some(Question::Site(site)) };
    ToolDone::Awaited
}

// Hands the next hop of the fetch under way to the network's task. Only the
// first hop is said in the chat box; the terminal has a line for each.
fn hop_go() -> ToolDone {
    let Some(fetch) = (unsafe { (*(&raw const FETCH)).as_ref() }) else {
        return ToolDone::Ended;
    };
    let first = fetch.seen.is_empty();
    let name = spoken(&fetch.asked_name);
    let site = fetch.address.site.clone();
    match errand_ask(Errand::Download(fetch.address.whole())) {
        Ok(()) => {
            if first {
                chat_say(&format!("I am fetching {} from {}.", name, site));
            }
            ToolDone::Awaited
        }
        Err(reason) => {
            unsafe { FETCH = None };
            chat_say(&format!("I cannot fetch {}, because {}.", name, reason));
            ToolDone::Back
        }
    }
}

// Whether the kernel waits for the person's answer to one of its questions
// here; then the next line sent is that answer (see `chat.rs`).
pub fn files_asking() -> bool {
    unsafe { (*(&raw const ASKING)).is_some() }
}

// Takes the person's answer to a question of this file: "yes" says yes, and
// anything else no. Says what comes of it.
pub fn files_answer(said: &str) -> ToolDone {
    let yes = said.trim().eq_ignore_ascii_case("yes");
    match unsafe { (*(&raw mut ASKING)).take() } {
        Some(Question::Site(site)) => {
            if !yes {
                unsafe { FETCH = None };
                chat_say(&format!("I did not fetch it, since {} was not allowed.", site));
                return ToolDone::Ended;
            }
            if let Err(reason) = site_allow(&site) {
                chat_say(&format!("I could not keep that yes, because {}, so I will ask again next time.", reason));
                if let Some(fetch) = unsafe { (*(&raw mut FETCH)).as_mut() } {
                    fetch.allowed.push(site);
                }
            }
            hop_go()
        }
        Some(Question::Remove(number)) => {
            let name = files().iter().find(|file| file.number == number).map(|file| file.name.clone()).unwrap_or_default();
            if !yes {
                chat_say(&format!("I kept file {}, \"{}\".", number, name));
                return ToolDone::Ended;
            }
            match file_remove(number) {
                Ok(name) => chat_say(&format!("I removed file {}, \"{}\".", number, name)),
                Err(reason) => chat_say(&format!("I could not remove file {}, because {}.", number, reason)),
            }
            ToolDone::Ended
        }
        None => ToolDone::Ended,
    }
}

// What a hop brought, from the network's task. A file is checked for its
// kind and kept; an address the site sends one on to is read, and the next
// hop goes, after a question if its site is new; anything else ends the
// fetch. Says how it went. A fetch that `setup` ended says nothing more.
pub fn download_answer(fetched: Option<Fetched>, sentence: &str) -> ToolDone {
    let Some(mut fetch) = (unsafe { (*(&raw mut FETCH)).take() }) else {
        return ToolDone::Ended;
    };
    let site = fetch.address.site.clone();
    let name = spoken(&fetch.asked_name);
    match fetched {
        None => {
            chat_say(&format!("I did not fetch {}, because {}.", name, sentence.strip_prefix("no answer came, because ").unwrap_or(sentence)));
            ToolDone::Back
        }
        Some(Fetched::Refused(why)) => {
            chat_say(&format!("I did not fetch {} from {}, because {}.", name, site, why));
            ToolDone::Back
        }
        Some(Fetched::SentOn(location)) => {
            fetch.seen.push(fetch.address.whole());
            if fetch.seen.len() > HOPS_MOST {
                chat_say(&format!("I did not fetch {}, because {} sends me on more than {} times.", name, site, HOPS_MOST));
                return ToolDone::Back;
            }
            let next = match address_join(&fetch.address, &location) {
                Ok(next) => next,
                Err(why) => {
                    chat_say(&format!("I did not fetch {}, because {} sends me on to an address I cannot use: {}.", name, site, why));
                    return ToolDone::Back;
                }
            };
            if fetch.seen.contains(&next.whole()) {
                chat_say(&format!("I did not fetch {}, because {} sends me back to an address I was sent from.", name, site));
                return ToolDone::Back;
            }
            fetch.address = next;
            unsafe { FETCH = Some(fetch) };
            hop_next(Some(&site))
        }
        Some(Fetched::File { bytes, content_type }) => {
            let kind = match kind_of(&bytes, fetch.address.last_part(), content_type.as_deref()) {
                Ok(kind) => kind,
                Err(why) => {
                    chat_say(&format!("I did not keep {} from {}, because {}.", name, site, why));
                    return ToolDone::Back;
                }
            };
            // The name of the file that came, which a site that sent the
            // fetch on may have changed; or the one asked for; or its number.
            let mut kept_name = name_of(&fetch.address);
            if kept_name.is_empty() {
                kept_name = fetch.asked_name.clone();
            }
            if kept_name.is_empty() {
                kept_name = format!("file {}", unsafe { NEXT_FILE });
            }
            match file_keep(&bytes, kind, &kept_name, &fetch.address.whole()) {
                Ok(number) => {
                    chat_say(&format!("I kept \"{}\" as file {}, {} of {} from {}.", kept_name, number, kind.told(), size_words(bytes.len() as u64), site));
                    ToolDone::Ended
                }
                Err(why) => {
                    chat_say(&format!("I did not keep {} from {}, because {}.", name, site, why));
                    ToolDone::Back
                }
            }
        }
    }
}

// The model asked to remove a kept file with the tool `remove_file`: the
// person is asked first.
pub fn remove_ask(number: u64) -> ToolDone {
    let Some(file) = files().iter().find(|file| file.number as u64 == number) else {
        chat_say(&format!("the model asked to remove file {}, but no kept file has that number.", number));
        return ToolDone::Back;
    };
    if !notebook_ready() {
        chat_say("I cannot remove a file, because the notebook cannot be added to.");
        return ToolDone::Back;
    }
    chat_say(&format!("remove file {}, \"{}\", for good? Type yes to remove it; anything else keeps it.", file.number, file.name));
    unsafe { ASKING = Some(Question::Remove(file.number)) };
    ToolDone::Awaited
}

// `setup` was sent: a fetch under way ends, and so does a question of this
// file. What the network's task still brings for it is not kept.
pub fn files_setup() {
    unsafe {
        FETCH = None;
        ASKING = None;
    }
}
