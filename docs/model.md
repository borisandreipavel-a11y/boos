# Asking the model

Code: `src/model.rs`; the lender of the key in `src/secret.rs`; the general exchange with a site in `src/page.rs`; the line `ask` in `src/chat.rs`. The request for an app goes through the same file; see [apps.md](apps.md).

A model is a program that answers a question put to it in words. This kernel does not run one. It asks one over the internet, through a provider: a service that takes a question, passes it on to a model, and sends the model's answer back. The provider wants a key with every question, which says who is asking and who pays. The key is the secret that the person at the machine types into the chat box: after the line `key`, for one start, or when the onboarding asks for it, which tries it with the question below, locks it with a password and keeps it on the disk, and unlocks it again at every start with that password (see [chat.md](chat.md)).

## What it does today

The line `ask`, sent by itself in the chat box, makes the kernel ask the model one fixed question, `Say hello in five words.` (`QUESTION`), with the kept secret as the key, and say in the chat box what came back. The one other thing the model can be asked for is an app, with the line `make` (see "Asking for an app" below).

- Without a kept secret the chat box says `Kernel: I cannot ask the model, because no key is kept. Send the line "key" first.` and nothing is sent.
- Otherwise it leaves an errand for the network's task (see "Errands" in [tasks.md](tasks.md)) and says `Kernel: I am asking the model "Say hello in five words."`. The answer comes later, as a row of its own.
- The network's task runs the errand by calling `model_tell`, which gives back one sentence:

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

A key typed at the onboarding is tried before it is kept: the network's task runs the errand `Errand::KeyTry`, which calls `model_tell` with `trying` set. The request is the same as for `ask`, byte for byte, with the key being tried in place of the kept one, and the sentence it gives back is the same too. Beside the sentence, `model_tell` says how the provider took the key (`KeyVerdict`), from the number in the first line of its answer only, never from its words:

| `KeyVerdict` | When | What the onboarding does |
|---|---|---|
| `Works` | 200: the question was answered | keeps the key |
| `Unknown` | 401, with or without a reason that can be read. The provider's documentation gives 401 for a key that is missing, wrong or past its expiry date | wipes the key and asks for it again |
| `Known` | 402 or 403 with the provider's reason in its JSON. Its documentation gives 402 for an account without credit, and 403 for a key held back by a limit of its own (a quota, a spending limit, a model it may not use, the addresses it may come from) | keeps the key |
| `NotTold` | anything else: another number, a 402 or 403 without the provider's reason (a page from somewhere on the way), no answer, or one that cannot be read | keeps the key |

A 200 whose body the kernel cannot read still counts as `Works`: the answer came from the provider's own site, whose certificate was checked, and it took the key. `ask` gets the verdict too and does nothing with it. What the onboarding says to each is in [chat.md](chat.md).

## The provider and the model

- The provider is OrcaRouter, a service that passes questions on to many models. Its site is `api.orcarouter.ai` (`MODEL_SITE`), and questions go to the place `/v1/chat/completions` on it (`MODEL_PATH`).
- The model is `deepseek/deepseek-v4.1-flash-1017` (`MODEL_NAME`), the name the provider knows it by.
- All three are constants in `model.rs`. Another provider or another model means changing them, and reading that provider's documentation first.
- The request and the answer have the form that many providers share, named after the first service that used it ("chat completions").
- Everything here about the provider's side was read in its documentation in November 2026 and seen in one real answer; read the documentation again before changing the request.
- What is typed as a question goes to the provider, and from there to the maker of the model. The provider also keeps a record of each request.

## The request

One request per connection, over an encrypted link whose certificate was checked for the provider's name. It is put together like this:

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
- The body is JSON. The two texts in it are written with `json_text` (see [json.md](json.md)). `max_tokens` is the longest answer the model may give (`ANSWER_TOKENS`, 1000); models count in tokens, which are pieces of words. The model can think before it answers (its page at the provider says it has a thinking and a non-thinking way, and not which it takes when nothing is said), and thinking may be paid out of the same tokens, so the limit leaves room for far more than a five-word answer. The provider is paid by the token used, not by the limit: at the model's prices in November 2026 (0.60 dollars a million tokens out, twice that in the provider's busy hours) the whole limit would cost about a tenth of a cent.
- `"stream":false` asks for the whole answer in one piece. The provider's documentation does not say what it does when nothing is said; sent word by word, the answer would not read as JSON.
- Nothing is sent to choose thinking or not: the provider's documentation names no such setting for this model, and a setting it does not know could make it refuse the question.
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

- The whole answer is collected, up to 64 KB (`ANSWER_ROOM`). A longer one is not read at all.
- `answer_parts` takes it apart: the number is the three digits behind the first space of the first line, which must begin with `HTTP/`; the notes are passed over up to the empty line; the rest is the body.
- With the number 200 (`model_sentence`), the model's words are looked for in the body at `choices`, the first of them, `message`, `content`. If what stands there is not a text, the first piece of a list there is tried (`content`, first, `text`): the provider's documentation allows the words as a list of pieces. The places are from the provider's documentation, and a good answer from the real provider was read from them (see "What the real question showed").
- How the answer ended is read at `choices`, the first of them, `finish_reason`. Two values are told apart, `length` (the limit of tokens was reached) and `content_filter` (the provider held something back); any other value, or none, counts as an ordinary end. The value is compared and never said, so whatever stands there cannot reach the screen.
- Spaces and line ends before and after the words are taken off. Words that are then empty, or a `null` where the words belong, make the sentence "the model's answer was empty". A `null`, or no words at all, counts only if `finish_reason` was read as a text: the JSON reader checks that the rest of the answer closes properly only when it hands out a text, so a damaged answer is not taken for an empty one.
- A model that thinks may send its thoughts beside its words, at `reasoning_content` or `reasoning` (the provider's documentation names the first; the second is the other common name). They are not shown as words; they are only looked at to say "it spent all of its tokens thinking" when the answer is empty and reached the limit. The one place where they can appear is the beginning of an answer whose words cannot be found, which is said as it is.
- With any other number, the reason is looked for at `error` then `message`, then at `error` as a text, then at `message`. A number from 500 to 599 is "the provider could not answer", any other "the provider turned the question down". The provider's page for the model gave an error rate of about 5 in 100 over a week in November 2026, so a 502 or 503 now and then is to be expected.
- The words are cleaned like every text from outside (`plain_text`) and cut at 300 signs (`WORDS_SHOWN`). Only the signs that are said, and as many behind them as the key is long, are cleaned and searched for the key: a piece of the key that begins among the signs that are said ends among those.
- The reader takes bytes from outside, so it reads them with `get` and the JSON reader's rules; see [json.md](json.md). 11,499 damaged and made-up answers were put through it; see [testing.md](testing.md).
- An answer sent in pieces with their lengths in between (the web calls it "chunked") is not put together again: its body does not read as JSON, and the sentence is "I could not read why". The provider did not answer that way.

## The key

- **Only this file can borrow it.** `secret_lend` in `secret.rs` runs a short piece of code with the key in hand. It asks for a pass, `KeyPass`, whose inside is private to `model.rs`, so no other file can make one: a call from anywhere else does not build. (The disk's `WriteTicket` works the same way; see [disk.md](disk.md).) A key being tried is lent the same way, by `trial_lend`, from a room of its own beside the kept one. The one other way the key leaves `secret.rs` is locked, by `secret_lock`, for the onboarding; a key unlocked by `secret_unlock` goes straight into its place there (see "A secret" in [chat.md](chat.md)).
- **It is borrowed once for each asking.** `model_tell` copies the key into a room of its own, and that copy serves the whole asking: it goes into the request, and it is what is looked for in the answer afterwards. A new key typed while the answer is awaited changes nothing about the asking under way. The room is wiped before `model_tell` ends.
- **It goes to one site.** `model_tell` is the only borrower, and the request, the site's name for the name question and the site's name for the certificate check are handed to `site_exchange` as one constant. With a certificate made out to another name, the link fails before the request is sent.
- **The request is wiped.** It is put together in a room that is large enough from the start, so that it never moves and leaves a copy behind, and the room is wiped after the exchange, however it went. After requests whose answers did not repeat the key, a test machine's memory held the key once, in the room where it is kept.
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

## Asking for an app

`model_app` asks the model to write an app, through the same exchange (`provider_exchange`) with the kept key, borrowed in the same way (`key_copy`). The request differs from the fixed question's in two places: the body holds two messages, a fixed instruction text first as the `system` message and then the request, and `max_tokens` is 4000 (`APP_TOKENS`). An answer that is not a good one is said word for word as for the fixed question. A good one is read as a script (`app_sentence`). [apps.md](apps.md) has the whole of it.
