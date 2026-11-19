# The notebook: named things kept on the disk

The code is in `src/notebook.rs`. The chat box is its first user, in `src/chat.rs`.

The notebook is how the kernel keeps things across a switch-off. A thing is some bytes under a name: `notebook_keep("last line", ...)` keeps it, `notebook_find("last line")` gives it back, also after the machine was switched off and on again. It lives in the kernel's own part of the disk and is written through `part_write`, so it cannot reach any other block of the disk; see [disk.md](disk.md).

## The idea

It works like a paper notebook that is only ever added to.

- Keeping a thing writes a new **entry** behind the last one: the name and the data.
- Nothing already written is ever changed. If a name is kept again, a new entry is written, and the newest entry for a name is the one that counts.
- A power cut in the middle of a write can spoil only the entry that was being written. Every entry before it is whole, because nothing touched it.

The price: old entries stay where they are and take up room, and a notebook can run full. Nothing tidies it yet; see "Limits".

## How the kernel's part is used

Blocks are counted from the beginning of the kernel's part, as `part_read` and `part_write` count them.

| Blocks | What is there |
| --- | --- |
| 0 | The notebook's head |
| 1 to the last but one | The entries, one entry in one block, entry number 1 in block 1, number 2 in block 2, and so on |
| the last | The count of starts, which is not part of the notebook (see [disk.md](disk.md)) |

Room that was never written is zeros. The script that divides a disk file leaves the part as zeros.

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
| 24 to 31 | Zeros |
| 32 on | The name, and right behind it the data. The rest of the block is zeros |

All numbers have their lowest byte first. A name is made of plain signs only (the bytes 32 to 126). The data can be any bytes.

**One entry is one block.** That is why a thing is at most 448 bytes, and it is what makes a write safe against a power cut without more machinery: the disk is given one block, and the entry is either there or not. A thing larger than that needs entries that go over several blocks, which is new work and a new version of the layout.

## Opening the notebook

`notebook_open` runs once at startup, after the kernel's own part is found. It goes through these steps, and writes nothing unless a step says so.

1. **Read block 0.**
   - All zeros: no notebook was ever begun here. The kernel then looks at the eight blocks behind it. If they are zeros too, it writes a head, reads it back, and has a new, empty notebook. If any of them holds something, the part is not empty and the kernel refuses: `my part holds something, but no notebook begins it`. A head that went missing in front of entries must not be answered by starting a new notebook over them.
   - The letters and a fitting check value, version 1: go on.
   - The letters and a fitting check value, another version: refuse with `the notebook is of a version this kernel does not know`. An older kernel must leave a newer layout alone.
   - Anything else: refuse with `the first block of my part holds something I do not know`.
2. **Walk the entries** from block 1. A block counts as the next entry only if all of this is true: the 8 letters are there, its number is the number of the block, both lengths are within their limits, the name is plain signs, and the check value fits. The first block that is not the next entry is the notebook's end. For every entry the kernel remembers the name and the block, the newer entry for a name taking the place of the older, so `notebook_find` needs no search on the disk.
3. **Look behind the end.** The block at the end itself may hold anything: zeros, or an entry that a power cut spoiled, and the next entry will be written over it. But the eight blocks behind that one must be zeros. If one of them holds something, then entries lie behind a block that cannot be read, and writing at the end would write over them. Such a notebook is called damaged: it is read as far as it goes, and nothing is added to it.

Entries are found only by walking from block 1, one block after the other. The kernel never searches the part for something that looks like an entry, so data that happens to look like one, inside a thing that was kept, is never taken for one.

When `notebook_open` refuses, the kernel writes nothing at all to its part during that start. The count of starts is left alone too: `main.rs` counts the start only after the notebook is open.

Everything read from the disk comes from outside the kernel. The two lengths in an entry are held to their limits before they are used for anything, and they can only reach inside the block that was read.

## Keeping and finding

`notebook_keep(name, data)` refuses a name that is empty, longer than 32 bytes or not plain signs, data longer than 448 bytes, a full notebook (`the notebook is full`), and a notebook that cannot be added to. Otherwise it builds the entry's block, writes it with `part_write` to the block behind the last entry, and reads it back. **A thing counts as kept only if the block, read back, is exactly what was written.** Only then does the kernel remember the entry and move the end on. If the write fails, nothing has changed in what the kernel remembers, and the next try goes to the same block.

`part_write` tells the disk to put the block down for good before it comes back (see [disk.md](disk.md)), so a thing that was kept is on the disk when `notebook_keep` returns.

`notebook_find(name)` reads the name's newest entry again from the disk, checks it again, and gives back its data. It gives nothing for a name that was never kept.

`notebook_ready()` says whether things can be kept: the notebook was opened and is not damaged.

## Who may use it

**Only the startup code and the main loop.** The notebook's list of names and the disk's frames are shared state with nothing protecting them, and a disk command takes many steps. This is the first use of the disk after startup, with device signals on: a timer signal can now take the processor away in the middle of a command. That does no harm as long as no other task uses the disk, because the command is simply carried on afterwards. A task that wants something kept or found has to ask the main loop, and nothing lets it do that yet.

The disk controller sends no signals; the kernel looks until a command is finished, as at startup. While it looks, the main loop does nothing else: keys pressed in the meantime wait in the keyboard's waiting line.

## The first user: the chat box

When a line is sent with Enter, `chat_key` keeps it under the name `last line`. At startup, `chat_begin` finds that name and, if a line is there, adds the row `Kernel: last time you said "..."` to the chat box and prints the same line through the serial port.

The person's name is kept too, under the name `name`, by `onboarding.rs`: the answer to the question the kernel asks at a start where the notebook holds no name, or after the line `setup`. An entry under `name` that holds no signs means that the answer was to stay `You`. Whether such an entry is there at all is what tells a start whether to ask. See "The name" in [chat.md](chat.md).

The model's key is kept under the name `locked key`, by `onboarding.rs`, and only locked with a password (see [lock.md](lock.md)): at most 250 bytes, a head, the scrambled key and a proof. An entry under `locked key` that holds no signs means that the question for the key was answered without one. Whether such an entry is there, and whether it holds a locked key, is what tells a start whether to ask for the key, for the password, or for nothing. A new key locked after `setup` is a new entry that counts from then on; the one before stays in the notebook, like every entry, and opens with the old password. See "The key and the password" in [chat.md](chat.md).

- If the line was kept, nothing is said about it.
- If it could not be kept, the kernel says so in a row and in the terminal, `Kernel: I could not keep that line, because ...`, and the chat goes on as before.
- On a machine with no disk, no part of the kernel's own, or a notebook that cannot be added to, the chat box says nothing about keeping; the lines at startup have said it.
- The kept line comes from the disk, so it is treated as text from outside: at most 50 signs of it are shown, and every byte that is not a plain sign becomes a dot.

## What a boot prints

One line, after the line about the kernel's own part and before the count of starts:

| Line | When |
| --- | --- |
| `Disk: a new notebook was begun, with room for 30685 entries` | The part held nothing |
| `Disk: the notebook holds 2 entries and has room for 30683 more` | A notebook was there |
| `Disk: the notebook holds 2 entries and is damaged behind that; nothing is added to it` | Something lies behind the notebook's end |
| `Disk: nothing is kept on it, because ...` | The part holds something the kernel does not know. No count of starts follows |

And, after the count of starts, the chat box's rows from the notebook: the greeting by the kept name, or the question for a name, and `Kernel: last time you said "..."` if a line was kept. See [chat.md](chat.md).

## How long it takes

Opening reads every entry, one block per command, so a start takes longer the more entries there are. The measured times are in [testing.md](testing.md).

## Limits

- **Nothing tidies the notebook.** Entries that a newer one has replaced stay, and a full notebook stays full: keeping is refused until tidying exists. The disk file in QEMU has room for 30,685 entries.
- **A thing is at most 448 bytes**, and a name at most 32.
- **A damaged notebook is not repaired.** It is read up to the damage and nothing is added.
- **Only eight blocks behind the end are looked at.** Something further behind, with eight blocks of zeros before it, is not noticed, and entries written later would reach it.
- **Nothing can be taken out.** A name, once kept, has a thing for good; it can only be replaced.
- **Opening reads the whole notebook**, one block at a time.
- **One user at a time**, and only from startup and the main loop.
