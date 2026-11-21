"""Makes the notices that go with a release of the boot disk, into an output folder:

- NOTICES.txt: for every piece of outside code built into the kernel or the interpreter it carries, its name,
  version and licence, and its own licence, notice and copyright files, word for word. The list of pieces is cargo's
  own (`cargo tree`, for the kernel and for the interpreter, offline: what the build used).
- COPYRIGHT-library.html: Rust's own notices for its standard library, which is built in too, as the Rust in use
  carries them (the component rust-docs).

Some crates hold no licence file. Their texts are kept in release/notices/, taken from their projects' repositories
at the commit the crate was made from; the script checks that the crate still comes from that commit.

    python release/make_notices.py <output folder>

It stops, and makes nothing, if any crate has no licence text, if a kept text belongs to another commit than the
crate's, or if Rust's notices are missing. See docs/release.md."""
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OWN = {os.path.normcase(os.path.abspath(os.path.join(REPO, part))) for part in ("", "interpreter", "password-key")}
LICENCE_FILE = re.compile(r"^(licen[cs]e|copying|notice|copyright|unlicense)", re.IGNORECASE)

# Crates whose files hold no licence text, with the texts kept here instead: the folder, the project, the commit.
KEPT = {
    "omnilua": ("notices/omnilua", "github.com/ianm199/omnilua", "37db04ee6cf40eee93b59ea94480b53bb73ccb1d"),
    "wasmi": ("notices/wasmi", "github.com/wasmi-labs/wasmi", "8273dfb09d493971b7bb12fe614d740cdc857175"),
}
KEPT_FOR = {"lua-code": "omnilua", "lua-gc": "omnilua", "lua-lex": "omnilua", "lua-parse": "omnilua",
            "lua-stdlib": "omnilua", "lua-types": "omnilua", "lua-vm": "omnilua", "omnilua": "omnilua",
            "wasmi": "wasmi", "wasmi_collections": "wasmi", "wasmi_core": "wasmi", "wasmi_ir": "wasmi"}


def stop(reason):
    print("NOT MADE: " + reason)
    sys.exit(1)


def registry_folders():
    home = os.environ.get("CARGO_HOME") or os.path.join(os.path.expanduser("~"), ".cargo")
    source = os.path.join(home, "registry", "src")
    return [os.path.join(source, name) for name in sorted(os.listdir(source))] if os.path.isdir(source) else []


def outside_crates():
    """(name, version, licence, folder) of every outside crate the two builds use, each once, sorted by name."""
    registries = registry_folders()
    found = {}
    for folder in (REPO, os.path.join(REPO, "interpreter")):
        done = subprocess.run(["cargo", "tree", "--offline", "-e", "normal,build", "--prefix", "none",
                               "--format", "{p}|{l}"], cwd=folder, capture_output=True, text=True)
        if done.returncode:
            stop("cargo tree failed in %s: %s" % (folder, done.stderr.strip()[-400:]))
        for line in done.stdout.splitlines():
            line = line.replace(" (*)", "").strip()
            if "|" not in line:
                continue
            package, licence = line.split("|", 1)
            parts = package.split()
            name, version = parts[0], parts[1].lstrip("v")
            path = re.search(r"\((.+)\)$", package)
            if path:
                where = os.path.abspath(path.group(1))
                if os.path.normcase(where) in OWN:
                    continue
            else:
                where = next((os.path.join(r, "%s-%s" % (name, version)) for r in registries
                              if os.path.isdir(os.path.join(r, "%s-%s" % (name, version)))), None)
                if where is None:
                    stop("the source of %s %s is not among cargo's downloaded crates" % (name, version))
            found.setdefault((name, version), (licence.strip() or "(none named)", where))
    return [(name, version, licence, where) for (name, version), (licence, where) in sorted(found.items())]


def kept_texts(name, where):
    """The kept texts for a crate that holds none, after checking that the crate comes from the commit they do."""
    project = KEPT_FOR.get(name)
    if project is None:
        return None
    folder, repository, commit = KEPT[project]
    info_path = os.path.join(where, ".cargo_vcs_info.json")
    made_from = json.load(open(info_path)).get("git", {}).get("sha1") if os.path.exists(info_path) else None
    if made_from != commit:
        stop("%s comes from commit %s of %s, the kept texts in release/%s from %s: take them again"
             % (name, made_from, repository, folder, commit))
    kept_folder = os.path.join(HERE, folder)
    files = sorted(os.listdir(kept_folder)) if os.path.isdir(kept_folder) else []
    if not files:
        stop("the texts kept for %s are missing from release/%s" % (name, folder))
    return [(os.path.join(kept_folder, file), file) for file in files], "%s at commit %s" % (repository, commit)


def main():
    if len(sys.argv) != 2:
        stop("usage: python release/make_notices.py <output folder>")
    out = os.path.abspath(sys.argv[1])
    version = tomllib.load(open(os.path.join(REPO, "Cargo.toml"), "rb"))["package"]["version"]
    sysroot = subprocess.run(["rustc", "--print", "sysroot"], capture_output=True, text=True).stdout.strip()
    rust_notices = os.path.join(sysroot, "share", "doc", "rust", "COPYRIGHT-library.html")
    if not os.path.exists(rust_notices):
        stop("Rust's notices for its standard library are missing (%s): add the component rust-docs"
             % os.path.join("share", "doc", "rust", "COPYRIGHT-library.html"))

    crates = outside_crates()
    sections, missing, kept_used, file_count = [], [], [], 0
    for name, version_of, licence, where in crates:
        files = [(os.path.join(where, file), file) for file in sorted(os.listdir(where))
                 if LICENCE_FILE.match(file) and os.path.isfile(os.path.join(where, file))]
        if files:
            origin = "a copy kept in vendor/ of the repository, see vendor/README.md" \
                if (os.sep + "vendor" + os.sep) in where else "crates.io"
        else:
            kept = kept_texts(name, where)
            if kept is None:
                missing.append("%s %s" % (name, version_of))
                continue
            files, source = kept
            origin = "crates.io; the crate holds no licence file, so these are its project's, from " + source
            kept_used.append(name)
        lines = ["=" * 78, "%s %s" % (name, version_of), "Licence: " + licence, "From: " + origin, ""]
        for path, file in files:
            text = open(path, "rb").read().decode("utf-8", errors="replace").replace("\r\n", "\n").strip("\n")
            lines += ["---- %s ----" % file, text, ""]
            file_count += 1
        sections.append("\n".join(lines))
    if missing:
        stop("no licence text for: " + ", ".join(missing))

    head = [
        "Notices for boos %s" % version,
        "",
        "The boot disk holds the kernel boos, built from the public code of its repository. The project's own code",
        "may be used under the MIT licence or the Apache License, Version 2.0, whichever you choose (LICENSE-MIT,",
        "LICENSE-APACHE). Built into the kernel, and into the interpreter for Lua that the kernel carries, is code of",
        "other projects. For each such piece, below: its name, version and licence, where it came from, and its own",
        "licence, notice and copyright files, word for word.",
        "",
        "Rust's own standard library is built in too. Its notices are in COPYRIGHT-library.html, beside this file,",
        "as the Rust project publishes them with the Rust this disk was built with.",
        "",
        "%d pieces of outside code, %d files." % (len(sections), file_count),
        "",
    ]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "NOTICES.txt"), "w", encoding="utf-8", newline="\n") as notices:
        notices.write("\n".join(head) + "\n".join(sections) + "\n")
    shutil.copyfile(rust_notices, os.path.join(out, "COPYRIGHT-library.html"))
    print("NOTICES.txt: %d pieces of outside code, %d files; texts kept in release/notices/ used for %d (%s)"
          % (len(sections), file_count, len(kept_used), ", ".join(kept_used)))
    print("COPYRIGHT-library.html: Rust's notices, %d bytes" % os.path.getsize(rust_notices))


if __name__ == "__main__":
    main()
