# Apps made on request

Code: `src/apps.rs`; the asking itself in `model_app` in `src/model.rs`; the errand `Errand::AppRequest` in `src/errand.rs` and its run in `src/network.rs`; the line `make` and the run in `chat_answer` in `src/chat.rs`; `box_script` in `src/app_box.rs` and `seed` in `interpreter/src/lib.rs`; keeping an app and the panel of apps in `src/apps_kept.rs`, with the notebook in `src/notebook.rs`.

The idea of this kernel is that a model writes the apps. The person at the machine says in the chat box what app they want, and the model writes it as a script in the language Lua, which the interpreter runs inside the locked box (see [interpreter.md](interpreter.md) and [box.md](box.md)).

**Today the script is asked for, checked, shown in the terminal and run once.** What the app shows appears in the box in the middle of the screen, what it prints comes out in the terminal, and the chat box says in one plain sentence how the run went. **An app that ran to its end is kept on the disk,** and the panel of apps near the top left of the screen lists it, also after the machine was switched off and on again. Nothing runs a kept app again yet.

## The words

- A **request** is what the person types after the word `make`: `make a dice that rolls` asks for "a dice that rolls".
- The **instruction text** is a fixed text that the kernel sends to the model with every request, before the request itself. It says how an app for this kernel is written.
- A **system message** is the part of a request to a model that tells it how to behave, apart from what it is asked. The provider's documentation lists `system` among the roles a message can have.
- **Marks** here are lines that begin with three backquotes, ```` ``` ````, which many models put around code.

## What it does today

- **A line that begins with the word `make` and a space asks for an app** (`MAKE_WORD`, `app_wanted`): what follows the word, without spaces at either end, is the request. The line is not given back. A request has at most 45 signs, what is left of the 50-sign line after the word and its space.
- `make` by itself, or with nothing but spaces behind it, asks nothing: `Kernel: write what app to make after the word, such as "make a dice".`
- `makes`, `maker` or `Make a dice` are ordinary lines and are given back.
- **It needs a kept key,** like `ask`: without one, `Kernel: I cannot ask the model for an app, because no key is kept. Send the line "key" first.`
- **Otherwise it leaves an errand for the network's task** (see "Errands" in [tasks.md](tasks.md)) and answers at once, `Kernel: I am asking the model to make "a dice that rolls".` One errand at a time: while the answer to a `make`, an `ask` or a `fetch` is awaited, the next one is turned away, `Kernel: I cannot ask the model for an app, because the answer to what I asked before has not come yet`. On a machine without an address on the network it is turned away at once.
- **The answer comes later, as a row of its own,** and, when the model wrote a script that passes the checks below, the terminal shows the script under that row, line by line. Then the script runs (see "Running it" below): what it prints follows as `App:` lines, what it shows appears in the box in the middle of the screen, and a second row says how the run went:

```text
Kernel: the model wrote an app of 4 lines. It is shown in the terminal.
Script 1: local sides = 6
Script 2: local roll = math.random(1, sides)
Script 3: print("You rolled a " .. roll)
Script 4: show("Dice: " .. roll)
App: You rolled a 5
Kernel: the app ran to its end.
```

The rows the answer can bring:

| The row (behind `Kernel: `) | When |
|---|---|
| `the model wrote an app of N lines. It is shown in the terminal.` | The number 200, words that hold a script, and the script passed the checks |
| `the model's app was cut off at the limit of 4000 tokens, so it is not whole.` | The words are there, but the answer says it ended because it reached the limit (`length`). Nothing is shown |
| `the provider held part of the model's app back, so it is not whole.` | The words are there, but the provider's filter ended the answer (`content_filter`). Nothing is shown |
| `the model's answer is no app, because there is no script in it.` | The words held nothing but marks and spaces |
| `the model's answer is no app, because the script is N bytes long, and the box takes at most 32768.` | The script is longer than the box takes (`SCRIPT_LIMIT` in `app_box.rs`) |
| `the model's answer was empty ...` | As for the fixed question (see [model.md](model.md)), with 4000 tokens as the limit |
| Anything else | Exactly the sentences of the fixed question: the provider turned it down, could not answer, or no answer came (see [model.md](model.md)) |

` Its answer did not come whole.` is added, as for the fixed question, when the provider did not say through the encrypted link that it had sent everything; the script is still taken if its JSON closed properly.

## What the model is told

The instruction text is `APP_INSTRUCTIONS` in `apps.rs`. It is sent with every request, the same each time:

```text
You write small apps for a home-made operating system. Each app is one script in the language Lua 5.4. Answer with the script only: no words before or after it, and no ``` marks around it.

The script runs once, from its first line to its last, and then ends. It runs in a locked box: it cannot read keys, files, the clock or the network, and it cannot wait. Lua's string, table and math libraries are there; io, os, require, debug, coroutine and utf8 are not. math.random works.

Two functions put out what the app has to say:
- show(text) puts one line of at most 40 characters in a box in the middle of the screen. This is what the person at the machine sees. Each show replaces the line shown before, and the last one stays on the screen after the script has ended. A longer text is cut at 40 characters, and a 21st show stops the script.
- print(...) writes one line to a log beside the screen. A line longer than 200 characters is cut, and a 101st print stops the script.

Use only plain English letters, digits and the signs of a US keyboard; any other character comes out as a dot.

The script's budget of work is small, about four thousand rounds of a simple loop in all, so keep loops short. A script longer than 32 KB is refused.

If the request cannot be done with these, write a script that shows in a few words what cannot be done.
```

- **Everything it says was checked against the interpreter on board** before it was written, with a script that tried each claim: the three libraries are there and the six names are `nil`; `string.format`, `table.sort` and whole-number division work; a printed line is cut at 200 signs; a tab and a letter with an accent come out as dots. The limits of `show` and `print`, the budget and the 32 KB are the box's and the interpreter's own (see [box.md](box.md) and [interpreter.md](interpreter.md)).
- **`math.random` on its own gives the same numbers at every start**: the interpreter's random numbers start from the same place each time, and the box has no clock and no source of random numbers to start them elsewhere. The kernel therefore gives every run of an app a new starting place (see "Running it" below); an earlier form of the text told the model that the numbers repeat.
- It names no project and no person: "a home-made operating system".
- The text is written out line by line in the source with its line ends spelt out, so that it does not depend on the kind of line end the file has.
- What the model makes of the text is not checked, except for the marks (below). A model that answers in words instead of a script gets those words taken as the script.

## The request

The same as for the fixed question (see [model.md](model.md)), with two differences in the body: two messages instead of one, and a larger limit of tokens.

```text
{"model":"deepseek/deepseek-v4.1-flash-1017","messages":[{"role":"system","content":"You write small apps ..."},{"role":"user","content":"Make this app: a dice that rolls"}],"max_tokens":4000,"stream":false}
```

- The first message is the instruction text, as the system message. The second is the request, with `Make this app: ` (`APP_LEAD`) in front of the words that were typed, so that a model reads them as the app to make. Both texts are written with `json_text` (see [json.md](json.md)), so quotes and backslashes in the request travel as they were typed.
- **`max_tokens` is 4000** (`APP_TOKENS` in `model.rs`), against 1000 for the fixed question: a script is longer than a greeting, and a model that thinks before it answers may pay its thinking out of the same tokens. 4000 tokens are about 16 KB of text, so the thoughts and the script together stay well inside the 64 KB the kernel reads of an answer. The provider is paid by the token used, not by the limit: at the model's prices in November 2026 (0.60 dollars a million tokens out, twice that in the provider's busy hours) the whole limit would cost at most about half a cent.
- The body is about 1,500 bytes (1,531 to 1,548 in the tests, for requests of 6 to 23 signs), so the request travels in several pieces through the connection's 512 bytes of sending room; the encrypted link sends them one after another (see [network.md](network.md)).
- The key is the kept one, borrowed once for the asking exactly as for `ask`; a request cannot be made with a key being tried at the onboarding.
- The wait for the answer is the same 60 seconds (`MODEL_WAIT`). The provider's page for the model gave, in November 2026, about 170 tokens a second, with the first token within 2.7 seconds for half of the questions and within 10 for 95 of 100; so 4000 tokens fit in the minute. How long the real model takes for an app was not seen.
- What is typed after `make` goes to the provider, and from there to the maker of the model, as for `ask`.

## Taking the script out of the answer

The words are read where the fixed question's are: at `choices`, the first, `message`, `content`, or the first piece of a list there (see [model.md](model.md)). Then:

1. **How the answer ended is looked at first.** A script cut off at the limit of tokens (`length`) or held back in part by the provider (`content_filter`) is not whole, and is not taken.
2. **The marks are taken off** (`app_script` in `apps.rs`). The instruction text asks for the script alone, but a model may still put it between two lines of marks, with words around them. Then only what stands between the first two such lines is taken: a second block of code, and words before or after, are dropped. With one line of marks only, what stands after it is taken if nothing but empty lines comes before it, and what stands before it otherwise. Without marks, the words are the script.
3. **Spaces and empty lines at either end are dropped.** A return before a line end is dropped too, so every line of the script ends in a line end alone.
4. **A script that is empty now is no app.** One longer than `SCRIPT_LIMIT` (32,768 bytes, the most the box hands to the interpreter) is no app either, and is said with its length.
5. **The key is hidden in the script** with the rule that hides it in every word from the provider (`key_hide`, see [model.md](model.md)): a run of signs that stands in the key and is six signs long or longer becomes stars. The model never sees the key, so this only matters if the provider puts it there.

The script and the row travel back to the main loop with the errand's answer (`Answer.script`).

## Showing it in the terminal

`app_print_script` prints each line of the script as `Script N: ...`, where N is the line's number, the same number Lua names when a script stops at a mistake (`[string "app"]:2: ...`). An empty line is `Script N:`.

- The script came from outside the kernel, so each line is cleaned like every text from outside (`plain_text` in `page.rs`): a tab first becomes two spaces, every other sign that is not a plain sign becomes a dot, and a return is dropped. A line is cut at 200 signs (`SCRIPT_LINE_SHOWN`).
- Each line is printed on its own, so that device signals are never held off for long (see "Output" in [README.md](README.md)).
- Nothing of the script goes into the chat box except the row that says how many lines it has. Once it has run to its end, it is kept on the disk (see "Keeping an app" below); otherwise it is gone.

## Running it

Right after the listing, `app_run` in `apps.rs` hands the script to the interpreter in the box (`script_run_seeded` in `interpreter.rs`, `box_script` in `app_box.rs`), and says in one sentence how the run went.

- **It runs in the main loop,** the part of the kernel that takes the keys and paints the chat box, from `chat_answer`. After startup the main loop is the one part of the kernel that paints the screen, so the box an app's text is shown in and the chat box are never painted at the same time. The other tasks go on while it runs; the main loop does nothing else.
- **While it runs, keys wait.** They are kept in the keyboard's line of 16 key numbers and taken when the run is over: about eight keys without Shift, four with it. Keys beyond that are lost. A small app is over within a second; the longest a run can hold the main loop is the time its fuel or its memory lasts, under two seconds (see [interpreter.md](interpreter.md)).
- **Its limits are any script's:** one megabyte of memory, 100 million units of fuel, 100 printed lines, 20 showings. Fuel is the only thing that ends a script that does not end by itself; there is no limit by the clock.
- **A new starting place for its random numbers at every run.** Before the script runs, the kernel takes a random number from the processor (`random_number`), halves it so that it stays a whole number above zero, and hands it to the interpreter's `seed`, which starts Lua's random numbers there (`math.randomseed`). Two runs of the same script then roll differently. A machine whose processor makes no random numbers would hand nothing over, and the numbers would repeat from run to run as before; but such a machine cannot make the encrypted link either (see [encryption.md](encryption.md)), so it never gets an app to run. The script written by hand that runs at startup gets no seed.
- **A shown text longer than 40 signs is cut,** by the interpreter, at 40 bytes, as a printed line is cut at 200; the kernel's own rule, which stops a program that hands it a longer text, is never reached from a script. A cut may fall inside a letter of several bytes; the kernel shows such bytes as dots anyway.
- **What it shows** appears in the box in the middle of the screen, the last showing over the ones before; it stays there after the run. **What it prints** comes out in the terminal as `App:` lines, below the listing.

The row after the run, behind `Kernel: `:

| The row | When |
|---|---|
| `the app ran to its end.` | The script ran to its last line and showed something |
| `the app ran to its end, but it showed nothing on the screen.` | The same, without a single showing; what it printed is in the terminal |
| `the app was stopped, because it has a mistake in it; the terminal says which.` | Lua found a mistake in how it is written or while it ran. The interpreter's own line above says which and where, such as `App: Lua stopped: [string "app"]:3: attempt to perform arithmetic on a nil value`; the number is the line in the listing |
| `the app was stopped, because it did too much work.` | It used up its fuel |
| `the app was stopped, because the interpreter gave up, most likely for lack of memory.` | The interpreter itself gave up (WebAssembly's `unreachable`), which is what it does when the script has used up its memory |
| `the app was stopped, because ...` | Any other stop, with the kernel's reason: `it printed too many texts` at the 101st print, `it showed too many texts` at the 21st showing, and so on |

The kernel tells the kinds of stop apart by what the box reports, not by its words: `box_script` gives back a `ScriptStop` with a kind, read from wasmi's own kind of trap for fuel and for `unreachable`, and from the interpreter's answer for a mistake.

## Keeping an app

Right after the row about the run, `chat_answer` hands the app to `app_keep` in `apps_kept.rs`, if it ran to its end.

- **Which apps are kept:** every app that ran to its end, with either of the two rows that say so (it showed something, or it showed nothing). An app that was stopped, for a mistake, for too much work or for any other reason, is not kept.
- **What is kept,** in the notebook (see [notebook.md](notebook.md)), as two things under names made from the app's number:
  - `app 3 script`: the script exactly as it ran, which is what the checks above took out of the model's words, with any piece of the key already turned into stars. A script longer than 448 bytes is kept in pieces; the longest, 32,768 bytes, in 74.
  - `app 3`: a note. Its first byte, 1, says what form the rest has, so that later forms can say more about an app; in form 1 the rest is the request, the words that were typed after `make`.
- **In that order:** the script first, and then it is read back from the disk and compared with the script that ran, byte for byte; only if they are the same is the note kept. So an app whose note is there had its whole script there first.
- **While it is kept, keys wait,** as while it runs: keeping is done in the main loop, and every entry is written, put down for good and read back, and the whole script is read back once more. How long that takes is in [testing.md](testing.md).
- **Its number** is the one after the highest kept so far, starting at 1, up to 999,999,999 (nine digits). **An app made for exactly the same request as a kept one takes that one's number:** its script takes the place of the old one, and the note, which says the same, is not written again. So asking again for the same app gives a fresh try in the same place, and the list does not fill up with copies. Requests that differ in a space or a capital letter are different requests.
- **Nothing is said in the chat box when an app is kept,** as with every line that is kept. The terminal says `Apps: the app made for "a dice that rolls" is kept on the disk`, and the panel of apps (below) shows its first page with the app at the top.
- **When it cannot be kept** in a notebook that can be added to, a row says why: `Kernel: I could not keep the app, because the notebook is full.`, or `the disk did not give its script back as it was written`, or the disk's own reason, or, once an app numbered 999,999,999 is kept, `the numbers for apps have run out` for every new request (nothing of it is written; an app made for the request of a kept one still takes that one's number). On a machine without a notebook that can be added to (no disk, no part of the kernel's own, a damaged notebook) nothing is kept and nothing is said; the lines at startup have said why.
- **Both things are kept unlocked,** readable by anyone with the disk, like every line kept there.

At every start, once the notebook is opened, `apps_kept_begin` (called at the end of `chat_begin`) finds the kept apps again: every note under a name `app` and a number (one to nine digits, without a 0 in front) whose form is 1 and which holds a request. An app counts if the notebook found its script whole (see "A thing in pieces" in [notebook.md](notebook.md)); the notebook checked the check value of every script in pieces as it opened. When any app is kept, the terminal lists them, the one kept last first, and the panel shows them:

```text
Apps: 2 are kept on the disk:
Apps: "a coin to flip"
Apps: "a dice that rolls"
```

An app whose note is there and whose script is not whole is left out, with a line of its own in the terminal: `Apps: the script kept for "..." is not whole, so that app is left out`. It keeps its number, so a new app made for its request takes its place again. With no app kept, nothing is said and no panel is shown.

A request read from the disk comes from outside the kernel: at most 45 bytes of it are taken, and every byte that is not a plain sign becomes a dot.

## The panel of apps

A panel near the top left of the screen, under the sentence, lists the kept apps a page at a time. It is the kernel's own, drawn by `apps_kept.rs` with the pieces of `screen.rs`; it is not the box in the middle of the screen that shows an app's text.

```text
Apps: page 1 of 2
- a coin to flip
- a dice that rolls
- ...
```

- **It is there only while at least one app is kept.** It appears at a start that finds kept apps, and when the first app is kept. A screen without kept apps looks as it did before.
- **The first row says which page is shown and how many there are,** and below it come the apps of that page, five a page, the one kept last first, each as `- ` and its request. A row holds 47 signs, so a request of 45 always fits whole.
- **It shows the first page,** at every start and again whenever an app is kept. Nothing turns the page yet.
- **Its sizes are kept in one place,** `APPS_PANEL_STYLE` in `apps_kept.rs`: its top left corner 40 dots from the left and 80 from the top, 600 dots across, a frame 3 dots thick, the text 10 dots from the frame, letters at size 2 and 4 dots between rows, and five apps a page. That makes it 158 dots high: on QEMU's usual screen of 1280 by 800 dots it covers columns 40 to 639 and rows 80 to 237. It keeps that size whatever the page shown holds. It lies under the sentence and above the box with an app's text, which begins at row 270 on a screen of 800 by 600 dots and lower on larger ones; on a smaller screen the two could overlap.
- **Its colours are those of the box with an app's text,** from the look in use: the frame's, the inside's and the letters'. `look_paint` paints it again with everything else when the look changes (`apps_panel_again`).
- **Painting it** paints the whole panel in the frame's colour, the inside over it, and the rows. **Nothing lands outside it:** only as many signs of a row are written as fit whole between the frame and the empty room on both sides.
- **On a machine without a usable screen** nothing is painted; the lines in the terminal say which apps are kept.
- **Only the startup code and the main loop may call `apps_kept.rs`:** the list of kept apps and the page shown are plain `static mut` values that nothing protects. The list grows, so `kept_apps()` hands it out through its address, with the same rule as the chat box's lists (see [chat.md](chat.md)).

## What the script is trusted with

Nothing. It is text from outside: it is limited in size before it is read (the answer's 64 KB), taken out of the JSON by the kernel's own reader, held to the box's limit, cleaned before any of it is printed, and searched for the key. No part of the kernel acts on what the script says. It runs in the box, which holds it to its memory, its fuel and its two calls, and what it prints and shows is cleaned like every app's text (see [box.md](box.md)).

## What the real model wrote

One request was made with a real key, in a person's own run, and the terminal showed this, which the person pasted back:

```text
Script 1: local faces = {
Script 2:   "[     o     ]",
Script 3:   "[  o     o  ]",
Script 4:   "[  o  o  o  ]",
Script 5:   "[ o  o  o  o ]",
Script 6:   "[ o o o o o ]",
Script 7:   "[o o o o o o]"
Script 8: }
Script 9: for i = 1, 8 do
Script 10:   show("Rolling " .. faces[math.random(1, 6)])
Script 11: end
Script 12: local n = math.random(1, 6)
Script 13: show("Rolled " .. n .. " " .. faces[n])
```

- So a good answer to a request for an app comes through the kernel's link, within the minute the kernel waits, and the model's words hold Lua only: no words of explanation reached the listing. Whether the model put marks around it, which the kernel would have taken off, cannot be told from the listing.
- It keeps to the instruction text: it uses `show` nine times, each with a text of 21 to 23 signs (counted by a script, for each of the six faces), against the 40 a text may have and the 20 showings a run may make; it prints nothing; its loop has eight rounds. It uses `math.random`, which the text of that time said repeats its numbers at every start.
- It shows eight lines one after another as if they were frames of a rolling die. Nothing in the box waits, so when it runs, the last line is the only one that stays to be seen. Run against the stand-in, it ends with such a line, `Rolled 4 [ o  o  o  o ]` or another face, and the row `the app ran to its end.`
- Nothing more of that run is known: not the request, not the row, not how long the answer took, not whether the model thought first.
- In a later run of a person's own, after scripts were run, an app the real model wrote for a request ran and its text appeared in the box in the middle of the screen. Nothing else of that run is known.

## How to test it

- **Against a stand-in for the provider on the test computer** (see "A server on the test computer" in [testing.md](testing.md)), never against the real provider: each request costs money. The stand-in sends a script of a known shape for each request, and checks every request it gets with another JSON reader: the model's name, the two messages, the instruction text word for word, the limit of tokens.
- **Work out what the kernel should say from the rules above, with code written apart from the kernel's,** and compare every row, every `Script` line, and every dot of the screen.
- Feed it the awkward shapes: marks with and without words around them, one line of marks, two blocks, marks only, both kinds of line end, tabs, signs that are not plain, lines over 200 signs, a script exactly 32,768 bytes long and one byte longer, a script that holds the key, an answer cut off, held back, empty or in another shape.
- **Give every script a known outcome:** what it prints, what the box shows after it, and the row about its run, worked out by hand from Lua's rules, since no other Lua interpreter is at hand to compare with. For a script that rolls dice, take the number from the line it printed and see that the box shows the same number. Make every kind of stop happen once: a mistake, a mistake in writing, fuel, memory, too many prints, too many showings.
- **Run a script that prints random numbers twice in one start:** the two lines must differ.
- Keep `ask` in the same test: the fixed question must still be sent as before.

[testing.md](testing.md) lists what was verified.

## Limits

See "Apps made on request" in [open-points.md](open-points.md). In short: an app runs once, and a kept app cannot be run again yet; a kept app cannot be taken away, only replaced; the panel shows its first page only; the request has at most 45 signs; the model is told the same fixed text every time; typing waits while an app runs; an app can show one line and print to the terminal, and nothing else.
