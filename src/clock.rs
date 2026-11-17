//! The clock chip: the part of a PC that keeps the date and the time, also
//! while the machine is switched off. Notes: `docs/random-and-date.md`.

use crate::processor::{port_read, port_write, signals_back, signals_off};

// The clock chip (RTC) keeps a row of numbered values. One of them is read in
// two steps: write its number to one port, then read the value at another.
const CLOCK_WHICH: u16 = 0x70;
const CLOCK_VALUE: u16 = 0x71;

// The numbers of the values this kernel reads.
const SECOND: u8 = 0x00;
const MINUTE: u8 = 0x02;
const HOUR: u8 = 0x04;
const DAY: u8 = 0x07;
const MONTH: u8 = 0x08;
const YEAR: u8 = 0x09; // Only the last two digits of the year.
const CENTURY: u8 = 0x32; // The first two. Not every chip keeps them.
const BUSY: u8 = 0x0A; // Bit 7 is set while the chip moves its values on.
const FORM: u8 = 0x0B; // How the chip writes its values; see `date_from`.

// How many times to look at a busy chip before giving up. The chip is busy
// for about two thousandths of a second, once a second.
const BUSY_LOOKS: u32 = 100_000;

// How many times to read the chip again when two readings in a row differ.
const READINGS: u32 = 10;

// A date and a time of day.
pub struct Date {
    pub year: u16,
    pub month: u8,
    pub day: u8,
    pub hour: u8,
    pub minute: u8,
    pub second: u8,
}

// What the chip holds, exactly as it gave it.
#[derive(Clone, Copy, PartialEq)]
struct Reading {
    second: u8,
    minute: u8,
    hour: u8,
    day: u8,
    month: u8,
    year: u8,
    century: u8,
    form: u8,
}

// Reads the date and the time from the clock chip. Answers with nothing if
// the chip does not answer or what it says cannot be a date.
pub fn clock_read() -> Option<Date> {
    // The `?` means: if there is no reading, answer "nothing" right away.
    date_from(chip_read()?)
}

// Reads one of the chip's values.
fn chip_value(number: u8) -> u8 {
    // The two steps belong together: no other task may ask in between.
    let were_on = signals_off();
    port_write(CLOCK_WHICH, number);
    let value = port_read(CLOCK_VALUE);
    signals_back(were_on);
    value
}

// Reads all the values once, at a moment when the chip is not busy.
fn chip_read_once() -> Option<Reading> {
    let mut looks = 0;
    while chip_value(BUSY) & 0x80 != 0 {
        looks += 1;
        if looks == BUSY_LOOKS {
            return None;
        }
    }
    Some(Reading {
        second: chip_value(SECOND),
        minute: chip_value(MINUTE),
        hour: chip_value(HOUR),
        day: chip_value(DAY),
        month: chip_value(MONTH),
        year: chip_value(YEAR),
        century: chip_value(CENTURY),
        form: chip_value(FORM),
    })
}

// Once a second the chip moves its values on, and a reading taken across that
// moment can mix old values with new ones: 10:59:59 and 11:00:00 could come
// out as 10:00:00. So the chip is read until two readings in a row agree.
fn chip_read() -> Option<Reading> {
    let mut before = chip_read_once()?;
    for _ in 0..READINGS {
        let now = chip_read_once()?;
        if now == before {
            return Some(now);
        }
        before = now;
    }
    None
}

// Turns what the chip holds into a date. Chips write their values in one of
// two ways, and count the hours in one of two ways. The `form` value says
// which: bit 2 for the writing, bit 1 for the hours.
fn date_from(reading: Reading) -> Option<Date> {
    // Bit 2 set: every value is a plain number. Not set: every value is two
    // decimal digits, one in each half of the byte, so 0x26 means 26 (BCD).
    let plain = reading.form & 0x04 != 0;
    // Bit 1 set: the hours run from 0 to 23. Not set: they run from 1 to 12,
    // and bit 7 of the hour marks the afternoon.
    let whole_day = reading.form & 0x02 != 0;

    let hour = if whole_day {
        number(reading.hour, plain)?
    } else {
        let afternoon = reading.hour & 0x80 != 0;
        let hour_of_half = number(reading.hour & 0x7F, plain)?;
        if hour_of_half < 1 || hour_of_half > 12 {
            return None;
        }
        // 12 at night is hour 0 of the day, and 12 at noon is hour 12.
        hour_of_half % 12 + if afternoon { 12 } else { 0 }
    };

    // A value in that place that is not 19, 20 or 21 is not a century. Then
    // the year is taken to be in the 2000s.
    let century = match number(reading.century, plain) {
        Some(century) if century >= 19 && century <= 21 => century as u16,
        _ => 20,
    };
    let year_of_century = number(reading.year, plain)?;

    let date = Date {
        year: century * 100 + year_of_century as u16,
        month: number(reading.month, plain)?,
        day: number(reading.day, plain)?,
        hour,
        minute: number(reading.minute, plain)?,
        second: number(reading.second, plain)?,
    };

    // Anything outside these ranges cannot be a date.
    let possible = year_of_century <= 99
        && date.month >= 1
        && date.month <= 12
        && date.day >= 1
        && date.day <= 31
        && date.hour <= 23
        && date.minute <= 59
        && date.second <= 59;
    if possible { Some(date) } else { None }
}

// Turns one of the chip's values into a number. Written as digits, each half
// of the byte has to be a digit from 0 to 9.
fn number(value: u8, plain: bool) -> Option<u8> {
    if plain {
        return Some(value);
    }
    let (tens, ones) = (value >> 4, value & 0x0F);
    if tens > 9 || ones > 9 {
        return None;
    }
    Some(tens * 10 + ones)
}
