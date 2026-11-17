# Encryption

Code: `src/encryption.rs`, `src/encryption_values.rs`, `sse_refuse` in `src/processor.rs`, the settings in `.cargo/config.toml`, and the copies in `vendor/`.

The kernel does not encrypt anything yet. What is there: the outside code that will do it, built into the kernel, and a check at startup that this code computes correctly on the machine. No connection is made with it so far.

## The words

- **TLS** is the set of rules that turns a plain connection into an encrypted one. It is the "s" in `https`.
- A **certificate** is a signed statement by which a site proves that it is that site.
- A **root** is one of the organisations whose signatures count. A certificate is believed if a chain of signatures leads from it back to a root.
- A **provider** is the part that does the arithmetic of encryption for a TLS library.

## The outside code

None of it was written for this kernel. `Cargo.toml` names nine crates:

- **`rustls` 0.23.46** speaks TLS: who says what, in which order, and when the certificate is checked. It contains no arithmetic. It has a slot for a provider, and its two ready-made providers are partly written in C, which cannot be built here. The kernel will carry a provider of its own: an adapter between rustls and the arithmetic crates below. That adapter is not written yet.
- **`rustls-webpki` 0.103.17** comes with rustls. It checks a certificate: the chain to a root, the site's name, and the dates.
- **`webpki-roots` 1.0.12** is the list of roots that the Firefox browser trusts, as data: 112 of them.
- **The arithmetic:** `sha2` and `hmac` (fingerprints), `chacha20poly1305` and `aes-gcm` (scrambling), `p256` and `p384` (agreeing on a key, and signatures on two curves), `rsa` (signatures of the RSA sort).

What cargo makes of that:

- `Cargo.lock` lists 62 crates for encryption. 52 are compiled: three from copies in `vendor/` and 49 fetched from crates.io.
- Ten are listed and never compiled: `fiat-crypto`, `libc`, `proc-macro2`, `quote`, `serde`, `serde_core`, `serde_derive`, `serdect`, `syn`, `unicode-ident`. A crate that only mentions another as an option can still make cargo list it. Three of the ten are also downloaded on a first build (`serde`, `serde_core`, `serdect`, 0.17 MB). Cutting them would take edited copies of more crates.
- None of the 52 has a build script or is a macro crate. That was checked from each crate's own files before the first build.
- [vendor/README.md](../vendor/README.md) says which three are copies and what was changed in them.

Why this library, from the comparison made on 2026-11-17:

- rustls was the only candidate where every need had a visible answer: checking the whole chain without C code, taking the time from the kernel, and a list of roots without a build script.
- `embedded-tls` 0.19.0 was not taken: its full certificate check is documented as working only with an operating system, and its other one accepts only a certificate signed directly by the trusted one.
- `purecrypto` 0.10.6 is a single crate with no dependencies, but all its encryption code was six months old, from one publisher, and by its own words without an outside audit.
- `rustls-rustcrypto`, a ready-made provider on the same arithmetic crates, says not to use it in production and needs an operating system.

How fresh the code is:

- The projects are five to ten years old. The versions are recent: the arithmetic crates' current line came out between June and November 2026.
- Nineteen security advisories for these crates were read on 2026-11-17 at rustsec.org. In each one the version used here is at or past the fix. Read them again whenever a version is changed.

## The five settings

The arithmetic crates each hold two versions of their code: a fast one for processors with special instructions, and a plain one that runs anywhere. This kernel must use the plain one, for two reasons:

- the fast code works with the processor's SSE registers, which the kernel does not save when it switches tasks;
- the compiler cannot build the fast code for this target at all. It stops with `rustc-LLVM ERROR: Do not know how to split the result of this operator!`.

`.cargo/config.toml` therefore passes five settings to the compiler, one per crate that has fast code:

```
--cfg sha2_backend="soft"
--cfg chacha20_backend="soft"
--cfg aes_backend="soft"
--cfg poly1305_backend="soft"
--cfg polyval_backend="soft"
```

- Each of the five was left out on its own once, and the build stopped every time: inside `sha2`, `poly1305` and `polyval` themselves, and inside the kernel's own crate for `chacha20` and `aes`.
- A new arithmetic crate may need a setting of its own. Look in its `Cargo.toml` for a line like `cfg(..._backend, values("soft"))`; two of the five are named there and not on the crates' documentation pages.
- Changing these settings makes cargo build everything again.

## The processor refuses SSE instructions

- Processors have a second set of registers, made for arithmetic on many numbers at once (SSE). The build target does not use them, and neither the task switch nor the signal stubs save them; see [interrupts.md](interrupts.md) and [tasks.md](tasks.md).
- `sse_refuse()` in `processor.rs` sets bit 3 of the control register `cr0`. From then on any instruction that touches those registers is a failure, reported as `CPU fault: device not available at 0x...`.
- The point: code that used those registers would spoil another task's numbers without any sign. Now it stops the kernel with a report instead.
- It is called right after the interrupt table is loaded, so the report can be printed. It must not come before the takeover: the firmware uses those registers.
- The switch is not part of what a task switch changes, so it holds in every task.
- If SSE is ever wanted, the registers must first be saved per task and in the stubs. Then this call goes.

## The check at startup

`encryption_check()` tries each kind of operation once and compares the result with a value worked out by something other than the code under check. The values are in `encryption_values.rs`.

| Check | What is compared | Where the value comes from |
| --- | --- | --- |
| Fingerprint | SHA-256 of "abc" | another program's SHA-256, outside the kernel |
| Keyed fingerprint | HMAC-SHA256, a published example | the same |
| ChaCha20-Poly1305 | the example of the document that defines it (RFC 8439) | that document |
| AES-GCM | the example with a key, number and text of zeros | the document that defines it |
| Agreeing on a key | the secret both sides reach on the curve P-256 | a calculation with whole numbers, from two test numbers |
| Signature, curve P-256 | a true signature accepted, a changed message refused | Windows' own encryption code |
| Signature, curve P-384 | the same | the same |
| RSA signature, both forms | the same, with a key of 2048 bits | the same |

- The two scrambling checks also unscramble the text again, and see that a text with one changed byte is refused.
- The signatures were made with keys that were thrown away at once. Only their public halves are in the file. The two numbers of the key-agreement check are test numbers, the bytes 1 to 32 and 33 to 64, and no secrets.
- `efi_main` prints `Encryption: 8 of 8 checks of the arithmetic are right, and 112 trusted roots are on board`. If a check fails the line is `Encryption: not to be trusted here, only N of 8 checks of the arithmetic are right`, and the kernel carries on.
- Code that encrypts must refuse to work when the check failed. No such code exists yet, so nothing reads the result today.
- `trusted_roots()` puts the list of roots into the form rustls wants and counts it.
- The check takes about half a second in QEMU and goes 45,696 bytes deep on the stack. At startup the kernel runs on the firmware's stack, which has 124 KB free at that point; see [memory.md](memory.md).
- **What the check does not show:** that the code is safe against an attacker. It shows that the arithmetic comes out right on this machine, for one example of each kind.

To make the Windows values again: sign the message in the file with a new key on each curve (`ECDsa.SignData`) and with a new RSA key of 2048 bits in both forms (`RSACng.SignData`), and write out the public halves and the signatures.

## Not there yet

- The provider, and with it any connection. rustls and the certificate checker are compiled into the kernel, but none of their own code runs except the counting of the roots.
- The date as a count of seconds since 1970, which rustls wants, and random bytes in bulk; see [random-and-date.md](random-and-date.md).
- More stack for the task that will make connections; see [open-points.md](open-points.md).
