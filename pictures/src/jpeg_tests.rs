//! The crate's own tests of JPEG photos. Like those of tests.rs, they run on
//! the computer the project is built on: `python test_pictures.py` in
//! test-tools/ runs them. The test photos are made by
//! test-tools/make_jpeg_cases.py and kept in test-data/: jpeg-cases.bin
//! holds them one after another, and jpeg-cases.txt lists the cases and
//! where each file lies in jpeg-cases.bin.

#![allow(clippy::indexing_slicing, clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::env;
use std::f64::consts::PI;
use std::fs;
use std::path::PathBuf;
use std::println;
use std::string::String;
use std::sync::OnceLock;
use std::vec::Vec;

use crate::entropy::{self, Band, Bits, Block, Code, Keep, ZIGZAG};
use crate::shrink::Shrink;
use crate::transform::{block_samples, rgb_of_ycc};
use crate::{JpegLimits, Picture, Refusal, fitted_size, jpeg_head, jpeg_picture};

const ROOMY: JpegLimits = JpegLimits { dots_most: 1 << 28, side_most: 1 << 15, held_most: 1 << 32 };

// ---------- Helpers ----------

fn data_path(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("test-data").join(name)
}

/// jpeg-cases.txt and jpeg-cases.bin, read once for all the tests.
fn data() -> &'static (String, Vec<u8>) {
    static DATA: OnceLock<(String, Vec<u8>)> = OnceLock::new();
    DATA.get_or_init(|| (fs::read_to_string(data_path("jpeg-cases.txt")).unwrap(), fs::read(data_path("jpeg-cases.bin")).unwrap()))
}

/// A test file, by its name.
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

/// The lines of jpeg-cases.txt that begin with `kind`, each split at spaces.
fn cases(kind: &str) -> Vec<Vec<String>> {
    data()
        .0
        .lines()
        .map(|line| line.split_whitespace().map(String::from).collect::<Vec<_>>())
        .filter(|words| words.first().map(String::as_str) == Some(kind))
        .collect()
}

/// A photo read at its whole size.
fn show(file: &[u8]) -> Result<Picture, Refusal> {
    jpeg_picture(file, u32::MAX, u32::MAX, &ROOMY)
}

/// Fails with the first dot that differs, if any does.
fn same_dots(name: &str, got: &[u8], meant: &[u8]) {
    assert_eq!(got.len(), meant.len(), "{}: {} bytes of dots, not {}", name, got.len(), meant.len());
    if let Some(at) = got.iter().zip(meant).position(|(a, b)| a != b) {
        let dot = at / 4 * 4;
        panic!("{}: dot {} is {:?}, meant {:?}", name, at / 4, &got[dot..dot + 4], &meant[dot..dot + 4]);
    }
}

/// A fixed sequence of numbers (xorshift32).
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

    fn below(&mut self, n: u32) -> u32 {
        self.next() % n.max(1)
    }
}

/// Bytes from a string of 0s and 1s as an encoder sends them: the last
/// byte filled with 1s, and a 00 after every FF.
fn bits_of(text: &str) -> Vec<u8> {
    let bits: Vec<u8> = text.bytes().filter(|byte| *byte == b'0' || *byte == b'1').map(|byte| byte - b'0').collect();
    let mut out = Vec::new();
    for chunk in bits.chunks(8) {
        let mut byte = 0u8;
        for at in 0..8 {
            byte = (byte << 1) | chunk.get(at).copied().unwrap_or(1);
        }
        out.push(byte);
        if byte == 0xFF {
            out.push(0);
        }
    }
    out
}

// ---------- Photos ----------

#[test]
fn jpegs_read_whole() {
    let photos = cases("jpeg");
    assert!(photos.len() >= 30);
    for words in photos {
        let name = &words[1];
        let numbers: Vec<u32> = words[2..6].iter().map(|word| word.parse().unwrap()).collect();
        let file = read(&format!("{}.jpg", name));
        let head = jpeg_head(&file).unwrap();
        assert_eq!(
            (head.width, head.height, u32::from(head.components), u32::from(head.progressive)),
            (numbers[0], numbers[1], numbers[2], numbers[3]),
            "{}",
            name
        );
        let picture = show(&file).unwrap_or_else(|refusal| panic!("{}: {:?}", name, refusal));
        assert_eq!((picture.width, picture.height), (numbers[0], numbers[1]), "{}", name);
        same_dots(name, &picture.dots, &read(&format!("{}.rgba", name)));
    }
}

#[test]
fn jpegs_shrunk() {
    let shrunk = cases("jshrunk");
    assert!(shrunk.len() >= 25);
    for words in shrunk {
        let name = &words[1];
        let numbers: Vec<u32> = words[2..6].iter().map(|word| word.parse().unwrap()).collect();
        let picture = jpeg_picture(&read(&format!("{}.jpg", name)), numbers[0], numbers[1], &ROOMY).unwrap();
        assert_eq!((picture.width, picture.height), (numbers[2], numbers[3]), "{}", name);
        same_dots(
            &format!("{} in {}x{}", name, numbers[0], numbers[1]),
            &picture.dots,
            &read(&format!("{}-{}x{}.rgba", name, numbers[0], numbers[1])),
        );
    }
}

#[test]
fn jpegs_turned_down() {
    let refused = cases("jrefused");
    assert!(refused.len() >= 40);
    let list = &data().0;
    for words in refused {
        let name = &words[1];
        // The reason is the rest of the line, as it was written.
        let line = list.lines().find(|line| line.starts_with(&format!("jrefused {} ", name))).unwrap();
        let reason = &line[format!("jrefused {} ", name).len()..];
        match jpeg_picture(&read(&format!("{}.jpg", name)), 100, 100, &ROOMY) {
            Ok(_) => panic!("{}: read, but it must be turned down because {}", name, reason),
            Err(refusal) => assert_eq!(refusal.because(), reason, "{}", name),
        }
    }
}

#[test]
fn jpegs_cut_anywhere() {
    for name in ["seq420", "prog420r", "multiscan", "greyprog", "extras", "proglong"] {
        let file = read(&format!("{}.jpg", name));
        let end_of_end = file.windows(2).rposition(|pair| pair == [0xFF, 0xD9]).unwrap() + 2;
        for end in 0..end_of_end {
            match show(&file[..end]) {
                Err(Refusal::CutShort) => {}
                Err(Refusal::NotJpeg) if end < 2 => {}
                other => panic!("{} cut at {}: {:?}", name, end, other.map(|picture| (picture.width, picture.height))),
            }
        }
        assert!(show(&file[..end_of_end]).is_ok(), "{}", name);
    }
}

#[test]
fn jpegs_damaged_anywhere() {
    // Any byte changed must give a picture or a refusal, never a stop.
    let mut numbers = Numbers(7);
    for name in ["seq420", "prog420r", "multiscan", "greyprog", "proglong", "seq311", "mixed"] {
        let file = read(&format!("{}.jpg", name));
        for at in 0..file.len() {
            let mut damaged = file.clone();
            damaged[at] = numbers.below(256) as u8;
            let _ = show(&damaged);
            let _ = jpeg_picture(&damaged, 7, 5, &ROOMY);
            let _ = jpeg_head(&damaged);
        }
    }
}

#[test]
fn heads_read() {
    let file = read("prog420.jpg");
    let head = jpeg_head(&file).unwrap();
    assert_eq!((head.width, head.height, head.components, head.progressive), (77, 45, 3, true));
    assert_eq!(jpeg_head(b"GIF89a"), Err(Refusal::NotJpeg));
    assert_eq!(jpeg_head(&file[..20]), Err(Refusal::CutShort));
}

// ---------- Transforms and colours ----------

/// The exact inverse transform at n dots a side, in floating point, from
/// the first n by n dequantized coefficients (docs/pictures.md, "JPEG").
fn exact(n: usize, coefficients: &[i64; 64]) -> Vec<f64> {
    let c = |u: usize| if u == 0 { 0.5f64.sqrt() } else { 1.0 };
    let mut out = Vec::new();
    for y in 0..n {
        for x in 0..n {
            let mut sum = 0.0;
            for v in 0..n {
                for u in 0..n {
                    sum += c(u)
                        * c(v)
                        * coefficients[v * 8 + u] as f64
                        * ((2 * x + 1) as f64 * u as f64 * PI / (2 * n) as f64).cos()
                        * ((2 * y + 1) as f64 * v as f64 * PI / (2 * n) as f64).cos();
                }
            }
            out.push(sum / 4.0 + 128.0);
        }
    }
    out
}

#[test]
fn transforms_near_exact() {
    // Blocks of random samples, turned into coefficients in floating point
    // and quantized; read back, every dot is within one level of the exact
    // transform of the same coefficients.
    let mut numbers = Numbers(99);
    let mut most = 0.0f64;
    for round in 0..3000 {
        let samples: Vec<f64> = (0..64)
            .map(|_| if round % 3 == 0 { numbers.below(256) as f64 } else { (numbers.below(64) + 96 + round as u32 % 64) as f64 })
            .collect();
        let quant: [u16; 64] = core::array::from_fn(|_| 1 + numbers.below(if round % 2 == 0 { 4 } else { 40 }) as u16);
        let mut kept = [0i16; 64];
        let mut dequantized = [0i64; 64];
        for v in 0..8 {
            for u in 0..8 {
                let c = |w: usize| if w == 0 { 0.5f64.sqrt() } else { 1.0 };
                let mut sum = 0.0;
                for y in 0..8 {
                    for x in 0..8 {
                        sum += (samples[y * 8 + x] - 128.0)
                            * ((2 * x + 1) as f64 * u as f64 * PI / 16.0).cos()
                            * ((2 * y + 1) as f64 * v as f64 * PI / 16.0).cos();
                    }
                }
                let value = (c(u) * c(v) * sum / 4.0 / f64::from(quant[v * 8 + u])).round();
                kept[v * 8 + u] = value as i16;
                dequantized[v * 8 + u] = value as i64 * i64::from(quant[v * 8 + u]);
            }
        }
        for n in [1usize, 2, 4, 8] {
            let small: Vec<i16> = (0..n * n).map(|at| kept[at / n * 8 + at % n]).collect();
            let mut out = [0u8; 64];
            block_samples(n, &small, &quant, &mut out, n);
            for (got, meant) in out.iter().zip(exact(n, &dequantized)) {
                let meant = meant.clamp(0.0, 255.0);
                let off = (f64::from(*got) - meant).abs();
                most = most.max(off);
                assert!(off <= 1.0, "n = {}: {} against {:.3}", n, got, meant);
            }
        }
    }
    println!("transforms: at most {:.3} from the exact", most);
}

#[test]
fn eighth_is_the_average() {
    // n = 1: the block's first coefficient over 8, rounded, and 128 added.
    let quant = [1u16; 64];
    let mut out = [0u8; 1];
    for (first, meant) in [(0i16, 128u8), (8, 129), (4, 129), (3, 128), (-4, 128), (-5, 127), (1016, 255), (-1024, 0)] {
        block_samples(1, &[first], &quant, &mut out, 1);
        assert_eq!(out[0], meant, "{}", first);
    }
}

#[test]
fn colours_by_hand() {
    assert_eq!(rgb_of_ycc(128, 128, 128), [128, 128, 128]);
    assert_eq!(rgb_of_ycc(0, 128, 128), [0, 0, 0]);
    assert_eq!(rgb_of_ycc(255, 128, 128), [255, 255, 255]);
    assert_eq!(rgb_of_ycc(100, 200, 50), [0, 131, 228]);
    // JFIF's red, green and blue.
    assert_eq!(rgb_of_ycc(76, 85, 255), [254, 0, 0]);
    assert_eq!(rgb_of_ycc(150, 44, 21), [0, 255, 1]);
    assert_eq!(rgb_of_ycc(29, 255, 107), [0, 0, 254]);
}

// ---------- Codes and coefficients ----------

/// A table with one code of each length from 1 to 16: 0, 10, 110 and so on,
/// whose values are their lengths less one; all 16 1-bits is no code.
fn one_of_each() -> Code {
    Code::new(&[1; 16], &(0..16).collect::<Vec<u8>>()).unwrap()
}

#[test]
fn codes_by_hand() {
    // Every length, the long ones too, and FF 00 standing for FF.
    let code = one_of_each();
    let mut text = String::new();
    for length in 1..=16 {
        text.push_str(&"1".repeat(length - 1));
        text.push('0');
    }
    let mut packed = bits_of(&text);
    packed.extend_from_slice(&[0xFF, 0xD9]);
    let mut bits = Bits::new(&packed, 0);
    for length in 0..16u8 {
        assert_eq!(bits.decode(&code), Ok(length));
    }
    assert_eq!(bits.end_of_scan(), Ok(packed.len() - 2));

    // Sixteen 1-bits are no code.
    let mut bits = Bits::new(&[0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xD9], 0);
    assert_eq!(bits.decode(&code), Err(Refusal::Damaged("its data holds a code that its table does not have")));
    // Codes cut by a marker, and by the end of the file.
    let mut bits = Bits::new(&[0b1111_1111, 0x00, 0xFF, 0xD9], 0);
    assert_eq!(bits.decode(&code), Err(Refusal::Damaged("a scan's data ends before its last unit")));
    let mut bits = Bits::new(&[0b1111_1111, 0x00], 0);
    assert_eq!(bits.decode(&code), Err(Refusal::CutShort));
    // Fill bytes before a 00.
    let mut bits = Bits::new(&[0xFF, 0xFF, 0x00], 0);
    assert_eq!(bits.decode(&code), Err(Refusal::Damaged("its data holds fill bytes that no marker follows")));

    // Two codes of one bit: the second would be all 1-bits.
    assert!(Code::new(&[2], &[0, 1]).is_err());
    // A table that fills up 1 to 15 bits and has one of 16: the all-1s.
    let mut counts = [1u8; 16];
    counts[15] = 2;
    assert!(Code::new(&counts, &(0..17).collect::<Vec<u8>>()).is_err());
}

/// A block of n by n kept coefficients, all zero.
fn empty(n: usize) -> (Vec<i16>, u64) {
    (vec![0; n * n], 0)
}

#[test]
fn sequential_blocks_by_hand() {
    // DC: one code, size 0. AC: 0 EOB, 10 ZRL, 110 run 14 and size 1, 1110
    // run 5 and size 0, which means nothing.
    let dc = Code::new(&[1], &[0]).unwrap();
    let ac = Code::new(&[1, 1, 1, 1], &[0x00, 0xF0, 0xE1, 0x50]).unwrap();
    let keep = Keep::new(8);

    // Three ZRLs, then run 14 to coefficient 63, which is 1: a sound block.
    let packed = bits_of("0 10 10 10 110 1");
    let (mut kept, mut nonzero) = empty(8);
    let mut prediction = 0;
    let mut bits = Bits::new(&packed, 0);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    assert_eq!(entropy::sequential_block(&mut bits, &dc, &ac, &mut prediction, &mut block, &keep), Ok(()));
    assert_eq!(kept[63], 1);
    assert_eq!(nonzero, 1 << 63);

    // Four ZRLs run past the end of the block.
    let packed = bits_of("0 10 10 10 10");
    let (mut kept, mut nonzero) = empty(8);
    let mut bits = Bits::new(&packed, 0);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    assert_eq!(
        entropy::sequential_block(&mut bits, &dc, &ac, &mut prediction, &mut block, &keep),
        Err(Refusal::Damaged("a run of zeros goes past the end of its band"))
    );

    // A run of 5 with no value.
    let packed = bits_of("0 1110");
    let (mut kept, mut nonzero) = empty(8);
    let mut bits = Bits::new(&packed, 0);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    assert_eq!(
        entropy::sequential_block(&mut bits, &dc, &ac, &mut prediction, &mut block, &keep),
        Err(Refusal::Damaged("its data holds a code that means nothing"))
    );

    // A DC size of 16.
    let big = Code::new(&[1], &[16]).unwrap();
    let mut bits = Bits::new(&[0x00, 0x00], 0);
    let (mut kept, mut nonzero) = empty(8);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    assert_eq!(
        entropy::dc_first(&mut bits, &big, &mut prediction, 0, &mut block),
        Err(Refusal::Damaged("its data holds a code that means nothing"))
    );

    // DC differences add up from block to block, and a negative one's bits
    // begin with 0: size 3, 010 is -5; size 3, 111 is 7.
    let dc = Code::new(&[0, 1], &[3]).unwrap();
    let mut prediction = 100;
    let packed = bits_of("00 010 00 111");
    let mut bits = Bits::new(&packed, 0);
    for meant in [95i16, 102] {
        let (mut kept, mut nonzero) = empty(1);
        let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
        entropy::dc_first(&mut bits, &dc, &mut prediction, 0, &mut block).unwrap();
        assert_eq!(kept[0], meant);
    }
}

#[test]
fn progressive_blocks_by_hand() {
    let band = Band { start: 1, end: 63, low: 0 };
    let keep = Keep::new(8);

    // EOB2 and 11: a run of 4 + 3 = 7 blocks, this one and six more, which
    // take no bits.
    let ac = Code::new(&[1], &[0x20]).unwrap();
    let packed = bits_of("0 11 0 00");
    let mut bits = Bits::new(&packed, 0);
    let mut eob_run = 0;
    for _ in 0..7 {
        let (mut kept, mut nonzero) = empty(8);
        let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
        entropy::ac_first(&mut bits, &ac, band, &mut eob_run, &mut block, &keep).unwrap();
        assert_eq!(nonzero, 0);
    }
    assert_eq!(eob_run, 0);
    // The eighth reads EOB2 and 00: four blocks.
    let (mut kept, mut nonzero) = empty(8);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    entropy::ac_first(&mut bits, &ac, band, &mut eob_run, &mut block, &keep).unwrap();
    assert_eq!(eob_run, 3);

    // A first scan with Al 1: run 0, size 2, bits 10 is 2, shifted: 4.
    let ac = Code::new(&[1, 1], &[0x02, 0x00]).unwrap();
    let packed = bits_of("0 10 10");
    let mut bits = Bits::new(&packed, 0);
    let (mut kept, mut nonzero) = empty(8);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    let mut eob_run = 0;
    entropy::ac_first(&mut bits, &ac, Band { low: 1, ..band }, &mut eob_run, &mut block, &keep).unwrap();
    assert_eq!((kept[1], eob_run), (4, 0));

    // A refinement (G.1.2.3): coefficient 1 is 2 already. The code 0 (run 0,
    // size 1) and its sign 1: the first zero coefficient, 2, becomes 1, after
    // coefficient 1's correction bit, 1, makes it 3. Then 10, EOB0: the rest
    // of the band has nothing non-zero, so no more bits.
    let ac = Code::new(&[1, 1], &[0x01, 0x00]).unwrap();
    for n in [8usize, 2, 1] {
        let keep = Keep::new(n);
        let packed = bits_of("0 1 1 10");
        let mut bits = Bits::new(&packed, 0);
        let (mut kept, _) = empty(n);
        if n > 1 {
            kept[1] = 2;
        }
        let mut nonzero: u64 = 1 << ZIGZAG[1];
        let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
        let mut eob_run = 0;
        entropy::ac_refine(&mut bits, &ac, band, &mut eob_run, &mut block, &keep).unwrap();
        assert_eq!(eob_run, 0);
        assert_eq!(nonzero, (1 << ZIGZAG[1]) | (1 << ZIGZAG[2]), "n = {}", n);
        if n > 1 {
            assert_eq!((kept[1], kept[n]), (3, 1), "n = {}", n);
        }
        assert_eq!(bits.end_of_scan(), Err(Refusal::CutShort));
    }

    // A refinement whose run of zeros goes past the band: run 15 and size
    // 1, in a band of 4.
    let ac = Code::new(&[1], &[0xF1]).unwrap();
    let packed = bits_of("0 1");
    let mut bits = Bits::new(&packed, 0);
    let (mut kept, mut nonzero) = empty(8);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    let mut eob_run = 0;
    assert_eq!(
        entropy::ac_refine(&mut bits, &ac, Band { start: 1, end: 4, low: 0 }, &mut eob_run, &mut block, &keep),
        Err(Refusal::Damaged("a run of zeros goes past the end of its band"))
    );
    // A size other than 1 means nothing in a refinement.
    let ac = Code::new(&[1], &[0x02]).unwrap();
    let packed = bits_of("0 11");
    let mut bits = Bits::new(&packed, 0);
    let (mut kept, mut nonzero) = empty(8);
    let mut block = Block { kept: &mut kept, nonzero: &mut nonzero };
    assert_eq!(
        entropy::ac_refine(&mut bits, &ac, band, &mut eob_run, &mut block, &keep),
        Err(Refusal::Damaged("its data holds a code that means nothing"))
    );
}

// ---------- Limits ----------

#[test]
fn jpeg_limits_kept() {
    let photo = read("seq420.jpg");
    let tight = JpegLimits { dots_most: 77 * 45, side_most: 77, held_most: 0 };
    // Read as it comes: it needs nothing held.
    assert!(jpeg_picture(&photo, 77, 45, &tight).is_ok());
    let narrow = JpegLimits { side_most: 76, ..tight };
    assert_eq!(jpeg_picture(&photo, 77, 45, &narrow), Err(Refusal::TooLarge { width: 77, height: 45 }));
    let fewer = JpegLimits { dots_most: 77 * 45 - 1, ..tight };
    assert_eq!(jpeg_picture(&photo, 77, 45, &fewer), Err(Refusal::TooLarge { width: 77, height: 45 }));

    // A progressive one keeps its blocks: 10 by 6 of the brightness and 5 by
    // 3 of each colour, 90 in all, 8 + 2 x 8 x 8 bytes each at its whole
    // size, 8 + 2 at an eighth.
    let progressive = read("prog420.jpg");
    let held = |bytes: u64| JpegLimits { held_most: bytes, ..ROOMY };
    assert!(jpeg_picture(&progressive, 77, 45, &held(90 * 136)).is_ok());
    assert_eq!(jpeg_picture(&progressive, 77, 45, &held(90 * 136 - 1)), Err(Refusal::TooLarge { width: 77, height: 45 }));
    assert!(jpeg_picture(&progressive, 10, 10, &held(90 * 10)).is_ok());
    assert_eq!(jpeg_picture(&progressive, 10, 10, &held(90 * 10 - 1)), Err(Refusal::TooLarge { width: 77, height: 45 }));

    // No room; a room larger than the photo is no harm.
    assert_eq!(jpeg_picture(&photo, 0, 5, &ROOMY), Err(Refusal::NoRoom));
    assert_eq!(jpeg_picture(&photo, 5, 0, &ROOMY), Err(Refusal::NoRoom));
    assert_eq!(jpeg_picture(&photo, u32::MAX, u32::MAX, &tight).map(|picture| (picture.width, picture.height)), Ok((77, 45)));
}

#[test]
fn size_read_at() {
    // A 77 by 45 photo in a room of 10 by 10 is shown 10 by 6: an eighth,
    // 10 by 6 (ceil(77 / 8), ceil(45 / 8)), is large enough. In 11 by 11 it
    // is shown 11 by 6, and is read at a quarter, 20 by 12, then shrunk.
    assert_eq!(fitted_size(77, 45, 10, 10), (10, 6));
    assert_eq!(fitted_size(77, 45, 11, 11), (11, 6));
    let photo = read("seq420.jpg");
    let whole = show(&photo).unwrap();
    for (room, shown) in [((10, 10), (10, 6)), ((11, 11), (11, 6)), ((77, 45), (77, 45))] {
        let picture = jpeg_picture(&photo, room.0, room.1, &ROOMY).unwrap();
        assert_eq!((picture.width, picture.height), shown);
    }
    assert_eq!((whole.width, whole.height), (77, 45));
}

#[test]
fn jpeg_reasons_in_words() {
    assert_eq!(Refusal::NotJpeg.because(), "it does not begin as a JPEG photo does");
    assert_eq!(Refusal::KindNotRead("it is lossless").because(), "it is a kind of JPEG I do not read: it is lossless");
}

// ---------- Photos made by other programs ----------

/// JPEG photos made by other programs, read by the crate and by Windows' own
/// reader (WIC, colour profiles left out): the list is made by
/// test_pictures.py --cross-check, with WIC's dots at the whole size (four
/// bytes a dot: blue, green, red, alpha) beside each photo. Two sound
/// readers differ a little (A.3.3), and more where colour was subsampled,
/// since WIC smooths it where this crate takes the nearest sample. So the
/// photos are compared by what smoothing does not move:
///
/// - at the whole size, the averages of squares of 16 by 16 dots, at most 4
///   apart (3.38 was the most seen); and the brightness of each dot that
///   neither reader clipped to 0 or 255, at most 3 apart (2 was the most
///   seen), in a grey photo, or a YCbCr one whose Y is not subsampled;
/// - at a frame's size, the averages of squares, WIC's dots brought to the
///   same grid and shrunk the same way: at most 10 apart (7.62 was the most
///   seen, in a strongly coloured part of a photo read at a quarter, where
///   WIC clips more dots to 0 than the crate does, which raises its
///   averages).
///
/// Run only when asked.
#[test]
#[ignore]
fn jpeg_cross_check() {
    let folder = PathBuf::from(env::var("PICTURES_JPEG_CROSS_CHECK").expect("PICTURES_JPEG_CROSS_CHECK names the folder"));
    let list = fs::read_to_string(folder.join("list.txt")).unwrap();
    let (mut compared, mut worst_whole, mut worst_shown, mut worst_luma, mut worst_over) = (0, 0.0f64, 0.0f64, 0u32, 0.0f64);
    let mut refused: Vec<String> = Vec::new();
    for line in list.lines() {
        let words: Vec<&str> = line.split('\t').collect();
        let (path, width, height) = (words[0], words[1].parse::<u32>().unwrap(), words[2].parse::<u32>().unwrap());
        let file = fs::read(path).unwrap();
        let bgra = fs::read(folder.join(words[3])).unwrap();
        let wic: Vec<u8> = bgra.as_chunks::<4>().0.iter().flat_map(|dot| [dot[2], dot[1], dot[0], 255]).collect();
        // WIC reads it, so it may be turned down only as a kind this crate
        // does not read (CMYK, say), or as no JPEG at all (a GIF named .jpg),
        // never as damaged or cut short.
        let whole = match show(&file) {
            Ok(picture) => picture,
            Err(refusal @ (Refusal::KindNotRead(_) | Refusal::NotJpeg)) => {
                refused.push(format!("{}: {}", path, refusal.because()));
                continue;
            }
            Err(refusal) => panic!("{}: WIC reads it, but it is turned down because {}", path, refusal.because()),
        };
        assert_eq!((whole.width, whole.height), (width, height), "{}", path);
        let off_whole = squares_off(&whole.dots, &wic, width as usize, height as usize);
        let (luma_most, luma_over) = luma_off(&whole.dots, &wic);
        let luma_checked = brightness_whole(&file);

        // At a frame's size, as the kernel shows it on a screen of 1280 by
        // 800. The crate reads it at n dots a block side; WIC's dots are
        // brought to the same grid by averaging each 8 / n by 8 / n of them,
        // and both are shrunk the same way.
        let shown = jpeg_picture(&file, 554, 400, &ROOMY).unwrap();
        let (shown_width, shown_height) = fitted_size(width, height, 554, 400);
        let side = |size: u32, n: u32| (size * n).div_ceil(8);
        let n = [1, 2, 4, 8].into_iter().find(|n| side(width, *n) >= shown_width && side(height, *n) >= shown_height).unwrap();
        let (step, read_width, read_height) = ((8 / n) as usize, side(width, n), side(height, n));
        let mut shrink = Shrink::new(read_width, read_height, shown_width, shown_height);
        let mut row = Vec::new();
        for read_y in 0..read_height as usize {
            row.clear();
            for read_x in 0..read_width as usize {
                let mut sums = [0u64; 3];
                let mut count = 0u64;
                for y in read_y * step..((read_y + 1) * step).min(height as usize) {
                    for x in read_x * step..((read_x + 1) * step).min(width as usize) {
                        let at = (y * width as usize + x) * 4;
                        for (channel, sum) in sums.iter_mut().enumerate() {
                            *sum += u64::from(wic[at + channel]);
                        }
                        count += 1;
                    }
                }
                row.extend(sums.iter().map(|sum| ((sum + count / 2) / count) as u8));
                row.push(255);
            }
            shrink.take_row(read_y as u32, &row);
        }
        let wic_shown = shrink.finish();
        assert_eq!((shown.width, shown.height), (wic_shown.width, wic_shown.height), "{}", path);
        let off_shown = squares_off(&shown.dots, &wic_shown.dots, shown.width as usize, shown.height as usize);
        println!(
            "{}\t{}x{}\twhole {:.2}\tshown {:.2}\tbrightness most {}{}\tover 4 {:.4}%",
            path,
            width,
            height,
            off_whole,
            off_shown,
            luma_most,
            if luma_checked { "" } else { " (not checked)" },
            luma_over
        );
        assert!(off_whole <= 4.0, "{}: at its whole size, a square's average is {:.2} off", path, off_whole);
        assert!(off_shown <= 10.0, "{}: as shown, a square's average is {:.2} off", path, off_shown);
        assert!(!luma_checked || luma_most <= 3, "{}: a dot's brightness is {} off", path, luma_most);
        (worst_whole, worst_shown) = (worst_whole.max(off_whole), worst_shown.max(off_shown));
        if luma_checked {
            worst_luma = worst_luma.max(luma_most);
        }
        worst_over = worst_over.max(luma_over);
        compared += 1;
    }
    for line in &refused {
        println!("turned down: {}", line);
    }
    println!(
        "cross-checked {} photos, {} turned down; worst: whole {:.2}, shown {:.2}, brightness most {}, over 4 {:.4}%",
        compared,
        refused.len(),
        worst_whole,
        worst_shown,
        worst_luma,
        worst_over
    );
}

/// Whether a photo's brightness is not subsampled: a grey photo, or a YCbCr
/// one whose Y has the largest sampling factors. Smoothing does not move its
/// brightness then. Its colours are taken as the crate takes them: YCbCr
/// with JFIF's note; otherwise as Adobe's says; otherwise red, green and
/// blue when named R, G and B. Read from the segments before the frame.
fn brightness_whole(file: &[u8]) -> bool {
    let (mut at, mut jfif, mut adobe) = (2, false, None);
    while at + 4 <= file.len() && file[at] == 0xFF {
        let code = file[at + 1];
        if code == 0xFF {
            at += 1;
            continue;
        }
        let length = usize::from(u16::from_be_bytes([file[at + 2], file[at + 3]]));
        let body = &file[at + 4..(at + 2 + length).min(file.len())];
        match code {
            0xE0 if body.starts_with(b"JFIF\0") => jfif = true,
            0xEE if body.starts_with(b"Adobe") && body.len() >= 12 => adobe = Some(body[11]),
            0xC0..=0xC2 => {
                let count = usize::from(body[5]);
                let ids: Vec<u8> = (0..count).map(|c| body[6 + 3 * c]).collect();
                let factors: Vec<u8> = (0..count).map(|c| body[7 + 3 * c]).collect();
                let rgb = !jfif && (adobe == Some(0) || (adobe.is_none() && ids == [82, 71, 66]));
                let (h, v) = (factors[0] >> 4, factors[0] & 15);
                return count == 1 || (!rgb && factors.iter().all(|f| f >> 4 <= h && f & 15 <= v));
            }
            _ => {}
        }
        at += 2 + length;
    }
    false
}

/// How far the brightness of two pictures' dots differs: (299 red + 587
/// green + 114 blue) / 1000, which gives back JFIF's Y whatever the colour,
/// so that smoothing subsampled colour does not move it, unless a colour
/// was clipped to 0 or 255 on the way. The most, among the dots neither of
/// whose colours is clipped; and the share of all dots more than 4 off, in
/// hundredths.
fn luma_off(ours: &[u8], theirs: &[u8]) -> (u32, f64) {
    let luma = |dot: &[u8]| (299 * u32::from(dot[0]) + 587 * u32::from(dot[1]) + 114 * u32::from(dot[2]) + 500) / 1000;
    let clipped = |dot: &[u8]| dot[..3].iter().any(|colour| *colour == 0 || *colour == 255);
    let (mut most, mut over, mut count) = (0u32, 0u64, 0u64);
    for (a, b) in ours.chunks(4).zip(theirs.chunks(4)) {
        let off = luma(a).abs_diff(luma(b));
        if !clipped(a) && !clipped(b) {
            most = most.max(off);
        }
        over += u64::from(off > 4);
        count += 1;
    }
    (most, over as f64 * 100.0 / count.max(1) as f64)
}

/// The most that the average of a colour over a square of 16 by 16 dots
/// differs between two pictures of the same size.
fn squares_off(ours: &[u8], theirs: &[u8], width: usize, height: usize) -> f64 {
    let mut most = 0.0f64;
    for top in (0..height).step_by(16) {
        for left in (0..width).step_by(16) {
            let mut sums = [0i64; 3];
            let mut count = 0i64;
            for y in top..(top + 16).min(height) {
                for x in left..(left + 16).min(width) {
                    let at = (y * width + x) * 4;
                    for (channel, sum) in sums.iter_mut().enumerate() {
                        *sum += i64::from(ours[at + channel]) - i64::from(theirs[at + channel]);
                    }
                    count += 1;
                }
            }
            for sum in sums {
                most = most.max((sum as f64 / count as f64).abs());
            }
        }
    }
    most
}
