# Open points

What is known to be missing, limited or waiting. Nothing here is done. Remove a point when it is dealt with, and say so in the matching note.

## Before several tasks can run

- **The device stub saves only nine registers.** Switching from one task to another from the timer needs every register saved, so `device_entry!` will need revisiting.
- **Each task needs a stack of its own.** The heap or the frame pile can provide one.
- **The memory code is not protected.** The frame pile, the page tables and the heap must not be entered twice at once. Before a task can be switched away in the middle of them, they need protection, for example by switching device signals off around them.
- **The kernel has no stack of its own.** It still runs on the firmware's. There is also no spare stack for failures, so a failure inside the failure report, or running out of stack, resets the machine without a message.

## Memory

- Reclaim the firmware's startup memory (kinds 3 and 4, about 42 MB of QEMU's 256 MB) once the kernel has its own stack.
- Leave the lowest page unmapped, so that a broken pointer near zero gives a page fault instead of quietly reading memory.
- Return heap memory to the frame pile.
- Make a request that cannot be met fail, instead of stopping the kernel.
- Mark code pages read-only and data pages non-executable. Today every page is writable and nothing is protected.
- `map_page` cannot be used inside the range covered by 2 MB pages. Mapping something small there would need the 2 MB page split up first.

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
