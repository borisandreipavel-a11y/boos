"""Breaks made on purpose in the code that writes, lays out, turns, keeps and opens documents of text, each in the
stand-in copy of the project only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names
the scenario of test_text_documents.py that must catch each break when it runs with BREAK set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- Pages ---
    # Page Down and Page Up change nothing.
    "pagenotturned": {"drawing.rs": swap("        if let Some(next) = next.filter(|next| *next < pages.pages.len()) {\n",
                                         "        if let Some(next) = next.filter(|_| false) {\n")},
    # Page Down at the last page goes on to a page that is not there.
    "pagepastend": {"drawing.rs": swap("        if let Some(next) = next.filter(|next| *next < pages.pages.len()) {\n",
                                       "        if let Some(next) = next {\n")},
    # The title's row says nothing of the page shown.
    "nomark": {"drawing.rs": swap("    if pages.pages.len() > 1 {\n", "    if false {\n")},
    # The title is not cut to leave room for the page mark.
    "titlenotcut": {"drawing.rs": swap("    let mark_room = if count > 1 { page_mark(count - 1, count).len() + 1 } else { 0 };\n",
                                       "    let mark_room = 0;\n")},
    # No empty row between two blocks.
    "nogap": {"drawing.rs": swap("            } else {\n                used = used.saturating_add(text_row());\n            }\n        }\n",
                                 "            }\n        }\n")},
    # A table that goes on to the next page goes on without its head.
    "noheadagain": {"drawing.rs": swap("head: head.clone(), rows: rows[from..from + take].to_vec() });",
                                       "head: if from == 0 { head.clone() } else { None }, rows: rows[from..from + take].to_vec() });")},
    # A word longer than a row is not cut, and runs past the frame's room.
    "wordsnotcut": {"drawing.rs": swap("        if word.len() > across {\n", "        if false {\n")},
    # A whole picture of the screen leaves the document of text out.
    "repaintnotext": {"drawing.rs": swap("            InFrame::Text(pages) => pages_paint(&place, &room, pages),\n",
                                         "            InFrame::Text(_) => {}\n")},
    # --- Kept on the disk, and told to the model ---
    # The `document` line is kept with the lines, and goes to the model with them.
    "linesdocumentkept": {"drawing.rs": swap("        if !begun && word.eq_ignore_ascii_case(\"document\") {\n            continue;\n        }\n", "")},
    # A document of text is kept as a table in its note.
    "keptastable": {"documents.rs": swap("    note.push(kind.byte());\n", "    note.push(KIND_TABLE);\n")},
    # A start leaves documents of text out, as a kernel before them does.
    "textnotfound": {"documents.rs": swap("    let kind = Kind::of_byte(note[1])?;\n",
                                          "    let kind = Kind::of_byte(note[1]).filter(|kind| *kind == Kind::Table)?;\n")},
    # The model is told to change an open document of text with draw_table.
    "toldastable": {"documents.rs": swap("    let kind = document.kind;\n    let open = open_take();\n",
                                         "    let kind = Kind::Table;\n    let open = open_take();\n")},
    # --- The tool ---
    # write_document is not offered.
    "notool": {"tools.rs": swap("        if let (true, Some((rows, signs, bars))) = (documents_usable(), writing_room()) {\n",
                                "        if let (true, Some((rows, signs, bars))) = (false, writing_room()) {\n")},
    # What write_document is given is held to the table's bound, 4,096 bytes.
    "smallbound": {"model.rs": swap("        \"write_document\" => Some(DOCUMENT_INPUTS_LONGEST),\n",
                                    "        \"write_document\" => Some(TABLE_INPUTS_LONGEST),\n")},
    # An answer piece by piece keeps only what a table may be given.
    "streambound": {"model.rs": swap("            if let Some(inputs) = inputs {\n                let room = (DOCUMENT_INPUTS_LONGEST + 1)",
                                     "            if let Some(inputs) = inputs {\n                let room = (TABLE_INPUTS_LONGEST + 1)")},
    # A document of text in an answer that broke off is not drawn.
    "brokennotdrawn": {"chat.rs": swap("            if call.name == \"draw_table\" || call.name == \"write_document\" {\n",
                                       "            if call.name == \"draw_table\" {\n")},
}

CATCH = {
    "pagenotturned": "write",
    "pagepastend": "write",
    "nomark": "write",
    "titlenotcut": "odd",
    "nogap": "write",
    "noheadagain": "odd",
    "wordsnotcut": "odd",
    "repaintnotext": "odd",
    "linesdocumentkept": "write",
    "keptastable": "write",
    "textnotfound": "write",
    "toldastable": "write",
    "notool": "write",
    "smallbound": "cut",
    "streambound": "cut",
    "brokennotdrawn": "broken",
}
