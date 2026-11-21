# A release of the boot disk

A release puts a ready boot disk (see "The boot disk" in [disk.md](disk.md)) where people can download it and start boos without building it. The disk in a release is built by GitHub from the public code of the repository, never taken from anyone's own runs: a disk that has been used holds the person's name and their locked key, and files built on a person's computer carry that computer's folder names.

## What a release holds

- `boos-<version>.zip`, with:
  - `boot.vdi`, the disk in VirtualBox's own format, made from `boot.img` by QEMU's `qemu-img convert -O vdi` (QEMU 11.1.0's `qemu-img` names `vdi` among the formats it writes). It holds only the parts of the disk that were written, so it is smaller than `boot.img`;
  - `boot.img`, the disk as one raw file of 80 MB, as `make-boot-disk.ps1` makes it, for QEMU; it is also the way back if VirtualBox does not take `boot.vdi`, through `VBoxManage convertfromraw` ("In VirtualBox" in [startup.md](startup.md));
  - `LICENSE-MIT` and `LICENSE-APACHE`, the project's own licence;
  - `NOTICES.txt` and `COPYRIGHT-library.html`, the notices (below).
- `SHA256SUMS.txt` beside the zip: the SHA-256 checksum of the zip and of each file in it, with which anyone can check that a download is byte for byte the one GitHub made.
- The release's text, `release/release-text.md` with the version and the checksums filled in: what boos is, how to start the disk in VirtualBox and in QEMU, that each person needs their own key for OrcaRouter and that every line typed in the chat box, but `key` and `setup`, is paid with it, that it is an early test version tried only in QEMU and VirtualBox, that a start fetches one web page, and that a used disk holds the person's name and locked key.

The version is the one in `Cargo.toml`, the release's tag `v<version>`, its title `boos <version> (early test)`. It is marked as a pre-release, which GitHub describes as "not ready for production and may be unstable"; a pre-release can never be a repository's "latest" release (GitHub's REST documentation), so a link to it names the release itself or the list of releases.

## The notices that go with it

A built disk holds code of other projects besides the project's own: the outside crates built into the kernel, the ones built into the interpreter for Lua that the kernel carries, and Rust's own standard library. Their licences ask for some of their texts to go with every copy, built copies included. So a release carries two files of notices:

- `NOTICES.txt`: for every outside crate, its name, version and licence, where it came from, and its own licence, notice and copyright files, word for word.
- `COPYRIGHT-library.html`: Rust's notices for its standard library, as the Rust project publishes them with the Rust the disk was built with (its component `rustc` carries the file, as its list of files in `lib\rustlib` says, so the smallest set of components has it). It says that the standard library may be used under MIT or Apache-2.0, gives the notices of what is in it (tables from Unicode, parts taken from LLVM and from musl), and holds every licence text it names.

What the licences ask, read from their texts:

- MIT, ISC (rustls-webpki, untrusted, and rustls among its choices) and BSD-3-Clause (subtle): each crate's copyright notice and licence text go with every copy, in a built copy "in the documentation and/or other materials provided with the distribution", as subtle's puts it.
- Apache-2.0: a copy of the licence goes with every copy, and the contents of a crate's `NOTICE` file if it has one. None of the crates here has one.
- CDLA-Permissive-2.0, the licence of webpki-roots, the list of certificate authorities the kernel trusts: the list may be shared "so long as the Data Recipient makes available the text of this agreement with the shared Data".
- 0BSD (managed, smoltcp) and the Unlicense (one of byteorder's two choices): no condition.
- wasmparser may also be used under Apache-2.0 with the LLVM exception, which frees built copies from Apache's conditions 4(a), 4(b) and 4(d).

Every crate's files are carried, whichever of its licences one would choose, so the notices hold for any choice.

## Making the notices

`python release/make_notices.py <folder>` writes both files into the folder. It takes the list of outside crates from cargo itself (`cargo tree`, for the kernel and for the interpreter, without the network: what the builds use) and finds each crate's files where cargo keeps the downloaded crates, or in `vendor/` for the copies kept there ([vendor/README.md](../vendor/README.md)). A crate's files are the ones whose names begin with `LICENSE`, `LICENCE`, `COPYING`, `NOTICE`, `COPYRIGHT` or `UNLICENSE`.

Twelve crates hold no licence file. Their texts are kept in `release/notices/`, taken from their projects' repositories at the commit each crate was made from, as its `.cargo_vcs_info.json` names it:

- the interpreter's omnilua and its seven crates `lua-code`, `lua-gc`, `lua-lex`, `lua-parse`, `lua-stdlib`, `lua-types` and `lua-vm`: `LICENSE` and `NOTICE` of `github.com/ianm199/omnilua` at commit `37db04ee6cf40eee93b59ea94480b53bb73ccb1d`. The `NOTICE` holds the copyright of the Lua it was translated from, "Copyright (c) 1994-2024 Lua.org, PUC-Rio.", which [interpreter.md](interpreter.md) names too;
- wasmi, `wasmi_collections`, `wasmi_core` and `wasmi_ir`: `LICENSE-MIT` and `LICENSE-APACHE` of `github.com/wasmi-labs/wasmi` at commit `8273dfb09d493971b7bb12fe614d740cdc857175`.

Nothing in `release/` runs in the kernel or in a test, so a change there alone boots no test: `release/` is named in `NO_TEST` in [test-tools/suites.py](../test-tools/suites.py).

The script makes nothing, says why and ends with 1, if a crate has no licence text and none is kept for it, if a crate now comes from another commit than its kept texts (take them again then), if kept texts are missing, or if Rust's notices are missing.

Checked on the code of `4353d34`: 76 outside crates, 68 in the kernel and 8 in the interpreter, with 150 files, the kept texts used for the twelve; `NOTICES.txt` of 784,605 bytes, and Rust's notices of Rust 1.100.0, 1,512,515 bytes. Each of the four refusals was tried by changing the script's lists in memory, no file touched: each stopped, said why and wrote nothing.

## Making the files

`python release/make_release.py <folder>` makes everything a release holds into a new or empty folder, and uploads nothing:

1. builds the interpreter and the kernel (`test-tools/build_all.py`, which also sees that the kernel holds the interpreter just built);
2. makes `boot.img` with `make-boot-disk.ps1`, then `boot.vdi` from it with `qemu-img`, and checks with `qemu-img compare` that the two hold the same contents, block for block, and with `qemu-img info` that they are disks of the same size (`compare`'s strict mode would also ask that the same blocks be stored, which a VDI, storing only blocks that hold something, does not);
3. makes the notices (`release/make_notices.py`) and copies the project's licence files;
4. starts QEMU once from a copy of `boot.img`, never from `boot.img` itself, because a start writes to its disk (the firmware may repair the list of parts, and the kernel begins its notebook and counts the start). The machine is the boot disk's test machine (`DiskMachine` in `test-tools/boot_disk_checks.py`: the disk file alone, the network with no way out), and the start is judged as the start's own report judges it (`start_report` in `test-tools/boot_count.py`): the prompt reached, plain text only, no panic or fault, and the first question, `Kernel: hello!`. Then it checks that `boot.img` is unchanged;
5. packs the zip, writes `SHA256SUMS.txt`, and fills in the release's text as `release-notes.md`.

On any failure it stops, says why ("NOT MADE") and ends with 1. QEMU, its firmware and the work folder for the start come from the environment, as for the tests ([test-tools/README.md](../test-tools/README.md)).

Tried on a Windows computer with QEMU 11.1.0, on the code of `4353d34` with the notices added: the start from the copy reached the prompt in 35 lines with plain text only and the first question, and `boot.img` was unchanged; the zip was 3,281,121 bytes, with `boot.vdi` of 8,389,632 bytes, `boot.img` of 83,886,080, `NOTICES.txt` of 784,605 and `COPYRIGHT-library.html` of 1,512,515; the release's text held the version and the seven checksums. Files made on a person's computer are for such a try only, never for a release.

## The release workflow

`.github/workflows/release.yml` makes a release on one of GitHub's Windows computers. It runs only when started by hand, with "Run workflow" on GitHub or `gh workflow run release.yml`, and only from `master`:

- It stops unless the boot tests' run after the commit landed on `master` passed on that very commit ("Boot tests on GitHub" in [testing.md](testing.md)). Runs on `master` wait one at a time, and of several waiting only the newest runs, so a commit that landed close before another may have no run: the release then waits for a commit that has one.
- It stops if a release or a draft of that version is there already: the listing of releases names drafts too (`isDraft`), for those who may push. It never replaces an earlier draft; to make a draft again after a fix, a person deletes the old one on GitHub first.
- The shared steps, `.github/actions/release-files/action.yml`: QEMU from the same installer as the boot tests, checked against its SHA-512 and taken from GitHub's cache when the boot tests keep it there; Rust 1.100.0, the smallest set of components, which has Rust's notices; then `release/make_release.py`.
- Then `gh release create` makes a draft: tag `v<version>` on the commit built, marked as a pre-release, with the release's text, the zip and `SHA256SUMS.txt`. A draft is seen only by those who may push to the repository ("Only users with push access will receive listings for draft releases", GitHub's REST documentation). Publishing it is a person's step.
- Last, it says whether the tag is there yet: GitHub's documentation, as read, does not say whether making a draft makes its tag. For 0.1.0 it did not: the tag came when the draft was published ("The first release", below).

This job may write the repository's contents, which is what making a release needs ("contents: write allows the action to create a release", GitHub's workflow syntax), and read the results of other workflows. Every other job of the project's workflows may only read. A release's commit must be on `master` anyway: GitHub refuses a release whose commit changes `.github/workflows/` against the default branch to the token a workflow has.

On a pull request that changes `release.yml`, the shared steps or `release/`, a dry run makes and checks the same files and shows them, their sizes, the checksums and the start of the text in its log. It uploads nothing, and it may only read the repository.

- The clean export of `a8425d4`, the change that brought the notices in, passed: 695 files, none built or private, 689 the same as the working files and six, the new ones, in line ends only; both builds from nothing without warnings or a helper program, and no block; the interpreter byte for byte the one tested, and inside the kernel; the kernel to the prompt in 35 lines, with "Free memory" 197 MB.
- So did the clean export of `b042f03`, the change that brought the release workflow in: 699 files, none built or private, 689 the same as the working files and ten, the new ones, in line ends only; both builds from nothing without warnings or a helper program, and no block; the interpreter byte for byte the one tested, and inside the kernel; the kernel to the prompt in 35 lines, with "Free memory" 197 MB.

## The first release

Version 0.1.0, "boos 0.1.0 (early test)", made from `master` at `8b6102a` and published on 2026-11-21 as a pre-release:

- The dry run on the pull request that brought the workflow in, merged with `master` at `4353d34`, passed in 2 minutes 22 seconds: QEMU's installer came from GitHub's cache and matched its SHA-512, and the files were made and checked as above, the start from a copy reaching the first question in 35 lines. `NOTICES.txt`, `COPYRIGHT-library.html` and the two licence files it made were byte for byte the ones made from the same code on a person's computer: nothing of the computer that makes them goes into them.
- The release run, started by hand on `master` at `8b6102a`, took 2 minutes 51 seconds. It found the boot tests' passed run after that commit had landed, made the files as in the dry run (the zip 3,305,380 bytes), and made the draft with the zip and `SHA256SUMS.txt`.
- Making this draft made no tag: the run's last step said so, and GitHub's list of tags had none.
- Before it was published, a person reported that the disk from the draft, started in VirtualBox 7.2.22 with the release text's steps, reached its first question; nothing of it was watched here.
- When the draft was published, GitHub made the tag `v0.1.0` on `8b6102a`. Making the tag started no workflow: each of them runs only for `master` and for pull requests.
- Without signing in, GitHub's API showed the release and its two files; GitHub's own SHA-256 of the zip was the one in `SHA256SUMS.txt`, and the zip's download link answered with its full size (its headers only were asked for; nothing was downloaded). GitHub's "latest release" stayed empty, since a pre-release is never the latest.
