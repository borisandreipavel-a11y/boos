"""Boots a kernel (KERNEL_FILE) on a fresh divided disk to the prompt and reports its lines.
Usage: python boot_count.py <tag>
`start_report` is the check itself. test_secret_keyed.py makes the same report from its own start, which is the same
kind of start, so that run_tests.py needs no boot for this check alone."""
import sys

WANTED = ("Free memory", "Lock:", "Interpreter:", "JSON:", "Disk: ", "Kernel:", "Kernel panic", "CPU fault")


def start_report(raw):
    """The report on a start, from the terminal's bytes `raw`, and what is wrong in it: the prompt never came, bytes
    that are not plain text or stray line ends, a panic or a fault."""
    from interp_helpers import odd_bytes
    begin = raw.find(b"Hello from my kernel!")
    raw = raw[begin:] if begin >= 0 else raw
    lines = [line.decode(errors="replace") for line in raw.split(b"\r\n")[:-1]]
    end = next((i for i, line in enumerate(lines) if line.startswith("Click the QEMU window")), None)
    odd = odd_bytes(raw)
    report = ["lines to the prompt: %s" % (end + 1 if end is not None else "THE PROMPT NEVER CAME"),
              "bytes that are not plain text or stray line ends: %d" % odd]
    for wanted in WANTED:
        found = [line for line in lines if line.startswith(wanted)]
        if found:
            report.append("  " + " | ".join(found))
    wrong = []
    if end is None:
        wrong.append("the prompt never came")
    if odd:
        wrong.append("bytes that are not plain text or stray line ends")
    if any(line.startswith(("Kernel panic", "CPU fault")) for line in lines):
        wrong.append("a panic or a fault")
    return report, wrong


if __name__ == "__main__":
    from interp_helpers import boot_lines  # sets the divided disk
    from verdict import Failures

    stamps, raw = boot_lines(sys.argv[1])
    report, wrong = start_report(raw)
    print("\n".join(report))
    failures = Failures()
    failures.extend(wrong)
    print("FAILURES:", failures if failures else "none")
