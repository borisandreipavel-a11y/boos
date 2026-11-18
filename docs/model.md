# Asking the model

Code: `src/model.rs`; the lender of the key in `src/secret.rs`; the general exchange with a site in `src/page.rs`; the line `ask` in `src/chat.rs`.

A model is a program that answers a question put to it in words. This kernel does not run one. It asks one over the internet, through a provider: a service that takes a question, passes it on to a model, and sends the model's answer back. The provider wants a key with every question, which says who is asking and who pays. The key is the secret that the person at the machine types into the chat box (see [chat.md](chat.md)).

## What it does today

The line `ask`, sent by itself in the chat box, makes the kernel ask the model one fixed question, `Say hello in five words.` (`QUESTION`), with the kept secret as the key, and say in the chat box what came back. Nothing else can be asked yet.

- Without a kept secret the chat box says `Kernel: I cannot ask the model, because no key is kept. Send the line "key" first.` and nothing is sent.
- Otherwise it leaves an errand for the network's task (see "Errands" in [tasks.md](tasks.md)) and says `Kernel: I am asking the model "Say hello in five words."`. The answer comes later, as a row of its own.
- The network's task runs the errand by calling `model_tell`, which gives back one sentence:

| The sentence | When |
|---|---|
| `the model answered "..."` | The provider's answer carries the number 200 and the model's words were found in it |
| `the provider turned the question down (401): "..."` | Any other number; the words are the provider's reason. 401 is what a key it does not know gets |
| `the provider turned the question down (N), and I could not read why.` | Any other number, and the answer's body is not JSON with a reason in one of the three places looked at |
| `the provider answered, but I could not find the model's words in its answer, because ...` | The number 200, with a body that is not sound JSON or does not hold the words where they are looked for |
| `no answer came that I could read, because ...` | What came does not begin as an answer on the web does, or is larger than the room for it |
| `no answer came, because ...` | Nothing came: no name server, no key, a link that could not be made, a certificate that was refused, a provider that stayed silent |

` Its answer did not come whole.` is added when the provider did not say, through the encrypted link, that it had sent everything.

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
Content-Length: 128
Connection: close
Authorization: Bearer <the key>

{"model":"deepseek/deepseek-v4.1-flash-1017","messages":[{"role":"user","content":"Say hello in five words."}],"max_tokens":300}
```

- `POST` hands something in at the place named behind it. The lines after it are notes: which site is meant, what form the body has, how many bytes long it is, that the connection may be closed after the answer, and the key. An empty line ends the notes, and the body follows.
- The body is JSON. The two texts in it are written with `json_text` (see [json.md](json.md)). `max_tokens` is the longest answer the model may give (`ANSWER_TOKENS`); models count in tokens, which are pieces of words.
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
- With the number 200, the model's words are looked for in the body at `choices`, the first of them, `message`, `content`. That place is from the provider's documentation. **No good answer from the real provider has been seen yet**, only the refusal above.
- With any other number, the reason is looked for at `error` then `message`, then at `error` as a text, then at `message`.
- The words are cleaned like every text from outside (`plain_text`) and cut at 300 signs (`WORDS_SHOWN`).
- The reader takes bytes from outside, so it reads them with `get` and the JSON reader's rules; see [json.md](json.md). 6,091 damaged answers were put through it; see [testing.md](testing.md).
- An answer sent in pieces with their lengths in between (the web calls it "chunked") is not put together again: its body does not read as JSON, and the sentence is "I could not read why". The provider did not answer that way.

## The key

- **Only this file can borrow it.** `secret_lend` in `secret.rs` runs a short piece of code with the key in hand. It asks for a pass, `KeyPass`, whose inside is private to `model.rs`, so no other file can make one: a call from anywhere else does not build. (The disk's `WriteTicket` works the same way; see [disk.md](disk.md).)
- **It is borrowed once for each asking.** `model_tell` copies the key into a room of its own, and that copy serves the whole asking: it goes into the request, and it is what is looked for in the answer afterwards. A new key typed while the answer is awaited changes nothing about the asking under way. The room is wiped before `model_tell` ends.
- **It goes to one site.** `model_tell` is the only borrower, and the request, the site's name for the name question and the site's name for the certificate check are handed to `site_exchange` as one constant. With a certificate made out to another name, the link fails before the request is sent.
- **The request is wiped.** It is put together in a room that is large enough from the start, so that it never moves and leaves a copy behind, and the room is wiped after the exchange, however it went. After requests whose answers did not repeat the key, a test machine's memory held the key once, in the room where it is kept.
- **The key is kept out of what is said.** A provider may repeat the key in its refusal. Words that came from the provider go through `words_shown` before they are said: cleaned, then `key_hide` writes a star over every run of signs that stands in the key and is six signs long or longer (`KEY_PIECE`), or over the whole key if it is shorter, and only then cut at 300 signs, so that the cut cannot leave the beginning of the key standing. The kernel's own words in the sentence are not searched, so a key that happens to be an ordinary word does not put stars into them.
- **Two tasks reach the secret now:** the main loop keeps it, the network's task borrows it. Every function of `secret.rs` touches it with device signals off; borrowing is short, because the borrower only copies it.

What is not kept out: see "Asking the model" in [open-points.md](open-points.md).

## The general exchange

`site_exchange` in `page.rs` is the fetch of a page made general: it is given the site, the request and how long to wait, and hands every piece of the answer to a piece of code of the caller's. It looks the name up, connects, has `secure_exchange` make the encrypted link, and ends the connection. The page fetch and the question to the model both go through it; see [network.md](network.md).

The wait for the greeting and the answer together is 60 seconds here (`MODEL_WAIT`), against 15 for a page: a model needs longer than a site.

## What the first contact showed

One question was sent to the real provider with a made-up key.

- The provider takes the kernel's link as it is: TLS 1.3 with the one curve this kernel offers, and its certificate leads back to one of the trusted roots.
- It takes a request in `HTTP/1.0` form and answers with the whole body and its length, not in pieces, and closes the connection with a proper goodbye.
- The refusal came 1.4 seconds after the asking.
