# The chat box: typing on the screen

Code: `src/chat.rs`, the call of `chat_setup` in `efi_main`, and the main loop, which hands every typed key to `chat_key`. The drawing is done with the pieces in `src/screen.rs`; see [screen.md](screen.md).

The chat box is the place on the screen where the person at the machine types. It lies along the bottom of the screen. Its bottom row shows the line being typed. Above that are the last rows of what was said: the person's lines and the kernel's answers. Today the kernel answers every line by giving it back.

## What it does

- **A key with a letter** adds that letter to the line being typed, and the row being typed is painted again. The row reads `> `, the line so far, and a `_` that marks where the next sign will go.
- **Backspace** takes the last sign away. On an empty line it does nothing.
- **Enter** sends the line. The line moves up into what was said as `You: ...`, the kernel's answer follows as `Kernel: you said "..."`, and the row being typed is empty again. On an empty line Enter does nothing.
- **A line is at most 50 signs long** (`CHAT_LINE_LIMIT`). A key pressed after that is ignored until a sign is taken away or the line is sent. On a screen so narrow that fewer than 53 signs fit on a row, the line may be only as long as fits behind the `> ` and before the `_`.
- **A text longer than a row goes on in the next row.** It is cut where the row ends, in the middle of a word if need be. On a screen 1280 dots wide a row holds 97 signs, so nothing typed needs a second row there; on a screen 800 dots wide a row holds 57, and the answer to a long line takes two.
- **Six rows of what was said are shown.** When a seventh comes, the oldest goes. Nothing older is kept anywhere.
- **What is said is repeated in the terminal,** as whole lines: the person's line and the answer, sent in one go when Enter is pressed. Single keys are not echoed there any more, so the terminal never gets a byte that is not plain text.
- **On a machine without a usable screen** nothing is shown and no rows are kept, but typing works: the line is collected, held to 50 signs, and repeated with its answer in the terminal on Enter.

Only the keys `key_letter` knows can be typed: the small letters, the digits, the signs on their keys without Shift, the space bar, Enter and Backspace. Shift is not understood, so Shift with `a` types `a`. The arrow keys, Esc, Tab, Delete and the F keys give nothing.

## The look

The whole look is one set of values, `CHAT_STYLE` in `chat.rs`: how many rows are shown, how far the chat box stays from the screen's left, right and bottom edges, the thickness and colour of the frame, the colour behind what was said and behind the row being typed, the colours of the person's and the kernel's letters, the size of the letters, how far the text stays from the frame, and the gap between rows. Changing the look means changing these values and nothing else. They are fixed when the kernel is built; nothing can change them while it runs.

Today's look: six rows, 40 dots from the edges, an orange frame 3 dots thick, a light inside (232, 236, 244), a white row for typing, black letters for the person, dark blue ones (0, 60, 140) for the kernel, letters at size 2, 10 dots between frame and text, 4 dots between rows.

Where the chat box sits and how much fits in it is worked out from the style and the screen's size by `chat_place`, each time it is needed:

- A row is as high as a letter plus the gap: 22 dots today.
- From top to bottom the chat box is the frame, the empty room, the six rows, the row being typed with empty room below it, and the frame: 180 dots today.
- It is as wide as the screen less the margin on both sides, and its bottom edge is one margin above the bottom of the screen. On a screen of 1280 by 800 dots it covers columns 40 to 1239 and rows 580 to 759.
- A row holds as many signs as fit whole between the frame and the empty room on both sides.

The chat box, the box that shows an app's text and the sentence at the top do not touch on screens of 800 by 600 dots and larger. Nothing was tried on a smaller one; there the chat box would be cut off at the screen's edges like everything else, and could lie over the app's box.

## Nothing lands outside the chat box

- Every row is written by `chat_write`, which writes only as many signs as fit whole on a row, whatever it is handed. `screen_text` itself stops only at the screen's edges.
- The rows above cannot be more than the style says, because `chat_add` drops the oldest, and each row is at most as long as fits, because `chat_add` cuts a longer text into several.
- With the cut in `chat_write` and the cutting into rows both taken out on purpose, a long answer ran out past the right edge of the chat box on a screen 800 dots wide.

## How it is painted

- `chat_setup` paints the whole chat box once at startup: all of it in the frame's colour, then the two areas inside, which leave the frame showing. It adds one row from the kernel that says what to do.
- After a key, only the row being typed is painted again (`chat_paint_typing`): its area in its colour, then the text.
- After Enter, the rows of what was said are painted again as well (`chat_paint_rows`): their whole area in the inside colour, which wipes out what stood there, then each row. A short row in the place of a long one leaves nothing of the long one.
- This is the first drawing that happens after startup, with device signals on. The timer and the other tasks carry on while the main loop paints.

Measured in QEMU without a window, where ticks can come late, so the times may be up to half as much again: painting the row being typed takes about 8 thousandths of a second, and sending a line about 50. For that half of a tenth of a second the rows are blank and then filled. A person watching a QEMU window saw no flicker.

A key held down types more of its letter: the keyboard itself sends the key again and again, and each arrives as an ordinary key.

Keys wait in the keyboard's line of 16 key numbers while the main loop paints, and each key takes two of them, one for pressing and one for letting go. A sentence of 39 keys and Enter, sent 10 thousandths of a second apart, a hundred keys a second and far faster than anybody types, arrived whole. Sent 5 thousandths apart, or with no pause at all, keys were lost.

## Who may use it

- `CHAT_ROWS` and `CHAT_LINE` are plain `static mut` lists, and nothing protects them. **Only the main loop may call the functions of `chat.rs`.** A second task that added a row, or painted, while the main loop was at work in the same list would break it.
- A task that has something to say in the chat box needs a way to hand its text to the main loop. There is none yet.
- The two lists grow, so they cannot be copied in and out by value like the kernel's other `static mut` values. `chat_rows()` and `chat_line()` hand them out through their addresses instead, and Rust cannot check what happens to a list handed out that way. The rule to keep by hand: after calling another function of `chat.rs`, do not go on using a list that was fetched before the call. Today `chat_key` fetches the typed line, changes it, and only then calls the painting functions, which fetch it again for themselves.
- The heap, which the lists use, is protected against task switches by itself; see [tasks.md](tasks.md).

## Text from outside

Everything in the chat box today comes from the keyboard or from the kernel's own code, and the keyboard can only produce plain signs. Text that comes from outside the kernel must be cleaned before it is handed to the chat box, as everywhere else (see `plain_text` in `page.rs`). A sign without a picture would show as an empty box on the screen; in the terminal it would go out as it is.

## How to test it

[testing.md](testing.md) says how to boot without a window, send keys and save pictures of the screen. Habits that proved their worth here:

- **Compare every dot** of a saved picture with a picture built by the checking script, from the style's numbers typed into the script and the grids in `letters.rs`. The script keeps its own account of what the chat box should hold after each key.
- **Take a picture before Enter too.** The point of the chat box is that letters show while they are typed.
- **Wait about half a second after a key before saving a picture.** Sending a line takes a twentieth of a second to paint, and a picture saved in the middle of that shows blank rows, which looks like a fault and is none.
- **Read the terminal as well:** the lines said must be the last lines there, word for word.

## Limits

See [open-points.md](open-points.md). In short: the kernel only gives the line back, one task may use the chat box, six rows are shown and nothing older is kept, there are no capital letters, and the look is fixed when the kernel is built.
