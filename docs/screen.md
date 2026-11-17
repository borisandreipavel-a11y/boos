# The screen: painting and letters

Code: `src/screen.rs`, and `src/letters.rs` for the shapes of the letters. The question to the firmware, `screen_find`, and the `Screen` it gives are in `src/firmware.rs`; [startup.md](startup.md) covers them.

## What the screen is

- A picture on the screen is a grid of dots (pixels). The dot at the top left is column 0 of row 0. Columns count to the right, rows count downwards.
- The screen's memory (the framebuffer) holds four bytes for every dot, row after row, starting with the top row. Three of the bytes say how much red, green and blue the dot shows, each from 0 to 255. The fourth is not used.
- Writing into that memory changes the picture at once. There is no "show it now" step and no second copy of the picture.
- The dot at column x of row y sits at `memory_start + (y * row_length + x) * 4`. `row_length` is how many dots a row takes up in the memory, which can be more than the picture is wide. Counting rows in `width` instead puts every row after the first in the wrong place on such a screen.
- Two orders of the three colours are known: red, green, blue and blue, green, red. `Screen.colours` says which one this screen uses.

## The pieces

- **`Colour`** is three amounts, `red`, `green` and `blue`, each a byte.
- **`screen_setup(screen)`** takes the `Screen` that `screen_find` gave, makes its memory reachable with `map_device_memory`, and keeps it in `SCREEN`. It is called once from `efi_main`, after the kernel's own page tables are in place: `map_device_memory` changes those tables. On a machine without a usable screen it is not called, `SCREEN` stays `None`, and the drawing functions do nothing.
- **`dot_value(order, colour)`** turns a colour into the number that is written for a dot. A dot is written as one number of four bytes. The lowest byte of a number is the one that lands first in memory, so the colour the screen wants first goes into the lowest byte. The fourth byte stays 0.
- **`screen_rectangle(left, top, width, height, colour)`** paints a filled rectangle, one dot at a time with `device_write_32`.
- **`screen_fill(colour)`** paints the whole screen: a rectangle from the top left corner, as wide and as high as the screen.
- **`screen_text(left, top, text, size, colour)`** writes one line of text; see "Letters" below.

## A rectangle is cut off at the screen's edges

- A rectangle that reaches past the right or bottom edge is cut off there. One that begins outside the screen paints nothing. So does one with a width or height of 0.
- This is what keeps drawing inside the screen's memory. Without it, dots past the right edge land at the start of the next row, and dots past the bottom edge land behind the last row: in memory of the display card that is not shown, in another device's controls, or in ordinary memory. Nothing would report that.
- The sums `left + width` and `top + height` stop at the largest number instead of wrapping round (`saturating_add`), so a huge width cannot turn into a small one.
- Any new drawing function must keep to the same rule: no address is written that was not first checked against `width` and `height`.

## Letters

The screen only knows dots, so every sign needs a small picture of itself. The pictures were drawn by hand for this kernel and are in `letters.rs`. No file was copied or downloaded for them. The shapes are not an invention, though: they follow the long-established way of writing letters on a grid of 5 by 7 dots, known from dot displays and old printers, as the one who drew them remembered it.

- A picture is 5 dots across and 9 down, written out in the source as nine rows of five signs: `#` for a dot that is painted, `.` for one that is left alone. The first seven rows hold the sign. The last two are for the tails of g, j, p, q and y, the comma, the semicolon and the underline, which hang below the line of writing.
- There are 95 pictures, `SHAPES`: the signs of plain English text in the order computers number them (ASCII), from the space, number 32, to `~`, number 126. `letter_shape(sign)` finds a sign's picture. Any other sign gets `UNKNOWN`, an empty box: letters with accents, a line break, a tab, and everything else.
- To change the look of a sign, change its picture. A row that is not 5 signs long, or a picture that is not 9 rows high, stops the build, because each row is a `[u8; 5]` and each picture nine of them. A sign other than `#` in a row counts as "left alone"; nothing checks for that.
- `screen_text` goes through the text sign by sign. For every `#` in a sign's picture it paints a square of `size` by `size` dots with `screen_rectangle`. With `size` 1 a letter is 5 by 9 dots of the screen, with 2 it is 10 by 18, and so on. The next sign starts 6 times `size` further right: the sign's width and one empty column.
- Only the dots of the letters are painted. What lies between and around them stays as it was, so text can be written over any background, and writing a second text on the same spot mixes the two.
- A text is one line. Nothing wraps round at the right edge and a line break is not understood. A text that reaches past the right or bottom edge is cut off there, in the middle of a sign if need be, because every square goes through `screen_rectangle`. The sums for a square's place stop at the largest number instead of wrapping round, so a huge `size` cannot put a dot in a wrong place.
- The next line of text belongs at least 9 times `size` lower; 10 times `size` leaves one empty row between the tails of one line and the tops of the next.
- With `size` 2, QEMU's usual screen of 1280 by 800 dots holds 106 signs across and 40 lines.
- How the letters look was judged by eye, in pictures of all 95 at several sizes; see [testing.md](testing.md).

## Drawing from tasks

- Nothing protects the screen against two tasks drawing at once. Each dot is written in one step and no state is shared, so the worst that can happen is a mixed picture: some dots from one task, some from the other. Nothing is damaged.
- `SCREEN` is written once, at startup, before any task runs. After that it is only read.
- Today only `efi_main` draws, once, before device signals are let through.

## What a boot shows

`efi_main` tries the screen right after printing the screen line: it fills the screen with dark blue (red 0, green 40, blue 90) and paints an orange rectangle (red 255, green 150, blue 0) of 300 by 200 dots in the middle. On QEMU's usual screen of 1280 by 800 dots the rectangle covers columns 490 to 789 and rows 300 to 499. Then it writes one sentence in white, at size 2, with its top left corner 40 dots from the left and 40 from the top: "Hello from my kernel! I draw my own letters now." The firmware's own text, "Hello from my kernel!" among it, is painted over before that. The picture is a demonstration and can go when something better shows that drawing works.

## How long it takes

Measured in QEMU, in the usual kind of build, by filling the screen ten times and counting timer ticks. The run had no window, and such runs can count too few ticks (see [testing.md](testing.md)), so the times may be up to half as much again; the ratio between them stands.

- Filling 1280 by 800 dots took 155 ticks for ten fills: roughly 0.16 s a fill, or 150 billionths of a second a dot. At startup that time is spent with device signals off.
- Writing a whole row with one call of Rust's own `fill` on a list of dots, instead of one `device_write_32` per dot, took 7 ticks for the same ten fills, about twenty times faster. It was tried and not kept, because one write per dot is the plainest thing to read. It is the first thing to change when drawing gets too slow.
- Writing the sentence of 48 signs at size 2 took 19 ticks for two hundred times, so about a thousandth of a second once. Every painted dot of a letter is one call of `screen_rectangle`.
