# Copies of outside code

This folder holds copies of two crates that were not written for this kernel. Everything else in the repository was.

| Folder | Crate and version | Taken from | Licence | Licence file |
| --- | --- | --- | --- | --- |
| `smoltcp/` | smoltcp 0.14.0, a network stack | crates.io | 0BSD | `smoltcp/LICENSE-0BSD.txt` |
| `heapless/` | heapless 0.9.3, lists of fixed size, needed by smoltcp | crates.io | MIT or Apache-2.0 | `heapless/LICENSE-MIT`, `heapless/LICENSE-APACHE` |

`Cargo.toml` in the project root points cargo at these copies with `[patch.crates-io]`.

## Why copies

Both crates come with a build script: a small program that cargo compiles and runs on the building computer before it compiles the crate. A program compiled a moment ago is unsigned and unknown, and a computer that only runs recognised programs (Windows with Smart App Control switched on) refuses to run it. The build then fails with "An Application Control policy has blocked this file".

The copies have their build scripts taken out, so building the kernel runs no program that was compiled along the way.

## What was changed

Each copy holds the crate's `src` folder, `Cargo.toml`, `README.md` and licence files as published. Left out: examples, tests, benchmarks and the files of the crates' own development. Four edits were made:

1. **Both `Cargo.toml` files:** `build = "build.rs"` became `build = false`, and `build.rs` was left out.
2. **`smoltcp/src/lib.rs`:** the line `include!(concat!(env!("OUT_DIR"), "/config.rs"));` became `include!("config.rs");`. The file `smoltcp/src/config.rs` was added. It is exactly what smoltcp's build script writes with its default settings: 16 lines of limits.
3. **`heapless/Cargo.toml`:** a `[lints.rust.unexpected_cfgs]` section was added, naming `arm_llsc` and `has_atomic_load_store`. Its build script used to announce these two names to the compiler. It only ever switched them on for ARM processors, so on a PC leaving them off changes nothing.
4. **`smoltcp/Cargo.toml`:** the line `"defmt?/alloc",` was taken out of the `alloc` feature. With it, cargo fetches nine crates of a logging system that this kernel never uses.

Every other file is byte for byte what crates.io serves. That was checked by comparing each file with the downloaded crate.

## What follows from the changes

- **smoltcp's limits are fixed in `smoltcp/src/config.rs`.** Its documentation describes changing them with features such as `iface-max-addr-count-3` or with environment variables. Neither works here. To change a limit, edit that file.
- **The copies do not update by themselves.** To move to a newer version: download the new crate, copy the same files, and redo the four edits. Check that the new version's build script still does no more than the old one did; if it does more, that work has to be replaced by hand.
- Six small crates that smoltcp and heapless need are still fetched from crates.io the first time the kernel is built: `bitflags`, `byteorder`, `cfg-if`, `hash32`, `managed`, `stable_deref_trait`. None of them has a build script.
