# Encryption

Code: `src/tls.rs`, `src/provider.rs`, `src/encryption.rs`, `src/encryption_values.rs`, `sse_refuse` in `src/processor.rs`, the settings in `.cargo/config.toml`, and the copies in `vendor/`.

The kernel fetches its page over an encrypted link. The site proves who it is with a certificate, which the kernel checks, and after that everything on the connection is scrambled. Three layers do it: rustls speaks TLS, the provider in `provider.rs` hands rustls the arithmetic, and `tls.rs` carries rustls's bytes over a connection. At startup a check sees that the arithmetic computes correctly on the machine.

## The words

- **TLS** is the set of rules that turns a plain connection into an encrypted one. It is the "s" in `https`.
- A **certificate** is a signed statement by which a site proves that it is that site.
- A **root** is one of the organisations whose signatures count. A certificate is believed if a chain of signatures leads from it back to a root.
- A **provider** is the part that does the arithmetic of encryption for a TLS library.
- The **greeting** (handshake) is the start of a link: both sides agree on keys, and the site shows its certificate and proves that it holds the key that goes with it.

## The outside code

None of it was written for this kernel. `Cargo.toml` names ten crates:

- **`rustls` 0.23.46** speaks TLS: who says what, in which order, and when the certificate is checked. It contains no arithmetic. It has a slot for a provider, and its two ready-made providers are partly written in C, which cannot be built here.
- **`rustls-webpki` 0.103.17** comes with rustls. It checks a certificate: the chain to a root, the site's name, and the dates.
- **`webpki-roots` 1.0.12** is the list of roots that the Firefox browser trusts, as data: 112 of them.
- **The arithmetic:** `sha2` and `hmac` (fingerprints), `chacha20poly1305` and `aes-gcm` (scrambling), `p256` and `p384` (agreeing on a key, and signatures on two curves), `rsa` (signatures of the RSA sort).
- **`der`** reads the fixed form in which certificates write numbers. The arithmetic crates use it already; the provider uses it directly, so it has a line of its own.

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
- The result is kept. `encryption_sound()` gives it, and the encrypted link asks it first: after a failed check no link is made.
- `root_list()` puts the list of roots into the form rustls wants, and `trusted_roots()` counts it.
- The check takes 0.2 to 0.3 seconds in QEMU and goes 41,544 bytes deep on the stack. Before the outside crates were built optimized (see [README.md](README.md)) it took half a second or more and went 45,696 deep. At startup the kernel runs on the firmware's stack, which has 124 KB free at that point; see [memory.md](memory.md).
- **What the check does not show:** that the code is safe against an attacker. It shows that the arithmetic comes out right on this machine, for one example of each kind.

To make the Windows values again: sign the message in the file with a new key on each curve (`ECDsa.SignData`) and with a new RSA key of 2048 bits in both forms (`RSACng.SignData`), and write out the public halves and the signatures.

## The provider

`provider()` in `provider.rs` gives rustls everything it needs from outside. Each piece is an adapter: it takes what rustls asks for in rustls's form and calls an arithmetic crate.

- **Fingerprints.** `Fingerprint` is SHA-256, for a whole piece of data or fed bit by bit. `KeyedFingerprint` is HMAC-SHA256. rustls builds the making of a link's keys out of the second one (`HkdfUsingHmac`).
- **Scrambling.** Two ways are offered, ChaCha20-Poly1305 first and AES-GCM with a 128-bit key second. Every site that speaks TLS 1.3 has to know the second. `Scrambling<C>` is written once for both; the `C` stands for the outside type that does the work.
  - Each piece that is scrambled gets a number that counts up, so no two pieces are scrambled alike, and ends in 16 bytes of proof. On the way in, the proof is checked before anything is unscrambled, and a piece that was changed is refused.
- **Agreeing on a key.** One way: the curve P-256 (`P256Agreement`). The kernel makes a number of its own from 32 random bytes and shows the site a point made from it. A point from the site that does not lie on the curve is refused.
- **Checking signatures.** This is where a certificate is believed or not. rustls's certificate checker walks the chain and asks, for each signature, the piece whose two labels match the certificate: the sort of key and the sort of signature. There are ten pieces:
  - on a curve: P-256 and P-384, each with a SHA-256 or a SHA-384 fingerprint (`CurveSignature`);
  - RSA in its older form (PKCS#1 v1.5) and its newer one (PSS), each with SHA-256, SHA-384 or SHA-512 (`RsaSignature`).
  - Certificates write a signature on a curve, and the public half of an RSA key, as a pair of numbers in a fixed form (DER). `two_numbers` takes the pair apart with the `der` crate and refuses anything else, bytes behind the pair included. `widened` refuses a number that is too long for its curve.
  - An RSA key shorter than 2048 bits or longer than 8192 is refused, whatever its signature says.
- **Random numbers.** `KernelRandom` passes rustls's requests to `random_fill`. Without a source rustls gets a "no" and no link is made.
- **A key of the kernel's own.** There is none (`NoOwnKey`), so the kernel cannot prove to a site who it is.

## The encrypted link

`tls.rs` drives rustls. rustls sends and receives nothing itself: it is handed the bytes that arrived, and hands back bytes to send.

- **`Wire`** is what `tls.rs` needs from whoever owns the connection: `send` all of these bytes, and `receive` some, where 0 means the other side ended the connection. `page.rs` offers it over the network stack's connection (`ConnectionWire`), waiting with `stack_turn` where it has to.
- **`secure_ready()`** says whether this machine can encrypt at all. Three things must hold: the startup check came out right, the processor makes random numbers, and the clock chip gives a date. `page_fetch` asks before it sends anything, so a machine that cannot encrypt sends nothing, not even the site's name.
- **`link_settings()`** sets up rustls: the provider, the time from the clock chip (`KernelClock`, seconds since 1970), TLS 1.3 only, the list of roots, no key of its own, and nothing kept from one link for the next.
- **`secure_exchange(name, request, wire, taker)`** does one exchange. It is a loop: rustls works through what has arrived and says what it needs next.

| rustls says | What `secure_exchange` does |
| --- | --- |
| a piece of the greeting is ready | writes it into the outgoing room, which grows if it has to |
| send what is written | sends it over the wire |
| the greeting needs more bytes | receives more; the connection ending here is an error |
| data may be sent | sends the request once, then receives more of the answer; after the site's goodbye, says goodbye too and stops |
| pieces of the answer arrived | hands each, unscrambled, to `taker` |
| the site said goodbye | remembers that the answer is whole |

- After each round the arrived bytes that rustls is done with are dropped. The room for arrived bytes is 17 KB, a little more than the largest piece a site may send.
- When the greeting is over the kernel prints `Network: example.com proved who it is: its certificate leads back to one of the 112 trusted roots. The link is encrypted with ChaCha20-Poly1305.`
- It answers "true" only if the site said through the link itself that it had sent everything. A connection that simply ends gives "false", and the page is then reported as not whole.
- `why` turns rustls's word for a failure into plain words. Where it has none of its own, rustls's word follows in brackets, cleaned like every text that may hold bytes from outside.

What the kernel refuses, each with a line `Network: no page fetched, because ...`:

| The reason printed | When |
| --- | --- |
| the site's certificate does not lead back to a trusted root | no chain of true signatures ends at one of the roots |
| a signature in the site's certificates is not true | a signature in the chain or in the greeting fails, or a key is too short |
| the site's certificate is made out to another name | the certificate is for a different site |
| the site's certificate has run out | its last day is before the kernel's date |
| the site's certificate is not valid yet, or this machine's date is wrong | its first day is after the kernel's date |
| the check of the encryption arithmetic at startup failed | the startup check found a wrong result |
| this machine cannot make random numbers, which encryption needs | the processor has no source for them |
| this machine has no usable date, which checking a certificate needs | the clock chip gave nothing usable |
| the site and this kernel have no way of encrypting in common | the site offers nothing the provider has |
| the site ended the connection in the middle of the greeting | the connection ended early |

What can still be read on the way:

- The site's name, twice: in the name question, and once in the greeting, where it tells the site which certificate to show.
- The addresses and sizes of the packets.
- Not the request and not the page. In a recording of a real fetch the words of the request appear nowhere.

How it goes in QEMU:

- A link took 100 KB of the network task's stack at most, with a chain that has RSA keys of up to 4096 bits, before the outside crates were built optimized. That is why a task's stack is 256 KB; see [tasks.md](tasks.md). Now a link takes 56 KB at most, with keys on a curve, and 38 KB with RSA keys.
- A fetch from the test server took 1.3 to 1.5 seconds, nearly all of it arithmetic. The rest count at startup falls from 397 to between 336 and 365 of 400 ticks because of it.
- Three fetches in a row used no more stack and no more frames than one.

## Limits

- **TLS 1.3 only.** A site that speaks only the older TLS 1.2 is refused.
- **One curve for agreeing on a key**, P-256. A site that insists on another is refused.
- **No look at whether a certificate was withdrawn.** A certificate that its issuer has called back before its last day is still believed.
- **The date is the clock chip's.** A clock that is wrong by years refuses every site; a clock set to local time is hours off, which matters only on a certificate's first or last day.
- **Nothing is kept between links.** Every link makes the full greeting.
- **The roots are fixed when the kernel is built.**
- **Two things use the link,** the page fetch and the question to the model (see [model.md](model.md)), both inside the network stack's own task.
