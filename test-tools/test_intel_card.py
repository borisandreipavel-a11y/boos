"""Intel's network card (src/intel_card.rs) in QEMU, which plays the 82540EM as `e1000` and the 82545EM as
`e1000-82545em`. Each scenario is one start; the network has no way out, except in `page`.

- start: the 82540EM found and set up, its address read from its memory chip, the gateway's answer, the address
  given; every packet of the start recorded, the kernel's first question byte for byte; a start judged as
  boot_count.py judges one.
- address: the card with another address of its own: that one is printed, and answers still come.
- model545: the 82545EM, named and set up, with the gateway's answer and the address given.
- both: a virtio card and an Intel card: the virtio card is used, with the lines a virtio start prints.
- fallback: a virtio card that cannot be set up (its newer way switched off) and an Intel card: the Intel card.
- nothing: the card attached to nothing: the gateway does not answer, no address comes, and the start goes on.
- asking: the card on a network where nobody has 10.0.2.2: the kernel asks for it exactly twice (counted in a
  recording, so that the count does not hang on how fast this computer looks), then the stack gets its address.
- again: the card set up twice (a copy of the kernel), so that the second setup finds it used and starts it over;
  it works after that. QEMU's card only clears the bit it is told to start over with, so this runs the steps and
  shows that they end, not what a real card does then.
- many: 600 questions to the gateway in a row (a copy of the kernel with a loop), so that both rings go round
  many times.
- page: a page of 300,000 bytes from a test server on this computer, through the encrypted link (a copy of the
  kernel that fetches from there): whole, and the digest of what arrived is the digest of what was sent.

A break on purpose (run_intel_card_breaks.py, or run_tests.py) comes as KERNEL_FILE; the scenarios that build a
copy of their own (many, page) take its change from KERNEL_BREAK into their copy too.
Usage: python test_intel_card.py [scenario ...]   (default: all)"""
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import threading
import time

from boot import HINT, KERNEL, RUNS, Machine, ask
from boot_count import start_report
from certs import test_keys
from copy_break import swapped
from net_copy import build
from ports import standin_port
from verdict import Failures

PORT = standin_port(9)  # the test server of `page`
QEMU_ADDRESS = bytes([0x52, 0x54, 0x00, 0x12, 0x34, 0x56])  # the address QEMU gives a card
OTHER_ADDRESS = "52:54:00:aa:bb:cc"
GATEWAY_ANSWER = "Network: the gateway 10.0.2.2 answered, its address is 52:55:0a:00:02:02"
NO_ANSWER = "Network: the gateway 10.0.2.2 did not answer"
# The gateway line of a start with QEMU's Intel card. QEMU holds the card's arriving packets back for a second after
# receiving is switched on, and the by-hand question counts its wait in looks, not in time: on a computer that looks
# fast enough, its two rounds end before the answer is handed over (seen on a GitHub computer). Either line is right
# there; the recording of `start` shows that the answer comes, and `asking` that the question is asked twice.
INTEL_GATEWAY = (GATEWAY_ANSWER, NO_ANSWER)
GIVEN = "Network: this machine was given the address 10.0.2.15 by 10.0.2.2"
SECOND_CARD = ["-netdev", "user,id=net1,restrict=on", "-device", "e1000,netdev=net1,mac=" + OTHER_ADDRESS]
failures = Failures()


def break_made():
    """The break on purpose that the test's kernel was built with, as a change for net_copy.build, or {}."""
    given = os.environ.get("KERNEL_BREAK")
    if not given:
        return {}
    file, old, new = json.loads(given)
    return {file: lambda text: swapped(text, old, new)}


def start(tag, card, extra=None, network=True, kernel=KERNEL, wait=120, after=3.0):
    """One start with the card named (BOOS_NETWORK_CARD for boot.py), to the prompt and `after` seconds more.
    Gives back the terminal's bytes and what QEMU's monitor says about the PCI list."""
    if card:
        os.environ["BOOS_NETWORK_CARD"] = card
    else:
        os.environ.pop("BOOS_NETWORK_CARD", None)
    machine = Machine(tag, extra=extra, network=network, kernel=kernel)
    try:
        if not machine.wait_for(HINT, wait):
            failures.append("%s: the prompt never came" % tag)
        time.sleep(after)
        pci = ask(machine, "info pci")
    finally:
        raw = machine.quit()
        os.environ.pop("BOOS_NETWORK_CARD", None)
    return raw, pci


def lines_of(raw):
    return [line.decode(errors="replace") for line in raw.split(b"\r\n")[:-1]]


def network_lines(raw):
    return [line for line in lines_of(raw) if line.startswith("Network")]


def check_start(tag, raw):
    """A start judged as boot_count.py judges one: the prompt, plain text only, no panic or fault."""
    _, wrong = start_report(raw)
    for reason in wrong:
        failures.append("%s: %s" % (tag, reason))


def expect_lines(tag, raw, meant):
    """The start's network lines must be exactly `meant`, in that order, with no other network line among them. A
    place in `meant` that holds a tuple takes any one of its lines."""
    said = network_lines(raw)
    print("%s: %s" % (tag, " | ".join(said)))
    fits = len(said) == len(meant) and all(line in want if isinstance(want, tuple) else line == want
                                           for line, want in zip(said, meant))
    if not fits:
        failures.append("%s: the network lines are not as meant" % tag)
        print("   meant: " + " | ".join(" or ".join(want) if isinstance(want, tuple) else want for want in meant))


def slot_of(pci, model):
    """The device number at which QEMU's PCI list (from its monitor) shows the Intel card of that model."""
    place = None
    for line in pci.splitlines():
        words = line.strip()
        if words.startswith("Bus") and "device" in words:
            place = int(words.split("device")[1].split(",")[0])
        if "PCI device 8086:%s" % model in words:
            return place
    return None


def recorded(path):
    """The packets of a recording made with QEMU's filter-dump (the pcap format)."""
    data = open(path, "rb").read()
    packets, at = [], 24
    while at + 16 <= len(data):
        length = struct.unpack_from("<I", data, at + 8)[0]
        packets.append(data[at + 16:at + 16 + length])
        at += 16 + length
    return packets


def question_from(address):
    """The kernel's first packet as network.rs builds it: who has 10.0.2.2, asked by 10.0.2.15."""
    question = bytearray(60)
    question[0:6] = b"\xff" * 6
    question[6:12] = address
    question[12:22] = bytes([0x08, 0x06, 0x00, 0x01, 0x08, 0x00, 6, 4, 0x00, 0x01])
    question[22:28] = address
    question[28:32] = bytes([10, 0, 2, 15])
    question[38:42] = bytes([10, 0, 2, 2])
    return bytes(question)


def scenario_start():
    dump = os.path.join(RUNS, "intel-start.pcap")
    if os.path.exists(dump):
        os.remove(dump)
    raw, pci = start("intel-start", "e1000", extra=["-object", "filter-dump,id=dump0,netdev=net0,file=" + dump])
    check_start("start", raw)
    slot = slot_of(pci, "100e")
    expect_lines("start", raw, [
        "Network card: found, an Intel 82540EM, device %s on bus 0 of the PCI list" % slot,
        "Network card: ready, its address is 52:54:00:12:34:56",
        INTEL_GATEWAY, GIVEN,
        "Network: no page fetched, because the network named no name server"])
    packets = recorded(dump)
    question = question_from(QEMU_ADDRESS)
    asked = [p for p in packets if p[:60] == question and len(p) in (60, 64)]
    answers = [p for p in packets if p[12:14] == b"\x08\x06" and p[20:22] == b"\x00\x02" and p[28:32] == bytes([10, 0, 2, 2])]
    ours = [p for p in packets if p[6:12] == QEMU_ADDRESS]
    dhcp_out = [p for p in ours if p[12:14] == b"\x08\x00" and p[23] == 17 and p[36:38] == b"\x00\x43"]
    dhcp_in = [p for p in packets if p[12:14] == b"\x08\x00" and p[23] == 17 and p[34:36] == b"\x00\x43"]
    print("start: %d packets recorded; the kernel's question %d times, byte for byte; %d answers from the gateway; "
          "%d address requests out, %d answers in" % (len(packets), len(asked), len(answers), len(dhcp_out), len(dhcp_in)))
    if not asked:
        failures.append("start: the kernel's first question is not in the recording byte for byte")
    if not answers:
        failures.append("start: no answer from the gateway in the recording")
    if len(dhcp_out) < 2 or len(dhcp_in) < 2:
        failures.append("start: the address request is not all in the recording")
    odd = [p for p in ours if len(p) < 60]
    if odd:
        failures.append("start: %d packets of the kernel shorter than 60 bytes" % len(odd))


def scenario_address():
    raw, pci = start("intel-address", "e1000,mac=" + OTHER_ADDRESS)
    check_start("address", raw)
    expect_lines("address", raw, [
        "Network card: found, an Intel 82540EM, device %s on bus 0 of the PCI list" % slot_of(pci, "100e"),
        "Network card: ready, its address is " + OTHER_ADDRESS,
        INTEL_GATEWAY, GIVEN,
        "Network: no page fetched, because the network named no name server"])


def scenario_model545():
    raw, pci = start("intel-545", "e1000-82545em")
    check_start("model545", raw)
    expect_lines("model545", raw, [
        "Network card: found, an Intel 82545EM, device %s on bus 0 of the PCI list" % slot_of(pci, "100f"),
        "Network card: ready, its address is 52:54:00:12:34:56",
        INTEL_GATEWAY, GIVEN,
        "Network: no page fetched, because the network named no name server"])


def scenario_both():
    raw, pci = start("intel-both", None, extra=SECOND_CARD)
    check_start("both", raw)
    if slot_of(pci, "100e") is None:
        failures.append("both: QEMU shows no Intel card")
    expect_lines("both", raw, [
        "Network card: found, device 3 on bus 0 of the PCI list",
        "Network card: ready, its address is 52:54:00:12:34:56",
        GATEWAY_ANSWER, GIVEN,
        "Network: no page fetched, because the network named no name server"])


def scenario_fallback():
    raw, pci = start("intel-fallback", "virtio-net-pci,disable-modern=on", extra=SECOND_CARD)
    check_start("fallback", raw)
    expect_lines("fallback", raw, [
        "Network card: found, device 3 on bus 0 of the PCI list",
        "Network card: not set up, because it does not offer the newer way of working",
        "Network card: found, an Intel 82540EM, device %s on bus 0 of the PCI list" % slot_of(pci, "100e"),
        "Network card: ready, its address is " + OTHER_ADDRESS,
        INTEL_GATEWAY, GIVEN,
        "Network: no page fetched, because the network named no name server"])


def scenario_nothing():
    raw, pci = start("intel-nothing", None, extra=["-device", "e1000"], network=False, after=5.0)
    check_start("nothing", raw)
    expect_lines("nothing", raw, [
        "Network card: found, an Intel 82540EM, device %s on bus 0 of the PCI list" % slot_of(pci, "100e"),
        "Network card: ready, its address is 52:54:00:12:34:56",
        "Network: the gateway 10.0.2.2 did not answer"])


def scenario_asking():
    dump = os.path.join(RUNS, "intel-asking.pcap")
    if os.path.exists(dump):
        os.remove(dump)
    extra = ["-netdev", "user,id=net0,net=192.168.76.0/24,dhcpstart=192.168.76.9,restrict=on", "-device", "e1000,netdev=net0",
             "-object", "filter-dump,id=dump0,netdev=net0,file=" + dump]
    raw, pci = start("intel-asking", None, extra=extra, network=False)
    check_start("asking", raw)
    expect_lines("asking", raw, [
        "Network card: found, an Intel 82540EM, device %s on bus 0 of the PCI list" % slot_of(pci, "100e"),
        "Network card: ready, its address is 52:54:00:12:34:56",
        "Network: the gateway 10.0.2.2 did not answer",
        "Network: this machine was given the address 192.168.76.9 by 192.168.76.2",
        "Network: no page fetched, because the network named no name server"])
    asked = [p for p in recorded(dump) if p[:60] == question_from(QEMU_ADDRESS)]
    print("asking: the kernel's question %d times in the recording" % len(asked))
    if len(asked) != 2:
        failures.append("asking: the kernel asked for the gateway %d times, not twice" % len(asked))


def with_break(changes):
    """`changes` (file: change) with the break on purpose of KERNEL_BREAK, if any, made first in its file."""
    made = break_made()
    for file, change in changes.items():
        if file in made:
            first = made[file]
            made[file] = lambda text, first=first, change=change: change(first(text))
        else:
            made[file] = change
    return made


# The copy for `again`: the card set up twice, and a line when a setup starts the card over.
AGAIN_OLD = "            match intel_card_setup(card) {\n"
AGAIN_NEW = "            let _ = intel_card_setup(card); // TEST: the second setup finds the card used\n" + AGAIN_OLD
OVER_OLD = "        // Stop receiving and sending, so that no packet is on its way into\n"
OVER_NEW = "        crate::serial::serial_print(\"TEST started over\\r\\n\");\n" + OVER_OLD


def scenario_again():
    kernel = build(PORT, more=with_break({"main.rs": lambda text: swapped(text, AGAIN_OLD, AGAIN_NEW),
                                          "intel_card.rs": lambda text: swapped(text, OVER_OLD, OVER_NEW)}), redirect=False)
    raw, pci = start("intel-again", "e1000", kernel=kernel)
    check_start("again", raw)
    over = [line for line in lines_of(raw) if line.startswith("TEST")]
    print("again: %s" % (" | ".join(over) or "no line about starting over"))
    if over != ["TEST started over"]:
        failures.append("again: the second setup did not start the card over, once")
    expect_lines("again", raw, [
        "Network card: found, an Intel 82540EM, device %s on bus 0 of the PCI list" % slot_of(pci, "100e"),
        "Network card: ready, its address is 52:54:00:12:34:56",
        INTEL_GATEWAY, GIVEN,
        "Network: no page fetched, because the network named no name server"])


# The copy for `many`: 600 questions to the gateway right after the card is set up, and how many were answered.
MANY_OLD = "            // The kernel's first packet: ask who the gateway is.\n"
MANY_NEW = ("            {\n                let mut test_answered = 0; // TEST: 600 questions in a row\n"
            "                for _ in 0..600 {\n                    if gateway_ask(address).is_some() {\n"
            "                        test_answered += 1;\n                    }\n                }\n"
            "                write!(serial, \"TEST {} of 600 answered\\r\\n\", test_answered).ok();\n            }\n" + MANY_OLD)


def scenario_many():
    kernel = build(PORT, more=with_break({"main.rs": lambda text: swapped(text, MANY_OLD, MANY_NEW)}), redirect=False)
    os.environ["BOOS_NETWORK_CARD"] = "e1000"
    machine = Machine("intel-many", kernel=kernel)
    started = time.time()
    try:
        came = machine.wait_for(b"TEST ", 90) and machine.wait_for(b"answered\r\n", 5)
        took = time.time() - started
        time.sleep(1)
    finally:
        raw = machine.quit()
        os.environ.pop("BOOS_NETWORK_CARD", None)
    said = [line for line in lines_of(raw) if line.startswith("TEST ")]
    print("many: %s (%.0f s from the machine's start)" % (" | ".join(said) or "no line came", took))
    if not came or said != ["TEST 600 of 600 answered"]:
        failures.append("many: not every one of 600 questions was answered")
    if any(line.startswith(("Kernel panic", "CPU fault")) for line in lines_of(raw)):
        failures.append("many: a panic or a fault")


def scenario_page():
    tls = test_keys()
    body = bytes((index * 7 + index // 997) % 95 + 32 for index in range(300_000))
    head = b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n" % len(body)
    sent = head + body
    kernel = build(PORT, roots=["a"], more=break_made())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(os.path.join(tls, "a", "both-chain.pem"), os.path.join(tls, "a", "both.key"))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", PORT))
    listener.listen(2)
    listener.settimeout(120)
    seen = {}

    def serve():
        try:
            raw, _ = listener.accept()
            raw.settimeout(60)
            with context.wrap_socket(raw, server_side=True) as link:
                request = b""
                while b"\r\n\r\n" not in request:
                    piece = link.recv(4096)
                    if not piece:
                        break
                    request += piece
                seen["request"] = request
                link.sendall(sent)
                link.unwrap()
                seen["sent"] = True
        except (OSError, ssl.SSLError) as problem:
            seen["problem"] = repr(problem)

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    os.environ["BOOS_NETWORK_CARD"] = "e1000"
    machine = Machine("intel-page", kernel=kernel, network="open")
    try:
        machine.wait_for(b"bytes long.", 120) or machine.wait_for(b"no page fetched", 1)
        machine.wait_for(b"TEST digest", 10)
        time.sleep(1)
    finally:
        raw = machine.quit()
        os.environ.pop("BOOS_NETWORK_CARD", None)
        listener.close()
    said = network_lines(raw)
    digests = [line for line in lines_of(raw) if line.startswith("TEST digest")]
    meant_digest = "TEST digest %s of %d bytes" % (hashlib.sha256(sent).hexdigest(), len(sent))
    print("page: %s" % " | ".join(line for line in said if "page" in line or "proved" in line or "answered \"" in line))
    print("page: %s; the server saw %r" % (" | ".join(digests) or "no digest", seen.get("request", seen.get("problem"))))
    if seen.get("request") != b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n":
        failures.append("page: the server did not see the kernel's request as meant")
    if "Network: the whole page is %d bytes long." % len(body) not in said:
        failures.append("page: the page did not come whole")
    if digests != [meant_digest]:
        failures.append("page: what arrived is not what was sent")


SCENARIOS = {"start": scenario_start, "address": scenario_address, "model545": scenario_model545, "both": scenario_both,
             "fallback": scenario_fallback, "nothing": scenario_nothing, "asking": scenario_asking, "again": scenario_again,
             "many": scenario_many, "page": scenario_page}


def main():
    if os.environ.get("KERNEL_BREAK"):
        print("BREAK ON PURPOSE: %s" % json.loads(os.environ["KERNEL_BREAK"])[:1])
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none")


if __name__ == "__main__":
    main()
