"""Breaks made on purpose in the code that fetches files from the web and keeps them, each in the stand-in copy of the
project only (through net_copy.build's `more`). BREAKS maps a name to {file: change}. CATCH names the scenario of
test_downloads.py that must catch each break when it runs with BREAK set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- The request and the answer ---
    # The request no longer asks for the file unpacked.
    "noidentity": {"download.rs": swap("\\r\\nAccept-Encoding: identity\\r\\nConnection: close", "\\r\\nConnection: close")},
    # A file sent in pieces with their lengths in between is taken as it came.
    "chunkedtaken": {"download.rs": swap("            if head.transfer_coding.is_some() {\n", "            if false {\n")},
    # A packed file is taken as it came.
    "packedtaken": {"download.rs": swap("                if !coding.is_empty() && !coding.eq_ignore_ascii_case(\"identity\") {\n",
                                        "                if false {\n")},
    # The length a site gives is not held against the largest file taken.
    "nolengthcap": {"download.rs": swap("                if length > FILE_MOST as u64 {\n", "                if false {\n")},
    # --- Being sent on ---
    "sixhops": {"files.rs": swap("const HOPS_MOST: usize = 5;", "const HOPS_MOST: usize = 6;")},
    "noloopcheck": {"files.rs": swap("            if fetch.seen.contains(&next.whole()) {\n", "            if false {\n")},
    # --- Sites ---
    # A site not contacted before is fetched from without asking.
    "noyes": {"files.rs": swap("    if site_allowed(&site) {\n        return hop_go();\n", "    if true {\n        return hop_go();\n")},
    # The yes is not kept in the notebook.
    "sitenotkept": {"files.rs": swap("    notebook_keep(&format!(\"{}{}\", SITE_NOTE, number), site.as_bytes())?;\n", "")},
    # --- The room ---
    # The notebook keeps its whole room although the room for files is left to them.
    "notebookwhole": {"notebook.rs": swap("            last_block = from - 1;\n            files_room = true;\n", "            files_room = true;\n")},
    # A removed file's note is not replaced, so it is still kept after a restart.
    "removenotkept": {"files.rs": swap("    notebook_keep(&format!(\"{}{}\", FILE_NOTE, number), b\"\").map_err(String::from)?;\n", "")},
}

CATCH = {
    "noidentity": "fetch",
    "chunkedtaken": "refusals",
    "packedtaken": "refusals",
    "nolengthcap": "refusals",
    "sixhops": "refusals",
    "noloopcheck": "refusals",
    "noyes": "fetch",
    "sitenotkept": "fetch",
    "notebookwhole": "fetch",
    "removenotkept": "remove",
}
