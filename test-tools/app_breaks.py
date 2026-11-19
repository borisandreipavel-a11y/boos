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
    "noinstructions": {"model.rs": swap("json_text(APP_INSTRUCTIONS),", "json_text(\"\"),")},
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
    "nohide": {"model.rs": swap("                key_hide(&mut signs, key);\n", "")},
    # The fixed question is asked with the app's limit of tokens.
    "asktokens": {"model.rs": swap("json_text(QUESTION),\n        ANSWER_TOKENS", "json_text(QUESTION),\n        APP_TOKENS")},
    # A word that only begins with "make" counts as a request.
    "anyprefix": {"apps.rs": swap("if rest.is_empty() || rest.starts_with(' ') {", "if true {")},
    # A request is sent without a kept key.
    "nokeycheck": {"apps.rs": swap("    if secret_length() == 0 {\n        return String::from(\"Kernel: I cannot ask the model for an app", "    if false {\n        return String::from(\"Kernel: I cannot ask the model for an app")},
    # The script is shown, but the request's words are sent without the lead in front.
    "nolead": {"model.rs": swap("json_text(&format!(\"{}{}\", APP_LEAD, wanted)),", "json_text(wanted),")},
    # --- The run ---
    # The script is shown but not run.
    "norun": {"chat.rs": swap("            chat_say(&app_run(script));\n", "")},
    # No new seed: every run starts its random numbers from the same place.
    "noseed": {"apps.rs": swap("let seed = random_number().map(|number| (number >> 1) as i64);", "let seed: Option<i64> = None;")},
    # The interpreter takes the seed but does not use it.
    "noseedlua": {"interpreter": swap("if let Some(value) = unsafe { SEED } {", "if let Some(value) = unsafe { SEED }.filter(|_| false) {")},
    # The interpreter does not cut a shown text, so the kernel's own rule stops the app.
    "nocut40": {"interpreter": swap("const LONGEST_SHOWN: usize = 40;", "const LONGEST_SHOWN: usize = 4000;")},
    # Fuel used up is not told apart, nor the interpreter giving up, nor a mistake.
    "fuelkind": {"app_box.rs": swap("Some(TrapCode::OutOfFuel) => StopKind::OutOfFuel,", "Some(TrapCode::OutOfFuel) => StopKind::Other,")},
    "gaveupkind": {"app_box.rs": swap("Some(TrapCode::UnreachableCodeReached) => StopKind::GaveUp,", "Some(TrapCode::UnreachableCodeReached) => StopKind::Other,")},
    "mistakekind": {"app_box.rs": swap("kind: StopKind::Mistake }),", "kind: StopKind::Other }),")},
    # A run that showed nothing is said as one that did.
    "shownothing": {"apps.rs": swap("Ok(0) => String::from(", "Ok(9999) => String::from(")},
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
    "anyprefix": "app",
    "nokeycheck": "app",
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
