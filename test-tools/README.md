# Test tools

Scripts that build the kernel, boot it in QEMU without a window, type keys through QEMU's monitor, save
pictures of the screen and compare them dot by dot with the picture that is meant, read the notebook from
outside, and stand in for the model's provider on this computer. [../docs/testing.md](../docs/testing.md) says
what was verified with them and which traps they avoid.

They are written in Python 3 and need nothing but its standard library, QEMU, and OpenSSL (the one that comes
with Git does). They were written for Windows. Run them from this folder.

## Where things go

`places.py` finds everything, so no script names a folder of one particular computer:

- the project is the folder above this one (`BOOS_PROJECT` names another);
- QEMU is looked for in `C:\Program Files\qemu` (`QEMU_DIR` names another folder);
- everything a test makes (disk files, pictures, logs, copies of the project, test certificates) goes into a
  folder of its own under the computer's temporary folder, `boos-tests\<a mark of the project's folder>`
  (`BOOS_TEST_WORK` names another). Nothing is written inside the project, except by the scripts that change
  a source file for a moment on purpose, which put it back.

A test boot never uses the project's `disk.img`: every test makes disk files of its own.

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
| `picture.py`, `onboard_model.py`, `keyed_model.py` | The pictures that are meant: the chat box as it should look after each key, in the look in use. `keyed_model.py` knows the onboarding's questions, the question for a look among them |
| `look_values.py`, `look_model.py` | The four looks' colours, typed in by hand, with a check of their contrast ratios; the model for the look's own tests |
| `reset_model.py` | The look's model grown by the line `setup` bringing back the first look |
| `disk_helpers.py`, `gpt.py`, `nb.py` | Test disk files, dividing them into parts, reading and writing the notebook from outside |
| `lockref.py`, `keyref.py` | The lock worked out by other code (Python's own PBKDF2 and a ChaCha20-Poly1305 written from RFC 8439), to judge the kernel's |
| `net_copy.py`, `certs.py`, `model_server.py` | A copy of the project whose kernel talks to the stand-in for the provider on this computer, with test certificates; the stand-in itself |
| `interp_helpers.py`, `raw_print.py` | Boot and output helpers |
| `ports.py`, `places.py` | Ports and folders, as above |
| `restore.py`, `crlf.py`, `export_check.py`, `make_lock_values.py` | Putting sources back after a break; Windows line ends; a clean export of a commit built from nothing; writing `src/lock_values.rs` |
| `app_cases.py` | The stand-in's answers to a request for an app, and what the kernel is meant to say, list and show for each, worked out apart from the kernel's code |
| `apps_kept_model.py` | Apps kept on the disk, worked out from the notes apart from the kernel's code: notebooks with things in pieces written and read from outside, the apps a start finds and the lines it prints, the panel of apps in the picture |
| `chat_server.py`, `chat_cases.py`, `chat_tools_model.py` | Every line to the model: a stand-in that answers a line with words or a tool call and a request for an app as before, its answers, and what the kernel is meant to send, say and show, worked out from the notes apart from the kernel's code |

Tests (each prints `FAILURES: none` or what went wrong, or the lines to judge):

| Script | What it checks |
| --- | --- |
| `boot_count.py <tag>` | A start on a fresh divided disk reaches the prompt with only plain text |
| `test_shift.py`, `test_more.py <tag>` | Typing with and without Shift, long rows, more rows than fit, every sign: every picture |
| `test_name3.py` | The name question at the first start and later starts |
| `test_key.py`, `test_key_memory.py` | The key and the password; the made-up secrets searched for in the machine's memory |
| `test_secret_keyed.py` | The secret line `key` |
| `test_model.py <kinds>` | `ask` against the stand-in, for 39 kinds of answer |
| `test_try.py`, `test_key_model.py` | Trying a key with the stand-in at the onboarding; the unlocked key is the key typed |
| `test_look.py` | Picking a look: the line `look` and the onboarding's question, every picture in the look in use, over several starts |
| `test_look_reset.py` | The line `setup` bringing back the first look: on the screen at once, on the disk at once, and the rows when it cannot be kept, over several starts |
| `test_look_his.py` | A person's path on a disk file made the way `run.bat` makes it, ended normally and by killing QEMU |
| `time_look.py`, `time_repaint.py` | How long a start shows the first look; how long painting the whole screen again takes (a measurement put into the source for a moment, then put back) |
| `run_regress_try.py` | Most of the above, one after another |
| `run_regress_look.py` | All of the above, the look's test included, one after another |
| `run_key_breaks.py`, `run_try_breaks.py`, `model_breaks.py`, `model_breaks5.py` | Breaks on purpose, each alone, in a copy of the project, and whether the tests catch them |
| `run_look_breaks.py` | Breaks of the look on purpose, each alone, in the project's own source, put back after each, and whether `test_look.py` catches them |
| `run_reset_breaks.py` | Breaks of `setup` bringing back the first look on purpose, each alone, in the project's own source, put back after each, and whether `test_look_reset.py` catches them |
| `test_app.py <kinds> [dump]`, `test_app.py nocard` | `make` against the stand-in: the request, the script listed in the terminal, the app's run, the box in the middle and the rows, for the kinds in `app_cases.py`; a machine without a network card |
| `test_app_first_start.py keylater\|keyfirst` | A request for an app at a first start on a fresh divided disk, with the key given either way |
| `run_app_breaks.py`, `app_breaks.py` | The breaks on purpose for apps, each alone; a change to the interpreter is built into the copy too |
| `check_lua.py <script> [boots]` | A Lua script of `lua/` in place of the greeting script, in a copy: what the interpreter really does |
| `run_regress_apps.py` | Everything for apps, then the try of a key and `run_regress_try.py`'s list, one after another |
| `test_apps_kept.py [scenario ...]` | Apps kept on the disk and the panel of apps, in the stand-in copy: a first run in a new folder and a restart, keeping after `make`, notebooks with things in pieces written from outside, looks, a small screen, a damaged, a full and a failing disk, QEMU killed while an app is kept, the kernel from before pieces on such a disk, and how long keeping and opening take |
| `run_apps_kept_breaks.py`, `apps_kept_breaks.py` | The breaks on purpose for apps kept on the disk, each alone, in the copy |
| `run_regress_kept.py` | Everything for apps kept on the disk, then the app tests, the try of a key, the locked key against the stand-in, the look's test and `run_regress_try.py`'s list, one after another: every suite of the two lists above, each once |
| `test_chat_tools.py [scenario ...]` | Every line to the model, in the stand-in copy: no key, the model's words and the tokens, an app asked for in words and run again after a restart, the panel's page turned, what a model may send that must not be believed, a line while an answer is awaited, no network card, no notebook |
| `run_chat_tools_breaks.py`, `chat_tools_breaks.py` | The breaks on purpose for every line to the model, each alone, in the copy |
