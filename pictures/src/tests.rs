//! The crate's own tests. They run on the computer the project is built on,
//! not in QEMU: `python test_pictures.py` in test-tools/ runs them. The test
//! pictures and packed streams are made by test-tools/make_picture_cases.py
//! and kept in test-data/: cases.bin holds them one after another, and
//! cases.txt lists the cases and where each file lies in cases.bin.

#![allow(clippy::indexing_slicing, clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::env;
use std::fs;
use std::path::PathBuf;
use std::string::String;
use std::sync::OnceLock;
use std::vec::Vec;

use crate::check::{Adler, crc};
use crate::shrink::Shrink;
use crate::unpack::{Sink, Source, zlib_unpack};
use crate::{Limits, Refusal, fitted_size, png_head, png_picture};

// ---------- Helpers ----------

const ROOMY: Limits = Limits { dots_most: 1 << 26, side_most: 1 << 15, interlaced_dots_most: 1 << 22 };

fn data_path(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("test-data").join(name)
}

/// cases.txt and cases.bin, read once for all the tests.
fn data() -> &'static (String, Vec<u8>) {
    static DATA: OnceLock<(String, Vec<u8>)> = OnceLock::new();
    DATA.get_or_init(|| (fs::read_to_string(data_path("cases.txt")).unwrap(), fs::read(data_path("cases.bin")).unwrap()))
}

/// A test file, by its name: the bytes that its line `file NAME AT LENGTH`
/// in cases.txt says it has in cases.bin.
fn read(name: &str) -> Vec<u8> {
    let (list, all) = data();
    for line in list.lines() {
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.len() == 4 && words[0] == "file" && words[1] == name {
            let (at, length) = (words[2].parse::<usize>().unwrap(), words[3].parse::<usize>().unwrap());
            return all[at..at + length].to_vec();
        }
    }
    panic!("{}: no such test file", name);
}

/// The lines of cases.txt that begin with `kind`, each split at spaces.
fn cases(kind: &str) -> Vec<Vec<String>> {
    let list = &data().0;
    list.lines()
        .map(|line| line.split_whitespace().map(String::from).collect::<Vec<_>>())
        .filter(|words| words.first().map(String::as_str) == Some(kind))
        .collect()
}

/// A fixed sequence of numbers (xorshift32), for damage that is the same at
/// every run.
struct Numbers(u32);

impl Numbers {
    fn next(&mut self) -> u32 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.0 = x;
        x
    }

    fn below(&mut self, n: usize) -> usize {
        self.next() as usize % n.max(1)
    }
}

struct Bytes {
    data: Vec<u8>,
    at: usize,
}

impl Source for Bytes {
    fn next_byte(&mut self) -> Option<u8> {
        let byte = self.data.get(self.at).copied();
        self.at += 1;
        byte
    }
}

/// Gathers what is unpacked, and stops the unpacking past `most` bytes.
struct Gather {
    out: Vec<u8>,
    most: usize,
}

impl Sink for Gather {
    fn take(&mut self, bytes: &[u8]) -> Result<(), Refusal> {
        if self.out.len() + bytes.len() > self.most {
            return Err(Refusal::Damaged("more than wanted"));
        }
        self.out.extend_from_slice(bytes);
        Ok(())
    }
}

fn unpack(data: &[u8]) -> Result<Vec<u8>, Refusal> {
    let mut source = Bytes { data: data.to_vec(), at: 0 };
    let mut gather = Gather { out: Vec::new(), most: 1 << 24 };
    zlib_unpack(&mut source, &mut gather)?;
    Ok(gather.out)
}

/// A zlib stream that stores `data` as it is, in stored blocks.
fn stored_stream(data: &[u8]) -> Vec<u8> {
    let mut out = vec![0x78, 0x01];
    let pieces: Vec<&[u8]> = if data.is_empty() { vec![&[][..]] } else { data.chunks(65_535).collect() };
    for (i, piece) in pieces.iter().enumerate() {
        out.push(if i + 1 == pieces.len() { 1 } else { 0 });
        let length = piece.len() as u16;
        out.extend_from_slice(&length.to_le_bytes());
        out.extend_from_slice(&(!length).to_le_bytes());
        out.extend_from_slice(piece);
    }
    let mut sum = Adler::new();
    sum.add(data);
    out.extend_from_slice(&sum.value().to_be_bytes());
    out
}

/// One part of a PNG file, with its check value.
fn part(name: &[u8; 4], data: &[u8]) -> Vec<u8> {
    let mut out = (data.len() as u32).to_be_bytes().to_vec();
    out.extend_from_slice(name);
    out.extend_from_slice(data);
    let mut named = name.to_vec();
    named.extend_from_slice(data);
    out.extend_from_slice(&crc(&named).to_be_bytes());
    out
}

/// A PNG file's parts: (where it begins, its name, its data).
fn parts_of(file: &[u8]) -> Vec<(usize, [u8; 4], Vec<u8>)> {
    let mut parts = Vec::new();
    let mut at = 8;
    while at + 12 <= file.len() {
        let length = u32::from_be_bytes(file[at..at + 4].try_into().unwrap()) as usize;
        let name: [u8; 4] = file[at + 4..at + 8].try_into().unwrap();
        if at + 12 + length > file.len() {
            break;
        }
        parts.push((at, name, file[at + 8..at + 8 + length].to_vec()));
        at += 12 + length;
        if &name == b"IEND" {
            break;
        }
    }
    parts
}

/// A PNG file's parts as they are put together: each part's name and data.
type Parts<'a> = Vec<(&'a [u8; 4], Vec<u8>)>;

/// A PNG file made of these parts, after the signature.
fn file_of(parts: &[(&[u8; 4], Vec<u8>)]) -> Vec<u8> {
    let mut out = vec![137, 80, 78, 71, 13, 10, 26, 10];
    for (name, data) in parts {
        out.extend_from_slice(&part(name, data));
    }
    out
}

fn head_data(width: u32, height: u32, depth: u8, colour: u8, interlace: u8) -> Vec<u8> {
    let mut data = width.to_be_bytes().to_vec();
    data.extend_from_slice(&height.to_be_bytes());
    data.extend_from_slice(&[depth, colour, 0, 0, interlace]);
    data
}

/// A small, sound picture: 3 by 2 red-green-blue dots, filter 0.
fn small_rgb() -> Parts<'static> {
    // Two rows, each a filter byte and three dots of three bytes.
    let rows = [0u8, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 10, 11, 12, 13, 14, 15, 16, 17, 18];
    vec![(b"IHDR", head_data(3, 2, 8, 2, 0)), (b"IDAT", stored_stream(&rows)), (b"IEND", Vec::new())]
}

fn show(file: &[u8]) -> Result<crate::Picture, Refusal> {
    png_picture(file, 1 << 15, 1 << 15, &ROOMY)
}

// ---------- Unpacking ----------

#[test]
fn streams_unpack() {
    let streams = cases("zlib");
    assert!(streams.len() >= 10);
    for words in streams {
        let (name, length, check) = (&words[1], words[2].parse::<usize>().unwrap(), words[3].parse::<u32>().unwrap());
        let out = unpack(&read(&format!("{}.zlib", name))).unwrap_or_else(|refusal| panic!("{}: {:?}", name, refusal));
        assert_eq!(out.len(), length, "{}", name);
        assert_eq!(crc(&out), check, "{}", name);
    }
}

#[test]
fn streams_cut_anywhere() {
    for words in cases("zlib") {
        let data = read(&format!("{}.zlib", words[1]));
        let step = (data.len() / 300).max(1);
        let ends: Vec<usize> = (0..data.len()).step_by(step).chain(data.len().saturating_sub(12)..data.len()).collect();
        for end in ends {
            match unpack(&data[..end]) {
                Err(Refusal::CutShort) | Err(Refusal::Damaged(_)) => {}
                other => panic!("{} cut at {}: {:?}", words[1], end, other.map(|out| out.len())),
            }
        }
    }
}

#[test]
fn streams_damaged_anywhere() {
    let mut numbers = Numbers(2026);
    for words in cases("zlib") {
        let data = read(&format!("{}.zlib", words[1]));
        if data.is_empty() {
            continue;
        }
        for _ in 0..400 {
            let mut damaged = data.clone();
            let at = numbers.below(damaged.len());
            damaged[at] ^= 1 << numbers.below(8);
            // Whatever comes of it, it must come back; the check value makes
            // a damaged stream that unpacks whole all but impossible.
            if let Ok(out) = unpack(&damaged) {
                assert_eq!(crc(&out), words[3].parse::<u32>().unwrap(), "{} damaged at {} unpacked to something else", words[1], at);
            }
        }
    }
}

/// Writes DEFLATE's bits: other numbers lowest bit first, codes highest
/// bit first (RFC 1951, 3.1.1).
struct BitWriter {
    out: Vec<u8>,
    held: u64,
    count: u32,
}

impl BitWriter {
    fn new() -> BitWriter {
        BitWriter { out: vec![0x78, 0x01], held: 0, count: 0 }
    }

    fn bits(&mut self, value: u32, count: u32) {
        self.held |= u64::from(value) << self.count;
        self.count += count;
        while self.count >= 8 {
            self.out.push(self.held as u8);
            self.held >>= 8;
            self.count -= 8;
        }
    }

    fn code(&mut self, code: u32, length: u32) {
        let mut turned = 0;
        for bit in 0..length {
            turned = (turned << 1) | ((code >> bit) & 1);
        }
        self.bits(turned, length);
    }

    /// A symbol of the fixed literal and length code (RFC 1951, 3.2.6).
    fn fixed_symbol(&mut self, symbol: u32) {
        match symbol {
            0..=143 => self.code(0x30 + symbol, 8),
            144..=255 => self.code(0x190 + symbol - 144, 9),
            256..=279 => self.code(symbol - 256, 7),
            _ => self.code(0xc0 + symbol - 280, 8),
        }
    }

    fn fixed_copy(&mut self, length: u32, distance: u32) {
        let lengths: [(u32, u32); 29] = [
            (3, 0), (4, 0), (5, 0), (6, 0), (7, 0), (8, 0), (9, 0), (10, 0), (11, 1), (13, 1), (15, 1), (17, 1),
            (19, 2), (23, 2), (27, 2), (31, 2), (35, 3), (43, 3), (51, 3), (59, 3), (67, 4), (83, 4), (99, 4),
            (115, 4), (131, 5), (163, 5), (195, 5), (227, 5), (258, 0),
        ];
        let distances: [(u32, u32); 30] = [
            (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (7, 1), (9, 2), (13, 2), (17, 3), (25, 3), (33, 4), (49, 4),
            (65, 5), (97, 5), (129, 6), (193, 6), (257, 7), (385, 7), (513, 8), (769, 8), (1025, 9), (1537, 9),
            (2049, 10), (3073, 10), (4097, 11), (6145, 11), (8193, 12), (12289, 12), (16385, 13), (24577, 13),
        ];
        let index = if length == 258 { 28 } else { lengths.iter().rposition(|(base, _)| *base <= length).unwrap() };
        let (base, extra) = lengths[index];
        self.fixed_symbol(257 + index as u32);
        self.bits(length - base, extra);
        let index = distances.iter().rposition(|(base, _)| *base <= distance).unwrap();
        let (base, extra) = distances[index];
        self.code(index as u32, 5);
        self.bits(distance - base, extra);
    }

    fn finish(mut self, sum: u32) -> Vec<u8> {
        if self.count > 0 {
            self.bits(0, 8 - self.count);
        }
        self.out.extend_from_slice(&sum.to_be_bytes());
        self.out
    }
}

fn adler(data: &[u8]) -> u32 {
    let mut sum = Adler::new();
    sum.add(data);
    sum.value()
}

#[test]
fn every_length_and_distance() {
    // One fixed block: 33,000 made-up literals, then copies of every length
    // from 3 to 258 and of the edges of every distance code, 32,768 among
    // them, until more than 98,304 bytes have come, so that copies reach
    // back across the place where unpacked bytes are handed on.
    let mut numbers = Numbers(7);
    let mut meant: Vec<u8> = Vec::new();
    let mut writer = BitWriter::new();
    writer.bits(1, 1);
    writer.bits(1, 2);
    for _ in 0..33_000 {
        let byte = numbers.below(256) as u32;
        writer.fixed_symbol(byte);
        meant.push(byte as u8);
    }
    let copy = |writer: &mut BitWriter, meant: &mut Vec<u8>, length: u32, distance: u32| {
        writer.fixed_copy(length, distance);
        for _ in 0..length {
            let byte = meant[meant.len() - distance as usize];
            meant.push(byte);
        }
    };
    for length in 3..=258 {
        copy(&mut writer, &mut meant, length, 1 + (length * 97) % 32_768);
    }
    // Up to exactly 98,304 bytes, where the first are handed on and the last
    // 32,768 kept; then a copy that reaches back all of them.
    while meant.len() < 98_304 {
        let rest = 98_304 - meant.len();
        if rest >= 3 {
            copy(&mut writer, &mut meant, rest.min(258) as u32, 1000);
        } else {
            writer.fixed_symbol(u32::from(b'x'));
            meant.push(b'x');
        }
    }
    copy(&mut writer, &mut meant, 258, 32_768);
    let edges = [1u32, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 16, 17, 24, 25, 32, 33, 48, 49, 64, 65, 96, 97, 128, 129, 192, 193,
        256, 257, 384, 385, 512, 513, 768, 769, 1024, 1025, 1536, 1537, 2048, 2049, 3072, 3073, 4096, 4097, 6144, 6145,
        8192, 8193, 12288, 12289, 16384, 16385, 24576, 24577, 32768];
    while meant.len() < 120_000 {
        for distance in edges {
            copy(&mut writer, &mut meant, 3 + distance % 256, distance);
        }
    }
    copy(&mut writer, &mut meant, 258, 32_768);
    writer.fixed_symbol(256);
    let stream = writer.finish(adler(&meant));
    assert_eq!(unpack(&stream).unwrap(), meant);
}

#[test]
fn streams_turned_down() {
    let empty = stored_stream(b"");
    assert_eq!(unpack(&empty).unwrap(), Vec::<u8>::new());

    // The head (RFC 1950): a check that does not divide by 31, a packing
    // other than deflate, too wide a window, a dictionary.
    let mut bad = empty.clone();
    bad[1] = 0x02;
    assert!(matches!(unpack(&bad), Err(Refusal::Damaged(_))));
    for (cmf, flg) in [(0x77u8, 0x01u8), (0x88, 0x00), (0x78, 0x20)] {
        let mut flg = flg;
        while (u32::from(cmf) * 256 + u32::from(flg)) % 31 != 0 {
            flg += 1;
        }
        let mut bad = empty.clone();
        bad[0] = cmf;
        bad[1] = flg;
        assert!(matches!(unpack(&bad), Err(Refusal::Damaged(_))), "cmf {:x} flg {:x}", cmf, flg);
    }

    // A block of kind 3.
    let mut writer = BitWriter::new();
    writer.bits(1, 1);
    writer.bits(3, 2);
    assert!(matches!(unpack(&writer.finish(1)), Err(Refusal::Damaged(_))));

    // A stored block whose length check does not fit.
    let mut bad = stored_stream(b"abc");
    bad[5] ^= 0xff;
    assert!(matches!(unpack(&bad), Err(Refusal::Damaged(_))));

    // A copy from before the beginning.
    let mut writer = BitWriter::new();
    writer.bits(1, 1);
    writer.bits(1, 2);
    writer.fixed_copy(3, 1);
    writer.fixed_symbol(256);
    assert!(matches!(unpack(&writer.finish(1)), Err(Refusal::Damaged(_))));

    // Literal codes 286 and 287, and distance codes 30 and 31.
    for symbol in [286u32, 287] {
        let mut writer = BitWriter::new();
        writer.bits(1, 1);
        writer.bits(1, 2);
        writer.fixed_symbol(symbol);
        assert!(matches!(unpack(&writer.finish(1)), Err(Refusal::Damaged(_))), "{}", symbol);
    }
    for code in [30u32, 31] {
        let mut writer = BitWriter::new();
        writer.bits(1, 1);
        writer.bits(1, 2);
        writer.fixed_symbol(b'a'.into());
        writer.fixed_symbol(257);
        writer.code(code, 5);
        writer.fixed_symbol(256);
        assert!(matches!(unpack(&writer.finish(1)), Err(Refusal::Damaged(_))), "{}", code);
    }

    // A check value that does not fit.
    let mut bad = stored_stream(b"abc");
    let last = bad.len() - 1;
    bad[last] ^= 1;
    assert!(matches!(unpack(&bad), Err(Refusal::Damaged(_))));

    // Dynamic blocks: too many literal codes; a repeat with nothing before
    // it; a repeat past the end; a code-length code with more codes than can
    // be. Each head: last block, kind 2, then HLIT, HDIST (0: one distance
    // code), HCLEN (15: all 19 code-length lengths), then those lengths, then
    // code-length symbols as (code, its bits, extra value, extra bits).
    let dynamic = |literal_extra: u32, lengths_of_lengths: &[(usize, u32)], symbols: &[(u32, u32, u32, u32)]| {
        let mut writer = BitWriter::new();
        writer.bits(1, 1);
        writer.bits(2, 2);
        writer.bits(literal_extra, 5);
        writer.bits(0, 5);
        writer.bits(15, 4);
        let order = [16usize, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
        for symbol in order {
            let length = lengths_of_lengths.iter().find(|(s, _)| *s == symbol).map(|(_, l)| *l).unwrap_or(0);
            writer.bits(length, 3);
        }
        for (code, length, extra, extra_bits) in symbols {
            writer.code(*code, *length);
            writer.bits(*extra, *extra_bits);
        }
        unpack(&writer.finish(1))
    };
    // With one-bit codes for 16 and 18, the smaller symbol takes the
    // smaller code (RFC 1951, 3.2.2): 16 is code 0, 18 is code 1.
    // HLIT 30: 287 literal codes, more than 286.
    assert_eq!(dynamic(30, &[(18, 1), (16, 1)], &[]), Err(Refusal::Damaged(crate::unpack::TOO_MANY_CODES)));
    // 16, repeat the length before, as the first length: there is none.
    assert_eq!(dynamic(0, &[(18, 1), (16, 1)], &[(0, 1, 0, 2)]), Err(Refusal::Damaged(crate::unpack::LENGTHS)));
    // 18, 138 zeros, twice: past the 257 + 1 lengths wanted.
    assert_eq!(dynamic(0, &[(18, 1), (16, 1)], &[(1, 1, 127, 7), (1, 1, 127, 7)]), Err(Refusal::Damaged(crate::unpack::LENGTHS)));
    // Three code-length codes of one bit: more than can be.
    assert_eq!(dynamic(0, &[(18, 1), (16, 1), (17, 1)], &[]), Err(Refusal::Damaged(crate::unpack::OVERFULL)));

    // A sink that wants no more stops it.
    let mut source = Bytes { data: read("z-text.zlib"), at: 0 };
    let mut gather = Gather { out: Vec::new(), most: 1000 };
    assert!(matches!(zlib_unpack(&mut source, &mut gather), Err(Refusal::Damaged("more than wanted"))));
}

// ---------- Pictures ----------

#[test]
fn pictures_read_whole() {
    let pictures = cases("png");
    assert!(pictures.len() >= 25);
    for words in pictures {
        let (name, width, height) = (&words[1], words[2].parse::<u32>().unwrap(), words[3].parse::<u32>().unwrap());
        let file = read(&format!("{}.png", name));
        let head = png_head(&file).unwrap();
        assert_eq!((head.width, head.height), (width, height), "{}", name);
        let picture = show(&file).unwrap_or_else(|refusal| panic!("{}: {:?}", name, refusal));
        assert_eq!((picture.width, picture.height), (width, height), "{}", name);
        same_dots(name, &picture.dots, &read(&format!("{}.rgba", name)));
    }
}

/// Fails with the first dot that differs, if any does.
fn same_dots(name: &str, got: &[u8], meant: &[u8]) {
    assert_eq!(got.len(), meant.len(), "{}: {} bytes of dots, not {}", name, got.len(), meant.len());
    if let Some(at) = got.iter().zip(meant).position(|(a, b)| a != b) {
        let dot = at / 4 * 4;
        panic!("{}: dot {} is {:?}, meant {:?}", name, at / 4, &got[dot..dot + 4], &meant[dot..dot + 4]);
    }
}

#[test]
fn pictures_shrunk() {
    let shrunk = cases("shrunk");
    assert!(shrunk.len() >= 8);
    for words in shrunk {
        let name = &words[1];
        let numbers: Vec<u32> = words[2..6].iter().map(|word| word.parse().unwrap()).collect();
        let picture = png_picture(&read(&format!("{}.png", name)), numbers[0], numbers[1], &ROOMY).unwrap();
        assert_eq!((picture.width, picture.height), (numbers[2], numbers[3]), "{}", name);
        assert!(picture.dots == read(&format!("{}-{}x{}.rgba", name, numbers[0], numbers[1])), "{} in {}x{}", name, numbers[0], numbers[1]);
    }
}

#[test]
fn fitted_by_hand() {
    assert_eq!(fitted_size(10, 10, 20, 20), (10, 10));
    assert_eq!(fitted_size(100, 50, 10, 10), (10, 5));
    assert_eq!(fitted_size(50, 100, 10, 10), (5, 10));
    // 1 * 2 / 3 is 0.67, rounded to 1.
    assert_eq!(fitted_size(3, 1, 2, 1), (2, 1));
    assert_eq!(fitted_size(1, 3, 1, 2), (1, 2));
    // 3 * 5 / 7 is 2.14, rounded to 2.
    assert_eq!(fitted_size(7, 3, 5, 5), (5, 2));
    // 10 / 1000 rounds to 0, and a side is at least 1.
    assert_eq!(fitted_size(1000, 1, 10, 10), (10, 1));
    // The usual frame on 1280 by 800: a 1600 by 1200 photo.
    assert_eq!(fitted_size(1600, 1200, 554, 400), (533, 400));
}

#[test]
fn shrink_by_hand() {
    // Four opaque dots into one: their average.
    let mut shrink = Shrink::new(2, 2, 1, 1);
    shrink.take_row(0, &[10, 20, 30, 255, 20, 30, 40, 255]);
    shrink.take_row(1, &[30, 40, 50, 255, 40, 50, 60, 255]);
    assert_eq!(shrink.finish().dots, vec![25, 35, 45, 255]);

    // An opaque red dot beside a wholly see-through blue one: red, half
    // covering (255 / 2 rounds to 128); the see-through blue adds nothing.
    let mut shrink = Shrink::new(2, 1, 1, 1);
    shrink.take_row(0, &[255, 0, 0, 255, 0, 0, 255, 0]);
    assert_eq!(shrink.finish().dots, vec![255, 0, 0, 128]);

    // Three dots into two: columns 0 and 1 fall on the first (0 * 2 / 3 and
    // 1 * 2 / 3 round down to 0), column 2 on the second.
    let mut shrink = Shrink::new(3, 1, 2, 1);
    shrink.take_row(0, &[0, 0, 0, 255, 100, 100, 100, 255, 7, 8, 9, 255]);
    assert_eq!(shrink.finish().dots, vec![50, 50, 50, 255, 7, 8, 9, 255]);
}

#[test]
fn pictures_cut_anywhere() {
    for words in cases("png") {
        let file = read(&format!("{}.png", words[1]));
        let end_of_end = parts_of(&file).last().map(|(at, _, data)| at + 12 + data.len()).unwrap();
        for end in 0..file.len() {
            match show(&file[..end]) {
                Ok(_) if end >= end_of_end => {}
                Err(Refusal::CutShort) => {}
                // A file cut inside its packed dots may also show as
                // fewer dots than its size, or as other damage.
                Err(Refusal::Damaged(_)) => {}
                other => panic!("{} cut at {}: {:?}", words[1], end, other.map(|p| p.width)),
            }
        }
    }
}

#[test]
fn pictures_damaged_anywhere() {
    // Damage of any byte, its part's check value left as it was: turned
    // down, nearly always by the check value; never a stop.
    let mut numbers = Numbers(11);
    for words in cases("png") {
        let file = read(&format!("{}.png", words[1]));
        for _ in 0..200 {
            let mut damaged = file.clone();
            let at = numbers.below(damaged.len());
            damaged[at] ^= 1 << numbers.below(8);
            let _ = show(&damaged);
        }
    }
}

#[test]
fn check_values_kept() {
    // Any byte of a part's name or data changed, its check value left as it
    // was: turned down by the check value, whatever the part.
    for words in cases("png") {
        let file = read(&format!("{}.png", words[1]));
        for (at, name, data) in parts_of(&file) {
            for offset in [4, 8 + data.len() / 2] {
                if offset >= 8 && data.is_empty() {
                    continue;
                }
                let mut damaged = file.clone();
                damaged[at + offset] ^= 0x20;
                assert_eq!(
                    show(&damaged),
                    Err(Refusal::Damaged("a part does not match its check value")),
                    "{}, part {}, byte {}",
                    words[1],
                    String::from_utf8_lossy(&name),
                    offset
                );
            }
        }
    }
}

#[test]
fn parts_damaged_and_checked_again() {
    // Damage inside a part's data, its check value made right again, so that
    // the damage reaches the reading of the head, the palette, the
    // transparency and the packed dots: never a stop.
    let mut numbers = Numbers(13);
    for words in cases("png") {
        let file = read(&format!("{}.png", words[1]));
        let parts = parts_of(&file);
        for _ in 0..300 {
            let which = numbers.below(parts.len());
            if parts[which].2.is_empty() {
                continue;
            }
            let mut rebuilt: Parts = parts.iter().map(|(_, name, data)| (name, data.clone())).collect();
            let data = &mut rebuilt[which].1;
            let at = numbers.below(data.len());
            data[at] ^= 1 << numbers.below(8);
            let _ = show(&file_of(&rebuilt));
        }
    }
}

#[test]
fn rows_damaged_and_packed_again() {
    // The unpacked rows themselves damaged and packed again, so that the
    // damage reaches the filters and the palette.
    for words in cases("raw") {
        let name = &words[1];
        let file = read(&format!("{}.png", name));
        let raw = read(&format!("{}.raw", name));
        let parts = parts_of(&file);
        let with_rows = |rows: &[u8]| {
            let mut rebuilt: Parts =
                parts.iter().filter(|(_, name, _)| name != b"IDAT" && name != b"IEND").map(|(_, n, d)| (n, d.clone())).collect();
            rebuilt.push((b"IDAT", stored_stream(rows)));
            rebuilt.push((b"IEND", Vec::new()));
            show(&file_of(&rebuilt))
        };
        // As it was, packed the other way: the same dots.
        assert!(with_rows(&raw).unwrap().dots == read(&format!("{}.rgba", name)), "{}", name);
        // A filter that does not exist.
        let mut bad = raw.clone();
        bad[0] = 5;
        assert_eq!(with_rows(&bad), Err(Refusal::Damaged("a row begins with a filter that does not exist")), "{}", name);
        // One byte short, one byte over.
        assert_eq!(with_rows(&raw[..raw.len() - 1]), Err(Refusal::Damaged("it holds fewer dots than its size")), "{}", name);
        let mut over = raw.clone();
        over.push(0);
        assert_eq!(with_rows(&over), Err(Refusal::Damaged("it holds more dots than its size")), "{}", name);
        // Every byte damaged in turn: never a stop.
        let mut numbers = Numbers(17);
        for _ in 0..300 {
            let mut damaged = raw.clone();
            let at = numbers.below(damaged.len());
            damaged[at] = numbers.below(256) as u8;
            let _ = with_rows(&damaged);
        }
    }
    // A palette of 200 colours, and a dot that names colour 255.
    let file = read("p8t.png");
    let mut raw = read("p8t.raw");
    raw[1] = 255;
    let parts = parts_of(&file);
    let mut rebuilt: Parts =
        parts.iter().filter(|(_, name, _)| name != b"IDAT" && name != b"IEND").map(|(_, n, d)| (n, d.clone())).collect();
    rebuilt.push((b"IDAT", stored_stream(&raw)));
    rebuilt.push((b"IEND", Vec::new()));
    assert_eq!(show(&file_of(&rebuilt)), Err(Refusal::Damaged("a dot names a colour its palette does not have")));
}

#[test]
fn heads_and_parts_turned_down() {
    let sound = file_of(&small_rgb());
    assert_eq!(show(&sound).unwrap().dots.len(), 3 * 2 * 4);

    // Not a PNG; a signature cut short.
    assert_eq!(show(b"GIF89a and so on"), Err(Refusal::NotPng));
    assert_eq!(show(&sound[..5]), Err(Refusal::CutShort));
    assert_eq!(png_head(b"\x89PNG\r\n\x1a\nxyz"), Err(Refusal::CutShort));

    // Heads that are not as they must be.
    let with_head = |head: Vec<u8>| {
        let mut parts = small_rgb();
        parts[0].1 = head;
        show(&file_of(&parts))
    };
    for head in [
        head_data(0, 2, 8, 2, 0),
        head_data(3, 0x8000_0000, 8, 2, 0),
        head_data(3, 2, 3, 2, 0),
        head_data(3, 2, 8, 5, 0),
        head_data(3, 2, 4, 2, 0),
        head_data(3, 2, 16, 3, 0),
        head_data(3, 2, 8, 2, 2),
        head_data(3, 2, 8, 2, 0)[..12].to_vec(),
    ] {
        assert!(matches!(with_head(head.clone()), Err(Refusal::Damaged(_))), "{:?}", head);
    }
    let mut packing = head_data(3, 2, 8, 2, 0);
    packing[10] = 1;
    assert!(matches!(with_head(packing), Err(Refusal::Damaged(_))));
    let mut filtering = head_data(3, 2, 8, 2, 0);
    filtering[11] = 1;
    assert!(matches!(with_head(filtering), Err(Refusal::Damaged(_))));

    // Parts out of order, missing, doubled, unknown.
    let parts = small_rgb();
    let (head, dots, end) = (parts[0].clone(), parts[1].clone(), parts[2].clone());
    let text = (b"tEXt", b"a\0b".to_vec());
    let palette = (b"PLTE", vec![1, 2, 3]);
    let cases: Vec<(Parts, Refusal)> = vec![
        (vec![dots.clone(), head.clone(), end.clone()], Refusal::Damaged("it does not begin with its head")),
        (vec![head.clone(), head.clone(), dots.clone(), end.clone()], Refusal::Damaged("it has two heads")),
        (vec![head.clone(), end.clone()], Refusal::Damaged("it has no dots")),
        (vec![head.clone(), dots.clone()], Refusal::CutShort),
        (vec![head.clone(), dots.clone(), (b"IEND", vec![0])], Refusal::Damaged("its end part is not empty")),
        (vec![head.clone(), (b"ABCD", vec![1, 2]), dots.clone(), end.clone()], Refusal::UnknownPart(*b"ABCD")),
        (vec![head.clone(), dots.clone(), (b"PLTE", vec![1, 2, 3]), end.clone()], Refusal::Damaged("its parts are not in the order a PNG must have")),
        (vec![head.clone(), palette.clone(), palette.clone(), dots.clone(), end.clone()], Refusal::Damaged("it has two palettes")),
        (vec![head.clone(), (b"PLTE", vec![1, 2, 3, 4]), dots.clone(), end.clone()], Refusal::Damaged("its palette is not as a palette must be")),
        (vec![head.clone(), (b"PLTE", Vec::new()), dots.clone(), end.clone()], Refusal::Damaged("its palette is not as a palette must be")),
        (vec![head.clone(), (b"tRNS", vec![0, 1]), dots.clone(), end.clone()], Refusal::Damaged("its transparency part is not as it must be")),
        (vec![head.clone(), (b"tRNS", vec![0; 6]), (b"tRNS", vec![0; 6]), dots.clone(), end.clone()], Refusal::Damaged("it has two transparency parts")),
        (vec![head.clone(), (b"tRNS", vec![0; 6]), palette.clone(), dots.clone(), end.clone()], Refusal::Damaged("its parts are not in the order a PNG must have")),
    ];
    for (parts, meant) in cases {
        assert_eq!(show(&file_of(&parts)), Err(meant), "{:?}", parts.iter().map(|(n, _)| String::from_utf8_lossy(&n[..]).into_owned()).collect::<Vec<_>>());
    }

    // The packed dots split by another part: the dots in two IDAT parts
    // with a tEXt part between.
    let packed = dots.1.clone();
    let (one, two) = packed.split_at(packed.len() / 2);
    let split = vec![head.clone(), (b"IDAT", one.to_vec()), text.clone(), (b"IDAT", two.to_vec()), end.clone()];
    assert_eq!(show(&file_of(&split)), Err(Refusal::Damaged("its packed dots are not in one run of parts")));
    // The same with nothing between, and an empty part: sound.
    let joined = vec![head.clone(), (b"IDAT", one.to_vec()), (b"IDAT", Vec::new()), (b"IDAT", two.to_vec()), end.clone()];
    assert!(show(&file_of(&joined)).is_ok());

    // Palette pictures: no palette; a palette larger than the depth allows;
    // grey with a palette; a transparency part longer than the palette.
    let palette_head = (b"IHDR", head_data(3, 2, 1, 3, 0));
    let rows = (b"IDAT", stored_stream(&[0, 0b0100_0000, 0, 0b1000_0000]));
    assert_eq!(show(&file_of(&[palette_head.clone(), rows.clone(), end.clone()])), Err(Refusal::Damaged("it has no palette, which its kind of colour needs")));
    assert_eq!(show(&file_of(&[palette_head.clone(), (b"PLTE", vec![0; 9]), rows.clone(), end.clone()])), Err(Refusal::Damaged("its palette is not as a palette must be")));
    assert!(show(&file_of(&[palette_head.clone(), (b"PLTE", vec![0; 6]), rows.clone(), end.clone()])).is_ok());
    assert_eq!(show(&file_of(&[palette_head.clone(), (b"PLTE", vec![0; 6]), (b"tRNS", vec![0; 3]), rows.clone(), end.clone()])), Err(Refusal::Damaged("its transparency part is not as it must be")));
    let grey_head = (b"IHDR", head_data(3, 2, 8, 0, 0));
    assert_eq!(show(&file_of(&[grey_head, (b"PLTE", vec![0; 6]), dots.clone(), end.clone()])), Err(Refusal::Damaged("it has a palette, which its kind of colour may not have")));
    let alpha_head = (b"IHDR", head_data(3, 2, 8, 6, 0));
    assert_eq!(show(&file_of(&[alpha_head, (b"tRNS", vec![0; 6]), dots.clone(), end.clone()])), Err(Refusal::Damaged("its transparency part is not as it must be")));

    // A part's length larger than a PNG allows.
    let mut long = file_of(&small_rgb());
    long[33..37].copy_from_slice(&0x8000_0000u32.to_be_bytes());
    assert_eq!(show(&long), Err(Refusal::Damaged("a part says it is longer than a PNG allows")));

    // A part's name that is not letters, with its check value right.
    let mut odd = small_rgb();
    odd.insert(1, (b"a1bc", vec![1]));
    assert_eq!(show(&file_of(&odd)), Err(Refusal::Damaged("a part's name is not four letters")));
}

#[test]
fn limits_kept() {
    // A head that says 30,000 by 30,000, with no dots: turned down for its
    // size before anything is unpacked.
    let huge = file_of(&[(b"IHDR", head_data(30_000, 30_000, 8, 2, 0)), (b"IDAT", stored_stream(b"")), (b"IEND", Vec::new())]);
    assert_eq!(show(&huge), Err(Refusal::TooLarge { width: 30_000, height: 30_000 }));
    // A 3 by 2 picture: just inside limits of 6 dots and 3 a side, and one
    // dot over 5.
    let sound = file_of(&small_rgb());
    let tight = Limits { dots_most: 6, side_most: 3, interlaced_dots_most: 6 };
    assert!(png_picture(&sound, 3, 2, &tight).is_ok());
    let tighter = Limits { dots_most: 5, side_most: 3, interlaced_dots_most: 5 };
    assert_eq!(png_picture(&sound, 3, 1, &tighter), Err(Refusal::TooLarge { width: 3, height: 2 }));
    // An interlaced 3 by 3 picture, with room for 9 dots but 8 interlaced.
    let interlaced = read("three.png");
    let narrow = Limits { dots_most: 9, side_most: 3, interlaced_dots_most: 8 };
    assert_eq!(png_picture(&interlaced, 3, 3, &narrow), Err(Refusal::TooLarge { width: 3, height: 3 }));
    // No room; a room larger than the limits is no harm, since the picture
    // is never shown larger than it is.
    assert_eq!(png_picture(&sound, 0, 3, &ROOMY), Err(Refusal::NoRoom));
    assert_eq!(png_picture(&sound, 3, 0, &ROOMY), Err(Refusal::NoRoom));
    assert_eq!(png_picture(&sound, u32::MAX, u32::MAX, &tight).map(|picture| (picture.width, picture.height)), Ok((3, 2)));
}

#[test]
fn reasons_in_words() {
    assert_eq!(Refusal::CutShort.because(), "the file ends before the picture does");
    assert_eq!(Refusal::UnknownPart(*b"ab\x001").because(), "it holds a part I cannot read, \"ab..\"");
    assert_eq!(Refusal::TooLarge { width: 9, height: 8 }.because(), "it is 9 by 8 dots, more than I show");
    assert_eq!(Refusal::Damaged("x").because(), "it is damaged: x");
}

/// PNG pictures made by other programs, read by both readers: the list is
/// made by test_pictures.py --cross-check, with the second reader's dots
/// beside each file. Run only when asked.
#[test]
#[ignore]
fn cross_check() {
    let folder = PathBuf::from(env::var("PICTURES_CROSS_CHECK").expect("PICTURES_CROSS_CHECK names the folder"));
    let list = fs::read_to_string(folder.join("list.txt")).unwrap();
    let mut compared = 0;
    for line in list.lines() {
        let words: Vec<&str> = line.split('\t').collect();
        let (path, width, height, dots) = (words[0], words[1].parse::<u32>().unwrap(), words[2].parse::<u32>().unwrap(), words[3]);
        let picture = show(&fs::read(path).unwrap()).unwrap_or_else(|refusal| panic!("{}: {:?}", path, refusal));
        assert_eq!((picture.width, picture.height), (width, height), "{}", path);
        assert!(picture.dots == fs::read(folder.join(dots)).unwrap(), "{}: the dots differ", path);
        compared += 1;
    }
    println!("cross-checked {} pictures", compared);
}
