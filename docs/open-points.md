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
- **Printing holds signals off for a whole text.** On a real serial port a long line takes several milliseconds, which could delay a tick.
- **The first task has no stack of its own.** Task 0 still runs on the firmware's stack. There is also no spare stack for failures, so a failure inside the failure report, or running out of stack, resets the machine without a message.

## Memory

- Reclaim the firmware's startup memory (kinds 3 and 4, about 42 MB of QEMU's 256 MB) once task 0 has a stack of its own.
- Leave the lowest page unmapped, so that a broken pointer near zero gives a page fault instead of quietly reading memory.
- Return heap memory to the frame pile.
- Make a request that cannot be met fail, instead of stopping the kernel.
- Mark code pages read-only and data pages non-executable. Today every page is writable and nothing is protected.
- `map_page` cannot be used inside the range covered by 2 MB pages. Mapping something small there would need the 2 MB page split up first.

## Network

- The kernel can send and receive single packets, and asks one question by hand. It has no network address of its own and no network stack: no connections, no names, no encryption.
- The gateway question assumes the kernel's network address (`10.0.2.15`) instead of being given one.
- Waiting for the gateway's answer is counted in looks, not in time, because it happens at startup with signals off. Tasks can wait for a time now, so network code that runs in a task should use that instead.
- There is one frame for sending, so packets go out one at a time, each waiting for the card to take the one before. That wait can last up to a million looks with device signals off. At startup that harms nothing, but once a task sends packets it breaks the rule to keep such stretches short: ticks and keys would wait too.
- Sixteen frames are lent for arriving packets. If more arrive before the kernel looks, the card has nowhere to put them and they are lost.
- Only virtio cards are recognised, and only through the newer way of working. Real PCs have cards of other makes, each needing its own driver.
- The card is told not to send signals, so nothing announces an arriving packet; code has to keep looking. The card's signal line (11 in QEMU) is on the second chip of the interrupt controller; the kernel holds that chip back entirely, and `signal_done` tells only the first chip. Listening to the card by signal needs all three changed.
- Device memory is mapped like ordinary memory. Real hardware wants it marked "do not cache".
- The frame pile hands out single frames. A device that needs several neighbouring frames in one piece cannot be served yet. The network card's newer way of working was chosen partly because it does not need that.
- The setup runs once. Nothing handles a card that reports a failure later, and nothing sets it up a second time.
- `pci_find` tries all 256 buses rather than following bridges. That is simple and was fast in QEMU; its speed on real hardware is not known.

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
