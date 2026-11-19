# Apps made on request

Code: `src/apps.rs`; the asking itself in `model_app` in `src/model.rs`; the errand `Errand::AppRequest` in `src/errand.rs` and its run in `src/network.rs`; the line `make` in `src/chat.rs`.

The idea of this kernel is that a model writes the apps. The person at the machine says in the chat box what app they want, and the model writes it as a script in the language Lua, which the interpreter can run inside the locked box (see [interpreter.md](interpreter.md) and [box.md](box.md)).

**Today the script is asked for, checked and shown in the terminal. Nothing runs it yet.**

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
- **The answer comes later, as a row of its own,** and, when the model wrote a script that passes the checks below, the terminal shows the script under that row, line by line:

```text
Kernel: the model wrote an app of 4 lines. It is shown in the terminal.
Script 1: local sides = 6
Script 2: local roll = math.random(1, sides)
Script 3: print("You rolled a " .. roll)
Script 4: show("Dice: " .. roll)
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

The script runs once, from its first line to its last, and then ends. It runs in a locked box: it cannot read keys, files, the clock or the network, and it cannot wait. Lua's string, table and math libraries are there; io, os, require, debug, coroutine and utf8 are not. math.random works, but gives the same numbers at every run.

Two functions put out what the app has to say:
- show(text) puts one line of at most 40 characters in a box in the middle of the screen. This is what the person at the machine sees. Each show replaces the line shown before, and the last one stays on the screen after the script has ended. A text longer than 40 characters stops the script, and so does a 21st show.
- print(...) writes one line to a log beside the screen. A line longer than 200 characters is cut, and a 101st print stops the script.

Use only plain English letters, digits and the signs of a US keyboard; any other character comes out as a dot.

The script's budget of work is small, about four thousand rounds of a simple loop in all, so keep loops short. A script longer than 32 KB is refused.

If the request cannot be done with these, write a script that shows in a few words what cannot be done.
```

- **Everything it says was checked against the interpreter on board** before it was written, with a script that tried each claim: the three libraries are there and the six names are `nil`; `string.format`, `table.sort` and whole-number division work; a printed line is cut at 200 signs; a tab and a letter with an accent come out as dots. **`math.random` gives the same numbers at every start**: the interpreter's random numbers start from the same place each time, and the box has no clock and no source of random numbers to start them elsewhere. The limits of `show` and `print`, the budget and the 32 KB are the box's and the interpreter's own (see [box.md](box.md) and [interpreter.md](interpreter.md)).
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
- The body is about 1,600 bytes (1,575 to 1,592 in the tests, for requests of 6 to 23 signs), so the request travels in several pieces through the connection's 512 bytes of sending room; the encrypted link sends them one after another (see [network.md](network.md)).
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
- Nothing of the script goes into the chat box except the row that says how many lines it has. Nothing of it is kept: once it is shown, it is gone.

## What the script is trusted with

Nothing. It is text from outside: it is limited in size before it is read (the answer's 64 KB), taken out of the JSON by the kernel's own reader, held to the box's limit, cleaned before any of it is printed, and searched for the key. No part of the kernel acts on what the script says. When scripts are run, they run in the box, which holds them to its memory, its fuel and its two calls.

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
- It keeps to the instruction text: it uses `show` nine times, each with a text of 21 to 23 signs (counted by a script, for each of the six faces), against the 40 a text may have and the 20 showings a run may make; it prints nothing; its loop has eight rounds. It uses `math.random`, which the text says repeats its numbers at every start.
- It shows eight lines one after another as if they were frames of a rolling die. Nothing in the box waits, so when such a script runs, the last line is the only one that stays to be seen.
- Nothing more of that run is known: not the request, not the row, not how long the answer took, not whether the model thought first.

## How to test it

- **Against a stand-in for the provider on the test computer** (see "A server on the test computer" in [testing.md](testing.md)), never against the real provider: each request costs money. The stand-in sends a script of a known shape for each request, and checks every request it gets with another JSON reader: the model's name, the two messages, the instruction text word for word, the limit of tokens.
- **Work out what the kernel should say from the rules above, with code written apart from the kernel's,** and compare every row, every `Script` line, and every dot of the screen.
- Feed it the awkward shapes: marks with and without words around them, one line of marks, two blocks, marks only, both kinds of line end, tabs, signs that are not plain, lines over 200 signs, a script exactly 32,768 bytes long and one byte longer, a script that holds the key, an answer cut off, held back, empty or in another shape.
- Keep `ask` in the same test: the fixed question must still be sent as before.

[testing.md](testing.md) lists what was verified.

## Limits

See "Apps made on request" in [open-points.md](open-points.md). In short: the script is shown, not run; the request has at most 45 signs; the model is told the same fixed text every time; the script is not kept; random numbers repeat.
