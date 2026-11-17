# Random numbers and the date

Code: `src/random.rs`, `src/clock.rs`, and `processor_ask` in `src/processor.rs`.

Encryption needs two things from the machine: numbers that nobody can guess, and today's date. The kernel can get both and prints them at startup. The encrypted link uses both; see [encryption.md](encryption.md).

## Random numbers

- A random number here means one that nobody can guess, not even somebody who has seen every number before it. A program cannot work such numbers out: whatever it computes, somebody else can compute too. They have to come from something unpredictable in the machine.
- The kernel takes them from the processor. Processors of roughly the last ten years have an instruction, RDRAND, that hands out a random number gathered from noise in the processor's own circuits.
- `processor_ask(question)` in `processor.rs` asks the processor about itself (the instruction CPUID). A question is a number, and the answer is four numbers. Bit 30 of the third number in the answer to question 1 says whether the processor has RDRAND. Using the instruction on a processor without it is a failure ("invalid instruction"), so the question comes first.
  - The second number of an answer arrives in the register `rbx`, which Rust keeps for its own use. `processor_ask` sets the register's content aside before the question and swaps it back after.
- `random_setup()` asks that question and then draws five numbers. Each must arrive, and they must not all be the same: a broken source hands out one number again and again. Only then is `RANDOM_FOUND` set.
- `random_number()` gives one number of 64 bits, or nothing.
  - The processor says through its carry flag, one of its yes-or-no marks, whether it had a number ready. If not, the kernel asks again, up to ten times (`TRIES`), which is what the processors' makers advise.
  - **It never falls back on something weaker.** Without a source there is no number. `time_stamp()` differs from boot to boot, but it can be guessed and must not stand in.
- `efi_main` prints `Random numbers: made by the processor, for example 6f3630af83499c29`. The number is written with 16 signs, the digits and the letters a to f (base 16, where each sign stands for four bits). It is a sample and is used for nothing else. Without a sound source the line is `Random numbers: none, because this processor has no sound source for them`, and the kernel carries on.
- `random_fill(bytes)` fills a piece of memory with random bytes, eight per number, and says whether it could. The TLS library gets its random bytes this way.
- Whatever needs random numbers for encryption must refuse to work when there are none. The encrypted link does: it asks first, and makes no link without them.

In QEMU:

- QEMU's usual processor does not have the instruction. `run.bat` therefore asks for that processor plus the instruction: `-cpu qemu64,+rdrand`.
- `-cpu max`, every feature QEMU can play, has the instruction too. It was not chosen because it also offers page tables with five levels, which the kernel is not prepared for; see [open-points.md](open-points.md). In the boots tried, the firmware did not switch them on.
- There is no processor circuit behind the instruction in QEMU. By QEMU's source code as its makers are developing it, read on 2026-11-17 (not the source of the installed version 11.1, which was not read), QEMU fills each number from its own routine for cryptographic random bytes (`qemu_guest_getrandom`, which calls `qcrypto_random_bytes`), unless QEMU is started with a fixed `-seed`. How good those numbers are was not examined here.
- With the option, the firmware keeps more memory for itself; see "Free memory" in [memory.md](memory.md).

## The date and the time

- A PC has a clock chip (RTC) that keeps the date and the time, running on a small battery while the machine is off. `clock.rs` reads it.
- The chip keeps a row of numbered values. One is read in two steps: write its number to port `0x70`, then read the value at port `0x71` (`chip_value`). The two steps belong together, so device signals are off around them.
  - The numbers: 0 the second, 2 the minute, 4 the hour, 7 the day, 8 the month, 9 the last two digits of the year, `0x32` the first two (the century), `0x0A` the busy mark in bit 7, `0x0B` the form of the values.
  - Bit 7 of what is written to port `0x70` is a switch of its own, for a kind of signal that cannot be held back otherwise. Every number the kernel writes there has that bit clear, which is the normal state.
- **Reading safely.** Once a second the chip moves its values on, and a reading taken across that moment can mix old values with new ones: 10:59:59 and 11:00:00 could come out as 10:00:00.
  - `chip_read_once` waits while the chip's busy mark is set, for at most 100,000 looks (`BUSY_LOOKS`), and then reads all values.
  - `chip_read` reads until two readings in a row agree, at most ten times more (`READINGS`).
- **Turning the values into a date** is `date_from`. Chips write their values in one of two ways and count the hours in one of two ways. The form value says which.
  - Bit 2 set: every value is a plain number. Not set: every value is two decimal digits, one in each half of the byte, so `0x26` means 26 (BCD).
  - Bit 1 set: the hours run from 0 to 23. Not set: they run from 1 to 12 and bit 7 of the hour marks the afternoon. 12 at night becomes hour 0, and 12 at noon stays 12.
  - The century is believed only if it is 19, 20 or 21. Any other value in that place is not a century, and the year is then taken to be in the 2000s.
  - A month outside 1 to 12, a day outside 1 to 31, an hour above 23, a minute or second above 59, or a half byte that is no digit gives no date at all.
- `clock_read()` gives a `Date` (year, month, day, hour, minute, second) or nothing. `efi_main` prints `Date and time: 2026-11-17 05:37:53, by this machine's clock`, or `Date and time: unknown, because the clock chip gave no usable answer`.
- **Which time it is.** The chip does not say whether it holds local time or world time (UTC), and the kernel cannot tell. QEMU sets its chip to world time, so the printed time differs from the clock on the wall by the time zone. PCs that run Windows usually keep local time in the chip. Certificates are dated in world time.
- `seconds_since_1970(date)` gives the same moment as one number, the seconds since the start of 1970, which is how certificates are dated. It counts the leap days by the rule of the calendar: every fourth year, but not the hundreds, but again every fourth hundred. A date before 1970 gives nothing.
- The chip is read each time the date is asked for. The kernel keeps no date of its own.

In QEMU:

- QEMU's chip writes digits and counts 24 hours (form `0x02`). It changes its form when the form value is written, which the tests use.
- `-rtc base=localtime` sets the chip to the host's local time, and `-rtc base=2000-02-29T23:59:58` starts it at a chosen moment.
- QEMU's chip goes from 1999 to 2000 with the century value changing from 19 to 20. After 2099 it says 2000 again. The kernel shows what the chip says.
