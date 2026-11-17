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

// The same for ports that work with 4 bytes at a time.
pub fn port_write_32(port: u16, value: u32) {
    unsafe { asm!("out dx, eax", in("dx") port, in("eax") value) };
}

pub fn port_read_32(port: u16) -> u32 {
    let value: u32;
    unsafe { asm!("in eax, dx", in("dx") port, out("eax") value) };
    value
}

// Some devices keep their controls in memory instead of behind ports. These
// read and write such a control, 1, 2 or 4 bytes wide. "Volatile" tells Rust
// that this memory belongs to a device: every read and every write must
// really happen, once, and in the order written.
pub fn device_read_8(address: u64) -> u8 {
    unsafe { core::ptr::read_volatile(address as *const u8) }
}

pub fn device_read_16(address: u64) -> u16 {
    unsafe { core::ptr::read_volatile(address as *const u16) }
}

pub fn device_read_32(address: u64) -> u32 {
    unsafe { core::ptr::read_volatile(address as *const u32) }
}

pub fn device_write_8(address: u64, value: u8) {
    unsafe { core::ptr::write_volatile(address as *mut u8, value) };
}

pub fn device_write_16(address: u64, value: u16) {
    unsafe { core::ptr::write_volatile(address as *mut u16, value) };
}

pub fn device_write_32(address: u64, value: u32) {
    unsafe { core::ptr::write_volatile(address as *mut u32, value) };
}

// The processor counts its own steps from the moment it is switched on. The
// count is different at every start of the kernel.
pub fn time_stamp() -> u64 {
    let (low_half, high_half): (u32, u32);
    unsafe { asm!("rdtsc", out("eax") low_half, out("edx") high_half) };
    (high_half as u64) << 32 | low_half as u64
}

// Switches device signals off and says whether they were on. While they are
// off nothing can interrupt the running code, so no other task gets a turn.
pub fn signals_off() -> bool {
    let flags: u64;
    unsafe { asm!("pushfq", "pop {}", "cli", out(reg) flags) };
    flags & 0x200 != 0
}

// Switches device signals back on, but only if they were on before.
pub fn signals_back(were_on: bool) {
    if were_on {
        unsafe { asm!("sti") };
    }
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
