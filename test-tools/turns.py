"""Turns that all test runs on this computer share, from every checkout:

- seats: at most that many test machines at once on the computer (BOOS_SEATS, 4 when not set). run_tests.py takes
  one seat for each test it runs and gives it back when the test ends;
- the memory turn: the moment a test copies a machine's whole memory (256 MB) to search it, one test at a time;
- the build turn: one build with cargo at a time, so that a build never slows the machines of other tests.

A turn is a lock on a file in the computer's temporary folder (BOOS_TURNS names another folder). The computer gives
it back when the program that holds it ends, however it ends, so a test that is stopped leaves no turn behind.
A test run on its own takes its memory and build turns too; it waits only while another run holds them."""
import contextlib
import os
import tempfile
import time

FOLDER = os.environ.get("BOOS_TURNS") or os.path.join(tempfile.gettempdir(), "boos-tests", "turns")

if os.name == "nt":
    import msvcrt

    def _try_lock(handle):
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(handle):
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(handle):
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(handle):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _open(name):
    os.makedirs(FOLDER, exist_ok=True)
    handle = open(os.path.join(FOLDER, name + ".lock"), "a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
    return handle


def take(name):
    """Takes the turn `name` if nobody holds it: gives back the open file that holds it, or None."""
    handle = _open(name)
    if _try_lock(handle):
        return handle
    handle.close()
    return None


def give_back(handle):
    _unlock(handle)
    handle.close()


@contextlib.contextmanager
def turn(name, pause=0.2):
    """Waits for the turn `name`, holds it inside the `with`, and gives it back."""
    while True:
        handle = take(name)
        if handle:
            break
        time.sleep(pause)
    try:
        yield
    finally:
        give_back(handle)


def memory_turn():
    return turn("memory")


def build_turn():
    return turn("build", pause=0.5)


def seat_count():
    return max(1, int(os.environ.get("BOOS_SEATS") or 4))


def take_seat(pause=1.0, stop=None):
    """Waits for one of the computer's seats and gives back the open file that holds it (None if `stop` was set)."""
    while stop is None or not stop.is_set():
        for number in range(1, seat_count() + 1):
            handle = take("seat-%d" % number)
            if handle:
                return handle
        time.sleep(pause)
    return None
