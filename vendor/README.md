# Copies of outside code

This folder holds copies of seven crates that were not written for this kernel. Everything else in the repository was.

| Folder | Crate and version | Taken from | Licence | Licence file |
| --- | --- | --- | --- | --- |
| `smoltcp/` | smoltcp 0.14.0, a network stack | crates.io | 0BSD | `smoltcp/LICENSE-0BSD.txt` |
| `heapless/` | heapless 0.9.3, lists of fixed size, needed by smoltcp | crates.io | MIT or Apache-2.0 | `heapless/LICENSE-MIT`, `heapless/LICENSE-APACHE` |
| `rustls/` | rustls 0.23.46, a library that speaks TLS | crates.io | Apache-2.0, ISC or MIT | `rustls/LICENSE-APACHE`, `rustls/LICENSE-ISC`, `rustls/LICENSE-MIT` |
| `rustls-webpki/` | rustls-webpki 0.103.17, which checks certificates, needed by rustls | crates.io | ISC | `rustls-webpki/LICENSE` |
| `num-traits/` | num-traits 0.2.19, helpers for numbers, needed by the encryption arithmetic | crates.io | MIT or Apache-2.0 | `num-traits/LICENSE-MIT`, `num-traits/LICENSE-APACHE` |
| `wasmparser/` | wasmparser 0.239.0, which reads and checks WebAssembly programs, needed by wasmi | crates.io; the licence texts from the project's repository | Apache-2.0 with LLVM exception, Apache-2.0 or MIT | `wasmparser/LICENSE-Apache-2.0_WITH_LLVM-exception`, `wasmparser/LICENSE-APACHE`, `wasmparser/LICENSE-MIT` |
| `libm/` | libm 0.2.16, arithmetic for numbers with a point, needed by wasmi | crates.io | MIT | `libm/LICENSE.txt` |

`Cargo.toml` in the project root points cargo at these copies with `[patch.crates-io]`.

## Why copies

Six of the seven come with a build script: a small program that cargo compiles and runs on the building computer before it compiles the crate. A program compiled a moment ago is unsigned and unknown, and a computer that only runs recognised programs (Windows with Smart App Control switched on) refuses to run it. The build then fails with "An Application Control policy has blocked this file".

The copies have their build scripts taken out, so building the kernel runs no program that was compiled along the way.

The seventh, rustls-webpki, has no build script. It is a copy because of one line in its settings that made cargo list and fetch about twenty crates this kernel never uses; see edit 6.

## What was changed

Each copy holds the crate's `src` folder, `Cargo.toml`, `README.md` and licence files as published. Left out: examples, tests, benchmarks and the files of the crates' own development. Twelve edits were made:

1. **`smoltcp/Cargo.toml` and `heapless/Cargo.toml`:** `build = "build.rs"` became `build = false`, and `build.rs` was left out.
2. **`smoltcp/src/lib.rs`:** the line `include!(concat!(env!("OUT_DIR"), "/config.rs"));` became `include!("config.rs");`. The file `smoltcp/src/config.rs` was added. It is exactly what smoltcp's build script writes with its default settings: 16 lines of limits.
3. **`heapless/Cargo.toml`:** a `[lints.rust.unexpected_cfgs]` section was added, naming `arm_llsc` and `has_atomic_load_store`. Its build script used to announce these two names to the compiler. It only ever switched them on for ARM processors, so on a PC leaving them off changes nothing.
4. **`smoltcp/Cargo.toml`:** the line `"defmt?/alloc",` was taken out of the `alloc` feature. With it, cargo fetches nine crates of a logging system that this kernel never uses.
5. **`rustls/Cargo.toml`:** `build = "build.rs"` became `build = false`, and `build.rs` was left out. That script only switched something on for the nightly version of Rust, which this kernel does not use.
6. **`rustls-webpki/Cargo.toml`:** the line `"ring?/alloc",` was taken out of the `alloc` feature. With it, cargo lists and fetches `ring`, a crate with C code inside, and what `ring` needs, among them the large crates for Windows programs. None of that is used here.
7. **`num-traits/Cargo.toml`:** `build = "build.rs"` became `build = false`, `build.rs` was left out, and the section `[build-dependencies.autocfg]` went with it. A section `[lints.rust]` with `deprecated = "allow"` was added: the crate uses old names that newer Rust warns about, and as a copy it would print about 350 such warnings in every build.
8. **`num-traits/src/float.rs`:** the build script asked the compiler whether a function that Rust has had since version 1.62 exists. It does, so the answer is written into the source: `#[cfg(has_total_cmp)]` became `#[cfg(all())]`, which is always true, and `#[cfg(not(has_total_cmp))]` became `#[cfg(any())]`, which is always false.
9. **`wasmparser/Cargo.toml` and `libm/Cargo.toml`:** `build = "build.rs"` became `build = false`, and `build.rs` was left out (with `configure.rs`, a part of libm's script).
10. **`wasmparser/src/binary_reader.rs`:** its build script ran the compiler to ask for its version, and switched `core_error` on for Rust 1.81 or newer. This kernel is built with a newer Rust, so the answer is written into the source: in the one line that uses it, `core_error` became `all()`, which is always true.
11. **`libm/Cargo.toml`:** seven names were added to the list of switches the compiler should know: `assert_no_panic`, `intrinsics_enabled`, `arch_enabled`, `optimizations_enabled`, `x86_no_sse`, `f16_enabled`, `f128_enabled`. The build script used to announce them. None is switched on: the script switched them on for features this kernel does not ask for, for optimized builds, or for other processors. If the kernel is ever built optimized, look at `optimizations_enabled` again.
12. **`libm/Cargo.toml` and `wasmparser/Cargo.toml`:** one kind of warning is allowed in each (`unstable_name_collisions` in libm, `unused_imports` in wasmparser). As copies the two would otherwise print 33 warnings in every build.

The crate file of wasmparser 0.239.0 holds no licence text. The three licence files in its folder were taken from its project's repository (bytecodealliance/wasm-tools), at the commit the crate file names as its origin.

Every other file is byte for byte what crates.io serves. That was checked by comparing each file with the downloaded crate, after checking the downloaded crate against the checksum in cargo's own list. For the three copies for encryption: 165 of 169 files are identical and four were edited. For the two for running apps: 206 of 212 are identical, three were edited and three are the added licence texts.

## What follows from the changes

- **smoltcp's limits are fixed in `smoltcp/src/config.rs`.** Its documentation describes changing them with features such as `iface-max-addr-count-3` or with environment variables. Neither works here. To change a limit, edit that file.
- **The copies do not update by themselves.** To move to a newer version: download the new crate, copy the same files, and redo the edits. Check that the new version's build script still does no more than the old one did; if it does more, that work has to be replaced by hand.
- **Security fixes do not arrive by themselves either.** rustls and rustls-webpki had several in 2026. When one is announced for a copy, the copy has to be renewed by hand.
- **wasmparser's version belongs to wasmi's.** wasmi 1.1.0 asks for wasmparser 0.239, and a newer wasmparser is not picked up by it. wasmi itself is held at 1.1.0; [docs/box.md](../docs/box.md) says why.
- **Other crates are still fetched from crates.io** the first time the kernel is built. None of them has a build script, and none is a macro crate.
  - Six that smoltcp and heapless need: `bitflags`, `byteorder`, `cfg-if`, `hash32`, `managed`, `stable_deref_trait`.
  - 49 for encryption, and three more that cargo lists and downloads but never compiles. [docs/encryption.md](../docs/encryption.md) has the details.
  - Six for running apps: `wasmi`, `wasmi_core`, `wasmi_ir`, `wasmi_collections`, `spin`, and a second, newer version of `bitflags`. [docs/box.md](../docs/box.md) has the details.
