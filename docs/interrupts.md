# Failures and device signals

Code: `src/segments.rs`, `src/faults.rs`, `src/interrupts.rs`, `src/controller.rs`, `src/timer.rs`, `src/keyboard.rs`.

Two kinds of events make the processor drop what it is doing and jump to kernel code:

- a **failure** (an exception): the running code did something impossible, such as dividing by zero. The kernel reports it and stops.
- a **signal** (an interrupt): a device wants attention. The kernel handles it and the interrupted code carries on.

Both go through the interrupt table.

## The two tables

- **Segment table (GDT)**, `SEGMENT_TABLE` in `segments.rs`: an empty entry, a code entry (selector 8, `CODE_SEGMENT`) and a data entry (selector 16). The firmware's copy lives in memory the kernel does not own, so the kernel loads its own with `load_segment_table`.
- **Interrupt table (IDT)**, `INTERRUPT_TABLE` in `interrupts.rs`: 256 lines, one per event. Lines 0 to 31 are the processor's failures. Lines 32 to 47 are the 16 device lines. Line 48 is not for a device: a task reaches it with the instruction `int 48` to step aside; see [tasks.md](tasks.md). The rest are empty.
- `set_interrupt_entry` fills one line. `load_interrupt_table` fills all 49 and hands the table to the processor.
- Every line uses kind `0x8E`: in use, kernel only, and no other signals while its code runs. So handlers never interrupt each other.
- An event that arrives on an empty line becomes a general protection fault. Its detail code, shifted right by 3, is the number of the line that was empty: `int 49` gives detail code `0x18a`, and `0x18a` shifted right by 3 is 49. That is the first thing to check if a fault appears right after `sti`.

## Failures

- Each of the 32 failures has a small stub of machine instructions, made by the `fault_entry!` macro and listed with its name in `FAULTS` (`faults.rs`).
- A stub puts the failure's number in `edi` and the stack address in `rsi`, then calls `report_fault`, which is `extern "sysv64"` so that those two registers are its two arguments.
- Some failures come with a detail code from the processor and some do not. For those that do not, the stub pushes a zero, so `FaultNotes` always has the same shape. `has_code` in `FAULTS` marks the ones that bring their own.
- `report_fault` prints one line and stops for good with `stop()`. The fault stubs never return.
- The stubs are naked functions (`#[unsafe(naked)]` with `naked_asm!`), because Rust's own `extern "x86-interrupt"` is not available on stable Rust.

What the reports look like:

```
CPU fault: divide by zero at 0xdf01f7a
CPU fault: page fault at 0xdf013a4, touching 0xffff800000000000, detail code 0x2
Kernel panic: src\frames.rs:29: the machine is out of memory
```

- "at" is the address of the instruction that failed.
- "touching", shown for a page fault, is the address it tried to use (the processor keeps it in `cr2`).
- The detail code is shown when it is not zero.
- A panic is Rust code giving up, for example on a list index out of range. The panic handler in `main.rs` switches signals off, prints the file, the line and the message, then stops.

Limits:

- There is no spare stack. A failure inside `report_fault`, or running out of stack, resets the machine without a message.

## The interrupt controller (PIC)

- Device signals reach the processor through the interrupt controller: two chips of 8 lines each. The timer is on line 0 and the keyboard on line 1.
- `controller_setup` sets both chips up from scratch, so nothing depends on how the firmware left them. It puts the 16 lines on interrupt-table lines 32 to 47 (`FIRST_DEVICE_ENTRY`) and holds back every line except 0 and 1.
- The lines must be moved to 32 because a PC's old default puts them on lines 8 to 15, where the processor's own failures are.
- After handling a signal, the handler must call `signal_done` (the "end of interrupt" message). Until then the controller holds back the next signal. Forgetting it shows as exactly one timer tick and then silence.
- `signal_done` tells only the first chip. That is enough while only lines 0 to 7 are used. A handler on lines 8 to 15 must tell both chips.
- The controller reaches the processor only because the firmware leaves the processor's own interrupt unit (the local APIC) passing those signals through. That held in QEMU with its firmware. The kernel does not set it up itself.

## Device stubs

- There are two kinds of stub. The keyboard uses `device_entry!`, described here. The timer has its own, `timer_entry` in `tasks.rs`, which saves every register so that it can switch to another task; line 48 uses the same instructions as `wait_entry`. See [tasks.md](tasks.md).
- `device_entry!(handler)` in `interrupts.rs` makes the stub for one device line. It saves the nine registers that Rust code may change (`rax rcx rdx rsi rdi r8 r9 r10 r11`), runs `cld`, calls the handler, restores the registers and returns with `iretq`. It always returns to the code it interrupted.
- The handler is an `extern "sysv64" fn()`. Under that convention the other registers are restored by the handler itself.
- Nine pushes leave the stack aligned to 16 bytes at the `call`, as Rust code expects. Changing the number of pushes breaks that.
- The build target has no SSE, so there are no other registers to save. If SSE is ever switched on, the stubs must save those registers too. Until then the processor is told to refuse SSE instructions (`sse_refuse`), so code that used them anyway stops with `CPU fault: device not available`; see [encryption.md](encryption.md).
- Lines 32 to 47 are first filled with `ignore_signal`, a bare `iretq`. That makes a stray signal harmless instead of a failure, and it covers the controller's false alarm on line 7, which must not be answered with `signal_done`.
- To listen to a new device: write an `extern "sysv64"` handler that ends with `signal_done()`, add its line in `load_interrupt_table` with `device_entry!`, and let its line through in `controller_setup`.

## The timer (PIT)

- The timer chip counts down from a chosen number, 1,193,182 steps per second, and signals at zero. `timer_setup` sets it to 100 signals per second (`TICKS_PER_SECOND`).
- `on_timer` adds one to `TICKS`, an `AtomicU64`, calls `signal_done`, and then lets the next task have its turn by calling `next_task`. It is given the address where the interrupted task's registers were saved and answers with the address to restore from; see [tasks.md](tasks.md).
- `TICKS` is the kernel's only clock. It only counts signals, so signals that arrive late or get lost make it run slow.
- A tick is also the longest one task's turn can last; a task that waits gives the rest of its turn away.

## The keyboard

- The keyboard controller (PS/2) hands over key numbers at port `0x60` and reports its state and takes commands at port `0x64`.
- `keyboard_setup`:
  - returns early if the state port reads `0xFF`, which means no controller is there;
  - writes the settings byte `0x65`: keyboard on, a signal for each key, key numbers translated to the classic set ("set 1"), mouse off;
  - empties any byte still waiting. The controller sends no new signal while an old byte waits, so skipping this can leave the keyboard silent.
- All waits in `keyboard_setup` give up after 100,000 tries.
- `on_keyboard` checks that a byte is really waiting, reads it and puts it in `KEY_QUEUE`: 16 slots, with the counters `KEYS_ARRIVED` and `KEYS_TAKEN`, all atomics. When the queue is full the key is dropped. It always ends with `signal_done`.
- The mouse is switched off in the settings byte on purpose. The mouse shares the keyboard's waiting byte, and nothing listens on its line, so a mouse byte would block the keyboard.
- The main loop takes keys out with `next_key` and turns them into letters with `key_letter`.
- A key number says where the key sits, not what is printed on it. Letting a key go sends the same number plus 128.
- `key_letter` knows the US layout in lower case, Enter and the space bar. Everything else gives nothing.

Left out on purpose, as possible additions: Shift and capitals, Backspace, any layout other than US.

## Rules for handlers

- A handler only counts or stores. Printing and anything slow happens in a task.
- Anything a handler shares with other code is an atomic.
- Handlers stay away from the heap and from printing. `next_task`, which runs inside the timer's handler, uses a fixed list for that reason.
- Code outside handlers that must not be interrupted switches signals off with `signals_off` and back with `signals_back`; see [tasks.md](tasks.md).
