"""Breaks made on purpose in the code that opens a kept file as a document, each in the stand-in copy of the project
only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the scenario of
test_open_file.py that must catch each break when it runs with BREAK set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- What goes to the model ---
    # The file's text is not taken by the ask that carries it, so it goes with every later ask about the line too.
    "fileagain": {"files.rs": swap("    let (lead, text) = opening.told.take()?;\n", "    let (lead, text) = opening.told.clone()?;\n")},
    # A file over 64 KB goes whole.
    "wholefile": {"files.rs": swap("    let whole = bytes <= SENT_MOST as u64;\n", "    let whole = true;\n")},
    # The first 64 KB of a longer file go as they are, cut in the middle of a row.
    "cutanywhere": {"files.rs": swap("    if !whole {\n        match read.iter().rposition(", "    if false {\n        match read.iter().rposition(")},
    # The words that ask for a table go with the last ask too, which offers no tools.
    "drawlast": {"files.rs": swap("lead, if draw { FILE_DRAW } else { \"\" }, text))", "lead, if draw || true { FILE_DRAW } else { \"\" }, text))")},
    # A file opened for one line is not forgotten at the next.
    "notforgotten": {"chat.rs": swap("    // A file opened for an earlier line never goes with this one.\n    file_opening_forget();\n",
                                     "    // A file opened for an earlier line never goes with this one.\n    if false {\n        file_opening_forget();\n    }\n")},
    # --- Which files ---
    # open_file lists every kept file, the PDF among them.
    "anykind": {"files.rs": swap("        .filter(|file| file.kind == Kind::Csv)\n", "        .filter(|_| true)\n")},
    # --- The document made from a file ---
    # The document's note does not say which file it was made from.
    "nolink": {"documents.rs": swap("    let from_file = if changes.is_none() { file_opening_number() } else { None };\n",
                                    "    let from_file = if false { file_opening_number() } else { None };\n")},
    # A file opened again is sent to the model again, in place of opening the document made from it.
    "noreopen": {"tools.rs": swap("let reopened = if kept { u32::try_from(number)", "let reopened = if false { u32::try_from(number)")},
}

CATCH = {
    "fileagain": "odd",
    "wholefile": "big",
    "cutanywhere": "big",
    "drawlast": "odd",
    "notforgotten": "odd",
    "anykind": "big",
    "nolink": "open",
    "noreopen": "open",
}
