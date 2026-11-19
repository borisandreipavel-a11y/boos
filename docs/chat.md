# The chat box: typing on the screen

Code: `src/chat.rs`, `src/secret.rs`, `src/onboarding.rs`, the calls of `chat_setup` and `chat_begin` in `efi_main`, and the main loop, which hands every typed key to `chat_key`. The drawing is done with the pieces in `src/screen.rs`; see [screen.md](screen.md).

The chat box is the place on the screen where the person at the machine types. It lies along the bottom of the screen. Its bottom row shows the line being typed. Above that are the last rows of what was said: the person's lines and the kernel's answers. Today the kernel answers every line but five by giving it back. One is `key`, which makes it ask for a secret; see "A secret" below. Another is `fetch`, which makes it fetch a page from the web; see "Asking the network" below. The third is `ask`, which makes it ask the model one fixed question; see "Asking the model" below. The fourth is `setup`, which makes it ask for the person's name and the model's key again; see "The name" and "The key and the password" below. The fifth is `look`, which makes it list the looks the screen can have and ask for the number of one; see "Picking a look" below. At a start where the kernel does not know the person's name yet, it asks for it before anything else, and then for the key, which it tries with one question to the model before it keeps it; at a start where a key is locked on the disk, it asks for the password that unlocks it.

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

Code: `src/onboarding.rs`. The kernel asks the person at the machine what to call them, keeps the answer in the notebook on the disk (see [notebook.md](notebook.md)), and puts it in front of their rows. After the name it asks about the model's key; see "The key and the password" below.

- **At a start where the notebook holds no name,** the kernel asks, in two rows that take the place of the row that says what to do: `Kernel: hello! I do not know you yet, so I have a few questions before we begin.` and `Kernel: what should I call you? Type a name and press Enter. Enter alone keeps "You".` When nothing about the key will be asked after the name, the first row reads `Kernel: hello! I do not know your name yet, so I have one question before we begin.` instead. If a line was kept from before, its row `Kernel: last time you said "..."` comes first, so that the question is the last row. The rows are printed in the terminal too, before the prompt.
- **While the kernel waits for the answer, the next line sent is the answer,** whatever it says: `key`, `fetch`, `ask` and `setup` are names then like any other. Enter alone is an answer too. A name is at most 20 signs (`NAME_LIMIT`): while the kernel waits, the line takes no more. Spaces at either end are dropped.
- **A name is kept under the name `name`,** and the kernel says `Kernel: hello, Ada. I will remember your name.`, followed by what it asks about the key, or with ` Type a line and press Enter.` on the same row when it asks nothing more. From then on the name stands in front of the person's rows in place of `You`, in the chat box and in the terminal. The row with the answer shows it as typed, with what stood in front of the rows before. The answer is not given back and not kept as the `last line`.
- **Enter alone leaves the name as it is.** At a start that asks, that is `You`: the kernel keeps an entry that holds no signs, which says that the question was answered, and says `Kernel: I will call you "You".` When a name is kept already, nothing is written, and the kernel says `Kernel: your name stays "Ada".` Either is followed as above. A line of nothing but spaces counts as Enter alone.
- **Every later start greets the person by the name,** in place of the row that says what to do: `Kernel: welcome back, Ada.`, or `Kernel: welcome back.` when the answer was to stay `You`, followed by the question for the password or the key, or with ` Type a line and press Enter.` on the same row when nothing is asked. The row of the last line follows if there is one, or comes first while a question waits.
- **The line `setup`, sent by itself, asks again** (`SETUP_WORD`): the question row, with the name that Enter alone keeps, and after the answer the question for a key. The line `setup` itself is kept as the last line, like any other line.
- **If the answer cannot be kept,** the kernel uses it until the machine is switched off and says why: `Kernel: hello, Ada. I could not keep your name, because ..., so it lasts only until the machine is switched off.` At a start that asked, the next start asks again.
- **Without a notebook that can be added to** (no disk, a disk without a part of the kernel's own, a part that holds something the kernel does not know, a damaged notebook), nothing is asked at startup, and the chat box begins with the row that says what to do, as without the name. A name kept in a damaged notebook is still read, and the person is greeted by it. `setup` asks all the same, and the answer lasts until the machine is switched off. Nothing is asked about a key there either, except the password for a key locked in a damaged notebook, since unlocking writes nothing.
- **An entry under `name` is what tells a later start that the question was answered.** It is written only when the answer comes, so a start that is switched off before that asks again at the next start.
- **The name stays on the disk as typed,** readable by anyone with the disk, like every line kept there. Nothing takes it out; a new answer only takes its place.
- **A name read from the disk comes from outside the kernel:** at most 20 bytes are taken, every byte that is not a plain sign becomes a dot, and spaces at either end are dropped.
- **Only the main loop may call the functions of `onboarding.rs`,** as for `chat.rs`: what the kernel waits for (`WAITING`), the name, the locked key read from the notebook and the marks beside them are plain `static mut` values, and the name and the locked key are reached through their addresses by `name()` and `locked_key()`, with the same rule as the chat box's lists.

## The key and the password

Code: `src/onboarding.rs`, with `src/secret.rs` and the lock in `src/lock.rs` (see [lock.md](lock.md)). After the name, the kernel asks for the key that the model's provider asks for, tries it with one question to the model, and asks for a password to lock it with. The key is kept on the disk only locked. Every later start asks for the password, which unlocks it, so that `ask` works without the key being typed again.

- **What is typed shows as stars,** as with a secret (see "A secret" below): the key, the password both times, and the password at a later start are typed into the same room as a secret, a star for each sign, at most 200 signs, and never go into a row, into the terminal or into the notebook as they are. Enter hands them to `onboarding_secret`, and the room is wiped.
- **The question for the key** comes after the name at a start where the notebook holds no answer about the key: `Kernel: to ask the model I need your key. I lock it with a password and keep it on the disk.` and `Kernel: type the key and press Enter. It shows as stars. Enter alone goes on without a key.` It is asked only if the key can be locked and kept: the notebook can be added to, and the machine can make random numbers. Without random numbers the kernel says `Kernel: I cannot lock a key on this machine, because it cannot make random numbers.` and `Kernel: send "key" for a key that lasts until the machine is switched off.`, and asks nothing.
- **The key is tried first.** It waits apart from any key kept before (`trial_keep` in `secret.rs`), and the kernel asks the model, with that key, the question that `ask` asks: an errand for the network's task (see "Errands" in [tasks.md](tasks.md)). It says `Kernel: I took a key of 35 signs, and I am trying it with one question to the model.` The count is the only check the person has that no key was lost. The answer comes in rows of their own: first what came back, in the words `ask` would use (see [model.md](model.md)), such as `Kernel: the model answered "..."`, and then what comes of it (`onboarding_tried`):
  - the model answered (the number 200): `Kernel: the key works. Now choose a password of at least 4 signs to lock it with.` The key takes the place of any kept before (`trial_take`), and `ask` finds it there.
  - the provider does not know the key (401): `Kernel: the provider does not know that key, so I did not keep it.` and the question for the key again. That key is wiped (`trial_forget`); a key kept before, such as one unlocked at this start, stays as it was.
  - the provider knows the key but did not answer with it, and says why (402: no credit is left; 403: a limit of the key's own, or a model the key may not use): `Kernel: the provider knows the key, so I keep it.` and `Kernel: now choose a password of at least 4 signs to lock it with.`
  - any other answer, or none: `Kernel: so I cannot tell whether the key is right. I keep it all the same.` and the row that asks for a password. That covers no name server, provider trouble (500 and on), too many questions (429), a 402 or 403 without the provider's reason (a page from somewhere on the way), and a provider that stays silent for the minute the kernel waits.
- **A try that cannot be made** is not waited for: when the machine has no address on the network, or the answer to an `ask` or a `fetch` has not come yet. The kernel says `Kernel: I took a key of 35 signs, but I cannot try it now, because ...` with the reason, the row that it cannot tell, and the row that asks for a password. The key is kept.
- **While the key is tried, nothing typed is taken**, since it would stand ready as the answer to a question that is not asked yet: the row being typed stays empty, and Enter says `Kernel: I am still trying the key. Wait for its answer, then type.` If signs were typed meanwhile, the answer begins with `Kernel: what was typed while I tried the key was not taken.` A provider that answers does so in a second or two; one that stays silent is waited for a minute.
- **Each try is a real question to the provider,** with the key that was typed. A key it does not know is turned down before any model is asked; with a key it knows, the question is paid for as an `ask` is.
- **The password** must have at least 4 signs (`PASSWORD_LEAST`): `Kernel: that password has only 3 signs, and it needs at least 4. Choose a longer one.` Such a password is meant to keep out somebody who uses the machine, not somebody with a copy of the disk (see [open-points.md](open-points.md)). Then: `Kernel: type the same password again and press Enter.` If the two differ: `Kernel: the two passwords differ. Choose a password again and press Enter.`, and the first is forgotten.
- **Locking:** when the second password is the same, the kernel says `Kernel: locking the key with your password. This takes a second or two.`, locks the key with the password (`secret_lock`), keeps the locked key in the notebook under the name `locked key`, forgets the password, and says `Kernel: the key is locked and kept on the disk. Each start will ask for the password.` and `Kernel: type a line and press Enter.`
- **Enter alone always leads out:**
  - at the question for the key: `Kernel: then no key is kept. Send "setup" to give one later. Type a line and press Enter.` An entry under `locked key` that holds no signs is kept, so that later starts do not ask again. At a `setup` while a locked key is kept: `Kernel: the key locked on the disk stays as it was. Type a line and press Enter.`
  - at either password: `Kernel: then the key is kept for this start only, not on the disk. Type a line and press Enter.` The key stays in memory until the machine is switched off. If the notebook held no answer about the key yet, the entry that holds no signs is kept, as above.
- **At every later start where a key is locked on the disk,** after the greeting: `Kernel: type your password and press Enter to unlock the key. Enter alone goes on without it.` On Enter the kernel says `Kernel: unlocking the key. This takes a second or two.`, and then:
  - with the right password: `Kernel: the key is unlocked, so "ask" works. Type a line and press Enter.` The key is kept in memory until the machine is switched off (`secret_unlock`).
  - with a wrong one: `Kernel: the key could not be unlocked: the password is wrong, or the locked key was changed.` and `Kernel: type the password again, or press Enter alone to go on without the key.` The two cannot be told apart (see [lock.md](lock.md)). There is no limit on the tries; each takes as long as an unlocking.
  - with a locked key that the kernel cannot read at all (too short, too long, another version or way, a count of rounds out of bounds): `Kernel: I cannot unlock the key kept on the disk, because ...`, with the reason `unlock` gives, and `Kernel: send "setup" to lock a new one. Type a line and press Enter.` This comes at once, before any round.
  - with Enter alone: `Kernel: going on without the key. Send "setup" to lock a new one. Type a line and press Enter.` A forgotten password means a new key and a new password, through `setup`.
- **`setup`** asks for the name and then for a key: the same question as at the first start if no key is locked, or `Kernel: type a new key and press Enter. Enter alone keeps the one locked on the disk.` if one is. A new key is tried, then locked with the new password and kept as a new entry, which counts from then on. After a key the provider does not know, the same question comes again, and Enter alone leaves both the locked key and a key unlocked at this start as they were.
- **A key locked before stays on the disk.** The notebook never changes what it wrote (see [notebook.md](notebook.md)), so after `setup` the key locked with the old password is still there, and the old password still opens it. If a password is changed because someone may know it, the key itself should be replaced at the provider, which makes the old locked one useless.
- **Locking and unlocking take about a second** in QEMU on the test computer, from Enter to the row that says it is done. The work is done in the main loop with device signals on, so the other tasks carry on. Keys typed meanwhile wait in the keyboard's line of 16 key numbers (a key without Shift takes two, one with Shift four) and are taken afterwards; keys that do not fit are lost. The row that says the work has begun is painted before it begins.
- **The line `key` is as it was:** a key typed after it is kept in memory for this start only, never tried, never locked and never kept on the disk. It takes the place of a key unlocked at the start until the machine is switched off.
- **The key and the password go only where they must.** The key goes from the room it is typed into to a room of its own in `secret.rs` while it is tried, and from there to the secret's place once it is kept, or it is wiped; the password to a room of its own there (`password_keep`) until it is typed the second time, and is wiped once the key is locked or the two differ; a password typed to unlock goes straight from the room it is typed into to the unlocking. Locking and unlocking work in rooms of their own, copied with device signals off and wiped at the end (see "A secret" below).

## A secret

A secret is a text that the person at the machine types and that nobody else should get to see, such as the key a paid service asks for. The chat box can take one, and `src/secret.rs` keeps it.

- **The line `key`, sent by itself, asks for it** (`SECRET_WORD`). The kernel answers `Kernel: type the secret and press Enter. It shows as stars.`, and from the next key on what is typed is the secret. `keys` and `Key` are ordinary lines.
- **Each sign shows as a star.** The row being typed reads `> `, a star for each sign, and the `_`. Past 30 stars (`STARS_SHOWN`) it goes on with ` and N more`, so that a long secret can be counted without being seen. The count is the only check the person has that no key was lost.
- **Backspace** takes the last sign away, and that sign is wiped.
- **Enter** hands the secret over. The kernel says how many signs it took and nothing else: `Kernel: I took a secret of 41 signs. It is kept in memory only.`, with ` The one before is gone.` behind it if one was kept already. Enter with nothing typed takes no secret, `Kernel: no secret was taken.`, and leaves the one kept before as it was.
- **A secret is at most 200 signs long** (`SECRET_LIMIT`). A key pressed after that is ignored.
- **Where a secret must never go, and does not:** into a row of what was said, to the terminal, into the notebook on the disk as it is. The line `key` itself is an ordinary line and is kept like any other.
- **Where it is while it is typed:** in `SECRET_TYPED` in `chat.rs`, a room of fixed size at a fixed place. It is not kept in the line being typed, because a text that grows moves in memory as it grows and leaves copies of itself behind that nothing wipes. On Enter the signs are copied to their place in `secret.rs` and the room is wiped.
- **Where it is kept:** in `SECRET` in `secret.rs`, again a room of fixed size, in memory. It is gone when the machine is switched off. `secret_keep` wipes the whole room before it puts a new secret in, so nothing of a longer one stays behind a shorter one. `secret_length` says how long the kept secret is.
- **The secret leaves `secret.rs` in two ways only.** `secret_lend` lends it to `model.rs` only, which sends it to the model's provider as the key (see [model.md](model.md)); the compiler refuses a call from any other file. And `secret_lock` locks it with the password kept beside it (`password_keep`, `password_same`, `password_forget`), for the onboarding (see "The key and the password" above); only the locked form goes to the disk. `secret_unlock` unlocks a locked key straight into the secret's place. A key being tried at the onboarding waits in a room of its own beside the secret (`trial_keep`), is lent to `model.rs` in the same way (`trial_lend`), and then either goes straight into the secret's place (`trial_take`) or is wiped (`trial_forget`). Locking and unlocking take about a second, far too long for device signals to be off, so both copy what they need into rooms of their own with signals off, work there with signals on, and wipe those rooms at the end. No function may be added that prints the secret, shows it or writes it to the disk as it is.
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
- **`chat_answer(answer)`** is how such a row gets in: the main loop calls it when an errand's answer has come, and it hands the sentence to `chat_say`, which adds a row of the kernel's and repeats it in the terminal. The answer to the try of a key goes to the onboarding instead (see "The key and the password" above). Like every function of `chat.rs` they may be called by the main loop only.
- **Each asking reaches the internet:** one question to the name server and one exchange with the site, as at startup.

The word and the page are a demonstration of the road an answer from the network takes into the chat box.

## The look

How the chat box is laid out is one set of values, `CHAT_STYLE` in `chat.rs`: how many rows are shown, how far the chat box stays from the screen's left, right and bottom edges, the thickness of the frame, the size of the letters, how far the text stays from the frame, and the gap between rows. They are fixed when the kernel is built. Its colours come from the look in use (see "The look" in [screen.md](screen.md)): the frame's, the colour behind what was said and behind the row being typed, and the colours of the person's and the kernel's letters. Changing how it looks means changing these values or picking another look, and nothing else.

Its sizes today: six rows, 40 dots from the edges, a frame 3 dots thick, letters at size 2, 10 dots between frame and text, 4 dots between rows. In the first look the frame is orange, the inside light (232, 236, 244), the row for typing white, the person's letters black and the kernel's dark blue (0, 60, 140).

Where the chat box sits and how much fits in it is worked out from the style and the screen's size by `chat_place`, each time it is needed:

- A row is as high as a letter plus the gap: 22 dots today.
- From top to bottom the chat box is the frame, the empty room, the six rows, the row being typed with empty room below it, and the frame: 180 dots today.
- It is as wide as the screen less the margin on both sides, and its bottom edge is one margin above the bottom of the screen. On a screen of 1280 by 800 dots it covers columns 40 to 1239 and rows 580 to 759.
- A row holds as many signs as fit whole between the frame and the empty room on both sides.

The chat box, the box that shows an app's text and the sentence at the top do not touch on screens of 800 by 600 dots and larger. Nothing was tried on a smaller one; there the chat box would be cut off at the screen's edges like everything else, and could lie over the app's box.

## Picking a look

Code: `src/look.rs`. The person at the machine picks the colours of everything on the screen from a short list of looks; see "The look" in [screen.md](screen.md).

- **The line `look`, sent by itself, lists the looks** (`LOOK_WORD`): `Kernel: pick a look by number: 1 Blue, 2 Night, 3 Paper, 4 Contrast. Enter alone keeps this one.`, which is one row of 96 signs on a screen 1280 dots wide. From then on the next line sent is the answer, whatever it says, as with the question for a name. The line `look` itself is kept as the last line, like any other line.
- **A number from the list shows that look at once.** The whole screen is painted again in it, and the kernel says `Kernel: this is look 2, Night. Enter alone keeps it; another number tries that one.` and waits for the next answer, so that another look can be tried. Only digits make a number. Spaces at either end do not count, and a nought in front does no harm.
- **Anything else is asked about again:** `Kernel: that is not the number of a look. Type 1 to 4, or Enter alone to keep this one.`
- **Enter alone ends the question, and the look on the screen stays:**
  - after a look was tried, it is kept in the notebook under the name `look` (see [notebook.md](notebook.md)): `Kernel: look 2, Night, is kept on the disk. Type a line and press Enter.`
  - with nothing tried, or with the look that the notebook holds already, nothing is written: `Kernel: look 2, Night, stays. Type a line and press Enter.`
  - if it cannot be kept, it lasts until the machine is switched off: `Kernel: I could not keep look 2, Night, because the notebook cannot be added to.` and `Kernel: so it lasts only until the machine is switched off. Type a line and press Enter.` That is what a machine without a notebook that can be added to says.
- **The answers are not given back and not kept as the last line.** The person's row shows each one as it was typed.
- **At every later start** the kept look is put in use as soon as the notebook is opened, and the whole screen is painted again in it, with the greeting already in the chat box. Until then the start shows look 1. A look kept under a name that the kernel does not know gives `Kernel: the look kept on the disk is not one I know, so the screen keeps look 1, Blue.`, and one it cannot read gives `Kernel: I cannot read the look kept on the disk, because ...`. Either row comes before the row of the last line, and both come before the questions while one waits. An entry that holds no signs counts as no look kept, and nothing is said.
- **Painting the whole screen again takes about a quarter of a second** in QEMU on the test computer. Keys typed meanwhile wait in the keyboard's line of 16 key numbers, as during locking.
- **On a machine without a usable screen** nothing is painted, but a look can be picked and kept all the same, and the rows go to the terminal.

## Nothing lands outside the chat box

- Every row is written by `chat_write`, which writes only as many signs as fit whole on a row, whatever it is handed. `screen_text` itself stops only at the screen's edges.
- The rows above cannot be more than the style says, because `chat_add` drops the oldest, and each row is at most as long as fits, because `chat_add` cuts a longer text into several.
- With the cut in `chat_write` and the cutting into rows both taken out on purpose, a long answer ran out past the right edge of the chat box on a screen 800 dots wide.

## How it is painted

- `chat_setup` adds one row from the kernel that says what to do, and paints the whole chat box once at startup with `chat_paint`: all of it in the frame's colour, then the two areas inside, which leave the frame showing. `chat_paint` paints it whole again whenever the screen is painted again in another look. Once the notebook is opened, `chat_begin` puts the greeting by name with the question for the password or the key, or the question for a name, in that row's place and paints the rows again.
- After a key, only the row being typed is painted again (`chat_paint_typing`): its area in its colour, then the text.
- After Enter, the rows of what was said are painted again as well (`chat_paint_rows`): their whole area in the inside colour, which wipes out what stood there, then each row. A short row in the place of a long one leaves nothing of the long one.
- This is the first drawing that happens after startup, with device signals on. The timer and the other tasks carry on while the main loop paints.

Measured in QEMU without a window, where ticks can come late, so the times may be up to half as much again: painting the row being typed takes about 8 thousandths of a second, and sending a line about 50. For that half of a tenth of a second the rows are blank and then filled. A person watching a QEMU window saw no flicker.

A key held down types more of its letter: the keyboard itself sends the key again and again, and each arrives as an ordinary key.

Keys wait in the keyboard's line of 16 key numbers while the main loop paints, and each key takes two of them, one for pressing and one for letting go. A sentence of 39 keys and Enter, sent 10 thousandths of a second apart, a hundred keys a second and far faster than anybody types, arrived whole. Sent 5 thousandths apart, or with no pause at all, keys were lost.

## Who may use it

- `CHAT_ROWS` and `CHAT_LINE` are plain `static mut` lists, and so are the secret's rooms in `chat.rs` and `secret.rs`. Nothing protects them. **Only the main loop may call the functions of `chat.rs`.** A second task that added a row, or painted, while the main loop was at work in the same list would break it.
- A task that has something to say in the chat box cannot say it itself. The one way in is an errand's answer, which the main loop picks up and hands to `chat_answer`; see "Errands" in [tasks.md](tasks.md).
- The two lists grow, so they cannot be copied in and out by value like the kernel's other `static mut` values. `chat_rows()` and `chat_line()` hand them out through their addresses instead, and `secret_typed()` does the same for the room a secret is typed into, which must not be copied; and Rust cannot check what happens to a list handed out that way. The rule to keep by hand: after calling another function of `chat.rs`, do not go on using a list that was fetched before the call. Today `chat_key` fetches the typed line, changes it, and only then calls the painting functions, which fetch it again for themselves.
- The heap, which the lists use, is protected against task switches by itself; see [tasks.md](tasks.md).

## Text from outside

What is typed comes from the keyboard, which can only produce plain signs, and the kernel's rows come from its own code. Four texts come from outside the kernel: the line kept on the disk, the name kept there, the locked key, and the name of the look kept there. `chat_begin` takes at most 50 signs of the line, `onboarding.rs` at most 20 of the name, and both turn every byte that is not a plain sign into a dot. The locked key is never shown; `unlock` checks its length and head before it does anything with it (see [lock.md](lock.md)). The look's name is never shown either; `look_begin` only compares it with the names of the looks. Any other text that comes from outside the kernel must be cleaned before it is handed to the chat box, as everywhere else (see `plain_text` in `page.rs`). A sign without a picture would show as an empty box on the screen; in the terminal it would go out as it is.

## How to test it

[testing.md](testing.md) says how to boot without a window, send keys and save pictures of the screen. Habits that proved their worth here:

- **Compare every dot** of a saved picture with a picture built by the checking script, from the style's numbers typed into the script and the grids in `letters.rs`. The script keeps its own account of what the chat box should hold after each key.
- **Take a picture before Enter too.** The point of the chat box is that letters show while they are typed.
- **Wait about half a second after a key before saving a picture.** Sending a line takes a twentieth of a second to paint, and a picture saved in the middle of that shows blank rows, which looks like a fault and is none.
- **Read the terminal as well:** the lines said must be the last lines there, word for word.

## Limits

See [open-points.md](open-points.md). In short: the kernel only gives the line back, takes a secret, fetches one fixed page, asks the model one fixed question, or asks for a name, a key, which it tries, and a password, one task may use the chat box, six rows are shown and of what was said before a switch-off only the last line is said again, only the last sign of a line can be taken away, and the looks to pick from are four, fixed when the kernel is built, which change colours only.
