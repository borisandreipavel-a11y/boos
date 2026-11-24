"""Breaks made on purpose in the code that reads, draws, keeps and opens bar charts, each in the stand-in copy of the
project only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the scenario of
test_chart_documents.py that must catch each break when it runs with BREAK set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- Reading the lines ---
    # A number with commas cannot be read.
    "commasnotread": {"drawing.rs": swap("            b',' if !point && after_digit && next_is_digit => after_digit = false,\n", "")},
    # A bar without a number that reads is not counted, so nothing is said of it.
    "unreadnotcounted": {"drawing.rs": swap("                None => found.unread += 1,\n", "                None => {}\n")},
    # A title or a colour after the first bar counts.
    "lateritems": {"drawing.rs": swap("        } else if begun {\n            continue;\n        } else if word.eq_ignore_ascii_case(\"document\") {\n",
                                      "        } else if word.eq_ignore_ascii_case(\"document\") {\n")},
    # --- The bars ---
    # Every bar is drawn, those that do not fit too.
    "barsnotcut": {"drawing.rs": swap("    let fit = chart_rows(&room).max(1);\n", "    let fit = usize::MAX;\n")},
    # The numbers are not brought to the most decimals any has.
    "nodecimals": {"drawing.rs": swap("        bar.digits.saturating_mul(10u128.saturating_pow(self.decimals.saturating_sub(bar.decimals)))\n",
                                      "        bar.digits\n")},
    # The zero point stands at the left end of the bars' room, whatever is below zero.
    "zeroatleft": {"drawing.rs": swap("    let zero = bars_left.saturating_add(scale.dots(scale.most_negative, width));\n",
                                      "    let zero = bars_left;\n")},
    # A bar below zero goes to the right of the zero point.
    "negativeright": {"drawing.rs": swap("        let left = if bar.negative { zero.saturating_sub(length) } else { zero };\n",
                                         "        let left = zero;\n")},
    # A bar's length is rounded up, not down.
    "lengthroundedup": {"drawing.rs": swap("        if span == 0 { 0 } else { (size.saturating_mul(u128::from(width)) / span) as u32 }\n",
                                           "        if span == 0 { 0 } else { ((size.saturating_mul(u128::from(width)) + span - 1) / span) as u32 }\n")},
    # No axis at the zero point.
    "noaxis": {"drawing.rs": swap("    screen_rectangle(zero, room.table_top, line, top.saturating_sub(room.table_top), look.panel_text);\n",
                                  "    let _ = line;\n")},
    # The scale's left end is written even where it would meet the right one.
    "scaletextsmeet": {"drawing.rs": swap("    if bars_left.saturating_add((scale.from.len() as u32 + 1).saturating_mul(sign)) <= to_left {\n",
                                          "    if true {\n")},
    # A label longer than 12 signs is not cut, and runs into the bars.
    "labelsnotcut": {"drawing.rs": swap("        screen_text(room.left, top.saturating_add(CHART_LETTERS_TOP), &shown(&bar.label, CHART_SIGNS_MOST), size, look.panel_text);\n",
                                        "        screen_text(room.left, top.saturating_add(CHART_LETTERS_TOP), &shown(&bar.label, usize::MAX), size, look.panel_text);\n")},
    # The title is not cut to the frame's room.
    "titlenotcut": {"drawing.rs": swap("shown(title, (room.width / sign_width().max(1)) as usize)).unwrap_or_default();\n",
                                       "shown(title, usize::MAX)).unwrap_or_default();\n")},
    # --- The bars' colour ---
    # The colour asked for is used even where it does not stand out.
    "colourunchecked": {"drawing.rs": swap("        Some(colour) if stands_out(colour) => colour,\n", "        Some(colour) => colour,\n")},
    # Where the colour asked for does not stand out, the letters' colour, never the frame's.
    "noframecolour": {"drawing.rs": swap("        _ if stands_out(frame) => frame,\n", "")},
    # A whole picture of the screen leaves the chart out.
    "repaintnochart": {"drawing.rs": swap("            InFrame::Chart(chart) => chart_paint(&place, &room, chart),\n",
                                          "            InFrame::Chart(_) => {}\n")},
    # --- Kept on the disk, and told to the model ---
    # The `document` line is kept with the lines, and goes to the model with them.
    "chartdocumentkept": {"drawing.rs": swap("        bars_begun = bars_begun || word.eq_ignore_ascii_case(\"bar\");\n        if !bars_begun && word.eq_ignore_ascii_case(\"document\") {\n            continue;\n        }\n",
                                             "        bars_begun = bars_begun || word.eq_ignore_ascii_case(\"bar\");\n")},
    # A chart is kept as a document of text in its note.
    "chartkeptastext": {"documents.rs": swap("            Kind::Chart => KIND_CHART,\n", "            Kind::Chart => KIND_TEXT,\n")},
    # A start leaves charts out, as a kernel before them does.
    "chartnotfound": {"documents.rs": swap("    let kind = Kind::of_byte(note[1])?;\n",
                                           "    let kind = Kind::of_byte(note[1]).filter(|kind| *kind != Kind::Chart)?;\n")},
    # The model is told to change an open chart with write_document.
    "charttoldastext": {"documents.rs": swap("is {}, a bar chart. To change it, write it whole again with draw_chart, beginning",
                                             "is {}, a document of text and tables. To change it, write it whole again with write_document, beginning")},
    # --- The tool ---
    # draw_chart is not offered.
    "nocharttool": {"tools.rs": swap("        if let (true, Some((bars, signs))) = (documents_usable(), charting_room()) {\n",
                                     "        if let (true, Some((bars, signs))) = (false, charting_room()) {\n")},
    # What draw_chart is given is held to a document of text's bound, 8,192 bytes.
    "chartbound": {"model.rs": swap("        \"draw_table\" | \"draw_chart\" => Some(TABLE_INPUTS_LONGEST),\n",
                                    "        \"draw_table\" => Some(TABLE_INPUTS_LONGEST),\n        \"draw_chart\" => Some(DOCUMENT_INPUTS_LONGEST),\n")},
    # A chart in an answer that broke off is said to be left undone.
    "chartbrokensaid": {"model.rs": swap("        let drawn_anyway = tool.as_ref().is_some_and(|tool| [\"draw_table\", \"write_document\", \"draw_chart\"].contains(&tool.name.as_str()));\n",
                                         "        let drawn_anyway = tool.as_ref().is_some_and(|tool| [\"draw_table\", \"write_document\"].contains(&tool.name.as_str()));\n")},
    # A chart in an answer that broke off is not drawn.
    "chartbrokennotdrawn": {"chat.rs": swap("            if [\"draw_table\", \"write_document\", \"draw_chart\"].contains(&call.name.as_str()) {\n",
                                            "            if [\"draw_table\", \"write_document\"].contains(&call.name.as_str()) {\n")},
}

CATCH = {
    "commasnotread": "odd",
    "unreadnotcounted": "odd",
    "lateritems": "odd",
    "barsnotcut": "odd",
    "nodecimals": "odd",
    "zeroatleft": "odd",
    "negativeright": "odd",
    "lengthroundedup": "draw",
    "noaxis": "draw",
    "scaletextsmeet": "odd",
    "labelsnotcut": "odd",
    "titlenotcut": "odd",
    "colourunchecked": "odd",
    "noframecolour": "draw",
    "repaintnochart": "draw",
    "chartdocumentkept": "draw",
    "chartkeptastext": "draw",
    "chartnotfound": "draw",
    "charttoldastext": "draw",
    "nocharttool": "draw",
    "chartbound": "cut",
    "chartbrokensaid": "broken",
    "chartbrokennotdrawn": "broken",
}
