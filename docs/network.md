# The network: the PCI list and the network card

Code: `src/pci.rs`, `src/network_card.rs`. The 4-byte port functions are in `src/processor.rs`.

So far the kernel only finds the network card. It reads the card's facts and writes nothing to it. It sends and receives nothing.

## The PCI list

- A PC keeps its cards and built-in devices on the PCI list. A place on the list is named by three numbers: the bus (a row of slots, 0 to 255), the device (a slot of that row, 0 to 31) and the function (one of up to 8 devices sharing a slot).
- Each place holds a small table of facts about its device. The first 4 bytes are the maker (low half) and the model (high half). An empty place answers with every bit set.
- `pci_read(place, offset)` reads 4 bytes of that table. It takes two steps: write which place and which 4 bytes to port `0xCF8`, then read the answer from port `0xCFC`. The two steps belong together, so signals are switched off around them.
- Those two ports work with 4 bytes at a time, which is what `port_write_32` and `port_read_32` are for.
- `pci_find(maker, model)` walks the whole list and returns the first place that states that maker and model.
  - It tries every bus and every slot. It does not follow bridges; trying all 256 buses finds devices behind them as well.
  - If function 0 of a slot is empty, the slot is empty and its other functions are skipped.
  - The other functions are tried only if function 0 says there are several: bit 7 of the byte at offset 14.
- Nothing is written to any device. Switching a device on, and reading where its ports and memory are, comes with the driver.

## The network card

- QEMU's card is a "virtio" card: one that exists only in virtual machines and is made to be simple to drive.
- Its maker's number is `0x1AF4`. Its model is `0x1000` for QEMU's usual card, which knows an older and a newer way of working, and `0x1041` for the card that knows only the newer way.
- `network_card_find()` looks for either and returns its place. `efi_main` prints the place, or "none found".
- A network card of another make is not recognised and counts as none.

How the usual card shows up in QEMU 11.1, as seen with the monitor's `info pci`:

- device 3 on bus 0, function 0;
- signal line 11. That line is on the second chip of the interrupt controller, which the kernel holds back entirely today; see [interrupts.md](interrupts.md);
- ports at `0xc000`, 32 of them: the older way of working;
- memory at `0xc000000000`: the newer way of working. That is far above the 4 GB the kernel's page tables cover, so it would have to be mapped first; see [memory.md](memory.md).

QEMU's whole list on its default machine, for comparison when testing: `0:0.0` `8086:1237`, `0:1.0` `8086:7000`, `0:1.1` `8086:7010`, `0:1.3` `8086:7113`, `0:2.0` `1234:1111`, and the card at `0:3.0`.

## QEMU's built-in network

`run.bat` attaches the card to QEMU's built-in network (`-netdev user`). QEMU plays a small network of its own and passes traffic on through the host computer:

- the network is `10.0.2.0` and the card's own address is `52:54:00:12:34:56`, as the monitor's `info network` shows;
- by QEMU's documentation the gateway is at `10.0.2.2` and a name server at `10.0.2.3`. The kernel has not talked to either yet;
- nothing outside can reach the kernel; only what the kernel sends out gets answers.

With the card attached, the firmware uses a little more memory during startup, and "Free memory" reads 205 MB instead of 206.

Nothing is sent yet. A boot with QEMU recording every packet on that network, from the firmware's start to three seconds after the kernel's prompt, recorded none. The option for that is in [testing.md](testing.md).
