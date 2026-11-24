# The notebook: named things kept on the disk

The code is in `src/notebook.rs`. The chat box is its first user, in `src/chat.rs`.

The notebook is how the kernel keeps things across a switch-off. A thing is some bytes under a name: `notebook_keep("last line", ...)` keeps it, `notebook_find("last line")` gives it back, also after the machine was switched off and on again. It lives in the kernel's own part of the disk and is written through `part_write`, so it cannot reach any other block of the disk; see [disk.md](disk.md).

## The idea

It works like a paper notebook that is only ever added to.

- Keeping a thing writes a new **entry** behind the last one: the name and the data. A thing longer than one entry holds is written as several entries, one right behind the other (see "A thing in pieces" below).
- Nothing already written is ever changed. If a name is kept again, a new entry is written, and the newest entry for a name is the one that counts.
- A power cut in the middle of a write can spoil only the entry that was being written. Every entry before it is whole, because nothing touched it. A thing in pieces that a power cut interrupted does not count, and the thing kept under its name before still does.

The price: old entries stay where they are and take up room, and a notebook can run full. Nothing tidies it yet; see "Limits".

## How the kernel's part is used

Blocks are counted from the beginning of the kernel's part, as `part_read` and `part_write` count them.

| Blocks | What is there |
| --- | --- |
| 0 | The notebook's head |
| 1 to the one before the middle | The entries, one entry in one block, entry number 1 in block 1, number 2 in block 2, and so on |
| the middle (`blocks / 2`) to the last but one | The room for files: its head, then the files (see "The room for files" in [disk.md](disk.md)) |
| the last | The count of starts, which is not part of the notebook (see [disk.md](disk.md)) |

Room that was never written is zeros. The script that divides a disk file leaves the part as zeros.

The room for files is there only on a part of 4096 blocks or more, and only while the notebook ends more than eight blocks in front of the middle, or once the room's head stands there. Otherwise the entries may use the blocks from 1 to the last but one, as before there were files: on a smaller part, on a part whose middle block holds something else, and when the notebook reaches into the room. On the usual disk file the notebook has room for 15,342 entries, where it had 30,685.

### The head

| Bytes | What |
| --- | --- |
| 0 to 15 | The 16 letters `boos notebook   ` (three spaces at the end) |
| 16 to 19 | The version of the layout, a number, lowest byte first. It is 1 |
| 20 to 23 | A check value of bytes 0 to 19 (the same CRC-32 as the disk's list of parts uses, `check_value` in `parts.rs`) |
| the rest | Zeros |

### An entry

| Bytes | What |
| --- | --- |
| 0 to 7 | The 8 letters `boosnote` |
| 8 to 15 | The entry's number, counted from 1. It is the same as the number of the block it lies in |
| 16 to 17 | How many bytes long the name is: 1 to 32 |
| 18 to 19 | How many bytes long the data is: 0 to 448 |
| 20 to 23 | A check value of the whole block of 512 bytes, worked out with these four bytes as zeros |
| 24 to 25 | For a piece of a longer thing: which piece it is, counted from 1. Zeros for a thing of one entry |
| 26 to 27 | For a piece: how many pieces the thing has, 2 to 74. Zeros for a thing of one entry |
| 28 to 31 | For a piece: a check value of all of the thing's data, the same CRC-32, the same in every piece. Zeros for a thing of one entry |
| 32 on | The name, and right behind it the data. The rest of the block is zeros |

All numbers have their lowest byte first. A name is made of plain signs only (the bytes 32 to 126). The data can be any bytes.

**One entry is one block.** That is what makes a write safe against a power cut without more machinery: the disk is given one block, and the entry is either there or not. An entry holds at most 448 bytes of data; a longer thing is kept in pieces, each of them a whole entry.

### A thing in pieces

- **A thing of up to 448 bytes is one entry,** with bytes 24 to 31 zeros: exactly the entry the kernel wrote before pieces existed.
- **A longer thing, up to 32 KB** (`THING_MOST`, as much as the longest script the box takes), **is kept in pieces:** as many entries as it needs, one right behind the other, each under the thing's name. Every piece but the last holds 448 bytes of the data, and the last holds the rest, 1 to 448 bytes. Bytes 24 to 31 of each say which piece it is and how many there are, and hold a check value of all of the data. 32 KB takes 74 pieces.
- **The thing counts only when it is whole:** all of its pieces in a row and in order, under the same name, with the same count and the same check value, and the check value of all of their data fits. Only then does it take the place of the thing kept under that name before.
- **A power cut in the middle** of keeping a thing in pieces leaves the pieces written so far as whole entries, and at most the block that was being written spoiled, which is then the notebook's end, as for any entry. At the next start the thing that never got finished is passed over: its pieces take room and count for nothing, and the thing kept under that name before, if there is one, still counts. The next entry goes over the spoiled block.
- **What a piece says never decides whether a block is an entry.** The notebook's end is found exactly as before pieces existed; bytes 24 to 31 only decide whether a thing counts. An entry whose eight bytes are neither zeros nor a sound piece (a piece number of 0, a count of 1 or above 74, a piece past the count, a piece before the last that is not full, an empty last piece, more than 32 KB in all) is an entry all the same, and belongs to no thing. So does a piece that does not follow the piece before it.
- **The layout's version stayed 1.** A kernel from before pieces reads every piece as an entry of its own, under its thing's name, which it never asks for, and adds its own entries behind the end as before; nothing it keeps is long enough to need pieces. So both kinds of kernel can use one notebook without harm. A new version would have made the older kernel refuse the whole notebook, and would have meant writing block 0 again, the one block whose loss loses everything kept.

## Opening the notebook

`notebook_open` runs once at startup, after the kernel's own part is found. It goes through these steps, and writes nothing unless a step says so.

0. **The room for files** is looked at first, by `files.rs`: whether the part is large enough for one, and whether its head stands in the middle block. The notebook is then told where the room begins and whether its head is there (see "The room for files" in [disk.md](disk.md)).
1. **Read block 0.**
   - All zeros: no notebook was ever begun here. The kernel then looks at the eight blocks behind it. If they are zeros too, it writes a head, reads it back, and has a new, empty notebook. If any of them holds something, the part is not empty and the kernel refuses: `my part holds something, but no notebook begins it`. A head that went missing in front of entries must not be answered by starting a new notebook over them.
   - The letters and a fitting check value, version 1: go on.
   - The letters and a fitting check value, another version: refuse with `the notebook is of a version this kernel does not know`. An older kernel must leave a newer layout alone.
   - Anything else: refuse with `the first block of my part holds something I do not know`.
2. **Walk the entries** from block 1, up to the block before the room for files when its head is there, so that no block of a file is ever read as an entry, or else up to the last but one. When the room for files has no head yet, it is left to the files after the walk only if the notebook ended more than eight blocks in front of it; then the notebook's room ends in front of it. A block counts as the next entry only if all of this is true: the 8 letters are there, its number is the number of the block, both lengths are within their limits, the name is plain signs, and the check value fits. The first block that is not the next entry is the notebook's end. For every whole thing the kernel remembers the name, the block it begins in and how many entries it takes, the newer thing for a name taking the place of the older, so `notebook_find` needs no search on the disk. Pieces are put together as they come, and a thing in pieces is remembered only once its last piece is there and its check value fits (see "A thing in pieces"): opening reads every piece and checks every thing in pieces whole.
3. **Look behind the end.** The block at the end itself may hold anything: zeros, or an entry that a power cut spoiled, and the next entry will be written over it. But the eight blocks behind that one must be zeros. If one of them holds something, then entries lie behind a block that cannot be read, and writing at the end would write over them. Such a notebook is called damaged: it is read as far as it goes, and nothing is added to it.

Entries are found only by walking from block 1, one block after the other. The kernel never searches the part for something that looks like an entry, so data that happens to look like one, inside a thing that was kept, is never taken for one.

When `notebook_open` refuses, the kernel writes nothing at all to its part during that start. The count of starts is left alone too: `main.rs` counts the start only after the notebook is open.

Everything read from the disk comes from outside the kernel. The two lengths in an entry are held to their limits before they are used for anything, and they can only reach inside the block that was read.

## Keeping and finding

`notebook_keep(name, data)` refuses a name that is empty, longer than 32 bytes or not plain signs, data longer than 32 KB (`the thing is too long for the notebook`), a notebook without room for all of the thing's entries (`the notebook is full`; then nothing is written), and a notebook that cannot be added to. Otherwise it builds the entry's block, or each piece's, writes it with `part_write` to the block behind the last entry, and reads it back. **An entry counts as written only if the block, read back, is exactly what was written, and a thing counts as kept only when all of its entries do.** Only then does the kernel remember the thing. If the write of a thing of one entry fails, nothing has changed in what the kernel remembers, and the next try goes to the same block. For a thing in pieces, once a piece is on the disk the next entry goes behind it, whatever happens to the rest: so what the kernel remembers is always what opening the notebook again would find. If a piece cannot be written, the pieces before it stay as entries of a thing that never got finished, and the thing kept under the name before still counts.

`part_write` tells the disk to put the block down for good before it comes back (see [disk.md](disk.md)), so a thing that was kept is on the disk when `notebook_keep` returns.

`notebook_find(name)` reads the name's newest thing again from the disk, checks every entry of it again (that it is still a whole entry under that name, and for a piece, the right piece of the same thing), puts the pieces together, checks the check value of all of the data, and gives back the data. It gives nothing for a name that was never kept.

`notebook_names()` gives the names kept, in the order in which their newest whole things were kept, the oldest first.

`notebook_ready()` says whether things can be kept: the notebook was opened and is not damaged.

## Who may use it

**Only the startup code and the main loop.** The notebook's list of names and the disk's frames are shared state with nothing protecting them, and a disk command takes many steps. This is the first use of the disk after startup, with device signals on: a timer signal can now take the processor away in the middle of a command. That does no harm as long as no other task uses the disk, because the command is simply carried on afterwards. A task that wants something kept or found has to ask the main loop, and nothing lets it do that yet.

The disk controller sends no signals; the kernel looks until a command is finished, as at startup. While it looks, the main loop does nothing else: keys pressed in the meantime wait in the keyboard's waiting line.

## The first user: the chat box

When a line is sent with Enter, `chat_key` keeps it under the name `last line`. At startup, `chat_begin` finds that name and, if a line is there, adds the row `Kernel: last time you said "..."` to the chat box and prints the same line through the serial port.

The person's name is kept too, under the name `name`, by `onboarding.rs`: the answer to the question the kernel asks at a start where the notebook holds no name, or after the line `setup`. An entry under `name` that holds no signs means that the answer was to stay `You`. Whether such an entry is there at all is what tells a start whether to ask. See "The name" in [chat.md](chat.md).

The model's key is kept under the name `locked key`, by `onboarding.rs`, and only locked with a password (see [lock.md](lock.md)): at most 250 bytes, a head, the scrambled key and a proof. An entry under `locked key` that holds no signs means that the question for the key was answered without one. Whether such an entry is there, and whether it holds a locked key, is what tells a start whether to ask for the key, for the password, or for nothing. A new key locked after `setup` is a new entry that counts from then on; the one before stays in the notebook, like every entry, and opens with the old password. See "The key and the password" in [chat.md](chat.md).

The look picked by the model with the tool `pick_look`, or by the person at the onboarding's question, is kept under the name `look`, by `look.rs`, as the look's name (`Night`), not locked: a new entry each time a look is kept, and none while looks are only tried. An entry under `look` that holds no signs means that the question was answered without a pick; the line `setup` keeps one too, at once, when the notebook holds another look, so that the next start shows the first look. At startup the newest entry under `look` decides which look the screen shows, and whether the question is asked: with no entry, or with a name the kernel does not know (which leaves the first look), it is asked; an entry that holds no signs leaves the first look and asks nothing. See "Picking a look" in [chat.md](chat.md).

Files fetched from the web are kept in the room for files, and noted under the names `file 1`, `file 2` and so on, by `files.rs`, once each file is on the disk and read back: where it lies, how long it is, its check value, its kind, its name, when it came and where from. A removed file's note is replaced by one that holds nothing. The sites the person allowed a fetch from are kept under `site 1`, `site 2` and so on, each holding the site's name. See "The room for files" in [disk.md](disk.md) and "download_file" in [tools.md](tools.md).

Apps the model made are kept under the names `app 1`, `app 2` and so on, by `apps_kept.rs`, once they have run to their end: `app 1 script` holds the script, exactly as it ran, and `app 1` a note with the request it was made for. A script longer than 448 bytes is kept in pieces. See "Keeping an app" in [apps.md](apps.md).

Tables the model described are kept as documents by `documents.rs`, where documents can be kept (see "Documents" in [screen.md](screen.md)). Each version of a document is a thing of its own: `document 1 v2` holds the lines of the second version of document 1, up to 4,096 bytes, in pieces when they are longer than 448 bytes (at most 10 entries). `document 1` is a note that names the newest version, kept again with every version: its first byte, 1, says what form the rest has; in form 1 a byte for the kind of document (1, a table), the newest version's number in four bytes, lowest first, and the document's name, at most 45 bytes. A document made from a kept file (see `open_file` in [tools.md](tools.md)) has a note of form 2, first byte 2: the same, with the file's number in four bytes, lowest first, between the version's number and the name, in the note of every version; a document made from no file keeps form 1, as before form 2 existed. A kernel from before form 2 does not know a note of form 2: by its code (read, not tried), it leaves that document out at a start without a word, and could give its number to a new document of its own, whose note would then take the old one's place. A version's lines are kept first and read back, byte for byte, and only then the note, so a power cut between the two leaves the version before counting. Older versions stay as things of their own, out of reach until going back to one exists. The longest names, `document 999999999` and `document 999999999 v999999999`, are 18 and 29 bytes.

- If the line was kept, nothing is said about it.
- If it could not be kept, the kernel says so in a row and in the terminal, `Kernel: I could not keep that line, because ...`, and the chat goes on as before.
- On a machine with no disk, no part of the kernel's own, or a notebook that cannot be added to, the chat box says nothing about keeping; the lines at startup have said it.
- The kept line comes from the disk, so it is treated as text from outside: at most 200 signs of it are shown, as many as a line may have, and every byte that is not a plain sign becomes a dot. The same signs are what Up brings back into the row being typed (see [chat.md](chat.md)). A line of 200 signs fits in one entry.

## What a boot prints

One line, after the line about the kernel's own part and before the room for files' line and the count of starts:

| Line | When |
| --- | --- |
| `Disk: a new notebook was begun, with room for 15342 entries` | The part held nothing |
| `Disk: the notebook holds 2 entries and has room for 15340 more` | A notebook was there |
| `Disk: the notebook holds 2 entries and is damaged behind that; nothing is added to it` | Something lies behind the notebook's end |
| `Disk: nothing is kept on it, because ...` | The part holds something the kernel does not know. No count of starts follows |

And, after the count of starts, the chat box's rows from the notebook: the greeting by the kept name, or the question for a name, and `Kernel: last time you said "..."` if a line was kept. See [chat.md](chat.md). If a look is kept that the kernel cannot use, a row says so; see "Picking a look" there.

## How long it takes

Opening reads every entry, one block per command, so a start takes longer the more entries there are. A piece is read like any entry. The measured times are in [testing.md](testing.md).

## Limits

- **Nothing tidies the notebook.** Entries that a newer one has replaced stay, and a full notebook stays full: keeping is refused until tidying exists. The disk file in QEMU has room for 15,342 entries in front of the room for files (30,685 before there were files); every line sent takes one.
- **A thing is at most 32 KB**, kept in at most 74 entries, and a name is at most 32 bytes.
- **A thing in pieces that never got finished takes room for good,** like every entry a newer one replaced.
- **A damaged notebook is not repaired.** It is read up to the damage and nothing is added.
- **Only eight blocks behind the end are looked at.** Something further behind, with eight blocks of zeros before it, is not noticed, and entries written later would reach it.
- **Nothing can be taken out.** A name, once kept, has a thing for good; it can only be replaced.
- **Opening reads the whole notebook**, one block at a time.
- **One user at a time**, and only from startup and the main loop.
