# Open points

What is known to be missing, limited or waiting. Nothing here is done. Remove a point when it is dealt with, and say so in the matching note.

## Tasks

- **A task can wait for a time, not for an event.** Waiting for a key, a packet or another task means looking again and again with short waits in between. A way to say "wake me when this happens" is missing.
- **Waits are counted in ticks.** The shortest real wait is one tick, 10 ms, and the clock behind it only counts timer signals.
- **Task 0 cannot wait.** It is the task that rests the processor, so its own work has to fit into its main loop.
- **There are 8 places and no priorities.** Every ready task gets the same turn of one tick.
- **Nothing notices a stack that overflows.** A task that uses more than its 256 KB writes into whatever lies below it on the heap. An unmapped page below each stack would turn that into a page fault.
- **A finished task's stack is given back only when its place is reused.**
- **A failure in one task stops everything.** Tasks are not isolated from each other.
- **Printing holds signals off for a whole text.** On a real serial port a long line takes several milliseconds, which could delay a tick. The longest text is the report about a fetched page, about 700 bytes: roughly 60 ms on a real port at the speed set, which is six ticks.
- **The first task has no stack of its own.** Task 0 still runs on the firmware's stack. There is also no spare stack for failures, so a failure inside the failure report, or running out of stack, resets the machine without a message.

## Memory

- Reclaim the firmware's startup memory (kinds 3 and 4, about 42 MB of QEMU's 256 MB when it was measured, before the network card and the present processor option) once task 0 has a stack of its own.
- Leave the lowest page unmapped, so that a broken pointer near zero gives a page fault instead of quietly reading memory.
- Return heap memory to the frame pile.
- Make a request that cannot be met fail, instead of stopping the kernel. This matters more since apps run in the kernel: an app is held to limits so that it cannot cause such a request (see [box.md](box.md)), and the limits are the only thing in the way.
- Mark code pages read-only and data pages non-executable. Today every page is writable and nothing is protected.
- `map_page` cannot be used inside the range covered by 2 MB pages. Mapping something small there would need the 2 MB page split up first.

## Network

- The page fetch is a demonstration: one fixed site, once per start, inside the stack's own task. It goes over an encrypted link; the limits of that link are under "Encryption" below.
- Every start of the kernel reaches the internet: one name question and one encrypted exchange with the site. A machine with no way out prints a "no page fetched" line instead.
- While a page is fetched, the stack's task does nothing else. News about the address waits until the fetch is over, which is about 26 seconds at worst.
- Only the first address of a name is tried: smoltcp is set to keep one. Only the 4-byte sort of address is asked for.
- The site's answer is taken as it comes. A redirect is not followed. The length the site states is not compared with what arrived; "the whole page" means that the site said through the encrypted link that it had sent everything. The greeting and the answer together get 15 seconds. A site that is still sending then is cut off, and what came is shown as not whole; so is a page too big to arrive in that time.
- A page arrives at about 50 KB a second through the encrypted link. The card's adapter tells smoltcp "one packet at a time", so the other side sends one packet and waits, and the stack is looked at once per tick. The card could take 16 packets between two looks; saying so, and more room for arrived bytes, would speed this up.
- After asking for one machine's hardware address, smoltcp asks for no other for a second. At each start that delays the page by a second, because the name server's address is asked for just before the gateway's. The by-hand gateway answer is not handed to the stack.
- The by-hand gateway question is still asked at startup, with an assumed address (`10.0.2.15`) and gateway (`10.0.2.2`). The stack does not need it. It could go.
- The stack's start number comes from the processor's count of its own steps. It differs between boots but is not secret, and must not be used for encryption. The same count picks this side's port number for the page fetch. The kernel has random numbers now, and neither place uses them yet.
- The stack's clock is the tick count, in steps of 10 ms, and runs slow when timer signals come late.
- The stack is looked at once per tick whether or not anything happened, because the card sends no signals. smoltcp can say how long it may be left alone (`poll_delay`); that is not used.
- Only the stack's own task may touch it. There is no way yet for another task to ask it for something.
- The copies in `vendor/` do not update by themselves, and smoltcp's limits are fixed in a file; see `vendor/README.md`.
- Waiting for the gateway's answer is counted in looks, not in time, because it happens at startup with signals off. Tasks can wait for a time now, so network code that runs in a task should use that instead.
- There is one frame for sending, so packets go out one at a time, each waiting for the card to take the one before. That wait can last up to a million looks with device signals off. The network stack's task sends packets now, so this breaks the rule to keep such stretches short: if the card ever were slow to take a packet, ticks and keys would wait too. In QEMU the card has always taken each packet at once, and the wait was never seen to be long.
- If the driver refuses to send a packet, the network stack is not told: its adapter ignores the driver's answer. The stack only finds out because no reply comes, and asks again.
- Sixteen frames are lent for arriving packets. If more arrive before the kernel looks, the card has nowhere to put them and they are lost.
- Only virtio cards are recognised, and only through the newer way of working. Real PCs have cards of other makes, each needing its own driver.
- The card is told not to send signals, so nothing announces an arriving packet; code has to keep looking. The card's signal line (11 in QEMU) is on the second chip of the interrupt controller; the kernel holds that chip back entirely, and `signal_done` tells only the first chip. Listening to the card by signal needs all three changed.
- Device memory is mapped like ordinary memory. Real hardware wants it marked "do not cache".
- The frame pile hands out single frames. A device that needs several neighbouring frames in one piece cannot be served yet. The network card's newer way of working was chosen partly because it does not need that.
- The setup runs once. Nothing handles a card that reports a failure later, and nothing sets it up a second time.
- `pci_find` tries all 256 buses rather than following bridges. That is simple and was fast in QEMU; its speed on real hardware is not known.

## Encryption

- **TLS 1.3 only, and one curve for agreeing on a key.** A site that speaks only the older TLS 1.2, or insists on another curve, is refused. The arithmetic for more is in the crates; the provider does not offer it.
- **No look at whether a certificate was withdrawn.** A certificate that its issuer has called back before its last day is still believed.
- **Only the page fetch can use the encrypted link**, one fixed site, inside the network stack's own task. Nothing can be sent but that one request.
- **Every task has a 256 KB stack because one task needs it.** The network task goes 100 KB deep when it makes an encrypted link; the others use a few KB. One constant sets the size for all, so each task costs 256 KB of memory. A size per task would save that. Building the outside crates optimized would make the link need less stack and less time, but would change how smoltcp is built as well.
- **A link is slow to make in this kind of build:** about half a second of arithmetic, during which the network task does nothing else.
- The startup check runs on the firmware's stack and uses 46 of the 124 KB free there. That room is what QEMU's firmware leaves; another firmware may leave less. Nothing notices if that stack overflows.
- The check delays startup by about half a second.
- The versions of the crates for encryption are months old, and some are days old. Security advisories appear for them, and nothing in the kernel or its build watches for those.
- The list of roots is fixed when the kernel is built. A root that loses its standing later stays trusted until the crate is renewed.
- The site's name travels readable twice at every start: in the name question, and in the greeting of the link.
- Ten crates are listed by cargo and never compiled, and three of them are downloaded on a first build.
- The five compiler settings have to be kept in step with the crates: a new or renewed crate may need another one.
- With SSE instructions refused, nothing may use those registers, the firmware's code included. No firmware code is called after the takeover today.
- The provider's adapters were written for this kernel and have been checked only by its own tests. Nobody else has looked at them.

## The box

- **An app can ask the kernel for one thing only: to print a text.** A program that wants to read a key, know the time or draw is not started.
- **What an app prints goes to the serial port,** as plain signs: no letters beyond the English ones, at most 200 bytes a text and 100 texts a run. Each line is sent with device signals off, like all printing (see "Tasks").
- **Every app may print.** There is no saying yet which app may use which call.
- **An app runs once, from the beginning of its `start` to the end.** It cannot wait for something, be called again later, or be handed anything by the kernel.
- **Nothing is kept between two runs.** Each run checks and translates the program again and starts the app from nothing. A translated program cannot be kept for later, because it lives in an engine and each run drops its engine.
- **A run holds its caller until it ends.** The check at startup runs with device signals off on the firmware's stack. A run in a task is switched away by the timer like any other work, but the task that called it waits for the answer, up to the whole of the fuel: about two seconds in this build.
- **Fuel is a count of steps, not time.** How long ten million units last depends on the build and the machine.
- **The limits are the same for every app,** fixed as constants.
- **wasmi's own memory for an app is not counted in the app's limit.** It is taken from the kernel's heap: the translated program, and a stack of values of up to 1 MB. Many apps at once, or one very large program, could still ask the heap for more than the machine has, and that stops the kernel (see "Memory").
- **The stack depth is known only for small programs:** 45 KB for programs of up to 540 bytes. Nothing notices a stack that overflows (see "Tasks").
- **The kernel no longer starts with 64 MB.** Its file is 6 MB in this kind of build, and QEMU's firmware refuses to load it on so small a machine. 96 MB works.
- **Running an app is slow in this kind of build.** The outside crates are built unoptimized; built optimized they were about 25 times faster in a trial, and the kernel's file about half the size. That setting would change how smoltcp and the crates for encryption are built as well.
- **The version of wasmi is fixed at 1.1.0.** The line after it cannot be built here (see [box.md](box.md)). If the 1.x line stops getting fixes, there is no way forward yet.
- **wasmi contains `unsafe` code,** and a mistake there could let an app out of its memory. Both of its past security advisories are, by their titles, mistakes with memory. Nothing in the kernel or its build watches for new ones, and the copies in `vendor/` do not renew themselves.
- **Only programs made by hand were run:** 41 to 540 bytes, with whole numbers of 32 bits, numbers with a point, one memory, loops, calls, and texts handed to the kernel. No program made by a compiler has run. Tables in use, values shared across functions, and whole numbers of 64 bits were not tried.
- Two versions of the helper crate `bitflags` are built, an older one for smoltcp and a newer one for the program checker.

## Random numbers and the date

- Random numbers have one source, the processor's own instruction. A processor without it gives none, and the kernel has no second source: not the firmware's, not a virtual machine's device, not noise it gathers itself.
- The numbers are used as the processor hands them out. The kernel does not mix them with anything or run a generator of its own on top, so it trusts the processor's maker entirely, and in QEMU it trusts QEMU.
- The source is tried once, at startup. If it breaks later, that shows only when a draw gives nothing.
- The network stack's start number and the page fetch's own port number still come from `time_stamp()`, not from the random numbers.
- The kernel does not know whether the clock chip holds local time or world time. Checking a certificate wants world time.
- The century is looked for in one place of the chip (`0x32`). Real PCs name the place in a table of the firmware (ACPI), which the kernel does not read. Where the value is no century, the year is taken to be in the 2000s.
- Nothing notices a clock that is plainly wrong, such as one whose battery is empty.
- Waiting for a busy chip is counted in looks, not in time.
- `run.bat` asks QEMU for its usual processor plus one instruction. The other processors QEMU can play change how much memory the firmware keeps, and `-cpu max` offers five-level page tables; see "Real hardware".

## Keyboard

- Shift and capitals, Backspace, and layouts other than US are left out.

## The screen

- **Only filled rectangles and single lines of text can be drawn.** There are no lines or pictures, and no app can draw. See [screen.md](screen.md).
- **Text is one line of plain English signs.** Nothing wraps round at the right edge, a line break is not understood, and every sign outside the 95 plain ones, a letter with an accent among them, shows as an empty box. The letters have one shape and one thickness; larger text is the same shapes with bigger dots.
- **The kernel's own lines do not appear on the screen.** They go to the serial port only, so a machine without one shows the picture and says nothing.
- **Nothing remembers what is written where.** Text cannot be taken off again except by painting over it, and there is no place on the screen that scrolls.
- **Painting is slow.** Filling the screen takes roughly 0.16 s in this kind of build, possibly up to half as much again, at startup with device signals off. Dots are written one at a time, each through a function call; writing a row in one go was measured at twenty times the speed and not kept, for the sake of plain code.
- **There is one picture and no copy of it.** What is painted shows at once, half-finished drawing included, and nothing remembers what was under a rectangle.
- **Nothing decides who may draw.** Any code can paint anywhere, and two tasks drawing at once give a mixed picture. Today only startup draws.
- **The screen's memory may lie in ordinary memory.** With QEMU's `ramfb` display it does, in a stretch the firmware's memory map calls kind 0, "set aside". The frame pile takes only kind 7, and the plan to hand out the firmware's startup memory (kinds 3 and 4, see "Memory") would not touch kind 0 either. This rests on the firmware's map: a firmware that listed the screen's memory as one of those kinds would have it handed out.
- The screen's memory is device memory and is mapped like ordinary memory; see "Network" for the "do not cache" mark. For a screen, real hardware has a mark of its own that makes many small writes fast, which the kernel does not set either.
- **Two ways of writing a colour are known:** red, green, blue and blue, green, red, at four bytes a dot. A screen that describes its colours with masks is refused, although it could be used. Only the second order was ever seen.
- **The screen is taken as the firmware left it.** The kernel does not choose a size, and looks at the first graphics service only, so a machine with two screens shows one.
- **A screen that can only be drawn on through the firmware's functions is refused.** Those functions are gone after the takeover.
- The picture at startup, a blue screen with an orange rectangle and one sentence, is a demonstration.

## Real hardware

The kernel has only run in QEMU. Known differences to expect:

- Use a FAT32 USB stick with the kernel at `EFI\BOOT\BOOTX64.EFI`, with Secure Boot switched off. Never the machine's main disk.
- Most PCs have no serial port, so the kernel would run but say nothing. It needs screen output first.
- Many modern PCs have no PS/2 keyboard controller, because their keyboards are USB. The keyboard code may stay silent there.
- The old interrupt controller and timer chips are usually still present, but that is not guaranteed.
- The kernel assumes 4-level page tables. A firmware that hands over with 5-level tables switched on (bit 12 of `cr4`) needs a check first: loading 4-level tables there resets the machine without a message.
- The interrupt controller's signals reach the processor only if the firmware left the processor's own interrupt unit (the local APIC) passing them through. The kernel does not set that up.
- The interrupt controller is set up without pauses between its commands. QEMU does not need them; very old hardware might.
