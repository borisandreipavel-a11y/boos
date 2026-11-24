//! PNG pictures (RFC 2083, PNG 1.0; the third edition of 2025 adds no part a
//! reader must know). A PNG file is an eight-byte signature and then parts
//! ("chunks"), each with its length, a four-letter name, its data and a check
//! value: IHDR first, the head; PLTE, a palette; IDAT, the packed dots, in
//! one run of parts; IEND last. Parts whose name begins with a small letter
//! may be passed over; a reader must know every other part.
//!
//! The file is read twice: once to check its parts and their order and to
//! find the head, the palette and the transparency; then the packed dots are
//! unpacked, row by row, unfiltered, turned into four bytes a dot, and
//! shrunk to fit the room (`shrink.rs`). Notes: `docs/pictures.md`.
//!
//! The section of RFC 2083 that each step follows is named beside it.

use alloc::vec;
use alloc::vec::Vec;

use crate::check::crc_update;
use crate::shrink::{Shrink, fitted_size};
use crate::unpack::{Sink, Source, zlib_unpack};
use crate::{Limits, Picture, Refusal};

/// Every PNG file begins with these eight bytes (RFC 2083, 3.1).
const SIGNATURE: [u8; 8] = [137, 80, 78, 71, 13, 10, 26, 10];

// What goes wrong, in the words the kernel says after "it is damaged:".
const LONG_PART: &str = "a part says it is longer than a PNG allows";
const BAD_CHECK: &str = "a part does not match its check value";
const BAD_NAME: &str = "a part's name is not four letters";
const NO_HEAD: &str = "it does not begin with its head";
const HEAD_LENGTH: &str = "its head is not 13 bytes long";
const BAD_SIZE: &str = "its width or height is not as a PNG allows";
const NO_SUCH_COLOUR: &str = "it names a kind of colour that does not exist";
const BAD_DEPTH: &str = "its depth does not go with its kind of colour";
const NOT_DEFLATE: &str = "it names a packing other than deflate";
const NO_SUCH_FILTERING: &str = "it names a filtering that does not exist";
const NO_SUCH_INTERLACING: &str = "it names an interlacing that does not exist";
const TWO_HEADS: &str = "it has two heads";
const OUT_OF_ORDER: &str = "its parts are not in the order a PNG must have";
const BAD_PALETTE: &str = "its palette is not as a palette must be";
const TWO_PALETTES: &str = "it has two palettes";
const NO_PALETTE_HERE: &str = "it has a palette, which its kind of colour may not have";
const NO_PALETTE: &str = "it has no palette, which its kind of colour needs";
const BAD_TRANSPARENCY: &str = "its transparency part is not as it must be";
const TWO_TRANSPARENCIES: &str = "it has two transparency parts";
const DOTS_SPLIT: &str = "its packed dots are not in one run of parts";
const NO_DOTS: &str = "it has no dots";
const END_NOT_EMPTY: &str = "its end part is not empty";
const NO_SUCH_FILTER: &str = "a row begins with a filter that does not exist";
const NO_SUCH_ENTRY: &str = "a dot names a colour its palette does not have";
const MORE_DOTS: &str = "it holds more dots than its size";
const FEWER_DOTS: &str = "it holds fewer dots than its size";

/// What a PNG's head says (RFC 2083, 4.1.1).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PngHead {
    /// Its size in dots.
    pub width: u32,
    pub height: u32,
    /// How many bits each sample has: 1, 2, 4, 8 or 16.
    pub depth: u8,
    /// Its kind of colour: 0 grey, 2 red-green-blue, 3 a palette's colours,
    /// 4 grey with alpha, 6 red-green-blue with alpha.
    pub colour: u8,
    /// Whether it comes in Adam7's seven passes.
    pub interlaced: bool,
}

impl PngHead {
    /// How many samples each dot has.
    fn channels(&self) -> u64 {
        match self.colour {
            2 => 3,
            4 => 2,
            6 => 4,
            _ => 1,
        }
    }

    fn bits_per_dot(&self) -> u64 {
        self.channels() * u64::from(self.depth)
    }

    /// How many bytes a row of `width` dots takes, its filter byte left out:
    /// a row begins on a byte, and dots of fewer than eight bits are packed
    /// several to a byte (RFC 2083, 2.3).
    fn row_bytes(&self, width: u64) -> u64 {
        (width * self.bits_per_dot()).div_ceil(8)
    }

    /// How many bytes before a byte the filters look back: the bytes of a
    /// whole dot, at least one (RFC 2083, 6.3).
    fn filter_step(&self) -> usize {
        (self.bits_per_dot() / 8).max(1) as usize
    }
}

/// Where each of Adam7's seven passes begins and how far it steps, across
/// and down, read from RFC 2083's pattern (2.6): x0, y0, dx, dy. A picture
/// that is not interlaced is one pass that begins at 0 and steps by 1.
const ADAM7: [(u32, u32, u32, u32); 7] =
    [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)];
const WHOLE: [(u32, u32, u32, u32); 1] = [(0, 0, 1, 1)];

/// How many dots a pass has across (or down): those of `start`, `start +
/// step`, and so on below `size`.
fn pass_size(size: u32, start: u32, step: u32) -> u32 {
    if size <= start { 0 } else { (size - start).div_ceil(step.max(1)) }
}

fn passes(head: &PngHead) -> &'static [(u32, u32, u32, u32)] {
    if head.interlaced { &ADAM7 } else { &WHOLE }
}

// ---------- Parts ----------

/// One part of a PNG file: its name, its data, and where the next part
/// begins.
struct Part<'a> {
    name: [u8; 4],
    data: &'a [u8],
    next: usize,
}

/// Reads the part that begins at `at`, and checks its length, its name and
/// its check value. A file that ends inside it is cut short.
fn part_at(file: &[u8], at: usize) -> Result<Part<'_>, Refusal> {
    let length = number(file, at).ok_or(Refusal::CutShort)?;
    if length > 0x7fff_ffff {
        return Err(Refusal::Damaged(LONG_PART));
    }
    let name_at = at.checked_add(4).ok_or(Refusal::CutShort)?;
    let data_at = name_at.checked_add(4).ok_or(Refusal::CutShort)?;
    let end = data_at.checked_add(length as usize).ok_or(Refusal::CutShort)?;
    let name_bytes = file.get(name_at..data_at).ok_or(Refusal::CutShort)?;
    let data = file.get(data_at..end).ok_or(Refusal::CutShort)?;
    let stored = number(file, end).ok_or(Refusal::CutShort)?;
    let mut name = [0u8; 4];
    for (slot, byte) in name.iter_mut().zip(name_bytes) {
        *slot = *byte;
    }
    // The check value covers the name and the data (3.2).
    if !crc_update(crc_update(0xffff_ffff, &name), data) != stored {
        return Err(Refusal::Damaged(BAD_CHECK));
    }
    if !name.iter().all(|byte| byte.is_ascii_alphabetic()) {
        return Err(Refusal::Damaged(BAD_NAME));
    }
    Ok(Part { name, data, next: end + 4 })
}

/// A four-byte number, highest byte first (3.1).
fn number(bytes: &[u8], at: usize) -> Option<u32> {
    let four = bytes.get(at..at.checked_add(4)?)?;
    let mut value = 0u32;
    for byte in four {
        value = (value << 8) | u32::from(*byte);
    }
    Some(value)
}

/// A part a reader must know: its name begins with a capital (3.3).
fn critical(name: &[u8; 4]) -> bool {
    name.first().is_some_and(u8::is_ascii_uppercase)
}

/// The signature, which must come first. A file that is shorter than it but
/// begins as it does is cut short.
fn signature_check(file: &[u8]) -> Result<(), Refusal> {
    if file.starts_with(&SIGNATURE) {
        Ok(())
    } else if SIGNATURE.starts_with(file) {
        Err(Refusal::CutShort)
    } else {
        Err(Refusal::NotPng)
    }
}

/// Reads and checks the head's 13 bytes (4.1.1).
fn head_read(data: &[u8]) -> Result<PngHead, Refusal> {
    if data.len() != 13 {
        return Err(Refusal::Damaged(HEAD_LENGTH));
    }
    let width = number(data, 0).unwrap_or(0);
    let height = number(data, 4).unwrap_or(0);
    let byte = |at: usize| data.get(at).copied().unwrap_or(0);
    let (depth, colour, packing, filtering, interlacing) = (byte(8), byte(9), byte(10), byte(11), byte(12));
    if width == 0 || height == 0 || width > 0x7fff_ffff || height > 0x7fff_ffff {
        return Err(Refusal::Damaged(BAD_SIZE));
    }
    let depths: &[u8] = match colour {
        0 => &[1, 2, 4, 8, 16],
        2 | 4 | 6 => &[8, 16],
        3 => &[1, 2, 4, 8],
        _ => return Err(Refusal::Damaged(NO_SUCH_COLOUR)),
    };
    if !depths.contains(&depth) {
        return Err(Refusal::Damaged(BAD_DEPTH));
    }
    if packing != 0 {
        return Err(Refusal::Damaged(NOT_DEFLATE));
    }
    if filtering != 0 {
        return Err(Refusal::Damaged(NO_SUCH_FILTERING));
    }
    if interlacing > 1 {
        return Err(Refusal::Damaged(NO_SUCH_INTERLACING));
    }
    Ok(PngHead { width, height, depth, colour, interlaced: interlacing == 1 })
}

/// What a PNG's head says, read from the signature and the first part only:
/// for saying a picture's size without reading all of it.
pub fn png_head(file: &[u8]) -> Result<PngHead, Refusal> {
    signature_check(file)?;
    let first = part_at(file, SIGNATURE.len())?;
    if &first.name != b"IHDR" {
        return Err(Refusal::Damaged(NO_HEAD));
    }
    head_read(first.data)
}

/// What the first reading of a file finds: the head; the palette, three
/// bytes a colour; the alphas the transparency part gives the palette's
/// colours; the one grey or colour that the transparency part makes
/// see-through, for pictures without a palette; and where the run of
/// packed-dot parts begins.
struct Layout<'a> {
    head: PngHead,
    palette: &'a [u8],
    alphas: &'a [u8],
    see_through: Option<[u32; 3]>,
    dots_at: usize,
}

/// Reads every part once, in order, checking each and the order they come
/// in, up to the end part. Parts after it are not read.
fn layout(file: &[u8]) -> Result<Layout<'_>, Refusal> {
    signature_check(file)?;
    let first = part_at(file, SIGNATURE.len())?;
    if &first.name != b"IHDR" {
        return Err(Refusal::Damaged(NO_HEAD));
    }
    let head = head_read(first.data)?;
    let mut palette: Option<&[u8]> = None;
    let mut transparency: Option<&[u8]> = None;
    let mut dots_at = None;
    let mut last_was_dots = false;
    let mut at = first.next;
    loop {
        let part = part_at(file, at)?;
        let this_is_dots = &part.name == b"IDAT";
        match &part.name {
            b"IHDR" => return Err(Refusal::Damaged(TWO_HEADS)),
            b"PLTE" => {
                // At most one palette, before the dots and before the
                // transparency, and only where colours may have one (4.1.2).
                if dots_at.is_some() || transparency.is_some() {
                    return Err(Refusal::Damaged(OUT_OF_ORDER));
                }
                if palette.is_some() {
                    return Err(Refusal::Damaged(TWO_PALETTES));
                }
                if head.colour == 0 || head.colour == 4 {
                    return Err(Refusal::Damaged(NO_PALETTE_HERE));
                }
                let colours = part.data.len() / 3;
                if part.data.len() % 3 != 0 || colours == 0 || colours > 256 {
                    return Err(Refusal::Damaged(BAD_PALETTE));
                }
                if head.colour == 3 && colours > 1usize << head.depth {
                    return Err(Refusal::Damaged(BAD_PALETTE));
                }
                palette = Some(part.data);
            }
            b"tRNS" => {
                // Before the dots, after the palette, not where every dot
                // has its own alpha (4.2.9).
                if dots_at.is_some() {
                    return Err(Refusal::Damaged(OUT_OF_ORDER));
                }
                if transparency.is_some() {
                    return Err(Refusal::Damaged(TWO_TRANSPARENCIES));
                }
                let right = match head.colour {
                    0 => part.data.len() == 2,
                    2 => part.data.len() == 6,
                    3 => match palette {
                        Some(colours) => part.data.len() <= colours.len() / 3,
                        None => return Err(Refusal::Damaged(OUT_OF_ORDER)),
                    },
                    _ => false,
                };
                if !right {
                    return Err(Refusal::Damaged(BAD_TRANSPARENCY));
                }
                transparency = Some(part.data);
            }
            b"IDAT" => {
                // The packed dots, in one run of parts; their boundaries mean
                // nothing, and a part may hold none of them (4.1.3).
                match dots_at {
                    None => dots_at = Some(at),
                    Some(_) if !last_was_dots => return Err(Refusal::Damaged(DOTS_SPLIT)),
                    Some(_) => {}
                }
            }
            b"IEND" => {
                if !part.data.is_empty() {
                    return Err(Refusal::Damaged(END_NOT_EMPTY));
                }
                break;
            }
            name if critical(name) => return Err(Refusal::UnknownPart(*name)),
            _ => {}
        }
        last_was_dots = this_is_dots;
        at = part.next;
    }
    let dots_at = dots_at.ok_or(Refusal::Damaged(NO_DOTS))?;
    if head.colour == 3 && palette.is_none() {
        return Err(Refusal::Damaged(NO_PALETTE));
    }
    let (alphas, see_through) = match (head.colour, transparency) {
        (3, Some(data)) => (data, None),
        (0, Some(data)) => {
            let grey = u32::from(number2(data, 0));
            (&[][..], Some([grey, grey, grey]))
        }
        (2, Some(data)) => (&[][..], Some([u32::from(number2(data, 0)), u32::from(number2(data, 2)), u32::from(number2(data, 4))])),
        _ => (&[][..], None),
    };
    Ok(Layout { head, palette: if head.colour == 3 { palette.unwrap_or(&[]) } else { &[] }, alphas, see_through, dots_at })
}

/// A two-byte number, highest byte first.
fn number2(bytes: &[u8], at: usize) -> u16 {
    let high = bytes.get(at).copied().unwrap_or(0);
    let low = bytes.get(at + 1).copied().unwrap_or(0);
    u16::from(high) << 8 | u16::from(low)
}

// ---------- The packed dots ----------

/// The packed dots as one stream of bytes, read from the run of IDAT parts
/// one after another (4.1.3). The parts were checked by the first reading.
struct PackedDots<'a> {
    file: &'a [u8],
    next_part: usize,
    data: &'a [u8],
    at: usize,
    ended: bool,
}

impl<'a> PackedDots<'a> {
    fn new(file: &'a [u8], first: usize) -> PackedDots<'a> {
        PackedDots { file, next_part: first, data: &[], at: 0, ended: false }
    }
}

impl Source for PackedDots<'_> {
    fn next_byte(&mut self) -> Option<u8> {
        loop {
            if let Some(byte) = self.data.get(self.at) {
                self.at += 1;
                return Some(*byte);
            }
            if self.ended {
                return None;
            }
            match part_at(self.file, self.next_part) {
                Ok(part) if &part.name == b"IDAT" => {
                    self.data = part.data;
                    self.at = 0;
                    self.next_part = part.next;
                }
                _ => self.ended = true,
            }
        }
    }
}

// ---------- Rows ----------

/// Takes the unpacked bytes, a row at a time: unfilters each row, turns its
/// dots into four bytes each, and hands them to the shrinking, or, for an
/// interlaced picture, puts them in their places in the whole picture first.
struct Rows<'a> {
    layout: &'a Layout<'a>,
    passes: &'static [(u32, u32, u32, u32)],
    pass: usize,
    pass_width: u32,
    pass_height: u32,
    row: u32,
    row_length: usize,
    filling: Vec<u8>,
    before: Vec<u8>,
    dots: Vec<u8>,
    whole: Vec<u8>,
    shrink: Option<Shrink>,
    done: bool,
}

impl<'a> Rows<'a> {
    fn new(layout: &'a Layout<'a>, shrink: Shrink) -> Result<Rows<'a>, Refusal> {
        let head = &layout.head;
        let width = head.width as usize;
        // The largest row any pass has is the picture's own width.
        let longest_row = usize::try_from(head.row_bytes(u64::from(head.width)))
            .map_err(|_| Refusal::TooLarge { width: head.width, height: head.height })?;
        let whole_bytes = if head.interlaced { width * head.height as usize * 4 } else { 0 };
        let mut rows = Rows {
            layout,
            passes: passes(head),
            pass: 0,
            pass_width: 0,
            pass_height: 0,
            row: 0,
            row_length: 0,
            filling: Vec::with_capacity(longest_row + 1),
            before: Vec::with_capacity(longest_row),
            dots: Vec::with_capacity(width * 4),
            whole: vec![0; whole_bytes],
            shrink: Some(shrink),
            done: false,
        };
        rows.pass_begin(0);
        Ok(rows)
    }

    /// Goes to the first pass from `from` on that has dots; passes of a
    /// small picture may have none, and then no row of them comes (2.6).
    fn pass_begin(&mut self, from: usize) {
        let head = self.layout.head;
        let mut pass = from;
        while let Some((x0, y0, dx, dy)) = self.passes.get(pass).copied() {
            let width = pass_size(head.width, x0, dx);
            let height = pass_size(head.height, y0, dy);
            if width > 0 && height > 0 {
                self.pass = pass;
                self.pass_width = width;
                self.pass_height = height;
                self.row = 0;
                self.row_length = head.row_bytes(u64::from(width)) as usize + 1;
                // The row before a pass's first row counts as zeros (6.2).
                self.before.clear();
                self.before.resize(self.row_length - 1, 0);
                return;
            }
            pass += 1;
        }
        self.done = true;
    }

    /// A row has come whole: unfilter it, turn it into dots, and pass them on.
    fn row_done(&mut self) -> Result<(), Refusal> {
        let head = self.layout.head;
        let (filter, row) = self.filling.split_first_mut().ok_or(Refusal::Damaged(FEWER_DOTS))?;
        unfilter(*filter, row, &self.before, head.filter_step())?;
        dots_of_row(self.layout, row, self.pass_width, &mut self.dots)?;

        let (x0, y0, dx, dy) = self.passes.get(self.pass).copied().unwrap_or((0, 0, 1, 1));
        if head.interlaced {
            // Into the whole picture, at the places of this pass.
            let y = (y0 + self.row * dy) as usize;
            for (i, dot) in self.dots.as_chunks::<4>().0.iter().enumerate() {
                let x = x0 as usize + i * dx as usize;
                let at = (y * head.width as usize + x) * 4;
                if let Some(place) = self.whole.get_mut(at..at + 4) {
                    for (to, from) in place.iter_mut().zip(dot) {
                        *to = *from;
                    }
                }
            }
        } else if let Some(shrink) = self.shrink.as_mut() {
            shrink.take_row(self.row, &self.dots);
        }

        // This row is the one before the next.
        self.before.clear();
        self.before.extend_from_slice(row);
        self.filling.clear();
        self.row += 1;
        if self.row >= self.pass_height {
            self.pass_begin(self.pass + 1);
        }
        Ok(())
    }

    /// Once every row has come: the picture, shrunk to fit.
    fn finish(mut self) -> Result<Picture, Refusal> {
        if !self.done {
            return Err(Refusal::Damaged(FEWER_DOTS));
        }
        let mut shrink = self.shrink.take().ok_or(Refusal::Damaged(FEWER_DOTS))?;
        if self.layout.head.interlaced {
            let row_bytes = self.layout.head.width as usize * 4;
            for (y, row) in self.whole.chunks_exact(row_bytes.max(1)).enumerate() {
                shrink.take_row(y as u32, row);
            }
        }
        Ok(shrink.finish())
    }
}

impl Sink for Rows<'_> {
    fn take(&mut self, bytes: &[u8]) -> Result<(), Refusal> {
        let mut rest = bytes;
        while !rest.is_empty() {
            if self.done {
                return Err(Refusal::Damaged(MORE_DOTS));
            }
            let wanted = self.row_length.saturating_sub(self.filling.len());
            let (piece, after) = rest.split_at_checked(wanted.min(rest.len())).unwrap_or((rest, &[]));
            self.filling.extend_from_slice(piece);
            rest = after;
            if self.filling.len() >= self.row_length {
                self.row_done()?;
            }
        }
        Ok(())
    }
}

/// Undoes a row's filter (6): each byte was stored as the difference from a
/// guess made from the byte `step` bytes to its left (`a`), the byte above
/// it (`b`), and the byte above that left one (`c`); bytes left of the row
/// and above the first row count as zeros.
fn unfilter(filter: u8, row: &mut [u8], before: &[u8], step: usize) -> Result<(), Refusal> {
    if filter > 4 {
        return Err(Refusal::Damaged(NO_SUCH_FILTER));
    }
    if filter == 0 {
        return Ok(());
    }
    for i in 0..row.len() {
        let left = if i >= step { row.get(i - step).copied().unwrap_or(0) } else { 0 };
        let above = before.get(i).copied().unwrap_or(0);
        let above_left = if i >= step { before.get(i - step).copied().unwrap_or(0) } else { 0 };
        let guess = match filter {
            1 => left,
            2 => above,
            3 => ((u16::from(left) + u16::from(above)) / 2) as u8,
            _ => paeth(left, above, above_left),
        };
        if let Some(byte) = row.get_mut(i) {
            *byte = byte.wrapping_add(guess);
        }
    }
    Ok(())
}

/// Paeth's guess (6.6): of left, above and above-left, the one nearest to
/// left + above - above-left, ties going to left, then above.
fn paeth(left: u8, above: u8, above_left: u8) -> u8 {
    let (a, b, c) = (i16::from(left), i16::from(above), i16::from(above_left));
    let p = a + b - c;
    let (pa, pb, pc) = ((p - a).abs(), (p - b).abs(), (p - c).abs());
    if pa <= pb && pa <= pc {
        left
    } else if pb <= pc {
        above
    } else {
        above_left
    }
}

/// Turns an unfiltered row of `width` dots into four bytes a dot: red,
/// green, blue, alpha, each of 8 bits. Samples of fewer bits are stretched
/// to the full range; samples of 16 bits keep their high byte (10.4). A dot
/// whose samples match the transparency part's is see-through; the match is
/// made before any sample is changed (4.2.9).
fn dots_of_row(layout: &Layout<'_>, row: &[u8], width: u32, dots: &mut Vec<u8>) -> Result<(), Refusal> {
    let head = layout.head;
    let channels = head.channels() as usize;
    let depth = u32::from(head.depth);
    let sample = |dot: usize, channel: usize| -> u32 {
        let index = dot * channels + channel;
        match depth {
            16 => u32::from(number2(row, index * 2)),
            8 => u32::from(row.get(index).copied().unwrap_or(0)),
            _ => {
                // Dots of 1, 2 or 4 bits, the leftmost in the highest bits
                // of each byte (2.3).
                let bit = index * depth as usize;
                let byte = u32::from(row.get(bit / 8).copied().unwrap_or(0));
                let shift = 8 - depth - (bit % 8) as u32;
                (byte >> shift) & ((1 << depth) - 1)
            }
        }
    };
    let eight = |value: u32| -> u8 {
        match depth {
            16 => (value >> 8) as u8,
            8 => value as u8,
            _ => (value * 255 / ((1 << depth) - 1)) as u8,
        }
    };
    dots.clear();
    for dot in 0..width as usize {
        let bytes = match head.colour {
            0 => {
                let grey = sample(dot, 0);
                let alpha = if layout.see_through == Some([grey, grey, grey]) { 0 } else { 255 };
                let g = eight(grey);
                [g, g, g, alpha]
            }
            2 => {
                let (r, g, b) = (sample(dot, 0), sample(dot, 1), sample(dot, 2));
                let alpha = if layout.see_through == Some([r, g, b]) { 0 } else { 255 };
                [eight(r), eight(g), eight(b), alpha]
            }
            3 => {
                let entry = sample(dot, 0) as usize;
                let colour = layout.palette.get(entry * 3..entry * 3 + 3).ok_or(Refusal::Damaged(NO_SUCH_ENTRY))?;
                let alpha = layout.alphas.get(entry).copied().unwrap_or(255);
                [
                    colour.first().copied().unwrap_or(0),
                    colour.get(1).copied().unwrap_or(0),
                    colour.get(2).copied().unwrap_or(0),
                    alpha,
                ]
            }
            4 => {
                let grey = eight(sample(dot, 0));
                [grey, grey, grey, eight(sample(dot, 1))]
            }
            _ => [eight(sample(dot, 0)), eight(sample(dot, 1)), eight(sample(dot, 2)), eight(sample(dot, 3))],
        };
        dots.extend_from_slice(&bytes);
    }
    Ok(())
}

// ---------- The whole picture ----------

/// Reads a PNG picture and shrinks it to fit a room of `room_width` by
/// `room_height` dots, keeping its shape (see `fitted_size`). Every check
/// that can turn a picture down for its size is made before memory is set
/// aside for it.
pub fn png_picture(file: &[u8], room_width: u32, room_height: u32, limits: &Limits) -> Result<Picture, Refusal> {
    let layout = layout(file)?;
    let head = layout.head;
    let too_large = Refusal::TooLarge { width: head.width, height: head.height };
    let dots = u64::from(head.width) * u64::from(head.height);
    if head.width > limits.side_most || head.height > limits.side_most || dots > limits.dots_most {
        return Err(too_large);
    }
    if head.interlaced && dots > limits.interlaced_dots_most {
        return Err(too_large);
    }
    // The shown picture is never larger than the picture, which the limits
    // bound, so any room will do but an empty one.
    if room_width == 0 || room_height == 0 {
        return Err(Refusal::NoRoom);
    }
    let (shown_width, shown_height) = fitted_size(head.width, head.height, room_width, room_height);
    let shrink = Shrink::new(head.width, head.height, shown_width, shown_height);
    let mut rows = Rows::new(&layout, shrink)?;
    let mut packed = PackedDots::new(file, layout.dots_at);
    zlib_unpack(&mut packed, &mut rows)?;
    rows.finish()
}
