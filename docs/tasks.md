# Tasks: several pieces of work taking turns

Code: `src/tasks.rs`. The timer's handler `on_timer` is in `src/timer.rs`; `signals_off` and `signals_back` are in `src/processor.rs`.

A task is a piece of work with a stack of its own. Only one task runs at a time. On every timer signal the running task is set aside and the next one carries on, so they all seem to run at once. A task does not have to cooperate: the timer takes the processor away from it. A task can also step aside by itself, to wait for a moment in time.

All tasks are part of the kernel. They share one set of page tables and nothing protects them from each other.

## The switch

There are two ways into the switch. Both run the same machine instructions, written once in the macro `switch_entry!` and produced twice:

- `timer_entry`, which the processor jumps to on every timer signal. Its handler is `on_timer`.
- `wait_entry`, which a task reaches by itself with the instruction `int 48`. Its handler is `on_wait`. Line 48 of the interrupt table (`WAIT_ENTRY`) is the first line after the 16 device lines.

What happens, in either case:

1. The processor writes down five things on the running task's stack (where its code was, its flags, where its stack was, and the two segments) and jumps to the entry.
2. The entry pushes all 15 general registers on that same stack. The task's whole state now lies on its own stack.
3. It calls the handler, handing it the address where those registers lie.
4. The handler asks which task is next and answers with the address where *that* task's registers lie. `on_timer` first counts the tick and tells the interrupt controller the signal is dealt with. `on_wait` does neither, because no device signalled.
5. The entry makes that address the stack, pops the 15 registers and returns. Because it is now on the other task's stack, the return lands in the other task, exactly where it was set aside.

Rules that keep this working:

- `SavedRegisters` describes what lies on a set-aside task's stack. Its fields are in the order `switch_entry!` pops them. Change the two together.
- `on_timer` must call `signal_done` on every tick, whichever task it switches to. Until the interrupt controller hears it, it holds back all further ticks, and with them every further switch.
- Fifteen pushes leave the stack aligned to 16 bytes at the `call`. An even number would not.
- The keyboard keeps the smaller stub, `device_entry!` in `interrupts.rs`, which saves nine registers and cannot switch tasks. See [interrupts.md](interrupts.md).
- The build target has no SSE, so there are no other registers. If SSE is ever switched on, its registers must be saved per task too. Until then the processor refuses SSE instructions in every task; see [encryption.md](encryption.md).

## The list of tasks

- `TASKS` is a fixed list of 8 places (`MAX_TASKS`). Each place is `EMPTY`, `READY` or `FINISHED`. `CURRENT_TASK` is the place of the running task.
- A ready task may be waiting: its `wake_tick` is the tick count it waits for, and 0 means it is not waiting.
- `switch_task` gives each ready task a turn, in the order of the list, passing over those whose time has not come. A turn lasts one tick, 10 ms, unless the task steps aside sooner.
- Task 0 is the code the kernel started with (`efi_main` and its main loop). It keeps the stack it always had, the firmware's. It never ends and never waits, and `switch_task` always counts it as ready. Without that, the kernel would loop forever inside a handler as soon as every other task waited.
- `switch_task` runs inside a handler. It must not print or use the heap, which is why the list is a fixed array and not a `Vec`.
- Use `MAX_TASKS`, not `TASKS.len()`: calling `.len()` on a `static mut` takes a reference, which edition 2024 refuses.

## Adding a task

`task_add(work)` adds a task that runs the function `work`. It starts at its next turn.

- It switches device signals off while it works, so the timer cannot read the list half-changed.
- It takes the first place that is not `READY`. If all are, it panics with "too many tasks".
- It takes a 256 KB stack from the heap (`TASK_STACK_SIZE`). One size serves every task, and the network task sets it: making an encrypted link takes up to 100 KB there; see [encryption.md](encryption.md).
- It then makes the new stack look as if the task had been set aside just as it was about to start `task_run`: a `SavedRegisters` at the top, with all registers zero and
  - the code address of `task_run`,
  - code segment 8 and stack segment 16,
  - flags `0x202`, which means "device signals on",
  - a stack address 8 bytes below the top. A function expects the stack to sit 8 bytes off a multiple of 16 when it starts, as it does right after a `call`.
- The first switch to the task pops that made-up state, and the task starts.

## Waiting

`task_wait(ticks)` sets the running task aside until that many more ticks have gone by.

- It notes the wake time in the task's `wake_tick` and gives up the turn with `int 48`. Both happen with device signals off, so they count as one step; the signals are restored when the task comes back.
- The wait is never shorter than asked. Its end can come a tick or two late when other tasks are busy, because the task then has to wait for its turn.
- A wait of 0 ticks only gives the other tasks their turns.
- Task 0 cannot wait this way. For it, `task_wait` does no more than a wait of 0.
- Do not wait during startup, before device signals are switched on: the wait would start the other tasks, with signals on, before the interrupt controller is set up.
- A task can only wait for time. Waiting for a key or a packet still means looking again and again, with short waits in between.

## Resting

While every other task waits, the processor has nothing to do. Task 0 is the one that rests it.

- `task_rest()` is what task 0's main loop calls when it has nothing to do. If another task could run, that task gets the turn at once. If none could, the processor sleeps with `hlt` until the next device signal.
- Switching signals back on and going to sleep is one step, `sti` followed by `hlt`: `sti` only takes effect after the instruction behind it, so no signal can slip in between and be slept through.
- `RESTED_TICKS` counts the ticks that arrived while task 0 was running. Task 0 passes its turn on whenever another task could run, so such a tick found the processor resting. `efi_main` prints the count with the typing prompt.

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
- Do not call `task_wait` inside such a stretch unless that is meant: the other tasks run meanwhile, with their own signals on.

What is protected today:

- **The heap.** `KernelHeap` switches signals off around every request and return made by Rust's lists and text. `heap_take` and `heap_give_back` themselves do not, so call them directly only with signals off, as `task_add` does.
- **Printing.** `serial_print` keeps one text whole. But `write!` sends a line in several pieces, and another task's line can land between them. To print a line from a task, build it first and send it in one go: `serial_print(&format!("... {}\r\n", value))`.
- **The list of tasks.** `task_add`, `task_wait` and `task_rest` switch signals off.
- **The PCI list.** `pci_read` and `pci_write` take two port steps each and switch signals off around them.
- **The clock chip.** Reading one of its values takes two port steps too, and `chip_value` switches signals off around them. Random numbers need no protection: each draw is a single instruction.
- **The network card.** `network_card_send` and `network_card_receive` switch signals off while they change the waiting lines and the driver's counters. So do the card's setup and `map_device_memory`.
- **The network stack** needs no protection of its own so far: only its own task, `network_task`, touches it. The page fetch runs inside that task for this reason. Anything another task wants from the network will have to go through that task or be protected.

Not protected, and fine as long as it stays that way:

- The keyboard's waiting line is taken from by one task only, the main loop.

## The demonstration

Besides the two demonstration tasks there is one task that never ends: `network_task`, which runs the network stack and waits one tick between its looks; see [network.md](network.md).

`task_a` and `task_b` in `main.rs` each print three numbered lines, one second apart, and then end. Between lines they wait with `task_wait`. Task A's first wait is half a second and task B's a whole one, so their lines come in turn and never fall on the same tick.

The main loop prints how many of the first ticks found the processor resting, and then the typing prompt, once four seconds have gone by. With the tasks waiting, that is nearly all of them (399 of 400). With the same tasks spinning instead, it is 100 of 400.

The demonstration no longer shows that the timer can take the processor from a task that never steps aside. It used to, when the two tasks waited by spinning. That is now shown only by tests with spinning tasks; see [testing.md](testing.md).

## Limits

See [open-points.md](open-points.md). In short: a task can wait for a time but not for an event, there are 8 places and no priorities, and nothing notices a stack that overflows.

Measured in a debug build: the demonstration tasks used about 2 KB of their stacks, tasks working with lists and formatted text about 4 KB, and the network task up to 100 KB of its 256 KB.
