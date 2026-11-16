# Tasks: several pieces of work taking turns

Code: `src/tasks.rs`. The timer's handler `on_timer` is in `src/timer.rs`; `signals_off` and `signals_back` are in `src/processor.rs`.

A task is a piece of work with a stack of its own. Only one task runs at a time. On every timer signal the running task is set aside and the next one carries on, so they all seem to run at once. A task does not have to cooperate: the timer takes the processor away from it.

All tasks are part of the kernel. They share one set of page tables and nothing protects them from each other.

## The switch

1. The timer signals. The processor writes down five things on the running task's stack (where its code was, its flags, where its stack was, and the two segments) and jumps to `timer_entry`.
2. `timer_entry` pushes all 15 general registers on that same stack. The task's whole state now lies on its own stack.
3. It calls `on_timer`, handing it the address where those registers lie.
4. `on_timer` counts the tick, tells the interrupt controller the signal is dealt with, and asks `next_task` which task is next. It answers with the address where *that* task's registers lie.
5. `timer_entry` makes that address the stack, pops the 15 registers and returns. Because it is now on the other task's stack, the return lands in the other task, exactly where it was interrupted.

Rules that keep this working:

- `SavedRegisters` describes what lies on a set-aside task's stack. Its fields are in the order `timer_entry` pops them. Change the two together.
- `on_timer` must call `signal_done` on every tick, whichever task it switches to. Until the interrupt controller hears it, it holds back all further ticks, and with them every further switch.
- Fifteen pushes leave the stack aligned to 16 bytes at the `call`. An even number would not.
- The keyboard keeps the smaller stub, `device_entry!` in `interrupts.rs`, which saves nine registers and cannot switch tasks. See [interrupts.md](interrupts.md).
- The build target has no SSE, so there are no other registers. If SSE is ever switched on, its registers must be saved per task too.

## The list of tasks

- `TASKS` is a fixed list of 8 places (`MAX_TASKS`). Each place is `EMPTY`, `READY` or `FINISHED`. `CURRENT_TASK` is the place of the running task.
- Task 0 is the code the kernel started with (`efi_main` and its main loop). It keeps the stack it always had, the firmware's. It never ends, and `next_task` always counts it as ready. Without that, a kernel with no other task would loop forever inside the handler.
- `next_task` gives each ready task a turn, in the order of the list. A turn lasts one tick, 10 ms.
- `next_task` runs inside the timer's handler. It must not print or use the heap, which is why the list is a fixed array and not a `Vec`.
- Use `MAX_TASKS`, not `TASKS.len()`: calling `.len()` on a `static mut` takes a reference, which edition 2024 refuses.

## Adding a task

`task_add(work)` adds a task that runs the function `work`. It starts at its next turn.

- It switches device signals off while it works, so the timer cannot read the list half-changed.
- It takes the first place that is not `READY`. If all are, it panics with "too many tasks".
- It takes a 64 KB stack from the heap (`TASK_STACK_SIZE`).
- It then makes the new stack look as if the task had been interrupted just as it was about to start `task_run`: a `SavedRegisters` at the top, with all registers zero and
  - the code address of `task_run`,
  - code segment 8 and stack segment 16,
  - flags `0x202`, which means "device signals on",
  - a stack address 8 bytes below the top. A function expects the stack to sit 8 bytes off a multiple of 16 when it starts, as it does right after a `call`.
- The first switch to the task pops that made-up state, and the task starts.

## A task ending

- Every new task starts in `task_run`. It looks up the task's `work` in the list and calls it.
- When `work` returns, `task_run` marks the task `FINISHED` and sleeps with `hlt`. At the next tick it is set aside and never gets another turn.
- A finished task's stack is given back to the heap when `task_add` reuses its place. That is safe: a finished task is never the running one while another task calls `task_add`.
- A failure or a panic inside any task stops the whole kernel, as anywhere else.

## Rules for code that runs in tasks

A switch can happen between any two instructions. Anything that several tasks change needs protection. The tool is a pair in `processor.rs`:

```rust
let were_on = signals_off();
// ... nothing can interrupt here, so no other task gets a turn ...
signals_back(were_on);
```

- `signals_back` switches signals on again only if they were on before. Never use a plain `sti` for this: the same code also runs during startup and inside failure reports, where signals are off and must stay off.
- Keep the stretch short. While signals are off, ticks and keys wait.

What is protected today:

- **The heap.** `KernelHeap` switches signals off around every request and return made by Rust's lists and text. `heap_take` and `heap_give_back` themselves do not, so call them directly only with signals off, as `task_add` does.
- **Printing.** `serial_print` keeps one text whole. But `write!` sends a line in several pieces, and another task's line can land between them. To print a line from a task, build it first and send it in one go: `serial_print(&format!("... {}\r\n", value))`.
- **The list of tasks.** `task_add` switches signals off.

Not protected, and fine as long as it stays that way:

- The keyboard's waiting line is taken from by one task only, the main loop.

## The demonstration

`task_a` and `task_b` in `main.rs` each print three numbered lines, one second apart, and then end. Two things about them are deliberate:

- They wait by spinning, never by handing the processor over. Both still get on, and keys are still echoed meanwhile. That is the proof that the timer makes the switch.
- Task A's lines come half a second before task B's. Lines that fall on the same tick would come out in an order that depends on whose turn it happens to be.

The main loop prints the typing prompt once four seconds have gone by.

## Limits

See [open-points.md](open-points.md). In short: a task cannot give up its turn or wait for something except by spinning or `hlt`, there are 8 places and no priorities, nothing notices a stack that overflows, and the main loop still sleeps through its own turns.

Measured in a debug build: the demonstration tasks used about 2 KB of their 64 KB stacks, and tasks working with lists and formatted text about 4 KB.
