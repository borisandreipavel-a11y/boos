//! Shrinking: a picture made small enough to fit a room, keeping its shape.
//! Each dot of the small picture is the average of the dots of the large one
//! that fall on it, so a picture of fine detail looks smooth, not torn. A
//! picture that fits already is not changed, and none is made larger.
//! Notes: `docs/pictures.md`.

use alloc::vec;
use alloc::vec::Vec;

use crate::Picture;

/// The size a picture of `width` by `height` dots is shown at in a room of
/// `room_width` by `room_height`: as it is if it fits; otherwise as large as
/// fits, keeping its shape, with the side that does not fill the room
/// rounded to the nearest dot (and at least one). Neither side may be 0.
pub fn fitted_size(width: u32, height: u32, room_width: u32, room_height: u32) -> (u32, u32) {
    if width <= room_width && height <= room_height {
        return (width, height);
    }
    let (width, height) = (u64::from(width.max(1)), u64::from(height.max(1)));
    let (room_width, room_height) = (u64::from(room_width.max(1)), u64::from(room_height.max(1)));
    if width * room_height >= height * room_width {
        // Wider than the room's shape: it fills the room's width.
        let shown_height = ((height * room_width + width / 2) / width).clamp(1, room_height);
        (room_width as u32, shown_height as u32)
    } else {
        // Taller: it fills the room's height.
        let shown_width = ((width * room_height + height / 2) / height).clamp(1, room_width);
        (shown_width as u32, room_height as u32)
    }
}

/// How many numbers are summed for each dot of the shown picture: the
/// alpha, the red, green and blue each times its alpha, and the count of
/// dots summed.
const SUMS: usize = 5;

/// A picture being shrunk as its rows come, top to bottom. `from_*` is the
/// size it has, `to_*` the size it is shown at. Only the shown row that the
/// coming rows fall on is summed at a time (`sums`); a finished row goes
/// into `dots`. A picture shown at its own size is not summed at all: its
/// rows go into `dots` as they are (`as_it_is`).
pub(crate) struct Shrink {
    from_width: u32,
    from_height: u32,
    to_width: u32,
    to_height: u32,
    as_it_is: bool,
    sums: Vec<u64>,
    row: u32,
    dots: Vec<u8>,
}

impl Shrink {
    /// The memory it sets aside is bounded by the shown size, which is never
    /// larger than the picture, which the caller's limits bound.
    pub(crate) fn new(from_width: u32, from_height: u32, to_width: u32, to_height: u32) -> Shrink {
        let as_it_is = from_width == to_width && from_height == to_height;
        let sums = if as_it_is { Vec::new() } else { vec![0; to_width as usize * SUMS] };
        Shrink {
            from_width,
            from_height,
            to_width,
            to_height,
            as_it_is,
            sums,
            row: 0,
            dots: Vec::with_capacity(to_width as usize * to_height as usize * 4),
        }
    }

    /// Takes row `y` of the picture, `from_width` dots of four bytes each:
    /// red, green, blue, alpha. Rows come in order.
    pub(crate) fn take_row(&mut self, y: u32, row: &[u8]) {
        if self.as_it_is {
            let bytes = self.from_width as usize * 4;
            self.dots.extend_from_slice(row.get(..bytes).unwrap_or(row));
            self.row += 1;
            return;
        }
        // The shown row it falls on: y times to_height / from_height,
        // rounded down. Rows of the shown picture that no row fell on are
        // finished empty (with a shown size no larger, none is skipped).
        let target = (u64::from(y) * u64::from(self.to_height) / u64::from(self.from_height.max(1))) as u32;
        while self.row < target && self.row < self.to_height {
            self.finish_row();
        }

        // The shown column dot x falls on is x times to_width / from_width,
        // rounded down: counted up step by step, without a division.
        let mut column = 0usize;
        let mut over = 0u64;
        for [red, green, blue, alpha] in row.as_chunks::<4>().0.iter().take(self.from_width as usize) {
            let (red, green, blue, alpha) = (u64::from(*red), u64::from(*green), u64::from(*blue), u64::from(*alpha));
            if let Some(sums) = self.sums.get_mut(column * SUMS..column * SUMS + SUMS) {
                let added = [alpha, red * alpha, green * alpha, blue * alpha, 1];
                for (sum, more) in sums.iter_mut().zip(added) {
                    *sum += more;
                }
            }
            over += u64::from(self.to_width);
            if over >= u64::from(self.from_width) {
                over -= u64::from(self.from_width);
                column += 1;
            }
        }
    }

    /// The row being summed, made into dots. A dot's alpha is the average of
    /// the alphas that fell on it; its colour is the average of their
    /// colours, each counted as much as it covers, so that a see-through dot
    /// does not darken its neighbours. Both are rounded to the nearest.
    fn finish_row(&mut self) {
        for [alpha, red, green, blue, count] in self.sums.as_chunks::<SUMS>().0 {
            let (alpha, count) = (*alpha, *count);
            let Some(shown_alpha) = (alpha + count / 2).checked_div(count) else {
                self.dots.extend_from_slice(&[0, 0, 0, 0]);
                continue;
            };
            let colour = |sum: u64| (sum + alpha / 2).checked_div(alpha).unwrap_or(0) as u8;
            self.dots.extend_from_slice(&[colour(*red), colour(*green), colour(*blue), shown_alpha as u8]);
        }
        for sum in self.sums.iter_mut() {
            *sum = 0;
        }
        self.row += 1;
    }

    /// The shown picture, once every row has come.
    pub(crate) fn finish(mut self) -> Picture {
        if self.as_it_is {
            // Rows that never came are see-through.
            self.dots.resize(self.to_width as usize * self.to_height as usize * 4, 0);
        } else {
            while self.row < self.to_height {
                self.finish_row();
            }
        }
        Picture { width: self.to_width, height: self.to_height, dots: self.dots }
    }
}
