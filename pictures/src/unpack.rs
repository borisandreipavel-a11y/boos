//! Unpacking: bytes packed with DEFLATE (RFC 1951) inside a zlib stream (RFC
//! 1950), turned back into the bytes they were. A PNG's dots are packed this
//! way, and so are most streams of a PDF and the parts of Word and Excel
//! files. The packed bytes come from a `Source` a byte at a time, and the
//! unpacked ones go to a `Sink` a piece at a time, so the whole of neither is
//! ever held in memory. Notes: `docs/pictures.md`.
//!
//! The section of RFC 1951 that each step follows is named beside it.

use alloc::vec;
use alloc::vec::Vec;

use crate::Refusal;
use crate::check::Adler;

/// Where packed bytes come from, one at a time. Once it has said there are
/// no more, it must go on saying so.
pub(crate) trait Source {
    fn next_byte(&mut self) -> Option<u8>;
}

/// Where unpacked bytes go, a piece at a time. It may stop the unpacking by
/// giving back a refusal, for example when more bytes come than it wants.
pub(crate) trait Sink {
    fn take(&mut self, bytes: &[u8]) -> Result<(), Refusal>;
}

// What goes wrong, in the words the kernel says after "it is damaged:".
const BAD_HEAD: &str = "its packed dots do not begin as a zlib stream must";
const NOT_DEFLATE: &str = "its packed dots name a packing other than deflate";
const WIDE_WINDOW: &str = "its packed dots name a window larger than 32 KB";
const DICTIONARY: &str = "its packed dots need a dictionary, which a PNG never has";
const NO_SUCH_BLOCK: &str = "its packed dots hold a block of a kind that does not exist";
const STORED_LENGTH: &str = "a stored block of its packed dots does not check its own length";
pub(crate) const OVERFULL: &str = "its packed dots hold a table of codes with more codes than can be";
const MEANINGLESS: &str = "its packed dots hold a code that means nothing";
pub(crate) const LENGTHS: &str = "its packed dots hold a table of code lengths that does not add up";
pub(crate) const TOO_MANY_CODES: &str = "its packed dots name more literal codes than there can be";
const TOO_FAR_BACK: &str = "its packed dots copy from before their own beginning";
const BAD_SUM: &str = "the check value of its packed dots does not fit";

/// The lengths that the length codes 257 to 285 stand for, before their
/// extra bits, and how many extra bits each has (RFC 1951, 3.2.5).
const LENGTH_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258,
];
const LENGTH_EXTRA: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];

/// The distances that the distance codes 0 to 29 stand for, before their
/// extra bits, and how many extra bits each has (RFC 1951, 3.2.5). Codes 30
/// and 31 "will never actually occur".
const DISTANCE_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
    8193, 12289, 16385, 24577,
];
const DISTANCE_EXTRA: [u8; 30] =
    [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

/// The order in which a dynamic block gives the lengths of the code-length
/// codes (RFC 1951, 3.2.7).
const LENGTH_ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

/// The longest code DEFLATE has, in bits.
const LONGEST: usize = 15;

/// Codes this long or shorter are found with one look in a small table; the
/// longer ones are found bit by bit (see `Code::decode`). Building the small
/// table costs 2^9 steps, so a file of many tiny blocks cannot make building
/// tables slow.
const QUICK_BITS: u32 = 9;

/// How far back a copy may reach: 32 KB (RFC 1951, 2 and 3.2.5).
const REACH: usize = 32_768;

/// The unpacked bytes are handed on when this many have gathered, all but the
/// last 32 KB, which stay for copies to reach back into.
const HAND_ON_AT: usize = 98_304;

// ---------- Reading bits ----------

/// Reads the packed bytes as bits, lowest bit of each byte first (RFC 1951,
/// 3.1.1). Up to 64 bits wait in `held`. When the source has no more bytes,
/// zeros are put in their place so that a code can still be looked up, and
/// `made_up` counts them: taking any of them means the stream was cut short.
struct Bits<'a, S: Source> {
    source: &'a mut S,
    held: u64,
    count: u32,
    made_up: u32,
}

impl<'a, S: Source> Bits<'a, S> {
    fn new(source: &'a mut S) -> Bits<'a, S> {
        Bits { source, held: 0, count: 0, made_up: 0 }
    }

    /// Fills `held` with whole bytes until it has more than 56 bits.
    fn fill(&mut self) {
        while self.count <= 56 {
            match self.source.next_byte() {
                Some(byte) => self.held |= u64::from(byte) << self.count,
                None => self.made_up += 8,
            }
            self.count += 8;
        }
    }

    /// How many of the held bits really came from the source.
    fn real(&self) -> u32 {
        self.count.saturating_sub(self.made_up)
    }

    /// Takes `n` bits, at most 32, as a number whose lowest bit came first.
    fn take(&mut self, n: u32) -> Result<u32, Refusal> {
        if n == 0 {
            return Ok(0);
        }
        if self.count < n {
            self.fill();
        }
        if n > self.real() {
            return Err(Refusal::CutShort);
        }
        let value = (self.held & ((1u64 << n) - 1)) as u32;
        self.drop_bits(n);
        Ok(value)
    }

    fn drop_bits(&mut self, n: u32) {
        self.held >>= n;
        self.count -= n;
    }

    /// The next 15 bits, without taking them, for looking a code up.
    fn peek(&mut self) -> u32 {
        if self.count < LONGEST as u32 {
            self.fill();
        }
        (self.held & 0x7fff) as u32
    }

    /// Skips what is left of the byte being read (RFC 1951, 3.2.4). The held
    /// bits are always whole bytes but for the one being read.
    fn skip_to_byte(&mut self) {
        let rest = self.count % 8;
        self.drop_bits(rest);
    }
}

// ---------- Codes ----------

/// A Huffman code (RFC 1951, 3.2.2), built from the length of each symbol's
/// code. `count[n]` is how many codes are n bits long; `symbols` lists the
/// symbols that have a code, the shorter codes first and, among codes of one
/// length, in the order of the symbols, as the code's values run. `quick` is
/// looked up with the next nine bits: for a code of at most nine bits it
/// holds the symbol times 16 plus the code's length, and 0 otherwise.
struct Code {
    count: [u16; LONGEST + 1],
    symbols: Vec<u16>,
    quick: Vec<u16>,
}

impl Code {
    fn new() -> Code {
        Code { count: [0; LONGEST + 1], symbols: Vec::with_capacity(320), quick: vec![0; 1 << QUICK_BITS] }
    }

    /// Builds the code from its lengths, one for each symbol, 0 for a symbol
    /// that has none. A set of lengths with more codes than there is room
    /// for is turned down. One with fewer is taken (RFC 1951 allows a single
    /// distance code of one bit, and none at all); a code it leaves out
    /// means nothing when it comes.
    fn build(&mut self, lengths: &[u8]) -> Result<(), Refusal> {
        self.count = [0; LONGEST + 1];
        for length in lengths {
            if let Some(count) = self.count.get_mut(usize::from(*length)) {
                *count += 1;
            }
        }
        if let Some(zero) = self.count.get_mut(0) {
            *zero = 0;
        }

        // Each length doubles the codes there is room for; the codes of that
        // length take theirs (the Kraft sum). Below zero is over-full.
        let mut room: i64 = 1;
        for count in self.count.iter().skip(1) {
            room = room * 2 - i64::from(*count);
            if room < 0 {
                return Err(Refusal::Damaged(OVERFULL));
            }
        }

        // Where each length's symbols begin in `symbols`, and the first
        // code of each length (RFC 1951, 3.2.2, steps 1 and 2).
        let mut start = [0usize; LONGEST + 2];
        let mut first_code = [0u32; LONGEST + 1];
        let mut code = 0u32;
        for length in 1..=LONGEST {
            let shorter = usize::from(self.count.get(length - 1).copied().unwrap_or(0));
            let before = start.get(length - 1).copied().unwrap_or(0);
            if let Some(slot) = start.get_mut(length) {
                *slot = if length == 1 { 0 } else { before + usize::from(self.count.get(length - 1).copied().unwrap_or(0)) };
            }
            code = (code + shorter as u32) << 1;
            if let Some(slot) = first_code.get_mut(length) {
                *slot = code;
            }
        }

        // The symbols in order of their codes (step 3), and the quick table.
        self.symbols.clear();
        self.symbols.resize(lengths.len(), 0);
        for entry in self.quick.iter_mut() {
            *entry = 0;
        }
        let mut next_place = start;
        let mut next_code = first_code;
        for (symbol, length) in lengths.iter().enumerate() {
            let length = usize::from(*length);
            if length == 0 || length > LONGEST {
                continue;
            }
            let (Some(place), Some(code)) = (next_place.get_mut(length), next_code.get_mut(length)) else {
                continue;
            };
            if let Some(slot) = self.symbols.get_mut(*place) {
                *slot = symbol as u16;
            }
            *place += 1;
            if length as u32 <= QUICK_BITS {
                // The code is read highest bit first (RFC 1951, 3.1.1), so it
                // is looked up with its bits turned round. Every entry whose
                // lowest bits are the code holds it.
                let turned = reversed(*code, length as u32) as usize;
                let entry = ((symbol as u16) << 4) | length as u16;
                let mut at = turned;
                while at < self.quick.len() {
                    if let Some(slot) = self.quick.get_mut(at) {
                        *slot = entry;
                    }
                    at += 1 << length;
                }
            }
            *code += 1;
        }
        Ok(())
    }

    /// Reads one symbol. A code of at most nine bits is found in the quick
    /// table; a longer one bit by bit, as RFC 1951's codes run: the codes of
    /// each length are consecutive numbers, after those of the shorter ones.
    fn decode<S: Source>(&self, bits: &mut Bits<'_, S>) -> Result<u16, Refusal> {
        let ahead = bits.peek();
        let quick = self.quick.get((ahead & ((1 << QUICK_BITS) - 1)) as usize).copied().unwrap_or(0);
        if quick != 0 {
            let length = u32::from(quick & 0xf);
            if length > bits.real() {
                return Err(Refusal::CutShort);
            }
            bits.drop_bits(length);
            return Ok(quick >> 4);
        }
        let mut code = 0u32;
        let mut first = 0u32;
        let mut index = 0u32;
        for length in 1..=LONGEST as u32 {
            code |= (ahead >> (length - 1)) & 1;
            let count = u32::from(self.count.get(length as usize).copied().unwrap_or(0));
            if code >= first && code - first < count {
                if length > bits.real() {
                    return Err(Refusal::CutShort);
                }
                let symbol = self.symbols.get((index + code - first) as usize).copied();
                bits.drop_bits(length);
                return symbol.ok_or(Refusal::Damaged(MEANINGLESS));
            }
            index += count;
            first = (first + count) << 1;
            code <<= 1;
        }
        // No code fits these bits. If some of them were made up after the end
        // of the stream, the stream was cut; otherwise the code means nothing.
        if bits.real() < LONGEST as u32 { Err(Refusal::CutShort) } else { Err(Refusal::Damaged(MEANINGLESS)) }
    }
}

/// A code's lowest `length` bits in the other order.
fn reversed(code: u32, length: u32) -> u32 {
    let mut turned = 0;
    for bit in 0..length {
        turned = (turned << 1) | ((code >> bit) & 1);
    }
    turned
}

// ---------- What has been unpacked ----------

/// The bytes unpacked so far that have not been handed on, of which the last
/// 32 KB are always kept for copies to reach back into; how many bytes were
/// unpacked in all; and their Adler-32.
struct Unpacked {
    held: Vec<u8>,
    total: u64,
    sum: Adler,
}

impl Unpacked {
    fn new() -> Unpacked {
        Unpacked { held: Vec::with_capacity(HAND_ON_AT + 260), total: 0, sum: Adler::new() }
    }

    fn push<K: Sink>(&mut self, byte: u8, sink: &mut K) -> Result<(), Refusal> {
        self.held.push(byte);
        self.total += 1;
        if self.held.len() >= HAND_ON_AT { self.hand_on(REACH, sink) } else { Ok(()) }
    }

    /// Copies `length` bytes that began `distance` bytes back (RFC 1951,
    /// 3.2.3); they may run on into the bytes being copied.
    fn copy<K: Sink>(&mut self, distance: usize, length: usize, sink: &mut K) -> Result<(), Refusal> {
        if distance == 0 || distance as u64 > self.total || distance > self.held.len() {
            return Err(Refusal::Damaged(TOO_FAR_BACK));
        }
        for _ in 0..length {
            let from = self.held.len().checked_sub(distance).ok_or(Refusal::Damaged(TOO_FAR_BACK))?;
            let byte = self.held.get(from).copied().ok_or(Refusal::Damaged(TOO_FAR_BACK))?;
            self.push(byte, sink)?;
        }
        Ok(())
    }

    /// Hands on all held bytes but the last `keep`.
    fn hand_on<K: Sink>(&mut self, keep: usize, sink: &mut K) -> Result<(), Refusal> {
        let ready = self.held.len().saturating_sub(keep);
        if ready == 0 {
            return Ok(());
        }
        let (going, _) = self.held.split_at(ready);
        self.sum.add(going);
        sink.take(going)?;
        self.held.drain(..ready);
        Ok(())
    }
}

// ---------- The stream ----------

/// Unpacks a zlib stream (RFC 1950) whose packing is DEFLATE (RFC 1951) from
/// `source` into `sink`. It checks the stream's head and, at its end, the
/// Adler-32 of everything unpacked. A sink that wants no more stops it.
/// Bytes after the stream's end are not read.
pub(crate) fn zlib_unpack<S: Source, K: Sink>(source: &mut S, sink: &mut K) -> Result<(), Refusal> {
    let mut bits = Bits::new(source);

    // The head: CMF and FLG (RFC 1950, 2.2 and 2.3).
    let cmf = bits.take(8)?;
    let flg = bits.take(8)?;
    if (cmf * 256 + flg) % 31 != 0 {
        return Err(Refusal::Damaged(BAD_HEAD));
    }
    if cmf & 0x0f != 8 {
        return Err(Refusal::Damaged(NOT_DEFLATE));
    }
    if cmf >> 4 > 7 {
        return Err(Refusal::Damaged(WIDE_WINDOW));
    }
    if flg & 0x20 != 0 {
        return Err(Refusal::Damaged(DICTIONARY));
    }

    let mut out = Unpacked::new();
    let mut literals = Code::new();
    let mut distances = Code::new();
    let mut code_lengths = Code::new();
    let mut fixed_built = false;
    loop {
        // A block's head: is it the last, and how it is packed (3.2.3).
        let last = bits.take(1)?;
        match bits.take(2)? {
            0 => stored(&mut bits, &mut out, sink)?,
            1 => {
                // The fixed codes (3.2.6); built again only after a dynamic
                // block has used the same tables.
                if !fixed_built {
                    fixed_codes(&mut literals, &mut distances)?;
                    fixed_built = true;
                }
                packed(&mut bits, &literals, &distances, &mut out, sink)?;
            }
            2 => {
                dynamic_codes(&mut bits, &mut code_lengths, &mut literals, &mut distances)?;
                fixed_built = false;
                packed(&mut bits, &literals, &distances, &mut out, sink)?;
            }
            _ => return Err(Refusal::Damaged(NO_SUCH_BLOCK)),
        }
        if last == 1 {
            break;
        }
    }
    out.hand_on(0, sink)?;

    // The Adler-32 of the unpacked bytes, highest byte first (RFC 1950).
    bits.skip_to_byte();
    let mut stored_sum = 0u32;
    for _ in 0..4 {
        stored_sum = (stored_sum << 8) | bits.take(8)?;
    }
    if stored_sum != out.sum.value() {
        return Err(Refusal::Damaged(BAD_SUM));
    }
    Ok(())
}

/// A stored block: its bytes as they are (3.2.4).
fn stored<S: Source, K: Sink>(bits: &mut Bits<'_, S>, out: &mut Unpacked, sink: &mut K) -> Result<(), Refusal> {
    bits.skip_to_byte();
    let length = bits.take(16)?;
    let check = bits.take(16)?;
    if check != !length & 0xffff {
        return Err(Refusal::Damaged(STORED_LENGTH));
    }
    for _ in 0..length {
        let byte = bits.take(8)? as u8;
        out.push(byte, sink)?;
    }
    Ok(())
}

/// The fixed codes (3.2.6): literals and lengths 0 to 143 in 8 bits, 144 to
/// 255 in 9, 256 to 279 in 7, 280 to 287 in 8; the 32 distance codes in 5.
fn fixed_codes(literals: &mut Code, distances: &mut Code) -> Result<(), Refusal> {
    let mut lengths = [0u8; 288];
    for (symbol, length) in lengths.iter_mut().enumerate() {
        *length = match symbol {
            0..=143 => 8,
            144..=255 => 9,
            256..=279 => 7,
            _ => 8,
        };
    }
    literals.build(&lengths)?;
    distances.build(&[5u8; 32])
}

/// A dynamic block's codes, read from its head (3.2.7).
fn dynamic_codes<S: Source>(
    bits: &mut Bits<'_, S>,
    code_lengths: &mut Code,
    literals: &mut Code,
    distances: &mut Code,
) -> Result<(), Refusal> {
    let literal_count = bits.take(5)? as usize + 257;
    let distance_count = bits.take(5)? as usize + 1;
    let length_count = bits.take(4)? as usize + 4;
    if literal_count > 286 {
        return Err(Refusal::Damaged(TOO_MANY_CODES));
    }

    // The code-length code, its lengths given three bits each, in the order
    // of LENGTH_ORDER.
    let mut lengths_of_lengths = [0u8; 19];
    for symbol in LENGTH_ORDER.iter().take(length_count) {
        let length = bits.take(3)? as u8;
        if let Some(slot) = lengths_of_lengths.get_mut(*symbol) {
            *slot = length;
        }
    }
    code_lengths.build(&lengths_of_lengths)?;

    // The lengths of the literal and length codes and of the distance codes,
    // one run together: a repeat may run on from the one into the other.
    let wanted = literal_count + distance_count;
    let mut lengths = [0u8; 286 + 32];
    let mut filled = 0usize;
    while filled < wanted {
        let symbol = code_lengths.decode(bits)?;
        let (value, times) = match symbol {
            0..=15 => (symbol as u8, 1),
            16 => {
                // The length before, 3 to 6 times; there must be one before.
                let Some(before) = filled.checked_sub(1).and_then(|place| lengths.get(place).copied()) else {
                    return Err(Refusal::Damaged(LENGTHS));
                };
                (before, 3 + bits.take(2)? as usize)
            }
            17 => (0, 3 + bits.take(3)? as usize),
            18 => (0, 11 + bits.take(7)? as usize),
            _ => return Err(Refusal::Damaged(MEANINGLESS)),
        };
        if filled + times > wanted {
            return Err(Refusal::Damaged(LENGTHS));
        }
        for _ in 0..times {
            if let Some(slot) = lengths.get_mut(filled) {
                *slot = value;
            }
            filled += 1;
        }
    }
    let (literal_lengths, rest) = lengths.split_at(literal_count);
    let distance_lengths = rest.get(..distance_count).ok_or(Refusal::Damaged(LENGTHS))?;
    literals.build(literal_lengths)?;
    distances.build(distance_lengths)
}

/// A block packed with codes (3.2.5): literal bytes, and copies of bytes
/// unpacked before, until the end-of-block code, 256.
fn packed<S: Source, K: Sink>(
    bits: &mut Bits<'_, S>,
    literals: &Code,
    distances: &Code,
    out: &mut Unpacked,
    sink: &mut K,
) -> Result<(), Refusal> {
    loop {
        let symbol = literals.decode(bits)?;
        match symbol {
            0..=255 => out.push(symbol as u8, sink)?,
            256 => return Ok(()),
            257..=285 => {
                let index = usize::from(symbol - 257);
                let base = LENGTH_BASE.get(index).copied().unwrap_or(0);
                let extra = LENGTH_EXTRA.get(index).copied().unwrap_or(0);
                let length = usize::from(base) + bits.take(u32::from(extra))? as usize;
                let code = usize::from(distances.decode(bits)?);
                let (Some(base), Some(extra)) = (DISTANCE_BASE.get(code), DISTANCE_EXTRA.get(code)) else {
                    // Distance codes 30 and 31 never stand for a distance.
                    return Err(Refusal::Damaged(MEANINGLESS));
                };
                let distance = usize::from(*base) + bits.take(u32::from(*extra))? as usize;
                out.copy(distance, length, sink)?;
            }
            // Codes 286 and 287 have a place in the fixed code but never
            // stand for anything.
            _ => return Err(Refusal::Damaged(MEANINGLESS)),
        }
    }
}
