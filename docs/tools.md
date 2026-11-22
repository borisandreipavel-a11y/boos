# The tools: what the kernel does when the model asks

Code: `src/tools.rs`; the request and the reading of the answer in `model_chat` and `chat_reply` in `src/model.rs`; the line's way there and back in `model_ask`, `chat_answer` and `ask_again` in `src/chat.rs`; what is remembered in `src/conversation.rs`.

Every line sent in the chat box goes to the model, except the two lines the kernel keeps for itself, `key` and `setup` (see [chat.md](chat.md)). With the line goes a list of **tools**: the things the kernel can do, each with a name, one sentence, and what it needs to be told. The model answers in words, or asks for one of the tools; the kernel then does it and says in its own plain sentence how that went. When what came of it needs the model (a new app, an app that was stopped, a tool the kernel turned down, a second tool it did not do), the model is asked about the line again, with what came of it, at most three times in all (see "When what a tool did goes back" below). The line, the model's words and the kernel's sentences are remembered, and go with the next lines (see "What the model remembers" below).

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
- **When the model is asked about the line again,** the request has the same shape, and the instruction text goes on with what came of the line so far; the last such ask has no list of tools (see "When what a tool did goes back" below).

## The five tools

Each is written out by hand in `tools.rs`, as JSON (see [json.md](json.md)), with every text in it written with `json_text`.

**`make_app`: a new app.**

```text
{"type":"function","function":{"name":"make_app","description":"Has a new app written for the person and runs it; an app that runs to its end is kept. Use it only when the person wants an app and no kept app fits.","parameters":{"type":"object","properties":{"request":{"type":"string","description":"What the app does, in at most 45 signs, such as: a dice that rolls"}},"required":["request"]}}}
```

- The request the model gives is cleaned (below), and then the model is asked for the app itself, with the request for an app that [apps.md](apps.md) describes: its instruction text about writing apps, and `Make this app: ` and the request. That is the second request of the line. Its answer is listed, run and kept as before, and what came of it goes back to the model (see "When what a tool did goes back" below).
- At once: `Kernel: I am asking the model to make "a dice that rolls".` (`app_make` in `apps.rs`).

**`run_app`: a kept app, again.**

```text
{"type":"function","function":{"name":"run_app","description":"Runs one of the kept apps again, as it was written, without writing it anew. The kept apps, by number: 2: a coin to flip; 1: a dice that rolls.","parameters":{"type":"object","properties":{"app":{"type":"integer","enum":[2,1],"description":"The number of the kept app"}},"required":["app"]}}}
```

- The kept apps are listed the one kept last first, as on the panel, each by its number and its request (see "Keeping an app" in [apps.md](apps.md)); `enum` holds their numbers. Only apps whose script is whole are listed.
- The script is read from the notebook (`app_kept` in `apps_kept.rs`) and run as any script: `Kernel: I am running the app made for "a dice that rolls".`, then the row about how the run went, as after a new app. It is not listed in the terminal again, and nothing is written: the model is not asked to make it. An app that runs to its end ends the line; one that was stopped goes back to the model.
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
- **Only the first tool is done.** When the model asks for more than one, `Kernel: the model asked for more than one thing at once, so I do only the first.` comes before it, and that goes back to the model (see below).
- **What the model asks for comes from outside, and is checked before anything is done:**
  - only the five names above count: any other gets `Kernel: the model asked for something I cannot do: "...".`, with the name cleaned and cut at 64 signs;
  - the inputs are held to 1,024 bytes (more counts as none), the key is hidden in them, and they are read with the JSON reader, which takes nothing on trust; the model's maker warns that its model does not always write sound JSON there;
  - a number may come as a number or as a text of digits alone;
  - inputs that cannot be read get a row of their own, such as `Kernel: the model asked to run a kept app, but I could not read which one.`;
  - a request for an app is cleaned byte by byte like every text from outside (every byte that is not a plain sign becomes a dot), spaces at either end go, and it is cut at 45 signs, before it is shown, sent on, or kept; an empty one gets `Kernel: the model asked for an app, but did not say what it should do.`
- **An answer cut off or held back** is said after the words: `Kernel: the model's answer was cut off at the limit of 1000 tokens.` A good answer with neither words nor a tool is said as for the fixed question: empty (with the reason, such as `because it spent all of its 1000 tokens thinking`), or, if its shape is not the documented one, with its first 160 signs. Any other answer (a refusal, a mistake on the provider's side, no answer) is said as for the fixed question (see [model.md](model.md)).

## When what a tool did goes back

Without this, the model would hear what its tool did only with the person's next line, and could neither say what a new app showed nor fix one that stopped. So when what came of a tool needs the model, the kernel asks the model about the same line again, with what came of it so far (`ask_again` in `chat.rs`). What needs the model is said by each tool when it is done: `tool_do` gives back whether the line ends there (`ToolDone`).

- **What goes back:** what came of a new app, always: its run, with what it left on the screen and, if it stopped at a mistake, the interpreter's line about it; or why the model's answer is no app. A kept app that was stopped. Everything the kernel turns down: a tool it does not have, inputs it cannot read, a kept app, a look or a page that is not there, an empty request for an app. And a second tool the model asked for that was not done.
- **What ends the line, as before:** words without a tool; a kept app that runs to its end; a look that is picked; a page that is shown; `forget`, which leaves nothing of the line to send. So `roll the dice`, with a kept dice, is still one request.
- **The ask** has the shape of the line's first: the line, as it was sent, as the user message; as the system message the instruction text, the record of the lines before it if there were any, and behind them `AGAIN_LEAD` and the rows the line has brought so far, one to a line, oldest first; and the list of tools as it stands then, which now offers `forget`, since the line is remembered, and `run_app` for an app just kept. `AGAIN_LEAD`, word for word: "What came of the newest line so far, oldest first. "Model:" is you, and "Kernel:" is the operating system saying what happened. The person has typed nothing since. If what they wanted is done, say in plain words what came of it. Use a tool again only if it is not done. A new app is written from its request alone, so to fix an app, use make_app with a request that says what to do differently." The request for an app gets nothing but the request (see [apps.md](apps.md)), so a fix can only come through a request in other words.
- **At most three asks a line** (`ASKS_MOST`), the first included; the requests that write an app are not counted, so a line costs at most three asks and two apps. The third ask goes without the list of tools, and its instruction text ends with `LAST_ASK`: "You are asked about this line for the last time, and no tools are offered now: answer in plain words." If its answer still asks for a tool, the tool is not done: `Kernel: the model asked for a tool in its last answer about this line, when none was offered, so I did nothing.`
- **Nothing twice:** a tool asked for again for the same line with the same inputs, as the kernel reads them (`tool_wanted`: a number written as text is the same number, and a request for an app is compared as it was cleaned), is not done again: `Kernel: the model asked for the same thing again for this line, so I did not do it twice.` That goes back too.
- **What an app left behind** is remembered with the line as sentences of the kernel's, but not said in the chat box or the terminal, since the box in the middle of the screen and the app's own lines show it already: `Kernel: the app left this on the screen: "Dice: 4".`, the last text the app showed in this run, at most 40 signs, and only if it showed one; and for an app stopped at a mistake `Kernel: the terminal says: "Lua stopped: [string "app"]:3: attempt to perform arithmetic on a nil value".`, the interpreter's line, at most 200 signs. Both came from the app, which cleaned them through the box; a piece of the key in them is starred when they are remembered (`key_starred_kept` in `model.rs`), since a script may put the key together out of pieces too short to be starred where it came in, and again when they go. They are new: what an app shows and its mistakes reach the provider this way, and go with the next lines too, as everything remembered does.
- **A request that fails ends the line:** an ask the provider turns down or does not answer is said as for the first ask; a request for an app that brings no good answer (anything but 200) ends the line after its row. What was done stays done, and is remembered. An ask that cannot be handed to the network's task is said, as `Kernel: I cannot ask the model again, because ...`.
- **`setup` ends the asks:** it forgets, and the model is not asked about the line again, not even when a new app it asked for comes after `setup`; an answer awaited then is still said, and its tool done, as before.
- **A line typed meanwhile** is turned away, as while any answer is awaited: from the line's first ask to its last, the network's task always has one request of the line in hand or waiting.
- **On the screen** nothing new: the model's words come as a row of their own (`Model: ...`), as for the first ask; a make-app line already fills five of the chat box's six rows. The terminal has one line of its own for each ask again, such as `Round 2 of 3: the model is asked again, with what came of the line so far`, with `, without tools` for the third.

After `make a dice that rolls`, when the app ran, the second ask goes with this behind the instruction text (with no line before it):

```text
...and make_app only when none fits.

What came of the newest line so far, oldest first. "Model:" is you, and "Kernel:" is the operating system saying what happened. The person has typed nothing since. ...
Kernel: I am asking the model to make "a dice that rolls".
Kernel: the model wrote an app of 4 lines. It is shown in the terminal.
Kernel: the app ran to its end.
Kernel: the app left this on the screen: "Dice: 4".
```

- **Why a written record here too,** and not the tool's result as a message of its own, the way the model's maker shows it: that way needs the model's thinking (`reasoning_content`) sent back with every later request, which the provider's description of a message has no place for (see "What the model remembers" below). An ask in the shape of the first has been answered by the real model. One paid try would show whether the provider passes the model's thinking on.

## What the model remembers

The model keeps nothing from one request to the next: whatever it should know of what was said before has to go with every request. So the kernel remembers the last lines that went to the model and what came of each, and sends them with every new line, as a written record behind the instruction text (`conversation.rs`). That way a line that only makes sense after the one before it, such as `make it roll two dice`, can be understood.

- **What is remembered:** each line that went to the model, as it was sent, as a row that begins with `Person:`, never with the person's name; and behind it the rows its answer brought, as the chat box said them: the model's words (`Model: ...`) and the kernel's own sentences (`Kernel: ...`), such as what a tool did, how an app's run went, or why no answer came. The rows of the answer to the request for an app, and of every ask about the line again, belong to the line too, and so does what an app left behind when it went back to the model (see above), which the chat box does not say. The tool the model asked for is not remembered as such: the kernel's sentence about it says what it was and what came of it.
- **What is not:** the lines `key` and `setup`, and everything typed or said in answer to the kernel's questions (a secret, a key, a password, a name, the number of a look); the rows at the start (the greeting, the line from before the last switch-off); the row said at once, `Kernel: I am asking the model.`; a line turned away at once (no key, no address, an answer still awaited); and the terminal's lines (the tokens, an app's script and what it prints).
- **When:** a line is remembered when the answer to it comes back from the network's task, whatever that answer says (`conversation_line`), and the rows that `chat_say` and `model_say` say from then on belong to it (`conversation_row`), until the answer to the next line comes. The answer to another ask about the same line adds to it (`conversation_again`), and that ask goes with the record of the lines before it and the line's own rows apart (`conversation_split`). A line for which no request was put together, because the machine has lost its address, is not remembered; nor is a line whose answer comes after `setup` was sent, since it belongs to what `setup` forgot.
- **The key:** a piece of the key in the line is starred before the line goes, as in the provider's answer (`key_hide` in `model.rs`; see [model.md](model.md)), and the line is remembered as it went; the record is starred again before it goes. On the screen, in the terminal and as the last line in the notebook, the line stays as it was typed.
- **How much:** the last 10 lines (`LINES_REMEMBERED`), each with what came of it, and never more than 8,000 bytes (`BYTES_REMEMBERED`) for the rows together, each with a line end; the oldest lines go first. A line and what came of it take from some tens to a few hundred bytes in a usual chat. A line asked about once takes at most 960 bytes (a line of 50 signs, the model's words cut at 300, an answer cut off, two tools, a request for an app of 45 signs and the refusal of that request with 300 signs of reason), so that 8 such lines fit. A line asked about three times can take more, at most about 2,750 bytes (in each of the first two answers words cut at 300, the answer cut off and not whole, two tools, and a new app that stopped at a mistake after it showed 40 signs, with the interpreter's line of 200; in the last, words and a tool), so that 2 such lines fit, and the newest line always does.
- **How long:** until the machine is switched off; nothing of it is written to the disk. The tool `forget` (above) and the line `setup` forget everything, `setup` because another person may be at the machine then. The line `key` changes nothing about it.
- **How it goes:** behind the instruction text, in the same system message, after `RECORD_LEAD`, one row to a line, oldest first. The line itself stays the user message. Nothing more is sent when nothing is remembered. After the line `I would like a dice to roll` made an app:

```text
...and make_app only when none fits.

What was said before the newest line, oldest first. "Person:" is the person at the machine, "Model:" is you, and "Kernel:" is the operating system saying what happened.
Person: I would like a dice to roll
Kernel: I am asking the model to make "a dice that rolls".
Kernel: the model wrote an app of 9 lines. It is shown in the terminal.
Kernel: the app ran to its end.
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
- what is remembered goes to the provider again with every line, and is paid for each time: a row goes up to 10 times. A usual record of 10 short lines is about 2,000 bytes, roughly 500 tokens, the tool `forget` (360 bytes) some 100 to 150 more, and the instruction text's sentence about it some 25 with every line; at the full price that is about 0.01 cent more per line, so that a line costs about 0.02 cent instead of about 0.01, twice that in the busy hours. The record changes the beginning of the request at every line, so the part the provider counts as repeated may be smaller than before; how much is not known;
- the most a line can cost is set by the limits: 1000 tokens of answer at the busy price, about 0.12 cent, and the request with it, which the full record of 8,000 bytes, about 2,000 tokens, makes up to about 0.06 cent dearer;
- a new app adds its own request: at most about half a cent (see [apps.md](apps.md)). Nothing remembered goes with it;
- each ask about a line again is another request with everything remembered and the line's own rows: about 0.03 cent and a few seconds. A new app always brings one, so `make a dice that rolls` costs about 0.55 cent instead of about 0.52; `roll the dice` with a kept dice brings none. The model does not keep its thinking from one ask to the next, so it may think again, which is paid as answer;
- at the most, a line is three asks and two apps, every answer at its limit, about 1.6 cent in the busy hours, and each request may wait a minute, so about five minutes, while every other line is turned away.

The token line in the terminal shows what each answer really took, and how much of the request was repeated.

## How to test it

- **Against the stand-in for the provider** on the test computer (`model_server.py`, with the answers of `chat_cases.py` for a line), never against the real provider. Every request the stand-in gets is written down whole, and compared with what this page says is sent: the instruction text word for word, the line, the tools for what the disk holds, the limit, and nothing more.
- **Work out what the kernel should say from this page, apart from the kernel's code** (`chat_tools_model.py`), and compare every row, every token line, and every dot of the screen.
- **Feed it what a model may send:** words; each tool; a tool behind a thinking text full of quotes, brackets and line ends; words and a tool; two tools; a tool the kernel does not have; an odd name; inputs that are not JSON, missing, or too long; numbers as text, and numbers that fit nothing; requests that are long, odd, empty, or hold the key; an answer cut off, one spent on thinking, a refusal, and a good answer without words or a tool.
- **The thing this part is done by:** a line asks for an app in other words, the app is made, runs and is kept; after a restart, `roll the dice` runs the kept app, the stand-in gets one request only, and nothing new is written on the disk.
- **What is remembered,** against the stand-in: `I would like a dice to roll`, then `make it roll two dice`, which must go with the first line and what came of it, and nothing else; and every request of a scenario compared whole with the request worked out from this page by a model of what is remembered (`conversation_model.py`), kept apart from the kernel's code. What must never be remembered is sent on purpose: a name kept and a key unlocked with a password, the line `key` and its secret, a line that holds the key, a line turned away while an answer is awaited, the tool `forget`, `setup`; and every request is searched for the name, the password and any piece of the key. The bounds: twelve short lines, of which the twelfth goes with the ten before it; then lines with the longest rows, until the bytes and not the count decide what goes.
- **What goes back,** against the stand-in (scenario `rounds`): a new app that stops at a mistake goes back with the interpreter's line, and the model's fix, a new app asked for in other words, is made, runs, is kept and goes back too, and the third ask, without tools, is answered in words; a model that keeps asking (a look that is not there, a page that is not there, and a tool again in its last answer) gets three asks, the last without tools, and its last tool is not done; a look that is picked does not go back; two tools at once go back, and the first asked for again is not done twice; an ask again that the provider turns down is said, and ends the line; an app that puts the key together out of pieces and shows it goes back starred, and stays starred after another key is given; `setup` while a new app is awaited ends the asks. Every request is compared whole with the request worked out from this page. The stand-in answers an ask about a line again with words of its own unless a scenario says otherwise, so that the other scenarios keep their lists.
- What only the real model can show: whether it picks `run_app` over `make_app` for a wish that fits a kept app, whether its tool calls have the shape the documentation gives, whether it understands a line by the record of what was said before it, and whether, asked about a line again, it says what came of it and stops, or fixes an app that stopped. A person's own paid run was the first real test of the tools, and they said it worked; nothing of it was watched (see [testing.md](testing.md)).

## Limits

See "Every line to the model" in [open-points.md](open-points.md). In short: every line is a paid question that needs the network and takes seconds; the model sees the last 10 lines and what came of them, until the machine is switched off, and everything it sees is sent again with every line; only the first tool is done, and what it did goes back to the model in the same line only when it needs the model, at most twice; every kept app makes every request longer; the model may pick the wrong tool, and nothing checks its choice.
