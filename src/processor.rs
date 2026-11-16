//! The smallest pieces for dealing with the processor directly: its ports,
//! stopping it, and the form in which it is told where a table is.

use core::arch::asm;

// Devices are reached through numbered ports. These two send one byte to a
// port and read one byte from it.
pub fn port_write(port: u16, value: u8) {
    unsafe { asm!("out dx, al", in("dx") port, in("al") value) };
}

pub fn port_read(port: u16) -> u8 {
    let value: u8;
    unsafe { asm!("in al, dx", in("dx") port, out("al") value) };
    value
}

// Stops the processor for good.
pub fn stop() -> ! {
    loop {
        unsafe { asm!("cli", "hlt") };
    }
}

// How the processor is told where a table is: its last byte and its address.
#[repr(C, packed)]
pub struct TablePointer {
    pub last_byte: u16,
    pub address: u64,
}
