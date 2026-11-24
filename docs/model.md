# Asking the model

Code: `src/model.rs`; the lender of the key in `src/secret.rs`; the general exchange with a site in `src/page.rs`; the lines of the chat box in `src/chat.rs`. A line typed in the chat box and the request for an app go through the same file; see [tools.md](tools.md) and [apps.md](apps.md).

A model is a program that answers a question put to it in words. This kernel does not run one. It asks one over the internet, through a provider: a service that takes a question, passes it on to a model, and sends the model's answer back. The provider wants a key with every question, which says who is asking and who pays. The key is the secret that the person at the machine types into the chat box: after the line `key`, for one start, or when the onboarding asks for it, which tries it with the question below, locks it with a password and keeps it on the disk, and unlocks it again at every start with that password (see [chat.md](chat.md)).

## What it does today

Three kinds of question go to the model, each with the kept secret as the key:

- **Every line typed in the chat box,** but `key` and `setup`, with the list of what the kernel can do for it and the record of what was said before it (`model_chat`; see [tools.md](tools.md)). The model answers in words, or asks for one of the tools. When what a tool did needs the model, the same line goes again, with what came of it. Its answer is asked for piece by piece, as the model writes it, and its words show in the chat box as they come (see "An answer piece by piece" below).
- **A request for an app,** when the model asked for a new one (`model_app`; see "Asking for an app" below and [apps.md](apps.md)).
- **One fixed question,** `Say hello in five words.` (`QUESTION`), with which a key typed at the onboarding is tried (`model_tell`; see "Trying a key" below). The line `ask`, which once asked it from the chat box, is an ordinary line now, and goes to the model like any other.

Every answer is read the same way; only what the kernel does with the model's words differs. `model_tell` gives back one sentence, and so do the other two when something went wrong:

| The sentence | When |
|---|---|
| `the model answered "..."` | The provider's answer carries the number 200 and the model's words were found in it |
| `the model answered "...", but it was cut off at the limit of 1000 tokens.` | The same, and the answer says it ended because it reached the limit (`length`) |
| `the model answered "...", but the provider held part of it back.` | The same, and the answer says the provider's filter ended it (`content_filter`) |
| `the model's answer was empty.` | The number 200, and the model's words are an empty text, spaces only, or `null`. A reason is added when the answer gives one: `, because it spent all of its 1000 tokens thinking` (it reached the limit and has thoughts beside its words), `, because it reached the limit of 1000 tokens`, or `, because the provider held it back` |
| `the provider turned the question down (401): "..."` | Any other number that is not from 500 to 599; the words are the provider's reason. 401 is what a key it does not know gets, 402 used-up credit, 404 a model it does not know, 429 too many questions |
| `the provider could not answer (502): "..."` | A number from 500 to 599: the trouble is on the provider's side or the model's. Asking again later may work |
| `the provider ... (N), and I could not read why.` | Either of the two above, with a body that is not JSON with a reason in one of the three places looked at |
| `the provider answered, but I could not find the model's words in its answer, because ... It begins "...".` | The number 200, with a body that is not sound JSON or does not hold the words where they are looked for. The first 160 signs of the body are said (`BEGINNING_SHOWN`), cleaned and with the key hidden, so that an answer of another shape than the documentation describes can be seen without asking again |
| `no answer came that I could read, because ...` | What came does not begin as an answer on the web does, or is larger than the room for it |
| `no answer came, because ...` | Nothing came: no name server, no key, a link that could not be made, a certificate that was refused, a provider that stayed silent |

` Its answer did not come whole.` is added when the provider did not say, through the encrypted link, that it had sent everything.

## Trying a key

A key typed at the onboarding is tried before it is kept: the network's task runs the errand `Errand::KeyTry`, which calls `model_tell` with `trying` set. The request is the fixed question, byte for byte as the line `ask` once sent it, with the key being tried in place of the kept one, and the sentence it gives back is the same too. Beside the sentence, `model_tell` says how the provider took the key (`KeyVerdict`), from the number in the first line of its answer only, never from its words:

| `KeyVerdict` | When | What the onboarding does |
|---|---|---|
| `Works` | 200: the question was answered | keeps the key |
| `Unknown` | 401, with or without a reason that can be read. The provider's documentation gives 401 for a key that is missing, wrong or past its expiry date | wipes the key and asks for it again |
| `Known` | 402 or 403 with the provider's reason in its JSON. Its documentation gives 402 for an account without credit, and 403 for a key held back by a limit of its own (a quota, a spending limit, a model it may not use, the addresses it may come from) | keeps the key |
| `NotTold` | anything else: another number, a 402 or 403 without the provider's reason (a page from somewhere on the way), no answer, or one that cannot be read | keeps the key |

A 200 whose body the kernel cannot read still counts as `Works`: the answer came from the provider's own site, whose certificate was checked, and it took the key. What the onboarding says to each is in [chat.md](chat.md).

## The provider and the model

- There are two providers, one in use at a time, chosen at the onboarding (see "The provider" in [chat.md](chat.md)): OrcaRouter, and Anthropic (see "Anthropic" below). `Provider` in `model.rs` names them; each key is kept and lent together with the provider it belongs to (see "The key" below), and that decides the site, the form of the request and the reading of the answer. Everything else in this file is the same for both.
- OrcaRouter is a service that passes questions on to many models. Its site is `api.orcarouter.ai` (`MODEL_SITE`), and questions go to the place `/v1/chat/completions` on it (`MODEL_PATH`).
- The model asked there is `deepseek/deepseek-v4.1-flash-1017` (`MODEL_NAME`), the name the provider knows it by.
- These are constants in `model.rs`. Another provider or another model means changing them, and reading that provider's documentation first.
- OrcaRouter's request and answer have the form that many providers share, named after the first service that used it ("chat completions").
- Everything here about the provider's side was read in its documentation in November 2026 and seen in one real answer; read the documentation again before changing the request.
- What is typed as a question goes to the provider, and from there to the maker of the model. The provider also keeps a record of each request.

## The request

One request per connection, over an encrypted link whose certificate was checked for the provider's name. It is put together like this, here for the fixed question; a line typed in the chat box and a request for an app differ only in the body (see [tools.md](tools.md) and "Asking for an app" below):

```text
POST /v1/chat/completions HTTP/1.0
Host: api.orcarouter.ai
Content-Type: application/json
Content-Length: 144
Connection: close
Authorization: Bearer <the key>

{"model":"deepseek/deepseek-v4.1-flash-1017","messages":[{"role":"user","content":"Say hello in five words."}],"max_tokens":1000,"stream":false}
```

- `POST` hands something in at the place named behind it. The lines after it are notes: which site is meant, what form the body has, how many bytes long it is, that the connection may be closed after the answer, and the key. An empty line ends the notes, and the body follows.
- The body is JSON. The two texts in it are written with `json_text` (see [json.md](json.md)). `max_tokens` is the longest answer the model may give (`ANSWER_TOKENS`, 1000); models count in tokens, which are pieces of words. A line typed in the chat box has a limit of its own, 4000 (`LINE_TOKENS`), with room for a table it describes (see [tools.md](tools.md)). The model can think before it answers (its page at the provider says it has a thinking and a non-thinking way, and not which it takes when nothing is said), and thinking may be paid out of the same tokens, so the limit leaves room for far more than a five-word answer. The provider is paid by the token used, not by the limit: at the model's prices in November 2026 (0.60 dollars a million tokens out, twice that in the provider's busy hours) the whole limit would cost about a tenth of a cent.
- `"stream":false` asks for the whole answer in one piece. The provider's documentation does not say what it does when nothing is said; sent word by word, the answer would not read as JSON. A line typed in the chat box asks for the other: `"stream":true,"stream_options":{"include_usage":true}` behind `max_tokens` (see "An answer piece by piece" below). The try of a key and the request for an app still ask for the whole answer.
- Nothing is sent to choose thinking or not. The model's page at the provider now lists `reasoning_effort` among the settings it takes, and the model's maker says its model thinks unless told not to, but neither says which values the provider passes on for this model; a value it does not take could make it refuse every question. The terminal's line about the tokens of each answer to a line or an app shows how much went on thinking (see [tools.md](tools.md)).
- The length note counts bytes, not signs.
- `HTTP/1.0` and `Connection: close` ask the provider to close the connection after its answer, which is how the kernel knows the answer is over.

## The answer

A real refusal looked like this (the long number is the provider's own name for the request):

```text
HTTP/1.1 401 Unauthorized
Date: ...
Content-Type: application/json; charset=utf-8
Content-Length: 133
Connection: close
(six more notes)

{"error":{"code":"","message":"Invalid API key (request id: ...)","type":"orcarouter_api_error"}}
```

- The whole answer is collected, up to 64 KB (`ANSWER_ROOM`). A longer one is not read at all. The answer to a line whose notes say that it comes piece by piece is not collected, but read as it comes (see "An answer piece by piece" below); one that comes whole all the same is read as here.
- `answer_parts` takes it apart: the number is the three digits behind the first space of the first line, which must begin with `HTTP/`; the notes are passed over up to the empty line; the rest is the body.
- With the number 200 (`model_sentence`), the model's words are looked for in the body at `choices`, the first of them, `message`, `content`. If what stands there is not a text, the first piece of a list there is tried (`content`, first, `text`): the provider's documentation allows the words as a list of pieces. The places are from the provider's documentation, and a good answer from the real provider was read from them (see "What the real question showed").
- How the answer ended is read at `choices`, the first of them, `finish_reason`. Two values are told apart, `length` (the limit of tokens was reached) and `content_filter` (the provider held something back); any other value, or none, counts as an ordinary end. The value is compared and never said, so whatever stands there cannot reach the screen.
- Spaces and line ends before and after the words are taken off. Words that are then empty, or a `null` where the words belong, make the sentence "the model's answer was empty". A `null`, or no words at all, counts only if `finish_reason` was read as a text: the JSON reader checks that the rest of the answer closes properly only when it hands out a text, so a damaged answer is not taken for an empty one.
- A model that thinks may send its thoughts beside its words, at `reasoning_content` or `reasoning` (the provider's documentation names the first; the second is the other common name). They are not shown as words; they are only looked at to say "it spent all of its tokens thinking" when the answer is empty and reached the limit. The one place where they can appear is the beginning of an answer whose words cannot be found, which is said as it is.
- With any other number, the reason is looked for at `error` then `message`, then at `error` as a text, then at `message`. A number from 500 to 599 is "the provider could not answer", any other "the provider turned the question down". The provider's page for the model gave an error rate of about 5 in 100 over a week in November 2026, so a 502 or 503 now and then is to be expected.
- The words are cleaned like every text from outside (`plain_text`) and cut at 300 signs (`WORDS_SHOWN`). Only the signs that are said, and as many behind them as the key is long, are cleaned and searched for the key: a piece of the key that begins among the signs that are said ends among those.
- The reader takes bytes from outside, so it reads them with `get` and the JSON reader's rules; see [json.md](json.md). 11,499 damaged and made-up answers were put through it; see [testing.md](testing.md).
- An answer sent in pieces with their lengths in between (the web calls it "chunked") is not put together again: its body does not read as JSON, and the sentence is "I could not read why". The provider did not answer that way.

## An answer piece by piece

The answer to a line typed in the chat box is asked for piece by piece, as the model writes it (`"stream":true`), so that its words can show in the chat box as they come (see [chat.md](chat.md)). What the provider and the model's maker say about such an answer was read in their documentation in November 2026. A person's own run with the real provider then showed it working over this kernel's link (see "What the first answers in pieces showed" below).

- **How it comes**, from both documentations: the notes say `text/event-stream` and give no length; behind them comes one line for each piece, `data: ` and a piece of JSON, with an empty line after it, and the line `data: [DONE]` at the end. The model's maker also sends lines that begin `:` (`: keep-alive`) while a question waits to be taken up. A piece holds a little at `choices`, the first of them, `delta`: some of the model's words (`content`), some of its thinking (`reasoning_content`, or `reasoning`), or a part of a tool it asks for (`tool_calls`: the first part of a tool names it, the parts after it bring pieces of what it gives the tool, each with the tool's place in the list at `index`); the last says how the answer ended (`finish_reason`). With `"include_usage":true` the last piece before `[DONE]` holds the counts of tokens (`usage`): the model's maker puts them in the last piece with words, the provider's documentation in a piece of their own with an empty list of choices. A piece with `error` in it says that the provider broke the answer off; `[DONE]` may still follow it.
- **The link:** neither documentation says anything about the web's versions, about pieces with their lengths in between, or about holding an answer back. The web's rules (RFC 9112, sections 6.1 and 6.3) say that a server must not send pieces with their lengths in between to a request in `HTTP/1.0`, and that an answer with neither a length nor such pieces ends when the server closes the connection, which the kernel already reads. Whether the provider passes the pieces on as they come to a request in `HTTP/1.0`, or holds them back until the end, is said nowhere, and nothing free can show it: a made-up key is turned down before any piece comes. The terminal's line about the pieces (below) shows it in the first paid run.
- **How the kernel reads it** (`provider_exchange` and `Stream` in `model.rs`): the head of the answer is read as it comes, by the same reader as a file's (`HeadReader` in `page.rs`). A good answer (200) of the kind `text/event-stream` is read piece by piece; any other answer is collected whole and read as above. The lines are taken however the pieces are cut, a line end with or without byte 13 before it; a line of more than 64 KB (`PIECE_ROOM`) stops the reading. Lines that begin `:`, empty lines and any line but `data:` are passed over. Each piece is read with the JSON reader, at the places above: the words are added up, from the first sign that is not a space, up to 16 KB (`WORDS_KEPT`); thinking is only noted; the parts of the first tool asked for are put together, up to 8,193 bytes of what it gives the tool (the largest bound, `write_document`'s, and one byte more), and of any other tool only that it is there counts; the last word on how the answer ended and the last piece with counts are kept. `[DONE]` ends the reading: the kernel says goodbye through the encrypted link at once, whether the provider closes the connection or not.
- **Handed on as it comes:** after each piece of the answer that arrives, the network's task leaves what of the words can be shown so far, and whether the model is thinking before its first word, for the main loop to paint (`errand_grow` in `errand.rs`). What can be shown is cleaned and starred as the words said at the end are, but without the last signs, one fewer than the key is long: a piece of the key that a sign shown belongs to then lies whole among the signs that came, and is starred; a piece that only begins among the last signs waits for the rest. At most 300 signs show, as at the end.
- **When it is over,** what came is said as for an answer that came whole (`stream_reply`): the words, cleaned, starred and cut at 300 signs; the first tool, held to its bound as above (`tool_made`, shared with the answer that comes whole); and the same sentences for an answer cut off at the limit, held back, empty, or of another shape, whose beginning is then said from the first bytes of the pieces. The answer is whole when `[DONE]` came after no piece that broke it off. The terminal's line about the tokens comes from the piece that held the counts.
- **An answer that broke off** says what came of it and why: `the model's answer broke off before it was whole.` when the connection ended, or the minute ran out, before the model said how it ended; `the model's answer broke off, because ...` when the link went wrong after the pieces had begun, with the reason; `the provider broke the model's answer off: "..."` for a piece that broke it off, with the provider's reason (or `, and I could not read why`); `the provider stopped the model's answer before its end.` when the model's maker's word for how it ended is `aborted` or `insufficient_system_resource`; and `the model's answer broke off, because a piece of it is larger than the room for it.` for a line too long. The words that came are said before it. A tool asked for in it is not done, and `, so I did not do what it asked for` is said; a table is the one tool that is still done, with the rows that came whole (see [tools.md](tools.md)). An answer that ended as the model said, but without `[DONE]`, is not whole and is said as above: `the provider's answer did not come whole.`
- **Pieces with their lengths in between** are not read: `no answer came that I could read, because the provider sent its answer in pieces with their lengths in between ("chunked"), which it should not for this kind of request`.
- **The wait** is the same minute as for every question (`MODEL_WAIT`), for the greeting and the whole answer together. What came before the minute ran out is kept now, and said, where an answer that came whole brought nothing.
- **In the terminal,** after the answer's rows, one line says how the pieces came, counted from the asking in hundredths of a second: `Stream: 57 pieces in 3.92 s: the first after 0.81 s, thinking from 0.81 s, words from 2.90 s, a tool from 3.10 s to 3.80 s, 2 lines that the link is alive, the end mark after 3.92 s.` (made-up numbers), with `no end mark` when `[DONE]` did not come. Pieces that came spread out over the seconds show that the provider passes them on as they come; pieces that all came within a hundredth or two would show that it holds them back.
- **What the first answers in pieces showed** (a person's own run, two lines, the terminal's lines about the pieces read from a picture of their terminal): the provider took `stream` and `stream_options` for this model, and passed the pieces on as they came, to a request in `HTTP/1.0`. A short answer: `45 pieces in 1.55 s: the first after 1.05 s, thinking from 1.07 s, words from 1.25 s, the end mark after 1.55 s.`, the counts with it (`125 out, 60 of them thinking`), so its thinking came in pieces too, and its words over three tenths of a second. A table: `131 pieces in 3.66 s: the first after 1.95 s, thinking from 1.97 s, a tool from 3.60 s to 3.66 s, the end mark after 3.66 s.` (`499 out, 361 of them thinking`), and the table was drawn from the tool's parts put together. So most of the wait is the thinking before the first word, and a tool's parts come within a few hundredths of a second of each other; no line that only says the link is alive came in either.
- **The cost** is the same as for an answer that comes whole: both documentations bill by the tokens, and name no other price for an answer in pieces. What changes is the bytes on the way: every piece repeats some notes around the few words it holds (some 200 bytes, an estimate from the model's maker's example), so a long answer is many times the bytes it would be whole, which the kernel reads and drops piece by piece. Whether tokens written before an answer broke off are paid for is said in neither documentation.

## The key

- **Only this file can borrow it.** `secret_lend` in `secret.rs` runs a short piece of code with the key in hand. It asks for a pass, `KeyPass`, whose inside is private to `model.rs`, so no other file can make one: a call from anywhere else does not build. (The disk's `WriteTicket` works the same way; see [disk.md](disk.md).) A key being tried is lent the same way, by `trial_lend`, from a room of its own beside the kept one. The one other way the key leaves `secret.rs` is locked, by `secret_lock`, for the onboarding; a key unlocked by `secret_unlock` goes straight into its place there (see "A secret" in [chat.md](chat.md)).
- **It is borrowed once for each asking.** `model_tell` copies the key into a room of its own, and that copy serves the whole asking: it goes into the request, and it is what is looked for in the answer afterwards. A new key typed while the answer is awaited changes nothing about the asking under way. The room is wiped before `model_tell` ends.
- **It goes to one site: its own provider's.** `key_copy` is the only borrower, and it takes the key and the provider it belongs to in the same moment (`secret_lend` hands over both, with device signals off). The provider gives the site, which serves for the name question, the certificate check and the request's `Host` alike, and the note the key goes in. With a certificate made out to another name, the link fails before the request is sent. A `setup` that picks another provider wipes the key in memory at once (see "The provider" in [chat.md](chat.md)), so no key can reach the other provider's site.
- **The request is wiped.** It is put together in a room that is large enough from the start, so that it never moves and leaves a copy behind, and the room is wiped after the exchange, however it went. After requests whose answers did not repeat the key, a test machine's memory held the key once, in the room where it is kept.
- **The key is kept out of what is sent, too.** It goes in the notes of the request only. A piece of it in a line typed in the chat box, or in the record of what was said before the line, is starred before the request is put together (`key_starred`, with `key_hide` below), and the line is remembered as it went (see "What the model remembers" in [tools.md](tools.md)). On the screen, in the terminal and as the last line in the notebook, the line stays as it was typed.
- **The key is kept out of what is said.** A provider may repeat the key in its refusal; when a key is tried, the key looked for is the one being tried. Words that came from the provider go through `words_shown` before they are said: cleaned, then `key_hide` writes a star over every run of signs that stands in the key and is six signs long or longer (`KEY_PIECE`), or over the whole key if it is shorter, and only then cut at 300 signs, so that the cut cannot leave the beginning of the key standing. The kernel's own words in the sentence are not searched, so a key that happens to be an ordinary word does not put stars into them.
- **Two tasks reach the secret now:** the main loop keeps it, the network's task borrows it, and the same holds for a key being tried. Every function of `secret.rs` touches them with device signals off; borrowing is short, because the borrower only copies.

What is not kept out: see "Asking the model" in [open-points.md](open-points.md).

## The general exchange

`site_exchange` in `page.rs` is the fetch of a page made general: it is given the site, the request and how long to wait, and hands every piece of the answer to a piece of code of the caller's. It looks the name up, connects, has `secure_exchange` make the encrypted link, and ends the connection. The page fetch and the question to the model both go through it; see [network.md](network.md).

The wait for the greeting and the answer together is 60 seconds here (`MODEL_WAIT`), against 15 for a page: a model needs longer than a site.

## What the first contact showed

One question was sent to the real provider with a made-up key.

- The provider takes the kernel's link as it is: TLS 1.3 with the one curve this kernel offers, and its certificate leads back to one of the trusted roots.
- It takes a request in `HTTP/1.0` form and answers with the whole body and its length, not in pieces, and closes the connection with a proper goodbye.
- The refusal came 1.4 seconds after the asking.

## What the real question showed

The real question was then asked with a real key, in a person's own run, and the chat box showed `Kernel: the model answered "...".`

- So a good answer comes through the kernel's link too, within the minute the kernel waits, and the model's words lie where the provider's documentation says.
- Nothing more of that run is known: not the words, not how long the answer took, not whether the model thought first or how many tokens it used. A run with a real key is not watched, and the raw answer is not printed, so its exact shape was not seen.

## Anthropic

The second provider, Anthropic, makes the model it is asked about. Everything here was read in its documentation (platform.claude.com, November 2026): the message request, streaming, errors, versions, thinking, tool use, prices.

- **Its site** is `api.anthropic.com` (`ANTHROPIC_SITE`), and questions go to `/v1/messages` (`ANTHROPIC_PATH`). The model is `claude-haiku-5-5` (`ANTHROPIC_MODEL`), its smallest and fastest; every model name of Anthropic's is a fixed snapshot.
- **The request** is today's, in Anthropic's words. The key goes in a note of its own, `x-api-key`, behind the version of the form, which every question must name (`anthropic-version: 2026-10-21`, `ANTHROPIC_VERSION`; that version takes no `temperature`, `top_p` or `top_k`, which the kernel never sends):

  ```text
  POST /v1/messages HTTP/1.0
  Host: api.anthropic.com
  Content-Type: application/json
  Content-Length: 127
  Connection: close
  anthropic-version: 2026-10-21
  x-api-key: <the key>

  {"model":"claude-haiku-5-5","max_tokens":1000,"messages":[{"role":"user","content":"Say hello in five words."}],"stream":false}
  ```

  A line's request holds the same texts as OrcaRouter's in other places: the instruction text, the open document, the record and what came of the line so far are one part of their own (`system`), beside one message, the line; each tool is written as its name, its sentence and its schema (`input_schema`), without OrcaRouter's wrapper around them (`tools_anthropic` in `tools.rs`); the answer is asked for piece by piece (`"stream":true`), and always brings its counts. The request for an app holds the text about apps as `system` and the request as the one message, whole. No `tool_choice` is sent (the model picks a tool or none), and nothing about thinking.
- **Thinking.** The model thinks when it sees fit, as much as its default effort (`medium`) lets it, when nothing is said; the tokens it thinks are paid as answer, out of the same limits (1000, 4000 and 4000). Its thinking comes back as a block whose text is left empty. Anthropic asks for thinking to be passed back only when a tool's result is returned in the same turn of the model's; this kernel never sends a turn of the model's back (what came of a tool goes into the instruction text), so nothing is passed back.
- **A good answer** holds a list of blocks at `content`, in the order the model wrote them: thinking, words (`text`), tools asked for (`tool_use`). They are read by their kind, never by their place. How it ended stands at `stop_reason`: `max_tokens` is read as the limit of tokens; `refusal` means the provider's checks stopped the answer, which is said (`the provider's checks stopped ...`) and keeps the answer's tool from being done, a table included, since such an answer may stop in the middle of what the model gives a tool; `model_context_window_exceeded` means the question and the answer grew larger than the model takes, said in a sentence of its own. A tool in an answer that came whole is not done: what the model gives it stands there as JSON of its own, which the JSON reader does not hand out as a text, and a line's answer comes piece by piece, as asked.
- **A refusal** has the same place for its reason as OrcaRouter's (`error`, `message`), so it is said in the same words, and the key's try reads it the same way: 401 (`authentication_error`) is a key Anthropic does not know; 402 (`billing_error`) and 403 (`permission_error`) with a reason, one it knows.
- **The answer piece by piece** comes in the same lines as OrcaRouter's, each piece behind a line `event:` that names it; the kernel reads the kind the piece names itself, at `type`. `message_start` holds the counts of the question; each block comes as `content_block_start` (its kind, and a tool's name), `content_block_delta`s (`text_delta`, a few words; `thinking_delta`; `input_json_delta`, a piece of what the model gives a tool, put together as OrcaRouter's are), and `content_block_stop`; `message_delta` says how it ended and holds the counts of the answer; `message_stop` ends it, where OrcaRouter's ends at `[DONE]`. `ping` only says the link is alive, `error` breaks the answer off as an error piece does, and a kind not named here is passed over (Anthropic may add kinds). Anthropic holds each part of what a tool is given back until it is whole and checked, and then sends it in pieces; what of a held part arrives when the answer reaches its limit was not seen.
- **The terminal's line about the tokens** is the same: the question's tokens are those counted afresh (`input_tokens`) with those read from, or written to, what Anthropic kept from an earlier question (`cache_read_input_tokens`, `cache_creation_input_tokens`), and those read back count as repeated; the answer's are `output_tokens`, of which `output_tokens_details`, `thinking_tokens` were thinking.
- **What it costs** (its price page, November 2026): $0.10 a million tokens of question and $0.50 of answer for questions up to 100,000 tokens, five times that for longer ones; the same at every hour. Tools add a hidden instruction of 286 tokens to every request. A usual line comes to about 0.04 cent (an estimate), about what OrcaRouter's costs when nothing counts as repeated. Caching a question's start is something Anthropic does only when asked, and the kernel does not ask.
- **What the first contact showed** (2026-11-23, from a computer with OpenSSL, set to offer only what the kernel offers, before the kernel's own; no key): the site takes TLS 1.3 with the curve P-256 and ChaCha20-Poly1305, and signs with ECDSA on P-256; its certificates lead through Google Trust Services' `WE1` to `GTS Root R4`, which is in the kernel's list of roots; a request in `HTTP/1.0` form with no key and no User-Agent was answered `HTTP/1.1 401 Unauthorized` with JSON, with no length and not in pieces with their lengths, and the connection was closed with a proper goodbye, about 1.5 seconds after the asking. Then the kernel's own (2026-11-24, a made-up key, from a copy of the project that only adds lines to its terminal): Anthropic chosen at the start, the key tried through the kernel's own link, and the try turned down: `Kernel: the provider turned the question down (401): "invalid x-api-key".`, then `the provider does not know that key, so I did not keep it.` and the question for the key again. Then a person's own run, with a key of their own: the key worked, a line's answer came piece by piece to the kernel's `HTTP/1.0` request, and a table and an app were made (see "Anthropic as a second provider" in [testing.md](testing.md)).

## Asking for an app

`model_app` asks the model to write an app, when the model asked for a new one with the tool `make_app` (see [tools.md](tools.md)), through the same exchange (`provider_exchange`) with the kept key, borrowed in the same way (`key_copy`). The request differs from the fixed question's in two places: the body holds two messages, a fixed instruction text first as the `system` message and then the request, and `max_tokens` is 4000 (`APP_TOKENS`). An answer that is not a good one is said word for word as for the fixed question. A good one is read as a script (`app_sentence`). [apps.md](apps.md) has the whole of it.
