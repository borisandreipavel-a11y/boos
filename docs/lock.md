# The lock: a secret locked with a password

Code: `src/lock.rs`, `src/lock_values.rs`, the crate in the folder `password-key/`, and the check's line in `efi_main`.

The lock takes a secret, such as a text of up to 200 signs, and a password, and scrambles the secret so that only someone who knows the password can read it back. The scrambled form can be kept where others might see it. The onboarding uses it to keep the model's key on the disk: `secret_lock` and `secret_unlock` in `secret.rs` call `lock` and `unlock` (see "The key and the password" in [chat.md](chat.md)).

## The words

- A **password** is a text the person at the machine chooses. A **key** here is 32 bytes that the scrambling uses. The key is made from the password, slowly on purpose.
- A **round** is one keyed fingerprint (HMAC-SHA256) of what the round before gave. The key is the end of many rounds, so that someone who guesses passwords has to go through all of them for every guess.
- The **salt** is 16 bytes drawn at random for every lock and kept with it. Two locks with the same password get different keys, so a guesser cannot work out keys for likely passwords ahead of time.
- The **number** is 12 bytes drawn at random for every lock. The scrambling needs a number that is never used twice with the same key.
- The **proof** is 16 bytes that the scrambling adds. With a wrong key, or after one changed byte, it does not fit, and nothing is unscrambled.

## Locking and unlocking

`lock(password, secret)` locks a secret:

1. It draws the salt and the number with `random_fill`. **Without random numbers nothing is locked:** a fixed salt or number would make locks alike, which helps someone who guesses.
2. It puts the head together (see the layout below) and the secret behind it, in a list that is as large as it will be from the start, so that it never moves and leaves a copy of the secret behind.
3. `password_key` makes the key from the password and the salt, in `LOCK_ROUNDS` rounds: 600,000.
4. ChaCha20-Poly1305 scrambles the secret where it lies, and the proof goes on the end. The proof covers the head too: a changed byte in the head is refused like a changed byte of the secret.
5. The key is wiped.

`unlock(password, locked, room)` unlocks into a room of 200 bytes and says how many signs the secret has. A locked secret is data that may come from outside the kernel, so it is checked before anything is done with it, in this order, and refused with a reason in words:

- shorter than a head and a proof (50 bytes): `it is too short to be a locked secret`;
- longer than a head, the longest secret and a proof (250 bytes): `it is too long to be a locked secret`;
- another version than 1: `the locked secret is of a version this kernel does not know`;
- another way of locking than 1: `the secret was locked in a way this kernel does not know`;
- 0 rounds, or more than 10,000,000 (`MOST_ROUNDS`): `the locked secret asks for a count of rounds this kernel does not take`. Without that bound a changed count could hold the kernel up for hours; ten million rounds are about 20 seconds in QEMU (8,388,611 rounds took about 17 seconds by the processor's counter).

Then the key is made with the salt and the count of rounds the head names, and the proof is checked before anything is unscrambled. If it does not fit: `the password is not the one it was locked with, or the locked secret was changed` (`NOT_UNLOCKED`, which the onboarding compares with to tell this refusal from the others). The two cannot be told apart. The room is wiped first, and again after a refusal.

## The layout of a locked secret

| Bytes | What |
| --- | --- |
| 1 | The version of this layout: 1 |
| 1 | The way it was locked: 1, a key by PBKDF2 with HMAC-SHA256, then ChaCha20-Poly1305 |
| 4 | The count of rounds, lowest byte first |
| 16 | The salt |
| 12 | The number |
| as long as the secret | The scrambled secret |
| 16 | The proof |

The first 34 bytes are the head. The count of rounds and the salt travel with the locked secret, so it can be unlocked on any machine, with the same work there.

## Turning a password into a key

`password_key(password, salt, rounds, key)` is PBKDF2 with HMAC-SHA256, as RFC 8018, section 5.2, writes it. The keyed fingerprint comes from the crates `hmac` and `sha2`, which the encryption already uses (see [encryption.md](encryption.md)). The rest is about 20 lines of this project's own: the first round fingerprints the salt and the block's number, every further round fingerprints the round before, and the key is all of the rounds' results laid over each other with exclusive or. A key of any length can be asked for, 32 bytes at a time; the lock asks for 32.

**600,000 rounds is the figure OWASP's advice on storing passwords names for PBKDF2 with HMAC-SHA256** (its Password Storage Cheat Sheet, read on 2026-11-19). The same page puts Argon2id first, a way that also makes every guess fill a large table of memory; that would have meant new outside code, and PBKDF2 needed none.

**Why a crate of its own.** The kernel's own code is built the plain way (see the end of `Cargo.toml`). Built plain, these rounds ran at about 35,000 a second in QEMU on the test computer: 600,000 rounds would take 17 seconds. The same lines in a crate of their own are built to run fast, like the outside crates, and ran at about 565,000 a second: 600,000 rounds in about 1.1 seconds. The function there is not generic, so the code of the keyed fingerprint it uses is compiled in that crate, built fast, and not in the kernel's.

- The crate is written for this kernel; it is not outside code. It is a path dependency of the kernel and has no `Cargo.lock` of its own: the kernel's lists it.
- It names the same two crates in the same versions as the kernel, so it brings no new outside crate.
- Cargo builds it like every crate that is not the kernel itself; that it was built at the faster setting was seen in cargo's command line.

## Wiping

- The key is wiped by `lock` and `unlock` as soon as the scrambling is done, and so are the last round's result and the running result inside `password_key`.
- The scrambler keeps its own copy of the key. `chacha20poly1305` is built with its `zeroize` feature, which writes zeros over that copy when the scrambler is thrown away. Without it, a dump of the machine's whole memory after a lock and an unlock held the key once; with it, the key was nowhere, and neither the password nor the secret either. That setting also covers the scramblers of the encrypted link (see [encryption.md](encryption.md)).
- **When the key for the model is locked or unlocked,** `secret_lock` and `secret_unlock` hand `lock` and `unlock` copies made in rooms of their own and wipe those rooms afterwards, and the rooms the password is typed into and kept in are wiped too (see "A secret" in [chat.md](chat.md)). A dump of the whole memory after locking, after unlocking, after a wrong password and after two passwords that differed held no password, the key made from it nowhere, and the model's key only once, in its room, while it was meant to be kept.
- **Not wiped:** the copies of the keyed fingerprint's state that every round makes on the stack. They are made from the password and can stand in for it: whoever has them can work out the key for any salt without knowing the password, and test guesses at the password quickly. The last of them stay on the stack until something else is written there. The memory search did not look for them. `hmac` and `sha2` have a feature that wipes such states when they are thrown away. It is not switched on: the password is meant to keep out somebody who uses the machine, not somebody who can read its memory, and the key itself lies in memory while the machine runs anyway.

## The check at startup

`lock_check()` runs right after the JSON check, at startup, with device signals off, and gives six checks:

1. A key from the password "passwd" and the salt "salt" in 1 round, 64 bytes: the value published in RFC 7914, section 11.
2. A key from "Password" and "NaCl" in 80,000 rounds, 64 bytes: the second published value there.
3. Locking a made-up secret with a made-up password, salt and number, in 1,000 rounds, gives exactly the bytes another implementation gave.
4. Unlocking those bytes gives the secret back.
5. A password that differs in one sign is refused.
6. One changed byte is refused, tried three times: in the salt, in the scrambled secret, and in the proof.

The check takes about a third of a second in QEMU on the test computer, nearly all of it the 160,000 rounds of the second value (two blocks of 80,000).

**`src/lock_values.rs` is made by a script, not by hand.** The first two values are the published ones, which Python's own PBKDF2 gives too. The locked secret was made by another implementation of the same steps: Python's own PBKDF2, and a ChaCha20-Poly1305 written in Python from RFC 8439 and checked against that document's example. Nothing in it comes from the kernel's code. The script is not in the repository; to make the file again, lock the same inputs with any other implementation of PBKDF2-HMAC-SHA256 and ChaCha20-Poly1305 and lay the result out as above.

## What a boot prints

One line, after the JSON line:

```
Lock: 6 of 6 checks of locking a secret with a password are right
```

If a check fails it reads `Lock: not to be trusted here, only N of 6 checks of locking a secret with a password are right`, and the kernel carries on.

## Limits

See [open-points.md](open-points.md). In short: a password protects only as well as it is hard to guess, and the onboarding takes passwords of 4 signs; the count of rounds is fixed when a secret is locked; locking and unlocking take about a second in QEMU and hold the main loop up meanwhile; and nothing is locked without random numbers.
