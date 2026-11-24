//! How much memory reading a picture takes, counted: every piece the crate
//! asks for goes through a counting allocator, and the most held at once is
//! read. The kernel's heap never gives memory back and stops when it runs
//! out, so these numbers are what a picture costs it. This test is a crate of
//! its own (Cargo builds each file in tests/ apart), so that the unsafe code
//! a counting allocator needs stays out of the pictures crate itself, which
//! forbids it.

use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};

use pictures::{JpegLimits, Limits, Refusal, jpeg_picture, png_picture};

struct Counting;

static NOW: AtomicUsize = AtomicUsize::new(0);
static MOST: AtomicUsize = AtomicUsize::new(0);

// SAFETY: every call is handed on to the system's allocator unchanged; the
// counts are only added to and read.
unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let now = NOW.fetch_add(layout.size(), Ordering::SeqCst) + layout.size();
        MOST.fetch_max(now, Ordering::SeqCst);
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        NOW.fetch_sub(layout.size(), Ordering::SeqCst);
        unsafe { System.dealloc(ptr, layout) }
    }
}

#[global_allocator]
static ALLOCATOR: Counting = Counting;

/// The CRC-32 of PNG's parts (RFC 2083, appendix 15), worked out here
/// rather than borrowed from the crate, which keeps it to itself.
fn crc(bytes: &[u8]) -> u32 {
    let mut c = 0xffff_ffffu32;
    for byte in bytes {
        c ^= u32::from(*byte);
        for _ in 0..8 {
            c = if c & 1 == 1 { 0xedb8_8320 ^ (c >> 1) } else { c >> 1 };
        }
    }
    !c
}

fn part(out: &mut Vec<u8>, name: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    let mut named = name.to_vec();
    named.extend_from_slice(data);
    out.extend_from_slice(&named);
    out.extend_from_slice(&crc(&named).to_be_bytes());
}

/// A red-green-blue PNG of `width` by `height` dots, a gentle pattern, its
/// rows stored unpacked (zlib stored blocks), so that it is made fast.
fn picture(width: u32, height: u32) -> Vec<u8> {
    let mut rows = Vec::with_capacity((height * (1 + width * 3)) as usize);
    for y in 0..height {
        rows.push(0);
        for x in 0..width {
            rows.extend_from_slice(&[(x % 256) as u8, (y % 256) as u8, ((x + y) % 256) as u8]);
        }
    }
    let mut packed = vec![0x78, 0x01];
    let pieces: Vec<&[u8]> = rows.chunks(65_535).collect();
    for (i, piece) in pieces.iter().enumerate() {
        packed.push(u8::from(i + 1 == pieces.len()));
        packed.extend_from_slice(&(piece.len() as u16).to_le_bytes());
        packed.extend_from_slice(&(!(piece.len() as u16)).to_le_bytes());
        packed.extend_from_slice(piece);
    }
    let (mut s1, mut s2) = (1u32, 0u32);
    for byte in &rows {
        s1 = (s1 + u32::from(*byte)) % 65521;
        s2 = (s2 + s1) % 65521;
    }
    packed.extend_from_slice(&((s2 << 16) | s1).to_be_bytes());
    let mut head = width.to_be_bytes().to_vec();
    head.extend_from_slice(&height.to_be_bytes());
    head.extend_from_slice(&[8, 2, 0, 0, 0]);
    let mut out = vec![137, 80, 78, 71, 13, 10, 26, 10];
    part(&mut out, b"IHDR", &head);
    part(&mut out, b"IDAT", &packed);
    part(&mut out, b"IEND", &[]);
    out
}

/// The most memory held at once, beyond what was held before, while `work`
/// ran.
fn most_held<T>(work: impl FnOnce() -> T) -> (T, usize) {
    let before = NOW.load(Ordering::SeqCst);
    MOST.store(before, Ordering::SeqCst);
    let result = work();
    (result, MOST.load(Ordering::SeqCst) - before)
}

/// Both parts in one test, one after the other: the count is of the whole
/// program, so two tests at once would count each other.
#[test]
fn memory_held() {
    png_memory_held();
    jpeg_memory_held();
}

fn png_memory_held() {
    let limits = Limits { dots_most: 1 << 26, side_most: 1 << 15, interlaced_dots_most: 1 << 22 };

    // A head that says 30,000 by 30,000: turned down before memory is set
    // aside for it.
    let mut huge = vec![137, 80, 78, 71, 13, 10, 26, 10];
    let mut head = 30_000u32.to_be_bytes().to_vec();
    head.extend_from_slice(&30_000u32.to_be_bytes());
    head.extend_from_slice(&[8, 2, 0, 0, 0]);
    part(&mut huge, b"IHDR", &head);
    part(&mut huge, b"IDAT", &[0x78, 0x01, 0x01, 0x00, 0x00, 0xff, 0xff, 0, 0, 0, 1]);
    part(&mut huge, b"IEND", &[]);
    let (result, held) = most_held(|| png_picture(&huge, 554, 400, &limits));
    assert_eq!(result.map(|p| p.width), Err(Refusal::TooLarge { width: 30_000, height: 30_000 }));
    println!("a head of 30000 by 30000 dots: {} bytes held at most", held);
    assert!(held < 4096, "{} bytes", held);

    // A photo-sized picture, 3000 by 2000, shown in the usual frame's room:
    // what is held is the shown picture, 554 by 369 dots of four bytes
    // (817,704 bytes), and the reading's own pieces, not the 18 MB of dots.
    // Then one that fits as it is, and a very wide one.
    for (width, height) in [(3000, 2000), (554, 400), (16_000, 100)] {
        let file = picture(width, height);
        let (result, held) = most_held(|| png_picture(&file, 554, 400, &limits));
        let shown = result.unwrap();
        let shown_bytes = shown.dots.len();
        println!(
            "{} by {} dots shown at {} by {}: {} bytes held at most, of which {} are the shown picture",
            width, height, shown.width, shown.height, held, shown_bytes
        );
        assert!(held < shown_bytes + 512 * 1024, "{} by {}: {} bytes", width, height, held);
    }
}

/// A JPEG segment: its marker's code, its length and what it holds.
fn segment(out: &mut Vec<u8>, code: u8, body: &[u8]) {
    out.extend_from_slice(&[0xFF, code]);
    out.extend_from_slice(&((body.len() + 2) as u16).to_be_bytes());
    out.extend_from_slice(body);
}

/// A colour JPEG of `width` by `height` dots, 4:2:0, every block flat grey,
/// so that it is made fast: a baseline one in one scan, or a progressive one
/// with its DC scan only. Each table has one code, 0: a DC difference of
/// size 0, and the end of a block. The data is zero bits, one or two a
/// block, the last byte filled with 1-bits.
fn photo(width: u16, height: u16, progressive: bool) -> Vec<u8> {
    let mut out = vec![0xFF, 0xD8];
    let mut quant = vec![0u8];
    quant.extend_from_slice(&[1; 64]);
    segment(&mut out, 0xDB, &quant);
    let mut frame = vec![8];
    frame.extend_from_slice(&height.to_be_bytes());
    frame.extend_from_slice(&width.to_be_bytes());
    frame.extend_from_slice(&[3, 1, 0x22, 0, 2, 0x11, 0, 3, 0x11, 0]);
    segment(&mut out, if progressive { 0xC2 } else { 0xC0 }, &frame);
    let mut one_code = vec![1u8];
    one_code.extend_from_slice(&[0; 15]);
    for kind in [0x00u8, 0x10] {
        let mut table = vec![kind];
        table.extend_from_slice(&one_code);
        table.push(0);
        segment(&mut out, 0xC4, &table);
    }
    let end = if progressive { 0 } else { 63 };
    segment(&mut out, 0xDA, &[3, 1, 0x00, 2, 0x00, 3, 0x00, 0, end, 0]);
    let units = u64::from(width.div_ceil(16)) * u64::from(height.div_ceil(16));
    let bits = units * 6 * if progressive { 1 } else { 2 };
    out.resize(out.len() + (bits / 8) as usize, 0);
    if bits % 8 != 0 {
        out.push(0xFF >> (bits % 8));
    }
    out.extend_from_slice(&[0xFF, 0xD9]);
    out
}

fn jpeg_memory_held() {
    let limits = JpegLimits { dots_most: 1 << 26, side_most: 1 << 15, held_most: 1 << 30 };

    // A baseline photo is read a row of units at a time: what is held is
    // the shown picture and the reading's own pieces, whatever its size.
    for (width, height) in [(4000, 3000), (554, 400), (16_000, 100)] {
        let file = photo(width, height, false);
        let (result, held) = most_held(|| jpeg_picture(&file, 554, 400, &limits));
        let shown = result.unwrap();
        let shown_bytes = shown.dots.len();
        println!(
            "a baseline JPEG of {} by {} dots shown at {} by {}: {} bytes held at most, of which {} are the shown picture",
            width, height, shown.width, shown.height, held, shown_bytes
        );
        assert!(held < shown_bytes + 512 * 1024, "{} by {}: {} bytes", width, height, held);
    }

    // A progressive one keeps its blocks until its last scan: 4000 by 3000
    // in 4:2:0 has 282,000 blocks; shown at 533 by 400 it is read at a
    // quarter, n = 2, so 8 + 2 x 2 x 2 = 16 bytes a block, 4,512,000 bytes.
    let file = photo(4000, 3000, true);
    let (result, held) = most_held(|| jpeg_picture(&file, 554, 400, &limits));
    let shown = result.unwrap();
    println!(
        "a progressive JPEG of 4000 by 3000 dots shown at {} by {}: {} bytes held at most, of which {} are the shown picture",
        shown.width,
        shown.height,
        held,
        shown.dots.len()
    );
    assert!(held >= 4_512_000 && held < 4_512_000 + shown.dots.len() + 512 * 1024, "{} bytes", held);
    // The same with too little room for its blocks: turned down before they
    // are set aside.
    let tight = JpegLimits { held_most: 4_511_999, ..limits };
    let (result, held) = most_held(|| jpeg_picture(&file, 554, 400, &tight));
    assert_eq!(result, Err(Refusal::TooLarge { width: 4000, height: 3000 }));
    assert!(held < shown.dots.len() + 64 * 1024, "{} bytes", held);
}
