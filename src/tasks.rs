//! Tasks: several pieces of work that take turns on the processor. The timer
//! makes the switch. Notes: `docs/tasks.md`.

use core::arch::{asm, naked_asm};
use core::sync::atomic::{AtomicU64, Ordering};

use crate::heap::{heap_give_back, heap_take};
use crate::processor::{signals_back, signals_off};
use crate::segments::{CODE_SEGMENT, DATA_SEGMENT};
use crate::timer::{TICKS, on_timer};

// A task is a piece of work with a stack of its own. Only one task runs at a
// time. On every timer signal the running task is set aside and the next one
// carries on, so they all seem to run at once.

// What lies on a task's stack while the task is set aside: all of its
// registers, then what the processor itself wrote down when the timer
// interrupted it. The registers are in the order `switch_entry!` takes them off
// the stack, so the two must be changed together.
#[repr(C)]
struct SavedRegisters {
    r15: u64,
    r14: u64,
    r13: u64,
    r12: u64,
    r11: u64,
    r10: u64,
    r9: u64,
    r8: u64,
    rbp: u64,
    rdi: u64,
    rsi: u64,
    rdx: u64,
    rcx: u64,
    rbx: u64,
    rax: u64,
    // Written down by the processor:
    address: u64, // Where the task's code carries on.
    code_segment: u64,
    flags: u64,
    stack: u64, // Where the task's stack had got to.
    stack_segment: u64,
}

// The machine instructions that switch tasks. They save every register on the
// stack of the task that was running, let a handler say which stack to carry
// on with, and put every register back from that stack. If it is another
// task's stack, returning lands in that other task, exactly where it was set
// aside. The same instructions are written out once for each event that can
// switch tasks; only the handler differs.
macro_rules! switch_entry {
    ($name:ident, $handler:ident) => {
        #[unsafe(naked)]
        pub extern "sysv64" fn $name() {
            naked_asm!(
                "push rax",
                "push rbx",
                "push rcx",
                "push rdx",
                "push rsi",
                "push rdi",
                "push rbp",
                "push r8",
                "push r9",
                "push r10",
                "push r11",
                "push r12",
                "push r13",
                "push r14",
                "push r15",
                "cld", // Rust code expects text to be copied front to back.
                "mov rdi, rsp", // Tell the handler where the registers were saved,
                "call {handler}",
                "mov rsp, rax", // and carry on with the stack it answers.
                "pop r15",
                "pop r14",
                "pop r13",
                "pop r12",
                "pop r11",
                "pop r10",
                "pop r9",
                "pop r8",
                "pop rbp",
                "pop rdi",
                "pop rsi",
                "pop rdx",
                "pop rcx",
                "pop rbx",
                "pop rax",
                "iretq", // Return to where the task was set aside.
                handler = sym $handler,
            )
        }
    };
}

// The processor jumps here on every timer signal,
switch_entry!(timer_entry, on_timer);

// and here when a task itself asks to be set aside, with the instruction
// `int` and this line of the interrupt table. It is the first line after the
// 16 device lines.
switch_entry!(wait_entry, on_wait);
pub const WAIT_ENTRY: usize = 48;

// The list of tasks. Each place in it is empty, holds a task that is ready to
// run, or holds one that has finished.
const MAX_TASKS: usize = 8;
const EMPTY: u8 = 0;
const READY: u8 = 1;
const FINISHED: u8 = 2;

#[derive(Clone, Copy)]
struct Task {
    state: u8,
    work: Option<fn()>,   // The function that is the task's work.
    stack: u64,           // Where the memory for its stack starts.
    saved_registers: u64, // Where its registers lie while it is set aside.
    wake_tick: u64,       // The tick count it is waiting for. 0 means it is not waiting.
}

static mut TASKS: [Task; MAX_TASKS] = [Task {
    state: EMPTY,
    work: None,
    stack: 0,
    saved_registers: 0,
    wake_tick: 0,
}; MAX_TASKS];

// Which task is running. Task 0 is the code the kernel started with. It keeps
// the stack it always had, and its place in the list only remembers where its
// registers lie.
static mut CURRENT_TASK: usize = 0;

// Each task's stack is 64 KB.
const TASK_STACK_SIZE: usize = 64 * 1024;

// Sets the running task aside and picks the next one: each ready task in
// turn, passing over those that are still waiting. It is given the place
// where the running task's registers were saved, and answers with the place
// where the next task's registers lie. It runs inside a handler, so it must
// not print or use the heap.
fn switch_task(saved_registers: u64) -> u64 {
    let now = TICKS.load(Ordering::Relaxed);
    unsafe {
        TASKS[CURRENT_TASK].saved_registers = saved_registers;
        loop {
            CURRENT_TASK = (CURRENT_TASK + 1) % MAX_TASKS;
            // Task 0 never ends and never waits, so it is always ready. It is
            // the task that runs when no other has anything to do.
            if CURRENT_TASK == 0 {
                break;
            }
            if TASKS[CURRENT_TASK].state == READY && TASKS[CURRENT_TASK].wake_tick <= now {
                break;
            }
        }
        TASKS[CURRENT_TASK].saved_registers
    }
}

// How many ticks found the processor resting. Task 0 passes its turn on
// whenever another task could run, so a tick that arrives while task 0 runs
// found nothing else to do, and is counted as rest.
pub static RESTED_TICKS: AtomicU64 = AtomicU64::new(0);

// Called by the timer's handler on every tick.
pub fn next_task(saved_registers: u64) -> u64 {
    if unsafe { CURRENT_TASK } == 0 {
        RESTED_TICKS.fetch_add(1, Ordering::Relaxed);
    }
    switch_task(saved_registers)
}

// The handler for a task that asked to be set aside. Unlike the timer's, it
// counts no tick and has no signal to acknowledge: no device signalled.
extern "sysv64" fn on_wait(saved_registers: u64) -> u64 {
    switch_task(saved_registers)
}

// Sets the running task aside until `ticks` more ticks have gone by. The
// other tasks run meanwhile, and if none of them has anything to do, the
// processor rests. Task 0 cannot wait this way: for it this only gives the
// other tasks their turns. It must not be called during startup, before
// device signals are switched on.
pub fn task_wait(ticks: u64) {
    // Noting the wake time and giving up the turn belong together.
    let were_on = signals_off();
    unsafe {
        TASKS[CURRENT_TASK].wake_tick = TICKS.load(Ordering::Relaxed) + ticks;
        asm!("int {entry}", entry = const WAIT_ENTRY);
    }
    signals_back(were_on);
}

// What task 0 does when it has nothing to do. If another task could run, it
// gets the turn at once. If none could, the processor rests until the next
// device signal. Call it with device signals on.
pub fn task_rest() {
    let were_on = signals_off();
    let now = TICKS.load(Ordering::Relaxed);
    let mut another_could_run = false;
    for place in 1..MAX_TASKS {
        if unsafe { TASKS[place].state == READY && TASKS[place].wake_tick <= now } {
            another_could_run = true;
        }
    }
    if another_could_run {
        unsafe { asm!("int {entry}", entry = const WAIT_ENTRY) };
        signals_back(were_on);
    } else {
        // Signals back on and sleep, as one step: `sti` only takes effect
        // after the instruction that follows it, so no signal can slip in
        // between the two and be slept through.
        unsafe { asm!("sti", "hlt") };
    }
}

// Adds a task that will run `work`. It starts at its next turn.
pub fn task_add(work: fn()) {
    // The timer must not switch tasks while the list is being changed.
    let were_on = signals_off();
    unsafe {
        // Find a place in the list: an empty one, or one whose task has finished.
        let mut place = 1;
        while place < MAX_TASKS && TASKS[place].state == READY {
            place += 1;
        }
        if place == MAX_TASKS {
            panic!("too many tasks");
        }
        // A finished task no longer needs its stack.
        if TASKS[place].state == FINISHED {
            heap_give_back(TASKS[place].stack as *mut u8, TASK_STACK_SIZE, 16);
        }

        // A stack grows downward, so the new task starts at its top.
        let stack = heap_take(TASK_STACK_SIZE, 16) as u64;
        let top = stack + TASK_STACK_SIZE as u64;

        // Make the stack look as if the task had been interrupted just as it
        // was about to start `task_run`. The first switch to it then starts it.
        let saved = (top - 8 - size_of::<SavedRegisters>() as u64) as *mut SavedRegisters;
        let start: fn() -> ! = task_run;
        saved.write_bytes(0, 1);
        (*saved).address = start as usize as u64;
        (*saved).code_segment = CODE_SEGMENT as u64;
        (*saved).flags = 0x202; // "Device signals are on."
        (*saved).stack = top - 8;
        (*saved).stack_segment = DATA_SEGMENT as u64;

        TASKS[place] = Task {
            state: READY,
            work: Some(work),
            stack,
            saved_registers: saved as u64,
            wake_tick: 0,
        };
    }
    signals_back(were_on);
}

// The first code every new task runs. It does the task's work, and when that
// is done it marks the task as finished and waits to be set aside for good.
fn task_run() -> ! {
    if let Some(work) = unsafe { TASKS[CURRENT_TASK].work } {
        work();
    }
    unsafe { TASKS[CURRENT_TASK].state = FINISHED };
    loop {
        unsafe { asm!("hlt") };
    }
}
