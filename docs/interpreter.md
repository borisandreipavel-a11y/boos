# The interpreter: a program that understands Lua

Code: the folder `interpreter/` (a program of its own, not part of the kernel), `src/interpreter.rs`, `box_accepts` in `src/app_box.rs`, the check in `efi_main`, and the first lines of `run.bat`.

Apps are going to be written as text in the language Lua. The kernel does not understand Lua, and it should not: a program that reads text written by somebody else is a large piece with many places for a mistake. So the understanding is done by a program that itself runs inside the locked box (see [box.md](box.md)), where a mistake in it can harm only the one app it is running. That program is the interpreter.

**Today the kernel only carries the interpreter and sees at startup that the box would take it. No script is run yet.** What is written below about scripts running comes from trials in a copy of the kernel and is marked as such.

## The words

- A **script** is a program kept as text, as a person would write it: `count = count + 1`.
- An **interpreter** is a program that reads such text and carries it out.
- **Lua** is a small language made to be put inside other programs. Its makers are at PUC-Rio, a university in Rio de Janeiro; their own interpreter is written in C.
- **WebAssembly** is the form of program the box runs; see [box.md](box.md). The interpreter is one such program, 761,879 bytes long.

So three things are stacked: the kernel runs the box, the box runs the interpreter, and the interpreter will run an app's script.

## The outside code

`interpreter/Cargo.toml` names one crate, **`omnilua` 0.7.1**, with its default features off. `interpreter/Cargo.lock` lists eight crates for it, all 0.7.1, all from the same project, and all eight are compiled: `omnilua`, `lua-vm`, `lua-gc`, `lua-types`, `lua-parse`, `lua-lex`, `lua-code`, `lua-stdlib`. They are fetched from crates.io on a first build, about 0.8 MB. None has a build script and none is a macro crate, so no copy in `vendor/` was needed.

- **What it is, in its makers' words:** "an AI-assisted port (a derivative work, a translation from C to Rust) of the PUC-Rio reference implementation of Lua 5.4.7". It runs Lua 5.4 unless told otherwise.
- **With the default features off** the parts of Lua that reach outside the program are left out: files (`io`), the clock and the system (`os`), loading other files (`require`), `debug`, coroutines, `utf8`. What stays is the language itself with its helpers for text (`string`), lists (`table`) and arithmetic (`math`). A script that uses a part that was left out is stopped with a plain message, such as `attempt to index a nil value (global 'os')`.
- **The version is fixed** (`=0.7.1`), so that a build always uses the code that was tested.
- **Licence:** MIT, for the port and for Lua itself. Two notices have to be kept with copies of it, and the kernel's file holds a copy, so they are repeated here: "Copyright (c) 2026 lua-rs-port contributors" (from the project's `LICENSE`) and "Copyright (c) 1994-2024 Lua.org, PUC-Rio." (from its `NOTICE`, for the Lua it was translated from). Both files are in the project's repository, `github.com/ianm199/omnilua`; the crate files themselves hold neither.
- **Security advisories**, looked up on 2026-11-18: rustsec.org has no page for any of the eight crates, and the project's own page lists none. For code this young that says little.

Why this one, from a comparison and a trial made on 2026-11-18:

- The test for any outside code here: pure Rust, no build script that must run, no macro crate (see `vendor/README.md`). Most interpreters for script languages that are written in Rust fail it on macro crates. Three for Lua pass.
- **`omnilua`** ran every ordinary small script it was given in the trial, and runs today's Lua (5.4). Against it: its first release was in June 2026, it is kept by one account, nobody outside has checked it, and it had no release between July and November 2026.
- **`rilua` 0.1.27** passes too and makes a smaller program (432 KB), written from scratch by one person. It runs Lua 5.1, the language as it was in 2006: a script that uses `//` or `table.unpack` is stopped as a mistake in writing.
- **`luna-core` 4.0.2** asks for the time of day when it starts, which a program in the box does not have, and stops at once.
- Writing an interpreter by hand for a small part of Lua was the other way. Six ordinary small scripts used closures, tables with methods, patterns in text and `string.format`: a part that could run them would be most of Lua.

## The program

`interpreter/src/lib.rs` is the small piece between omnilua and the kernel, about 90 lines.

- **It asks the kernel for one thing:** `print` of `kernel`, the system API's call for printing a text.
- **It shows the outside three things:** its `memory`, and two functions.
  - **`room(length)`** makes room for a script of `length` bytes and gives back where in the program's memory the kernel should write it.
  - **`run(length)`** carries out the script that was written there. A script that cannot be carried out to its end, because of a mistake in how it is written or one that turns up while it runs, is reported as a printed line that begins `Lua stopped:`, and `run` ends in the ordinary way.
- **Lua's own `print` is replaced.** The original writes to a screen that a program in the box does not have. The replacement is seven lines of Lua kept in the program: it joins what it is given with tabs, as the original does, and hands the line to the kernel's print.
- A printed line is cut at 200 bytes, the longest the kernel takes; a longer one would get the whole program stopped.

## How it is built

The interpreter is built for WebAssembly, not for the machine the kernel runs on, so it cannot be part of the kernel's own build. It is a second, separate build:

```
cd interpreter
cargo build --release
```

That makes `interpreter/target/wasm32-unknown-unknown/release/interpreter.wasm`. `run.bat` does it before it builds the kernel.

- **The building computer's Rust needs the WebAssembly target**, once: `rustup target add wasm32-unknown-unknown`. It is library files, 23 MB to download.
- **Build it from inside its folder.** Its settings are in `interpreter/.cargo/config.toml`, and cargo reads such a file only when it is started from that folder or below. Started from the project's root with `--manifest-path interpreter/Cargo.toml`, cargo uses the kernel's settings and stops: `cannot produce cdylib for interpreter ... as the target x86_64-unknown-uefi does not support these crate types`. From inside the folder cargo reads both files, and the interpreter's wins where they differ: the build was watched to get the WebAssembly target and none of the kernel's five settings for the encryption crates.
- **The stack setting is needed.** A WebAssembly program made from Rust sets aside 1 MB of its memory as its stack, and the box allows an app 1 MB in all. Built that way a program asks for 17 pages at its start and the box refuses it. `-C link-arg=-zstack-size=262144` makes the stack 256 KB; the interpreter then asks for 5 pages, 320 KB.
- **It is built small rather than fast** (`opt-level = "s"`, one unit, `lto`, no unwinding), because the box checks the whole file each time it gets the interpreter ready.
- **No program made along the way is run**, and the linker for WebAssembly, `wasm-ld`, comes with Rust.
- **The built file is not in the repository.** It is build output, like the kernel's own file. Two builds of the same source in two different folders gave the same bytes, and so did the source with the other kind of line end; the piece of Lua in the source is written line by line with its line ends spelt out for that reason.
- **The built file holds folder paths of the computer it was built on:** 22 of them, the places of omnilua's source files in cargo's own folder, which the compiler puts into the messages for mistakes that end a program. So the file's bytes, and its length, can differ from one computer to the next, and the 761,879 in these notes is one computer's figure. It is one more reason to keep the built file out of the repository. The kernel's own file holds such paths in the same way.

## How the kernel carries it

`src/interpreter.rs` holds one line that reads the built file in while the kernel is compiled (`include_bytes!`), so the bytes become part of the kernel's own file.

- **The interpreter has to be built before the kernel.** If it was not, the kernel's build stops with `couldn't read ... interpreter.wasm`. `run.bat` builds both in the right order, and stops with `The interpreter could not be built` if the first build fails.
- **A kernel built without rebuilding the interpreter carries the old one.** After changing anything under `interpreter/`, build there first. The byte count in the line at startup tells which one is on board.

## The check at startup

`efi_main` calls `interpreter_check()` after the three small apps:

- `Interpreter: a program of 761879 bytes that understands Lua is on board, and the box accepts it`
- otherwise: `Interpreter: not usable, because ...` with the reason, and the kernel carries on.

`interpreter_check` hands the program to `box_accepts` (see [box.md](box.md)), which gets it ready exactly as an app is got ready for a run, with the same check against WebAssembly's rules, the same limits and the same system API, and then looks for a memory called `memory` and for the functions `room` and `run`. Neither function is called.

What that check proves and what it does not: the file is a whole WebAssembly program, it fits the box's limits at its start, it asks the kernel for nothing the kernel does not offer, and the two functions are there under their names. Whether they take and give what the kernel expects, and whether a script runs, it does not show.

## What was measured

In QEMU, in the plain debug build:

- **Time:** the check adds about 1.2 to 1.4 seconds to a start, with device signals off.
- **Stack:** 44,920 bytes deep at its place in the startup, of the 124 KB free on the firmware's stack.
- **Memory:** the first check took 556 frames (2.2 MB) for the kernel's heap, a second and a third none. The heap keeps them for later use and never hands frames back (see [memory.md](memory.md)).
- **Fuel:** none. Getting the interpreter ready runs none of it.
- **Size:** the kernel's file grew from 6.3 MB to 7.1 MB. "Free memory" reads the same as before on the usual machine.
- The kernel still starts with 96 MB of memory.

## What trials showed about running scripts

None of this is in the kernel yet. It was measured in a copy of the kernel that handed scripts to this same program through `room` and `run`, in the plain debug build:

- **Scripts run.** Six ordinary small scripts (closures, tables with methods, patterns, sorting with a function, `string.format`, `pcall`) ran as written. A mistake in writing, a mistake while running and a call of `error` each came back as a `Lua stopped:` line with the line number.
- **Time:** a script of five lines took about 2.7 seconds from getting the interpreter ready to its end, at startup. With the outside crates built optimized, a setting that is not in use, about a tenth of a second.
- **Fuel:** five lines cost about 4.4 million units, a small script 6 to 10 million, a loop about 24 thousand units a round. The box's ten million units, set for apps written by hand, are used up by a few hundred rounds of a loop. A program that runs through the interpreter needs a budget of its own.
- **Fuel is a poor clock.** A script that fills memory without end kept the processor for many seconds on less fuel than a harmless loop uses in one.
- **Memory:** every small script ended with 384 KB of the app's memory in use, inside the box's 1 MB.
- **Stack:** about 56 KB deep in the kernel while a script runs, the same on the firmware's stack.
- **Going on after the fuel has run out, a trap.** wasmi can take a run up again where it stopped for lack of fuel (`call_resumable`, `resume`), which would let the kernel hand out fuel in slices and look at its clock in between. With wasmi translating each function at its first use, which is its default and what the box uses, **that stopped the whole kernel with a panic inside wasmi** in the first script tried. With everything translated up front (`CompilationMode::Eager`) nine runs went through and a loop without end was stopped by the clock. Do not use `resume` with the default setting.

## How to test it

- **Build both, in order, before every test boot**, and see that the kernel's file holds exactly the interpreter that was just built. A test that builds only the kernel tests a stale interpreter without saying so.
- **To try another file in the interpreter's place**, build the kernel in a copy of the project with that file put where the built interpreter belongs. That is how the refusals were tested: a program that asks for too much memory, half a file, an empty file, each of the three names changed, a call the kernel does not offer.
- **A WebAssembly file can be looked at without running it**: a short script that walks its sections tells what it asks for, what it shows, and how much memory it wants at its start.

[testing.md](testing.md) lists what was verified.

## Limits

See [open-points.md](open-points.md). In short: no script runs yet; the interpreter is checked anew at every start, which costs over a second; a script will need a fuel budget of its own, and fuel does not bound time; the outside code is young and unaudited.
