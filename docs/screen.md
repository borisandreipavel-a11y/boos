# The screen: painting, letters and the panel

Code: `src/screen.rs`, and `src/letters.rs` for the shapes of the letters. The chat box, which is drawn with these pieces, has its own file and note: `src/chat.rs` and [chat.md](chat.md). The question to the firmware, `screen_find`, and the `Screen` it gives are in `src/firmware.rs`; [startup.md](startup.md) covers them.

## What the screen is

- A picture on the screen is a grid of dots (pixels). The dot at the top left is column 0 of row 0. Columns count to the right, rows count downwards.
- The screen's memory (the framebuffer) holds four bytes for every dot, row after row, starting with the top row. Three of the bytes say how much red, green and blue the dot shows, each from 0 to 255. The fourth is not used.
- Writing into that memory changes the picture at once. There is no "show it now" step and no second copy of the picture.
- The dot at column x of row y sits at `memory_start + (y * row_length + x) * 4`. `row_length` is how many dots a row takes up in the memory, which can be more than the picture is wide. Counting rows in `width` instead puts every row after the first in the wrong place on such a screen.
- Two orders of the three colours are known: red, green, blue and blue, green, red. `Screen.colours` says which one this screen uses.

## The pieces

- **`Colour`** is three amounts, `red`, `green` and `blue`, each a byte.
- **`screen_size()`** says how many dots the screen is across and down, or nothing on a machine without a usable screen. The chat box works out its place from it.
- **`screen_setup(screen)`** takes the `Screen` that `screen_find` gave, makes its memory reachable with `map_device_memory`, and keeps it in `SCREEN`. It is called once from `efi_main`, after the kernel's own page tables are in place: `map_device_memory` changes those tables. On a machine without a usable screen it is not called, `SCREEN` stays `None`, and the drawing functions do nothing.
- **`dot_value(order, colour)`** turns a colour into the number that is written for a dot. A dot is written as one number of four bytes. The lowest byte of a number is the one that lands first in memory, so the colour the screen wants first goes into the lowest byte. The fourth byte stays 0.
- **`screen_rectangle(left, top, width, height, colour)`** paints a filled rectangle, one dot at a time with `device_write_32`.
- **`screen_fill(colour)`** paints the whole screen: a rectangle from the top left corner, as wide and as high as the screen.
- **`screen_text(left, top, text, size, colour)`** writes one line of text; see "Letters" below.
- **`screen_panel(text)`** shows a text in the box that apps show their texts in; see "The panel" below.

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

## The panel

An app can ask the kernel to show a text on the screen (`kernel.show`, see [box.md](box.md)). The kernel shows it in a box. The code calls that box a panel, because "box" already means the locked box that apps run in.

- **The app says what, the kernel decides how.** An app hands over a text and nothing else. It cannot paint, and it cannot say where the panel goes or how it looks.
- **The whole look is kept in one place,** `PANEL_STYLE` in `screen.rs`: the panel's width and height, the thickness and colour of its frame, the colour inside, the colour and size of the letters, and how far the text begins from the left and top edges. Where the panel sits is decided next to it, in `screen_panel`: in the middle of the screen. Changing the look of every app's text means changing these values and nothing else. They are fixed when the kernel is built; nothing can change them while it runs.
- **Today's look:** 520 by 60 dots, an orange frame 3 dots thick, a light inside (240, 240, 240), black letters at size 2, the text 20 dots from the left edge and 21 from the top. At that width and letter size one line of 40 signs fits, which is why an app's text may be 40 bytes long.
- **`screen_panel(text)`** paints the whole panel in the frame's colour, paints the inside over it, smaller by the frame's thickness on every side, and writes the text. Painting the whole panel each time wipes out what it showed before, so a short text after a long one leaves nothing of the long one.
- **Nothing an app shows lands outside the panel.** `screen_text` stops only at the screen's edges, so `screen_panel` holds the text to the panel itself: it writes only as many signs as fit whole between the left and right edges, and writes nothing if a line of letters does not fit between top and bottom. This holds for any values in the style, and does not lean on the 40-byte limit in `app_box.rs`. On a screen smaller than the panel, the panel and its text are cut off at the screen's edges like everything else.
- **There is one panel for every app.** The app that shows last wins. What it shows stays after the app has ended, because nothing paints over it; the kernel keeps no record of what is shown.
- On a machine without a usable screen `screen_panel` does nothing.

## Drawing from tasks

- Nothing protects the screen against two tasks drawing at once. Each dot is written in one step and no state is shared, so the worst that can happen is a mixed picture: some dots from one task, some from the other. Nothing is damaged.
- `SCREEN` is written once, at startup, before any task runs. After that it is only read.
- Most drawing happens at startup, before device signals are let through: `efi_main` draws once, and so does the app that shows a text, which runs there.
- The chat box is the one thing drawn after startup, with device signals on: the main loop paints it again whenever a key is typed. The main loop is the only task that draws then, so nothing mixes. See [chat.md](chat.md).

## What a boot shows

`efi_main` tries the screen right after printing the screen line: it fills the screen with dark blue (red 0, green 40, blue 90) and writes one sentence in white, at size 2, with its top left corner 40 dots from the left and 40 from the top: "Hello from my kernel! I draw my own letters now." The firmware's own text, "Hello from my kernel!" among it, is painted over by the fill. Right after the sentence, `chat_setup` paints the chat box along the bottom; [chat.md](chat.md) says where it sits and how it looks.

A little later, after the encryption line, an app in the box asks for its text to be shown, and the panel appears in the middle of the screen with "Hello from an app in the box" in it. On QEMU's usual screen of 1280 by 800 dots the panel covers columns 380 to 899 and rows 370 to 429, and its text begins at column 400, row 391. Some seconds after that a script, run by the interpreter in the box, asks for its own text to be shown, and the panel is painted again with "Hello from a Lua script!!!" in it; that is the text that stays. See [interpreter.md](interpreter.md).

The sentence is a demonstration and can go when something better shows that drawing works. An orange rectangle that used to be painted in the middle was such a demonstration and went when the panel came.

## How long it takes

Measured in QEMU, in the usual kind of build, by filling the screen ten times and counting timer ticks. The run had no window, and such runs can count too few ticks (see [testing.md](testing.md)), so the times may be up to half as much again; the ratio between them stands.

- Filling 1280 by 800 dots took 155 ticks for ten fills: roughly 0.16 s a fill, or 150 billionths of a second a dot. At startup that time is spent with device signals off.
- Writing a whole row with one call of Rust's own `fill` on a list of dots, instead of one `device_write_32` per dot, took 7 ticks for the same ten fills, about twenty times faster. It was tried and not kept, because one write per dot is the plainest thing to read. It is the first thing to change when drawing gets too slow.
- Writing the sentence of 48 signs at size 2 took 19 ticks for two hundred times, so about a thousandth of a second once. Every painted dot of a letter is one call of `screen_rectangle`.
- Showing a text in the panel was not timed by itself. An app that showed in a loop, with the limit on showing taken out and one printed line per showing, managed about 115 showings a second, so one is under a hundredth of a second.
