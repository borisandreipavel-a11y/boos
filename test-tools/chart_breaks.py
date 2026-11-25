"""Breaks made on purpose in the code that reads, lays out, draws and keeps bar charts in documents of text, each in the
stand-in copy of the project only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names
the scenario of test_chart_documents.py that must catch each break when it runs with BREAK set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- Reading the lines ---
    # A chart line begins no chart: it is skipped.
    "chartlineskipped": {"drawing.rs": swap("        } else if word.eq_ignore_ascii_case(\"chart\") {\n",
                                            "        } else if word.eq_ignore_ascii_case(\"chart\") && false {\n")},
    # A bar with no chart begun since the last other block begins none: it is lost.
    "barnotbegun": {"drawing.rs": swap("            if !matches!(found.blocks.last(), Some(Block::Chart(_))) {\n"
                                       "                found.blocks.push(Block::Chart(ChartBlock { title: None, colour: colour_held.take(), bars: Vec::new(), unread: 0 }));\n"
                                       "            }\n", "")},
    # A bar without a number that reads is not counted, so nothing is said of it.
    "unreadnotcounted": {"drawing.rs": swap("                    None => chart.unread += 1,\n", "                    None => {}\n")},
    # A colour for bars given when no chart can take it is lost, not held for the next chart.
    "colournotheld": {"drawing.rs": swap("                    _ => colour_held = Some(colour),\n", "                    _ => {}\n")},
    # A number with commas cannot be read.
    "commasnotread": {"drawing.rs": swap("            b',' if !point && after_digit && next_is_digit => after_digit = false,\n", "")},
    # A chart is no block when the lines are kept: a `document` line after its first bar is dropped.
    "chartnotblock": {"drawing.rs": swap("            || [\"text\", \"head\", \"row\", \"chart\", \"bar\"].iter().any(|block| word.eq_ignore_ascii_case(block))\n",
                                         "            || [\"text\", \"head\", \"row\"].iter().any(|block| word.eq_ignore_ascii_case(block))\n")},
    # --- Laying out ---
    # Every bar is drawn, those that do not fit on a page too.
    "barsnotcut": {"drawing.rs": swap("                let take = chart.bars.len().min(fit);\n", "                let take = chart.bars.len();\n")},
    # A chart that does not fit under what stands before it on the page is drawn there all the same.
    "chartsplits": {"drawing.rs": swap("                if used > 0 && used.saturating_add(chart_height) > height {\n", "                if false {\n")},
    # A chart's title takes no room in the layout.
    "titlerowfree": {"drawing.rs": swap("                let title_height = if chart.title.is_some() { text_row() } else { 0 };\n",
                                        "                let title_height = 0;\n")},
    # A chart with no bar to draw is drawn, an empty title and scale, and nothing is said of it.
    "emptychartdrawn": {"drawing.rs": swap("        if let Block::Chart(chart) = block {\n            if chart.bars.is_empty() {\n"
                                           "                charts_empty += 1;\n                continue;\n            }\n        }\n", "")},
    # A chart's title is not cut to the row.
    "titlenotcut": {"drawing.rs": swap("                        title: chart.title.as_deref().map(|title| shown(title, across)),\n",
                                       "                        title: chart.title.as_deref().map(|title| shown(title, usize::MAX)),\n")},
    # A document with bars left out counts as drawn whole, so it does not go back.
    "chartnotwhole": {"drawing.rs": swap("        !self.columns_left_out && !self.bars_left_out && self.bars_unread == 0 && self.charts_empty == 0 && self.pictures_not_shown.is_empty()\n",
                                         "        !self.columns_left_out && self.pictures_not_shown.is_empty()\n")},
    # --- Drawing ---
    # The bars of a chart are not painted, only its title.
    "chartnotpainted": {"drawing.rs": swap("                chart_paint(room, top, *colour, bars);\n", "                let _ = (colour, bars);\n")},
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
    "noaxis": {"drawing.rs": swap("    screen_rectangle(zero, top, line, row_top.saturating_sub(top), look.panel_text);\n", "    let _ = line;\n")},
    # The scale's left end is written even where it would meet the right one.
    "scaletextsmeet": {"drawing.rs": swap("    if bars_left.saturating_add((scale.from.len() as u32 + 1).saturating_mul(sign)) <= to_left {\n",
                                          "    if true {\n")},
    # A label longer than 12 signs is not cut, and runs into the bars.
    "labelsnotcut": {"drawing.rs": swap("        screen_text(room.left, row_top.saturating_add(CHART_LETTERS_TOP), &shown(&bar.label, CHART_SIGNS_MOST), size, look.panel_text);\n",
                                        "        screen_text(room.left, row_top.saturating_add(CHART_LETTERS_TOP), &shown(&bar.label, usize::MAX), size, look.panel_text);\n")},
    # The colour asked for is used even where it does not stand out.
    "colourunchecked": {"drawing.rs": swap("        Some(colour) if stands_out(colour) => colour,\n", "        Some(colour) => colour,\n")},
    # Where the colour asked for does not stand out, the letters' colour, never the frame's.
    "noframecolour": {"drawing.rs": swap("        _ if stands_out(frame) => frame,\n", "")},
    # --- Kept, and told to the model ---
    # A chart kept alone before charts stood in documents (kind 3) is left out at a start, as a kernel before charts did.
    "kind3notread": {"documents.rs": swap("            KIND_TEXT | KIND_CHART => Some(Kind::Text),\n", "            KIND_TEXT => Some(Kind::Text),\n")},
    # The model is told a chart shows one bar more than it does.
    "toldbars": {"tools.rs": swap("        bars, rows, signs\n", "        bars + 1, rows, signs\n")},
}

CATCH = {
    "chartlineskipped": "guide",
    "barnotbegun": "odd",
    "unreadnotcounted": "odd",
    "colournotheld": "odd",
    "commasnotread": "odd",
    "chartnotblock": "odd",
    "barsnotcut": "odd",
    "chartsplits": "odd",
    "titlerowfree": "guide",
    "emptychartdrawn": "odd",
    "titlenotcut": "odd",
    "chartnotwhole": "odd",
    "chartnotpainted": "guide",
    "nodecimals": "odd",
    "zeroatleft": "odd",
    "negativeright": "odd",
    "lengthroundedup": "guide",
    "noaxis": "guide",
    "scaletextsmeet": "odd",
    "labelsnotcut": "odd",
    "colourunchecked": "odd",
    "noframecolour": "guide",
    "kind3notread": "old",
    "toldbars": "guide",
}
