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
- **Printing holds signals off for a whole text.** On a real serial port a long line takes several milliseconds, which could delay a tick. The longest text is the report about a fetched page, about 700 bytes: roughly 60 ms on a real port at the speed set, which is six ticks. While the machine starts, a line is also painted on the screen then; that is before device signals are let through, so no tick waits for it.
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
- Only the stack's own task may touch it. The main loop can ask it for three things, the example page, one question to the model and a request to the model for an app, through an errand (see [tasks.md](tasks.md)); no other task can ask, and nothing else can be asked for.
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
- **Two things can use the encrypted link:** the page fetch and the question to the model, each with one fixed site and one fixed request, inside the network stack's own task. One request per connection, and the link is made anew each time.
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
- **An app has no say in how its text looks.** The box's sizes are a set of values in `screen.rs`, fixed when the kernel is built, and its colours are those of the look the person at the machine picked (see "The screen"). Letting an app add wishes to the look needs new work; so does arranging several things in a box.
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

- **One script runs at startup, and it is part of the kernel; the others come from the model.** A script the model writes on request is run once, in the main loop, and is then gone (see [apps.md](apps.md)); the disk cannot hand one at all. See [interpreter.md](interpreter.md).
- **A script can print lines and show one line of text, and nothing else.** That is the whole system API. A script cannot read a key, know the time, keep anything, or put more than one thing on the screen.
- **What is too long is cut without a word.** A printed line of more than 200 bytes, and a shown text of more than 40, are cut by the interpreter; the script is not told. The kernel's own rule for a shown text that is too long, which stops a program, is met only by programs that call `kernel.show` themselves.
- **A script's run holds up its caller.** At startup it happens with device signals off: keys pressed meanwhile are lost, and a start is about half a second longer for the check and the one script. An app made on request runs in the main loop with signals on: the other tasks go on, but keys wait in the keyboard's line of 16 key numbers (about eight keys) until the run is over, and keys beyond those are lost. A run in a task of its own would let typing go on; it was not chosen.
- **Fuel is the only thing that ends a bad script, and fuel does not bound time.** The budget is used up in 0.4 seconds by an empty loop and in 1.4 by a script that joins texts without end. A script that fills its memory holds the processor for 1.6 to 1.8 seconds and is ended by the memory limit, not by the fuel. (Before the outside crates were built optimized these were 2, 24 and up to 43 seconds.) Where the script at startup runs, the timer does not tick; where apps made on request run, in the main loop, it ticks, but nothing looks at it during a run. A limit by the clock would need wasmi's way of going on after the fuel has run out, which stopped the kernel in one of its two settings (see [interpreter.md](interpreter.md)).
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

## JSON

- **One request is made with it,** the question to the model, and its answer is read with it. See [json.md](json.md) and [model.md](model.md).
- **Only texts can be read.** A number, `true`, `false` or `null` can be passed over, not read as a value; a list cannot be walked through without knowing how long it is; nothing says whether a name is there except by asking for its text.
- **The parts that are passed over are not checked.** Commas, colons and the spelling of numbers and words are not looked at there, and a square bracket closes a curly one. The kernel hands out the right text from some pieces that a strict reader refuses.
- **A text is copied whole, however long.** An answer with a text of many megabytes asks the heap for as much, and a request for memory that cannot be met stops the kernel (see "Memory"). Whoever hands an answer to the reader has to limit its size first.
- **The whole piece has to be in memory at once.** It cannot be read as it arrives.
- **The values of the startup check are made by a script that is not in the repository.** [json.md](json.md) says how to make them again.

## Asking the model

- **One fixed question.** What is asked is a constant; a typed line cannot be the question yet, and the answer is only said, not used. A typed line can be a request for an app, which is a question of its own kind (see "Apps made on request" below).
- **A good answer from the real provider was seen once, and only its row.** In a person's own run with a real key the model's words appeared in the chat box; the raw answer was not seen. Whether the model thinks before it answers, how long a good answer takes, and whether 1000 tokens leave room for longer answers are not known; if they do not, the kernel says so ("the model's answer was empty, because ...") instead of showing nothing. The kernel does not ask for thinking or no thinking, because the provider's documentation names no setting for this model.
- **The tokens used are not read.** The answer says how many tokens the question and the answer cost (`usage`), but the JSON reader only reads texts, not numbers, so the kernel cannot say what an asking cost.
- **The model's words are cut at 300 signs** and shown as plain signs only: a letter with an accent becomes dots.
- **An answer in pieces is not read.** If a provider sends its answer in pieces with their lengths in between ("chunked"), the body does not read as JSON. The provider did not answer that way to this kernel's request.
- **The end of an answer is the closed connection.** A provider that sends its whole answer and then leaves the connection open is waited for until the minute is over, and its answer is then called "not whole". The length the provider names is not used.
- **An asking can hold the network's task for a minute and more,** and cannot be called off.
- **If the provider repeats the key in its answer, copies of it stay behind in memory.** What is said hides the key, but the answer as it arrived was unscrambled into rooms that are given back to the heap unwiped: the room for arrived bytes, a copy the encryption library makes of each piece, the collected answer and the words read out of it. A test machine's memory held the key two or three times after such answers, once in its own room and otherwise in such leftovers. A heap that wipes whatever is given back to it would end this; it does not exist. The real provider's refusal did not repeat the key.
- **The wiping after a request is not shown to matter by a test.** The request passes through the encryption library, which makes a copy to scramble; no copy was found in memory afterwards. With the wiping of the request, or of the copy of the key that an asking works with, taken out on purpose, none was found either.
- **A short key hides much.** A key shorter than six signs is hidden wherever it stands whole in the provider's or the model's words, so a key of one letter turns that letter into a star everywhere in them. A piece of five signs or fewer of a longer key is not hidden.
- **The request names nothing about this kernel** (no note saying what kind of program asks). A provider that wants one would refuse; this one did not.
- **Refusals are not told apart.** A wrong key, used-up credit, a model the provider does not know and too many requests all read "the provider turned the question down", with the number and the provider's words. Only the provider's own trouble (500 to 599) reads differently, "the provider could not answer". Nothing asks again by itself.

## Apps made on request

- **The app runs once and is gone.** Its script goes to the terminal, line by line, and is run; nothing keeps it, so the same app asked for again is written again by the model. See [apps.md](apps.md).
- **An app can show one line of 40 signs and print to the terminal, and nothing else.** It cannot wait, read a key, or be run again; so an app that shows several lines in turn, like frames, is seen only at its last. Its printed lines are in the terminal, not on the screen.
- **A request has at most 45 signs,** what is left of the chat box's 50-sign line after `make` and its space.
- **The model is told the same fixed text every time,** sent with every request. Whether it follows the text is not checked, except that marks around code are taken off: an answer in words is taken as a script, and only the first block between marks is kept.
- **Random numbers depend on the processor's.** The interpreter's random numbers start from the same place each time unless the kernel gives a run a seed; it takes one from the processor's random numbers for every app. A processor without them would give none, but then the encrypted link cannot be made and no app comes at all. The seed is not secret and not meant to be: it only makes runs differ. The script at startup gets none.
- **The kernel says how a run went in a few kinds only:** a mistake (the terminal's line says which), fuel used up, the interpreter giving up, and the kernel's own refusals in its own words. That the interpreter gave up because of memory is the likely reason, not one it reports.
- **One real answer to a request has been seen,** a script of Lua only that kept to the instruction text (see "What the real model wrote" in [apps.md](apps.md)); in a later run an app the real model wrote ran and its text appeared, which is all that is known of it. How many of the 4000 tokens the model spends thinking, and how long a script takes to come, are not known. An answer cut off at the limit is said and not taken; one that takes longer than the minute the kernel waits ends as "the site took too long".
- **A short key hides much in a script too:** a key shorter than six signs becomes stars wherever it stands in the script, as in the provider's words (see "Asking the model").
- **A line of the script over 200 signs is cut in the terminal,** and every sign that is not a plain sign shows as a dot, a tab as two spaces.

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

- **The kernel gives the typed line back, with six lines set apart.** `key` takes a secret, `fetch` fetches the example page and says how the site answered, `ask` asks the model one fixed question, `setup` asks for the person's name, a key and a look again, `look` asks for the number of a look, and `make` with a few words asks the model for an app (see [apps.md](apps.md)). Nothing reads what else is typed: a typed line cannot be the question yet.
- **The kernel asks the person at the machine for three things: a name, the model's key with a password to lock it, and a look.** The name is asked at a start where the notebook holds none, and after `setup`; the key after the name, at a start where the notebook holds no answer about it, and after `setup`; the password at every start where a key is locked on the disk; the look when the questions about the key are over, at a start where the notebook holds no answer about the look, and after `setup`. While the kernel waits, the next line is the answer, whatever it says; there is no way to leave a question but to answer it, Enter alone included.
- **A name is one line of at most 20 plain signs.** Nothing checks it further: any signs, a name of one sign, a name that is a command word.
- **The name is kept on the disk as typed, readable by anyone with the disk,** and nothing takes it out; a new answer only adds an entry that takes its place. Every `setup` answered with a new name adds an entry, like every line sent.
- **A notebook from before the question was built asks at its next start,** because it holds no name. Its kept lines stay, and the last one is still said, before the question.
- **Nothing is asked when the notebook cannot be added to,** because the answer could not be kept: a damaged notebook, or none. `setup` asks all the same there, and the answer lasts until the machine is switched off.
- **Only the main loop may use the chat box.** Its lists are not protected. Another task can get a text into it in one way only, as the answer to an errand (see [tasks.md](tasks.md)).
- **There is room for one errand at a time,** and only the main loop may ask. A second asking is turned away until the answer to the first was picked up. Nothing can call an errand off once it is asked for.
- **While an errand runs, the network's task does nothing else.** It is the same for its own fetch at startup: no other use of the network gets a turn until the work is done or gives up, which can take a quarter of a minute and more, and a minute and more when the model is asked and its provider stays silent.
- **An errand's answer is one sentence,** and, for a question to the model, how the provider took the key. Nothing else can come back with it.
- **Nothing says in the chat box that an answer is still awaited,** except the row that the asking was made. The row of the answer simply appears.
- **A secret taken with `key` is kept in memory only,** so it has to be typed again after every start. A key given at the onboarding is kept on the disk locked, and needs the password at every start. One thing uses either: the question to the model, as its key.
- **A secret is typed blind.** The stars and the count are all the person sees; a wrong sign cannot be found except by typing the whole again. There is no way to leave the asking but Enter on nothing.
- **A secret's signs pass through places that are not wiped:** the processor's registers and the stack of the main loop while a key is handled, a byte at a time. The dump of a test machine's memory held a typed secret exactly once and no further run of six of its signs, which is as far as that was looked into; where in memory the one copy lay was not looked at, and it is the breaks made on purpose that tie the count to the two rooms made for it.
- **Anything in the kernel can read the secret's room.** The kernel has one memory for all its code; only apps in the box are shut out of it. The compiler lets one file borrow the secret through `secret_lend`; that is a rule for code that keeps to Rust's rules, not a wall.
- **Six rows of what was said are shown,** and there is no scrolling back. Of what was said before a switch-off, only the last line that was sent is said again at the next start.
- **A long text is cut into rows where the row ends,** in the middle of a word if need be.
- **A line is at most 50 signs,** and there is no way to move inside it; only its last sign can be taken away.
- **The mark for the next sign does not blink.** A key held down repeats as fast as the keyboard sends it; the kernel sets no pace of its own.
- **Sending a line paints the rows again from nothing,** about a twentieth of a second in this kind of build. For that moment the rows are blank. In a QEMU window that showed no flicker; on a slower machine or with more rows it might. Painting a row in one go (see "The screen") would shorten it.
- **The chat box's sizes are fixed when the kernel is built,** as a set of values in `chat.rs`; only its colours follow the look in use. The box that shows an app's text has its own set of sizes in `screen.rs`; the two are not one.
- **On a machine without a screen the typing is blind:** nothing shows until Enter, when the line appears in the terminal.
- **On a screen smaller than 800 by 600 dots** the chat box may lie over the box that shows an app's text. Nothing was tried there.
- The row from the kernel that says what to do, and the answer that gives the line back, are demonstrations.

## Trying the key

- **Only a key typed at the onboarding is tried.** A secret taken with `key` is not.
- **The verdict rests on the number in the provider's answer,** and on the meanings its documentation gives them (read in November 2026). From the real provider only a 401 for a made-up key has been seen at a try, in a person's run; the other numbers were seen only from the stand-in on the test computer, which was built from that documentation. If the provider gave a 401 for something other than the key, a right key would be asked for again; Enter alone would still lead on.
- **A key that cannot be judged is kept,** and is locked if a password is chosen: a key typed when the machine has no address yet, or while the answer to an `ask` or a `fetch` is awaited, and a key whose try got any answer but 200, 401, 402 or 403. A mistyped key kept that way shows itself at the first `ask` as a 401; `setup` replaces it.
- **At a first start a key can come too early.** The machine gets its address a few seconds after it starts; a key typed before that is kept untried.
- **While a key is tried, nothing typed is taken,** and there is no way to call the try off. With a provider that stays silent that is the minute the kernel waits for any question to the model, and longer by the wall clock in QEMU. Signs typed meanwhile are lost, and a row says so when the answer comes.
- **Each try is a real question to the provider:** with a key it knows, it is paid for as an `ask` is, and the provider keeps its record of it. A key it does not know is turned down before any model is asked.
- **The question is the one `ask` asks,** so the try shows the model's answer to it. A cheaper or quicker way to check a key was not found in the provider's documentation: it names no free page that says whether a key is good.

## The lock

- **One thing uses the lock: the onboarding,** which keeps the model's key on the disk locked with a password. See [lock.md](lock.md) and "The key and the password" in [chat.md](chat.md).
- **A password protects only as well as it is hard to guess.** Whoever has a locked secret can try passwords on a computer of their own for as long as they like; every try costs 600,000 rounds, and graphics cards make each round cheap. The rounds slow guessing down; they cannot stop it. Argon2id, the way OWASP's advice puts first, would also make every try fill a large table of memory, which graphics cards handle poorly; it was not taken because it is outside code.
- **The onboarding takes a password of 4 signs.** It is meant to keep out somebody who uses the machine, not somebody who has a copy of the disk. NIST's SP 800-63B (revision 4) and OWASP's advice ask for at least 15 signs when a password stands guard alone, as here. Whoever has a copy of the disk file can try every short password, and a disk file is copied wherever the folder that holds it is copied, by a backup or by a service that keeps folders in step.
- **A key locked before stays on the disk after `setup`,** and the old password still opens it: the notebook never changes what it wrote. Copies of the disk file made before would hold it anyway. Replacing the key at the provider makes the old locked one useless.
- **Nothing limits how often a password is tried at the machine.** Each try takes as long as an unlocking, about a second in QEMU.
- **While a key is locked or unlocked, the main loop does nothing else** for about a second: rows and keys wait, and keys that do not fit into the keyboard's line of 16 key numbers are lost. The other tasks carry on.
- **The password is typed blind,** twice when it is chosen and once at every start; the stars and the count are all the person sees.
- **The count of rounds is fixed when a secret is locked,** and travels with it. Raising it later means locking again. A locked secret that asks for more than 10,000,000 rounds is refused.
- **Locking and unlocking each take about a second in QEMU** on the test computer: 1.2 to 1.4 seconds measured on their own, about 0.9 from Enter to the row that says it is done in the onboarding. Nothing else runs in the main loop meanwhile. A real PC should be many times faster; not measured.
- **Nothing is locked without random numbers.** On a processor that cannot make them, `lock` refuses.
- **A wrong password and a changed locked secret look alike:** both give the same refusal.
- **The copies of the keyed fingerprint's state that every round makes are not wiped.** They are made from the password and can stand in for it, and with one of them guesses at the password can be tested without the 600,000 rounds. The key, the password and the secret were not found in a dump of the whole memory after a lock and an unlock; those states were not looked for. The wiping feature of `hmac` and `sha2` is not switched on (see [lock.md](lock.md)).
- **One way of locking is known,** version 1, way 1. Another way would need a new way number and both kept readable.
- **The rounds run in plain kernel code at a sixteenth of the speed** if `password_key` is ever moved into the kernel's own crate: it lives in a crate of its own only to be built fast.

## The screen

- **Only filled rectangles and single lines of text can be drawn.** There are no lines or pictures. An app cannot draw; it can only have one text shown in the kernel's box (see "The box"). See [screen.md](screen.md).
- **Text is one line of plain English signs.** Nothing wraps round at the right edge, a line break is not understood, and every sign outside the 95 plain ones, a letter with an accent among them, shows as an empty box. The letters have one shape and one thickness; larger text is the same shapes with bigger dots.
- **The kernel's own lines have colours and a size of their own,** white letters at size 2 on dark blue, and white on dark red when the kernel stops, whatever the look; and only the last 100 lines are kept, each with at most 300 signs. The rest of a longer line is in the terminal only. See "The kernel's lines" in [screen.md](screen.md).
- **Once the start is over, the kernel's lines show only after F1.** What is printed later, a fetched page's report or an app's printed lines, is not seen on the screen without it.
- **Once the tasks run, the kernel's lines are painted by the main loop.** A task that stops all work with device signals off, without a failure, keeps the lines printed just before off the screen.
- **Between the takeover and the kernel's own page tables, the screen's memory is reached through the firmware's.** That held in QEMU. On a real PC it is expected, since the firmware wrote its own text there a moment before, but it was not seen. A screen whose memory lies above 4 GB, which `screen_reach` maps, was not tried either.
- **Nothing remembers what is written where,** except the chat box, which keeps its own rows and paints them again, the box that shows an app's text, which keeps that text so that it can be painted again in another look, and the kernel's lines, which keep the last 100. Elsewhere text cannot be taken off again except by painting over it.
- **Painting is slow.** Filling the screen takes roughly 0.16 s in this kind of build, possibly up to half as much again, at startup with device signals off. Dots are written one at a time, each through a function call; writing a row in one go was measured at twenty times the speed and not kept, for the sake of plain code.
- **There is one picture and no copy of it.** What is painted shows at once, half-finished drawing included, and nothing remembers what was under a rectangle.
- **Nothing decides who may draw.** Any code in the kernel can paint anywhere, and two tasks drawing at once give a mixed picture. Today drawing happens at startup and, for the chat box and for the whole screen when a look is tried, in the main loop; no other task draws.
- **The screen's memory may lie in ordinary memory.** With QEMU's `ramfb` display it does, in a stretch the firmware's memory map calls kind 0, "set aside". The frame pile takes only kind 7, and the plan to hand out the firmware's startup memory (kinds 3 and 4, see "Memory") would not touch kind 0 either. This rests on the firmware's map: a firmware that listed the screen's memory as one of those kinds would have it handed out.
- The screen's memory is device memory and is mapped like ordinary memory; see "Network" for the "do not cache" mark. For a screen, real hardware has a mark of its own that makes many small writes fast, which the kernel does not set either.
- **Two ways of writing a colour are known:** red, green, blue and blue, green, red, at four bytes a dot. A screen that describes its colours with masks is refused, although it could be used. Only the second order was ever seen.
- **The screen is taken as the firmware left it.** The kernel does not choose a size, and looks at the first graphics service only, so a machine with two screens shows one.
- **A screen that can only be drawn on through the firmware's functions is refused.** Those functions are gone after the takeover.
- The sentence written at startup is a demonstration, and so is the app that shows a text.
- **There are four looks to pick from, and a look is colours only.** Sizes, places and the letters' shapes stay as they were built, and there is no look but these four.
- **The kernel does not check that a look can be read.** The four looks are written into it and were checked from outside by a stated measure (see "The look" in [screen.md](screen.md)). Nothing in the kernel would stop a look whose letters cannot be told from what lies behind them.
- **The usual picture first appears when the start is over,** about four seconds after the devices start, or at the first key before then; the start itself shows the kernel's lines. It appears in the look kept in the notebook; a start without a notebook keeps the first look.
- **Painting the whole screen again for a look is slow,** about a quarter of a second, for the same reason as filling it: a dot at a time. The same painting ends every start, when the usual picture takes the place of the kernel's lines. Keys typed meanwhile wait in the keyboard's line of 16 key numbers; those that do not fit are lost.
- **A kept look is found by its name, letter for letter.** A look renamed in a later kernel would not be found, and the first look would show.
- **The box that shows an app's text remembers 160 bytes of it,** enough for the 40 signs that fit today. A box made wide enough for more would have its text cut when it is painted again in another look.

## Real hardware

The kernel has only run in QEMU. Known differences to expect:

- Use a FAT32 USB stick with the kernel at `EFI\BOOT\BOOTX64.EFI`, with Secure Boot switched off. Never the machine's main disk.
- Most PCs have no serial port. The kernel's lines then show on the screen only (see "The kernel's lines" in [screen.md](screen.md)). A machine without one was played in QEMU by a kernel that finds none; none was met for real.
- Many modern PCs have no PS/2 keyboard controller, because their keyboards are USB. The keyboard code may stay silent there.
- The old interrupt controller and timer chips are usually still present, but that is not guaranteed.
- The kernel assumes 4-level page tables. A firmware that hands over with 5-level tables switched on (bit 12 of `cr4`) needs a check first: loading 4-level tables there resets the machine without a message.
- The interrupt controller's signals reach the processor only if the firmware left the processor's own interrupt unit (the local APIC) passing them through. The kernel does not set that up.
- The interrupt controller is set up without pauses between its commands. QEMU does not need them; very old hardware might.
