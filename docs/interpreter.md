# The interpreter: a program that understands Lua

Code: the folder `interpreter/` (a program of its own, not part of the kernel), `src/interpreter.rs`, `box_accepts` and `box_script` in `src/app_box.rs`, the check and the script's run in `efi_main`, `app_run` in `src/apps.rs`, and the first lines of `run.bat`.

Apps are written as text in the language Lua. The kernel does not understand Lua, and it should not: a program that reads text written by somebody else is a large piece with many places for a mistake. So the understanding is done by a program that itself runs inside the locked box (see [box.md](box.md)), where a mistake in it can harm only the one app it is running. That program is the interpreter.

**Today the kernel carries the interpreter, sees at startup that the box would take it, and has it run one script that is written by hand and kept in the kernel.** A script can ask for two things: to print a line, and to show a text on the screen. After startup it also runs the scripts the model writes on request, one at a time, each once (see [apps.md](apps.md)).

## The words

- A **script** is a program kept as text, as a person would write it: `count = count + 1`.
- An **interpreter** is a program that reads such text and carries it out.
- **Lua** is a small language made to be put inside other programs. Its makers are at PUC-Rio, a university in Rio de Janeiro; their own interpreter is written in C.
- **WebAssembly** is the form of program the box runs; see [box.md](box.md). The interpreter is one such program, 765,037 bytes long.

So three things are stacked: the kernel runs the box, the box runs the interpreter, and the interpreter runs an app's script.

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

`interpreter/src/lib.rs` is the small piece between omnilua and the kernel, about 160 lines.

- **It asks the kernel for two things,** the whole of the system API: `print` of `kernel`, which prints a text as a line, and `show` of `kernel`, which shows a text on the screen.
- **It shows the outside four things:** its `memory`, and three functions.
  - **`room(length)`** makes room for a script of `length` bytes and gives back where in the program's memory the kernel should write it.
  - **`seed(value)`** takes a whole number of 64 bits to start the script's random numbers from. When the kernel calls it before `run`, the script's random numbers start there (`math.randomseed(value)` is run before the script); when it does not, they start where Lua always starts them, so that every run gives the same numbers. The box has no clock and no random numbers of its own, so only the kernel can give a run numbers of its own. It does so for apps made on request (see [apps.md](apps.md)), and not for the script at startup.
  - **`run(length)`** carries out the script that was written there and gives back a number: 0 if the script ran to its end, 1 if not. A script that cannot be carried out to its end, because of a mistake in how it is written or one that turns up while it runs, is reported as a printed line that begins `Lua stopped:`. Either way `run` itself ends in the ordinary way.
- **Lua's own `print` is replaced.** The original writes to a screen that a program in the box does not have. The replacement is seven lines of Lua kept in the program: it joins what it is given and hands the line to the kernel's print. The original puts a tab between two values; this one puts a space, because the kernel prints plain signs only and would show a tab as a dot. So `print(1, 2)` gives `1 2`.
- **`show(value)` is offered to a script,** for the kernel's call that shows a text in the box on the screen (see [box.md](box.md) and [screen.md](screen.md)). The script says only which text; how the box looks is the kernel's business. Like `print`, it turns whatever it is given into text first, so `show(42)` shows `42`; that is four lines of Lua kept in the program, around a function that takes a text and nothing else. **A text longer than 40 bytes is cut at 40** (`LONGEST_SHOWN`), the most the kernel shows; the kernel stops a program that hands it a longer one, so the cut keeps a script from being stopped for it. The cut may fall inside a letter of several bytes, whose bytes the kernel shows as dots anyway. (Until apps were made on request, the text was handed over whole and a longer one stopped the script.)
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
- **The built file holds folder paths of the computer it was built on:** 22 of them, the places of omnilua's source files in cargo's own folder, which the compiler puts into the messages for mistakes that end a program. So the file's bytes, and its length, can differ from one computer to the next, and the 765,037 in these notes is one computer's figure. It is one more reason to keep the built file out of the repository. The kernel's own file holds such paths in the same way.

## How the kernel carries it

`src/interpreter.rs` holds one line that reads the built file in while the kernel is compiled (`include_bytes!`), so the bytes become part of the kernel's own file.

- **The interpreter has to be built before the kernel.** If it was not, the kernel's build stops with `couldn't read ... interpreter.wasm`. `run.bat` builds both in the right order, and stops with `The interpreter could not be built` if the first build fails.
- **A kernel built without rebuilding the interpreter carries the old one.** After changing anything under `interpreter/`, build there first. The byte count in the line at startup tells which one is on board.

## The check at startup

`efi_main` calls `interpreter_check()` after the three small apps:

- `Interpreter: a program of 765037 bytes that understands Lua is on board, and the box accepts it`
- otherwise: `Interpreter: not usable, because ...` with the reason; no script is run then, and the kernel carries on.

`interpreter_check` hands the program to `box_accepts` (see [box.md](box.md)), which gets it ready exactly as an app is got ready for a run, with the same check against WebAssembly's rules, the same limits and the same system API, and then looks for a memory called `memory` and for the functions `room`, `seed` and `run`. None of them is called.

What that check proves and what it does not: the file is a whole WebAssembly program, it fits the box's limits at its start, it asks the kernel for nothing the kernel does not offer, and the three functions are there under their names. Whether they take and give what the kernel expects it does not show; the run of a script, which follows, does.

## Running a script

`script_run(script)` in `interpreter.rs` runs a script: it hands the interpreter's program and the script's text to `box_script` (see [box.md](box.md)), which gets the program ready in the box, asks it for room, writes the script there and tells it to run. Each run starts from nothing: the program is checked and translated again, and nothing of one script is left for the next. `script_run_seeded(script, seed)` does the same with a number for `seed` before the run, and returns the last text this run showed, if any. A stopped run also returns its reason and, for a Lua mistake, the error the interpreter printed. Apps made on request are run with it (see [apps.md](apps.md)).

What comes back:

- **`Ok`** when the script ran to its end. What it printed has come out as `App: ` lines, like any app's text.
- **`the script made a mistake, which is told in the line before`** when the interpreter gave back 1. The line before is the interpreter's own, such as `App: Lua stopped: [string "app"]:2: attempt to index a nil value (local 't')`. The number after the name is the script's line. What the script printed before the mistake stays printed.
- **`all fuel consumed by WebAssembly`** when the script used up its budget.
- **`it printed too many texts`** after 100 printed lines.
- **`it showed too many texts`** at the 21st showing. This is the kernel's own rule for `show`, and a script cannot get round it: `pcall(show, ...)` does not catch it, because it is the whole interpreter that is stopped, not the script inside it. (The kernel's other rule for `show`, which stops a program that hands it a text of more than 40 bytes, is not reached from a script any more: the interpreter cuts such a text first.)
- **`wasm `unreachable` instruction executed`** when the interpreter itself gave up, which is what happens when it runs out of memory.
- **`the script is too long`** for a script of more than 32 KB; nothing is started then.

What a script can count on:

- **Lua 5.4,** with `string`, `table` and `math`. `io`, `os`, `require`, `debug`, coroutines and `utf8` are not there (their names are `nil`); `load` is.
- **`print`,** with any number of values, joined by a space. A line longer than 200 bytes is cut at 200 by the interpreter. Every byte that is not a plain sign comes out as a dot: a tab inside a text, a letter with an accent (two dots, because it is two bytes).
- **`say(text)`,** the function `print` is built on, which hands one text to the kernel.
- **`show(value)`,** which puts one line of at most 40 bytes into the box on the screen; a longer text is cut at 40. Each showing wipes out the one before; the last one stays after the script has ended. Bytes are counted, not letters: twenty letters with an accent fill the 40, and each comes out as two dots. On a machine without a usable screen nothing is shown and the script carries on.
- **`math.random`,** whose numbers start from the same place at every run, unless the kernel gave the run a seed: it does for apps made on request.
- **Both kinds of line end** in the script's text.
- **A text with bytes that are no letters at all cannot be printed.** The piece between omnilua and this program wants proper text, and the script is stopped with `Lua stopped: string is not valid UTF-8`.

## The script at startup

`GREETING_SCRIPT` in `interpreter.rs` is a whole app as a script, six lines written by hand:

```lua
local greeting = "Hello from a Lua script"
for count = 1, 3 do
  greeting = greeting .. "!"
end
print(greeting)
show(greeting)
```

`efi_main` runs it right after the check, if the check passed:

- in the terminal: `App: Hello from a Lua script!!!`
- on the screen, in the box below the panel of apps, showing `Hello from a Lua script!!!`, painted over the text the hand-made showing app put there a few seconds earlier
- when the run fails: `Interpreter: the script was stopped, because ...` with the reason.

It is a demonstration, like the three small apps before it. Nothing depends on it. If the script is stopped before its last line, the box keeps the hand-made app's text.

## The budget for a script

A script is held to the box's limits like any app (1 MB of memory, 100 printed lines), with one difference: its fuel. `SCRIPT_FUEL` in `app_box.rs` is 100,000,000 units, ten times an app's.

- **Why more:** every step of a script costs the interpreter many of the box's steps. The five-line greeting costs about 4.4 million units, small scripts 4 to 11 million, one round of a loop about 24 thousand.
- **Why not far more:** fuel counts steps, and the same number of units lasts very different times. Measured with scripts that never end, each given 100 million units. The first column of seconds is today's kernel; the second is from before the outside crates were built optimized, when the number was chosen:

| The script's work | Seconds now | Seconds, plain |
| --- | --- | --- |
| an empty loop, counting, calling a function | 0.4 to 0.5 | about 2 |
| sorting a list | 0.5 | 5 |
| turning numbers into text | 0.7 | 13 |
| a pattern that is hard to match | 0.8 | 15 |
| making small lists and dropping them | 1.0 | 17 |
| repeating or joining texts | 1.3 to 1.4 | 23 to 24 |

- So with this budget a bad script holds the machine for about a second and a half at most. In the plain build it was half a minute, and ten times the budget, which was the first try, would have been minutes. Now ten times the budget would be 4 to 14 seconds; the number has not been raised.
- **What the budget stops that is harmless:** a loop of more than about four thousand rounds, `fib(20)`, the Tower of Hanoi with ten discs. The number is a stopgap until something better bounds a script's time.
- **One kind of script is not ended by the fuel at all:** one that fills its memory. It is ended by the memory limit after 1.6 to 1.8 seconds, having used 92 million units (29 to 43 seconds in the plain build).

## What was measured

In QEMU. The times vary with how busy the test computer is, so the kernel from before a change and the one after it are booted turn about.

- **Time:** the check adds 0.16 to 0.33 seconds to a start and the script 0.26 to 0.49 more, both with device signals off. Most of the script's time is getting the interpreter ready again. Showing a text adds a few hundredths of a second.
- **Time, plain:** before the outside crates were built optimized the check took 1.1 to 3.3 seconds and the script 2.6 to 6.8.
- **Stack:** 16,744 bytes deep for the check and 17,384 while a script runs, at their place in the startup, of the 124 KB free on the firmware's stack; the second figure was the same for four scripts, among them calls without end and a flood of prints. Plain, the two figures were 44,920 and 54,824.
- **Memory:** the first check takes 556 frames (2.2 MB) for the kernel's heap, a second and a third none. Twenty-eight well-behaved scripts in a row took 25 frames more. Fourteen that should be stopped took about 514, 513 of them at the script with calls without end, the only one that made the interpreter's memory grow far. The heap keeps them for later use and never hands frames back (see [memory.md](memory.md)).
- **A script's own memory:** every small script ended with 384 KB of the app's 1 MB in use (measured in a trial's copy).
- **Size:** the interpreter adds its own 0.76 MB to the kernel's file, which is 4.0 MB.
- The kernel starts with 80 MB of memory and not with 64, where the firmware refuses to load a file of this size.

## What trials showed beyond that

None of this is in the kernel. It was measured in a copy of the kernel, in the plain build:

- **With the interpreter checked once and kept** for several scripts, each started from that one check in a store of its own: a later small script took half the time and half the fuel, because translating is paid once.
- **Going on after the fuel has run out, a trap.** wasmi can take a run up again where it stopped for lack of fuel (`call_resumable`, `resume`), which would let the kernel hand out fuel in slices and look at its clock in between. With wasmi translating each function at its first use, which is its default and what the box uses, **that stopped the whole kernel with a panic inside wasmi** in the first script tried. With everything translated up front (`CompilationMode::Eager`) nine runs went through and a loop without end was stopped by the clock. Do not use `resume` with the default setting.
- **Where scripts run today the timer does not tick,** so a limit by the clock could not work there whatever wasmi did.

## How to test it

- **Build both, in order, before every test boot**, and see that the kernel's file holds exactly the interpreter that was just built. A test that builds only the kernel tests a stale interpreter without saying so.
- **Scripts are tried with a temporary file** that calls `script_run` for each one at the place where the kernel runs its own script, and prints how each ended. It is taken out again afterwards.
- **What a script should print is worked out by hand,** and where the language is the same, compared with what a second interpreter printed for the same script in a trial (one written from scratch by somebody else). No reference interpreter for Lua is installed.
- **To try another file in the interpreter's place**, build the kernel in a copy of the project with that file put where the built interpreter belongs. That is how the refusals at the check were tested.
- **To try a program that lies to the kernel,** make one by hand that shows `memory`, `room` and `run`, and hand it to `box_script` directly. Fifteen such programs of 71 to 98 bytes were made by a script, and each was checked in another engine first, as [box.md](box.md) describes.
- **A WebAssembly file can be looked at without running it**: a short script that walks its sections tells what it asks for, what it shows, and how much memory it wants at its start.

[testing.md](testing.md) lists what was verified.

## Limits

See [open-points.md](open-points.md). In short: scripts run at startup and when the model has written one, and a script can only print lines and show one line of text; fuel is all that ends a bad script, and it does not bound time; the interpreter is got ready anew for every script, which is most of what a small script costs; the kernel learns that a script made a mistake but not which; the outside code is young and unaudited.
