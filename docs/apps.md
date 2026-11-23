# Apps made on request

Code: `src/apps.rs`; the asking itself in `model_app` in `src/model.rs`; the errand `Errand::AppRequest` in `src/errand.rs` and its run in `src/network.rs`; the tools `make_app` and `run_app` in `src/tools.rs`; the run in `chat_answer` in `src/chat.rs`; `box_script` in `src/app_box.rs` and `seed` in `interpreter/src/lib.rs`; keeping an app and the panel of apps in `src/apps_kept.rs`, with the notebook in `src/notebook.rs`.

The idea of this kernel is that a model writes the apps. The person at the machine says in the chat box what app they want, and the model writes it as a script in the language Lua, which the interpreter runs inside the locked box (see [interpreter.md](interpreter.md) and [box.md](box.md)).

**Today the script is asked for, checked, shown in the terminal and run once.** What the app shows appears in the box under the panel of apps, what it prints comes out in the terminal, and the chat box says in one plain sentence how the run went. **An app that ran to its end is kept on the disk,** and the panel of apps near the top left of the screen lists it, also after the machine was switched off and on again. **A kept app runs again** when the person asks for it and the model picks it, without being written anew.

## The words

- A **request** is the few words that say what an app does, such as "a dice that rolls". The model gives it with the tool `make_app`, from what the person typed (see [tools.md](tools.md)); before every line went to the model, it was what the person typed after the word `make`.
- The **instruction text** is a fixed text that the kernel sends to the model with every request, before the request itself. It says how an app for this kernel is written.
- A **system message** is the part of a request to a model that tells it how to behave, apart from what it is asked. The provider's documentation lists `system` among the roles a message can have.
- **Marks** here are lines that begin with three backquotes, ```` ``` ````, which many models put around code.

## What it does today

- **The person asks for an app in their own words,** in any line: `I would like a dice to roll`. The line goes to the model like every line (see [tools.md](tools.md)), and the model asks for a new app with the tool `make_app` and a request, such as "a dice that rolls". The request comes from outside: it is cleaned byte by byte, spaces at either end go, and it is cut at 45 signs before it is shown, sent on or kept.
- **The kernel then asks the model for the app itself** (`app_make`), with the request below, as an errand for the network's task (see "Errands" in [tasks.md](tasks.md)), and says so at once: `Kernel: I am asking the model to make "a dice that rolls".` That needs a kept key, as every line does; an empty request gets `Kernel: the model asked for an app, but did not say what it should do.`
- **An app may take inputs,** values the model fills in at each run, such as the distance a converter converts: `convert 5 km to miles` makes a converter with the input `km` and runs it with 5 (`Kernel: I am asking the model to make "converts km to miles", with km 5.`), and `convert 12 km` runs the kept converter with 12, without its being written again. See "Inputs" below.
- **The answer comes later, as a row of its own,** and, when the model wrote a script that passes the checks below, the terminal shows the script under that row, line by line. Then the script runs (see "Running it" below): what it prints follows as `App:` lines, what it shows appears in the box under the panel of apps, and a second row says how the run went:

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
- show(text) puts one line of at most 40 characters in a box on the screen. This is what the person at the machine sees. Each show replaces the line shown before, and the last one stays on the screen after the script has ended. A longer text is cut at 40 characters, and a 21st show stops the script.
- print(...) writes one line to a log beside the screen. A line longer than 200 characters is cut, and a 101st print stops the script.

Use only plain English letters, digits and the signs of a US keyboard; any other character comes out as a dot.

The app may take inputs, listed below its request, each with a name, a kind and a sentence. Before the script runs, their values are put in a table called input, such as input.km for an input called km: a number as a Lua number, a text as a string of at most 100 characters, and a yes/no as true or false. When no inputs are listed, the app takes none and input is empty: do not read it then. Write the app for any values, not only for one: if a value makes no sense, show in a few words what is wrong.

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

- The first message is the instruction text, as the system message. The second is the request, with `Make this app: ` (`APP_LEAD`) in front of the words that were typed, so that a model reads them as the app to make, and the app's inputs below it, if it has any (`app_wanted`; see "Inputs" below). Both texts are written with `json_text` (see [json.md](json.md)), so quotes and backslashes in the request travel as they were typed.
- **`max_tokens` is 4000** (`APP_TOKENS` in `model.rs`), against 1000 for the fixed question: a script is longer than a greeting, and a model that thinks before it answers may pay its thinking out of the same tokens. 4000 tokens are about 16 KB of text, so the thoughts and the script together stay well inside the 64 KB the kernel reads of an answer. The provider is paid by the token used, not by the limit: at the model's prices in November 2026 (0.60 dollars a million tokens out, twice that in the provider's busy hours) the whole limit would cost at most about half a cent.
- The body is about 2,000 bytes (2,023 to 2,040 in the tests, for requests of 6 to 23 signs; 2,094 for `converts km to miles` with its one input), so the request travels in several pieces through the connection's 512 bytes of sending room; the encrypted link sends them one after another (see [network.md](network.md)).
- The key is the kept one, borrowed once for the asking exactly as for a line; a request cannot be made with a key being tried at the onboarding.
- The wait for the answer is the same 60 seconds (`MODEL_WAIT`). The provider's page for the model gave, in November 2026, about 170 tokens a second, with the first token within 2.7 seconds for half of the questions and within 10 for 95 of 100; so 4000 tokens fit in the minute. How long the real model takes for an app was not seen.
- The request goes to the provider, and from there to the maker of the model, as every line does.

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
- **What it shows** appears in the box under the panel of apps, the last showing over the ones before; it stays there after the run. **What it prints** comes out in the terminal as `App:` lines, below the listing.
- **The values of its inputs,** if it has any, are handed to the interpreter as data behind the script, which puts them in the table `input` before the script runs (see "Inputs" below). A new app runs with the values the model gave with `make_app`; they wait in the kernel, with the errand, until the app has come.

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

**What goes back to the model.** After a new app's run, the model is asked about the line again (see "When what a tool did goes back" in [tools.md](tools.md)), with the rows above and what the app left behind, which `box_script` reports either way: the last text it showed in this run, as `Kernel: the app left this on the screen: "Dice: 4".`, and, for a stop at a mistake, the interpreter's line, as `Kernel: the terminal says: "Lua stopped: [string "app"]:3: attempt to perform arithmetic on a nil value".` (`AppRun` in `apps.rs`). Neither is said in the chat box; both are remembered with the line. A kept app's run goes back only when it was stopped. The request for an app itself never gets any of it: a fix is a new app, for a request in other words.

## Keeping an app

Right after the row about the run, `chat_answer` hands the app to `app_keep` in `apps_kept.rs`, if it ran to its end.

- **Which apps are kept:** every app that ran to its end, with either of the two rows that say so (it showed something, or it showed nothing). An app that was stopped, for a mistake, for too much work or for any other reason, is not kept.
- **What is kept,** in the notebook (see [notebook.md](notebook.md)), as two things under names made from the app's number:
  - `app 3 script`: the script exactly as it ran, which is what the checks above took out of the model's words, with any piece of the key already turned into stars; for an app with inputs, a head with the inputs in front of it (see "Inputs" below). A script longer than 448 bytes is kept in pieces; the longest, 32,768 bytes, in 74.
  - `app 3`: a note. Its first byte, 1, says what form the rest has, so that later forms can say more about an app; in form 1 the rest is the request.
- **In that order:** the script first, and then it is read back from the disk and compared with the script that ran, byte for byte; only if they are the same is the note kept. So an app whose note is there had its whole script there first.
- **While it is kept, keys wait,** as while it runs: keeping is done in the main loop, and every entry is written, put down for good and read back, and the whole script is read back once more. How long that takes is in [testing.md](testing.md).
- **Its number** is the one after the highest kept so far, starting at 1, up to 999,999,999 (nine digits). **An app made for exactly the same request as a kept one takes that one's number:** its script, with its inputs, takes the place of the old one, and the note, which says the same, is not written again. So asking again for the same app gives a fresh try in the same place, and the list does not fill up with copies. Requests that differ in a space or a capital letter are different requests.
- **Nothing is said in the chat box when an app is kept,** as with every line that is kept. The terminal says `Apps: the app made for "a dice that rolls" is kept on the disk`, and the panel of apps (below) shows its first page with the app at the top.
- **When it cannot be kept** in a notebook that can be added to, a row says why: `Kernel: I could not keep the app, because the notebook is full.`, or `the disk did not give its script back as it was written`, or the disk's own reason, or, once an app numbered 999,999,999 is kept, `the numbers for apps have run out` for every new request (nothing of it is written; an app made for the request of a kept one still takes that one's number). On a machine without a notebook that can be added to (no disk, no part of the kernel's own, a damaged notebook) nothing is kept and nothing is said; the lines at startup have said why.
- **Both things are kept unlocked,** readable by anyone with the disk, like every line kept there.
- **A kept app runs again** when the person asks for it in a line and the model picks it with the tool `run_app`, which lists the kept apps by number and request, with the inputs of each that has any (see [tools.md](tools.md)). Its script is read from the notebook and run as it was kept, with the values the model gave, without asking the model to write it again: `Kernel: I am running the app made for "a dice that rolls".`, then the row about how the run went. Nothing is written.

At every start, once the notebook is opened, `apps_kept_begin` (called at the end of `chat_begin`) finds the kept apps again: every note under a name `app` and a number (one to nine digits, without a 0 in front) whose form is 1 and which holds a request. An app counts if the notebook found its script whole (see "A thing in pieces" in [notebook.md](notebook.md)) and the inputs in front of it can be read; the notebook checked the check value of every script in pieces as it opened, and each script is read once more for its inputs. When any app is kept, the terminal lists them, the one kept last first, and the panel shows them:

```text
Apps: 2 are kept on the disk:
Apps: "a coin to flip"
Apps: "a dice that rolls"
```

An app whose note is there and whose script is not whole is left out, with a line of its own in the terminal: `Apps: the script kept for "..." is not whole, so that app is left out`; so is one whose inputs cannot be read (`Apps: the inputs kept for "..." cannot be read, so that app is left out`). It keeps its number, so a new app made for its request takes its place again. With no app kept, nothing is said and no panel is shown.

A request read from the disk comes from outside the kernel: at most 45 bytes of it are taken, and every byte that is not a plain sign becomes a dot.

## Inputs

Code: `src/app_inputs.rs`; the tools in `src/tools.rs`; the table in `interpreter/src/lib.rs`.

An app may take **inputs**: values the model fills in each time the app runs, such as the distance a converter converts. So `convert 5 km to miles` makes a converter with an input `km` and runs it with 5, and `convert 12 km` later runs the kept converter with 12, without its being written again.

- **Three kinds:** a number, which may have a point and may be below zero (`5`, `-3`, `2.5`); a text of at most 100 signs; and a yes/no.
- **The model names them** when it asks for a new app with `make_app` (see [tools.md](tools.md)): at most 4, as lines of text, one for each input, with its name, its kind, one sentence that says what it is, and its value for this first run, parted by `|`: `km | number | the distance in kilometres | 5`. The request says what the app does in general, without its inputs or this run's values ("converts km to miles"), so that one app serves every distance.
- **The model that writes the app** is told the inputs, below the request, and never the values, so that it writes the app for any of them:

```text
Make this app: converts km to miles
Its inputs:
- km, a number: the distance in kilometres
```

- **The script finds the values in a table called `input`,** as `input.km`: a number as a Lua number (whole when it is written without a point, with a point otherwise), a text as a string, a yes/no as `true` or `false`. They are put there with Lua's own functions before the script runs, never written into the script's text, so no value can be taken for Lua (see [interpreter.md](interpreter.md)). An app without inputs finds the table empty.
- **A kept app runs with new values** when the model asks for it with `run_app` and gives them (see [tools.md](tools.md)): `Kernel: I am running the app made for "converts km to miles", with km 12.`
- **The kernel's sentences name the values,** and the model remembers them with the line: a number and a yes/no as they were checked, a text in quotes, cut at 40 signs with `...` behind when it is longer (the app gets the whole text). Values are kept nowhere else, never on the disk.
- **Every input needs its value at every run, the first included.** A run without one is turned down, and for a new app that means it is not written. The model is told to ask the person in plain words then, unless a value is obvious (six sides for a dice): the refusal goes back to the model in the same line, it asks, and the person's answer comes with the next line, which goes with the record of the last lines (see [tools.md](tools.md)). There are no defaults.

### What is checked

Everything about inputs comes from outside, from the model or from the disk, and is checked before anything is done with it:

- **A name** has 1 to 20 signs, letters, digits and `_` only, begins with a letter, and is none of the 22 words Lua keeps for itself (`and`, `end`, `for`, `in`, `repeat` and the others), so that `input.name` is always sound Lua. The interpreter on board refuses exactly these 22 as names (`test-tools/lua/numbers.lua`). No two inputs of an app have the same name.
- **A kind** is `number`, `text` or `yes/no`, in small letters or capitals.
- **The sentence** is cleaned like a request (every byte that is not a plain sign becomes a dot, spaces at either end go), cut at 80 signs, and may not be empty.
- **A number** is written with digits, at most one point with digits on both sides of it, and a minus sign in front at most, with at most 15 digits in all; spaces around it are dropped. `1e3`, `1,000`, `+5` and `.5` are no numbers here. The kernel does not reckon with it: it hands it on as it was written, and the interpreter makes the number inside the box.
- **A text** is cleaned like every text from outside and may have 100 signs. A piece of the key in it was starred before, as in everything the model gives a tool (see [model.md](model.md)).
- **A yes/no** is `yes`, `no`, `true` or `false`.
- **The inputs and the values come as lines of text,** the inputs as `name | kind | what it is | value` and the values, for `run_app`, as `name | value` (or `name = value`, or `name: value`, in a line without a `|`). Spaces around each part, empty lines, and a `|` at either end of a line are dropped; a value is the rest of its line, so that a text may hold a `|`, but not a line end. An empty value counts as none. No `inputs` or `values` at all, `null`, or a text without lines means none; anything but a text (a list, a set of named things, a number) is turned down, not taken for none, so that the model hears of it and can give them again in the same line.
- **Why lines of text, and not a list:** the first form gave the inputs as a list of sets of named things, and the values the same way. In two runs of a person's own with the real model it was left empty: the first time the model gave no inputs at all, which the kernel took for none, and the app was written without inputs; the second time it wrote the input into the request's words (`converts kilometres to miles, taking the km as an input`). Lines of text are what the real model had filled well for a table (see [tools.md](tools.md)). In a third run, with lines of text that were still not required, the model again gave only the request, and the app was written without inputs; since then `make_app` requires the inputs (an empty text for an app that takes none) and `run_app` the values, while any kept app has inputs.
- **For `run_app`,** a value for a name the app has no input of is turned down, and so is a name given twice. Turned down, not passed over: `convert 12 km to feet` given to a converter to miles must not quietly answer in miles.

Each refusal is one sentence of the kernel's, and goes back to the model in the same line, like every refusal (see "When what a tool did goes back" in [tools.md](tools.md)). What the model gave is shown cleaned and cut at 40 signs. Behind `Kernel: `:

| The row | When |
|---|---|
| `the model asked for an app, but did not give its inputs as lines of text, one for each input: name \| kind \| what it is \| value.` | `inputs` is anything but a text: a list, a set of named things, a number or a word (`null` counts as no inputs) |
| `the model asked for an app, but I could not read its inputs.` | `inputs` is no sound JSON |
| `the model asked for an app with more than 4 inputs.` | A fifth line |
| `the model gave the app's input 2 as "km number", but an input is written as name \| kind \| what it is \| value.` | A line with fewer than three parts |
| `the model named an input "end", but a name has letters, digits and _ only, begins with a letter, has at most 20 signs, and is no word of Lua's own.` | A name that breaks the rule, or none |
| `the model gave two inputs the name "km".` | A name twice |
| `the model gave the input "km" the kind "integer", but an input is a number, a text or a yes/no.` | Another kind |
| `the model gave the input "km" no sentence that says what it is.` | No sentence, or one of spaces only |
| `the model asked for an app with the input "km", but gave it no value, so the app was not written.` | `make_app` without a value |
| `the model asked to run a kept app, but did not give its values as lines of text, one for each: name \| value.` | `values` is anything but a text (`null` counts as no values) |
| `the model asked to run a kept app, but I could not read its values.` | `values` is no sound JSON |
| `the model gave the value 2 as "count 3", but a value is written as name \| value.` | A line without `\|`, `=` or `:` |
| `the model gave a value for "unit", but the app made for "converts km to miles" has no input of that name.` | An unknown name; `... takes no inputs.` for an app without inputs |
| `the model gave the input "km" two values.` | A name twice |
| `the model gave the input "km" no value.` | A name without a value |
| `the model asked to run the app made for "converts km to miles", but gave no value for its input "km".` | `run_app` without a value |
| `the model gave the input "km" the value "five", which is not a number written with digits.` | A number that breaks the rule |
| `the model gave the input "word" a text of 140 signs, and an input takes at most 100.` | A text too long |
| `the model gave the input "loud" the value "maybe", which is not yes or no.` | A yes/no that is neither |

### Kept with the script

An app's inputs are kept in the same thing as its script, `app 3 script`, in front of it, so that one write keeps both and they never get out of step, also when an app made for the same request takes the place of the old one:

| Bytes | What |
|---|---|
| 1 | 0xFF, a byte that no proper text (UTF-8) holds |
| 1 | The form of what follows: 1 |
| 1 | How many inputs: 1 to 4 |
| For each input | Its kind's letter (`n`, `t` or `y`), its name's length in one byte and the name, its sentence's length in one byte and the sentence |
| The rest | The script |

- **An app without inputs is kept as before inputs existed:** the script alone. So apps kept before run as they always did, and a kernel from before inputs runs such apps too.
- **A kernel from before inputs, finding an app with inputs,** still lists it, and refuses to run it: it wants the whole thing as proper text, and the first byte is not (`its script on the disk is not proper text`). It never takes the head for Lua. This is read from that kernel's code, not tried.
- **The head is read like everything from the disk,** by the same rules as the model's inputs. An app whose head breaks one is left out at the start (see "Keeping an app" above); running it gives `I could not run the app made for "...", because its inputs on the disk cannot be read.`
- **At every start each kept script is read once more,** for its inputs, since `run_app` lists them with every line. Not measured: by what opening the notebook takes (about 0.6 ms a block and some 24 ms for the check value of 32 KB, see [testing.md](testing.md)), a few thousandths of a second for a usual app and about 0.07 seconds for the longest are to be expected.
- **A head takes up to 415 bytes,** so the longest script the box takes, 32,768 bytes, cannot be kept with inputs: the notebook refuses the thing (`I could not keep the app, because the thing is too long for the notebook.`). Every app so far has been far shorter.

## The panel of apps

A panel near the top left of the screen, under the sentence, lists the kept apps a page at a time. It is the kernel's own, drawn by `apps_kept.rs` with the pieces of `screen.rs`; it is not the box under it that shows an app's text.

```text
Apps: page 1 of 2
- a coin to flip
- a dice that rolls
- ...
```

- **It is there only while at least one app is kept.** It appears at a start that finds kept apps, with the rest of the usual picture when the start is over (see "The kernel's lines" in [screen.md](screen.md)), and when the first app is kept. A screen without kept apps looks as it did before.
- **The first row says which page is shown and how many there are,** and below it come the apps of that page, five a page, the one kept last first, each as `- ` and its request. A row holds 47 signs, so a request of 45 always fits whole.
- **It shows the first page,** at every start and again whenever an app is kept. When it has more than one page, the model can turn it with the tool `turn_page`, when the person asks for another page (see [tools.md](tools.md)).
- **Its sizes are kept in one place,** `APPS_PANEL_STYLE` in `apps_kept.rs`: its top left corner 40 dots from the left and 80 from the top, 600 dots across, a frame 3 dots thick, the text 10 dots from the frame, letters at size 2 and 4 dots between rows, and five apps a page. That makes it 158 dots high: on QEMU's usual screen of 1280 by 800 dots it covers columns 40 to 639 and rows 80 to 237. It keeps that size whatever the page shown holds. It lies under the sentence and above the box with an app's text, which sits 20 dots under it, from row 258 on every screen.
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
- Ask for the app in words, through the tool `make_app` of a stand-in that answers lines too (see [tools.md](tools.md)), and see that the second request is the request for an app, byte for byte.
- **Inputs:** ask for a converter with an input and its value, and see the request for the app name the input and not the value, the app run with the value and kept with its input, byte for byte; run it again with other values, a whole number and one with a point, also after a restart, in one request and with nothing written; leave a value out; and give, once each, every kind of input and value the rules above turn down. Give an app every kind of input, the values as texts and as JSON's own numbers and words, a text with signs that are not plain and the key, and see what Lua made of each in what the app prints. Put a head that breaks a rule on the disk from outside.

[testing.md](testing.md) lists what was verified.

## Limits

See "Apps made on request" in [open-points.md](open-points.md). In short: a kept app runs again only when the model picks it; a kept app cannot be taken away, only replaced; the panel turns its page only when the model is asked to; the request has at most 45 signs; the model is told the same fixed text every time; typing waits while an app runs; an app can show one line and print to the terminal, and nothing else; an app has at most 4 inputs, of three kinds, and every run needs a value for each, given by the model.
