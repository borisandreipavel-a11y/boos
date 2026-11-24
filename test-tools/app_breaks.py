"""Breaks made on purpose in the code that asks the model for an app, each in a copy of the project only (through
net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the stand-in's behaviours that must
catch each break when test_app.py runs with BREAK set to its name."""


def swap(old, new):
    def change(text):
        assert text.count(old) == 1, (old[:70], text.count(old))
        return text.replace(old, new)
    return change


BREAKS = {
    # The instruction text is left out of the request.
    "noinstructions": {"model.rs": swap("json_text(MODEL_NAME),\n            json_text(APP_INSTRUCTIONS),", "json_text(MODEL_NAME),\n            json_text(\"\"),")},
    # The ``` marks are never found, so they stay in the script.
    "nomarks": {"apps.rs": swap('.filter(|(_, line)| line.trim_start().starts_with("```"))', '.filter(|(_, line)| line.trim_start().starts_with("~~~never"))')},
    # A script cut off at the limit is taken as if it were whole.
    "nolength": {"model.rs": swap("Ok(words) if !words.is_empty() && out_of_room =>", "Ok(words) if !words.is_empty() && out_of_room && false =>")},
    # A script longer than the box takes is let through.
    "nolimit": {"apps.rs": swap("if script.len() > SCRIPT_LIMIT {", "if script.len() > SCRIPT_LIMIT * 2 {")},
    # The script's lines go to the terminal as they came.
    "noclean": {"apps.rs": swap("let shown = plain_text(&line.replace('\\t', \"  \"), SCRIPT_LINE_SHOWN);", "let shown = line.replace('\\t', \"  \");")},
    # A long line of the script is not cut.
    "nocut": {"apps.rs": swap("const SCRIPT_LINE_SHOWN: usize = 200;", "const SCRIPT_LINE_SHOWN: usize = 400;")},
    # The key is not hidden in the script.
    "nohide": {"model.rs": swap("            key_hide(&mut signs, key);\n            // Only signs of the key", "            // Only signs of the key")},
    # A line is sent with the fixed question's limit of tokens, not its own (every line goes to the model,
    # docs/tools.md; a line's limit is the app's 4000 too, so that swap would show nothing).
    "asktokens": {"model.rs": swap("json_text(&sent),\n            offered,\n            LINE_TOKENS", "json_text(&sent),\n            offered,\n            ANSWER_TOKENS")},
    # (No break for the word `make` and for a request without a key: the word is an ordinary line now, and a line
    # without a key is turned away before it reaches the model, which the breaks of model_breaks.py and
    # chat_tools_breaks.py named nokeycheck show.)
    # The script is shown, but the request's words are sent without the lead in front.
    "nolead": {"model.rs": swap("json_text(&format!(\"{}{}\", APP_LEAD, wanted)),", "json_text(wanted),")},
    # --- The run ---
    # The script is shown but not run: no run, no row about it, nothing kept.
    "norun": {"chat.rs": swap("            let run = app_run(script, values);\n            chat_say(&run.sentence);\n",
                              "            let run = crate::apps::AppRun { sentence: String::new(), ran: false, told: Vec::new() };\n")},
    # No new seed: every run starts its random numbers from the same place.
    "noseed": {"apps.rs": swap("let seed = random_number().map(|number| (number >> 1) as i64);", "let seed: Option<i64> = None;")},
    # The interpreter takes the seed but does not use it.
    "noseedlua": {"interpreter": swap("if let Some(value) = unsafe { SEED } {", "if let Some(value) = unsafe { SEED }.filter(|_| false) {")},
    # The interpreter does not cut a shown text, so the kernel's own rule stops the app.
    "nocut40": {"interpreter": swap("const LONGEST_SHOWN: usize = 40;", "const LONGEST_SHOWN: usize = 4000;")},
    # Fuel used up is not told apart, nor the interpreter giving up, nor a mistake.
    "fuelkind": {"app_box.rs": swap("Some(TrapCode::OutOfFuel) => StopKind::OutOfFuel,", "Some(TrapCode::OutOfFuel) => StopKind::Other,")},
    "gaveupkind": {"app_box.rs": swap("Some(TrapCode::UnreachableCodeReached) => StopKind::GaveUp,", "Some(TrapCode::UnreachableCodeReached) => StopKind::Other,")},
    "mistakekind": {"app_box.rs": swap("kind: StopKind::Mistake, texts }),", "kind: StopKind::Other, texts }),")},
    # A run that showed nothing is said as one that did.
    "shownothing": {"apps.rs": swap("Ok(texts) if texts.shown.is_none() => (String::from(", "Ok(texts) if texts.shown.is_some() && false => (String::from(")},
}

CATCH = {
    "noinstructions": "app",
    "nomarks": "appfenced",
    "nolength": "appcut",
    "nolimit": "appover",
    "noclean": "appodd",
    "nocut": "appodd",
    "nohide": "appecho",
    "asktokens": "app",
    "nolead": "app",
    "norun": "app",
    "noseed": "runrandom,runrandom",
    "noseedlua": "runrandom,runrandom",
    "nocut40": "runcut41",
    "fuelkind": "runloop",
    "gaveupkind": "runmemory",
    "mistakekind": "runmistake",
    "shownothing": "runprint",
}
