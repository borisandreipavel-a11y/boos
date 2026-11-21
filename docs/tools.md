# The tools: what the kernel does when the model asks

Code: `src/tools.rs`; the request and the reading of the answer in `model_chat` and `chat_reply` in `src/model.rs`; the line's way there and back in `model_ask` and `chat_answer` in `src/chat.rs`; what is remembered in `src/conversation.rs`.

Every line sent in the chat box goes to the model, except the two lines the kernel keeps for itself, `key` and `setup` (see [chat.md](chat.md)). With the line goes a list of **tools**: the things the kernel can do, each with a name, one sentence, and what it needs to be told. The model answers in words, or asks for one of the tools; the kernel then does it and says in its own plain sentence how that went. A new app, a failed tool or an extra tool the kernel skipped can bring a follow-up on the same line. The result and the answer stay together in memory.

## The words

- A **tool** is something the kernel can do when the model asks for it, described to the model in a few words: its name, a sentence about what it does, and its **inputs**, each with a type. The provider's documentation calls the list `tools`, and a model's request to use one a tool call.
- The **inputs** are what the model gives the tool, as a small piece of JSON, such as `{"app": 1}`.
- A **token** is a piece of a word, about three quarters of one; the provider is paid by the token (see [model.md](model.md)).

## The request

A line goes to the provider like every question (see "The request" in [model.md](model.md)), with this body, shortened here:

```text
{"model":"deepseek/deepseek-v4.1-flash-1017","messages":[{"role":"system","content":"You are the voice of ..."},{"role":"user","content":"roll the dice"}],"tools":[{"type":"function","function":{"name":"make_app",...}},...],"max_tokens":1000,"stream":false}
```

- **The instruction text** (`CHAT_INSTRUCTIONS`), as the system message, every time, word for word: "You are the voice of a small home-made operating system. The person at the machine types one line at a time into its chat box. You get the newest line, and below these instructions a record of the last lines before it and what came of them, if there were any. If the person asks you to forget what was said or to start over, use forget: saying so in words forgets nothing. Answer in plain words, in one or two short sentences, or use one of the tools when the person wants something done that a tool does. Use run_app for a kept app that fits the wish, and make_app only when none fits." It names no project and no person. The sentence about `forget` came after a person's run in which the real model, asked to forget what was said, answered "Done, clean slate" in words and used no tool, so that nothing was forgotten.
- **The record of what was said before the line,** behind the instruction text in the same system message, when anything was (see "What the model remembers" below).
- **The line**, as it was typed, as the user message; only a piece of the key in it is starred.
- **The tools**, in this order: `make_app` always; `run_app` while any app is kept; `pick_look` always; `turn_page` while the panel of apps has more than one page; `forget` while anything is remembered. The list and the record are made by the main loop when the line is sent (`chat_tools`, `conversation_record`), because only the main loop may read the kept apps and what is remembered, and they travel to the network's task with the errand (`Errand::ChatLine`).
- **1000 tokens at most** for the answer (`ANSWER_TOKENS`), as for the fixed question; a model that thinks pays its thinking out of them.
- **Nothing else is sent:** no `tool_choice`, no `parallel_tool_calls`, no `strict`, and nothing about thinking. Each would be a risk that only a paid request could show: the model's maker says that `tool_choice` set to `required` or to one tool gives a 400 while the model thinks, and its reference does not list `parallel_tool_calls`; the provider's documentation does not say what `strict` does.
- **Its size:** about 1,700 bytes with no app kept and nothing remembered (1,723 for the line `roll the dice`). The first kept app adds the tool `run_app`, some 330 bytes, and each further app its number and request in its sentence and its number in the list of numbers, some 20 to 60 bytes. Once anything is remembered, the record adds its rows and some 180 bytes before them, and the tool `forget` 360 bytes: the line `make it roll two dice` with the record of the example below, and no app kept, comes to 2,474 bytes.

## The five tools

Each is written out by hand in `tools.rs`, as JSON (see [json.md](json.md)), with every text in it written with `json_text`.

**`make_app`: a new app.**

```text
{"type":"function","function":{"name":"make_app","description":"Has a new app written for the person and runs it; an app that runs to its end is kept. Use it only when the person wants an app and no kept app fits.","parameters":{"type":"object","properties":{"request":{"type":"string","description":"What the app does, in at most 45 signs, such as: a dice that rolls"}},"required":["request"]}}}
```

- The request the model gives is cleaned (below), and then the model is asked for the app itself, with the request for an app that [apps.md](apps.md) describes: its instruction text about writing apps, and `Make this app: ` and the request. That is the second request of the line. Its answer is listed, run and kept as before.
- At once: `Kernel: I am asking the model to make "a dice that rolls".` (`app_make` in `apps.rs`).

**`run_app`: a kept app, again.**

```text
{"type":"function","function":{"name":"run_app","description":"Runs one of the kept apps again, as it was written, without writing it anew. The kept apps, by number: 2: a coin to flip; 1: a dice that rolls.","parameters":{"type":"object","properties":{"app":{"type":"integer","enum":[2,1],"description":"The number of the kept app"}},"required":["app"]}}}
```

- The kept apps are listed the one kept last first, as on the panel, each by its number and its request (see "Keeping an app" in [apps.md](apps.md)); `enum` holds their numbers. Only apps whose script is whole are listed.
- The script is read from the notebook (`app_kept` in `apps_kept.rs`) and run as any script: `Kernel: I am running the app made for "a dice that rolls".`, then the row about how the run went, as after a new app. It is not listed in the terminal again, and nothing is written: the model is not asked to make it.
- A number that no kept app has: `Kernel: the model asked for app 7, but no kept app has that number.`

**`pick_look`: another look.**

```text
{"type":"function","function":{"name":"pick_look","description":"Changes the colours of the whole screen to one of these looks, and keeps it for later starts: 1 Blue (a dark blue screen, light boxes with orange frames); 2 Night (an almost black screen, dark grey boxes, light letters); 3 Paper (a white screen, white boxes with grey frames, like a printed page); 4 Contrast (black and yellow, the easiest to read).","parameters":{"type":"object","properties":{"look":{"type":"integer","enum":[1,2,3,4],"description":"The number of the look"}},"required":["look"]}}}
```

- The look is put in use at once, the whole screen is painted again, and it is kept in the notebook under `look` (`look_pick` in `look.rs`): `Kernel: this is look 2, Night. It is kept on the disk.` Picking the look that is kept already writes nothing: `..., which is kept on the disk already.` Without a notebook that can be added to: `Kernel: this is look 2, Night. It lasts until the machine is switched off, because there is no notebook to keep it in.` If keeping fails: `Kernel: this is look 2, Night, but I could not keep it, because ..., so it lasts only until the machine is switched off.`
- `setup` still brings back the first look (see [chat.md](chat.md)).
- A number that is not on the list: `Kernel: the model asked for look 9, but there are only 4 looks.`

**`turn_page`: another page of the panel of apps.** Offered only while the panel has more than one page.

```text
{"type":"function","function":{"name":"turn_page","description":"Shows another page of the panel of kept apps near the top left of the screen. It has 2 pages, the app kept last first, and shows page 1 now.","parameters":{"type":"object","properties":{"page":{"type":"integer","description":"The number of the page, from 1 to 2"}},"required":["page"]}}}
```

- `Kernel: the panel of apps shows page 2 of 2.` and the panel is painted again (`apps_page_turn` in `apps_kept.rs`). A page that is not there: `Kernel: the model asked for page 5 of the panel of apps, but it has 2 pages.` The panel goes back to its first page when an app is kept and at every start.

**`forget`: start afresh.** Offered only while anything that was said is remembered.

```text
{"type":"function","function":{"name":"forget","description":"Forgets everything said before the newest line, so that the next line starts afresh. Only this tool makes the system forget; saying so in words does not. Use it whenever the person asks to forget what was said, to start over, or for a clean slate.","parameters":{"type":"object","properties":{}}}}
```

- It needs no inputs, and what the model gives it is not read.
- Everything remembered is forgotten, the line that asked for it too, and then: `Kernel: I forgot what was said so far. The next line starts afresh.` That row is not remembered either, so the next line goes with nothing, and without this tool.

## The answer

- **Where the kernel looks,** from the provider's documentation and the model's maker's: the model's words at `choices`, the first of them, `message`, `content`, as for every answer; a tool it asks for at `choices`, the first, `message`, `tool_calls`, the first, `function`, with the tool's `name` and its inputs at `arguments`, a text that is itself JSON. Whether a second tool call stands there is only looked at.
- **The model's words** are said as a row of their own that begins with `Model:`, so that they cannot be taken for the kernel's own sentences: cleaned like every text from outside, the key hidden, cut at 300 signs. Words and a tool may come together: the words first, then the tool is done.
- **Only the first tool is done.** When the model asks for more than one, `Kernel: the model asked for more than one thing at once, so I do only the first.` comes before it.
- **What the model asks for comes from outside, and is checked before anything is done:**
  - only the five names above count: any other gets `Kernel: the model asked for something I cannot do: "...".`, with the name cleaned and cut at 64 signs;
  - the inputs are held to 1,024 bytes (more counts as none), the key is hidden in them, and they are read with the JSON reader, which takes nothing on trust; the model's maker warns that its model does not always write sound JSON there;
  - a number may come as a number or as a text of digits alone;
  - inputs that cannot be read get a row of their own, such as `Kernel: the model asked to run a kept app, but I could not read which one.`;
  - a request for an app is cleaned byte by byte like every text from outside (every byte that is not a plain sign becomes a dot), spaces at either end go, and it is cut at 45 signs, before it is shown, sent on, or kept; an empty one gets `Kernel: the model asked for an app, but did not say what it should do.`
- **An answer cut off or held back** is said after the words: `Kernel: the model's answer was cut off at the limit of 1000 tokens.` A good answer with neither words nor a tool is said as for the fixed question: empty (with the reason, such as `because it spent all of its 1000 tokens thinking`), or, if its shape is not the documented one, with its first 160 signs. Any other answer (a refusal, a mistake on the provider's side, no answer) is said as for the fixed question (see [model.md](model.md)).

## What goes back after a tool runs

After a new app runs, the kernel asks the model about the same typed line again. The system message carries the older conversation first. A separate block says that the person typed nothing new and gives the results for this line. It includes the kernel's sentences, the last text this app showed (up to 40 signs), and the interpreter's last printed error on a Lua mistake (up to 200 signs). The box cleans these texts, and the kernel stars pieces of the key before keeping or sending them. Ordinary printed lines stay in the terminal.

A kept app that succeeds, a change of look or page, and forgetting usually finish in one trip. A tool refusal, a stopped app, or a second tool skipped in the same answer brings the result back. Forgetting ends the line immediately. Only the first tool in each answer can run. The kernel compares the inputs as it will use them, so it can decline to do the same thing twice.

There are at most three chat requests for a typed line. The third offers no tools and the kernel declines a tool even if the model sends one. Writing an app is a separate request, so a line can make up to five paid requests in total. The terminal marks each follow-up round. The chat box shows the model's words. A failed follow-up ends the line and keeps the results already obtained. Sending `setup` clears the record and cancels any further tool work for that line.

## What the model remembers

The model keeps nothing from one request to the next: whatever it should know of what was said before has to go with every request. So the kernel remembers the last lines that went to the model and what came of each, and sends them with every new line, as a written record behind the instruction text (`conversation.rs`). That way a line that only makes sense after the one before it, such as `make it roll two dice`, can be understood.

- **What is remembered:** each line that went to the model, as it was sent, as a row that begins with `Person:`, never with the person's name; and behind it the rows its answer brought, as the chat box said them: the model's words (`Model: ...`) and the kernel's own sentences (`Kernel: ...`), such as what a tool did, how an app's run went, or why no answer came. App output sent with a follow-up is remembered under `App showed:` or `App error:`. All rounds belong to one typed line. The tool the model asked for is not remembered as such: the kernel's sentence about it says what it was and what came of it.
- **What is not:** the lines `key` and `setup`, and everything typed or said in answer to the kernel's questions (a secret, a key, a password, a name, the number of a look); the rows at the start (the greeting, the line from before the last switch-off); the row said at once, `Kernel: I am asking the model.`; a line turned away at once (no key, no address, an answer still awaited); and the terminal's lines (the tokens, an app's script and its ordinary printed lines).
- **When:** a line is remembered when the answer to it comes back from the network's task, whatever that answer says (`conversation_line`), and the rows that `chat_say` and `model_say` say from then on belong to it (`conversation_row`), until the answer to the next line comes. A line for which no request was put together, because the machine has lost its address, is not remembered; nor is a line whose answer comes after `setup` was sent, since it belongs to what `setup` forgot.
- **The key:** a piece of the key in the line is starred before the line goes, as in the provider's answer (`key_hide` in `model.rs`; see [model.md](model.md)), and the line is remembered as it went; the record is starred again before it goes. On the screen, in the terminal and as the last line in the notebook, the line stays as it was typed.
- **How much:** the last 10 lines (`LINES_REMEMBERED`), each with what came of it, and never more than 8,000 bytes (`BYTES_REMEMBERED`) for the rows together, each with a line end; the oldest lines go first. A line and what came of it take from some tens to a few hundred bytes in a usual chat. App output and follow-up answers count towards the same bound.
- **How long:** until the machine is switched off; nothing of it is written to the disk. The tool `forget` (above) and the line `setup` forget everything, `setup` because another person may be at the machine then. The line `key` changes nothing about it.
- **How it goes:** behind the instruction text, in the same system message, after `RECORD_LEAD`, one row to a line, oldest first. The line itself stays the user message. Nothing more is sent when nothing is remembered. For example, after a line made a dice app, the next request could include these rows.

```text
...and make_app only when none fits.

What was said before the newest line, oldest first. "Person:" is the person at the machine, "Model:" is you, and "Kernel:" is the operating system saying what happened.
Person: I would like a dice to roll
Kernel: I am asking the model to make "a dice that rolls".
Kernel: the model wrote an app of 9 lines. It is shown in the terminal.
Kernel: the app ran to its end.
App showed: Dice: 4
Model: You rolled a four.
```

- **Why a written record, and not the conversation turn by turn:** the model's maker describes sending a conversation as a list of messages, the person's and the model's in turn. Its pages also say that when a request carries a list of tools, as every line here does, what the model thought (`reasoning_content`) in every earlier turn must be sent back too, or the request is refused with a 400. The provider's description of a message has no place for that, and its pages say nothing about passing it on (both read in November 2026). A record in the system message keeps the request in the shape that has been tried with the real model. What it cannot show on the test computer: whether the real model understands a line by the record; only a paid run can, and in a person's run it did (see [testing.md](testing.md)).
- **Only the main loop** may call the functions of `conversation.rs`. The list is taken out of its place and put back by value each time, so no reference to it is ever handed out.

## Tokens, in the terminal

After every good answer to a line or to a request for an app, the terminal says how many tokens it took, which is what the provider is paid for: `Tokens: 640 in, 600 of them repeated; 42 out, 12 of them thinking`.

- **In** is the request (`usage`, `prompt_tokens`); **repeated** is how many of them the provider had kept from an earlier request, which cost far less (`prompt_cache_hit_tokens`, the model's maker's name, or `prompt_tokens_details`, `cached_tokens`, the provider's); **out** is the answer (`completion_tokens`), and **thinking** how much of it went on thinking (`completion_tokens_details`, `reasoning_tokens`). A part the answer does not give is left out of the line.
- An answer that says nothing about its tokens: `Tokens: the provider did not say how many this answer took`.
- The line goes to the terminal only, not into the chat box. The try of a key at the onboarding prints none.

## Without a key, without the network, while waiting

- **No key kept:** `Kernel: I cannot ask the model, because no key is kept. Send the line "key" first.` Nothing leaves the machine.
- **No address on the network:** `Kernel: I cannot ask the model, because this machine has no address on the network`.
- **While the answer to a line or an app is awaited,** another line is turned away: `Kernel: I cannot ask the model, because the answer to what I asked before has not come yet`. It is still kept as the last line.
- Otherwise: `Kernel: I am asking the model.` at once, and the answer some seconds later. The kernel waits a minute at most (see [model.md](model.md)).

## What a line costs

Prices as the model's page gave them in November 2026, per million tokens: $0.15 for the request, $0.003 for the repeated part of it, $0.60 for the answer, all twice that in the busy hours (01:00 to 04:00 and 06:00 to 10:00 world time, on weekdays). Estimates, not measured with the real model:

- a request of about 600 tokens and an answer of about 40, most of the request repeated after the first line: about a hundredth of a cent; thinking, if the model thinks for some hundred tokens, a few hundredths more;
- what is remembered goes to the provider again with every line, and is paid for each time: a row can go with up to ten later typed lines and their follow-ups. A usual record of 10 short lines is about 2,000 bytes, roughly 500 tokens, the tool `forget` (360 bytes) some 100 to 150 more, and the instruction text's sentence about it some 25 with every line; at the full price that is about 0.01 cent more per line, so that a line costs about 0.02 cent instead of about 0.01, twice that in the busy hours. The record changes the beginning of the request at every line, so the part the provider counts as repeated may be smaller than before; how much is not known;
- each chat request has its own limit of 1000 tokens of answer at the busy price, about 0.12 cent, and the request with it, which the full record of 8,000 bytes, about 2,000 tokens, makes up to about 0.06 cent dearer;
- each app-writing request can add about half a cent (see [apps.md](apps.md)). A single line can use up to three chat requests and two app-writing requests.

The token line in the terminal shows what each answer really took, and how much of the request was repeated.

## How to test it

- **Against the stand-in for the provider** on the test computer (`model_server.py`, with the answers of `chat_cases.py` for a line), never against the real provider. Every request the stand-in gets is written down whole, and compared with what this page says is sent: the instruction text word for word, the line, the tools for what the disk holds, the limit, and nothing more.
- **Work out what the kernel should say from this page, apart from the kernel's code** (`chat_tools_model.py`), and compare every row, every token line, and every dot of the screen.
- **Feed it what a model may send:** words; each tool; a tool behind a thinking text full of quotes, brackets and line ends; words and a tool; two tools; a tool the kernel does not have; an odd name; inputs that are not JSON, missing, or too long; numbers as text, and numbers that fit nothing; requests that are long, odd, empty, or hold the key; an answer cut off, one spent on thinking, a refusal, and a good answer without words or a tool.
- **The thing this part is done by:** a line asks for an app in other words, the app is made, runs and is kept; after a restart, `roll the dice` runs the kept app, the stand-in gets one request only, and nothing new is written on the disk.
- **What is remembered,** against the stand-in: `I would like a dice to roll`, then `make it roll two dice`, which must go with the first line and what came of it, and nothing else; and every request of a scenario compared whole with the request worked out from this page by a model of what is remembered (`conversation_model.py`), kept apart from the kernel's code. What must never be remembered is sent on purpose: a name kept and a key unlocked with a password, the line `key` and its secret, a line that holds the key, a line turned away while an answer is awaited, the tool `forget`, `setup`; and every request is searched for the name, the password and any piece of the key. The bounds: twelve short lines, of which the twelfth goes with the ten before it; then lines with the longest rows, until the bytes and not the count decide what goes.
- What only the real model can show: whether it picks `run_app` over `make_app` for a wish that fits a kept app, whether its tool calls have the shape the documentation gives, and whether it understands a line by the record of what was said before it. A person's own paid run was the first real test of the tools, and they said it worked; nothing of it was watched (see [testing.md](testing.md)).

## Limits

See "Every line to the model" in [open-points.md](open-points.md). In short: every line is a paid question that needs the network and takes seconds; the model sees the last 10 lines and what came of them, until the machine is switched off, and everything it sees is sent again with every line; up to two tools can run for a line; every kept app makes every request longer; the model may pick the wrong tool, and nothing checks its choice.
