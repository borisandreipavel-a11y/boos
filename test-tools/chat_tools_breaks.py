"""Breaks made on purpose in the code that sends every line to the model and does the tools it asks for, each in
the stand-in copy of the project only (through net_copy.build's `more`). BREAKS maps a name to {file: change}.
CATCH names the scenario of test_chat_tools.py that must catch each break when it runs with BREAK set to its
name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- Where a line goes ---
    # The old echo stays: a line is given back instead of going to the model.
    "echo": {"chat.rs": swap("                // Every other line goes to the model.\n                model_ask(&said)\n",
                             '                format!("Kernel: you said \\"{}\\"", said)\n')},
    # A line goes to the model without a key.
    "nokeycheck": {"chat.rs": swap("    if secret_length() == 0 {\n        return String::from(\"Kernel: I cannot ask the model, because no key",
                                   "    if false {\n        return String::from(\"Kernel: I cannot ask the model, because no key")},
    # --- What goes with a line ---
    # The tool that picks a look is left out of the list.
    "nolooktool": {"tools.rs": swap("    tools.push(',');\n    tools.push_str(&pick_look_tool());\n", "")},
    # The kept apps are not offered.
    "norunlist": {"tools.rs": swap("    if !apps.is_empty() {\n", "    if false {\n")},
    # The page of the panel cannot be turned.
    "nopagetool": {"tools.rs": swap("    if pages > 1 {\n", "    if pages > 9 {\n")},
    # --- What the model answers ---
    # The model's words look like the kernel's own.
    "kernelwords": {"chat.rs": swap('    let row = format!("Model: {}", words);', '    let row = format!("Kernel: {}", words);')},
    # The terminal says nothing about the tokens of a line.
    "notokens": {"chat.rs": swap("        if let Some(tokens) = &answer.tokens {\n            serial_print(&format!(\"{}\\r\\n\", tokens));\n        }\n        if let Some(reply) = reply {",
                                 "        if let Some(reply) = reply {")},
    # The router's place for the repeated tokens is not read.
    "nocache": {"model.rs": swap('Step::Name("prompt_tokens_details"), Step::Name("cached_tokens")', 'Step::Name("prompt_tokens_details"), Step::Name("cached")')},
    # Nothing is said when the model asks for two things.
    "nomore": {"chat.rs": swap("                if reply.more {\n", "                if false {\n")},
    # The key is not hidden in what the model gives a tool.
    "nokeyhide": {"model.rs": swap("        key_hide(&mut inputs, key);\n", "")},
    # --- Doing the tools ---
    # A kept app asked for is made again instead of being run.
    "remake": {"tools.rs": swap('                Ok((request, script)) => {\n                    chat_say(&format!("I am running the app made for \\"{}\\".", request));\n'
                                '                    let (sentence, _) = app_run(&script);\n                    chat_say(&sentence);\n                }\n',
                                "                Ok((request, _)) => chat_say(&app_make(&request)),\n")},
    # The request the model gave is not cleaned or cut.
    "rawrequest": {"tools.rs": swap("Some(request) => chat_say(&app_make(&request_cleaned(&request))),", "Some(request) => chat_say(&app_make(&request)),")},
    # A number written as a text is not taken.
    "nonumbertext": {"tools.rs": swap("    digits.parse().ok()\n", "    None\n")},
    # A look picked by the model is not kept.
    "looknotkept": {"look.rs": swap("    } else if unsafe { KEPT } == Some(place) {\n", "    } else if true {\n")},
    # The panel does not turn to the page asked for.
    "pagenotturned": {"apps_kept.rs": swap("            unsafe { PAGE = page - 1 };\n", "")},
    # --- Reading numbers ---
    # A number with a point is taken for no JSON instead of for no whole number: the check at startup says so.
    "jsonfraction": {"json.rs": swap("            Some(b'.' | b'e' | b'E') => Err(NOT_A_NUMBER),\n", "            Some(b'e' | b'E') => Err(NOT_A_NUMBER),\n")},
}

CATCH = {
    "echo": "nokey",
    "nokeycheck": "nokey",
    "nolooktool": "words",
    "norunlist": "dice",
    "nopagetool": "pages",
    "kernelwords": "words",
    "notokens": "words",
    "nocache": "words",
    "nomore": "odd",
    "nokeyhide": "odd",
    "remake": "dice",
    "rawrequest": "odd",
    "nonumbertext": "odd",
    "looknotkept": "odd",
    "pagenotturned": "pages",
    "jsonfraction": "words",
}
