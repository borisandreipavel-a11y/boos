"""Breaks made on purpose in the code that sends every line to the model and does the tools it asks for, each in
the stand-in copy of the project only (through net_copy.build's `more`). BREAKS maps a name to {file: change}.
CATCH names the scenario of test_chat_tools.py that must catch each break when it runs with BREAK set to its
name."""
from apps_kept_breaks import swap

BREAKS = {
    # The final chat round still invites the model to call a tool.
    "lasttools": {"chat.rs": swap("if round.number < LAST_ROUND { chat_tools() }", "if round.number <= LAST_ROUND { chat_tools() }")},
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
    "remake": {"tools.rs": swap("            Ok((request, script)) => {",
                               "            Ok((request, _)) => return tool_do(&Tool::Make(request), more),\n            #[allow(unreachable_patterns)]\n            Ok((request, script)) => {")},
    # The request the model gave is not cleaned or cut.
    "rawrequest": {"tools.rs": swap("return Tool::Make(request_cleaned(&request));", "return Tool::Make(request);")},
    # A number written as a text is not taken.
    "nonumbertext": {"tools.rs": swap("    digits.parse().ok()\n", "    None\n")},
    # A look picked by the model is not kept.
    "looknotkept": {"look.rs": swap("    } else if unsafe { KEPT } == Some(place) {\n", "    } else if true {\n")},
    # The panel does not turn to the page asked for.
    "pagenotturned": {"apps_kept.rs": swap("            unsafe { PAGE = page - 1 };\n", "")},
    # --- Reading numbers ---
    # A number with a point is taken for no JSON instead of for no whole number: the check at startup says so.
    "jsonfraction": {"json.rs": swap("            Some(b'.' | b'e' | b'E') => Err(NOT_A_NUMBER),\n", "            Some(b'e' | b'E') => Err(NOT_A_NUMBER),\n")},
    # --- What is remembered (docs/tools.md, "What the model remembers") ---
    # The record does not go with the line.
    "norecord": {"model.rs": swap("    if !record.is_empty() {\n        told.push_str(RECORD_LEAD);\n", "    if false {\n        told.push_str(RECORD_LEAD);\n")},
    # A line is not remembered when its answer comes.
    "nolinememory": {"chat.rs": swap("        conversation_line(answer.sent.as_deref());\n", "")},
    # The kernel's own sentences are not remembered.
    "nokernelrows": {"chat.rs": swap("    chat_paint_rows();\n    conversation_row(&row);\n}\n\n// Says the model's own words",
                                     "    chat_paint_rows();\n}\n\n// Says the model's own words")},
    # The person's line is remembered as "You", not as the person's.
    "nopersonlabel": {"conversation.rs": swap('format!("Person: {}", line)', 'format!("You: {}", line)')},
    # The key in a line is not starred before the line goes.
    "nostar": {"model.rs": swap("    let sent = key_starred(line, key);\n", "    let sent = String::from(line);\n")},
    # More than 10 lines are remembered.
    "nolinecount": {"conversation.rs": swap("    while exchanges.len() > LINES_REMEMBERED {\n", "    while exchanges.len() > LINES_REMEMBERED * 100 {\n")},
    # The bound of 8,000 bytes is not kept.
    "nobytebound": {"conversation.rs": swap("bytes_of(exchanges) > BYTES_REMEMBERED {\n", "bytes_of(exchanges) > BYTES_REMEMBERED * 100 {\n")},
    # `setup` does not forget.
    "nosetupforget": {"chat.rs": swap("                conversation_forget();\n                onboarding_again()\n", "                onboarding_again()\n")},
    # The tool `forget` is not offered.
    "noforgettool": {"tools.rs": swap("    if conversation_remembers() {\n", "    if false {\n")},
    # The tool `forget` forgets nothing.
    "forgetnothing": {"tools.rs": swap('            conversation_forget();\n            chat_say("I forgot', '            chat_say("I forgot')},
    # A line whose answer comes after `setup` is remembered all the same.
    "awaitedkept": {"conversation.rs": swap("        FORGOTTEN_WHILE_AWAITED = AWAITED;\n", "        FORGOTTEN_WHILE_AWAITED = false;\n")},
}

CATCH = {
    "lasttools": "results",
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
    "norecord": "remember",
    "nolinememory": "remember",
    "nokernelrows": "remember",
    "nopersonlabel": "remember",
    "nostar": "forgetting",
    "nolinecount": "bound",
    "nobytebound": "bound",
    "nosetupforget": "forgetting",
    "noforgettool": "forgetting",
    "forgetnothing": "forgetting",
    "awaitedkept": "forgetting",
}
