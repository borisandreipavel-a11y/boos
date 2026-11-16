# Memory: the map, frames, page tables, the heap

Code: `src/frames.rs`, `src/page_tables.rs`, `src/heap.rs`. The memory map itself is saved by `take_over` in `src/firmware.rs`.

The three pieces build on each other:

- **Frames** hand out real memory, 4096 bytes at a time.
- **Page tables** decide what sits behind each address. They need frames for their tables.
- **The heap** hands out pieces of any size. It needs frames, and page tables to line scattered frames up as one stretch.

## The memory map

The firmware's map lists stretches of memory, each with a kind:

| Kind | What it is | Handed out? |
| --- | --- | --- |
| 1, 2 | The loaded program: the kernel itself | Never |
| 3, 4 | Memory the firmware used during startup ("boot services") | Not yet, see below |
| 5, 6 | Memory the firmware still uses afterwards ("runtime services") | Never |
| 7 | Free | Yes, from 1 MB up |
| 9, 10 | The firmware's tables about the machine (ACPI) | No |
| 0, 11, 12 and others | Unusable stretches and devices | No |

- Kinds 1 to 7, 9 and 10 count as real memory when working out where memory ends.
- QEMU's map also has a kind 0 stretch at `0xfd00000000`, 12 GB long. It is not memory. Counting it would make the page tables cover a terabyte.
- Kinds 3 and 4 are about 42 MB of QEMU's 256 MB. The firmware no longer needs them, but they are not handed out, because the kernel still runs on the firmware's stack, which sits in a kind 4 stretch (near `0xfe65600` in QEMU). The firmware's old page tables are in kind 4 too. They can be reclaimed once the kernel runs on a stack of its own.

## Frames

- A frame is 4096 bytes of real memory (`FRAME_SIZE`).
- `frames_setup(map_size, entry_size)` walks the saved map once. It puts every kind 7 frame at or above 1 MB on a pile and returns the address where real memory ends.
- The first megabyte is skipped. It holds leftovers of the old PC design, and skipping it keeps address 0 free to mean "no frame".
- The pile is a linked list kept inside the free frames themselves. `TOP_FREE_FRAME` is the top, the first 8 bytes of each free frame hold the address of the next, 0 ends the list, and `FREE_FRAMES` counts them.
- `frame_take()` returns the address of a frame. `frame_give_back(frame)` returns one.
- `frame_take` panics with "the machine is out of memory" when the pile is empty.
- A frame's contents are whatever was there before. Zero it if that matters, as `empty_table` does.
- Building the pile writes to every free frame once at startup. On a virtual machine that makes the host really provide all of the guest's memory.
- "Free memory" at boot reads 206 MB on QEMU's 256 MB machine. Before frames existed it read 207, because the first megabyte was still counted.

## Page tables

- The processor looks every address up in the page tables. There are 4 levels, each table is one frame of 512 lines, and each level uses 9 bits of the address. A line at level 1 names one frame. A line at level 2 may instead name a 2 MB "big page".
- `page_tables_setup(memory_end)` builds the kernel's own tables and loads their top table into `cr3`. In them every address leads to itself, as in the firmware's tables, so every address already in use keeps working.
- That self-leading range uses 2 MB pages and runs from 0 to 4 GB, or to the end of memory if that is higher, rounded up to a whole GB. The 4 GB are there because a PC keeps its devices below that mark.
- Before the switch, the kernel itself, its stack and every frame must lie inside the covered range. They do, because all of them are real memory.
- `map_page(address, frame)` makes one 4096-byte page lead to a frame, creating the tables it needs on the way. `table_line` picks a line of a table; `table_below` follows a line down or creates the next table.
- **`map_page` must not be used inside the range covered by 2 MB pages.** `table_below` would mistake a 2 MB line for a table and corrupt memory.
- Every page is writable and nothing is protected. The firmware left write protection on (`cr0` bit 16), so a page mapped without the writable mark would refuse writes even from the kernel.
- Nothing is ever unmapped. If that changes, the processor must be told to forget the page (`invlpg`), which no code does yet.
- The kernel assumes 4-level tables. See [open-points.md](open-points.md) for 5-level machines.

## The heap

- The heap lives at made-up addresses from `HEAP_START = 0x4000_0000_0000` (64 TB) upward, far above the self-leading range, so its pages never collide with the 2 MB pages.
- A request is rounded up to a power of two: at least 16 bytes and at least the wanted alignment (`heap_piece_size`). Alignment is the number the piece's address must be a multiple of.
- `HEAP_PILES[n]` is a pile of returned pieces of size 2^n, built like the frame pile. Pile 4 holds the 16-byte pieces.
- `heap_take(size, align)`:
  - hands out a returned piece from the right pile if there is one;
  - otherwise cuts a new piece at `HEAP_END`, at an address that is a multiple of the piece's own size, and maps fresh frames as needed. `HEAP_MAPPED` is how far the heap has frames behind it.
- `heap_give_back(piece, size, align)` puts a piece on its pile. It must be given the same size and alignment as the request.
- Because a piece's address is a multiple of its size, any piece on a pile fits any request for that pile, whatever alignment it asks for.
- A returned piece keeps its old contents except the first 8 bytes.

Known limits:

- A request can take up to twice its size. A 5 MB list takes an 8 MB piece.
- Frames never go back from the heap to the frame pile. A returned piece is only reused for requests of the same pile.
- Running out of memory stops the kernel with a panic, instead of refusing the one request.
- The heap has no setup step. Its first request must come after `page_tables_setup`.

## Rust's lists and text

- `alloc` is the part of Rust's own library with `Vec` (a list) and `String` (a text). It ships with Rust next to `core`; nothing is downloaded and `Cargo.toml` is unchanged.
- `KernelHeap` with `#[global_allocator]` in `heap.rs` is the thin layer that connects it: `alloc` calls `heap_take` and `heap_give_back` by itself.
- To drop `alloc` again: remove `extern crate alloc;` and the two `use alloc::...` lines and the heap demonstration in `main.rs`, and the `KernelHeap` block in `heap.rs`. `heap_take` and `heap_give_back` work without it.

## Not protected against signals

The frame pile, the page tables and the heap are plain global state. If a signal handler used them while the main code was in the middle of them, they would be corrupted. Today that cannot happen, because handlers never use them. Before tasks can be switched in the middle of a heap call, this needs protection, for example by switching signals off around the memory code.
