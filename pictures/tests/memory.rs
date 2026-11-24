//! How much memory reading a picture takes, counted: every piece the crate
//! asks for goes through a counting allocator, and the most held at once is
//! read. The kernel's heap never gives memory back and stops when it runs
//! out, so these numbers are what a picture costs it. This test is a crate of
//! its own (Cargo builds each file in tests/ apart), so that the unsafe code
//! a counting allocator needs stays out of the pictures crate itself, which
//! forbids it.

use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};

use pictures::{Limits, Refusal, png_picture};

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

#[test]
fn memory_held() {
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
