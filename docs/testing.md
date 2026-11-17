# Building, running and verifying

There are no automated tests. The kernel is verified by booting it in QEMU and reading what it prints. This file says how, what has been verified so far, and which traps cost time before.

**Rule:** if you can run commands on the machine, build and boot to verify each change before calling it done. Say plainly what was tested and what was not.

## Build and run

- `cargo build` builds `target\x86_64-unknown-uefi\debug\boos.efi`.
- The very first build on a computer fetches six small crates from crates.io, so it needs the internet once. After that, building works without it. The network stack itself is not fetched; it is a copy in `vendor/`.
- `run.bat`, run from the project root, builds, copies that file to `esp\EFI\BOOT\BOOTX64.EFI` and starts QEMU with 256 MB, a virtio network card on QEMU's built-in network, the UEFI firmware file, the `esp` folder as a disk, and the serial port connected to the terminal.
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
| `info pci` | QEMU's own PCI list: each device's place, maker and model, signal line, ports and memory |
| `info network` | The network cards and what they are attached to |
| `info virtio` | The path of each virtio device, needed by the next two |
| `info virtio-status <path>` | How far a virtio device's handshake has got, and which features are in use |
| `info virtio-queue-status <path> <line>` | The length of one of its waiting lines and the addresses of its three areas |
| `quit` | Ends QEMU |

The serial file can be read while QEMU runs if it is opened with shared read and write access (`[System.IO.File]::Open(path, 'Open', 'Read', 'ReadWrite')`).

Other QEMU options that proved useful:

| Option | Use |
| --- | --- |
| `-d int,cpu_reset -D <log file>` | Logs every failure and signal. After a silent reset, the last exception's `CR2` is the address the page tables miss |
| `-m 64M`, `-m 512M` | Other memory sizes (a later `-m` overrides the first) |
| `-machine pc,max-ram-below-4g=128M` | Puts the rest of the guest's memory above 4 GB, without needing a large guest |
| `-machine pc,i8042=off` | A machine without a keyboard controller |
| `-object filter-dump,id=dump0,netdev=net0,file=<path>` | Records every packet on the card's network in a file (pcap format: a 24-byte header, then each packet behind a 16-byte header whose third 4-byte field is the packet's length). A file of 24 bytes means no packet passed. A normal boot records six: the by-hand gateway question and its answer, then the four packets of the address request |
| `-netdev user,id=net0,net=192.168.76.0/24,dhcpstart=192.168.76.9` | QEMU's built-in network with other addresses, to show that the kernel's address is given and not assumed |
| `-device virtio-net-pci` with no `-netdev` | A card attached to nothing, so nobody can answer |
| `-net none` in place of the `-netdev` and `-device` options | A machine without a network card |
| `-device virtio-net-pci-non-transitional,netdev=net0` | The virtio card that knows only the newer way of working (model `1041`) |
| `-device e1000,netdev=net0` | A network card of another make |
| `-device virtio-net-pci,netdev=net0,mac=52:54:00:aa:bb:cc` | The card with another address of its own |
| `-device virtio-net-pci,netdev=net0,disable-modern=on` | The card with its newer way of working switched off |
| `-device virtio-net-pci,netdev=net0,addr=0x10` | The card in another slot |
| `-device pci-bridge,id=bridge1,chassis_nr=1 -device virtio-net-pci,netdev=net0,bus=bridge1,addr=2` | The card behind a bridge, on bus 1 |

## Temporary tests

Checks that need code inside the kernel are done with a temporary snippet:

1. Keep a copy of every file to change. Copying the whole `src` folder is simplest.
2. Put the snippet just above a known line of `src/main.rs`. Three places serve most needs:
   - above `// Get the devices ready, then let their signals through.` in `efi_main` for code that runs once, with signals still off. `task_add(test_task);` goes here too;
   - above `if seconds >= 4 && !hint_shown {` in the main loop for code that runs with signals on. Guard it with `if seconds == 2 { ... }` to run it two seconds in;
   - above `#[unsafe(no_mangle)]` for new functions, such as the work of a test task.
3. Build, boot, read the output.
4. Put the copies back, then build again.

A snippet that needs something private in another file can add `pub` there for the test. Put that back too.

A test should be able to fail. For each protection or saved register that a test is meant to check, break that one thing on purpose once and see the test report it. Two lessons from doing that:

- Swapping two registers in the timer's stub is not a good break: every switch swaps them back, and the test passes by luck. Leaving one register unrestored cannot cancel out.
- A register test must compare after every single switch, not once at the end. With one register left unrestored, a test that set the registers once, gave up its turn many times and compared at the end reported nothing: the task that finished first put the right value back as its function ended, and the other task then found it. Comparing all 15 registers after every turn reported 99,995 changes in 100,000 turns.
- Two tasks doing ordinary work with lists did not catch a heap without protection in three seconds; a switch rarely lands inside the heap. Two tasks that do almost nothing but take and return pieces of one size caught it at once.

## Deliberate bugs

These prove that problems are reported. Each stops the kernel with one line.

| Snippet | Expected line |
| --- | --- |
| `unsafe { asm!("div ecx", in("ecx") 0u32, inout("eax") 1u32 => _, inout("edx") 0u32 => _) };` | `CPU fault: divide by zero at 0x...` |
| `unsafe { *(0xFFFF_8000_0000_0000u64 as *mut u8) = 1 };` | `CPU fault: page fault at 0x..., touching 0xffff800000000000, detail code 0x2` |
| `let list = alloc::vec![1u8, 2, 3]; let index = seconds as usize + 5; write!(serial, "{}", list[index]).ok();` | `Kernel panic: src\main.rs:<line>: index out of bounds: the len is 3 but the index is 7` |
| `let huge: Vec<u8> = Vec::with_capacity(300 * 1024 * 1024);` on a 256 MB machine | `Kernel panic: src\frames.rs:<line>: the machine is out of memory` |
| `unsafe { asm!("int 49") };` (an event on an empty line of the interrupt table) | `CPU fault: general protection fault at 0x..., detail code 0x18a` |

A panic line names the file the panic is in, so the file name changes when code moves.

## Traps

- **A QEMU left running** keeps the serial file and `BOOTX64.EFI` locked, and the next run then shows the old output. Always end QEMU with `quit`, or kill it, and check that none is left.
- **Cutting a script's output short** (for example with `Select-Object -First 1`) can end the script before it sends `quit`. That leaves a QEMU running.
- **Restoring a file by copying a backup** keeps the backup's old timestamp, and `cargo build` then skips the rebuild and the old kernel is booted. Set the file's time to now before building.
- **`powershell -File script.ps1 -Keys a,b,c`** passes `a,b,c` as one string. Use `powershell -Command "& 'script.ps1' -Keys a,b,c"` to pass a list.
- **Memory on the host.** The frame pile writes to every free frame at startup, so the host must really provide all of the guest's memory. On a host with about 1 GB free, guests were kept at 512 MB or less.
- **Timing in windowless runs.** The kernel's clock counts timer signals. In some windowless runs, lines meant to be 1.0 s apart came 1.56 s apart, and in other runs of the same kernel exactly 1.0 s. The kernel before the memory work and the one after it showed the same 1.0 s when compared side by side, so the kernel is not the cause. The factor matches Windows' default timer step of 15.6 ms: QEMU then delivers at most 64 timer signals a second where the kernel asks for 100. The likely reason is that Windows does not give a hidden program its finer timer. Judge timing by a run with a visible QEMU window, and judge order by tick counts, which do not depend on it.
- **Windows can refuse to run freshly compiled programs.** With Smart App Control switched on, Windows only runs programs that are signed or that Microsoft recognises. A build then stops with "An Application Control policy has blocked this file (os error 4551)" when it hits one that is neither.
  - A crate's build script is such a program: cargo compiles it and runs it on the spot. With smoltcp taken from crates.io, the build script of `heapless` was blocked on every one of four tries. That is why the two crates with build scripts are kept as copies without them; see `vendor/README.md`.
  - The verdict is not predictable. In a temporary folder the same kind of build script had been let through, and Rust's own linker, `rust-lld`, was blocked once and never again.
  - Windows records each block in its Code Integrity log (`Microsoft-Windows-CodeIntegrity/Operational`, events 3033 and 3077), with the file's name.
  - Do not switch the protection off and do not try to slip a program past it. Find a way that runs no such program.
  - If the linker is blocked, running the build again has worked.
- **`cargo` may fetch more than a build uses.** Asked for smoltcp from crates.io, cargo downloaded 17 crates where the build used 8. The other nine were optional parts for a logging system, pulled in by one line in smoltcp's settings. `cargo tree` shows what a build uses; `Cargo.lock` shows what cargo will fetch. Check both before taking in a crate.

## What has been verified

All of it in QEMU 11.1 with its UEFI firmware, on Windows, on 2026-11-16 and 2026-11-17. Nothing has run on real hardware.

**Serial output and the takeover**

- The first two pieces (serial output, the takeover) were at first only checked by compiling. They were then booted in QEMU, where the boot lines appear.
- The serial setup was booted with and without a serial port present. Without one the kernel runs but prints nothing. How that silent case was confirmed is not recorded.

**Failures**

- The divide-by-zero, page-fault and out-of-range-index bugs each print their report. They were repeated after each later piece of work, also with device signals switched on.

**Timer and keyboard**

- Three `Timer: N s` lines, which the main loop printed at the time, appeared 1.0 s apart by the wall clock.
- Keys sent with `sendkey` were echoed (`hello boos`, digits, punctuation, Enter). Shift, the arrows, F1 and Esc printed nothing, as intended.
- A temporary test filled the nine saved registers with known values, slept through 300 timer signals and found them unchanged. With the stub broken on purpose (two registers not saved), the same test showed the damage. The timer used the nine-register stub then; it has its own now, tested under Tasks below.
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

**Tasks**

- Two tasks that never hand the processor over printed their lines in turn, half a second apart, and ended. Keys typed while both were still spinning were echoed at once.
- Registers: two tasks filled all 15 general registers with their own values and spun through about 300 switches each, next to three other tasks. No register changed. With one register left unrestored on purpose, both tasks reported it.
- Heap: two tasks taking and returning pieces of one size, about 250,000 rounds each, each stamping and checking its pieces, found no wrong value. With the protection taken out on purpose, each found 42. Two tasks working with lists and formatted text for 3 s also found nothing wrong.
- Printing: two tasks printed 4328 lines at once and none was torn. With the protection taken out on purpose, 77 were.
- Stack depth in a debug build: about 2 KB for the demonstration tasks and 4 KB for tasks using lists and formatted text, of 64 KB.
- Ending: 60 short tasks, started three at a time by another task, all ran and ended. The free-frame count dropped by the three stacks of the first wave and then stayed put, so places and stacks are reused.
- Starting more tasks than the list holds prints `Kernel panic: src\tasks.rs:<line>: too many tasks`.
- A divide by zero and an out-of-range index inside a task each print their report.
- The page-fault and out-of-memory bugs still print their reports. It boots with 64 MB and 512 MB. Twenty boots in a row all reached the prompt.
- A person ran it with a visible QEMU window and saw the two tasks' lines come in turn. Whether they came at the intended pace was not reported.

**Tasks that wait**

- The two demonstration tasks print in turn, half a second apart, waiting instead of spinning. The kernel then reports that the processor rested through 399 of the first 400 ticks. With the same tasks spinning, it reports 100 of 400.
- From outside: while the two tasks were at work, QEMU used about 1.9 s of the host's processor time with the kernel whose tasks spin, and about 0.1 s with the one whose tasks wait. At the end `info registers` shows the processor asleep (`HLT=1`).
- Registers: two tasks filled all 15 general registers with their own values and gave up their turn 100,000 times each, with timer switches in between, comparing every register after every turn. Nothing had changed. With one register left unrestored on purpose, one task found it changed 99,995 times.
- Length: 28 waits of 1 to 50 ticks were never early and exactly on time when alone; next to two busy tasks, never early and at most 1 tick late. A thousand waits of 0 took less than a tick.
- A wait entered with device signals off comes back with them off.
- Waves of four tasks that each wait a different length and then end woke in the order of their waits, ten times over; 40 tasks ended and the free-frame count stayed put.
- An event on an empty line of the interrupt table (`int 49`) prints a general protection fault with detail code `0x18a`, which shifted right by 3 is 49.
- The earlier task tests still pass, and tasks that never step aside get more done than before, because the main loop no longer sleeps through its turns: the heap test ran 665,000 rounds per task where it ran 260,000.
- Keys typed while both tasks wait are echoed at once. The network lines, a page-fault report and failures inside a task still work. It boots with 64 MB and 512 MB. Fifteen boots in a row reached the prompt.
- A person ran `run.bat` and saw the line with the rest count.
- The same register test with tasks that never step aside, so that only the timer switches them: two tasks compared all 15 registers 6 million times each while spinning, and nothing had changed. With one register left unrestored on purpose, one task found it changed 5.4 million times.
- Not verified: any real hardware.

**Finding the network card**

- With the card `run.bat` attaches, the kernel reports it at device 3 on bus 0, where `info pci` shows it.
- A temporary test printed every place on the list that answers, trying all of them without shortcuts: the same six places with the same makers and models as `info pci`, two of them at a function other than 0. `pci_find` found each of the six at its place and reported a made-up model as not found.
- The card is also found in another slot (device 16), behind a bridge (device 2 on bus 1), and as the newer-only model.
- With no card, and with a card of another make, the kernel prints "none found". Looking for a card that is not there does not visibly slow the boot.
- With every packet on the card's network recorded, a whole boot recorded none: neither the firmware nor the kernel sends anything yet.
- The task lines, the key echo and a page-fault report still work. Ten boots in a row reached the prompt.
- A person ran `run.bat` with its window after the change and saw the "Network card: found" line.
- Not verified: any real hardware.

**Setting the network card up**

- The kernel prints the card's address, `52:54:00:12:34:56`. With another address given to the card in QEMU, it prints that one.
- QEMU's own view agrees with the kernel's. `info virtio-status` shows all four handshake marks, the card started and not broken, and exactly the two features the driver chose. `info virtio-queue-status` shows both waiting lines 256 long, with their three areas at the very addresses the kernel printed in a temporary test.
- `info mem` shows the card's three pages of controls reachable at `0xc000000000`, and not the fourth, which the driver does not use. Reading that fourth page prints a page fault report.
- `map_device_memory` called on a device range below 4 GB changed nothing and broke nothing.
- The newer-only card, the card in another slot and the card behind a bridge are set up too. A card with the newer way switched off prints "not set up, because it does not offer the newer way of working".
- With every packet recorded, a whole boot still recorded none (before the kernel could send).
- The task lines, the key echo and a page-fault report still work. It boots with 64 MB and 512 MB. Fifteen boots in a row reached the prompt.
- A person ran `run.bat` and saw the "Network card: ready" line with the card's address.
- With the driver changed on purpose to need a feature the card lacks, the kernel prints "not set up, because it lacks a feature this driver needs", and `info virtio-status` shows the card not started, with the driver's "failed" mark and not the card's own.
- Not verified: the older way of working (not written), the other ways the handshake can fail, and any real hardware.

**Sending and receiving packets, and the gateway question**

- The kernel prints the gateway's hardware address, `52:55:0a:00:02:02`.
- A recording of a whole boot holds exactly two packets. The first is the kernel's question, byte for byte as built: to everybody, from the card, kind `0806`, "1", the card's address and `10.0.2.15`, asking for `10.0.2.2`. The second is the answer, and the address the kernel prints is the one in it.
- 600 questions in a row got 600 right answers. That passes the end of a 256-place waiting line twice and reuses each of the 16 lent frames many times. The answer took 32 looks on average and 283 at most.
- After that, `info virtio-queue-status` shows the card having taken 601 packets from the send line and filled 601 frames of the receive line, with nothing left in use.
- The card sent no signals: after 601 packets each way, `info irq` lists nothing on line 11 and `info pic` shows nothing waiting on the second chip.
- With another address given to the card, the question carries that address and the answer still arrives.
- With the card attached to nothing, the kernel prints "the gateway 10.0.2.2 did not answer" after about a second, and carries on.
- The newer-only card and the card behind a bridge get the answer too. With no card, or a card that is refused, no gateway line is printed and the boot goes on.
- The task lines, the key echo and a page-fault report still work. It boots with 64 MB and 512 MB. Fifteen boots in a row each showed the gateway's answer.
- A person ran `run.bat` and saw the line with the gateway's answer.
- Not verified: a packet other than the answer arriving first (none ever did, so the passing-over was never exercised), more than 16 packets arriving before the kernel looks, packets longer than the question, more than one packet waiting to be sent, a card that hands back a description the driver did not lend, and any real hardware.

**The network stack and the address it is given**

- The kernel prints the address it was given, `10.0.2.15`, and who gave it, `10.0.2.2`.
- A recording of a whole boot holds six packets: the by-hand question and answer, then the kernel asking everybody for an address, the server's offer of `10.0.2.15`, the kernel's request, and the server's confirmation of `10.0.2.15`. The printed address is the confirmed one.
- On another network (`192.168.76.0`, handing out from `.9`) the kernel prints `192.168.76.9`, given by `192.168.76.2`. So the address is given, not assumed. The by-hand gateway question, which does assume, prints "did not answer" there.
- With the card attached to nothing, no address line is printed, nothing floods the output, and the boot goes on.
- Renewal: with the address made to run out after 10 seconds, the stack renewed it every 5 seconds, eight times in 40 seconds. The address line was printed once, the free-frame count did not move, and the processor rested through 3,996 of 3,999 ticks.
- The network stack's task used 8,696 bytes of its 64 KB stack. Its start number differed between two boots.
- With the stack running: two tasks hammering the heap found no wrong value, two tasks printing 11,574 lines at once tore none, 60 short tasks ended cleanly, and a failure inside a task and a page fault print their reports. Keys are echoed while tasks wait. It boots with 64 MB and 512 MB, and with the newer-only card. Fifteen boots in a row each showed the address line.
- QEMU used 0.23 s of processor time while the tasks were at work and 0.02 s in five idle seconds, so looking at the stack once per tick costs next to nothing.
- The build: no program compiled along the way is run, Windows recorded no block, and `Cargo.lock` names eight crates besides the kernel, two of them the copies.
- Each file of the two copies was compared with the crate as downloaded: 131 of 135 are identical, three were edited, and one was added. `vendor/README.md` lists the edits.
- A person ran `run.bat`, which built the kernel with the copies, and saw the line with the given address.
- Not verified: an address being lost, more than one address source, a network that answers slowly or wrongly, anything that uses the address (connections, names), and any real hardware.

**The split into files**

- Every line of code in the old single file appears unchanged in the new files; only `pub`, `mod` and `use` were added and comments changed.
- The split kernel and the single-file kernel printed the same lines for the same keys. Four deliberate bugs printed their reports.
- A person ran it and saw the same lines and the key echo as before.

**Not verified**

- Real hardware of any kind.
- Machines with several GB of memory.
- Keyboards with a layout other than US.

## Oddities seen once

- **One silent boot.** One boot out of roughly two hundred printed "Hello from my kernel!" and then nothing, with QEMU still running. It was the first boot of the build that added the heap, it stopped before any memory code runs, and it did not come back in 56 further boots, 20 of them with the compiler running alongside. Unexplained. If it comes back, `info registers` tells the two candidates apart: a processor asleep in the main loop (`HLT=1`) means the serial port test failed and the kernel is only mute; anything else means it is stuck.
