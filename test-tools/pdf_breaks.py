"""Breaks made on purpose in the code that opens a kept PDF as a document, each in the stand-in copy of the project only
(through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the scenario of
test_pdf_documents.py that must catch each break when it runs with BREAK set to its name: `orca` with OrcaRouter, every
other with Anthropic (BOOS_PROVIDER=anthropic, which run_tests.py sets for them)."""
from apps_kept_breaks import swap

BREAKS = {
    # --- The question ---
    # A no sends the PDF all the same.
    "noisyes": {"files.rs": swap("    let Some(address) = address.filter(|_| yes) else {\n", "    let Some(address) = address.filter(|_| true) else {\n")},
    # The question does not say which site Anthropic fetches the PDF from.
    "nosite": {"files.rs": swap("        site_of(&address)\n", "        \"the site\"\n")},
    # --- Which PDFs, and when ---
    # A PDF opens while OrcaRouter is the provider, and goes to it.
    "orcaopens": {"files.rs": swap("    if provider_in_use() != Provider::Anthropic {\n        chat_say(&format!(\"file {}, \\\"{}\\\", is a PDF, which opens only",
                                   "    if false {\n        chat_say(&format!(\"file {}, \\\"{}\\\", is a PDF, which opens only")},
    # open_file lists the PDFs while OrcaRouter is the provider.
    "orcalists": {"files.rs": swap("    file.kind == Kind::Pdf && file.address.is_some() && provider_in_use() == Provider::Anthropic\n",
                                   "    file.kind == Kind::Pdf && file.address.is_some()\n")},
    # A note's address need not be an encrypted one.
    "anyaddress": {"files.rs": swap("    let rest = given.strip_prefix(\"https://\")?;\n",
                                    "    let rest = given.strip_prefix(\"https://\").or_else(|| given.strip_prefix(\"http://\"))?;\n")},
    # A PDF opened on a line's second ask goes with its last, from which nothing can be kept.
    "lateopens": {"tools.rs": swap("                    return pdf_open_ask(number, chat_next_ask_last());\n",
                                   "                    return pdf_open_ask(number, false);\n")},
    # A PDF a document was made from is asked about and sent again, in place of opening its document.
    "reopensends": {"tools.rs": swap("                if reopened.is_none() && file_is_pdf(number) {\n", "                if file_is_pdf(number) {\n")},
    # --- What goes to the model ---
    # The ask that carries a PDF goes without it.
    "nodocument": {"model.rs": swap("            if pdf.is_empty() {\n                json_text(&sent)\n", "            if true {\n                json_text(&sent)\n")},
    # The model is asked to draw a PDF as a table, as a CSV file.
    "drawpdf": {"files.rs": swap("draw: PDF_WRITE,", "draw: FILE_DRAW,")},
    # open_file's sentence stays the CSV one while a PDF is listed.
    "csvsentence": {"tools.rs": swap("open_file_tool(&openable, files_open_pdf())", "open_file_tool(&openable, false)")},
    # The ask that carries a PDF may take a minute, as every other.
    "shortwait": {"model.rs": swap("const PDF_WAIT: u64 = 180;\n", "const PDF_WAIT: u64 = 60;\n")},
}

CATCH = {
    "noisyes": "no",
    "nosite": "open",
    "orcaopens": "orca",
    "orcalists": "orca",
    "anyaddress": "no",
    "lateopens": "no",
    "reopensends": "open",
    "nodocument": "open",
    "drawpdf": "open",
    "csvsentence": "open",
    "shortwait": "wait",
}
