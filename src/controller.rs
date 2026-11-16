//! The interrupt controller (PIC), through which every device signal passes
//! on its way to the processor. Notes: `docs/interrupts.md`.

use crate::processor::port_write;

// A device that wants attention sends a signal (an "interrupt"). The signals
// first reach the interrupt controller (PIC): a pair of chips with 8 input
// lines each, 16 lines in all. It passes the signals on to the processor one
// at a time. The timer is wired to line 0 and the keyboard to line 1.
const CONTROLLER_1_COMMAND: u16 = 0x20;
const CONTROLLER_1_SETTING: u16 = 0x21;
const CONTROLLER_2_COMMAND: u16 = 0xA0;
const CONTROLLER_2_SETTING: u16 = 0xA1;

// The 16 device lines use lines 32 to 47 of the interrupt table, right after
// the 32 failures.
pub const FIRST_DEVICE_ENTRY: usize = 32;
pub const TIMER_LINE: usize = 0;
pub const KEYBOARD_LINE: usize = 1;

// Sets up the interrupt controller from scratch, so that nothing depends on
// how the firmware left it.
pub fn controller_setup() {
    // "Start over. Three settings follow."
    port_write(CONTROLLER_1_COMMAND, 0x11);
    port_write(CONTROLLER_2_COMMAND, 0x11);
    // Setting 1: the line of the interrupt table that each chip's first line uses.
    port_write(CONTROLLER_1_SETTING, FIRST_DEVICE_ENTRY as u8);
    port_write(CONTROLLER_2_SETTING, FIRST_DEVICE_ENTRY as u8 + 8);
    // Setting 2: how the chips are wired. The second chip hangs off line 2 of the first.
    port_write(CONTROLLER_1_SETTING, 0x04);
    port_write(CONTROLLER_2_SETTING, 0x02);
    // Setting 3: work the way a PC expects.
    port_write(CONTROLLER_1_SETTING, 0x01);
    port_write(CONTROLLER_2_SETTING, 0x01);

    // Which lines to hold back: one bit per line, and a 1 means "hold back".
    // Only the timer (line 0) and the keyboard (line 1) are let through.
    port_write(CONTROLLER_1_SETTING, 0b1111_1100);
    port_write(CONTROLLER_2_SETTING, 0b1111_1111);
}

// Tells the interrupt controller that a signal has been dealt with. Until it
// hears this, it holds back the next one.
pub fn signal_done() {
    port_write(CONTROLLER_1_COMMAND, 0x20);
}
