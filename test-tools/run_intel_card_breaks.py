"""Breaks Intel's network card on purpose, one break at a time, in a copy of the project (copy_break.py), and sees
whether test_intel_card.py catches each one, booting the copy's kernel. The project itself is only read, so other
tests can run beside these.
Usage: python run_intel_card_breaks.py [break ...]   (default: all)
BREAKS is data: run_tests.py runs the same breaks."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# label: (file, old, new, scenarios of test_intel_card.py that must catch it)
BREAKS = {
    # Setting the card up.
    "receiving never switched on": ("intel_card.rs",
        "    device_write_32(controls + RECEIVING, RECEIVE_ON | TAKE_BROADCASTS | STRIP_CHECK);\n",
        "    device_write_32(controls + RECEIVING, TAKE_BROADCASTS | STRIP_CHECK);\n", ["start"]),
    "the card may not reach memory": ("intel_card.rs", "    pci_write(place, 4, settings | 0x0406);\n",
        "    pci_write(place, 4, (settings | 0x0402) & !0x0004);\n", ["start"]),
    "a used card not started over": ("intel_card.rs", "    if used {\n", "    if used && false {\n", ["again"]),
    "the address read with its bytes swapped": ("intel_card.rs",
        "        address[word * 2] = value as u8;\n        address[word * 2 + 1] = (value >> 8) as u8;\n",
        "        address[word * 2] = (value >> 8) as u8;\n        address[word * 2 + 1] = value as u8;\n", ["start"]),
    # Packets.
    "a packet's length read from the wrong place": ("intel_card.rs",
        "                    let written = device_read_16(description + RECEIVED_LENGTH) as usize;\n",
        "                    let written = device_read_16(description + 10) as usize;\n", ["start"]),
    "a received slot never handed back": ("intel_card.rs",
        "                device_write_32(CONTROLS + RECEIVE_RING + RING_TAIL, slot as u32);\n", "", ["many"]),
    "the send ring does not go round": ("intel_card.rs", "            let next = (slot + 1) % SEND_SLOTS;\n",
        "            let next = slot + 1;\n", ["many"]),
    # Which card is used.
    "the virtio card not looked for first": ("main.rs",
        "    if let Some(card) = network_card_find() {\n        card_found = true;\n",
        "    if let Some(card) = None::<pci::PciPlace> {\n        card_found = true;\n", ["both"]),
    "no Intel card after a virtio card that cannot be set up": ("main.rs",
        "    if card_address.is_none() {\n        if let Some((card, model)) = intel_card_find() {\n",
        "    if !card_found {\n        if let Some((card, model)) = intel_card_find() {\n", ["fallback"]),
    # The gateway question.
    "the gateway asked once only": ("network.rs", "const ASKINGS: u32 = 2;\n", "const ASKINGS: u32 = 1;\n", ["asking"]),
}


def main():
    from copy_break import NotMade, make
    from places import RUNS
    kernel_out = os.path.join(RUNS, "intel-break-kernel.efi")
    results, not_made = [], 0
    for label in sys.argv[1:] or list(BREAKS):
        file, old, new, scenarios = BREAKS[label]
        print("BREAK ON PURPOSE:", label, flush=True)
        try:
            kernel = make(file, old, new, kernel_out)
        except (NotMade, RuntimeError) as reason:
            not_made += 1
            print("   THE BREAK WAS NOT MADE |", str(reason)[-400:], flush=True)
            continue
        run = subprocess.run([sys.executable, "test_intel_card.py"] + scenarios, cwd=HERE, capture_output=True, text=True,
                             env=dict(os.environ, KERNEL_FILE=kernel, KERNEL_BREAK=json.dumps([file, old, new])))
        last = [l for l in run.stdout.splitlines() if l.startswith("FAILURES:")]
        caught = bool(last) and last[-1] != "FAILURES: none"
        first = [l for l in run.stdout.splitlines() if l.startswith("FAILED:")]
        print("   caught" if caught else "   NOT CAUGHT", "|", (first[0][:170] if first else (run.stdout + run.stderr)[-400:]), flush=True)
        results.append((label, caught))
    print("caught %d of %d%s" % (sum(c for _, c in results), len(results), "; %d not made" % not_made if not_made else ""))
    sys.exit(1 if not_made else 0)


if __name__ == "__main__":
    main()
