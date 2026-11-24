"""Breaks made on purpose in the code for the second provider (docs/model.md, "Anthropic"; docs/chat.md, "The
provider"), each in a copy of the project only (through net_copy.build's `more`). BREAKS maps a name to {file:
change}. CATCH names the scenario of test_anthropic.py that must catch each break when it runs with BREAK set to its
name."""


def swap(*pairs):
    """A change that swaps each old text for its new one; each old text must stand once."""
    def change(text):
        for old, new in pairs:
            assert text.count(old) == 1, (old[:70], text.count(old))
            text = text.replace(old, new)
        return text
    return change


BREAKS = {
    # The key's provider is not taken with it: every key is taken for OrcaRouter's.
    "keytoother": {"model.rs": swap(("        owner = provider;\n", "        owner = Provider::OrcaRouter;\n        let _ = provider;\n"))},
    # Anthropic's request leaves out the version of its form.
    "noversion": {"model.rs": swap(("Connection: close\\r\\nanthropic-version: {}\\r\\nx-api-key: ", "Connection: close\\r\\nx-version: {}\\r\\nx-api-key: "))},
    # Anthropic's key goes in OrcaRouter's note.
    "bearer": {"model.rs": swap(("Connection: close\\r\\nanthropic-version: {}\\r\\nx-api-key: ", "Connection: close\\r\\nanthropic-version: {}\\r\\nAuthorization: Bearer "))},
    # The choice of provider is not kept in the notebook.
    "notkept": {"onboarding.rs": swap(("    if chosen != provider_kept() {\n", "    if false {\n"))},
    # The key in memory is not wiped when another provider is picked.
    "nowipe": {"onboarding.rs": swap(("    if chosen != provider_in_use() {\n        secret_forget();\n", "    if chosen != provider_in_use() {\n"))},
    # The key typed after `key` is taken for OrcaRouter's, whatever provider is in use.
    "untagged": {"chat.rs": swap(("secret_keep(&typed[..signs], provider_in_use())", "secret_keep(&typed[..signs], crate::model::Provider::OrcaRouter)"))},
    # After a change of provider, Enter alone at the key does not ask for that key's password.
    "noswitchpassword": {"onboarding.rs": swap(("            if unsafe { SWITCHED } && secret_length() == 0 {\n", "            if false && secret_length() == 0 {\n"))},
    # The question always offers OrcaRouter for Enter alone.
    "offersorca": {"onboarding.rs": swap(("Enter alone keeps {}.\", provider_in_use().named())", "Enter alone keeps {}.\", Provider::OrcaRouter.named())"))},
    # A notebook without a word about the provider is taken for Anthropic's.
    "olderasked": {"onboarding.rs": swap(("        Ok(Some(kept)) if kept == ANTHROPIC_KEPT => Provider::Anthropic,\n        _ => Provider::OrcaRouter,\n",
                                          "        Ok(Some(kept)) if kept == ORCAROUTER_KEPT => Provider::OrcaRouter,\n        _ => Provider::Anthropic,\n"))},
    # Anthropic's end mark is not read, so no answer of its counts as whole.
    "nostopmark": {"model.rs": swap(("            \"message_stop\" => {\n", "            \"message_stop_never\" => {\n"))},
    # An `error` piece of Anthropic's is passed over.
    "noerror": {"model.rs": swap(("            \"error\" => {\n                self.failed = true;\n", "            \"error_never\" => {\n                self.failed = true;\n"))},
    # A tool is done after the provider's checks stopped the answer.
    "checkstool": {"model.rs": swap(("    let checked = stream.checks && !broken;\n", "    let checked = false;\n"))},
    # The pieces of what the model gives a tool are not put together.
    "toolpieces": {"model.rs": swap(("json_find_text(piece, &[Step::Name(\"delta\"), Step::Name(\"partial_json\")])", "json_find_text(piece, &[Step::Name(\"delta\"), Step::Name(\"partial\")])"))},
    # A thinking block does not count as thinking.
    "nothinking": {"model.rs": swap(("                    \"thinking\" | \"redacted_thinking\" => {\n                        self.thought = true;\n",
                                     "                    \"thinking\" | \"redacted_thinking\" => {\n"),
                                    ("                    \"thinking_delta\" => {\n                        self.thought = true;\n", "                    \"thinking_delta\" => {\n"))},
    # The counts of the question, which come in the first piece, are not read.
    "nocountsfirst": {"model.rs": swap(("                    self.usage_first = Some(piece.to_vec());\n", "                    let _ = piece;\n"))},
}

CATCH = {
    "keytoother": "first",
    "noversion": "first",
    "bearer": "first",
    "notkept": "first",
    "nowipe": "keyword",
    "untagged": "keyword",
    "noswitchpassword": "first",
    "offersorca": "powercut",
    "olderasked": "older",
    "nostopmark": "keyword",
    "noerror": "events",
    "checkstool": "events",
    "toolpieces": "events",
    "nothinking": "events",
    "nocountsfirst": "keyword",
}
