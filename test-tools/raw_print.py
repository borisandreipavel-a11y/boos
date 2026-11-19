"""A temporary addition to model.rs, for a copy of the project only: print the provider's whole raw answer,
cleaned, 100 signs a row, so that one contact shows the web version, the notes and the body's real shape."""


def with_raw_print(text):
    old = "    wipe(&mut request);\n"
    assert text.count(old) == 1
    new = old + (
        "    {\n"
        "        // TEST: the whole raw answer, cleaned, 100 signs a row.\n"
        "        let mut report = format!(\"TEST raw answer, {} bytes, result {:?}:\\r\\n\", answer.len(), result);\n"
        "        let mut row = String::new();\n"
        "        for byte in answer.iter().take(6000) {\n"
        "            if *byte == b'\\n' || row.len() == 100 {\n"
        "                report.push_str(\"TEST | \");\n"
        "                report.push_str(&row);\n"
        "                report.push_str(\"\\r\\n\");\n"
        "                row.clear();\n"
        "            }\n"
        "            if (b' '..=b'~').contains(byte) {\n"
        "                row.push(*byte as char);\n"
        "            } else if *byte != b'\\n' && *byte != b'\\r' {\n"
        "                row.push('.');\n"
        "            }\n"
        "        }\n"
        "        report.push_str(\"TEST | \");\n"
        "        report.push_str(&row);\n"
        "        report.push_str(\"\\r\\n\");\n"
        "        crate::serial::serial_print(&report);\n"
        "    }\n")
    return text.replace(old, new)
