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
- **Every task has a 256 KB stack because one task needs it.** The network task went 100 KB deep when it made an encrypted link, before the outside crates were built optimized; now it goes 56 KB deep at most, and the others use a few KB. One constant sets the size for all, so each task costs 256 KB of memory. The size was not lowered when the need shrank. A size per task would save the most.
- **While a link is made the network task does nothing else.** That was about half a second of arithmetic before the outside crates were built optimized; it is about a tenth of a second or less now, judged by how much of its first four seconds the processor rested.
- The startup check runs on the firmware's stack and uses 42 of the 124 KB free there. That room is what QEMU's firmware leaves; another firmware may leave less. Nothing notices if that stack overflows.
- The check delays startup by 0.2 to 0.3 seconds.
- The versions of the crates for encryption are months old, and some are days old. Security advisories appear for them, and nothing in the kernel or its build watches for those.
- The list of roots is fixed when the kernel is built. A root that loses its standing later stays trusted until the crate is renewed.
- The site's name travels readable twice at every start: in the name question, and in the greeting of the link.
- Ten crates are listed by cargo and never compiled, and three of them are downloaded on a first build.
- The five compiler settings have to be kept in step with the crates: a new or renewed crate may need another one.
- With SSE instructions refused, nothing may use those registers, the firmware's code included. No firmware code is called after the takeover today.
- The provider's adapters were written for this kernel and have been checked only by its own tests. Nobody else has looked at them.

## The box

- **An app can ask the kernel for two things only: to print a text, and to show a text on the screen.** A program that wants to read a key, know the time or paint is not started.
- **What an app prints goes to the serial port,** as plain signs: no letters beyond the English ones, at most 200 bytes a text and 100 texts a run. Each line is sent with device signals off, like all printing (see "Tasks").
- **What an app shows is one line of at most 40 plain signs, in one box.** There is one box for every app, of a fixed size, in the middle of the screen, and the app that shows last wins. An app can show 20 texts a run, cannot show several things at once, cannot take its text off again, and cannot tell whether there is a screen at all.
- **An app has no say in how its text looks, and neither has the person at the machine.** The look of the box is a set of values in `screen.rs`, fixed when the kernel is built. Changing the look while the kernel runs, or letting an app add wishes to it, needs new work; so does arranging several things in a box.
- **Showing holds everything else up.** Each showing paints the box with device signals off when it happens at startup, about a hundredth of a second each time.
- **Every app may print and show.** There is no saying yet which app may use which call.
- **An app runs once, from the beginning of its `start` to the end.** It cannot wait for something or be called again later. The one thing the kernel can hand a program is a script's text, and only to a program made for that (see "The interpreter").
- **Nothing is kept between two runs.** Each run checks and translates the program again and starts the app from nothing. A translated program cannot be kept for later, because it lives in an engine and each run drops its engine.
- **A run holds its caller until it ends.** The check at startup runs with device signals off on the firmware's stack. A run in a task is switched away by the timer like any other work, but the task that called it waits for the answer, up to the whole of the fuel: about two seconds in this build.
- **Fuel is a count of steps, not time.** How long ten million units last depends on the build and the machine.
- **The limits are the same for every app,** fixed as constants.
- **wasmi's own memory for an app is not counted in the app's limit.** It is taken from the kernel's heap: the translated program, and a stack of values of up to 1 MB. Many apps at once, or one very large program, could still ask the heap for more than the machine has, and that stops the kernel (see "Memory").
- **The stack depth is known only for small programs:** 16 KB for programs of up to 540 bytes, and for the interpreter: 17 KB to get it ready and 17 KB while it carries a script out, the same for every script tried, misbehaving ones among them. Nothing notices a stack that overflows (see "Tasks").
- **The kernel does not start with 64 MB.** Its file is 4 MB, and QEMU's firmware refuses to load it on so small a machine. 80 MB works, with 22 MB free.
- **Only the outside crates are built optimized.** The kernel's own code is still built plain, and so are the pieces of outside code that the compiler builds as part of the kernel because they are fitted to the kernel's own types. What that costs was not measured piece by piece. A build of the kernel from nothing takes a minute instead of 20 seconds.
- **The version of wasmi is fixed at 1.1.0.** The line after it cannot be built here (see [box.md](box.md)). If the 1.x line stops getting fixes, there is no way forward yet.
- **wasmi contains `unsafe` code,** and a mistake there could let an app out of its memory. Both of its past security advisories are, by their titles, mistakes with memory. Nothing in the kernel or its build watches for new ones, and the copies in `vendor/` do not renew themselves.
- **Only programs made by hand were run:** 41 to 540 bytes, with whole numbers of 32 bits, numbers with a point, one memory, loops, calls, and texts handed to the kernel. The one program made by a compiler that runs here is the interpreter (see [interpreter.md](interpreter.md)). Tables in use, values shared across functions, and whole numbers of 64 bits were not tried.
- Two versions of the helper crate `bitflags` are built, an older one for smoltcp and a newer one for the program checker.

## The interpreter

- **One script runs, at startup, and it is part of the kernel.** Nothing can hand the kernel a script from outside yet: not the chat box, not the disk, not the network. See [interpreter.md](interpreter.md).
- **A script can print lines and show one line of text, and nothing else.** That is the whole system API. A script cannot read a key, know the time, keep anything, or put more than one thing on the screen.
- **`print` cuts a line that is too long, and `show` stops the script.** A printed line of more than 200 bytes is cut by the interpreter without a word; a shown text of more than 40 bytes stops the whole run, by the kernel's rule for apps. The two were decided at different times and do not match.
- **A script's run holds everything else up.** Keys pressed during it are lost. It happens at startup with device signals off, and a start is about half a second longer for the check and the one script. A script run later, when tasks are running, would have to run in a task.
- **Fuel is the only thing that ends a bad script, and fuel does not bound time.** The budget is used up in 0.4 seconds by an empty loop and in 1.4 by a script that joins texts without end. A script that fills its memory holds the processor for 1.6 to 1.8 seconds and is ended by the memory limit, not by the fuel. (Before the outside crates were built optimized these were 2, 24 and up to 43 seconds.) Where scripts run today the timer does not tick, so nothing could stop one by the clock; and wasmi's way of going on after the fuel has run out, which a clock would need, stopped the kernel in one of its two settings (see [interpreter.md](interpreter.md)).
- **The budget for a script is a stopgap,** 100 million units. It stops harmless work too: a loop of more than about four thousand rounds, `fib(20)`, the Tower of Hanoi with ten discs. It was set when the outside crates were built plain and ten times as much would have let a bad script hold the machine for minutes; now ten times as much would be 4 to 14 seconds. It has not been raised.
- **The interpreter is checked and translated anew for every script,** and once more for the check at startup. That is most of the time a small script takes. Keeping a checked program for the next script is not built; an engine keeps what it has translated only as long as it lives, and each run drops its engine (see [box.md](box.md)).
- **A script cannot catch the kernel's refusals.** When the kernel stops a showing or a print, the whole interpreter is stopped; a script that wanted to try a text and fall back on a shorter one cannot.
- **The kernel learns only that a script made a mistake, not which.** The interpreter prints the mistake as a line and gives back a number. Code that wants to act on the mistake, such as handing it back to whoever wrote the script, has no way to get the text.
- **A script that ends by a mistake inside the interpreter itself looks like any stopped app.** When the interpreter runs out of memory it ends with wasmi's `unreachable`, and that word is all the kernel can say.
- **What a script prints is cut and cleaned without a word.** A line longer than 200 bytes is cut by the interpreter, and every byte that is not a plain sign, a tab or a letter with an accent among them, becomes a dot. A text with bytes that are no letters at all stops the script.
- **The outside code is young.** omnilua's first release was in June 2026, one account keeps it, its makers describe it as translated from the C original with the help of AI, and nobody outside has checked it. It runs inside the box, so a mistake in it can harm the app it runs and not the kernel; the box is what that rests on.
- **Nothing watches for new versions or advisories** of omnilua, as for the other outside code.
- **The kernel's build needs a second build first,** and the building computer needs Rust's WebAssembly target. A kernel built without rebuilding the interpreter carries the old one without saying so, except through the byte count in its line.
- **The built interpreter is not in the repository,** so what a given kernel file carries can only be made again by building, with the same compiler and the same version of the crates. Two builds on one computer gave the same bytes; another version of the compiler was not tried.

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

- Caps Lock and layouts other than US are left out. Ctrl is not understood either: a key gives its usual sign while it is held. Alt was not tried.
- **Shift can stick.** Whether a Shift key is down is worked out from the key numbers as the main loop takes them. If the waiting line is full when Shift is let go, that number is dropped, and every key gives its second sign until the same Shift key is pressed and let go again.
- **Shift numbers behind the mark are passed over,** which is right for Print Screen as QEMU plays it. What real keyboards send around the arrow keys and the number pad was not looked at.
- **Any other number behind the mark is looked up like an ordinary key's.** A key that sends the mark and then a number from a row of signs would type that sign. The up arrow, Delete and Print Screen do not; no other such key was looked for.
- The waiting line holds 16 key numbers, two for each key pressed and let go. Keys that arrive faster than the main loop takes them out are dropped, and the main loop paints after every key, about 8 thousandths of a second each time. Keys 10 thousandths of a second apart all arrived; keys 5 apart did not.

## The disk

- **Nothing tidies the notebook.** Every line sent in the chat box adds an entry, entries that a newer one has replaced stay, and a full notebook stays full: keeping is refused from then on. The disk file in QEMU has room for 30,685 entries. Tidying has to be safe against a power cut too, which an only-added-to notebook is by itself and a tidied one is not.
- **A start takes longer the more entries there are.** Opening reads every entry in a command of its own: about half a second for a thousand entries and 14 seconds for a full notebook of 30,685, in QEMU. Reading several blocks with one command would shorten it; tidying would too.
- **A thing in the notebook is at most 448 bytes,** because an entry is one block. Anything larger, such as the text of an app, needs entries that go over several blocks: a new version of the layout, and an answer to a power cut between the blocks of one entry.
- **Every line sent is kept, whatever it holds.** Nothing asks whether a line should be kept, and nothing can take a line out of the notebook again; older lines stay on the disk although only the last is said. A secret typed as a line would stay there in the clear.
- **A damaged notebook is not repaired.** It is read up to the damage, the entries behind it are not looked at, and nothing is added. Only the eight blocks behind the notebook's end are looked at for that; something further behind is not noticed.
- **The reading back after a write was not tested for the notebook.** In QEMU a write either works or reports its failure. For the count of starts a write that silently does nothing was played and caught by the reading back; the notebook uses the same steps.
- **A line can be reported as not kept and be on the disk all the same.** Keeping is a write and then the "put it down for good" command. If the write works and that command fails or is given up on, the kernel says the line could not be kept, although its entry is on the disk: the next start says that line, and the next line kept is written over its block. Reasoned from the code, not seen. On a real disk that is slow with that command it would also hold the main loop up at every Enter.
- **Keeping a line holds the main loop up** for as long as the disk takes: a write, the "put it down for good" command and a read. In QEMU that is too short to see; forty lines typed 90 thousandths of a second apart were all kept. On a real disk it is not known.
- **A write is one block, and is not safe against a power cut in the middle.** One block either gets written or does not, as far as is known. The notebook is built on that: an entry is one block, and a block at the notebook's end that is not a whole entry is written over. A power cut in the middle of a block could only be played by building such blocks by hand.
- **Three protections of writing were never seen to matter in QEMU:** with the "put it down for good" command left out, a count written just before QEMU's process was killed was still there; with the entry's mark "the data goes to the disk" left out, QEMU wrote all the same; and getting the socket going again after a failed command made no difference. A real disk and a real controller need all three.
- **What a sync program does to the disk file was tried only briefly:** eight starts with a test disk file inside a synced folder went through and left nothing odd behind. Whether the sync program touched the file at all in those two minutes is not known, and longer use was not tried.
- **The "put it down for good" command may be given up on too early on a real disk.** It can take far longer than reading or writing a block, and the kernel's patience is counted in looks, not in time. A start would then be reported as not counted although its block was written. This is expected, not seen: QEMU answers at once.
- **The count of starts is a demonstration** and takes the last block of the kernel's own part. The notebook leaves that block alone. The count could become a thing in the notebook instead; then every start would add an entry.
- **Every list of parts the kernel has read was written by this project's own script or tests.** A list written by another system's tools, as a real disk's will be, has not been read, except for one head that QEMU's firmware had written anew while repairing a test disk. What may differ is not known: more or fewer entries, other marks in them, a second copy placed elsewhere.
- **Only the list's copy at the start is read.** If it is damaged the kernel finds nothing of its own, also when the copy at the end is whole. It repairs nothing. A firmware may have repaired the list before the kernel runs; QEMU's does.
- **A disk divided the older way is not understood.** The kernel reads the list PCs use today. A disk with only the old-style list in block 0 counts as having no list.
- **The kernel cannot divide a disk.** A disk gets its list and the kernel's part from outside: the disk file from the script, a real disk from another system's tools. Nothing in the kernel can make or change a part, and nothing asks the person at the machine.
- **Nothing puts the kernel on a disk.** A machine can only start the kernel from a part that holds it as a file in a file system the firmware reads. The kernel cannot make such a part or copy itself into one; in QEMU it is started from a folder, on a real machine from a USB stick.
- **Two parts of the kernel's kind are refused,** and so is one that shares a block with another part, although the reference firmware would only ignore the overlapping entries. Refusing is the safe answer for a kernel that will write there.
- **The dividing script needs a computer that runs script files.** Where the settings refuse them, `run.bat` stops. The script was run on one computer.
- **The first disk on the controller is taken,** the one in the lowest socket. On a machine with two disks the other is ignored, and nothing lets a person choose.
- **A disk whose blocks are not 512 bytes long is refused.** Some large new disks have blocks of 4096 bytes. QEMU cannot play such a disk on this controller, so the refusal was seen only with the disk's answer replaced in the code.
- **A disk that counts its blocks in 28 bits is set up and cannot be read.** The kernel knows the read command for disks that count in 48 bits only. Such disks are old and small.
- **One block per command, one command at a time.** Reading many blocks takes one command each, about half a thousandth of a second apiece in QEMU, and holds everything else up meanwhile.
- **Nothing decides who may use the disk.** Reading and writing keep no protection; two tasks using the disk at once would overwrite each other's command. Only startup code and the main loop use it today, and a task has no way to ask the main loop for something to be kept or found.
- **Waiting is counted in looks, not in time,** 3 million of them, because the setup runs before the timer's signals are let through. The specification gives times: half a second for a socket to stop, up to 2 seconds for the firmware to let go. On a fast machine the looks may run out sooner than that, and a slow disk would be given up on too early.
- **Several steps were never seen to matter in QEMU,** so they are untested as protections:
  - taking the controller over from the firmware: QEMU's controller says it has no control for that, so the code never ran;
  - "take answers" before "carry out commands": with that switch left off on purpose, QEMU's disk answered all the same;
  - the check that a whole block arrived fired once, when a read was made to ask for 65,536 blocks into room for one; with room for half a block named on purpose in the "who are you" command, QEMU still wrote 512 into the entry;
  - the short count of blocks, for disks that count in 28 bits: QEMU's disk always gives the long one. With the short one taken on purpose the size came out the same.
- **Getting a socket going again after a failure was never seen to matter.** The kernel does what the specification says after a failed command. In QEMU the next command worked just as well with that taken out on purpose. If the disk is still busy after a failure, the socket stays stopped for good: the harder push the specification names for that case is not written.
- **A disk that is asleep or slow to wake is counted as not there.** The kernel does not wake a disk or start it spinning; it uses what the firmware left running.
- **The two frames lent to the controller are never given back,** also when the setup fails after taking them.
- **The disk's own documents were not read.** What the kernel knows about commands and about the disk's answer comes from the source of Linux and of QEMU, which agree; see [disk.md](disk.md).
- **Only an AHCI controller is recognised,** by the three numbers it states about its kind. A controller set to RAID mode or to the older IDE mode states other numbers and counts as none; some PCs are delivered that way. An NVMe disk, which newer PCs have, is not known either.
- **The first controller found is taken.** A machine with two is not handled.
- **In QEMU the disk is one file of 16 MB,** made by `run.bat`. Nothing makes it larger.
- **The rule for writing rests on one file.** Only `parts.rs` can make the ticket that writing asks for, so code elsewhere cannot write to a block of the disk by its own number. Code added to `parts.rs` itself can. Whoever changes that file must keep `part_write` the only caller of `disk_write`.
- **Closing QEMU's window is a power cut** as far as the kernel can tell; there is no way to shut the machine down. Whatever is stored later has to survive being cut off in the middle of a write.

## The chat box

- **The kernel only gives the typed line back.** Nothing reads the line, and nothing else can answer in the chat box.
- **Only the main loop may use the chat box.** Its lists are not protected, and there is no way yet for another task to hand it a text. A task that gets an answer from somewhere, such as the network task, cannot show it there.
- **A secret can be typed, and nothing uses it yet.** It is kept in memory only, so it has to be typed again after every start.
- **A secret is typed blind.** The stars and the count are all the person sees; a wrong sign cannot be found except by typing the whole again. There is no way to leave the asking but Enter on nothing.
- **A secret's signs pass through places that are not wiped:** the processor's registers and the stack of the main loop while a key is handled, a byte at a time. The dump of a test machine's memory held a typed secret exactly once and no further run of six of its signs, which is as far as that was looked into; where in memory the one copy lay was not looked at, and it is the breaks made on purpose that tie the count to the two rooms made for it.
- **Anything in the kernel can read the secret's room.** The kernel has one memory for all its code; only apps in the box are shut out of it.
- **Six rows of what was said are shown,** and there is no scrolling back. Of what was said before a switch-off, only the last line that was sent is said again at the next start.
- **A long text is cut into rows where the row ends,** in the middle of a word if need be.
- **A line is at most 50 signs,** and there is no way to move inside it; only its last sign can be taken away.
- **The mark for the next sign does not blink.** A key held down repeats as fast as the keyboard sends it; the kernel sets no pace of its own.
- **Sending a line paints the rows again from nothing,** about a twentieth of a second in this kind of build. For that moment the rows are blank. In a QEMU window that showed no flicker; on a slower machine or with more rows it might. Painting a row in one go (see "The screen") would shorten it.
- **The look is fixed when the kernel is built,** as a set of values in `chat.rs`. Neither the person at the machine nor anything else can change it while the kernel runs. The box that shows an app's text has its own set in `screen.rs`; the two are not one.
- **On a machine without a screen the typing is blind:** nothing shows until Enter, when the line appears in the terminal.
- **On a screen smaller than 800 by 600 dots** the chat box may lie over the box that shows an app's text. Nothing was tried there.
- The row from the kernel that says what to do, and the answer that gives the line back, are demonstrations.

## The screen

- **Only filled rectangles and single lines of text can be drawn.** There are no lines or pictures. An app cannot draw; it can only have one text shown in the kernel's box (see "The box"). See [screen.md](screen.md).
- **Text is one line of plain English signs.** Nothing wraps round at the right edge, a line break is not understood, and every sign outside the 95 plain ones, a letter with an accent among them, shows as an empty box. The letters have one shape and one thickness; larger text is the same shapes with bigger dots.
- **The kernel's own lines do not appear on the screen.** They go to the serial port only, so a machine without one shows the picture and the chat box, and none of the lines about its start.
- **Nothing remembers what is written where,** except the chat box, which keeps its own rows and paints them again. Elsewhere text cannot be taken off again except by painting over it.
- **Painting is slow.** Filling the screen takes roughly 0.16 s in this kind of build, possibly up to half as much again, at startup with device signals off. Dots are written one at a time, each through a function call; writing a row in one go was measured at twenty times the speed and not kept, for the sake of plain code.
- **There is one picture and no copy of it.** What is painted shows at once, half-finished drawing included, and nothing remembers what was under a rectangle.
- **Nothing decides who may draw.** Any code in the kernel can paint anywhere, and two tasks drawing at once give a mixed picture. Today drawing happens at startup and, for the chat box, in the main loop; no other task draws.
- **The screen's memory may lie in ordinary memory.** With QEMU's `ramfb` display it does, in a stretch the firmware's memory map calls kind 0, "set aside". The frame pile takes only kind 7, and the plan to hand out the firmware's startup memory (kinds 3 and 4, see "Memory") would not touch kind 0 either. This rests on the firmware's map: a firmware that listed the screen's memory as one of those kinds would have it handed out.
- The screen's memory is device memory and is mapped like ordinary memory; see "Network" for the "do not cache" mark. For a screen, real hardware has a mark of its own that makes many small writes fast, which the kernel does not set either.
- **Two ways of writing a colour are known:** red, green, blue and blue, green, red, at four bytes a dot. A screen that describes its colours with masks is refused, although it could be used. Only the second order was ever seen.
- **The screen is taken as the firmware left it.** The kernel does not choose a size, and looks at the first graphics service only, so a machine with two screens shows one.
- **A screen that can only be drawn on through the firmware's functions is refused.** Those functions are gone after the takeover.
- The sentence written at startup is a demonstration, and so is the app that shows a text.

## Real hardware

The kernel has only run in QEMU. Known differences to expect:

- Use a FAT32 USB stick with the kernel at `EFI\BOOT\BOOTX64.EFI`, with Secure Boot switched off. Never the machine's main disk.
- Most PCs have no serial port, so the kernel would run but say nothing. It needs screen output first.
- Many modern PCs have no PS/2 keyboard controller, because their keyboards are USB. The keyboard code may stay silent there.
- The old interrupt controller and timer chips are usually still present, but that is not guaranteed.
- The kernel assumes 4-level page tables. A firmware that hands over with 5-level tables switched on (bit 12 of `cr4`) needs a check first: loading 4-level tables there resets the machine without a message.
- The interrupt controller's signals reach the processor only if the firmware left the processor's own interrupt unit (the local APIC) passing them through. The kernel does not set that up.
- The interrupt controller is set up without pauses between its commands. QEMU does not need them; very old hardware might.
