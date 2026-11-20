//! Printing through the serial port. It works before and after the takeover.
//! Everything the kernel says goes through here, and is kept for the screen
//! too (`lines.rs`), because a PC may have no serial port. Notes:
//! `docs/startup.md`.

use core::fmt::{self, Write};

use crate::lines::lines_keep;
use crate::processor::{port_read, port_write, signals_back, signals_off};

// The PC's first serial port answers at this port number.
const COM1: u16 = 0x3F8;

// Whether a working serial port was found at startup.
static mut SERIAL_FOUND: bool = false;

// Sets the serial port's speed and letter format, then checks it is really there.
// QEMU's port works without this. A real PC's port does not.
pub fn serial_setup() {
    // This runs first of all, while the firmware is still in charge, and the
    // firmware's timer still runs the firmware's own code now and then. That
    // code reads this port too: the firmware's console takes whatever comes in
    // there. If it took the test byte below, the kernel would believe it has
    // no serial port, and say nothing through it for the whole run. With
    // device signals off the timer cannot step in, so nothing but this code
    // touches the port until the check is over. The firmware does the same
    // when its own code must not be interrupted.
    let were_on = signals_off();

    port_write(COM1 + 1, 0x00); // The port must not send signals of its own.
    port_write(COM1 + 3, 0x80); // Unlock the speed setting.
    port_write(COM1, 0x01); // Speed: 115200 bits per second (low half of the setting),
    port_write(COM1 + 1, 0x00); // (high half).
    port_write(COM1 + 3, 0x03); // Lock it again. A letter is 8 bits, 1 stop bit, no check bit.
    port_write(COM1 + 2, 0xC7); // Switch on the port's small queues and empty them.

    // Test: in loop-back mode, a byte sent out comes straight back in.
    port_write(COM1 + 4, 0x10);
    port_write(COM1, 0xA5);
    let mut tries = 0;
    while port_read(COM1 + 5) & 0x01 == 0 && tries < 100_000 {
        tries += 1;
    }
    let found = port_read(COM1) == 0xA5;

    // Back to normal mode, telling the other side that this one is ready.
    port_write(COM1 + 4, 0x03);
    signals_back(were_on);
    unsafe { SERIAL_FOUND = found };
}

pub fn serial_print(text: &str) {
    // Keep the text in one piece: with device signals off, the timer cannot
    // switch to another task that prints in the middle of it.
    let were_on = signals_off();
    // The lines are kept for the screen whether or not there is a serial
    // port.
    lines_keep(text);
    // Without a serial port there is nowhere else to print to.
    if unsafe { SERIAL_FOUND } {
        for byte in text.bytes() {
            // Wait until the serial port is ready for the next letter.
            while port_read(COM1 + 5) & 0x20 == 0 {}
            port_write(COM1, byte);
        }
    }
    signals_back(were_on);
}

// Lets `write!` print text and numbers through the serial port.
pub struct Serial;

impl Write for Serial {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        serial_print(text);
        Ok(())
    }
}
