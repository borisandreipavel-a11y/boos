# Pictures: a picture file turned into dots

Code: the folder `pictures/`, a crate of this project's own: `src/lib.rs` (what it offers, its limits, its reasons), `src/png.rs` (PNG pictures), `src/unpack.rs` (unpacking: zlib and DEFLATE), `src/shrink.rs` (shrinking to fit a room), `src/check.rs` (the two check values). Its tests: `src/tests.rs`, `tests/memory.rs` and `test-data/`, run by `test-tools/test_pictures.py` (see "How it is tested" below).

It reads a PNG picture from the bytes of its file and gives back its dots, shrunk to fit a room of a given size, ready to paint. The kernel uses it to show kept PNG pictures in the frame beside the panel of apps (see "In the kernel" below, and "Pictures" in [screen.md](screen.md)).

## The words

- **Dots** are what the screen shows (pixels). A picture here is a grid of dots, four bytes each: red, green, blue, and **alpha**, how much the dot covers what lies behind it, from 0 (not at all) to 255 (wholly).
- **Packed** bytes are bytes made smaller with DEFLATE; **unpacking** turns them back into the bytes they were. A PNG's dots are packed so, and so are most streams of a PDF and the parts of Word and Excel files.
- A **sample** is one number of a dot as the file keeps it: a grey, a red, an alpha, or the number of a palette's colour.
- A **room** is the size, in dots, that a picture must fit into: for the kernel, the frame beside the panel of apps.

## Why a crate of its own

- **To run fast.** The kernel's own code is built the plain way, and the outside crates and `password-key/` are built to run fast (`opt-level = 2` in the kernel's `Cargo.toml`); built plain they were 2 to 25 times slower. Reading a picture is heavy work of the same kind, so it lives in a crate of its own, as `password-key/` does. The checks for a number too large for its type stay on.
- **It uses no other crate**, has no build script and is not a macro crate. It needs `core` and `alloc` only (`#![no_std]`), and whole numbers only: no arithmetic with a point, which this target does in software, and nothing that could use the processor's SSE registers, which the kernel refuses.
- **Nothing in it may stop the kernel.** Every byte of a picture comes from outside, and may be damaged or made to do harm. So:
  - it has no unsafe code (`#![forbid(unsafe_code)]`);
  - clippy turns into an error any indexing that could fail, `unwrap`, `expect`, `panic!` and the like (the list is at the top of `src/lib.rs`); reads go through `get`, which can only come back empty;
  - every size is checked before memory is set aside for it (see "Memory" below);
  - nothing large is put on the stack, and no function calls itself, since the kernel's main loop runs on the firmware's stack of 128 KB, where nothing notices an overflow (see [memory.md](memory.md)). The largest lists on the stack are 318 bytes of code lengths and 288 of the fixed code's.
  A picture it cannot read is turned away with the reason in plain words (`Refusal`). A mistake in its code that the checks did not stop would still end in a stop of the kernel, the red screen, through Rust's own checks, never in a write outside its memory: that is what the tests that feed it damaged files are for.

## What it offers

- **`png_head(file)`** reads the signature and the head only, and gives the picture's width and height in dots, its depth and its kind of colour, and whether it is interlaced: for saying how large a picture is without reading it all.
- **`png_picture(file, room_width, room_height, &limits)`** reads the whole picture and gives a `Picture`: its width and height as shown, and its dots, row after row from the top, four bytes each. The colours are not mixed with any background, so that the same dots can be painted over another look's colour without the file being read again. Or it gives a `Refusal`.
- **`fitted_size(width, height, room_width, room_height)`**: the size a picture is shown at (see "Shrinking" below).
- **`Limits`**, given by the caller, who alone knows how much memory there is: `dots_most`, the most dots a picture may have; `side_most`, the most on either side; `interlaced_dots_most`, the most an interlaced picture may have, since such a picture is put together whole before it is shrunk.
- **`Refusal`** and **`because()`**, the reason in words to stand after "because": `it does not begin as a PNG picture does`; `the file ends before the picture does`; `it is damaged: ...`; `it holds a part I cannot read, "ABCD"`; `it is 30000 by 30000 dots, more than I show`; `there is no room to show it`.

## PNG

What it follows: RFC 2083 (PNG 1.0), the text the W3C's later editions grew from. The third edition (a W3C Recommendation of 24 June 2025) still has only the four parts below that a reader must know; the rest, its animation among them, may be passed over, and then "a non-animated PNG decoder will ignore the ancillary APNG-specific chunks and display the static image".

- **The file** begins with the bytes 137 80 78 71 13 10 26 10, and is then a row of parts ("chunks"): a length of at most 2^31 - 1, a name of four letters, the data, and a CRC-32 of the name and the data. A part whose name begins with a small letter may be passed over; every other part a reader must know: IHDR (the head), PLTE (a palette), IDAT (the packed dots) and IEND (the end). Anything after the end part is not read.
- **What is checked in every part:** that it is whole, that its check value fits, and that its name is four letters. A part whose name begins with a capital and that is none of the four is turned down by its name.
- **The head** comes first, 13 bytes: width and height, each from 1 to 2^31 - 1; the depth and the kind of colour, in the pairs RFC 2083 allows (grey: 1, 2, 4, 8, 16 bits; red-green-blue: 8, 16; a palette's colours: 1, 2, 4, 8; grey with alpha: 8, 16; red-green-blue with alpha: 8, 16); packing 0 (deflate); filtering 0; interlacing 0 (none) or 1 (Adam7).
- **The order:** one head, first; at most one palette, before the dots and before the transparency part, only where a palette may be (never with grey), and needed with a palette's colours, with at most as many colours as the depth can name; the transparency part (tRNS) before the dots, after the palette, at most once, two bytes for grey, six for red-green-blue, no more than the palette's colours for a palette, and not where every dot has its own alpha; the IDAT parts in one run, their boundaries anywhere and some of them empty if so made; the end part last, empty.
- **The packed dots** are the IDAT parts' data one after another, unpacked as one zlib stream (see "Unpacking" below). Their bytes are rows: for each row a filter byte and the row's bytes, a row of dots of fewer than eight bits packed several to a byte, the leftmost in the highest bits, each row beginning on a byte. Exactly as many bytes must come as the head's size says; more or fewer is damage.
- **Filters** (RFC 2083, 6): each byte was stored as its difference from a guess made from the byte a whole dot to its left (at least one byte), the byte above it, and the one above that left one, all counting as 0 left of the row and above the first row of each pass: none, the left byte, the byte above, their average rounded down, or Paeth's guess, whose ties go to the left byte, then the one above. A filter byte above 4 is damage.
- **Adam7** sends an interlaced picture in seven passes, each laid out as a small picture of its own, with its own rows and filters; a pass a small picture has no dots of is left out with no bytes at all. Where each pass begins and steps, across and down: (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2), read from RFC 2083's pattern (2.6).
- **Four bytes a dot:** samples of 1, 2 or 4 bits are stretched to the full range (times 255 and divided by the largest sample); samples of 16 bits keep their high byte, as RFC 2083 allows (10.4); grey becomes equal red, green and blue; a palette's colour is looked up, and a dot that names a colour the palette does not have is damage; its alpha is the transparency part's for that colour, or 255. For grey and red-green-blue, a dot whose samples are those of the transparency part is see-through (alpha 0); the match is made on the samples as they are, before they are cut to 8 bits.
- **Not applied:** gamma (gAMA), the colour of the screen it was made on (cHRM, iCCP, sRGB, cICP) and the other parts that may be passed over. The colours are shown as they are written.

## Unpacking

What it follows: RFC 1950 (zlib) and RFC 1951 (DEFLATE). Bytes come from a `Source` one at a time and go to a `Sink` a piece at a time, so the whole of neither is ever held.

- **The zlib head** must check (the two bytes, read as one number, divide by 31), name deflate (8), a window of at most 32 KB, and no preset dictionary, which a PNG never has. At the end, the Adler-32 of everything unpacked must fit. Bytes after the stream are not read.
- **Blocks** (RFC 1951, 3.2.3): stored (its bytes as they are, after a length and that length with every bit turned over, which must agree), packed with the fixed codes, or packed with codes the block gives itself. The fourth kind does not exist and is damage.
- **Codes** are built from lengths alone (3.2.2): the codes of each length are consecutive numbers after those of the shorter lengths. A set of lengths with more codes than there is room for is damage; one with fewer is taken, since RFC 1951 allows a single distance code of one bit, and none at all. A code of at most nine bits is found with one look in a table of 512 entries; a longer one bit by bit. So building a code costs at most a few hundred steps, however small the block: a file of many tiny blocks, each with codes of its own, does not pay for a large table each time. How long a whole file takes was not measured.
- **The fixed codes** (3.2.6): literals 0 to 143 in 8 bits, 144 to 255 in 9, 256 to 279 in 7, 280 to 287 in 8; distances in 5.
- **A block's own codes** (3.2.7): 257 to 286 literal and length codes (more is damage), 1 to 32 distance codes, their lengths given with a code of their own, in the order 16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15; 16 repeats the length before 3 to 6 times (there must be one before), 17 and 18 give 3 to 10 and 11 to 138 lengths of 0; a repeat may run on from the literal lengths into the distance lengths, but not past the last.
- **Copies** (3.2.5): lengths 3 to 258 and distances 1 to 32,768, from the tables of RFC 1951, written out in `unpack.rs`. Codes 286 and 287, and distance codes 30 and 31, have a place in the codes but never stand for anything: damage if they come. A copy from before the first byte is damage. The last 32 KB unpacked are always kept for copies to reach into; the bytes before them are handed on in pieces of 64 KB.

## Shrinking

- **The size shown** (`fitted_size`): a picture that fits the room is shown as it is, and nothing is made larger. Otherwise it is made as large as fits, keeping its shape: if it is wider than the room's shape it fills the room's width, and its height is its height times the room's width divided by its width, rounded to the nearest dot; if it is taller, the other way round; a side is at least one dot. A photo of 1600 by 1200 dots in a page of the frame, 554 by 426 dots, is shown at 554 by 416; with a caption under it, in 554 by 406, at 541 by 406.
- **A picture that fits** passes through unchanged, dot for dot.
- **A shrunk picture:** dot x of a row falls on shown column x times the shown width divided by the width, rounded down, and row y on shown row y times the shown height divided by the height, rounded down. Each shown dot is the average of the dots that fall on it: its alpha the average of their alphas; its colour the average of their colours, each counted as much as its alpha, so that see-through dots do not darken their neighbours. Both are rounded to the nearest; a shown dot that only see-through dots fell on is black and see-through. Rows are summed as they come, one shown row at a time.

## Memory

Everything set aside for a picture is bounded before it is set aside: the picture's size, from its head, against the caller's limits, before anything is unpacked.

- the shown picture: its dots, four bytes each, never more than the picture's own;
- the sums of the shown row being summed: 40 bytes for each shown column;
- two rows of the file's bytes, each at most the picture's width times 8 bytes, and one row of dots, four bytes each;
- an interlaced picture whole, four bytes a dot, bounded by `interlaced_dots_most`;
- for unpacking: 96 KB of unpacked bytes and three small code tables;
- the file itself, which is the caller's.

**Measured** (`tests/memory.rs`, on the computer the project is built on, with a counting allocator: the most held at once beyond what was held before):

| Picture | Shown at, in a room of 554 by 400 | Held at most | Of which the shown picture |
| --- | --- | --- | --- |
| A head that says 30,000 by 30,000 | turned down for its size | 0 bytes | |
| 3000 by 2000 dots | 554 by 369 | 973,421 bytes | 817,704 |
| 554 by 400 dots | as it is | 995,497 bytes | 886,400 |
| 16,000 by 100 dots | 554 by 3 | 292,365 bytes | 6,648 |

So a picture that is not interlaced costs, whatever its size, about the shown picture and a few hundred KB more. An interlaced picture is held whole first, four bytes a dot, up to `interlaced_dots_most`: one of 1000 by 1000 dots holds 4 MB more (worked out; no interlaced picture was measured). The kernel's heap gives each piece a power of two in size and never gives frames back (see [memory.md](memory.md)): the shown picture of the usual frame takes a piece of 1 MB.

How long a picture takes to read where the kernel runs: see "In the kernel" below.

## In the kernel

Code: `file_picture` in `src/files.rs`, which reads a kept PNG file whole from the room for files and calls `png_picture` with the room a page of the frame has; the layout and painting in `src/drawing.rs` (see "Pictures" in [screen.md](screen.md)).

- **The limits** (`PICTURE_LIMITS` in `files.rs`): at most 9,000,000 dots in all, enough for a screenshot of 3840 by 2160 (8,294,400); at most 16,384 on either side; and at most 4,000,000 in an interlaced picture, enough for 2560 by 1440, which is held whole first, four bytes a dot, so 16 MB. The file itself is at most 4 MB, as every kept file. A picture over them is turned down at its head, at once: `it is 3000 by 3001 dots, more than I show`.
- **Time, measured in QEMU** on the computer the project is built on (2026-11-24, with the timer's ticks of 10 ms, in a build with lines of its own that said them, since taken out): reading the file from the disk, about 0.26 s a MB (1.8 MB in 0.49 s, 2.9 MB in 0.77 s). Reading the picture: 1600 by 1200 dots of 8-bit colour, packed into 1.8 MB, 0.73 s; 1100 by 900 dots of noise, 2.9 MB, 0.31 s; 4000 by 4000 dots of one 8-bit colour, 4.5 s; the same in 16-bit colour and alpha, 8.7 s; 1414 by 1414 interlaced, 16-bit colour and alpha, 1.2 s; 2000 by 2000 interlaced, at the limit of 4,000,000 dots and held whole, 16 MB, 2.2 s in 16-bit colour and alpha and 1.1 s in 8-bit colour. So at the limit of 9,000,000 dots the slowest kind takes about 5 s and an 8-bit one about 2.5 s; the usual pictures of the web take well under 2 s, the file's reading included. Painting a page with a picture of 554 by 416 dots took about 0.2 s, the frame alone 0.1 s. The main loop waits meanwhile: keys wait in the keyboard's line, and the network's task goes on. A document reads at most 4 pictures, so it waits some 20 s at the very worst.
- **Memory in the kernel:** the file read whole, a piece of the heap of up to 4 MB, given back once the picture is read; what the crate holds while it reads (above; an interlaced picture up to 16 MB); and each shown picture, kept while its document is shown, under 1 MB, a piece of 1 MB. The heap hands a piece that was given back out again for the next request of its size (see [memory.md](memory.md)), so opening pictures again and again takes no more than the largest at once.
- **Nothing of a picture goes to the model,** nor is anything of it written to the disk but the file as it was fetched.

## How it is tested

The crate's tests run on the computer the project is built on, not in QEMU: it needs no machine. They are built and run as a program there, with the Visual Studio linker that cargo finds for `x86_64-pc-windows-msvc`; a computer whose settings refuse programs that were built a moment ago cannot run them. GitHub runs them in the build check (`build.yml`), which every pull request must pass, and the runner's table (`suites.py`) has two entries for the crate, "pictures" and "pictures breaks", which a change to the crate or its test data picks, and nothing that boots. Since the kernel builds the crate in, such a change also picks the entries that boot the kernel and show pictures, "picture documents" (see [testing.md](testing.md)).

- **`python test_pictures.py`** (in `test-tools/`): `cargo test` (the tests in `src/tests.rs` and the count of memory), `cargo clippy` with every warning an error (passed over, and said so, where clippy is not installed), and `cargo build` for the kernel's own target, which must give no warning. Cargo's output goes to the tests' work folder, never into the project, and a `Cargo.lock` that cargo writes beside the crate is removed again. Its last line is `FAILURES: none`, or the steps that failed.
- **`python test_pictures.py --cross-check`** also reads, with the crate and with a second reader written apart from it in Python (`test-tools/png_reference.py`, which unpacks with Python's own zlib), the PNG pictures that come with Python, with Git and with QEMU on that computer, QEMU's many icons sampled, and compares their dots one by one. Read only; nothing of them is kept. These pictures were made by other programs, so they are the check that does not rest on this project's own reading of the rules. On the computer it was run on, 106 were compared, every dot the same: 74 red-green-blue with alpha, 13 red-green-blue, 12 palettes of 8 bits and 3 of 4 bits (14 of them with see-through colours), 2 greys of 8 bits, 1 of 1 bit, and 1 grey with alpha, all of 8 bits but those. None was interlaced, of 16 bits, a grey of 2 or 4 bits, a palette of 1 or 2 bits, or had a see-through grey or colour: those are checked against the project's own second reader only.
- **The test pictures and streams** were made by `test-tools/make_picture_cases.py` with Python's zlib, and each picture was read back by the second reader before it was kept. They lie in `test-data/cases.bin`, one after another, 86 files in 540,110 bytes, and `test-data/cases.txt` lists the 56 cases and where each file lies: two files rather than a hundred, so that the runner's table can name them. They are kept as made, since another version of zlib may pack the same bytes differently, and git is told to leave them as they are (`test-data/.gitattributes`). They cover every kind of colour and depth, palettes with and without transparency, see-through greys and colours, Adam7 (with passes left out), every filter, stored, fixed, dynamic and Huffman-only blocks, runs, a 512-byte window, packed dots cut into parts of 0 to 7 bytes, parts that may be passed over, bytes after the end, and streams of up to 205 KB unpacked, with copies reaching back 32,000 bytes.
- **What the tests check:** every test picture read whole, dot for dot, and shown in rooms smaller than it, dot for dot with the second reader's shrinking; sizes and averages worked out by hand; every length from 3 to 258 and the edges of every distance code, 32,768 among them, in a stream made by the tests themselves, unpacking past the place where bytes are handed on; each rule above turned down with its own words; and damage at three depths, which must never stop it: any byte of a file changed (turned down by a check value), any byte of a part's data changed with its check value made right again, and the unpacked rows themselves changed and packed again; files cut at every byte; streams cut and changed at hundreds of places.
- **Breaks on purpose:** `python run_picture_breaks.py` puts each of 17 mistakes into a copy of the crate and runs the one test that must catch it; all 17 were caught. Three were missed at first and taught something: a change to Paeth's first tie changed nothing (a tie between the left byte and the one above comes only when the two are equal) and was replaced by its second tie; no copy reached back the full 32,768 bytes right where unpacked bytes are handed on, so the test now lands one exactly there; and the limit on literal codes said the same words as another check, so it got words of its own. One break reads codes longer than nine bits wrong, to show that the test streams have such codes.

**What was run** (on the computer the project is built on): 17 tests and the count of memory passed, clippy gave no warning, the build for the kernel's target gave no warning, the cross-check compared 106 pictures, and 17 of 17 breaks were caught. What a reading takes where the kernel runs: see "In the kernel" above.
