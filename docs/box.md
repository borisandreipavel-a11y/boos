# The box: running an app locked in

Code: `src/app_box.rs`, the three runs in `efi_main`, and two copies in `vendor/` (`wasmparser`, `libm`).

An app is a program that is not part of the kernel. It runs inside a box: it gets one block of memory of its own and can touch nothing else. The box is kept by an outside library, wasmi, which carries the app out one small step at a time. What an app may ask the kernel to do is a short list, the system API. Today that list has two entries: print a text, and show a text on the screen.

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

`box_accepts(program, functions)` uses `box_start` as well and calls nothing. It answers whether the box would take a program that is not an app with a `start`: after the five steps it looks whether the program shows a memory called `memory` and a function under each of the names given, and gives back the reason in words if not (`it shows no function called ...`). It looks for the names only, not at what the functions take and give. The interpreter is checked with it at startup; see [interpreter.md](interpreter.md).

`box_script(program, script, seed)` is the second way to run something in the box, for a program that carries scripts out. Such a program is not run once from a `start`. After the five steps of `box_start` the kernel:

1. finds `room` and `run` and sees that each takes one whole number of 32 bits and gives one back; a program whose functions have another shape is turned away here;
2. sets the fuel to `SCRIPT_FUEL`, the budget for a script;
3. calls `room(length)` with the script's length in bytes, and gets back where in the program's memory the script should go;
4. writes the script there, through wasmi's `write`, which refuses if any byte of it would lie outside the program's memory. So the place is not taken on trust: a program that names a place outside, or below zero, is stopped with `it gave room for the script outside its own memory`;
5. if `seed` holds a number, finds `seed`, which must take one whole number of 64 bits and give nothing back, and calls it with that number, on the same fuel; the interpreter starts the script's random numbers there;
6. calls `run(length)`. 0 back means the script ran to its end; anything else is reported as `the script made a mistake, which is told in the line before`, because the program prints what went wrong itself.

A completed run returns its last displayed text, if it showed any. On failure, a `ScriptStop` carries any last display, the printed error for a Lua mistake, the reason in words and the kind of stop. The kinds are `Mistake` for that last reason; `OutOfFuel` and `GaveUp` when wasmi reports its own kind of trap for fuel used up and for WebAssembly's `unreachable` (what the interpreter does when it runs out of memory); `Other` for everything else. The kinds come from what wasmi and the program report, not from the words, so that a caller can say them in plainer words (see "Running it" in [apps.md](apps.md)). The script at startup is run without a seed, and says the reason in words as before.

A script longer than `SCRIPT_LIMIT` is turned away before anything is started. A script the model writes is held to the same limit as soon as it comes (see [apps.md](apps.md)). What the script prints goes through `kernel.print` like any app's text, with its limits: 200 bytes a text, 100 texts a run.

That `start` is a function the app shows to the outside under this name. It is not WebAssembly's "start section", a different thing with a similar name: a program may name one function there that runs by itself during step 5. Such a function runs under the same limits and fuel, which are set before that step, but no program with one has been tried.

`reason()` turns an error into text. wasmi's errors can hold names taken from the program, so the text is cleaned with `plain_text` and cut at 120 signs before it is shown.

## The system API

Two calls so far. An app reaches them as `print` and `show` of `kernel`. Both take a text in the same way, and both fetch it with the same function, `app_text`.

**`kernel.print(start, length)`** prints a text that lies in the app's own memory. `start` is the address where the text begins there, `length` how many bytes long it is; both are whole numbers of 32 bits. Nothing comes back. The kernel prints the text as one line with `App: ` in front.

The text comes from outside the kernel, so `app_text` takes nothing about it on trust:

- **The app must show its memory under the name `memory`.** That is how the kernel finds it. An app that prints without doing so is stopped.
- **The whole text must lie inside the app's memory.** The reading is done by wasmi's `read`, which refuses if any part lies outside. A `start` below zero becomes a very large address, which is outside too. The app is stopped.
- **A text is at most 200 bytes long** (`APP_TEXT_LIMIT`). A longer one, or a length below zero, stops the app. The check comes before the kernel takes any memory for the text. The text is copied into a list as long as the app says, so without the check an app could make the kernel ask its heap for up to 2 GB, and a request that cannot be met stops the kernel. That was not tried with this form of the code. In an earlier form, which copied into a fixed room of 200 bytes, a length of 201 with the check taken out stopped the kernel with a panic.
- **An app may print 100 texts in one run** (`APP_PRINT_LIMIT`). The next one stops it. Fuel does not bound printing well: with this limit taken out on purpose, an app in a loop printed 400,000 lines in 40 seconds and was not done.
- **Only plain letters, digits and signs are printed.** Every other byte becomes a dot, the bytes for a line end among them. So one call makes exactly one line, and an app cannot send commands to the terminal.
- **`App: ` stands in front of every line.** An app can write "Kernel panic" in its text, but never at the start of a line. With the cleaning taken out on purpose, a test app's text did put a made-up `Kernel panic:` line on the screen, convincingly enough to fool the test script.

"Stopped" means that `start` ends there and `box_run` gives back the reason, such as `it asked to print a text that lies outside its memory`. What the app printed before stays printed.

**`kernel.show(start, length)`** shows a text on the screen. The app hands the text over exactly as for `print`, and nothing comes back. The kernel paints a box in the middle of the screen and writes the text in it; see "The panel" in [screen.md](screen.md).

- **The app says only what it wants shown.** How the box looks, how large the letters are and where the box sits is the kernel's business: the sizes are kept in one place, `PANEL_STYLE` in `screen.rs`, and the colours are those of the look the person at the machine picked (see "The look" in [screen.md](screen.md)). An app cannot paint, and cannot say anything about the look.
- **The rules for the text are the same as for `print`,** with the word "show" in the reasons: the app must show its memory as `memory`, the whole text must lie inside it, and every byte that is not a plain sign becomes a dot.
- **A shown text is at most 40 bytes long** (`APP_SHOWN_TEXT_LIMIT`), which is what fits on the box's one line. A longer one, or a length below zero, stops the app. With this limit raised to 200 on purpose, a text of 41 signs was accepted. The box itself cuts a text at the 40 signs that fit; see [screen.md](screen.md). The interpreter cuts a script's text at 40 bytes before it hands it over, so a script never meets this rule (see [interpreter.md](interpreter.md)).
- **An app may show 20 texts in one run** (`APP_SHOW_LIMIT`). The next one stops it. Every showing paints the whole box again, about a hundredth of a second, and at startup that happens with device signals off. With this limit taken out on purpose, an app in a loop was still showing after half a minute, 3,457 times, and by a rough count its fuel would have lasted for hours at that pace.
- **Each showing wipes out the one before.** There is one box, for every app. What it shows last stays on the screen after the app has ended, until something paints over it; the kernel keeps only its text, to paint the box again when the person picks another look.
- **Nothing is printed for a showing.** The terminal gets a line only if the app is stopped.
- **On a machine without a usable screen** the text is checked in the same way and then nothing is shown. The app is not stopped for it and cannot tell the difference.

To add a call: write a function like `kernel_show`, and name it in `box_start` with `linker.func_wrap("kernel", "its name", the_function)`. Treat everything the app hands over as untrusted: check numbers before using them as sizes, and read the app's memory only through `read`. A call that takes a text should take it through `app_text`.

## The limits

An app is held to these. They are constants in `app_box.rs`.

| Limit | Value | What happens past it |
| --- | --- | --- |
| Memory (`APP_MEMORY_LIMIT`) | 1 MB, which is 16 pages | An app that asks for more at the start is not started. Asking for more while running gets the answer "no" (-1), and the app carries on |
| Memories | 1 | Not started |
| Table (`APP_TABLE_LIMIT`) | 4096 places | Not started |
| Tables | 1 | Not started |
| Fuel (`APP_FUEL`) | 10,000,000 units per run | The app is stopped with "all fuel consumed" |
| Fuel for a script (`SCRIPT_FUEL`) | 100,000,000 units per script | The script is stopped with "all fuel consumed" |
| Length of a script (`SCRIPT_LIMIT`) | 32 KB | The script is not handed over, and nothing is started |
| Length of a printed text (`APP_TEXT_LIMIT`) | 200 bytes | The app is stopped |
| Texts printed (`APP_PRINT_LIMIT`) | 100 per run | The app is stopped |
| Length of a shown text (`APP_SHOWN_TEXT_LIMIT`) | 40 bytes | The app is stopped |
| Texts shown (`APP_SHOW_LIMIT`) | 20 per run | The app is stopped |

Two more come from wasmi and are left as it sets them: at most 1000 calls nested inside each other ("call stack exhausted" past that), and at most 1 MB for wasmi's own stack of an app's values.

Why they are needed:

- **A request for memory that cannot be met stops the whole kernel** (see [memory.md](memory.md)). With the memory limit taken out on purpose, a program that asks for 1 GB did exactly that: `Kernel panic: ... the machine is out of memory`. The limits on tables and on the number of memories and tables close the same door.
- **Without fuel, a loop that never ends never comes back.** With fuel taken out on purpose, the test never got past such a loop. Ten million units are about half a second of the processor in a tight loop written by hand (two seconds before the outside crates were built optimized).
- **A script has a budget of its own, ten times as large,** because a program in the box carries it out and every step of the script costs many of the box's steps: five lines of script cost over four million units, one round of a loop about 24 thousand. The number is a stopgap set by measuring. Fuel bounds the steps and not the time: the same budget lasts three to four times as long in one kind of work as in another; see [interpreter.md](interpreter.md).

What the limits do not cover: wasmi's own bookkeeping for an app lives on the kernel's heap and is not counted in the app's memory. A translated program takes room in proportion to its size.

## The three apps in the kernel

All are whole WebAssembly programs written out by hand in `app_box.rs`, with a comment on each group of bytes. No compiler made them. Each has a heading of 8 bytes and then numbered sections, each with its length in front.

- **`ADDING_APP`, 41 bytes.** One function, `add`, that gives back the sum of two numbers. Four sections: the kinds of function, the functions, what the app shows to the outside, the code. The code is 7 bytes: no variables, take the first value, take the second, add, end.
- **`GREETING_APP`, 111 bytes.** It keeps the text "Hello from inside the box" in its memory and asks the kernel to print it. Three sections more: what it asks of the kernel (`kernel`, `print`), its memory (one page), and what the memory holds at the start (the 25 bytes of the text, at address 0). It shows two things to the outside, `memory` and `start`. The code of `start` is 8 bytes: no variables, the number 0, the number 25, call `print`, end.
- **`SHOWING_APP`, 113 bytes.** The greeting app with two things changed: it asks the kernel for `show` instead of `print`, and its text is "Hello from an app in the box", 28 bytes.

## The three runs at startup

`efi_main` runs the three apps after the encryption line.

`box_check()` runs `ADDING_APP` and asks it for 2 + 3:

- `Box: a program of 41 bytes ran inside it and answered 2 + 3 = 5`
- with a wrong answer: `Box: not working, the program inside it answered 2 + 3 = N`
- when the run fails: `Box: not working, because ...` with wasmi's reason.

`box_run(&GREETING_APP)` follows. The line it brings is the app's own, printed by `kernel_print`:

- `App: Hello from inside the box`
- when the run fails: `Box: the app was stopped, because ...` with the reason.

`box_run(&SHOWING_APP)` comes last. It brings no line. Its text appears on the screen, in the box in the middle:

- on the screen: `Hello from an app in the box`, for a few seconds, until the script that runs after the three apps shows its own text there (see [interpreter.md](interpreter.md))
- when the run fails: `Box: the app that shows a text was stopped, because ...` with the reason, and no box is painted.

The kernel carries on whatever the outcome. Nothing depends on these runs yet.

All three run with device signals off, on the firmware's stack, like the encryption check before them. The greeting app goes 15,752 bytes deep of the 124 KB free there (45,776 before the outside crates were built optimized). How long they take was not measured; they do not visibly slow the start.

## Numbers with a point

WebAssembly has numbers with a point, so wasmi carries code for them. The build target computes them in software, without the processor's SSE registers, and the processor refuses SSE instructions (see [encryption.md](encryption.md)). Programs that take square roots, round in four ways, and turn numbers with a point into whole ones and back were run in the box with that refusal on: nothing was refused, and every result matched another engine's bit for bit.

## What was measured

In QEMU. The figures marked "plain" are from before the outside crates were built optimized (see [README.md](README.md)); they are kept because much of the testing was done then.

- **Stack, now:** 15,960 bytes for the adding app and 15,752 for the greeting app, at startup, of the 124 KB free on the firmware's stack.
- **Stack, plain:** 45,776 bytes for the greeting app and for the showing app alike, at startup, of the 124 KB free on the firmware's stack and of a task's 256 KB. (It was 45,408 for the greeting app before the second call came in.) The adding app went 43,112 deep when it was measured, before the print call existed. Larger programs will go deeper; no app bigger than 540 bytes has been run. The interpreter, a program of 762 KB, is got ready at startup without any of it being run, and that went 44,920 bytes deep; see [interpreter.md](interpreter.md).
- **Size:** the kernel's file grew from 2.9 MB to 6.2 MB when the box came, in the plain build. Built as it is now, with everything that has come since, it is 4.0 MB.
- **Speed, plain:** checking and translating a program of 540 bytes took about 5 thousandths of a second. A small counting loop ran about 0.7 million rounds a second, at about 4 units of fuel a round. Ten million units of fuel lasted about 2 seconds.
- **Speed, now:** a tight loop written by hand uses a hundred million units up in 4.3 to 4.8 seconds, where it took 31 to 32: about seven times as fast. The interpreter, a far bigger program, gained more; see [interpreter.md](interpreter.md).
- **Memory:** three rounds of 42 runs took 274 frames in the first round and none after. Two passes over 333 changed programs took none. So nothing is lost from run to run; the heap only never hands frames back (see [memory.md](memory.md)).

## How to test it

The programs for these tests are made by hand, byte by byte, with a short script outside the repository; none of them comes from a compiler. (The interpreter does come from one, and has its own way of being tested; see [interpreter.md](interpreter.md).) Habits that proved their worth:

- **Run every test program in another engine first** and take the expected outcome from there. Node has one built in: `WebAssembly.validate(bytes)` says whether a program follows the rules, and `new WebAssembly.Instance(new WebAssembly.Module(bytes), imports)` runs it, with `imports` holding a `print` that does what the kernel's is meant to do. A hand-made program with a mistake in it is otherwise indistinguishable from a runtime that is wrong. One thing Node cannot judge: the shape of a function. A function written in JavaScript has none, so Node accepts a program that asks for `show` in another shape, or whose `start` takes values, where the kernel refuses it.
- **Change every byte of a good program, one at a time**, and run each changed copy. Most are refused by the check; the rest run and either end or are stopped. None may bring the kernel down.
- **Look at every byte the kernel printed**, not only at the lines. Text meant to do harm shows as bytes that are not plain text, or as a line end that is not the two bytes 13 and 10.
- **A script that waits for `Kernel panic` must look for it at the start of a line.** An app can print those words behind `App: `.

[testing.md](testing.md) lists what was verified.

## Limits

See [open-points.md](open-points.md). In short: an app can ask the kernel for two things only, it runs once from `start` to the end and nothing of a run is kept for the next, every run translates the program again, and the version of wasmi cannot simply be raised.
