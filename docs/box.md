# The box: running an app locked in

Code: `src/app_box.rs`, the check in `efi_main`, and two copies in `vendor/` (`wasmparser`, `libm`).

An app is a program that is not part of the kernel. It runs inside a box: it gets one block of memory of its own and can touch nothing else. The box is kept by an outside library, wasmi, which carries the app out one small step at a time. Today the kernel can run one function of an app and get a number back. An app cannot ask the kernel for anything yet.

## The words

- **WebAssembly** is a form for programs, made of very small steps ("take this value", "add the two"), with exactly written-down rules. A WebAssembly program is a row of bytes.
- A **runtime** is the code that runs such a program. wasmi is a runtime that **interprets**: it reads the steps and carries them out one by one. It never turns them into instructions for the processor.
- **Checking** (validation) is going through a whole program before any of it runs and refusing it if it breaks a rule: a step that takes a value that is not there, a jump to nowhere, a call to a function that does not exist.
- The **engine** is wasmi's part that translates programs and runs them. The **store** holds what belongs to one running app.
- An app's **memory** is one block of bytes, counted in **pages** of 64 KB. Every read and write of the app is checked against the block's size.
- A **table** is a list of functions an app can keep, to call one by its place in the list.
- **Fuel** is a budget of steps. wasmi takes about one unit per step, and stops the app when the budget is used up.

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

`box_run(program, function, first, second)` runs one function of a program, hands it two whole numbers and gives back the whole number it answers with. Whatever goes wrong comes back as a reason in words, never as a kernel panic. The steps:

1. **A new engine**, set to count fuel. Each run has an engine of its own, dropped at the end. An engine keeps every program it has translated for as long as it lives: with one engine for 1,620 programs the heap grew by 7 MB, with an engine for each it did not grow at all.
2. **`Module::new`** checks the program and translates it into wasmi's own steps. A program that breaks a rule is refused here, before any of it has run. wasmi also has `Module::new_unchecked`, which skips the check; it must never be used.
3. **A store with limits** (see below) and with `APP_FUEL` units of fuel.
4. **A linker with nothing in it.** The linker is where the kernel puts what an app may ask it for. Nothing is offered yet, so a program that asks for anything is not started.
5. **Starting the app**, which gives it its memory and table within the limits.
6. **Finding the function** by name, seeing that it takes two whole numbers and gives one back, and calling it.

`reason()` turns wasmi's error into text. That text can hold names taken from the program, so it is cleaned with `plain_text` and cut at 120 signs before it is shown.

## The limits

An app is held to these. They are constants in `app_box.rs`.

| Limit | Value | What happens past it |
| --- | --- | --- |
| Memory (`APP_MEMORY_LIMIT`) | 1 MB, which is 16 pages | An app that asks for more at the start is not started. Asking for more while running gets the answer "no" (-1), and the app carries on |
| Memories | 1 | Not started |
| Table (`APP_TABLE_LIMIT`) | 4096 places | Not started |
| Tables | 1 | Not started |
| Fuel (`APP_FUEL`) | 10,000,000 units per run | The app is stopped with "all fuel consumed" |

Two more come from wasmi and are left as it sets them: at most 1000 calls nested inside each other ("call stack exhausted" past that), and at most 1 MB for wasmi's own stack of an app's values.

Why they are needed:

- **A request for memory that cannot be met stops the whole kernel** (see [memory.md](memory.md)). With the memory limit taken out on purpose, a program that asks for 1 GB did exactly that: `Kernel panic: ... the machine is out of memory`. The limits on tables and on the number of memories and tables close the same door.
- **Without fuel, a loop that never ends never comes back.** With fuel taken out on purpose, the test never got past such a loop. In this build ten million units are about two seconds of the processor.

What the limits do not cover: wasmi's own bookkeeping for an app lives on the kernel's heap and is not counted in the app's memory. A translated program takes room in proportion to its size.

## The smallest app

`ADDING_APP` in `app_box.rs` is a whole WebAssembly program of 41 bytes with one function, `add`, that gives back the sum of two numbers. No compiler made it. The bytes are written out by hand with a comment on each group: a heading of 8 bytes, then four numbered sections (the kinds of function, the functions, what the app shows to the outside, the code), each with its length in front. The code itself is 7 bytes: no variables, take the first value, take the second, add, end.

## The check at startup

`box_check()` runs `ADDING_APP` once and asks it for 2 + 3. `efi_main` prints the result after the encryption line:

- `Box: a program of 41 bytes ran inside it and answered 2 + 3 = 5`
- with a wrong answer: `Box: not working, the program inside it answered 2 + 3 = N`
- when the run fails: `Box: not working, because ...` with wasmi's reason.

The kernel carries on after any of the three. Nothing depends on the result yet.

The check runs with device signals off, on the firmware's stack, like the encryption check before it. It goes 43 KB deep, of the 124 KB free there. How long it takes was not measured; it does not visibly slow the start.

## Numbers with a point

WebAssembly has numbers with a point, so wasmi carries code for them. The build target computes them in software, without the processor's SSE registers, and the processor refuses SSE instructions (see [encryption.md](encryption.md)). Programs that take square roots, round in four ways, and turn numbers with a point into whole ones and back were run in the box with that refusal on: nothing was refused, and every result matched another engine's bit for bit.

## What was measured

In QEMU, in the plain debug build:

- **Stack:** 43,112 bytes for the check at startup; 43,784 bytes for a run in a task, of the task's 256 KB. A trial with a program of 540 bytes went 44,376 deep. Larger programs will go deeper; nothing bigger has been run.
- **Size:** the kernel's file grew from 2.9 MB to 6.1 MB.
- **Speed:** checking and translating a program of 540 bytes took about 5 thousandths of a second. A small counting loop ran about 0.7 million rounds a second, at about 4 units of fuel a round. Ten million units of fuel lasted 2.15 seconds.
- **Memory:** three rounds of 42 runs took 303 frames in the first round and none after. Two passes over 621 changed programs, eight runs each, took 160 frames in the first and none in the second. So nothing is lost from run to run; the heap only never hands frames back (see [memory.md](memory.md)).
- With the outside crates built optimized, in a trial: the file is about half the size, the stack a third as deep, and the steps about 25 times as fast. That setting is not in use; it would change how every outside crate is built.

## How to test it

The programs for tests are made by hand, byte by byte, with a short script outside the repository; no compiler for WebAssembly is installed. Two habits that proved their worth:

- **Run every test program in another engine first** and take the expected values from there. Node has one built in: `WebAssembly.validate(bytes)` says whether a program follows the rules, and `new WebAssembly.Instance(new WebAssembly.Module(bytes), {})` runs it. A hand-made program with a mistake in it is otherwise indistinguishable from a runtime that is wrong.
- **Change every byte of a good program, one at a time**, and run each changed copy. Most are refused by the check; the rest run and either answer or are stopped. None may bring the kernel down.

[testing.md](testing.md) lists what was verified.

## Limits

See [open-points.md](open-points.md). In short: an app cannot ask the kernel for anything, only one function shape can be called, nothing is kept between two runs, every run translates the program again, and the version of wasmi cannot simply be raised.
