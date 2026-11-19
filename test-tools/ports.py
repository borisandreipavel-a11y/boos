"""Port numbers for the test tools, so that two checkouts can be tested at the same time.

Two kinds of numbered door are used:

- QEMU's monitor (how a test types keys and saves pictures). free_port() asks Windows for a door
  nobody holds, just before QEMU starts. Nothing has to be planned between them.
- The stand-in provider and the TLS test server. Their number is built into a copy of the kernel,
  so it cannot be picked at the last moment. standin_port(n) gives the n-th number of this
  checkout's own range. The range starts at the environment variable BOOS_PORT_BASE (44300 when
  it is not set). Give a second checkout another base, for example BOOS_PORT_BASE=47300.
"""

import os
import socket

DEFAULT_BASE = 44300


def free_port():
    """A port on 127.0.0.1 that nothing holds right now.

    Windows picks it. Between closing it here and QEMU taking it, another program could take it;
    then QEMU does not start, and boot.py says so instead of talking to the wrong program."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def port_base():
    text = os.environ.get("BOOS_PORT_BASE", "")
    if not text:
        return DEFAULT_BASE
    base = int(text)
    if not 1024 < base < 65000:
        raise ValueError("BOOS_PORT_BASE must lie between 1025 and 64999, not %d" % base)
    return base


def standin_port(number):
    """The number-th port of this checkout's range (number 1 to 99)."""
    if not 1 <= number <= 99:
        raise ValueError("a stand-in port number lies between 1 and 99")
    return port_base() + number
