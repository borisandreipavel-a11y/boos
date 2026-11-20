# The tools: what the kernel does when the model asks

Code: `src/tools.rs`; the request and the reading of the answer in `model_chat` and `chat_reply` in `src/model.rs`; the line's way there and back in `model_ask` and `chat_answer` in `src/chat.rs`.

Every line sent in the chat box goes to the model, except the two lines the kernel keeps for itself, `key` and `setup` (see [chat.md](chat.md)). With the line goes a list of **tools**: the things the kernel can do, each with a name, one sentence, and what it needs to be told. The model answers in words, or asks for one of the tools; the kernel then does it and says in its own plain sentence how that went. What the tool did does not go back to the model: there is one request per line, and one more only when the model asks for a new app.

## The words

- A **tool** is something the kernel can do when the model asks for it, described to the model in a few words: its name, a sentence about what it does, and its **inputs**, each with a type. The provider's documentation calls the list `tools`, and a model's request to use one a tool call.
- The **inputs** are what the model gives the tool, as a small piece of JSON, such as `{"app": 1}`.
- A **token** is a piece of a word, about three quarters of one; the provider is paid by the token (see [model.md](model.md)).

## The request

A line goes to the provider like every question (see "The request" in [model.md](model.md)), with this body, shortened here:

```text
{"model":"deepseek/deepseek-v4.1-flash-1017","messages":[{"role":"system","content":"You are the voice of ..."},{"role":"user","content":"roll the dice"}],"tools":[{"type":"function","function":{"name":"make_app",...}},...],"max_tokens":1000,"stream":false}
```

- **The instruction text** (`CHAT_INSTRUCTIONS`), as the system message, every time, word for word: "You are the voice of a small home-made operating system. The person at the machine types one line at a time into its chat box, and you see only that line, not the ones before it. Answer in plain words, in one or two short sentences, or use one of the tools when the person wants something done that a tool does. Use run_app for a kept app that fits the wish, and make_app only when none fits." It names no project and no person.
- **The line**, exactly as it was typed, as the user message.
- **The tools**, in this order: `make_app` always; `run_app` while any app is kept; `pick_look` always; `turn_page` while the panel of apps has more than one page. The list is made by the main loop when the line is sent (`chat_tools`), because only the main loop may read the kept apps, and it travels to the network's task with the errand (`Errand::ChatLine`).
- **1000 tokens at most** for the answer (`ANSWER_TOKENS`), as for the fixed question; a model that thinks pays its thinking out of them.
- **Nothing else is sent:** no `tool_choice`, no `parallel_tool_calls`, no `strict`, and nothing about thinking. Each would be a risk that only a paid request could show: the model's maker says that `tool_choice` set to `required` or to one tool gives a 400 while the model thinks, and its reference does not list `parallel_tool_calls`; the provider's documentation does not say what `strict` does.
- **Its size:** about 1,500 bytes with no app kept (1,529 for the line `roll the dice`). The first kept app adds the tool `run_app`, some 330 bytes, and each further app its number and request in its sentence and its number in the list of numbers, some 20 to 60 bytes.

## The four tools

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

## The answer

- **Where the kernel looks,** from the provider's documentation and the model's maker's: the model's words at `choices`, the first of them, `message`, `content`, as for every answer; a tool it asks for at `choices`, the first, `message`, `tool_calls`, the first, `function`, with the tool's `name` and its inputs at `arguments`, a text that is itself JSON. Whether a second tool call stands there is only looked at.
- **The model's words** are said as a row of their own that begins with `Model:`, so that they cannot be taken for the kernel's own sentences: cleaned like every text from outside, the key hidden, cut at 300 signs. Words and a tool may come together: the words first, then the tool is done.
- **Only the first tool is done.** When the model asks for more than one, `Kernel: the model asked for more than one thing at once, so I do only the first.` comes before it.
- **What the model asks for comes from outside, and is checked before anything is done:**
  - only the four names above count: any other gets `Kernel: the model asked for something I cannot do: "...".`, with the name cleaned and cut at 64 signs;
  - the inputs are held to 1,024 bytes (more counts as none), the key is hidden in them, and they are read with the JSON reader, which takes nothing on trust; the model's maker warns that its model does not always write sound JSON there;
  - a number may come as a number or as a text of digits alone;
  - inputs that cannot be read get a row of their own, such as `Kernel: the model asked to run a kept app, but I could not read which one.`;
  - a request for an app is cleaned byte by byte like every text from outside (every byte that is not a plain sign becomes a dot), spaces at either end go, and it is cut at 45 signs, before it is shown, sent on, or kept; an empty one gets `Kernel: the model asked for an app, but did not say what it should do.`
- **An answer cut off or held back** is said after the words: `Kernel: the model's answer was cut off at the limit of 1000 tokens.` A good answer with neither words nor a tool is said as for the fixed question: empty (with the reason, such as `because it spent all of its 1000 tokens thinking`), or, if its shape is not the documented one, with its first 160 signs. Any other answer (a refusal, a mistake on the provider's side, no answer) is said as for the fixed question (see [model.md](model.md)).

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
- the most a line can cost is set by the limit: 1000 tokens of answer at the busy price, about 0.12 cent, and the request with it;
- a new app adds its own request: at most about half a cent (see [apps.md](apps.md)).

The token line in the terminal shows what each answer really took.

## How to test it

- **Against the stand-in for the provider** on the test computer (`model_server.py`, with the answers of `chat_cases.py` for a line), never against the real provider. Every request the stand-in gets is written down whole, and compared with what this page says is sent: the instruction text word for word, the line, the tools for what the disk holds, the limit, and nothing more.
- **Work out what the kernel should say from this page, apart from the kernel's code** (`chat_tools_model.py`), and compare every row, every token line, and every dot of the screen.
- **Feed it what a model may send:** words; each tool; a tool behind a thinking text full of quotes, brackets and line ends; words and a tool; two tools; a tool the kernel does not have; an odd name; inputs that are not JSON, missing, or too long; numbers as text, and numbers that fit nothing; requests that are long, odd, empty, or hold the key; an answer cut off, one spent on thinking, a refusal, and a good answer without words or a tool.
- **The thing this part is done by:** a line asks for an app in other words, the app is made, runs and is kept; after a restart, `roll the dice` runs the kept app, the stand-in gets one request only, and nothing new is written on the disk.
- What only the real model can show: whether it picks `run_app` over `make_app` for a wish that fits a kept app, and whether its tool calls have the shape the documentation gives. A person's own paid run was the first real test, and they said it worked; nothing of it was watched (see [testing.md](testing.md)).

## Limits

See "Every line to the model" in [open-points.md](open-points.md). In short: every line is a paid question that needs the network and takes seconds; the model sees one line, not what was said before; only the first tool is done, and what it did is not told to the model; every kept app makes every request longer; the model may pick the wrong tool, and nothing checks its choice.
