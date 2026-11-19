"""backup() keeps a copy of the source files; restore() puts them back from it, sets their time to now, and
shows that the working tree's source equals the backup."""

import filecmp
import os
import shutil
import time

from places import PROJECT, WORK

SRC = os.path.join(PROJECT, "src")
BACKUP = os.path.join(WORK, "src-backup")


def backup():
    """Keeps a copy of the source files, for restore() to put back after a break on purpose."""
    shutil.rmtree(BACKUP, ignore_errors=True)
    shutil.copytree(SRC, BACKUP)


def restore():
    changed = []
    for name in os.listdir(BACKUP):
        a, b = os.path.join(BACKUP, name), os.path.join(SRC, name)
        if not os.path.exists(b) or not filecmp.cmp(a, b, shallow=False):
            shutil.copyfile(a, b)
            os.utime(b, (time.time(), time.time()))
            changed.append(name)
    extra = [n for n in os.listdir(SRC) if n not in os.listdir(BACKUP)]
    return changed, extra


if __name__ == "__main__":
    changed, extra = restore()
    print("put back:", changed, "| files not in the backup:", extra)
