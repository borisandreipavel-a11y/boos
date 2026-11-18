//! The values that the check of JSON at startup is made against. This file
//! is made by a script, not written by hand: the expected values in it come
//! from another JSON reader and writer than this kernel's, so that the check
//! does not merely compare the kernel's two halves with each other.
//! The pieces of JSON stand between `br#"` and `"#`, a form in which a text is
//! taken exactly as it is written. The model's answer in here is made up from
//! the names of its parts; it is not a real answer.
//! Notes: `docs/json.md`.

// A text with nothing special in it, and the same written the JSON way.
pub const PLAIN: &str = "Hello";
pub const PLAIN_AS_JSON: &str = "\"Hello\"";

// A text with every kind of awkward sign: quotes, a backslash, a slash, line
// ends, a tab, three control signs, letters with accents, signs of another
// script, and a sign whose number does not fit in four digits.
pub const AWKWARD: &str = "She said \"hi\", then a backslash \\, a slash /,\u{a}a new line, a tab\u{9}, a return\u{d}, the signs 1, 8 and 12:\u{1}\u{8}\u{c}, and caf\u{e9} \u{4f60}\u{597d} \u{1f600}.";
pub const AWKWARD_AS_JSON: &str = "\"She said \\\"hi\\\", then a backslash \\\\, a slash /,\\na new line, a tab\\t, a return\\r, the signs 1, 8 and 12:\\u0001\\b\\f, and caf\u{e9} \u{4f60}\u{597d} \u{1f600}.\"";

// An answer of the shape a model's answer has, and two texts in it.
pub const ANSWER: &[u8] = br#"{
  "id": "gen-0001",
  "object": "chat.completion",
  "created": 1790000000,
  "model": "deepseek/deepseek-v4.1-flash-1017",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!\nI am \"here\", said the model."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 9,
    "total_tokens": 21
  }
}"#;
pub const ANSWER_CONTENT: &str = "Hello!\u{a}I am \"here\", said the model.";
pub const ANSWER_MODEL: &str = "deepseek/deepseek-v4.1-flash-1017";

// A refusal, and the reason in it.
pub const REFUSAL: &[u8] = br#"{"error": {"message": "Missing or invalid API key", "type": "orcarouter_api_error", "code": "invalid_api_key"}}"#;
pub const REFUSAL_MESSAGE: &str = "Missing or invalid API key";

// A text in which every way of writing a special sign is used, and what it
// says once those are undone.
pub const ESCAPES: &[u8] = br#"{"text": "quote \" backslash \\ slash \/ line \n return \r tab \t back \b feed \f small \u00e9 capital \u00C9 pair \ud83d\ude00 zero \u0000 end"}"#;
pub const ESCAPES_TEXT: &str = "quote \" backslash \\ slash / line \u{a} return \u{d} tab \u{9} back \u{8} feed \u{c} small \u{e9} capital \u{c9} pair \u{1f600} zero \u{0} end";

// A piece of JSON in which the name `content` also stands where it must not
// count: inside a text, further in, and at the top. The one that counts has
// one of its letters written as a number. A text that is passed over on the
// way holds brackets, which must not be counted.
pub const DECOYS: &[u8] = br#"{"note": "\"content\": \"wrong, inside a text\" } ] ",
 "choices": [
  {"index": 0,
   "extra": {"content": "wrong, one level in", "message": {"content": "wrong, two levels in"}, "list": [[1, {"a": null}], true], "brackets": "] } ] [ { in a text"},
   "message": {"role": "assistant", "my_content": "wrong, a name that only ends alike", "cont\u0065nt": "right"}}
 ],
 "content": "wrong, at the top"}"#;
pub const DECOYS_CONTENT: &str = "right";

// The answer above, cut off in the middle of the text that is looked for.
pub const CUT_OFF: &[u8] = br#"{
  "id": "gen-0001",
  "object": "chat.completion",
  "created": 1790000000,
  "model": "deepseek/deepseek-v4.1-flash-1017",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!\nI am \"here\", "#;

// The answer above, whole, with one closing bracket too many behind it.
pub const ONE_TOO_MANY: &[u8] = br#"{
  "id": "gen-0001",
  "object": "chat.completion",
  "created": 1790000000,
  "model": "deepseek/deepseek-v4.1-flash-1017",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!\nI am \"here\", said the model."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 9,
    "total_tokens": 21
  }
}}"#;
