# Test tools

Scripts that build the kernel, boot it in QEMU without a window, type keys through QEMU's monitor, save
pictures of the screen and compare them dot by dot with the picture that is meant, read the notebook from
outside, and stand in for the model's provider on this computer. [../docs/testing.md](../docs/testing.md) says
what was verified with them and which traps they avoid.

They are written in Python 3 and need nothing but its standard library, QEMU, and OpenSSL (the one that comes
with Git does). They were written for Windows. Run them from this folder.

## Running them

```
python run_tests.py              only what the change needs: the files changed since master, committed or not
python run_tests.py all          everything: every suite once and every break on purpose, before a merge
python run_tests.py --list       what would run and why, without running it (works with `all` and the options)
```

Options: `--workers N` (test machines at once; by default as many as the free memory and commit take, at most 4
and at most one for each two processors), `--base REF` (compare with another branch than master), `--files
PATH...` (run what a change to those files needs), `--to-the-end` (breaks on purpose run to the end instead of
stopping at their first failure), `--only NAME...` (only the jobs whose names begin so), `--share I/N` (only the
I-th of N shares of the jobs it picked, dealt longest first by the table's seconds in the same way on every
computer, so that N computers together run each job once; the boot tests on GitHub use four), `--own-breaks` (of
the breaks on purpose, only the change's own: a break whose line in its list is new or changed, or whose first
failure or known miss in `suites.py` is new or changed; and, when anything runs, the first break of each list, so
that a change to what makes and judges breaks shows too. The boot tests on GitHub use it for a pull request, and
run every break after the merge).

**What to run before a push.** On the computer a change is made on, run only what the change adds or changes: its
own suites or scenarios, its own breaks on purpose, and what was sorted out by hand when `master` was taken in,
picked by name with `--only`, for example `python run_tests.py all --only "chat tools stream" "break tools: nodone"`.
Run each new break once with `--to-the-end` and put the first failure the runner prints for it into
`suites.CAUGHT_BY`: on GitHub a break without one is run again, alone and to the end. Every suite the change needs
and its own breaks then run on GitHub with its pull request, and every other break after the merge into `master`
([../docs/testing.md](../docs/testing.md), "Boot tests on GitHub").

It builds the interpreter and the kernel once, then runs the jobs longest first: each suite once (the long ones
split into their scenarios), and each break on purpose alone in a copy of the project. It opens no window and asks
nothing. It prints a line for each job as it ends and a table at the end, keeps every job's output in
`run-tests\<date-time>\` under the work folder, with a copy beside it of the notes each stand-in wrote during the job
(`<job>.<name>-server.log`), and ends with 0 only when every suite passed and every break was caught (the misses that
`docs/testing.md` names excepted).

- **What a change needs.** A test script or helper that changed runs every suite that uses it (read from the
  scripts' imports). A kernel file runs the suites whose entry in `suites.py` watches it; any other kernel file
  runs every suite, because nearly every file of the kernel runs at every start. A file that only holds words
  (`.md`) boots nothing. A break on purpose runs when the file it breaks changed, or the test that must catch it,
  or its own list.
- **Several machines at once.** Each test machine gets a work folder of its own under this checkout's (`w1`,
  `w2`, ...) and a range of stand-in ports of its own (`BOOS_PORT_BASE`, plus 100 for each). They share the
  copies of the project (`copies\`), which are built one at a time.
- **Turns for the whole computer** (`turns.py`): at most `BOOS_SEATS` test machines at once from all runs and
  checkouts together (4 when not set); one copy of a machine's whole memory at a time, from copying to the end of
  the search; one build with cargo at a time. A turn is a lock on a file in `boos-tests\turns`, which the
  computer gives back however the program that held it ends.
- **Breaks stop at their first failure.** One failure shows that a break is caught, so the runner stops the test
  there. It counts the break as caught only when that first failure is the one in `suites.CAUGHT_BY`, recorded
  from a run alone and to the end; any other first failure (a wait in vain while other machines ran, say) makes
  it run that break again, alone and to the end. The breaks of the kernel's own lines run through
  `run_lines_breaks.py` itself, one at a time, to the end: a break counts as caught when every check named for it
  catches it, as that script says.
- **The table checks itself.** A `test_*.py` or `run_*_breaks.py` that is in no entry of `suites.py` and not
  excused there, a list of breaks whose count differs from `suites.BREAK_COUNTS`, kinds of answer that differ from
  what the tests know, and a break whose old text no longer stands exactly once in its file: each is reported at
  every run, `--list` and "only what changed" included, and makes the run end with 1.
- **To add a suite:** one entry in `suites.py`. **To add a break on purpose:** a line in one of the lists
  (`run_key_breaks.py`, `run_look_breaks.py`, `run_reset_breaks.py`, `run_lines_breaks.py`, `run_try_breaks.py`
  with `test_try.py`, `app_breaks.py`, `apps_kept_breaks.py`, `model_breaks.py`, `model_breaks5.py`,
  `run_intel_card_breaks.py`), the count in
  `suites.BREAK_COUNTS`, and its first failure in
  `suites.CAUGHT_BY` after one run with `--to-the-end`. A break that can no longer be caught, for a reason that
  `docs/testing.md` gives, goes into `suites.KNOWN_MISSES` with that reason: it is still made and run, and counted
  as missed, as meant. A list of new breaks of the same kind (file, old text,
  new text, the test that must catch it) can run in the break copy as the key's and the look's do
  (`copy_break.py`): the project's own source is never changed. `run_tests.py` and `run_look_breaks.py` hand the
  test the break itself too (`KERNEL_BREAK`, beside the kernel in `KERNEL_FILE`), so that a copy of the kernel it
  builds of its own, as the look's stand-in does (`look_standin.py`), carries the same break.

## Where things go

`places.py` finds everything, so no script names a folder of one particular computer:

- the project is the folder above this one (`BOOS_PROJECT` names another);
- QEMU is looked for in `C:\Program Files\qemu` (`QEMU_DIR` names another folder), and its firmware is the
  project's `edk2-x86_64-code.fd` (`BOOS_FIRMWARE` names another file);
- everything a test makes (disk files, pictures, logs, copies of the project, test certificates) goes into a
  folder of its own under the computer's temporary folder, `boos-tests\<a mark of the project's folder>`
  (`BOOS_TEST_WORK` names another). Nothing is written inside the project, except by the scripts that change
  a source file for a moment on purpose, which put it back.

A test boot never uses the project's `disk.img`: every test makes disk files of its own.

**The network card.** Every test machine gets QEMU's virtio card, or the card that `BOOS_NETWORK_CARD` names, such
as `e1000` (`boot.py`). The table runs some suites both ways; the runner clears the name from its own surroundings, so
that a name left set by hand cannot change every suite.

**Ports.** QEMU's monitor gets a free port from the computer at every boot. The stand-in servers' port is built
into a copy of the kernel, so it comes from a range that starts at `BOOS_PORT_BASE` (44300 when not set). Two
checkouts tested at the same time need two bases.

**Made up.** Every name, key and password in these scripts is made up. Never put a real one here: the folder is
public. Test certificates are made fresh on each computer by `certs.py` and never stored here.

## The scripts

Building and helpers:

| Script | What it does |
| --- | --- |
| `build_all.py` | Builds the interpreter, then the kernel, and sees that the kernel holds the interpreter just built. Run it before any test |
| `boot.py` | One windowless boot: `Machine`, keys, pictures, the serial lines |
| `start_helper.py` | One boot with a given disk, checked key by key against the model of the chat box. For tests about other things it answers the question for a look with Enter alone as soon as it appears, and it reads from the disk file what the notebook holds under `look` before each start. Its `wait` waits, after its seconds, until the last row meant has come in the terminal |
| `picture.py`, `onboard_model.py`, `keyed_model.py` | The pictures that are meant: the chat box as it should look after each key, in the look in use, where every line but `key` and `setup` goes to the model and gets the row the kernel says at once. `keyed_model.py` knows the onboarding's questions, the question for a look among them, and a look the model picks |
| `look_values.py`, `look_model.py` | The four looks' colours, typed in by hand, with a check of their contrast ratios; the model for the look's own tests |
| `reset_model.py` | The look's model grown by the line `setup` bringing back the first look |
| `disk_helpers.py`, `gpt.py`, `nb.py` | Test disk files, dividing them into parts, reading and writing the notebook from outside |
| `lockref.py`, `keyref.py` | The lock worked out by other code (Python's own PBKDF2 and a ChaCha20-Poly1305 written from RFC 8439), to judge the kernel's |
| `net_copy.py`, `certs.py`, `model_server.py` | A copy of the project whose kernel talks to the stand-in for the provider on this computer, with test certificates; the stand-in itself, which answers the try of a key, a line (with words, a tool call, or any of its kinds of answer) and a request for an app; a good answer to a request that asks for it piece by piece goes so (`stream_pieces` in `chat_cases.py`), unless its last argument is `whole`, and ways in front of a line's behaviour (`hold:`, `cut:`, ...) change how |
| `look_standin.py` | Picking a look through the model for the look's tests: the stand-in, its copy of the kernel (with the break on purpose that the test's kernel has, if any), and the line `key` with a made-up key |
| `interp_helpers.py`, `raw_print.py` | Boot and output helpers |
| `ports.py`, `places.py` | Ports and folders, as above |
| `restore.py`, `crlf.py`, `export_check.py`, `make_lock_values.py`, `make_drawing_values.py` | Putting sources back after a break; Windows line ends; a clean export of a commit built from nothing; writing `src/lock_values.rs`; writing `src/drawing_values.rs`, the amounts of light made linear for the check of a table's letters |
| `app_cases.py` | The stand-in's answers to a request for an app, and what the kernel is meant to say, list and show for each, worked out apart from the kernel's code |
| `apps_kept_model.py` | Apps kept on the disk, worked out from the notes apart from the kernel's code: notebooks with things in pieces written and read from outside, the apps a start finds and the lines it prints, the panel of apps in the picture |
| `boot_disk_checks.py` | The boot disk: a reader of its start part's FAT32 file system, worked out from Microsoft's FAT specification and the reference firmware's checks apart from the script; a machine that QEMU starts from a disk file alone |
| `lines_model.py`, `lines_checks.py`, `lines_copy.py` | The kernel's own lines on the screen: the pictures that are meant (the start screen, the lines after F1, the stop screen); the checks that boot and judge them; a copy of the project with a failure or a break on purpose |
| `run_tests.py`, `suites.py` | The runner and its table, as above |
| `turns.py`, `copy_break.py`, `verdict.py` | Turns shared by the whole computer (seats, the memory turn, the build turn); a break on purpose made in a copy of the project and built there; the list of failures, each printed the moment it happens (`FAILED: ...`) |
| `chat_cases.py`, `chat_tools_model.py`, `conversation_model.py` | Every line to the model: the stand-in's answers to a line with words or a tool call, and how they go piece by piece (`model_server.py` sends them, answers a line with `make_app` first when a kind of app waits, and answers an ask about a line again with words of its own unless the next behaviour begins with `again:`), and what the kernel is meant to send, say and show, worked out from the notes apart from the kernel's code; `conversation_model.py` is what the kernel remembers of what was said, which `picture.py`'s chat box keeps, with the record each line went with (`Chat.records`) and what each ask again went with (`Chat.agains`); `table_model.py` is a table the model describes with `draw_table`, worked out from the notes apart from the kernel's code: the frame's place and room, the tool's text, the reading of a description, what the kernel says, the check of letters, and the picture, which `picture.py` paints when its chat box holds a table (`Chat.table`) |

Tests (each prints `FAILURES: none` or what went wrong, or the lines to judge):

| Script | What it checks |
| --- | --- |
| `boot_count.py <tag>` | A start on a fresh divided disk reaches the prompt with only plain text. `test_secret_keyed.py` makes the same report from its own start |
| `test_shift.py`, `test_more.py <tag> [shift]` | Typing with and without Shift, long rows, more rows than fit, every sign: every picture. With `shift`, Shift's steps follow the chat box's in the same start |
| `test_chat_line.py [scenario ...]` | The line typed in the chat box: 200 signs, the row being typed growing upward, the place where the next sign goes moved by the arrows, Home and End, signs put in and taken away there, Up and Down, a long line at 800 by 600, after a restart and while an answer comes in: every picture, and the terminal's rows. Its breaks on purpose are in `run_key_breaks.py` |
| `test_name3.py` | The name question at the first start and later starts |
| `test_key.py`, `test_key_memory.py` | The key and the password; the made-up secrets searched for in the machine's memory |
| `test_secret_keyed.py` | The secret line `key` |
| `test_model.py <kinds> [pieces]` | A line to the model against the stand-in, for 39 kinds of answer, every answer whole; with `pieces`, a good answer piece by piece, with the same rows meant |
| `test_try.py`, `test_key_model.py` | Trying a key with the stand-in at the onboarding; the unlocked key is the key typed |
| `test_look.py` | Picking a look: the onboarding's question, and the model's tool `pick_look` through the stand-in, every picture in the look in use, over several starts |
| `test_look_reset.py` | The line `setup` bringing back the first look: on the screen at once, on the disk at once, and the rows when it cannot be kept, over several starts |
| `test_look_his.py` | A person's path on a disk file made the way `run.bat` makes it, ended normally and by killing QEMU |
| `time_look.py`, `time_repaint.py` | How long a start shows the first look; how long painting the whole screen again takes (a measurement put into the source for a moment, then put back) |
| `run_regress_try.py` | Most of the above, one after another |
| `run_regress_look.py` | All of the above, the look's test included, one after another |
| `run_key_breaks.py`, `run_try_breaks.py`, `model_breaks.py`, `model_breaks5.py` | Breaks on purpose, each alone, in a copy of the project, and whether the tests catch them |
| `run_look_breaks.py` | Breaks of the look on purpose, each alone, in a copy of the project, and whether `test_look.py` catches them |
| `run_reset_breaks.py` | Breaks of `setup` bringing back the first look on purpose, each alone, in the project's own source, put back after each, and whether `test_look_reset.py` catches them (`run_tests.py` makes them in a copy of the project) |
| `test_app.py <kinds> [dump]`, `test_app.py nocard` | A line that asks for an app, against the stand-in, which answers it with `make_app` and then the request for the app: the requests, the script listed in the terminal, the app's run, the app's box and the rows, for the kinds in `app_cases.py`; a machine without a network card |
| `test_app_first_start.py keylater\|keyfirst` | A request for an app at a first start on a fresh divided disk, with the key given either way |
| `run_app_breaks.py`, `app_breaks.py` | The breaks on purpose for apps, each alone; a change to the interpreter is built into the copy too |
| `check_lua.py <script> [boots]` | A Lua script of `lua/` in place of the greeting script, in a copy: what the interpreter really does |
| `run_regress_apps.py` | Everything for apps, then the try of a key and `run_regress_try.py`'s list, one after another |
| `test_apps_kept.py [scenario ...]` | Apps kept on the disk and the panel of apps, in the stand-in copy: a first run in a new folder and a restart, keeping after an app asked for in a line, notebooks with things in pieces written from outside, looks, a small screen, a damaged, a full and a failing disk, QEMU killed while an app is kept, the kernel from before pieces on such a disk, and how long keeping and opening take |
| `run_apps_kept_breaks.py`, `apps_kept_breaks.py` | The breaks on purpose for apps kept on the disk, each alone, in the copy |
| `run_regress_kept.py` | Everything for apps kept on the disk, then the app tests, the try of a key, the locked key against the stand-in, the look's test and `run_regress_try.py`'s list, one after another: every suite of the two lists above, each once |
| `test_lines.py [start] [early] [small] [noscreen] [noserial] [later] [held]` | The kernel's own lines: the start screen, judged dot by dot with the machine paused at moments along the way; the usual picture at the prompt; F1, a key, Enter; a key during the start; a screen of 800 by 600, where the lines move up; no screen; no serial port; lines printed while F1 shows them; F1 held down (pressed again without being let go, through QEMU's machine protocol) |
| `test_lines_stop.py` | The stop screen after a failure or a panic made on purpose in a copy: right after the takeover, after the kernel's own page tables, in the middle of the start, with the usual picture, with the lines after F1, and in a task of its own while the start screen shows |
| `run_lines_breaks.py` | Breaks of the kernel's lines on purpose, each alone, in a copy, and whether those checks catch them |
| `test_boot_disk.py [made] [start] [again] [refuses]` | The boot disk: a new one read from outside, QEMU started from it alone, a new kernel that leaves boos's part alone, and the files the script must refuse |
| `run_boot_disk_breaks.py` | Breaks of `make-boot-disk.ps1` on purpose, each alone, in a copy of the script, and whether `test_boot_disk.py` catches them |
| `time_lines.py [boots] [commit]` | How much later the lines of a start arrive than with another commit's kernel, built from a clean export |
| `test_chat_tools.py [scenario ...]` | Every line to the model, in the stand-in copy: no key, the model's words and the tokens, an app asked for in words and run again after a restart, the panel's page turned, what a model may send that must not be believed, a line while an answer is awaited, no network card, no notebook; what is remembered: a second line that goes with the first, what is never remembered and what forgets, and the bounds of 10 lines and 8,000 bytes; and what a tool did going back to the model (`rounds`): a mistake and its fix, three asks at most, the last without tools, a look that ends the line, nothing done twice, an ask again turned down, a key an app puts together, `setup` while an app is awaited; a table drawn in the frame beside the panel of apps (`table`, on a disk without a notebook, where tables are not kept as documents, and `tablesmall`): whole, in another look, with rows left out, cut off at the limit, turned down, after F1, with more columns than fit and the key in a cell, past the bound on its inputs, and on a screen without room for one; apps with inputs (`inputs`, `inputsodd`): a converter made for "convert 5 km to miles" and kept with its input, run again with 12 and, after a restart, with 2.5, in one request each, a run without its value, an app kept before inputs existed, and everything about inputs and values that must not be believed, a head on the disk among it; and an answer that comes piece by piece (`stream`): the mark that the model thinks and the words as they come, in pictures taken while the stand-in holds the answer, the counts in a piece of their own, answers that break off, a tool and a table broken off, and pieces with their lengths in between |
| `run_chat_tools_breaks.py`, `chat_tools_breaks.py` | The breaks on purpose for every line to the model, each alone, in the copy |
| `test_downloads.py [scenario ...]` | Files fetched from the web and kept on the disk, in the stand-in copy, whose stand-in serves made-up files from made-up sites (`download_cases.py`): a file from a new site, asked about and allowed, through a redirect, kept and found after a restart; every refusal; a site not allowed and a redirect to a second site; a file removed and its room taken again; the room's line at a start; a room too full. Every GET and the list of tools of every request are compared with the notes, and the disk file is read from outside |
| `download_cases.py`, `download_breaks.py` | The stand-in's files and odd answers by site and path, with the rows the kernel is meant to say for each, worked out from the notes; the breaks on purpose for files, each caught by a scenario of `test_downloads.py` (run through `run_tests.py`) |
| `test_documents.py [scenario ...]` | Documents, tables kept on the disk, in the stand-in copy: a table kept, changed by a wish with its lines sent and kept as a new version in one ask, a second document, a restart with the panel listing both, a document opened, `setup` emptying the frame (`keep`); a change cut off and left as it was, a table without a document line, a change asked for a document that is not open, a new table cut off and not kept, a table with the key in a cell kept with stars, `forget` with a document open (`cut`); no title, an odd title, more rows than fit, documents that are not there, and a start that finds a document whose lines are not whole (`odd`); answers that break off in the middle of a change and of a new table (`broken`). Every request compared whole, every picture dot for dot, and the disk read from outside |
| `documents_model.py`, `document_cases.py`, `documents_breaks.py` | Documents worked out from the notes apart from the kernel's code: `draw_table` and `open_document` as offered, what the model is told about the open document, the kernel's rows, the lines and the notes kept, what a start finds and says, and the panel of documents in the picture; the stand-in's answers about documents (`chat_cases.py` hands it the behaviours it does not know) and the tables they describe; the breaks on purpose for documents, each caught by a scenario of `test_documents.py` (run through `run_tests.py`) |
| `test_intel_card.py [scenario ...]` | Intel's network card as QEMU plays it: the start with the 82540EM and every packet of it, another address, the 82545EM, a virtio card beside it (the virtio card is used), a virtio card that cannot be set up beside it (the Intel card is used), the card attached to nothing, the gateway asked twice on a network without it (counted in a recording), the card set up twice, 600 questions in a row, and a page of 300,000 bytes through the encrypted link from a test server |
| `run_intel_card_breaks.py` | The breaks on purpose for Intel's network card, each alone, in the break copy |
