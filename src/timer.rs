//! The timer (PIT) and the count of its ticks, which is the kernel's only
//! clock. Notes: `docs/interrupts.md`.

use core::sync::atomic::{AtomicU64, Ordering};

use crate::controller::signal_done;
use crate::processor::port_write;
use crate::tasks::next_task;

// The timer chip (PIT) counts down from a number of your choice, 1,193,182
// steps per second, and sends a signal each time it reaches zero. Counting
// down from 11,931 gives 100 signals ("ticks") per second.
const TIMER_STEPS_PER_SECOND: u64 = 1_193_182;
pub const TICKS_PER_SECOND: u64 = 100;

// How many ticks have arrived since the kernel started. It is an "atomic"
// number: one that both the main code and a signal handler may use, because
// every read or change of it happens in a single step that cannot be
// interrupted halfway.
pub static TICKS: AtomicU64 = AtomicU64::new(0);

pub fn timer_setup() {
    let count = (TIMER_STEPS_PER_SECOND / TICKS_PER_SECOND) as u16;
    port_write(0x43, 0x36); // "Counter 0, start again after each zero. The count follows."
    port_write(0x40, count as u8); // The count's low half,
    port_write(0x40, (count >> 8) as u8); // and its high half.
}

// Runs on every tick: counts it, then gives the next task its turn. It is
// given the place where the interrupted task's registers were saved, and
// answers with the place to put the registers back from.
pub extern "sysv64" fn on_timer(saved_registers: u64) -> u64 {
    TICKS.fetch_add(1, Ordering::Relaxed);
    signal_done();
    next_task(saved_registers)
}
