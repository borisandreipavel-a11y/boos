# Building, running and verifying

There are no automated tests. The kernel is verified by booting it in QEMU and reading what it prints. This file says how, what has been verified so far, and which traps cost time before.

**Rule:** if you can run commands on the machine, build and boot to verify each change before calling it done. Say plainly what was tested and what was not.

## Build and run

- `cargo build` builds `target\x86_64-unknown-uefi\debug\boos.efi`.
- `run.bat`, run from the project root, builds, copies that file to `esp\EFI\BOOT\BOOTX64.EFI` and starts QEMU with 256 MB, no network, the UEFI firmware file, the `esp` folder as a disk, and the serial port connected to the terminal.
- The kernel's output appears in the terminal, not in the QEMU window. Keys are typed in the QEMU window, not in the terminal.
- What a normal boot prints is listed in [startup.md](startup.md).

## Booting without a window

Use the same QEMU options as `run.bat`, with these changes:

- add `-display none -no-reboot`;
- replace `-serial stdio` with `-serial file:<path>` and read that file;
- add `-monitor tcp:127.0.0.1:<port>,server=on,wait=off` to control QEMU from outside.

`-no-reboot` makes QEMU exit when the machine resets, so a reset is noticed instead of looping.

The monitor is a plain text connection. From PowerShell:

```powershell
$client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", $port)
$writer = New-Object System.IO.StreamWriter($client.GetStream())
$writer.NewLine = "`n"; $writer.AutoFlush = $true
$writer.WriteLine("sendkey a")      # press and release a key
Start-Sleep -Milliseconds 250       # one key at a time
$writer.WriteLine("quit")           # always end QEMU this way
```

Monitor commands that proved useful:

| Command | What it gives |
| --- | --- |
| `sendkey a`, `sendkey ret`, `sendkey spc`, `sendkey shift-a` | A key press, as if typed in the window |
| `mouse_move 20 20`, `mouse_button 1`, `mouse_button 0` | Mouse movement and clicks |
| `info registers` | Where the processor is (`RIP`), whether it sleeps (`HLT=1`), `CR3` |
| `info mem` | What the current page tables cover |
| `info pic`, `info irq` | The interrupt controller's state and how many signals each line sent |
| `quit` | Ends QEMU |

The serial file can be read while QEMU runs if it is opened with shared read and write access (`[System.IO.File]::Open(path, 'Open', 'Read', 'ReadWrite')`).

Other QEMU options that proved useful:

| Option | Use |
| --- | --- |
| `-d int,cpu_reset -D <log file>` | Logs every failure and signal. After a silent reset, the last exception's `CR2` is the address the page tables miss |
| `-m 64M`, `-m 512M` | Other memory sizes (a later `-m` overrides the first) |
| `-machine pc,max-ram-below-4g=128M` | Puts the rest of the guest's memory above 4 GB, without needing a large guest |
| `-machine pc,i8042=off` | A machine without a keyboard controller |

## Temporary tests

Checks that need code inside the kernel are done with a temporary snippet:

1. Keep a copy of the file to change.
2. Put the snippet just above a known line of `efi_main` in `src/main.rs`. Two places serve most needs:
   - above `// Get the devices ready, then let their signals through.` for code that runs once, with signals still off;
   - above `if seconds > seconds_shown && seconds <= 3 {` in the main loop for code that runs with signals on. Guard it with `if seconds == 2 { ... }` to run it two seconds in.
3. Build, boot, read the output.
4. Put the copy back, then build again.

A snippet that needs something private in another file can add `pub` there for the test. Put that back too.

## Deliberate bugs

These prove that problems are reported. Each stops the kernel with one line.

| Snippet | Expected line |
| --- | --- |
| `unsafe { asm!("div ecx", in("ecx") 0u32, inout("eax") 1u32 => _, inout("edx") 0u32 => _) };` | `CPU fault: divide by zero at 0x...` |
| `unsafe { *(0xFFFF_8000_0000_0000u64 as *mut u8) = 1 };` | `CPU fault: page fault at 0x..., touching 0xffff800000000000, detail code 0x2` |
| `let list = alloc::vec![1u8, 2, 3]; let index = seconds as usize + 5; write!(serial, "{}", list[index]).ok();` | `Kernel panic: src\main.rs:<line>: index out of bounds: the len is 3 but the index is 7` |
| `let huge: Vec<u8> = Vec::with_capacity(300 * 1024 * 1024);` on a 256 MB machine | `Kernel panic: src\frames.rs:<line>: the machine is out of memory` |

A panic line names the file the panic is in, so the file name changes when code moves.

## Traps

- **A QEMU left running** keeps the serial file and `BOOTX64.EFI` locked, and the next run then shows the old output. Always end QEMU with `quit`, or kill it, and check that none is left.
- **Cutting a script's output short** (for example with `Select-Object -First 1`) can end the script before it sends `quit`. That leaves a QEMU running.
- **Restoring a file by copying a backup** keeps the backup's old timestamp, and `cargo build` then skips the rebuild and the old kernel is booted. Set the file's time to now before building.
- **`powershell -File script.ps1 -Keys a,b,c`** passes `a,b,c` as one string. Use `powershell -Command "& 'script.ps1' -Keys a,b,c"` to pass a list.
- **Memory on the host.** The frame pile writes to every free frame at startup, so the host must really provide all of the guest's memory. On a host with about 1 GB free, guests were kept at 512 MB or less.
- **Timing on a busy host.** The kernel's clock counts timer signals. In a few windowless runs on a loaded host the three timer lines came about 1.5 s apart instead of 1.0 s. The kernel before the memory work and the one after it showed the same 1.0 s when compared side by side afterwards, so it was the host delivering signals late.
- **The linker blocked once.** One build stopped with "An Application Control policy has blocked this file" for `rust-lld`. The same build worked when run again, and nothing was changed in between.

## What has been verified

All of it in QEMU 11.1 with its UEFI firmware, on Windows, on 2026-11-16. Nothing has run on real hardware.

**Serial output and the takeover**

- The first two pieces (serial output, the takeover) were at first only checked by compiling. They were then booted in QEMU, where the boot lines appear.
- The serial setup was booted with and without a serial port present. Without one the kernel runs but prints nothing. How that silent case was confirmed is not recorded.

**Failures**

- The divide-by-zero, page-fault and out-of-range-index bugs each print their report. They were repeated after each later piece of work, also with device signals switched on.

**Timer and keyboard**

- The timer lines appeared 1.0 s apart by the wall clock.
- Keys sent with `sendkey` were echoed (`hello boos`, digits, punctuation, Enter). Shift, the arrows, F1 and Esc printed nothing, as intended.
- A temporary test filled the nine saved registers with known values, slept through 300 timer signals and found them unchanged. With the stub broken on purpose (two registers not saved), the same test showed the damage.
- Mouse movement and clicks between key presses did not silence the keyboard.
- With no keyboard controller, the kernel boots and the timer runs.
- A person typed in the QEMU window and saw the letters in the terminal.

**Memory**

- Frames: 1000 frames taken were all different, all inside free stretches of the map, each held its own pattern, and giving them back restored the count.
- Page tables: `cr3` holds the kernel's top table, not the firmware's. `info mem` shows 0 to 4 GB leading to itself plus the heap's pages. Bytes written through a heap address were read back through the frame's own address, and the other way round.
- A read just past the heap's last frame prints a page fault report.
- Heap: three rounds of 1000 patterned pieces of 1 byte to 200 KB, returned out of order, with no wrong byte. A returned piece is handed out again at the same address. A 5 MB list used 2052 frames the first time and none the second. Alignments from 1 byte to 2 MB were honoured.
- Heap work without pause for 2.5 s with timer signals arriving (243 of 3994 rounds were interrupted) gave no wrong result. The keyboard echo still worked afterwards.
- It boots with 64 MB, 128 MB and 512 MB, and with memory placed above 4 GB, where the tables cover 5 GB.
- A person ran it and saw the three memory lines.

**The split into files**

- Every line of code in the old single file appears unchanged in the new files; only `pub`, `mod` and `use` were added and comments changed.
- The split kernel and the single-file kernel printed the same lines for the same keys. Four deliberate bugs printed their reports.
- A person ran it and saw the same lines and the key echo as before.

**Not verified**

- Real hardware of any kind.
- Machines with several GB of memory.
- Keyboards with a layout other than US.

## Oddities seen once

- **One silent boot.** One boot out of roughly a hundred printed "Hello from my kernel!" and then nothing, with QEMU still running. It was the first boot of the build that added the heap, it stopped before any memory code runs, and it did not come back in 56 further boots, 20 of them with the compiler running alongside. Unexplained. If it comes back, `info registers` tells the two candidates apart: a processor asleep in the main loop (`HLT=1`) means the serial port test failed and the kernel is only mute; anything else means it is stuck.
