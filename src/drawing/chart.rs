//! Horizontal bars from an open table. Calculations use integers so the
//! kernel can draw exact signed decimal values without floating point.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use super::{Cuts, FRAME, PADDING, Place, ROW_HEIGHT, SIGN, TEXT_SIZE, clean, paint_frame, readable, table_line};
use crate::letters::{LETTER_HEIGHT, LETTER_WIDTH};
use crate::look::look;
use crate::screen::{screen_rectangle, screen_text};

const FRACTION_DIGITS: usize = 6;
const SCALE: u64 = 1_000_000;
const MIN_WIDTH: u32 = 240;
const MIN_PLOT: u32 = 64;
const COLUMN_GAP: u32 = 12;
const BAR_HEIGHT: u32 = 16;

struct Bar {
    label: String,
    value: i64,
    number: String,
}

pub(super) struct Chart {
    title: String,
    bars: Vec<Bar>,
}

pub(super) fn fits(place: &Place) -> bool {
    place.inside_width() >= MIN_WIDTH
}

pub(super) fn read(
    text: &str,
    labels: usize,
    values: usize,
    place: &Place,
) -> Result<(Chart, usize, usize), String> {
    let lines = text.lines().map(table_line);
    let headings = lines.clone().take_while(|(word, _)| *word != "row")
        .filter_map(|(word, text)| (word == "head").then_some(text)).last().unwrap_or("");
    let label_heading = cell(headings, labels);
    let value_heading = cell(headings, values);
    let title = format!("{} by {}",
        if value_heading.is_empty() { "Value" } else { value_heading },
        if label_heading.is_empty() { "Label" } else { label_heading });

    let mut bars = Vec::new();
    let mut total = 0;
    for (_, row) in lines.filter(|(word, _)| *word == "row") {
        total += 1;
        let value = decimal(cell(row, values))
            .ok_or_else(|| format!("row {} needs a plain number in column {} for the bar chart.", total, values + 1))?;
        if bars.len() < place.rows() {
            let label = cell(row, labels);
            let label = if label.is_empty() { format!("Row {}", total) } else { String::from(label) };
            bars.push(Bar { label, value, number: number_label(value) });
        }
    }
    let shown = bars.len();
    if shown == 0 {
        return Err(String::from("the open table has no data rows to chart."));
    }
    Ok((Chart { title, bars }, shown, total))
}

fn cell(row: &str, column: usize) -> &str {
    row.split('|').nth(column).unwrap_or("").trim()
}

// Read plain decimals with up to six places. The checked conversion
// rejects values outside the same range for every table and look.
fn decimal(text: &str) -> Option<i64> {
    let negative = text.starts_with('-');
    let text = text.strip_prefix(['-', '+']).unwrap_or(text);
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    if (whole.is_empty() && fraction.is_empty()) || fraction.len() > FRACTION_DIGITS ||
        !whole.bytes().chain(fraction.bytes()).all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let whole = if whole.is_empty() { 0 } else { whole.parse::<i128>().ok()? };
    let fraction_value = if fraction.is_empty() { 0 } else { fraction.parse::<i128>().ok()? };
    let padded = fraction_value * 10i128.pow((FRACTION_DIGITS - fraction.len()) as u32);
    let unsigned = whole.checked_mul(SCALE as i128)?.checked_add(padded)?;
    i64::try_from(if negative { -unsigned } else { unsigned }).ok()
}

fn number_label(value: i64) -> String {
    let magnitude = value.unsigned_abs();
    let prefix = if value < 0 { "-" } else { "" };
    let whole = magnitude / SCALE;
    let fraction = magnitude % SCALE;
    if fraction == 0 {
        return format!("{}{}", prefix, whole);
    }
    let text = format!("{:06}", fraction);
    format!("{}{}.{}", prefix, whole, text.trim_end_matches('0'))
}

impl Chart {
    pub(super) fn paint(&self, place: &Place) {
        let look = look();
        paint_frame(place);
        let ink = look.panel_text;
        let bar_ink = readable(look.chat_kernel, look.panel_inside);
        let width = place.inside_width();
        let left = place.left + FRAME + PADDING;
        let top = place.top + FRAME + PADDING;
        let text_down = (ROW_HEIGHT - TEXT_SIZE * LETTER_HEIGHT) / 2;
        let title = clean(&self.title, width / SIGN, &mut Cuts::default());
        screen_text(left, top + text_down, &title, TEXT_SIZE, ink);

        let digits = self.bars.iter().map(|bar| bar.number.len() as u32).max().unwrap_or(0);
        let value_size = if digits * SIGN <= width / 3 { TEXT_SIZE } else { 1 };
        let value_sign = value_size * (LETTER_WIDTH + 1);
        let value_width = digits * value_sign;
        let labels = self.bars.iter().map(|bar| bar.label.trim().len() as u32).max().unwrap_or(0);
        let label_signs = labels.min((width - value_width - MIN_PLOT - 2 * COLUMN_GAP) / SIGN).min(18);
        let plot_left = left + label_signs * SIGN + COLUMN_GAP;
        let plot_right = left + width - value_width - COLUMN_GAP;
        // Reserve one dot for the line marking zero.
        let span = plot_right - plot_left - 1;
        let (low, high) = self.bars.iter().fold((0i64, 0i64), |(low, high), bar| (low.min(bar.value), high.max(bar.value)));
        let split = if low == 0 {
            0
        } else if high == 0 {
            span
        } else {
            let ratio = (span as i128 * -(low as i128)) / (high as i128 - low as i128);
            (ratio as u32).clamp(1, span - 1)
        };
        let axis = plot_left + split;
        let plot_top = top + ROW_HEIGHT;
        screen_rectangle(axis, plot_top, 1, self.bars.len() as u32 * ROW_HEIGHT, ink);

        for (row, bar) in self.bars.iter().enumerate() {
            let y = plot_top + row as u32 * ROW_HEIGHT;
            let bar_top = y + (ROW_HEIGHT - BAR_HEIGHT) / 2;
            if bar.value > 0 {
                let length = scaled_length(bar.value as i128, high as i128, span - split);
                screen_rectangle(axis + 1, bar_top, length, BAR_HEIGHT, bar_ink);
            } else if bar.value < 0 {
                let length = scaled_length(-(bar.value as i128), -(low as i128), split);
                screen_rectangle(axis - length, bar_top, length, BAR_HEIGHT, bar_ink);
            }
            let label = clean(&bar.label, label_signs, &mut Cuts::default());
            screen_text(left, y + text_down, &label, TEXT_SIZE, ink);
            let value_left = left + width - bar.number.len() as u32 * value_sign;
            let value_top = y + (ROW_HEIGHT - value_size * LETTER_HEIGHT) / 2;
            screen_text(value_left, value_top, &bar.number, value_size, ink);
        }
        let footer = place.top + place.height - FRAME - PADDING - ROW_HEIGHT + text_down;
        screen_text(left, footer, "Tab returns to table", TEXT_SIZE, ink);
    }
}

fn scaled_length(value: i128, extreme: i128, room: u32) -> u32 {
    ((value * room as i128 / extreme) as u32).max(1)
}
