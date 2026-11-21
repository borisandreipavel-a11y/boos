"""Breaks made on purpose in the code that keeps apps and things in pieces, each in the stand-in copy of the project
only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the scenario of
test_apps_kept.py that must catch each break when it runs with BREAK set to its name."""


def swap(old, new):
    def change(text):
        assert text.count(old) == 1, (old[:70], text.count(old))
        return text.replace(old, new)
    return change


BREAKS = {
    # --- The notebook ---
    # A thing in pieces counts without its check value fitting.
    "nowholecheck": {"notebook.rs": swap("if check_value(&thing.data) as u64 == thing.whole_check {", "if true {")},
    # A piece counts wherever it lies, as long as it is of the same thing.
    "noorder": {"notebook.rs": swap("&& thing.whole_check == whole_check && thing.first + piece - 1 == next_block)",
                                    "&& thing.whole_check == whole_check)")},
    # Any count of pieces is believed.
    "nopiecelimits": {"notebook.rs": swap("if pieces < 2 || pieces > PIECES_MOST as u64 || piece == 0 || piece > pieces {",
                                          "if piece == 0 || piece > pieces {")},
    # A piece before the last need not be full.
    "nofullpieces": {"notebook.rs": swap("if piece < pieces && data_length != DATA_MOST {", "if false {")},
    # A thing in pieces may hold more than 32 KB.
    "nothinglimit": {"notebook.rs": swap("if piece == pieces && (data_length == 0 || (pieces as usize - 1) * DATA_MOST + data_length > THING_MOST) {",
                                         "if piece == pieces && data_length == 0 {")},
    # What a piece says decides where the notebook ends.
    "piecesdecideend": {"notebook.rs": swap("            Piece::Odd => gathering = None,\n", "            Piece::Odd => break,\n")},
    # Only the first piece needs room.
    "noroom": {"notebook.rs": swap("if next_block > last_block || pieces > last_block - next_block + 1 {", "if next_block > last_block {")},
    # The end moves on only once the whole thing is written.
    "nopieceadvance": {"notebook.rs": swap("            unsafe { NEXT_BLOCK = number + 1 };\n", "")},
    # --- Keeping apps ---
    # An app is not kept.
    "nokeep": {"chat.rs": swap("                if let Some(trouble) = app_keep(request, script) {\n                    chat_say(&trouble);\n                }\n", "")},
    # An app that was stopped is kept too.
    "keepstopped": {"chat.rs": swap("            chat_say(&sentence);\n            if ran {\n", "            chat_say(&sentence);\n            if true {\n")},
    # The same request again gets a number of its own.
    "nosamerequest": {"apps_kept.rs": swap("let same = apps.iter().find(|app| app.request == request).map(|app| app.number);",
                                           "let same: Option<u32> = None;")},
    # The oldest app first.
    "oldestfirst": {"apps_kept.rs": swap("found.sort_by(|(one, _), (other, _)| other.cmp(one));", "found.sort_by(|(one, _), (other, _)| one.cmp(other));")},
    # A request read from the disk is not cleaned.
    "requestnotcleaned": {"apps_kept.rs": swap("map(|byte| if (b' '..=b'~').contains(byte) { *byte as char } else { '.' })", "map(|byte| *byte as char)")},
    # A number with a 0 in front counts.
    "leadingzero": {"apps_kept.rs": swap("|| digits.starts_with('0') ", "")},
    # --- The panel of apps ---
    # Apps without a whole script are counted in the panel's pages.
    "notwholelisted": {"apps_kept.rs": swap("let listed: Vec<&KeptApp> = apps.iter().filter(|app| app.whole).collect();",
                                            "let listed: Vec<&KeptApp> = apps.iter().collect();")},
    # A change of look does not paint the panel of apps again.
    "nolookrepaint": {"look.rs": swap("    screen_panel_again();\n    apps_panel_again();\n", "    screen_panel_again();\n")},
    # Six apps a page.
    "sixapps": {"apps_kept.rs": swap("    apps_on_a_page: 5,\n", "    apps_on_a_page: 6,\n")},
}

CATCH = {
    "nowholecheck": "outside",
    "noorder": "outside",
    "nopiecelimits": "outside",
    "nofullpieces": "outside",
    "nothinglimit": "outside",
    "piecesdecideend": "outside",
    "noroom": "full",
    "nopieceadvance": "failing",
    "nokeep": "make",
    "keepstopped": "make",
    "nosamerequest": "make",
    "oldestfirst": "make",
    "requestnotcleaned": "requests",
    "leadingzero": "requests",
    "notwholelisted": "outside",
    "nolookrepaint": "look",
    "sixapps": "small",
}
