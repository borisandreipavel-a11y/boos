# A release of the boot disk

A release puts a ready boot disk (see "The boot disk" in [disk.md](disk.md)) where people can download it and start boos without building it. The disk in a release is built by GitHub from the public code of the repository, never taken from anyone's own runs: a disk that has been used holds the person's name and their locked key, and files built on a person's computer carry that computer's folder names.

## The notices that go with it

A built disk holds code of other projects besides the project's own: the outside crates built into the kernel, the ones built into the interpreter for Lua that the kernel carries, and Rust's own standard library. Their licences ask for some of their texts to go with every copy, built copies included. So a release carries two files of notices:

- `NOTICES.txt`: for every outside crate, its name, version and licence, where it came from, and its own licence, notice and copyright files, word for word.
- `COPYRIGHT-library.html`: Rust's notices for its standard library, as the Rust project publishes them with the Rust the disk was built with (in the component `rust-docs`). It says that the standard library may be used under MIT or Apache-2.0, gives the notices of what is in it (tables from Unicode, parts taken from LLVM and from musl), and holds every licence text it names.

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

The script makes nothing, says why and ends with 1, if a crate has no licence text and none is kept for it, if a crate now comes from another commit than its kept texts (take them again then), if kept texts are missing, or if Rust's notices are missing (add the component `rust-docs`).

Checked on the code of `4353d34`: 76 outside crates, 68 in the kernel and 8 in the interpreter, with 150 files, the kept texts used for the twelve; `NOTICES.txt` of 784,605 bytes, and Rust's notices of Rust 1.100.0, 1,512,515 bytes. Each of the four refusals was tried by changing the script's lists in memory, no file touched: each stopped, said why and wrote nothing.
