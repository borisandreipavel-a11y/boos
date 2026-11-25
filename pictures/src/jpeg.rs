//! JPEG photos (ITU-T T.81, the JPEG standard, also ISO/IEC 10918-1, and
//! JFIF 1.02). A JPEG file is a run of segments, each beginning with a
//! marker, the byte FF and a code: tables, the frame (the picture's size and
//! its colour components), and scans, each a header followed by the packed
//! data of some or all of the components (`entropy.rs`). Each component is
//! cut into blocks of 8 by 8 samples, and each block is sent as the 64
//! coefficients of its cosine transform. Colour components may have fewer
//! samples than the picture has dots (subsampling).
//!
//! The picture is read at the smallest of its whole size, a half, a quarter
//! and an eighth that is still at least as large as it is shown, from the
//! first n by n coefficients of each block (`transform.rs`), and then shrunk
//! the rest of the way (`shrink.rs`). A picture whose first scan holds all
//! its components is read a row of units at a time, as it comes; any other
//! keeps its blocks' coefficients until its last scan has come. A photo
//! whose Exif note says it was taken turned is turned back, so that it is
//! seen as it was taken (`turned`). Notes: `docs/pictures.md`.
//!
//! The section of T.81 that each step follows is named beside it.

use alloc::vec;
use alloc::vec::Vec;

use crate::entropy::{self, Band, Bits, Block, Code, Keep, OVERFULL, ZIGZAG};
use crate::shrink::{Shrink, fitted_size};
use crate::transform::{block_samples, rgb_of_ycc};
use crate::{JpegLimits, Picture, Refusal};

// What goes wrong, in the words the kernel says after "it is damaged:".
const NOT_A_MARKER: &str = "something stands between its segments that is not a marker";
const BAD_LENGTH: &str = "a segment's length does not fit what it holds";
const TWO_STARTS: &str = "it has a second start marker";
const STRAY_RESTART: &str = "a restart marker stands outside a scan's data";
const TWO_FRAMES: &str = "it has two frames";
const NO_FRAME: &str = "a scan or its end comes before its frame";
const BAD_PRECISION: &str = "its samples have a number of bits its kind of frame does not allow";
const NO_WIDTH: &str = "its width is 0";
const NO_COMPONENTS: &str = "it has no colour components";
const BAD_FACTORS: &str = "a component's sampling factors are not from 1 to 4";
const NO_SUCH_TABLE: &str = "it names a table that cannot be";
const SAME_NAMES: &str = "two of its components have the same name";
const QUANT_PRECISION: &str = "a quantization table has a precision that does not exist";
const QUANT_ZERO: &str = "a quantization table holds a 0";
const NO_TABLE: &str = "a scan uses a table that has not been given";
const SCAN_SIZE: &str = "a scan names no components, or more than 4";
const NOT_IN_FRAME: &str = "a scan names a component its frame does not have";
const SCAN_ORDER: &str = "a scan names its components out of the frame's order";
const TOO_MANY_BLOCKS: &str = "a scan's units have more than 10 blocks";
const BAD_BAND: &str = "a scan's band of coefficients is not as a progressive scan's must be";
const OUT_OF_ORDER: &str = "its scans do not build up its coefficients in order";
const TWO_SCANS: &str = "a component comes in two scans";
const MISSING: &str = "it ends before all its components have come";
const EOB_PAST: &str = "a run of empty blocks goes past the end of its restart interval";

// What it does not read, in the words the kernel says after "it is a kind
// of JPEG I do not read:".
const ARITHMETIC: &str = "its data is packed with arithmetic coding";
const TWELVE_BITS: &str = "its samples have 12 bits";
const LOSSLESS: &str = "it is lossless";
const HIERARCHICAL: &str = "it is hierarchical";
const COMPONENTS: &str = "its colours are in other than 1 or 3 components, as CMYK's are in 4";
const RATIOS: &str = "its colour components are sampled at ratios that are not whole";
const LATE_HEIGHT: &str = "its height comes after its first scan";
const UNKNOWN_MARKER: &str = "it holds a marker I do not know";

/// What a JPEG's frame says (B.2.2), and its Exif note's turn.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct JpegHead {
    /// Its size in dots, as it is stored.
    pub width: u32,
    pub height: u32,
    /// How many colour components it has: 1 (grey) or 3.
    pub components: u8,
    /// Whether it comes in progressive scans.
    pub progressive: bool,
    /// How it is turned to be seen as it was taken: Exif's orientation, 1
    /// to 8 (see `turned`); 1, as it is stored, when it has none.
    pub turn: u8,
}

impl JpegHead {
    /// Its size in dots as it is seen: the sides swapped for a quarter turn.
    pub fn seen(&self) -> (u32, u32) {
        if self.turn >= 5 { (self.height, self.width) } else { (self.width, self.height) }
    }
}

// ---------- Segments ----------

/// What a marker begins, by its code (B.1.1.3, Table B.1).
enum Marker {
    /// A frame of a kind it reads: SOF0 (baseline), SOF1 (extended
    /// sequential) or SOF2 (progressive), all with Huffman codes. Its code.
    Frame(u8),
    /// DHT, Huffman tables.
    Codes,
    /// DQT, quantization tables.
    Quant,
    /// DRI, the restart interval.
    Interval,
    /// SOS, a scan.
    Scan,
    /// EOI, the end of the picture.
    End,
    /// APPn, a segment for programs' own notes: its n.
    App(u8),
    /// COM, a comment, and DAC, which is for arithmetic coding only: both
    /// passed over by their lengths.
    PassOver,
    /// TEM, a marker with no segment.
    Alone,
}

fn marker_kind(code: u8) -> Result<Marker, Refusal> {
    match code {
        0xC0..=0xC2 => Ok(Marker::Frame(code)),
        0xC3 => Err(Refusal::KindNotRead(LOSSLESS)),
        0xC5..=0xC7 | 0xDE | 0xDF => Err(Refusal::KindNotRead(HIERARCHICAL)),
        0xC9..=0xCB | 0xCD..=0xCF => Err(Refusal::KindNotRead(ARITHMETIC)),
        0xC4 => Ok(Marker::Codes),
        0xCC | 0xFE => Ok(Marker::PassOver),
        0xD0..=0xD7 => Err(Refusal::Damaged(STRAY_RESTART)),
        0xD8 => Err(Refusal::Damaged(TWO_STARTS)),
        0xD9 => Ok(Marker::End),
        0xDA => Ok(Marker::Scan),
        0xDB => Ok(Marker::Quant),
        0xDC => Err(Refusal::KindNotRead(LATE_HEIGHT)),
        0xDD => Ok(Marker::Interval),
        0xE0..=0xEF => Ok(Marker::App(code - 0xE0)),
        0x01 => Ok(Marker::Alone),
        _ => Err(Refusal::KindNotRead(UNKNOWN_MARKER)),
    }
}

/// The marker at `at`, with any fill bytes (FF) before it passed over
/// (B.1.1.2): its code, and where what follows it begins.
fn marker_at(file: &[u8], at: usize) -> Result<(u8, usize), Refusal> {
    match file.get(at) {
        None => return Err(Refusal::CutShort),
        Some(0xFF) => {}
        Some(_) => return Err(Refusal::Damaged(NOT_A_MARKER)),
    }
    let mut after = at + 1;
    loop {
        match file.get(after).copied() {
            None => return Err(Refusal::CutShort),
            Some(0xFF) => after += 1,
            Some(0) => return Err(Refusal::Damaged(NOT_A_MARKER)),
            Some(code) => return Ok((code, after + 1)),
        }
    }
}

/// The segment that follows a marker, at `at`: what it holds, its length's
/// two bytes left out, and where the next marker begins (B.1.1.4).
fn segment_at(file: &[u8], at: usize) -> Result<(&[u8], usize), Refusal> {
    let length = usize::from(number2(file, at).ok_or(Refusal::CutShort)?);
    if length < 2 {
        return Err(Refusal::Damaged(BAD_LENGTH));
    }
    let end = at + length;
    let body = file.get(at + 2..end).ok_or(Refusal::CutShort)?;
    Ok((body, end))
}

/// The two bytes at `at` as a number, the higher byte first (B.1.1.1).
fn number2(bytes: &[u8], at: usize) -> Option<u16> {
    Some(u16::from_be_bytes([*bytes.get(at)?, *bytes.get(at + 1)?]))
}

// ---------- Tables ----------

/// The tables given so far: four places for each kind (B.2.4). A table may
/// be given again between scans, and the new one stands from then on.
struct Tables {
    /// Quantization tables, in the blocks' natural order.
    quant: [Option<[u16; 64]>; 4],
    dc: [Option<Code>; 4],
    ac: [Option<Code>; 4],
}

/// DQT (B.2.4.1): tables, each a byte that gives its precision (8 or 16
/// bits) and its place, then its 64 numbers in zig-zag order, none 0.
fn quant_tables(body: &[u8], tables: &mut Tables) -> Result<(), Refusal> {
    let mut at = 0;
    while let Some(head) = body.get(at) {
        let (precision, place) = (head >> 4, usize::from(head & 15));
        let size = match precision {
            0 => 1,
            1 => 2,
            _ => return Err(Refusal::Damaged(QUANT_PRECISION)),
        };
        let numbers = body.get(at + 1..at + 1 + 64 * size).ok_or(Refusal::Damaged(BAD_LENGTH))?;
        let mut table = [0u16; 64];
        for (k, natural) in ZIGZAG.iter().enumerate() {
            let number = if size == 1 { numbers.get(k).map(|byte| u16::from(*byte)) } else { number2(numbers, 2 * k) };
            let number = number.unwrap_or(0);
            if number == 0 {
                return Err(Refusal::Damaged(QUANT_ZERO));
            }
            if let Some(slot) = table.get_mut(usize::from(*natural)) {
                *slot = number;
            }
        }
        *tables.quant.get_mut(place).ok_or(Refusal::Damaged(NO_SUCH_TABLE))? = Some(table);
        at += 1 + 64 * size;
    }
    Ok(())
}

/// DHT (B.2.4.2): tables, each a byte that gives its kind (0 for DC, 1 for
/// AC) and its place, then how many codes it has of each length from 1 to
/// 16, then their values.
fn code_tables(body: &[u8], tables: &mut Tables) -> Result<(), Refusal> {
    let mut at = 0;
    while let Some(head) = body.get(at) {
        let (kind, place) = (head >> 4, usize::from(head & 15));
        let counts = body.get(at + 1..at + 17).ok_or(Refusal::Damaged(BAD_LENGTH))?;
        let many: usize = counts.iter().map(|count| usize::from(*count)).sum();
        if many > 256 {
            return Err(Refusal::Damaged(OVERFULL));
        }
        let values = body.get(at + 17..at + 17 + many).ok_or(Refusal::Damaged(BAD_LENGTH))?;
        let places = match kind {
            0 => &mut tables.dc,
            1 => &mut tables.ac,
            _ => return Err(Refusal::Damaged(NO_SUCH_TABLE)),
        };
        *places.get_mut(place).ok_or(Refusal::Damaged(NO_SUCH_TABLE))? = Some(Code::new(counts, values)?);
        at += 17 + many;
    }
    Ok(())
}

// ---------- The frame ----------

/// One colour component of the frame (B.2.2), and how its blocks are kept.
struct Component {
    id: u8,
    /// Its sampling factors (A.1.1). In a frame of one component they do not
    /// count (A.2.2), and are taken as 1.
    h: usize,
    v: usize,
    /// The place of the quantization table it uses, and the table itself,
    /// as it stands when the component's first scan begins.
    table: usize,
    quant: Option<[u16; 64]>,
    /// Its blocks across and down as they are kept: whole units' worth, as
    /// a scan of several components has them (A.2.3).
    across: usize,
    down: usize,
    /// The blocks a scan of it alone has: at the right and bottom edges,
    /// fewer than whole units' worth (A.2.2).
    own_across: usize,
    own_down: usize,
    /// Where its blocks begin among all the kept blocks.
    first_block: usize,
    /// For each of its coefficients, in zig-zag order, the point transform
    /// of the last scan that sent it, or -1 if none has. A sequential
    /// frame's one scan of a component sends every coefficient whole (0).
    sent: [i8; 64],
}

/// The frame (B.2.2).
struct Frame {
    progressive: bool,
    width: u32,
    height: u32,
    components: Vec<Component>,
    /// The largest sampling factors.
    h_most: usize,
    v_most: usize,
    /// Its units across and down, as a scan of several components has them,
    /// each 8 x h_most by 8 x v_most dots (A.2.3).
    units_across: usize,
    units_down: usize,
}

impl Frame {
    fn head(&self, turn: u8) -> JpegHead {
        JpegHead {
            width: self.width,
            height: self.height,
            components: self.components.len() as u8,
            progressive: self.progressive,
            turn,
        }
    }
}

/// SOF0, SOF1 or SOF2 (B.2.2): the samples' precision, the height and
/// width, and each component's name, sampling factors and quantization
/// table.
fn frame_of(code: u8, body: &[u8]) -> Result<Frame, Refusal> {
    let (Some(precision), Some(height), Some(width), Some(count)) =
        (body.first(), number2(body, 1), number2(body, 3), body.get(5))
    else {
        return Err(Refusal::Damaged(BAD_LENGTH));
    };
    if body.len() != 6 + 3 * usize::from(*count) {
        return Err(Refusal::Damaged(BAD_LENGTH));
    }
    match (code, precision) {
        (_, 8) => {}
        (0xC1 | 0xC2, 12) => return Err(Refusal::KindNotRead(TWELVE_BITS)),
        _ => return Err(Refusal::Damaged(BAD_PRECISION)),
    }
    if height == 0 {
        return Err(Refusal::KindNotRead(LATE_HEIGHT));
    }
    if width == 0 {
        return Err(Refusal::Damaged(NO_WIDTH));
    }
    match count {
        0 => return Err(Refusal::Damaged(NO_COMPONENTS)),
        1 | 3 => {}
        _ => return Err(Refusal::KindNotRead(COMPONENTS)),
    }

    let mut components: Vec<Component> = Vec::with_capacity(3);
    for &[id, factors, table] in body.get(6..).unwrap_or(&[]).as_chunks::<3>().0 {
        let (h, v) = (usize::from(factors >> 4), usize::from(factors & 15));
        if !(1..=4).contains(&h) || !(1..=4).contains(&v) {
            return Err(Refusal::Damaged(BAD_FACTORS));
        }
        if table > 3 {
            return Err(Refusal::Damaged(NO_SUCH_TABLE));
        }
        if components.iter().any(|component| component.id == id) {
            return Err(Refusal::Damaged(SAME_NAMES));
        }
        components.push(Component {
            id,
            h,
            v,
            table: usize::from(table),
            quant: None,
            across: 0,
            down: 0,
            own_across: 0,
            own_down: 0,
            first_block: 0,
            sent: [-1; 64],
        });
    }
    if let [only] = components.as_mut_slice() {
        (only.h, only.v) = (1, 1);
    }
    let h_most = components.iter().map(|component| component.h).max().unwrap_or(1);
    let v_most = components.iter().map(|component| component.v).max().unwrap_or(1);
    if components.iter().any(|component| h_most % component.h != 0 || v_most % component.v != 0) {
        return Err(Refusal::KindNotRead(RATIOS));
    }

    // Sizes (A.1.1, A.2.2, A.2.3).
    let (width, height) = (usize::from(width), usize::from(height));
    let units_across = width.div_ceil(8 * h_most);
    let units_down = height.div_ceil(8 * v_most);
    let mut first_block = 0;
    for component in components.iter_mut() {
        component.across = units_across * component.h;
        component.down = units_down * component.v;
        component.own_across = (width * component.h).div_ceil(h_most).div_ceil(8);
        component.own_down = (height * component.v).div_ceil(v_most).div_ceil(8);
        component.first_block = first_block;
        first_block += component.across * component.down;
    }
    Ok(Frame {
        progressive: code == 0xC2,
        width: width as u32,
        height: height as u32,
        components,
        h_most,
        v_most,
        units_across,
        units_down,
    })
}

// ---------- Scans ----------

/// A scan's header (B.2.3).
struct ScanHead {
    /// The components it holds, by their places in the frame, each with the
    /// places of its DC and AC Huffman tables.
    parts: Vec<(usize, usize, usize)>,
    band: Band,
    /// The point transform of the band's last scan (Ah), 0 in its first.
    high: u32,
}

/// What a scan sends of each block.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Pass {
    /// Everything, in a sequential frame.
    Sequential,
    /// In a progressive frame: the DC coefficients, or one more bit of them.
    DcFirst,
    DcRefine,
    /// A band of AC coefficients, or one more bit of them.
    AcFirst,
    AcRefine,
}

fn scan_head(body: &[u8], frame: &Frame) -> Result<ScanHead, Refusal> {
    let count = usize::from(*body.first().ok_or(Refusal::Damaged(BAD_LENGTH))?);
    if count == 0 || count > 4 {
        return Err(Refusal::Damaged(SCAN_SIZE));
    }
    if body.len() != 1 + 2 * count + 3 {
        return Err(Refusal::Damaged(BAD_LENGTH));
    }
    let mut parts: Vec<(usize, usize, usize)> = Vec::with_capacity(count);
    for &[id, tables] in body.get(1..1 + 2 * count).unwrap_or(&[]).as_chunks::<2>().0 {
        let place = frame.components.iter().position(|component| component.id == id).ok_or(Refusal::Damaged(NOT_IN_FRAME))?;
        if parts.last().is_some_and(|(last, _, _)| *last >= place) {
            return Err(Refusal::Damaged(SCAN_ORDER));
        }
        let (dc, ac) = (usize::from(tables >> 4), usize::from(tables & 15));
        if dc > 3 || ac > 3 {
            return Err(Refusal::Damaged(NO_SUCH_TABLE));
        }
        parts.push((place, dc, ac));
    }
    let Some(&[start, end, approximation]) = body.get(1 + 2 * count..) else {
        return Err(Refusal::Damaged(BAD_LENGTH));
    };
    if count > 1 {
        let blocks: usize = parts
            .iter()
            .filter_map(|(place, _, _)| frame.components.get(*place))
            .map(|component| component.h * component.v)
            .sum();
        if blocks > 10 {
            return Err(Refusal::Damaged(TOO_MANY_BLOCKS));
        }
    }
    Ok(ScanHead {
        parts,
        band: Band { start: usize::from(start), end: usize::from(end), low: u32::from(approximation & 15) },
        high: u32::from(approximation >> 4),
    })
}

/// Checks that a scan may come now, and notes what it sends. In a
/// sequential frame each component comes in one scan, and the band and the
/// point transforms are not read (T.81 sets them to 0, 63, 0 and 0). In a
/// progressive one (G.1.1.1): a DC band holds only the DC coefficient, an AC
/// band only AC ones and one component; a component's first DC scan comes
/// before its AC scans; a band's first scan has Ah 0, and each later one
/// sends the next bit down, Ah the last scan's Al and Al one less.
fn check_scan(frame: &mut Frame, head: &ScanHead) -> Result<Pass, Refusal> {
    if !frame.progressive {
        for (place, _, _) in &head.parts {
            let component = frame.components.get_mut(*place).ok_or(Refusal::Damaged(NOT_IN_FRAME))?;
            if component.sent.first().is_some_and(|sent| *sent >= 0) {
                return Err(Refusal::Damaged(TWO_SCANS));
            }
            component.sent = [0; 64];
        }
        return Ok(Pass::Sequential);
    }
    let Band { start, end, low } = head.band;
    let high = head.high;
    let dc = start == 0;
    let band_sound = if dc { end == 0 } else { start <= end && end <= 63 && head.parts.len() == 1 };
    if !band_sound || high > 13 || low > 13 || (high != 0 && low + 1 != high) {
        return Err(Refusal::Damaged(BAD_BAND));
    }
    let wanted = if high == 0 { -1 } else { high as i8 };
    for (place, _, _) in &head.parts {
        let component = frame.components.get_mut(*place).ok_or(Refusal::Damaged(NOT_IN_FRAME))?;
        if !dc && component.sent.first().is_some_and(|sent| *sent < 0) {
            return Err(Refusal::Damaged(OUT_OF_ORDER));
        }
        for sent in component.sent.get_mut(start..=end).unwrap_or(&mut []) {
            if *sent != wanted {
                return Err(Refusal::Damaged(OUT_OF_ORDER));
            }
            *sent = low as i8;
        }
    }
    Ok(match (dc, high) {
        (true, 0) => Pass::DcFirst,
        (true, _) => Pass::DcRefine,
        (false, 0) => Pass::AcFirst,
        (false, _) => Pass::AcRefine,
    })
}

/// A Huffman table that a scan needs, which must have been given by now.
fn table(places: &[Option<Code>; 4], place: usize) -> Result<&Code, Refusal> {
    places.get(place).and_then(Option::as_ref).ok_or(Refusal::Damaged(NO_TABLE))
}

/// Reads one block of a scan into `block`, as `pass` says.
#[allow(clippy::too_many_arguments)]
fn read_block(
    bits: &mut Bits<'_>,
    pass: Pass,
    codes: (Option<&Code>, Option<&Code>),
    band: Band,
    prediction: &mut i32,
    eob_run: &mut u32,
    block: &mut Block<'_>,
    keep: &Keep,
) -> Result<(), Refusal> {
    match (pass, codes) {
        (Pass::Sequential, (Some(dc), Some(ac))) => entropy::sequential_block(bits, dc, ac, prediction, block, keep),
        (Pass::DcFirst, (Some(dc), _)) => entropy::dc_first(bits, dc, prediction, band.low, block),
        (Pass::DcRefine, _) => entropy::dc_refine(bits, band.low, block),
        (Pass::AcFirst, (_, Some(ac))) => entropy::ac_first(bits, ac, band, eob_run, block, keep),
        (Pass::AcRefine, (_, Some(ac))) => entropy::ac_refine(bits, ac, band, eob_run, block, keep),
        _ => Err(Refusal::Damaged(NO_TABLE)),
    }
}

// ---------- Dots ----------

/// How a picture's components become red, green and blue.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Colour {
    Grey,
    /// The components are red, green and blue already.
    Rgb,
    /// JFIF's Y, Cb and Cr.
    Ycc,
}

/// The picture's dots, made a row of units at a time: each component's
/// samples for one row of units, at n dots a block side, are turned into
/// rows of dots and shrunk.
struct Rows {
    n: usize,
    colour: Colour,
    /// Each component's samples for one row of units: its blocks across
    /// times n wide (`strides`), v times n high.
    samples: Vec<Vec<u8>>,
    strides: Vec<usize>,
    /// For each component, how many dots across and down each of its
    /// samples covers: Hmax / h by Vmax / v, whole numbers.
    spread: Vec<(usize, usize)>,
    /// The size it is read at, and how many rows of dots a row of units
    /// makes.
    width: usize,
    height: usize,
    unit_height: usize,
    row: Vec<u8>,
    shrink: Shrink,
}

impl Rows {
    fn new(frame: &Frame, n: usize, colour: Colour, read: (u32, u32), shown: (u32, u32)) -> Rows {
        let components = &frame.components;
        Rows {
            n,
            colour,
            samples: components.iter().map(|component| vec![0; component.across * n * component.v * n]).collect(),
            strides: components.iter().map(|component| component.across * n).collect(),
            spread: components.iter().map(|component| (frame.h_most / component.h, frame.v_most / component.v)).collect(),
            width: read.0 as usize,
            height: read.1 as usize,
            unit_height: frame.v_most * n,
            row: Vec::with_capacity(read.0 as usize * 4),
            shrink: Shrink::new(read.0, read.1, shown.0, shown.1),
        }
    }

    /// Puts the samples of a block of component `place`: the block `x`
    /// across and `y` down within the row of units.
    fn put(&mut self, place: usize, x: usize, y: usize, kept: &[i16], quant: &[u16; 64]) {
        let n = self.n;
        let (Some(samples), Some(stride)) = (self.samples.get_mut(place), self.strides.get(place)) else {
            return;
        };
        if let Some(out) = samples.get_mut(y * n * stride + x * n..) {
            block_samples(n, kept, quant, out, *stride);
        }
    }

    /// Turns the row of units `unit_y` into rows of dots: each dot (x, y)
    /// takes component i's sample at (x x h / Hmax, y x v / Vmax).
    fn make_dots(&mut self, unit_y: usize) {
        for local in 0..self.unit_height {
            let y = unit_y * self.unit_height + local;
            if y >= self.height {
                break;
            }
            self.row.clear();
            for x in 0..self.width {
                let sample = |place: usize| -> u8 {
                    let (Some(samples), Some(stride), Some((across, down))) =
                        (self.samples.get(place), self.strides.get(place), self.spread.get(place))
                    else {
                        return 0;
                    };
                    samples.get(local / down * stride + x / across).copied().unwrap_or(0)
                };
                let [red, green, blue] = match self.colour {
                    Colour::Grey => [sample(0); 3],
                    Colour::Rgb => [sample(0), sample(1), sample(2)],
                    Colour::Ycc => rgb_of_ycc(sample(0), sample(1), sample(2)),
                };
                self.row.extend_from_slice(&[red, green, blue, 255]);
            }
            self.shrink.take_row(y as u32, &self.row);
        }
    }
}

/// How the blocks are read.
enum Mode {
    /// No scan has come yet.
    NotYet,
    /// The first scan holds every component: each row of units is turned
    /// into dots as it comes.
    Stream(Rows),
    /// The coefficients of every block are kept until the last scan has
    /// come: n by n of them a block (`kept`), and the 64 bits that say
    /// which are non-zero (`nonzero`).
    Held { kept: Vec<i16>, nonzero: Vec<u64>, rows: Rows },
}

// ---------- The whole picture ----------

/// Reads the head of a JPEG photo: the segments up to its frame.
pub fn jpeg_head(file: &[u8]) -> Result<JpegHead, Refusal> {
    if file.get(..2) != Some(&[0xFF, 0xD8][..]) {
        return Err(Refusal::NotJpeg);
    }
    let mut at = 2;
    let mut turn = None;
    loop {
        let (code, after) = marker_at(file, at)?;
        at = match marker_kind(code)? {
            Marker::Frame(code) => return Ok(frame_of(code, segment_at(file, after)?.0)?.head(turn.unwrap_or(1))),
            Marker::Scan | Marker::End => return Err(Refusal::Damaged(NO_FRAME)),
            Marker::Alone => after,
            Marker::App(1) => {
                let (body, end) = segment_at(file, after)?;
                turn = turn.or_else(|| exif_turn(body));
                end
            }
            _ => segment_at(file, after)?.1,
        };
    }
}

// ---------- The turn ----------

/// The turn an Exif note gives (CIPA DC-008, Exif 3.1): an APP1 segment
/// that begins with "Exif" and two zero bytes (4.7.2) holds a TIFF head, its
/// byte order ("II", lowest byte first, or "MM", highest first), 42, and
/// where its 0th IFD begins, counted from the head's first byte; the IFD is
/// a count of entries, then 12 bytes each: a tag, a type, a count and a
/// value (4.6.2). The entry of tag 274 (Orientation), of type SHORT and count
/// 1, holds the turn in the first two bytes of its value (4.6.5.1.6). A
/// note that is not whole, or a turn other than 1 to 8, gives nothing: the
/// photo is shown as it is stored.
fn exif_turn(body: &[u8]) -> Option<u8> {
    let tiff = body.strip_prefix(b"Exif\x00\x00")?;
    let big = match tiff.get(..2)? {
        b"MM" => true,
        b"II" => false,
        _ => return None,
    };
    let two = |at: usize| -> Option<u16> {
        let bytes = [*tiff.get(at)?, *tiff.get(at.checked_add(1)?)?];
        Some(if big { u16::from_be_bytes(bytes) } else { u16::from_le_bytes(bytes) })
    };
    let four = |at: usize| -> Option<u32> {
        let bytes = [*tiff.get(at)?, *tiff.get(at.checked_add(1)?)?, *tiff.get(at.checked_add(2)?)?, *tiff.get(at.checked_add(3)?)?];
        Some(if big { u32::from_be_bytes(bytes) } else { u32::from_le_bytes(bytes) })
    };
    if two(2)? != 42 {
        return None;
    }
    let ifd = usize::try_from(four(4)?).ok()?;
    let entries = usize::from(two(ifd)?);
    for number in 0..entries {
        let entry = ifd.checked_add(2)?.checked_add(number.checked_mul(12)?)?;
        if two(entry)? == 274 && two(entry.checked_add(2)?)? == 3 && four(entry.checked_add(4)?)? == 1 {
            let turn = two(entry.checked_add(8)?)?;
            return u8::try_from(turn).ok().filter(|turn| (1..=8).contains(turn));
        }
    }
    None
}

/// The picture turned as the Exif note says, so that it is seen as it was
/// taken (CIPA DC-008, 4.6.5.1.6, Figure 13). A turn of 2 mirrors it left to
/// right, 3 turns it a half turn, 4 mirrors it top to bottom; 5 to 8 turn
/// it a quarter, so that its sides swap: 6 a quarter turn clockwise, 8 one
/// the other way, and 5 and 7 those of 6 and 8 mirrored. The dot (x, y) as
/// seen comes from the stored picture of W by H dots at: 2 (W - 1 - x, y);
/// 3 (W - 1 - x, H - 1 - y); 4 (x, H - 1 - y); 5 (y, x); 6 (y, H - 1 - x);
/// 7 (W - 1 - y, H - 1 - x); 8 (W - 1 - y, x).
fn turned(picture: Picture, turn: u8) -> Picture {
    if !(2..=8).contains(&turn) {
        return picture;
    }
    let (width, height) = (picture.width as usize, picture.height as usize);
    let (seen_width, seen_height) = if turn >= 5 { (height, width) } else { (width, height) };
    let mut dots = vec![0u8; picture.dots.len()];
    for (y, row) in dots.chunks_mut(seen_width.max(1) * 4).enumerate() {
        for (x, dot) in row.chunks_mut(4).enumerate() {
            let (from_x, from_y) = match turn {
                2 => (width.saturating_sub(1 + x), y),
                3 => (width.saturating_sub(1 + x), height.saturating_sub(1 + y)),
                4 => (x, height.saturating_sub(1 + y)),
                5 => (y, x),
                6 => (y, height.saturating_sub(1 + x)),
                7 => (width.saturating_sub(1 + y), height.saturating_sub(1 + x)),
                _ => (width.saturating_sub(1 + y), x),
            };
            let at = (from_y * width + from_x) * 4;
            if let Some(from) = picture.dots.get(at..at + 4) {
                for (to, from) in dot.iter_mut().zip(from) {
                    *to = *from;
                }
            }
        }
    }
    Picture { width: seen_width as u32, height: seen_height as u32, dots }
}

/// What is known while a picture is read.
struct Reading<'a> {
    file: &'a [u8],
    room: (u32, u32),
    limits: &'a JpegLimits,
    tables: Tables,
    /// The restart interval, in units (B.2.4.4): 0 for none.
    interval: usize,
    /// Whether JFIF's APP0 segment has come, and the colour transform
    /// Adobe's APP14 segment names, if it has come.
    jfif: bool,
    adobe: Option<u8>,
    /// The turn the first Exif note before the frame gives, if any.
    turn: Option<u8>,
    frame: Option<Frame>,
    /// The picture is read at n dots a block side, at the size `read`, and
    /// shown at the size `shown`.
    n: usize,
    keep: Keep,
    read: (u32, u32),
    shown: (u32, u32),
    mode: Mode,
}

/// Reads a JPEG photo and shrinks it to fit a room of `room_width` by
/// `room_height` dots, keeping its shape (see `fitted_size`). Every check
/// that can turn a picture down for its size is made before memory is set
/// aside for it.
pub fn jpeg_picture(file: &[u8], room_width: u32, room_height: u32, limits: &JpegLimits) -> Result<Picture, Refusal> {
    if file.get(..2) != Some(&[0xFF, 0xD8][..]) {
        return Err(Refusal::NotJpeg);
    }
    let mut reading = Reading {
        file,
        room: (room_width, room_height),
        limits,
        tables: Tables { quant: [None; 4], dc: [None, None, None, None], ac: [None, None, None, None] },
        interval: 0,
        jfif: false,
        adobe: None,
        turn: None,
        frame: None,
        n: 8,
        keep: Keep::new(8),
        read: (0, 0),
        shown: (0, 0),
        mode: Mode::NotYet,
    };
    let mut at = 2;
    loop {
        let (code, after) = marker_at(file, at)?;
        let marker = marker_kind(code)?;
        if let Marker::End = marker {
            return reading.finish();
        }
        if let Marker::Alone = marker {
            at = after;
            continue;
        }
        let (body, end) = segment_at(file, after)?;
        at = end;
        match marker {
            Marker::Frame(code) => reading.frame(code, body)?,
            Marker::Codes => code_tables(body, &mut reading.tables)?,
            Marker::Quant => quant_tables(body, &mut reading.tables)?,
            Marker::Interval => {
                if body.len() != 2 {
                    return Err(Refusal::Damaged(BAD_LENGTH));
                }
                reading.interval = usize::from(number2(body, 0).unwrap_or(0));
            }
            // JFIF's note (APP0) says its colours are YCbCr (JFIF 1.02).
            // Adobe's (APP14): "Adobe", its version and two flags, and then
            // its colour transform (0 none, 1 YCbCr); a shorter one says
            // nothing.
            Marker::App(0) if body.starts_with(b"JFIF\x00") => reading.jfif = true,
            // The Exif note's turn counts only before the frame, where the
            // size the photo is read at is chosen; the first note that gives
            // one counts.
            Marker::App(1) if reading.frame.is_none() && reading.turn.is_none() => reading.turn = exif_turn(body),
            Marker::App(14) if body.starts_with(b"Adobe") => {
                if let Some(transform) = body.get(11) {
                    reading.adobe = Some(*transform);
                }
            }
            Marker::Scan => at = reading.scan(body, end)?,
            _ => {}
        }
    }
}

impl Reading<'_> {
    /// The frame: its size is checked against the limits, and the size the
    /// picture is read at is chosen.
    fn frame(&mut self, code: u8, body: &[u8]) -> Result<(), Refusal> {
        if self.frame.is_some() {
            return Err(Refusal::Damaged(TWO_FRAMES));
        }
        let frame = frame_of(code, body)?;
        let (width, height) = (frame.width, frame.height);
        let dots = u64::from(width) * u64::from(height);
        if width > self.limits.side_most || height > self.limits.side_most || dots > self.limits.dots_most {
            return Err(Refusal::TooLarge { width, height });
        }
        if self.room.0 == 0 || self.room.1 == 0 {
            return Err(Refusal::NoRoom);
        }
        // A photo turned a quarter is shown with its sides swapped, so it is
        // fitted to the room with the room's sides swapped, and turned last.
        let room = if self.turn.unwrap_or(1) >= 5 { (self.room.1, self.room.0) } else { self.room };
        self.shown = fitted_size(width, height, room.0, room.1);
        let side = |size: u32, n: usize| (u64::from(size) * n as u64).div_ceil(8) as u32;
        // A picture shown at its whole size is read whole: for a photo of one
        // dot an eighth would be as large, but its dot would be the block's
        // average, the samples the encoder filled the block with included.
        self.n = if self.shown == (width, height) {
            8
        } else {
            [1, 2, 4, 8]
                .into_iter()
                .find(|n| side(width, *n) >= self.shown.0 && side(height, *n) >= self.shown.1)
                .unwrap_or(8)
        };
        self.keep = Keep::new(self.n);
        self.read = (side(width, self.n), side(height, self.n));
        self.frame = Some(frame);
        Ok(())
    }

    /// A scan, whose header is `body` and whose data begins at `at`. Gives
    /// where the marker after its data begins.
    fn scan(&mut self, body: &[u8], at: usize) -> Result<usize, Refusal> {
        let Reading { file, limits, tables, interval, jfif, adobe, frame, n, keep, read, shown, mode, .. } = self;
        let n = *n;
        let frame = frame.as_mut().ok_or(Refusal::Damaged(NO_FRAME))?;
        let head = scan_head(body, frame)?;
        let pass = check_scan(frame, &head)?;

        // The tables it needs, which must have been given by now.
        let mut codes: Vec<(Option<&Code>, Option<&Code>)> = Vec::with_capacity(head.parts.len());
        for (place, dc, ac) in &head.parts {
            let dc = if matches!(pass, Pass::Sequential | Pass::DcFirst) { Some(table(&tables.dc, *dc)?) } else { None };
            let ac =
                if matches!(pass, Pass::Sequential | Pass::AcFirst | Pass::AcRefine) { Some(table(&tables.ac, *ac)?) } else { None };
            codes.push((dc, ac));
            let component = frame.components.get_mut(*place).ok_or(Refusal::Damaged(NOT_IN_FRAME))?;
            if component.quant.is_none() {
                component.quant = Some(tables.quant.get(component.table).copied().flatten().ok_or(Refusal::Damaged(NO_TABLE))?);
            }
        }

        // The first scan chooses how the blocks are read, and what the
        // colours are, from the notes that came before it: JFIF's first, then
        // Adobe's, then the components' names, R, G and B.
        if matches!(mode, Mode::NotYet) {
            let ids: Vec<u8> = frame.components.iter().map(|component| component.id).collect();
            let colour = match (ids.len(), *jfif, *adobe) {
                (1, _, _) => Colour::Grey,
                (_, true, _) => Colour::Ycc,
                (_, false, Some(0)) => Colour::Rgb,
                (_, false, Some(_)) => Colour::Ycc,
                _ if ids == [82, 71, 66] => Colour::Rgb,
                _ => Colour::Ycc,
            };
            let rows = Rows::new(frame, n, colour, *read, *shown);
            *mode = if !frame.progressive && head.parts.len() == frame.components.len() {
                Mode::Stream(rows)
            } else {
                let blocks: u64 = frame.components.iter().map(|component| (component.across * component.down) as u64).sum();
                if blocks * (8 + 2 * (n * n) as u64) > limits.held_most {
                    return Err(Refusal::TooLarge { width: frame.width, height: frame.height });
                }
                Mode::Held { kept: vec![0; blocks as usize * n * n], nonzero: vec![0; blocks as usize], rows }
            };
        }

        // Its units: a scan of one component has its blocks one by one
        // (A.2.2); one of several has units of each component's h by v
        // blocks in turn (A.2.3).
        let single = head.parts.len() == 1;
        let (across, down) = match (single, head.parts.first().and_then(|(place, _, _)| frame.components.get(*place))) {
            (true, Some(component)) => (component.own_across, component.own_down),
            _ => (frame.units_across, frame.units_down),
        };
        let mut bits = Bits::new(file, at);
        let mut predictions = [0i32; 4];
        let mut eob_run = 0u32;
        let mut restarts = 0u8;
        let mut scratch = vec![0i16; n * n];
        for unit_y in 0..down {
            for unit_x in 0..across {
                let unit = unit_y * across + unit_x;
                if *interval > 0 && unit > 0 && unit % *interval == 0 {
                    // Restart (F.2.1.3, G.1.2.2): the run of empty blocks
                    // ends with the interval.
                    if eob_run > 0 {
                        return Err(Refusal::Damaged(EOB_PAST));
                    }
                    bits.restart(restarts)?;
                    restarts = (restarts + 1) % 8;
                    predictions = [0; 4];
                }
                for (((place, _, _), pair), prediction) in head.parts.iter().zip(&codes).zip(predictions.iter_mut()) {
                    let component = frame.components.get(*place).ok_or(Refusal::Damaged(NOT_IN_FRAME))?;
                    let (h, v) = if single { (1, 1) } else { (component.h, component.v) };
                    for local_y in 0..v {
                        for local_x in 0..h {
                            let (x, y) = if single { (unit_x, unit_y) } else { (unit_x * h + local_x, unit_y * v + local_y) };
                            match mode {
                                Mode::Stream(rows) => {
                                    scratch.fill(0);
                                    let mut nonzero = 0;
                                    let mut block = Block { kept: &mut scratch, nonzero: &mut nonzero };
                                    read_block(&mut bits, pass, *pair, head.band, prediction, &mut eob_run, &mut block, keep)?;
                                    let quant = component.quant.unwrap_or([0; 64]);
                                    rows.put(*place, x, local_y, &scratch, &quant);
                                }
                                Mode::Held { kept, nonzero, .. } => {
                                    let index = component.first_block + y * component.across + x;
                                    let (Some(kept), Some(nonzero)) =
                                        (kept.get_mut(index * n * n..(index + 1) * n * n), nonzero.get_mut(index))
                                    else {
                                        continue;
                                    };
                                    let mut block = Block { kept, nonzero };
                                    read_block(&mut bits, pass, *pair, head.band, prediction, &mut eob_run, &mut block, keep)?;
                                }
                                Mode::NotYet => {}
                            }
                        }
                    }
                }
            }
            if let Mode::Stream(rows) = mode {
                rows.make_dots(unit_y);
            }
        }
        if eob_run > 0 {
            return Err(Refusal::Damaged(EOB_PAST));
        }
        bits.end_of_scan()
    }

    /// The end marker: every component must have come. Kept blocks are
    /// turned into dots now, a row of units at a time. Then the picture is
    /// turned as the Exif note says.
    fn finish(self) -> Result<Picture, Refusal> {
        let turn = self.turn.unwrap_or(1);
        self.dots().map(|picture| turned(picture, turn))
    }

    /// The picture's dots, as it is stored.
    fn dots(self) -> Result<Picture, Refusal> {
        let frame = self.frame.ok_or(Refusal::Damaged(NO_FRAME))?;
        if frame.components.iter().any(|component| component.sent.first().is_none_or(|sent| *sent < 0)) {
            return Err(Refusal::Damaged(MISSING));
        }
        let n = self.n;
        match self.mode {
            Mode::NotYet => Err(Refusal::Damaged(MISSING)),
            Mode::Stream(rows) => Ok(rows.shrink.finish()),
            Mode::Held { kept, mut rows, .. } => {
                for unit_y in 0..frame.units_down {
                    for (place, component) in frame.components.iter().enumerate() {
                        let quant = component.quant.unwrap_or([0; 64]);
                        for local_y in 0..component.v {
                            let y = unit_y * component.v + local_y;
                            for x in 0..component.across {
                                let index = component.first_block + y * component.across + x;
                                if let Some(block) = kept.get(index * n * n..(index + 1) * n * n) {
                                    rows.put(place, x, local_y, block, &quant);
                                }
                            }
                        }
                    }
                    rows.make_dots(unit_y);
                }
                Ok(rows.shrink.finish())
            }
        }
    }
}
