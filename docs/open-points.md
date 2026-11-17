# Open points

What is known to be missing, limited or waiting. Nothing here is done. Remove a point when it is dealt with, and say so in the matching note.

## Tasks

- **A task can wait for a time, not for an event.** Waiting for a key, a packet or another task means looking again and again with short waits in between. A way to say "wake me when this happens" is missing.
- **Waits are counted in ticks.** The shortest real wait is one tick, 10 ms, and the clock behind it only counts timer signals.
- **Task 0 cannot wait.** It is the task that rests the processor, so its own work has to fit into its main loop.
- **There are 8 places and no priorities.** Every ready task gets the same turn of one tick.
- **Nothing notices a stack that overflows.** A task that uses more than its 64 KB writes into whatever lies below it on the heap. An unmapped page below each stack would turn that into a page fault.
- **A finished task's stack is given back only when its place is reused.**
- **A failure in one task stops everything.** Tasks are not isolated from each other.
- **Printing holds signals off for a whole text.** On a real serial port a long line takes several milliseconds, which could delay a tick. The longest text is the report about a fetched page, about 700 bytes: roughly 60 ms on a real port at the speed set, which is six ticks.
- **The first task has no stack of its own.** Task 0 still runs on the firmware's stack. There is also no spare stack for failures, so a failure inside the failure report, or running out of stack, resets the machine without a message.

## Memory

- Reclaim the firmware's startup memory (kinds 3 and 4, about 42 MB of QEMU's 256 MB when it was measured, before the network card and the present processor option) once task 0 has a stack of its own.
- Leave the lowest page unmapped, so that a broken pointer near zero gives a page fault instead of quietly reading memory.
- Return heap memory to the frame pile.
- Make a request that cannot be met fail, instead of stopping the kernel.
- Mark code pages read-only and data pages non-executable. Today every page is writable and nothing is protected.
- `map_page` cannot be used inside the range covered by 2 MB pages. Mapping something small there would need the 2 MB page split up first.

## Network

- The page fetch is a demonstration: one fixed site, once per start, inside the stack's own task. There is no encryption, so nothing secret may be sent this way, and what arrives may have been read or changed on the way.
- Every start of the kernel reaches the internet: one name question and one request to the site. A machine with no way out prints a "no page fetched" line instead.
- While a page is fetched, the stack's task does nothing else. News about the address waits until the fetch is over, which is about 21 seconds at worst.
- Only the first address of a name is tried: smoltcp is set to keep one. Only the 4-byte sort of address is asked for.
- The site's answer is taken as it comes. A redirect is not followed. The length the site states is not compared with what arrived, so "the whole page" only means that the site ended the connection properly. A site that keeps the connection open is cut off after 10 seconds, and so is a page too big to arrive in that time.
- A page arrives at about 70 KB a second. The card's adapter tells smoltcp "one packet at a time", so the other side sends one packet and waits, and the stack is looked at once per tick. The card could take 16 packets between two looks; saying so, and more room for arrived bytes, would speed this up.
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

## Random numbers and the date

- Random numbers have one source, the processor's own instruction. A processor without it gives none, and the kernel has no second source: not the firmware's, not a virtual machine's device, not noise it gathers itself.
- The numbers are used as the processor hands them out. The kernel does not mix them with anything or run a generator of its own on top, so it trusts the processor's maker entirely, and in QEMU it trusts QEMU.
- The source is tried once, at startup. If it breaks later, that shows only when a draw gives nothing.
- Nothing uses the random numbers or the date yet.
- The kernel does not know whether the clock chip holds local time or world time. Checking a certificate wants world time.
- The date comes as year, month, day, hour, minute and second. Code that checks certificates will probably want a count of seconds since 1970, which is not written.
- The century is looked for in one place of the chip (`0x32`). Real PCs name the place in a table of the firmware (ACPI), which the kernel does not read. Where the value is no century, the year is taken to be in the 2000s.
- Nothing notices a clock that is plainly wrong, such as one whose battery is empty.
- Waiting for a busy chip is counted in looks, not in time.
- `run.bat` asks QEMU for its usual processor plus one instruction. The other processors QEMU can play change how much memory the firmware keeps, and `-cpu max` offers five-level page tables; see "Real hardware".

## Keyboard

- Shift and capitals, Backspace, and layouts other than US are left out.

## The screen

- Drawing on the screen needs the framebuffer's details from the firmware's graphics service. They must be fetched before the takeover, so `take_over` or the code before it will need revisiting then.

## Real hardware

The kernel has only run in QEMU. Known differences to expect:

- Use a FAT32 USB stick with the kernel at `EFI\BOOT\BOOTX64.EFI`, with Secure Boot switched off. Never the machine's main disk.
- Most PCs have no serial port, so the kernel would run but say nothing. It needs screen output first.
- Many modern PCs have no PS/2 keyboard controller, because their keyboards are USB. The keyboard code may stay silent there.
- The old interrupt controller and timer chips are usually still present, but that is not guaranteed.
- The kernel assumes 4-level page tables. A firmware that hands over with 5-level tables switched on (bit 12 of `cr4`) needs a check first: loading 4-level tables there resets the machine without a message.
- The interrupt controller's signals reach the processor only if the firmware left the processor's own interrupt unit (the local APIC) passing them through. The kernel does not set that up.
- The interrupt controller is set up without pauses between its commands. QEMU does not need them; very old hardware might.
