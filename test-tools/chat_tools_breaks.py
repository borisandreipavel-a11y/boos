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
    "notokens": {"chat.rs": swap("        if let Some(tokens) = &answer.tokens {\n            serial_print(&format!(\"{}\\r\\n\", tokens));\n        }\n        // A line ends",
                                 "        // A line ends")},
    # The router's place for the repeated tokens is not read.
    "nocache": {"model.rs": swap('Step::Name("prompt_tokens_details"), Step::Name("cached_tokens")', 'Step::Name("prompt_tokens_details"), Step::Name("cached")')},
    # Nothing is said when the model asks for two things.
    "nomore": {"chat.rs": swap("        if more {\n            chat_say(", "        if false {\n            chat_say(")},
    # The key is not hidden in what the model gives a tool.
    "nokeyhide": {"model.rs": swap("    key_hide(&mut inputs, key);\n", "")},
    # --- Doing the tools ---
    # A kept app asked for is made again instead of being run.
    "remake": {"tools.rs": swap('                Ok((request, script)) => {\n                    chat_say(&format!("I am running the app made for \\"{}\\".", request));\n'
                                '                    let run = app_run(&script);\n',
                                "                Ok((request, _)) => {\n                    let said = match app_make(&request) { Ok(said) | Err(said) => said };\n"
                                "                    let run = crate::apps::AppRun { sentence: said, ran: true, told: alloc::vec::Vec::new() };\n")},
    # The request the model gave is not cleaned or cut.
    "rawrequest": {"tools.rs": swap("Some(request) => match app_make(&request_cleaned(&request)) {", "Some(request) => match app_make(&request) {")},
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
    # --- What goes back to the model (docs/tools.md, "When what a tool did goes back") ---
    # What the kernel turns down does not go back.
    "noback": {"tools.rs": swap("    chat_say(&turned_down);\n    ToolDone::Back\n", "    chat_say(&turned_down);\n    ToolDone::Ended\n")},
    # A look that is picked goes back.
    "lookback": {"tools.rs": swap("                    if changed {\n                        look_paint();\n                    }\n                    return ToolDone::Ended;\n",
                                  "                    if changed {\n                        look_paint();\n                    }\n                    return ToolDone::Back;\n")},
    # What came of a new app does not go back.
    "appnoback": {"chat.rs": swap("            if answer.tokens.is_some() {\n                ask_again(asks);\n", "            if false {\n                ask_again(asks);\n")},
    # Four asks a line.
    "asksfour": {"chat.rs": swap("const ASKS_MOST: usize = 3;", "const ASKS_MOST: usize = 4;")},
    # The last ask goes with the list of tools.
    "lastwithtools": {"chat.rs": swap("    let tools = if last { String::new() } else { chat_tools() };\n", "    let tools = chat_tools();\n")},
    # The same tool with the same inputs is done twice for a line.
    "twice": {"chat.rs": swap("        let outcome = if asks.wanted.contains(&wanted) {\n", "        let outcome = if false {\n")},
    # The answer to an ask about a line again begins a piece of its own.
    "newpiece": {"chat.rs": swap("        if first {\n            conversation_line(answer.sent.as_deref());\n        } else {\n            conversation_again();\n        }\n",
                                 "        conversation_line(answer.sent.as_deref());\n")},
    # What an app left behind is remembered with the key as it was, starred only when it goes.
    "nostarkept": {"model.rs": swap("    let starred = key_starred(text, &key_room[..key_length]);\n", "    let starred = String::from(text);\n")},
    # --- Drawing a table ---
    # Letters too faint to read on their background are painted as the model asked.
    "tablefaint": {"drawing.rs": swap("    if 2 * (lighter + FLARE) >= 9 * (darker + FLARE) {\n", "    if true {\n")},
    # Another table asked for after the kernel turned one down counts as the same thing again.
    "tablewanted": {"tools.rs": swap('        "draw_table" => drawing_wanted(&call.inputs, call.cut_off),\n', "")},
    # --- An answer piece by piece ---
    # "[DONE]" is not taken as the end: every answer that comes piece by piece breaks off.
    "nodone": {"model.rs": swap("            self.done = true;\n            self.done_at = Some(self.now());\n",
                                "            self.done_at = Some(self.now());\n")},
    # The words that come show whole, the last signs, where a piece of the key may begin, not held back.
    "noholdback": {"model.rs": swap("let shown = signs.len().saturating_sub(key.len().saturating_sub(1)).min(WORDS_SHOWN);",
                                    "let shown = signs.len().min(WORDS_SHOWN);")},
    # The key is not starred in the words shown while more may come.
    "nohidesofar": {"model.rs": swap("    key_hide(&mut signs, key);\n    let shown = signs.len()", "    let shown = signs.len()")},
    # Only the first part of what the model gives a tool is kept.
    "firstpart": {"model.rs": swap("            if let Some(inputs) = inputs {\n                let room",
                                   "            if let Some(inputs) = inputs.filter(|_| self.tool_inputs.is_empty()) {\n                let room")},
    # Pieces with their lengths in between are read as if they were none.
    "nochunked": {"model.rs": swap("            self.chunked = head.transfer_coding.is_some();\n", "            self.chunked = false;\n")},
    # A tool asked for in an answer that broke off is done all the same.
    "brokendone": {"chat.rs": swap("        if reply.as_ref().is_some_and(|reply| reply.broken) {\n", "        if false {\n")},
    # The rows of the answer that came in stay when the answer is said.
    "growstays": {"chat.rs": swap("    growing().clear();\n    unsafe { THINKING = false };\n", "    unsafe { THINKING = false };\n")},
    # The mark that the model thinks is never shown.
    "nothinking": {"chat.rs": swap("    let thinking = unsafe { THINKING } && growing.is_empty();\n", "    let thinking = false;\n")},
}

CATCH = {
    "nodone": "stream",
    "noholdback": "stream",
    "nohidesofar": "stream",
    "firstpart": "stream",
    "nochunked": "stream",
    "brokendone": "stream",
    "growstays": "stream",
    "nothinking": "stream",
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
    "noback": "rounds",
    "lookback": "rounds",
    "appnoback": "dice",
    "asksfour": "rounds",
    "lastwithtools": "rounds",
    "twice": "rounds",
    "newpiece": "rounds",
    "nostarkept": "rounds",
    "tablefaint": "table",
    "tablewanted": "table",
}
