//! Tasks: several pieces of work that take turns on the processor. The timer
//! makes the switch. Notes: `docs/tasks.md`.

use core::arch::{asm, naked_asm};

use crate::heap::{heap_give_back, heap_take};
use crate::processor::{signals_back, signals_off};
use crate::segments::{CODE_SEGMENT, DATA_SEGMENT};
use crate::timer::on_timer;

// A task is a piece of work with a stack of its own. Only one task runs at a
// time. On every timer signal the running task is set aside and the next one
// carries on, so they all seem to run at once.

// What lies on a task's stack while the task is set aside: all of its
// registers, then what the processor itself wrote down when the timer
// interrupted it. The registers are in the order `timer_entry` takes them off
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

// The machine instructions the processor jumps to on every timer signal. They
// save every register on the stack of the task that was running, let
// `on_timer` say which stack to carry on with, and put every register back
// from that stack. If it is another task's stack, returning lands in that
// other task, exactly where it was interrupted.
#[unsafe(naked)]
pub extern "sysv64" fn timer_entry() {
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
        "mov rdi, rsp", // Tell `on_timer` where the registers were saved,
        "call {on_timer}",
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
        "iretq", // Return to the interrupted code.
        on_timer = sym on_timer,
    )
}

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
}

static mut TASKS: [Task; MAX_TASKS] = [Task {
    state: EMPTY,
    work: None,
    stack: 0,
    saved_registers: 0,
}; MAX_TASKS];

// Which task is running. Task 0 is the code the kernel started with. It keeps
// the stack it always had, and its place in the list only remembers where its
// registers lie.
static mut CURRENT_TASK: usize = 0;

// Each task's stack is 64 KB.
const TASK_STACK_SIZE: usize = 64 * 1024;

// Sets the running task aside and picks the next one: each ready task in
// turn. It is given the place where the running task's registers were saved,
// and answers with the place where the next task's registers lie. It runs
// inside the timer's handler, so it must not print or use the heap.
pub fn next_task(saved_registers: u64) -> u64 {
    unsafe {
        TASKS[CURRENT_TASK].saved_registers = saved_registers;
        loop {
            CURRENT_TASK = (CURRENT_TASK + 1) % MAX_TASKS;
            // Task 0 never ends, so it is always ready.
            if CURRENT_TASK == 0 || TASKS[CURRENT_TASK].state == READY {
                break;
            }
        }
        TASKS[CURRENT_TASK].saved_registers
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
