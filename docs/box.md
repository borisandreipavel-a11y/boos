# The box: running an app locked in

Code: `src/app_box.rs`, the two runs in `efi_main`, and two copies in `vendor/` (`wasmparser`, `libm`).

An app is a program that is not part of the kernel. It runs inside a box: it gets one block of memory of its own and can touch nothing else. The box is kept by an outside library, wasmi, which carries the app out one small step at a time. What an app may ask the kernel to do is a short list, the system API. Today that list has one entry: print a text.

## The words

- **WebAssembly** is a form for programs, made of very small steps ("take this value", "add the two"), with exactly written-down rules. A WebAssembly program is a row of bytes.
- A **runtime** is the code that runs such a program. wasmi is a runtime that **interprets**: it reads the steps and carries them out one by one. It never turns them into instructions for the processor.
- **Checking** (validation) is going through a whole program before any of it runs and refusing it if it breaks a rule: a step that takes a value that is not there, a jump to nowhere, a call to a function that does not exist.
- The **engine** is wasmi's part that translates programs and runs them. The **store** holds what belongs to one running app.
- An app's **memory** is one block of bytes, counted in **pages** of 64 KB. Every read and write of the app is checked against the block's size.
- A **table** is a list of functions an app can keep, to call one by its place in the list.
- **Fuel** is a budget of steps. wasmi takes about one unit per step, and stops the app when the budget is used up.
- The **system API** is the list of things an app may ask the kernel to do. A program names each thing it wants in its own bytes, as a pair of names such as `kernel` and `print`.

## The outside code

`Cargo.toml` names one crate, **`wasmi` 1.1.0**, with its default features off because they need an operating system. `Cargo.lock` lists eight crates for it, and all eight are compiled:

- `wasmi`, `wasmi_core`, `wasmi_ir`, `wasmi_collections` (all 1.1.0): the runtime itself.
- `wasmparser` 0.239.0 reads a program's bytes and checks them. Its own settings refuse `unsafe` code; one place in its source is marked as an exception.
- `libm` 0.2.16 holds the arithmetic for numbers with a point that Rust offers only with an operating system: square roots and the kinds of rounding.
- `spin` 0.9.9 (locks that wait by spinning) and `bitflags` 2.13.2 (a helper). smoltcp uses the older `bitflags` 1.3.2, so both versions are built.

Six are fetched from crates.io on a first build, 0.44 MB. `wasmparser` and `libm` are copies in `vendor/`, because each has a build script; [vendor/README.md](../vendor/README.md) says what was changed. None of the eight is a macro crate. No setting in `.cargo/config.toml` was needed.

Why this library and this version, from the comparison made on 2026-11-17:

- wasmi has existed since 2018, is widely used, and is the only candidate that outside auditors have looked at: version 0.31 in 2023 and versions 0.36 to 0.38 in 2024. Version 1.1.0 itself has not been audited.
- **The version is fixed at 1.1.0 on purpose.** The line after it, 2.0.0, cannot be built here: one of its crates has a build script that writes four of the crate's own source files, several hundred KB of them. A build script cannot run on the building computer (see `vendor/README.md`), and that one cannot be replaced by hand. `Cargo.toml` therefore says `=1.1.0`.
- `tinywasm` 0.11.0 would fit as well and has no `unsafe` code, but it has one author, few users, no audit, and a breaking release every two months or so.
- `spacewasm` 0.7.1 is built never to give up on a failed request for memory, but it was under five months old with seven security advisories already, and it knows only the first version of WebAssembly.
- `nowasm` does not check a program before running it. `wasmtime` needs a C compiler and macro crates.

Security advisories, looked up on 2026-11-17: wasmi has two in its history. By their titles they are a write outside its bounds (2024, fixed in 0.31.1) and a use of memory after it was given back (December 2025, fixed in 1.0.1); only the titles and the affected versions were read. `spin` has two (fixed in 0.5.2 and 0.9.8), which were read. The versions used here are past all four. rustsec.org has no page for the other crates. Read them again whenever a version is changed.

## A run in the box

`box_run(program)` runs an app: it gets the app ready and calls the app's function `start`, which takes nothing and gives back nothing. Whatever goes wrong comes back as a reason in words, never as a kernel panic.

Getting an app ready is `box_start(program)`. Its steps:

1. **A new engine**, set to count fuel. Each run has an engine of its own, which goes away with the store at the end. An engine keeps every program it has translated for as long as it lives: with one engine for 1,620 programs the heap grew by 7 MB, with an engine for each it did not grow at all.
2. **`Module::new`** checks the program and translates it into wasmi's own steps. A program that breaks a rule is refused here, before any of it has run. wasmi also has `Module::new_unchecked`, which skips the check; it must never be used.
3. **A store with limits** (see below) and with `APP_FUEL` units of fuel.
4. **A linker holding the system API.** The linker is where the kernel puts what an app may ask it for. A program that asks for anything that is not there, or for something in another shape than the kernel offers it in, is not started.
5. **Starting the app**, which gives it its memory and table within the limits.

`box_run` then finds `start` by name, sees that it takes and gives nothing, and calls it. `box_check` uses `box_start` too, and calls a function `add` instead.

That `start` is a function the app shows to the outside under this name. It is not WebAssembly's "start section", a different thing with a similar name: a program may name one function there that runs by itself during step 5. Such a function runs under the same limits and fuel, which are set before that step, but no program with one has been tried.

`reason()` turns an error into text. wasmi's errors can hold names taken from the program, so the text is cleaned with `plain_text` and cut at 120 signs before it is shown.

## The system API

One call so far. An app reaches it as `print` of `kernel`.

**`kernel.print(start, length)`** prints a text that lies in the app's own memory. `start` is the address where the text begins there, `length` how many bytes long it is; both are whole numbers of 32 bits. Nothing comes back. The kernel prints the text as one line with `App: ` in front.

The text comes from outside the kernel, so `kernel_print` takes nothing about it on trust:

- **The app must show its memory under the name `memory`.** That is how the kernel finds it. An app that prints without doing so is stopped.
- **The whole text must lie inside the app's memory.** The reading is done by wasmi's `read`, which refuses if any part lies outside. A `start` below zero becomes a very large address, which is outside too. The app is stopped.
- **A text is at most 200 bytes long** (`APP_TEXT_LIMIT`). A longer one, or a length below zero, stops the app. Without this check a length of 201 stopped the kernel itself, with a panic about the 200 bytes of room the text is copied into.
- **An app may print 100 texts in one run** (`APP_PRINT_LIMIT`). The next one stops it. Fuel does not bound printing well: with this limit taken out on purpose, an app in a loop printed 400,000 lines in 40 seconds and was not done.
- **Only plain letters, digits and signs are printed.** Every other byte becomes a dot, the bytes for a line end among them. So one call makes exactly one line, and an app cannot send commands to the terminal.
- **`App: ` stands in front of every line.** An app can write "Kernel panic" in its text, but never at the start of a line. With the cleaning taken out on purpose, a test app's text did put a made-up `Kernel panic:` line on the screen, convincingly enough to fool the test script.

"Stopped" means that `start` ends there and `box_run` gives back the reason, such as `it asked to print a text that lies outside its memory`. What the app printed before stays printed.

To add a call: write a function like `kernel_print`, and name it in `box_start` with `linker.func_wrap("kernel", "its name", the_function)`. Treat everything the app hands over as untrusted: check numbers before using them as sizes, and read the app's memory only through `read`.

## The limits

An app is held to these. They are constants in `app_box.rs`.

| Limit | Value | What happens past it |
| --- | --- | --- |
| Memory (`APP_MEMORY_LIMIT`) | 1 MB, which is 16 pages | An app that asks for more at the start is not started. Asking for more while running gets the answer "no" (-1), and the app carries on |
| Memories | 1 | Not started |
| Table (`APP_TABLE_LIMIT`) | 4096 places | Not started |
| Tables | 1 | Not started |
| Fuel (`APP_FUEL`) | 10,000,000 units per run | The app is stopped with "all fuel consumed" |
| Length of a printed text (`APP_TEXT_LIMIT`) | 200 bytes | The app is stopped |
| Texts printed (`APP_PRINT_LIMIT`) | 100 per run | The app is stopped |

Two more come from wasmi and are left as it sets them: at most 1000 calls nested inside each other ("call stack exhausted" past that), and at most 1 MB for wasmi's own stack of an app's values.

Why they are needed:

- **A request for memory that cannot be met stops the whole kernel** (see [memory.md](memory.md)). With the memory limit taken out on purpose, a program that asks for 1 GB did exactly that: `Kernel panic: ... the machine is out of memory`. The limits on tables and on the number of memories and tables close the same door.
- **Without fuel, a loop that never ends never comes back.** With fuel taken out on purpose, the test never got past such a loop. In this build ten million units are about two seconds of the processor.

What the limits do not cover: wasmi's own bookkeeping for an app lives on the kernel's heap and is not counted in the app's memory. A translated program takes room in proportion to its size.

## The two apps in the kernel

Both are whole WebAssembly programs written out by hand in `app_box.rs`, with a comment on each group of bytes. No compiler made them. Each has a heading of 8 bytes and then numbered sections, each with its length in front.

- **`ADDING_APP`, 41 bytes.** One function, `add`, that gives back the sum of two numbers. Four sections: the kinds of function, the functions, what the app shows to the outside, the code. The code is 7 bytes: no variables, take the first value, take the second, add, end.
- **`GREETING_APP`, 111 bytes.** It keeps the text "Hello from inside the box" in its memory and asks the kernel to print it. Three sections more: what it asks of the kernel (`kernel`, `print`), its memory (one page), and what the memory holds at the start (the 25 bytes of the text, at address 0). It shows two things to the outside, `memory` and `start`. The code of `start` is 8 bytes: no variables, the number 0, the number 25, call `print`, end.

## The two runs at startup

`efi_main` runs both apps after the encryption line.

`box_check()` runs `ADDING_APP` and asks it for 2 + 3:

- `Box: a program of 41 bytes ran inside it and answered 2 + 3 = 5`
- with a wrong answer: `Box: not working, the program inside it answered 2 + 3 = N`
- when the run fails: `Box: not working, because ...` with wasmi's reason.

`box_run(&GREETING_APP)` follows. The line it brings is the app's own, printed by `kernel_print`:

- `App: Hello from inside the box`
- when the run fails: `Box: the app was stopped, because ...` with the reason.

The kernel carries on whatever the outcome. Nothing depends on these runs yet.

Both run with device signals off, on the firmware's stack, like the encryption check before them. The deeper one, the greeting app, goes 45 KB deep, of the 124 KB free there. How long they take was not measured; they do not visibly slow the start.

## Numbers with a point

WebAssembly has numbers with a point, so wasmi carries code for them. The build target computes them in software, without the processor's SSE registers, and the processor refuses SSE instructions (see [encryption.md](encryption.md)). Programs that take square roots, round in four ways, and turn numbers with a point into whole ones and back were run in the box with that refusal on: nothing was refused, and every result matched another engine's bit for bit.

## What was measured

In QEMU, in the plain debug build:

- **Stack:** 45,408 bytes for the greeting app, at startup and in a task alike, of the 124 KB free on the firmware's stack and of a task's 256 KB. The adding app went 43,112 deep when it was measured, before the print call existed. Larger programs will go deeper; nothing bigger than 540 bytes has been run.
- **Size:** the kernel's file grew from 2.9 MB to 6.2 MB.
- **Speed:** checking and translating a program of 540 bytes took about 5 thousandths of a second. A small counting loop ran about 0.7 million rounds a second, at about 4 units of fuel a round. Ten million units of fuel lasted about 2 seconds.
- **Memory:** three rounds of 42 runs took 274 frames in the first round and none after. Two passes over 333 changed programs took none. So nothing is lost from run to run; the heap only never hands frames back (see [memory.md](memory.md)).
- With the outside crates built optimized, in a trial: the file is about half the size, the stack a third as deep, and the steps about 25 times as fast. That setting is not in use; it would change how every outside crate is built.

## How to test it

The programs for tests are made by hand, byte by byte, with a short script outside the repository; no compiler for WebAssembly is installed. Habits that proved their worth:

- **Run every test program in another engine first** and take the expected outcome from there. Node has one built in: `WebAssembly.validate(bytes)` says whether a program follows the rules, and `new WebAssembly.Instance(new WebAssembly.Module(bytes), imports)` runs it, with `imports` holding a `print` that does what the kernel's is meant to do. A hand-made program with a mistake in it is otherwise indistinguishable from a runtime that is wrong.
- **Change every byte of a good program, one at a time**, and run each changed copy. Most are refused by the check; the rest run and either end or are stopped. None may bring the kernel down.
- **Look at every byte the kernel printed**, not only at the lines. Text meant to do harm shows as bytes that are not plain text, or as a line end that is not the two bytes 13 and 10.
- **A script that waits for `Kernel panic` must look for it at the start of a line.** An app can print those words behind `App: `.

[testing.md](testing.md) lists what was verified.

## Limits

See [open-points.md](open-points.md). In short: an app can ask the kernel for one thing only, it runs once from `start` to the end and nothing of it is kept, every run translates the program again, and the version of wasmi cannot simply be raised.
