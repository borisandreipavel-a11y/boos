"""Breaks made on purpose in the code that keeps, opens and changes documents, each in the stand-in copy of the project
only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the scenario of
test_documents.py that must catch each break when it runs with BREAK set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- Changing a document ---
    # A change that did not come whole is drawn and kept all the same.
    "cutchangekept": {"documents.rs": swap("        if !whole {\n            return Err(format!(\"the new table for document",
                                           "        if false {\n            return Err(format!(\"the new table for document")},
    # A change for a document that is not open is made all the same, from lines the model has not seen.
    "closedchanged": {"documents.rs": swap("        if open_number() != Some(number) {\n            open_inner(number)?;\n",
                                           "        if false {\n            open_inner(number)?;\n")},
    # The `document` line is kept with the lines, and goes to the model with them.
    "documentlinekept": {"drawing.rs": swap("        if !rows_begun && word.eq_ignore_ascii_case(\"document\") {\n            continue;\n        }\n", "")},
    # --- What the model is told ---
    # The open document's lines do not go with the line.
    "nolines": {"model.rs": swap("    if !document.is_empty() {\n        told.push_str(&key_starred(document, key));\n",
                                 "    if false {\n        told.push_str(&key_starred(document, key));\n")},
    # A change asked for again once the kernel opened its document counts as the same thing again for the line.
    "wantedwithoutopen": {"tools.rs": swap("    let given = if call.name == \"draw_table\" { given.map(documents_wanted) } else { given };\n",
                                           "    let given = if false { given.map(documents_wanted) } else { given };\n")},
    # Opening a document ends the line, so the model never sees its lines in it.
    "openends": {"tools.rs": swap("            Some(number) => match document_open(number) {\n                Ok(said) => {\n                    chat_say(&said);\n"
                                  "                    return ToolDone::Back;\n",
                                  "            Some(number) => match document_open(number) {\n                Ok(said) => {\n                    chat_say(&said);\n"
                                  "                    return ToolDone::Ended;\n")},
    # A name is kept and listed as the model wrote it, signs that are not plain among them.
    "namenotcleaned": {"documents.rs": swap(
        "    let plain: String = bytes.iter().map(|byte| if (b' '..=b'~').contains(byte) { *byte as char } else { '.' }).collect();\n",
        "    let plain: String = String::from_utf8_lossy(bytes).into_owned();\n")},
    # --- Kept on the disk, and found at a start ---
    # The documents found at a start are listed the one changed first first.
    "oldestfirst": {"documents.rs": swap("    found.sort_by(|(one, _), (other, _)| other.cmp(one));\n", "    found.sort_by(|(one, _), (other, _)| one.cmp(other));\n")},
    # A new document's number is taken again from one whose lines are not whole.
    "numberreused": {"documents.rs": swap("let highest = documents.iter().map(|document| document.number).max().unwrap_or(0);",
                                          "let highest = documents.iter().filter(|document| document.whole).map(|document| document.number).max().unwrap_or(0);")},
    # --- The screen ---
    # A whole picture of the screen leaves the panel of documents out.
    "nopanel": {"look.rs": swap("    drawing_paint_again();\n    documents_panel_again();\n", "    drawing_paint_again();\n")},
    # `setup` leaves the open document open, and the frame as it was.
    "setupkeepsopen": {"documents.rs": swap("pub fn documents_setup() {\n    open_put(None);\n    drawing_clear();\n", "pub fn documents_setup() {\n")},
}

CATCH = {
    "cutchangekept": "cut",
    "closedchanged": "cut",
    "wantedwithoutopen": "cut",
    "documentlinekept": "keep",
    "nolines": "keep",
    "openends": "keep",
    "namenotcleaned": "odd",
    "oldestfirst": "keep",
    "numberreused": "odd",
    "nopanel": "keep",
    "setupkeepsopen": "keep",
}
