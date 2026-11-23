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
    "nokeyhide": {"model.rs": swap("        key_hide(&mut inputs, key);\n", "")},
    # --- Doing the tools ---
    # A kept app asked for is made again instead of being run.
    "remake": {"tools.rs": swap('                        chat_say(&format!("I am running the app made for \\"{}\\"{}.", request, values_said(&values)));\n'
                                '                        let run = app_run(&script, &values);\n',
                                "                        let said = match app_make(&request, inputs.clone(), values.clone()) { Ok(said) | Err(said) => said };\n"
                                "                        let run = crate::apps::AppRun { sentence: said, ran: true, told: alloc::vec::Vec::new() };\n")},
    # The request the model gave is not cleaned or cut.
    "rawrequest": {"tools.rs": swap("Ok((inputs, values)) => match app_make(&request_cleaned(&request), inputs, values) {",
                                    "Ok((inputs, values)) => match app_make(&request, inputs, values) {")},
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
    # --- Apps with inputs (docs/apps.md, "Inputs") ---
    # A number is not looked at before it is handed to the app.
    "numbernotchecked": {"app_inputs.rs": swap("            if !number_fits(written) {\n", "            if false {\n")},
    # A run of a kept app counts as the same thing whatever its values, so values given again in the same line are not taken.
    "valueswanted": {"tools.rs": swap('"run_app" => input_number(&call.inputs, "app").map(|number| format!("{}{}", number, values_wanted(&call.inputs))),',
                                      '"run_app" => input_number(&call.inputs, "app").map(|number| format!("{}", number)),')},
    # An app's inputs are not kept with its script.
    "inputsnotkept": {"apps_kept.rs": swap("    let thing = inputs_kept(inputs, script);\n", "    let thing = inputs_kept(&[], script);\n")},
    # A head of inputs read from the disk is not held to the rules.
    "headnotchecked": {"app_inputs.rs": swap(
        "        if !name_fits(name) || inputs.iter().any(|input| input.name == name) || about.is_empty() || about != about_cleaned(about) {\n",
        "        if false {\n")},
    # A kept app runs without the value one of its inputs needs.
    "missingtaken": {"app_inputs.rs": swap(
        '            None => return Err(format!("the model asked to run the app made for \\"{}\\", but gave no value for its input \\"{}\\".", request, input.name)),\n',
        "            None => continue,\n")},
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
    "numbernotchecked": "inputsodd",
    "valueswanted": "inputsodd",
    "inputsnotkept": "inputs",
    "headnotchecked": "inputsodd",
    "missingtaken": "inputs",
}
