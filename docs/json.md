# JSON: making it and reading it

Code: `src/json.rs`, `src/json_values.rs`, and the check in `efi_main`.

JSON is the form in which many services on the internet send and expect their data. The kernel has to speak it to ask a model for anything. It is done with code written for this kernel, about 400 lines with their comments, and no outside crate. That code does two things and no more: it writes a text the JSON way, and it finds one text in a piece of JSON.

**One thing uses it:** the question to the model is written with it, and the provider's answer is read with it (see [model.md](model.md)). A check at startup shows that it works.

## The words

- **JSON** is text. A **value** in it is one of six things: a text in double quotes (`"hello"`), a number, one of the words `true`, `false` and `null`, a **list** of values in square brackets (`[1, 2]`), or a **set of named values** in curly brackets (`{"name": "value"}`).
- Inside a text some signs cannot stand as they are and are written with a backslash in front: `\"` for a quote, `\\` for a backslash, `\n` for a line end, and so on. Any sign can also be written as `\u` and four digits that give its number, such as `é` for an é. A sign whose number does not fit in four digits is written as two such pieces, a first half and a second half (a **surrogate pair**).
- A **path** says where in a piece of JSON something lies: into the thing called `choices`, into its first place, into the thing called `message`, into the thing called `content`.

## Making

`json_text(text)` gives the text as JSON writes it: in double quotes, with `"` and `\` written as `\"` and `\\`, the line end, the return, the tab and two older control signs written as `\n`, `\r`, `\t`, `\b` and `\f`, and every other sign below the space as `\u` and four digits. All other signs go in as they are, letters with accents and signs of other scripts among them.

That is the only piece of making there is. A whole request is put together by writing its fixed parts as they are and each changing text through `json_text`.

## Reading

`json_find_text(json, path)` finds one text in a piece of JSON and gives it back as plain text, with every backslash form undone. The path is a list of steps, each `Step::Name("...")` or `Step::Place(n)`, where the first place is 0.

What comes back when there is no text to give:

- `it is not sound JSON`: the piece is broken, cut off, or not JSON at all, such as a page of a web site sent in place of an answer.
- `it has no such part`: a name on the path is not there, a list is too short, or a step leads into something that is neither a list nor a set of names.
- `that part of it is not a text`: what lies at the end of the path is a number, a list, `null` or anything else that is not a text.
- `a text in it is not made of proper signs`: the bytes between a text's quotes are not proper text (UTF-8).

**The JSON comes from outside the kernel, so nothing about it is taken on trust.** It is taken as bytes, which may be anything at all.

- Every byte is reached through `get`, which gives nothing where there is no byte instead of stopping the kernel.
- No function here calls itself. A list or a set of names that is passed over is passed by counting brackets, so brackets nested ten thousand deep cost no more of the stack than two. This matters because nothing notices a stack that overflows.
- The text that is handed out is whatever the other side sent. It has to be cleaned like any text from outside before it is printed or shown (see `plain_text` in `page.rs`).

The rules, where JSON leaves a choice or the kernel is stricter or laxer than others:

- **A name counts only where the path looks for it:** not inside a text, and not one level further in.
- **Names are compared after their backslash forms are undone,** so `"content"` is `content`.
- **Of two things with the same name, the first is taken.** (Python's reader takes the last.)
- **A half of a surrogate pair that stands alone** becomes the sign for "unknown" (U+FFFD), and the text is still handed out.
- **A control sign that stands in the text as it is,** not written with a backslash, makes the piece unsound. In a text that is only passed over it is not noticed.
- **A text is handed out only if what stands behind it closes properly:** every bracket that was open is closed, every text has its closing quote, and nothing but spaces follows. An answer that was cut off, or damaged so that a text ends too early, is turned away whole.
- **This is not a full check of the JSON.** In the parts that are passed over, commas, colons and the spelling of numbers and words are not looked at, and a square bracket closes a curly one. So the kernel hands out the right text from some pieces that a strict reader refuses. It never handed out a text from the wrong place, in any case tried.

## What is left out

Numbers, `true`, `false` and `null` cannot be read as values, only passed over. There is no way to walk through a list whose length is not known, to ask whether a name is there without asking for its text, or to build a list or a set of names other than by writing the brackets by hand. Each can be added when something needs it.

## The check at startup

`efi_main` calls `json_check()` after the interpreter's lines:

- `JSON: 13 of 13 checks of making and reading it are right`
- otherwise: `JSON: not to be trusted here, only N of 13 checks of making and reading it are right`, and the kernel carries on.

The thirteen: two texts made, one of them with every kind of awkward sign; three texts found in an answer of the shape a model's answer has; the reason found in a refusal; every backslash form undone; a piece in which the name looked for also stands where it must not count, a name that only ends alike stands in front of it, and a text that is passed over holds brackets; a part that is not there, a part that is not a text, a piece cut off, and a whole piece with one closing bracket too many behind it; and a text made here and read back here.

**The values it is held against are in `json_values.rs`, and that file is made by a script, not written by hand.** The script takes the expected values from Python's own JSON code, which is another reader and writer than the kernel's. Reading back what the kernel itself wrote would let two wrong halves agree with each other; only the last of the thirteen checks does that. The script is not in the repository. To make the file anew, write each piece of JSON, let another JSON reader say what it holds and how it would write the two texts, and put those in as the constants.

The answer of a model in that file is made up from the names of its parts as the provider's documentation lists them. It is not a real answer: the documentation shows none.

## How to test it

- **Test inside the kernel, in QEMU.** Building the file for the test computer and running it there would be quicker, and is not possible: the computer refuses to run a program that was built a moment ago (see `vendor/README.md`).
- **Keep the cases in a file of bytes** that a script makes and a temporary piece of the kernel reads in with `include_bytes!`. JSON is full of quotes and backslashes; written by hand into Rust text or into a command line it gets mangled, and the test then tests something else.
- **Use another JSON reader as the judge** for pieces it made itself: the kernel must give exactly what it gives. Python's is on most computers.
- **Feed it broken pieces as well:** an answer cut off at every byte, every byte of it changed in three ways, bytes at random, brackets nested ten thousand deep, a text of a million signs. For these there is one rule: the kernel must not stop.
- **Count what the kernel accepts and the other reader refuses,** and look at what it handed out. It must be the right text every time.

[testing.md](testing.md) lists what was verified.

## Limits

See [open-points.md](open-points.md). In short: only texts can be read; the parts that are passed over are not checked; a text is copied whole, however long.
