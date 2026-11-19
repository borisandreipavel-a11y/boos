"""Gives every changed or new text file of the project Windows line ends, and says which ones needed it."""
import subprocess

import os

from places import PROJECT
names = subprocess.run(["git", "ls-files", "-m", "-o", "--exclude-standard"], cwd=PROJECT, capture_output=True, text=True).stdout.split()
for name in names:
    if name == 'README.md':
        continue  # the front page is left as it is
    path = os.path.join(PROJECT, *name.split("/"))
    data = open(path, "rb").read()
    if data.count(b"\n") != data.count(b"\r\n"):
        open(path, "wb").write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        print("mended:", name)
print("%d files looked at" % len(names))
