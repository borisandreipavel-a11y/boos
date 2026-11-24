//! Check values: the two sums that tell whether bytes are as they were
//! written. A PNG's parts each end with a CRC-32 (RFC 2083, 3.4 and its
//! appendix 15), and packed bytes end with an Adler-32 (RFC 1950, 2.2 and 9).
//! Notes: `docs/pictures.md`.

/// The CRC-32's table: for every byte, what it does to the register. Worked
/// out by the compiler, as RFC 2083's `make_crc_table` does it, with the
/// polynomial 0xedb88320 (the bits taken lowest first).
const CRC_TABLE: [u32; 256] = crc_table();

// The compiler works this out while it builds: an index out of range would
// stop the build, never the kernel, so plain indexing is allowed here.
#[allow(clippy::indexing_slicing)]
const fn crc_table() -> [u32; 256] {
    let mut table = [0u32; 256];
    let mut n = 0;
    while n < 256 {
        let mut c = n as u32;
        let mut k = 0;
        while k < 8 {
            c = if c & 1 == 1 { 0xedb8_8320 ^ (c >> 1) } else { c >> 1 };
            k += 1;
        }
        table[n] = c;
        n += 1;
    }
    table
}

/// Carries a CRC-32 on over more bytes. Begin with 0xffff_ffff, and turn
/// every bit over at the end (`!crc`), as RFC 2083's `crc` does.
pub(crate) fn crc_update(crc: u32, bytes: &[u8]) -> u32 {
    let mut c = crc;
    for byte in bytes {
        let index = ((c ^ u32::from(*byte)) & 0xff) as usize;
        c = CRC_TABLE.get(index).copied().unwrap_or(0) ^ (c >> 8);
    }
    c
}

/// The CRC-32 of some bytes, whole (for the tests).
#[cfg(test)]
pub(crate) fn crc(bytes: &[u8]) -> u32 {
    !crc_update(0xffff_ffff, bytes)
}

/// The largest prime below 65536: both sums of an Adler-32 are taken modulo
/// it (RFC 1950, 2.2).
const ADLER_BASE: u32 = 65521;

/// How many bytes may be added before the sums are reduced, so that they
/// stay inside 32 bits: 5552 is the most for which the larger sum cannot pass
/// 2^32 - 1, whatever the bytes.
const ADLER_RUN: usize = 5552;

/// An Adler-32 being worked out: s1, the sum of all the bytes, and s2, the
/// sum of all the s1 values, both modulo 65521. s1 begins at 1 and s2 at 0.
pub(crate) struct Adler {
    s1: u32,
    s2: u32,
}

impl Adler {
    pub(crate) fn new() -> Adler {
        Adler { s1: 1, s2: 0 }
    }

    pub(crate) fn add(&mut self, bytes: &[u8]) {
        for run in bytes.chunks(ADLER_RUN) {
            for byte in run {
                self.s1 += u32::from(*byte);
                self.s2 += self.s1;
            }
            self.s1 %= ADLER_BASE;
            self.s2 %= ADLER_BASE;
        }
    }

    /// The value as a stream stores it: s2 times 65536 plus s1.
    pub(crate) fn value(&self) -> u32 {
        (self.s2 << 16) | self.s1
    }
}
