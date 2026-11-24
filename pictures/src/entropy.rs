//! A JPEG's packed data: what follows each scan's header, the coefficients
//! of its blocks packed with Huffman codes (ITU-T T.81, Annex F for
//! sequential frames, Annex G for progressive ones). The bits are read
//! highest first; a byte FF of the data is sent as FF 00, and any other FF
//! begins a marker, which ends the data (B.1.1.5, F.1.2.3). Notes:
//! `docs/pictures.md`, "JPEG".
//!
//! The section of T.81 that each step follows is named beside it.

use alloc::vec;
use alloc::vec::Vec;

use crate::Refusal;

// What goes wrong, in the words the kernel says after "it is damaged:".
pub(crate) const OVERFULL: &str = "a table of codes has more codes than can be";
const NO_SUCH_CODE: &str = "its data holds a code that its table does not have";
const MEANINGLESS: &str = "its data holds a code that means nothing";
const SHORT_DATA: &str = "a scan's data ends before its last unit";
const EXTRA_DATA: &str = "a scan's data goes on where a marker must come";
const BAD_FILL: &str = "its data holds fill bytes that no marker follows";
pub(crate) const BAD_RESTART: &str = "a restart marker is missing or out of turn";
const PAST_END: &str = "a run of zeros goes past the end of its band";
const TOO_LARGE: &str = "a coefficient is larger than 16 bits hold";

/// Where each of a block's 64 coefficients, in the zig-zag order they are
/// sent in, lies in the block's natural order: row by row, 8 to a row (A.3.6,
/// Figure A.6).
pub(crate) const ZIGZAG: [u8; 64] = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28, 35,
    42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62,
    63,
];

/// The longest code, in bits (Annex C).
const LONGEST: u32 = 16;

/// Codes this long or shorter are found with one look in a table of 2^9
/// entries; the longer ones length by length (see `Bits::decode`).
const QUICK_BITS: u32 = 9;

// ---------- Codes ----------

/// A Huffman table (B.2.4.2, Annex C): for each length from 1 to 16, how many
/// codes it has (`count`), the first of them (`first`), and where the value
/// of that first code is in `values`, which lists the values of the shorter
/// codes first (`start`). `quick` is looked up with the next nine bits: for a
/// code of at most nine bits it holds the code's value times 16 plus its
/// length, and 0 otherwise.
pub(crate) struct Code {
    count: [u32; LONGEST as usize + 1],
    first: [u32; LONGEST as usize + 1],
    start: [u32; LONGEST as usize + 1],
    values: Vec<u8>,
    quick: Vec<u16>,
}

impl Code {
    /// Builds a table from its 16 counts, how many codes of each length it
    /// has, and its values, as many as the counts add up to. The codes of
    /// each length are consecutive numbers, after those of the shorter
    /// lengths, each count doubled for the next length (C.2). The code of
    /// all 1-bits of any length is kept to begin longer codes, so a table
    /// whose codes reach it has more codes than can be (Annex C).
    pub(crate) fn new(counts: &[u8], values: &[u8]) -> Result<Code, Refusal> {
        let mut code = Code {
            count: [0; LONGEST as usize + 1],
            first: [0; LONGEST as usize + 1],
            start: [0; LONGEST as usize + 1],
            values: values.to_vec(),
            quick: vec![0; 1 << QUICK_BITS],
        };
        let mut next = 0u32;
        let mut start = 0u32;
        for (length, many) in (1..=LONGEST).zip(counts) {
            let many = u32::from(*many);
            if let (Some(count), Some(first), Some(begins)) = (
                code.count.get_mut(length as usize),
                code.first.get_mut(length as usize),
                code.start.get_mut(length as usize),
            ) {
                (*count, *first, *begins) = (many, next, start);
            }
            next += many;
            start += many;
            if next >= 1 << length {
                return Err(Refusal::Damaged(OVERFULL));
            }
            next <<= 1;
        }

        // The quick table: every entry whose first bits are a short code
        // holds it.
        for length in 1..=QUICK_BITS {
            let (Some(count), Some(first), Some(begins)) =
                (code.count.get(length as usize), code.first.get(length as usize), code.start.get(length as usize))
            else {
                continue;
            };
            for number in 0..*count {
                let value = u16::from(code.values.get((begins + number) as usize).copied().unwrap_or(0));
                let entry = (value << 4) | length as u16;
                let from = ((first + number) << (QUICK_BITS - length)) as usize;
                let to = ((first + number + 1) << (QUICK_BITS - length)) as usize;
                for slot in code.quick.get_mut(from..to).unwrap_or(&mut []) {
                    *slot = entry;
                }
            }
        }
        Ok(code)
    }
}

// ---------- Reading bits ----------

/// Why the data being read has ended, once it has.
#[derive(Clone, Copy, PartialEq, Eq)]
enum End {
    NotYet,
    /// A marker came: its code. `Bits::at` is where its first FF lies.
    Marker(u8),
    /// The file ran out.
    RanOut,
    /// Fill bytes (FF) came, and then a byte 00, which is no marker.
    BadFill,
}

/// Reads one scan's data as bits, highest bit of each byte first (F.2.2.5).
/// Up to 64 bits wait in `held`, the next one highest. When the data has
/// ended, zeros are put in its place so that a code can still be looked up,
/// and `made_up` counts them: taking any of them means the data ended too
/// soon.
pub(crate) struct Bits<'a> {
    file: &'a [u8],
    /// Where the next byte of the data is.
    at: usize,
    held: u64,
    count: u32,
    made_up: u32,
    end: End,
}

impl<'a> Bits<'a> {
    /// Reads the data that begins at `at` in `file`.
    pub(crate) fn new(file: &'a [u8], at: usize) -> Bits<'a> {
        Bits { file, at, held: 0, count: 0, made_up: 0, end: End::NotYet }
    }

    /// The next byte of the data, or none once a marker or the end of the
    /// file has come, which `end` then records. A byte FF of the data is
    /// sent as FF 00 (F.1.2.3); any other FF begins a marker, and more FFs
    /// before a marker are fill bytes (B.1.1.2).
    fn next_byte(&mut self) -> Option<u8> {
        if self.end != End::NotYet {
            return None;
        }
        let Some(byte) = self.file.get(self.at).copied() else {
            self.end = End::RanOut;
            return None;
        };
        if byte != 0xFF {
            self.at += 1;
            return Some(byte);
        }
        let mut after = self.at + 1;
        while self.file.get(after) == Some(&0xFF) {
            after += 1;
        }
        match self.file.get(after).copied() {
            None => self.end = End::RanOut,
            Some(0) if after == self.at + 1 => {
                self.at = after + 1;
                return Some(0xFF);
            }
            Some(0) => self.end = End::BadFill,
            Some(code) => self.end = End::Marker(code),
        }
        None
    }

    /// Fills `held` with whole bytes until it has more than 56 bits.
    fn fill(&mut self) {
        while self.count <= 56 {
            match self.next_byte() {
                Some(byte) => self.held |= u64::from(byte) << (56 - self.count),
                None => self.made_up += 8,
            }
            self.count += 8;
        }
    }

    /// How many of the held bits really came from the data.
    fn real(&self) -> u32 {
        self.count.saturating_sub(self.made_up)
    }

    /// What it means that bits were wanted after the data ended.
    fn ended(&self) -> Refusal {
        match self.end {
            End::RanOut => Refusal::CutShort,
            End::BadFill => Refusal::Damaged(BAD_FILL),
            End::Marker(_) | End::NotYet => Refusal::Damaged(SHORT_DATA),
        }
    }

    fn drop_bits(&mut self, n: u32) {
        self.held = self.held.checked_shl(n).unwrap_or(0);
        self.count -= n;
    }

    /// Takes `n` bits, at most 16, as a number whose highest bit came first.
    pub(crate) fn take(&mut self, n: u32) -> Result<u32, Refusal> {
        if n == 0 {
            return Ok(0);
        }
        if self.count < n {
            self.fill();
        }
        if n > self.real() {
            return Err(self.ended());
        }
        let value = (self.held >> (64 - n)) as u32;
        self.drop_bits(n);
        Ok(value)
    }

    /// Takes the `size` bits that follow a code and gives the number they
    /// stand for: those that begin with 0 are negative (F.2.2.1, RECEIVE and
    /// EXTEND, Figure F.12). `size` is at most 15.
    pub(crate) fn number(&mut self, size: u32) -> Result<i32, Refusal> {
        if size == 0 {
            return Ok(0);
        }
        let bits = self.take(size)? as i32;
        Ok(if bits < 1 << (size - 1) { bits - (1 << size) + 1 } else { bits })
    }

    /// Reads one code of `code`'s table and gives its value (F.2.2.3). A
    /// code of at most nine bits is found in the quick table; a longer one
    /// length by length.
    pub(crate) fn decode(&mut self, code: &Code) -> Result<u8, Refusal> {
        if self.count < LONGEST {
            self.fill();
        }
        let ahead = (self.held >> (64 - LONGEST)) as u32;
        let quick = code.quick.get((ahead >> (LONGEST - QUICK_BITS)) as usize).copied().unwrap_or(0);
        if quick != 0 {
            let length = u32::from(quick & 0xf);
            if length > self.real() {
                return Err(self.ended());
            }
            self.drop_bits(length);
            return Ok((quick >> 4) as u8);
        }
        for length in QUICK_BITS + 1..=LONGEST {
            let bits = ahead >> (LONGEST - length);
            let (Some(count), Some(first), Some(start)) =
                (code.count.get(length as usize), code.first.get(length as usize), code.start.get(length as usize))
            else {
                break;
            };
            if bits >= *first && bits - first < *count {
                if length > self.real() {
                    return Err(self.ended());
                }
                self.drop_bits(length);
                return code.values.get((start + bits - first) as usize).copied().ok_or(Refusal::Damaged(NO_SUCH_CODE));
            }
        }
        // No code fits. If some of the bits were made up after the end of
        // the data, it ended too soon; otherwise the code is in no table.
        if self.real() < LONGEST { Err(self.ended()) } else { Err(Refusal::Damaged(NO_SUCH_CODE)) }
    }

    /// Ends a run of data: what is left of the byte being read is padding
    /// (F.1.2.3), and no whole byte of data may be left before the marker.
    fn finish_data(&mut self) -> Result<(), Refusal> {
        self.drop_bits(self.count % 8);
        if self.real() > 0 || self.next_byte().is_some() {
            return Err(Refusal::Damaged(EXTRA_DATA));
        }
        Ok(())
    }

    /// Ends a restart interval: the data must end with the restart marker
    /// RSTn of `number`, the next of the eight in turn (B.2.1), and the next
    /// interval's data begins after it.
    pub(crate) fn restart(&mut self, number: u8) -> Result<(), Refusal> {
        self.finish_data()?;
        match self.end {
            End::Marker(code) if code == 0xD0 + number => {}
            End::Marker(_) => return Err(Refusal::Damaged(BAD_RESTART)),
            _ => return Err(self.ended()),
        }
        let mut after = self.at;
        while self.file.get(after) == Some(&0xFF) {
            after += 1;
        }
        *self = Bits::new(self.file, after + 1);
        Ok(())
    }

    /// Ends the scan: its data must end with a marker other than a restart
    /// marker, since none follows the last interval (B.2.1). Gives where the
    /// marker begins.
    pub(crate) fn end_of_scan(&mut self) -> Result<usize, Refusal> {
        self.finish_data()?;
        match self.end {
            End::Marker(0xD0..=0xD7) => Err(Refusal::Damaged(BAD_RESTART)),
            End::Marker(_) => Ok(self.at),
            _ => Err(self.ended()),
        }
    }
}

// ---------- Blocks ----------

/// For each coefficient, in zig-zag order, where it is kept in a block read
/// at n dots a side: (row) x n + (column) for the first n by n of the block,
/// and 255 for the others, which are not kept.
pub(crate) struct Keep([u8; 64]);

impl Keep {
    pub(crate) fn new(n: usize) -> Keep {
        let mut places = [255u8; 64];
        for (place, natural) in places.iter_mut().zip(ZIGZAG) {
            let (row, column) = (usize::from(natural) / 8, usize::from(natural) % 8);
            if row < n && column < n {
                *place = (row * n + column) as u8;
            }
        }
        Keep(places)
    }
}

/// A block's coefficients as they are kept: the first n by n, row by row
/// (`kept`), and a bit for each of the 64, by its place in the natural
/// order, saying whether it is non-zero yet (`nonzero`), which a later scan
/// of successive approximation needs to know of every coefficient
/// (G.1.2.3).
pub(crate) struct Block<'a> {
    pub(crate) kept: &'a mut [i16],
    pub(crate) nonzero: &'a mut u64,
}

impl Block<'_> {
    /// Sets the coefficient at `k` in zig-zag order.
    fn set(&mut self, keep: &Keep, k: usize, value: i16) {
        if value != 0 {
            *self.nonzero |= ZIGZAG.get(k).map_or(0, |natural| 1 << natural);
        }
        if let Some(kept) = keep.0.get(k).and_then(|place| self.kept.get_mut(usize::from(*place))) {
            *kept = value;
        }
    }

    fn is_nonzero(&self, k: usize) -> bool {
        ZIGZAG.get(k).is_some_and(|natural| *self.nonzero & (1 << natural) != 0)
    }

    /// Makes the coefficient at `k`, non-zero already, `step` larger in
    /// size, unless that bit is set already (G.1.2.3).
    fn refine(&mut self, keep: &Keep, k: usize, step: i32) -> Result<(), Refusal> {
        if let Some(kept) = keep.0.get(k).and_then(|place| self.kept.get_mut(usize::from(*place))) {
            let value = i32::from(*kept);
            if value & step == 0 {
                let refined = if value >= 0 { value + step } else { value - step };
                *kept = i16::try_from(refined).map_err(|_| Refusal::Damaged(TOO_LARGE))?;
            }
        }
        Ok(())
    }
}

/// The band of coefficients a scan sends, from `start` to `end` in zig-zag
/// order, and the point transform: the bits of each value below `low` are
/// not sent (A.4).
#[derive(Clone, Copy)]
pub(crate) struct Band {
    pub(crate) start: usize,
    pub(crate) end: usize,
    pub(crate) low: u32,
}

/// A DC coefficient as a sequential scan or the first progressive scan
/// sends it: the difference from the last block's of the same component,
/// whose size in bits comes first as a code (F.2.2.1; G.1.2.1 shifts it by
/// the point transform).
pub(crate) fn dc_first(bits: &mut Bits<'_>, dc: &Code, prediction: &mut i32, low: u32, block: &mut Block<'_>) -> Result<(), Refusal> {
    let size = bits.decode(dc)?;
    if size > 15 {
        return Err(Refusal::Damaged(MEANINGLESS));
    }
    // The prediction stays within 16 bits (checked below), so the sum fits.
    let sum = *prediction + bits.number(u32::from(size))?;
    let value = i16::try_from(sum << low).map_err(|_| Refusal::Damaged(TOO_LARGE))?;
    *prediction = sum;
    if let Some(first) = block.kept.first_mut() {
        *first = value;
    }
    if value != 0 {
        *block.nonzero |= 1;
    }
    Ok(())
}

/// A later progressive scan of DC coefficients: one more bit of each
/// (G.1.2.1).
pub(crate) fn dc_refine(bits: &mut Bits<'_>, low: u32, block: &mut Block<'_>) -> Result<(), Refusal> {
    if bits.take(1)? == 1 {
        if let Some(first) = block.kept.first_mut() {
            *first |= 1i16.checked_shl(low).unwrap_or(0);
        }
        *block.nonzero |= 1;
    }
    Ok(())
}

/// A block of a sequential scan: its DC coefficient, then its AC ones, each
/// sent as a code that gives the run of zeros before it and its size in
/// bits, and then its bits (F.2.2.2). The code 0 ends the block early (EOB),
/// and the code F0 stands for 16 zeros (ZRL).
pub(crate) fn sequential_block(
    bits: &mut Bits<'_>,
    dc: &Code,
    ac: &Code,
    prediction: &mut i32,
    block: &mut Block<'_>,
    keep: &Keep,
) -> Result<(), Refusal> {
    dc_first(bits, dc, prediction, 0, block)?;
    let mut k = 1;
    while k <= 63 {
        let code = bits.decode(ac)?;
        let (run, size) = (usize::from(code >> 4), u32::from(code & 15));
        if size == 0 {
            match run {
                0 => break,
                15 => {
                    k += 16;
                    if k > 64 {
                        return Err(Refusal::Damaged(PAST_END));
                    }
                    continue;
                }
                _ => return Err(Refusal::Damaged(MEANINGLESS)),
            }
        }
        k += run;
        if k > 63 {
            return Err(Refusal::Damaged(PAST_END));
        }
        // At most 15 bits: it fits in 16.
        let value = bits.number(size)? as i16;
        block.set(keep, k, value);
        k += 1;
    }
    Ok(())
}

/// A block of the first progressive scan of a band of AC coefficients
/// (G.1.2.2): as in a sequential scan, but the codes 0, 10, 20 and so on to
/// E0 end this block and a run of the blocks after it (EOBn: 2^n blocks and
/// the number in the n bits that follow), whose coefficients in the band are
/// all zero. `eob_run` counts the blocks of the run still to come.
pub(crate) fn ac_first(
    bits: &mut Bits<'_>,
    ac: &Code,
    band: Band,
    eob_run: &mut u32,
    block: &mut Block<'_>,
    keep: &Keep,
) -> Result<(), Refusal> {
    if *eob_run > 0 {
        *eob_run -= 1;
        return Ok(());
    }
    let mut k = band.start;
    while k <= band.end {
        let code = bits.decode(ac)?;
        let (run, size) = (u32::from(code >> 4), u32::from(code & 15));
        if size == 0 {
            if run == 15 {
                k += 16;
                if k > band.end + 1 {
                    return Err(Refusal::Damaged(PAST_END));
                }
                continue;
            }
            *eob_run = (1 << run) + bits.take(run)? - 1;
            return Ok(());
        }
        k += run as usize;
        if k > band.end {
            return Err(Refusal::Damaged(PAST_END));
        }
        let value = bits.number(size)? << band.low;
        if value.abs() > i32::from(i16::MAX) {
            return Err(Refusal::Damaged(TOO_LARGE));
        }
        block.set(keep, k, value as i16);
        k += 1;
    }
    Ok(())
}

/// A block of a later progressive scan of a band of AC coefficients
/// (G.1.2.3): one more bit of each. A coefficient that is zero so far either
/// stays zero or becomes 1 or -1 at that bit, sent as in a first scan, but
/// with the run counting only the coefficients that are zero so far; every
/// coefficient that is non-zero already and is passed over, or lies in the
/// rest of the band after an EOBn, has one bit sent for it, a correction
/// bit, which makes it larger in size when it is 1.
pub(crate) fn ac_refine(
    bits: &mut Bits<'_>,
    ac: &Code,
    band: Band,
    eob_run: &mut u32,
    block: &mut Block<'_>,
    keep: &Keep,
) -> Result<(), Refusal> {
    let step = 1i32 << band.low;
    let mut k = band.start;
    if *eob_run == 0 {
        while k <= band.end {
            let code = bits.decode(ac)?;
            let (mut zeros, size) = (u32::from(code >> 4), code & 15);
            let mut value = 0;
            match size {
                1 => value = if bits.take(1)? == 1 { step } else { -step },
                0 if zeros != 15 => {
                    *eob_run = (1 << zeros) + bits.take(zeros)?;
                    break;
                }
                0 => {}
                _ => return Err(Refusal::Damaged(MEANINGLESS)),
            }
            // Pass over the coefficients that are non-zero already, each
            // with its correction bit, and `zeros` zero ones, to the zero
            // coefficient the code is for (ZRL: the sixteenth).
            loop {
                if k > band.end {
                    return Err(Refusal::Damaged(PAST_END));
                }
                if block.is_nonzero(k) {
                    if bits.take(1)? == 1 {
                        block.refine(keep, k, step)?;
                    }
                } else if zeros == 0 {
                    break;
                } else {
                    zeros -= 1;
                }
                k += 1;
            }
            if value != 0 {
                block.set(keep, k, value as i16);
            }
            k += 1;
        }
    }
    if *eob_run > 0 {
        while k <= band.end {
            if block.is_nonzero(k) && bits.take(1)? == 1 {
                block.refine(keep, k, step)?;
            }
            k += 1;
        }
        *eob_run -= 1;
    }
    Ok(())
}
