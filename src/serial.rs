//! Printing through the serial port. It works before and after the takeover,
//! and it is the kernel's only way to say anything. Notes: `docs/startup.md`.

use core::fmt::{self, Write};

use crate::processor::{port_read, port_write};

// The PC's first serial port answers at this port number.
const COM1: u16 = 0x3F8;

// Whether a working serial port was found at startup.
static mut SERIAL_FOUND: bool = false;

// Sets the serial port's speed and letter format, then checks it is really there.
// QEMU's port works without this. A real PC's port does not.
pub fn serial_setup() {
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
    unsafe { SERIAL_FOUND = found };
}

pub fn serial_print(text: &str) {
    // Without a serial port there is nowhere to print to.
    if !unsafe { SERIAL_FOUND } {
        return;
    }
    for byte in text.bytes() {
        // Wait until the serial port is ready for the next letter.
        while port_read(COM1 + 5) & 0x20 == 0 {}
        port_write(COM1, byte);
    }
}

// Lets `write!` print text and numbers through the serial port.
pub struct Serial;

impl Write for Serial {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        serial_print(text);
        Ok(())
    }
}
