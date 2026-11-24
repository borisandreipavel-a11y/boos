//! A JPEG's blocks turned into samples, at the whole size or a half, a
//! quarter or an eighth of it (the inverse transforms), and its colours
//! turned into red, green and blue. Everything here is in whole numbers, as
//! `docs/pictures.md` ("JPEG") writes it down, so that the tests' second
//! reader, written from the same page, gives the same dots.

/// K(u, x) = round(8192 x 1/2 x C(u) x cos((2x + 1) u pi / 16)), with C(0) =
/// 1 / sqrt(2) and C(u) = 1 otherwise: row u for the frequency, column x for
/// the dot. At n dots a block side the constants are K(u x 8 / n, x), the
/// same cosines.
const K: [[i64; 8]; 8] = [
    [2896, 2896, 2896, 2896, 2896, 2896, 2896, 2896],
    [4017, 3406, 2276, 799, -799, -2276, -3406, -4017],
    [3784, 1567, -1567, -3784, -3784, -1567, 1567, 3784],
    [3406, -799, -4017, -2276, 2276, 4017, 799, -3406],
    [2896, -2896, -2896, 2896, 2896, -2896, -2896, 2896],
    [2276, -4017, 799, 3406, -3406, -799, 4017, -2276],
    [1567, -3784, 3784, -1567, -1567, 3784, -3784, 1567],
    [799, -2276, 3406, -4017, 4017, -3406, 2276, -799],
];

/// Turns a block into n by n samples, n being 1, 2, 4 or 8 dots a side:
/// `kept` holds the block's first n by n coefficients, row by row, and
/// `quant` its quantization table's 64 numbers in the block's natural order,
/// which they are multiplied by first. The samples go into `out`, n rows of
/// n, each row `stride` bytes after the one before. Every sum is made in 64
/// bits: a coefficient of 16 bits times a number of 16 times a constant of
/// 13, eight times over, is far from 63 bits.
pub(crate) fn block_samples(n: usize, kept: &[i16], quant: &[u16; 64], out: &mut [u8], stride: usize) {
    let coefficient = |v: usize, u: usize| -> i64 {
        let value = kept.get(v * n + u).copied().unwrap_or(0);
        i64::from(value) * i64::from(quant.get(v * 8 + u).copied().unwrap_or(0))
    };
    if n <= 1 {
        // T.81's first coefficient is eight times the block's average.
        if let Some(sample) = out.first_mut() {
            *sample = (((coefficient(0, 0) + 4) >> 3) + 128).clamp(0, 255) as u8;
        }
        return;
    }
    let step = 8 / n;
    let constant = |frequency: usize, dot: usize| -> i64 {
        K.get(frequency * step).and_then(|row| row.get(dot)).copied().unwrap_or(0)
    };

    // Rows first: t(v, x), which keeps 2 bits more than the samples. A row
    // of zeros gives zeros, (0 + 1024) >> 11.
    let mut rows = [[0i64; 8]; 8];
    for (v, row) in rows.iter_mut().enumerate().take(n) {
        if (0..n).all(|u| coefficient(v, u) == 0) {
            continue;
        }
        for (x, done) in row.iter_mut().enumerate().take(n) {
            let sum: i64 = (0..n).map(|u| constant(u, x) * coefficient(v, u)).sum();
            *done = (sum + 1024) >> 11;
        }
    }

    // Then columns, and the level shift back (A.3.1).
    for (y, line) in out.chunks_mut(stride.max(1)).enumerate().take(n) {
        for (x, sample) in line.iter_mut().enumerate().take(n) {
            let sum: i64 =
                rows.iter().take(n).enumerate().map(|(v, row)| constant(v, y) * row.get(x).copied().unwrap_or(0)).sum();
            *sample = (((sum + 16384) >> 15) + 128).clamp(0, 255) as u8;
        }
    }
}

/// Red, green and blue from JFIF's Y, Cb and Cr: R = Y + 1.402 (Cr - 128),
/// G = Y - 0.34414 (Cb - 128) - 0.71414 (Cr - 128), B = Y + 1.772 (Cb - 128),
/// with the constants times 65536, rounded, each held to 0 to 255.
pub(crate) fn rgb_of_ycc(y: u8, cb: u8, cr: u8) -> [u8; 3] {
    let (y, cb, cr) = (i32::from(y), i32::from(cb) - 128, i32::from(cr) - 128);
    let red = y + ((91_881 * cr + 32_768) >> 16);
    let green = y + ((-22_554 * cb - 46_802 * cr + 32_768) >> 16);
    let blue = y + ((116_130 * cb + 32_768) >> 16);
    [red.clamp(0, 255) as u8, green.clamp(0, 255) as u8, blue.clamp(0, 255) as u8]
}
