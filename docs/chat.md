# The chat box: typing on the screen

Code: `src/chat.rs`, `src/secret.rs`, `src/onboarding.rs`, the calls of `chat_setup` and `chat_begin` in `efi_main`, and the main loop, which hands every typed key to `chat_key`. The drawing is done with the pieces in `src/screen.rs`; see [screen.md](screen.md).

The chat box is the place on the screen where the person at the machine types. It lies along the bottom of the screen. Its bottom row shows the line being typed. Above that are the last rows of what was said: the person's lines and the kernel's answers. Today the kernel answers every line but four by giving it back. One is `key`, which makes it ask for a secret; see "A secret" below. Another is `fetch`, which makes it fetch a page from the web; see "Asking the network" below. The third is `ask`, which makes it ask the model one fixed question; see "Asking the model" below. The fourth is `setup`, which makes it ask for the person's name again; see "The name" below. At a start where the kernel does not know the person's name yet, it asks for it before anything else.

## What it does

- **A key with a letter** adds that letter to the line being typed, and the row being typed is painted again. The row reads `> `, the line so far, and a `_` that marks where the next sign will go.
- **Backspace** takes the last sign away. On an empty line it does nothing.
- **Enter** sends the line. The line moves up into what was said as `You: ...`, the kernel's answer follows as `Kernel: you said "..."`, and the row being typed is empty again. Once the person has given a name, it stands in front of their lines in place of `You` (see "The name" below). On an empty line Enter does nothing, except while the kernel waits for a name.
- **The line that was sent is kept on the disk,** in the notebook, under the name `last line`; see [notebook.md](notebook.md). Nothing is said when that works. If it does not, a row says so, `Kernel: I could not keep that line, because ...`, and the chat goes on. On a machine without a disk, or without a notebook that can be added to, nothing is kept and nothing is said about it.
- **At the next start the kernel says that line again:** `chat_begin`, called once from `efi_main` after the notebook is opened, adds the row `Kernel: last time you said "..."` and prints the same line in the terminal. It comes after the greeting by name, or before the question at a start that asks for a name. Only the last line is said, although every line that was sent is still in the notebook.
- **A line is at most 50 signs long** (`CHAT_LINE_LIMIT`). A key pressed after that is ignored until a sign is taken away or the line is sent. On a screen so narrow that fewer than 53 signs fit on a row, the line may be only as long as fits behind the `> ` and before the `_`.
- **A text longer than a row goes on in the next row.** It is cut where the row ends, in the middle of a word if need be. On a screen 1280 dots wide a row holds 97 signs, so nothing typed needs a second row there; on a screen 800 dots wide a row holds 57, and the answer to a long line takes two.
- **Six rows of what was said are shown.** When a seventh comes, the oldest goes. Nothing older is kept anywhere.
- **What is said is repeated in the terminal,** as whole lines: the person's line and the answer, sent in one go when Enter is pressed. Single keys are not echoed there any more, so the terminal never gets a byte that is not plain text.
- **On a machine without a usable screen** nothing is shown and no rows are kept, but typing works: the line is collected, held to 50 signs, and repeated with its answer in the terminal on Enter.

Only the keys `key_letter` knows can be typed: the letters, small and with Shift capital, the digits, the signs of a US keyboard with and without Shift, the space bar, Enter and Backspace. That is every one of the 95 signs the screen has a picture for. Caps Lock does nothing. The arrow keys, Esc, Tab, Delete and the F keys give nothing. See [interrupts.md](interrupts.md) for how Shift is followed.

## The name

Code: `src/onboarding.rs`. The kernel asks the person at the machine what to call them, keeps the answer in the notebook on the disk (see [notebook.md](notebook.md)), and puts it in front of their rows.

- **At a start where the notebook holds no name,** the kernel asks, in two rows that take the place of the row that says what to do: `Kernel: hello! I do not know your name yet, so I have one question before we begin.` and `Kernel: what should I call you? Type a name and press Enter. Enter alone keeps "You".` If a line was kept from before, its row `Kernel: last time you said "..."` comes first, so that the question is the last row. The rows are printed in the terminal too, before the prompt.
- **While the kernel waits for the answer, the next line sent is the answer,** whatever it says: `key`, `fetch`, `ask` and `setup` are names then like any other. Enter alone is an answer too. A name is at most 20 signs (`NAME_LIMIT`): while the kernel waits, the line takes no more. Spaces at either end are dropped.
- **A name is kept under the name `name`,** and the kernel says `Kernel: hello, Ada. I will remember your name. Type a line and press Enter.` From then on the name stands in front of the person's rows in place of `You`, in the chat box and in the terminal. The row with the answer shows it as typed, with what stood in front of the rows before. The answer is not given back and not kept as the `last line`.
- **Enter alone leaves the name as it is.** At a start that asks, that is `You`: the kernel keeps an entry that holds no signs, which says that the question was answered, and says `Kernel: I will call you "You". Type a line and press Enter.` When a name is kept already, nothing is written, and the kernel says `Kernel: your name stays "Ada". Type a line and press Enter.` A line of nothing but spaces counts as Enter alone.
- **Every later start greets the person by the name,** in place of the row that says what to do: `Kernel: welcome back, Ada. Type a line and press Enter.`, or `Kernel: welcome back. Type a line and press Enter.` when the answer was to stay `You`. The row of the last line follows if there is one.
- **The line `setup`, sent by itself, asks again** (`SETUP_WORD`): the question row, with the name that Enter alone keeps. The line `setup` itself is kept as the last line, like any other line.
- **If the answer cannot be kept,** the kernel uses it until the machine is switched off and says why: `Kernel: hello, Ada. I could not keep your name, because ..., so it lasts only until the machine is switched off.` At a start that asked, the next start asks again.
- **Without a notebook that can be added to** (no disk, a disk without a part of the kernel's own, a part that holds something the kernel does not know, a damaged notebook), nothing is asked at startup, and the chat box begins with the row that says what to do, as without the name. A name kept in a damaged notebook is still read, and the person is greeted by it. `setup` asks all the same, and the answer lasts until the machine is switched off.
- **An entry under `name` is what tells a later start that the question was answered.** It is written only when the answer comes, so a start that is switched off before that asks again at the next start.
- **The name stays on the disk as typed,** readable by anyone with the disk, like every line kept there. Nothing takes it out; a new answer only takes its place.
- **A name read from the disk comes from outside the kernel:** at most 20 bytes are taken, every byte that is not a plain sign becomes a dot, and spaces at either end are dropped.
- **Only the main loop may call the functions of `onboarding.rs`,** as for `chat.rs`: the name and the two marks `ASKING` and `ANSWER_KEPT` are plain `static mut` values, and the name is reached through its address by `name()`, with the same rule as the chat box's lists.

## A secret

A secret is a text that the person at the machine types and that nobody else should get to see, such as the key a paid service asks for. The chat box can take one, and `src/secret.rs` keeps it.

- **The line `key`, sent by itself, asks for it** (`SECRET_WORD`). The kernel answers `Kernel: type the secret and press Enter. It shows as stars.`, and from the next key on what is typed is the secret. `keys` and `Key` are ordinary lines.
- **Each sign shows as a star.** The row being typed reads `> `, a star for each sign, and the `_`. Past 30 stars (`STARS_SHOWN`) it goes on with ` and N more`, so that a long secret can be counted without being seen. The count is the only check the person has that no key was lost.
- **Backspace** takes the last sign away, and that sign is wiped.
- **Enter** hands the secret over. The kernel says how many signs it took and nothing else: `Kernel: I took a secret of 41 signs. It is kept in memory only.`, with ` The one before is gone.` behind it if one was kept already. Enter with nothing typed takes no secret, `Kernel: no secret was taken.`, and leaves the one kept before as it was.
- **A secret is at most 200 signs long** (`SECRET_LIMIT`). A key pressed after that is ignored.
- **Where a secret must never go, and does not:** into a row of what was said, to the terminal, into the notebook on the disk. The line `key` itself is an ordinary line and is kept like any other.
- **Where it is while it is typed:** in `SECRET_TYPED` in `chat.rs`, a room of fixed size at a fixed place. It is not kept in the line being typed, because a text that grows moves in memory as it grows and leaves copies of itself behind that nothing wipes. On Enter the signs are copied to their place in `secret.rs` and the room is wiped.
- **Where it is kept:** in `SECRET` in `secret.rs`, again a room of fixed size, in memory only. It is gone when the machine is switched off. `secret_keep` wipes the whole room before it puts a new secret in, so nothing of a longer one stays behind a shorter one. `secret_length` says how long the kept secret is. **One function lends the secret out, `secret_lend`, and only to `model.rs`,** which sends it to the model's provider as the key (see [model.md](model.md)); the compiler refuses a call from any other file. No function may be added that prints the secret, shows it or writes it to the disk.
- **Wiping** is done by `wipe` in `secret.rs`, which writes zeros in a way the compiler may not leave out.
- **The keyboard's waiting line** holds the numbers of the last keys pressed, a secret's among them. `next_key` now empties each place as it takes the key out; see [interrupts.md](interrupts.md).
- **On a machine without a usable screen** a secret can be typed all the same, blind: no stars show, and the terminal says how many signs were taken.

The secret is used as the key when the model is asked; see "Asking the model" below and [model.md](model.md).

## Asking the network

- **The line `fetch`, sent by itself, asks for the example page** (`FETCH_WORD`). The chat box cannot use the network itself: only the network's task may. So it leaves an errand for that task (see "Errands" in [tasks.md](tasks.md)) and answers at once, `Kernel: I am asking the network for the page of example.com.`
- **The answer comes later, as a row of its own,** when the network's task has it: `Kernel: example.com answered "HTTP/1.1 200 OK". Its page is 577 bytes long.`, or `Kernel: no page came, because ...` with the reason. With a site that answers it takes about a second; with one that goes silent, as long as the fetch waits, a quarter of a minute and more.
- **Typing goes on meanwhile.** Lines are given back, and a secret can be typed, while the answer is awaited.
- **One asking at a time.** A second `fetch` before the answer to the first has come is turned away: `Kernel: I cannot ask the network, because the answer to what I asked before has not come yet`.
- **On a machine without a network card, or without an address,** it is turned away at once: `Kernel: I cannot ask the network, because this machine has no address on the network`.

## Asking the model

- **The line `ask`, sent by itself, asks the model one fixed question** (`ASK_WORD`; the question is `QUESTION` in `model.rs`). It needs a kept secret, which goes along as the key. Without one: `Kernel: I cannot ask the model, because no key is kept. Send the line "key" first.`
- It is an errand for the network's task, like `fetch`, and the chat box answers at once, `Kernel: I am asking the model "Say hello in five words."`
- **The answer comes later, as a row of its own:** what the model answered, why the provider turned the question down or could not answer, or why no answer came. The sentences are listed in [model.md](model.md). A provider that refuses answers within a second or two; one that stays silent is waited for a minute.
- **The key that was sent does not show.** If the provider repeats it or a piece of it in its answer, stars stand in its place in the row and in the terminal.
- **One asking at a time,** of either kind: while the answer to an `ask` or a `fetch` is awaited, both are turned away, `... because the answer to what I asked before has not come yet`. Typing goes on meanwhile.
- **`chat_say(text)`** is how such a row gets in: it adds a row of the kernel's and repeats it in the terminal. The main loop calls it when an errand's answer has come. Like every function of `chat.rs` it may be called by the main loop only.
- **Each asking reaches the internet:** one question to the name server and one exchange with the site, as at startup.

The word and the page are a demonstration of the road an answer from the network takes into the chat box.

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

- `chat_setup` paints the whole chat box once at startup: all of it in the frame's colour, then the two areas inside, which leave the frame showing. It adds one row from the kernel that says what to do. Once the notebook is opened, `chat_begin` puts the greeting by name, or the question for one, in that row's place and paints the rows again.
- After a key, only the row being typed is painted again (`chat_paint_typing`): its area in its colour, then the text.
- After Enter, the rows of what was said are painted again as well (`chat_paint_rows`): their whole area in the inside colour, which wipes out what stood there, then each row. A short row in the place of a long one leaves nothing of the long one.
- This is the first drawing that happens after startup, with device signals on. The timer and the other tasks carry on while the main loop paints.

Measured in QEMU without a window, where ticks can come late, so the times may be up to half as much again: painting the row being typed takes about 8 thousandths of a second, and sending a line about 50. For that half of a tenth of a second the rows are blank and then filled. A person watching a QEMU window saw no flicker.

A key held down types more of its letter: the keyboard itself sends the key again and again, and each arrives as an ordinary key.

Keys wait in the keyboard's line of 16 key numbers while the main loop paints, and each key takes two of them, one for pressing and one for letting go. A sentence of 39 keys and Enter, sent 10 thousandths of a second apart, a hundred keys a second and far faster than anybody types, arrived whole. Sent 5 thousandths apart, or with no pause at all, keys were lost.

## Who may use it

- `CHAT_ROWS` and `CHAT_LINE` are plain `static mut` lists, and so are the secret's rooms in `chat.rs` and `secret.rs`. Nothing protects them. **Only the main loop may call the functions of `chat.rs`.** A second task that added a row, or painted, while the main loop was at work in the same list would break it.
- A task that has something to say in the chat box cannot say it itself. The one way in is an errand's answer, which the main loop picks up and hands to `chat_say`; see "Errands" in [tasks.md](tasks.md).
- The two lists grow, so they cannot be copied in and out by value like the kernel's other `static mut` values. `chat_rows()` and `chat_line()` hand them out through their addresses instead, and `secret_typed()` does the same for the room a secret is typed into, which must not be copied; and Rust cannot check what happens to a list handed out that way. The rule to keep by hand: after calling another function of `chat.rs`, do not go on using a list that was fetched before the call. Today `chat_key` fetches the typed line, changes it, and only then calls the painting functions, which fetch it again for themselves.
- The heap, which the lists use, is protected against task switches by itself; see [tasks.md](tasks.md).

## Text from outside

What is typed comes from the keyboard, which can only produce plain signs, and the kernel's rows come from its own code. Two texts come from outside the kernel: the line kept on the disk and the name kept there. `chat_begin` takes at most 50 signs of the line, `onboarding.rs` at most 20 of the name, and both turn every byte that is not a plain sign into a dot. Any other text that comes from outside the kernel must be cleaned before it is handed to the chat box, as everywhere else (see `plain_text` in `page.rs`). A sign without a picture would show as an empty box on the screen; in the terminal it would go out as it is.

## How to test it

[testing.md](testing.md) says how to boot without a window, send keys and save pictures of the screen. Habits that proved their worth here:

- **Compare every dot** of a saved picture with a picture built by the checking script, from the style's numbers typed into the script and the grids in `letters.rs`. The script keeps its own account of what the chat box should hold after each key.
- **Take a picture before Enter too.** The point of the chat box is that letters show while they are typed.
- **Wait about half a second after a key before saving a picture.** Sending a line takes a twentieth of a second to paint, and a picture saved in the middle of that shows blank rows, which looks like a fault and is none.
- **Read the terminal as well:** the lines said must be the last lines there, word for word.

## Limits

See [open-points.md](open-points.md). In short: the kernel only gives the line back, takes a secret, fetches one fixed page, asks the model one fixed question or asks for a name, one task may use the chat box, six rows are shown and of what was said before a switch-off only the last line is said again, only the last sign of a line can be taken away, and the look is fixed when the kernel is built.
