"""Breaks made on purpose in the code that keeps PNG pictures and JPEG photos, opens them as documents, lays them out in
documents of text and paints them, each in the stand-in copy of the project only (through net_copy.build's `more`). BREAKS maps a name to
{file: change}. CATCH names the scenario of test_picture_documents.py that must catch each break when it runs with BREAK
set to its name."""
from apps_kept_breaks import swap

BREAKS = {
    # --- Kept files ---
    # A PNG picture is not known by its first bytes, so it is not kept.
    "pngnotkept": {"files.rs": swap("    if bytes.starts_with(&PNG_SIGNATURE) {\n        return Ok(Kind::Png);\n    }\n", "")},
    # A kept picture's note is not read at a start, so the picture is forgotten.
    "pngforgotten": {"files.rs": swap("Kind::Csv, Kind::Png, Kind::Jpeg]", "Kind::Csv, Kind::Jpeg]")},
    # open_file does not list the PNG pictures, though its words name them.
    "picturesnotlisted": {"files.rs": swap(" || pdf_openable(file) || file.kind.picture())\n", " || pdf_openable(file))\n")},
    # A removed file is said to be a number never kept.
    "removednotsaid": {"files.rs": swap("        let removed = number > 0 && number < u64::from(unsafe { NEXT_FILE });\n",
                                        "        let removed = false;\n")},
    # More dots are taken than the notes say.
    "limitslarger": {"files.rs": swap("dots_most: 9_000_000", "dots_most: 16_000_000")},
    # --- Laid out and painted ---
    # Alpha does not count: a see-through dot is painted in its own colour.
    "noblend": {"drawing.rs": swap("            let alpha = dot[3] as u32;\n", "            let alpha = 255;\n")},
    # The blend is cut down, not rounded to the nearest.
    "blendcut": {"drawing.rs": swap("(255 - alpha) + 127) / 255", "(255 - alpha)) / 255")},
    # A picture is painted over the look Blue's inside colour in every look.
    "blendblue": {"drawing.rs": swap("picture_paint(room.left, room.table_top.saturating_add(*top), picture, look.panel_inside)",
                                     "picture_paint(room.left, room.table_top.saturating_add(*top), picture, Colour { red: 240, green: 240, blue: 240 })")},
    # A picture that does not fit the rest of a page stays on it.
    "nonextpage": {"drawing.rs": swap("                        if used > 0 && used.saturating_add(picture_height).saturating_add(caption_height) > height {\n",
                                      "                        if false {\n")},
    # A picture's caption is left out.
    "nocaption": {"drawing.rs": swap("                        used = used.saturating_add(picture_height);\n                        text_rows_laid(&mut pages, &mut used, height, caption_rows);\n",
                                     "                        used = used.saturating_add(picture_height);\n")},
    # A picture with a caption is shrunk to a whole page, so its caption runs past the page.
    "captionroom": {"drawing.rs": swap("file_picture(*file, room.width, height.saturating_sub(caption_height))", "file_picture(*file, room.width, height)")},
    # Every picture line is read, past the fourth.
    "nolimit": {"drawing.rs": swap("                let got = if pictures_tried > PICTURES_MOST {\n", "                let got = if false {\n")},
    # A page's pictures are not painted.
    "notpainted": {"drawing.rs": swap("            PagePart::Picture { top, picture } => picture_paint(room.left, room.table_top.saturating_add(*top), picture, look.panel_inside),\n",
                                      "            PagePart::Picture { .. } => {}\n")},
    # --- Opened and kept ---
    # A picture's document is kept as made from no file.
    "notfromfile": {"documents.rs": swap("version_keep(Kind::Text, None, &name_cleaned(name.as_bytes()), &lines, Some(file))",
                                         "version_keep(Kind::Text, None, &name_cleaned(name.as_bytes()), &lines, None)")},
    # A picture that cannot be shown opens all the same, its reason in its place.
    "refusedopened": {"documents.rs": swap("    if let Some((_, why)) = laid.written.pictures_not_shown.first() {\n", "    if let Some((_, why)) = None::<&(u64, String)> {\n")},
    # A picture opened before makes a new document.
    "noreopen": {"documents.rs": swap("    if let Some(reopened) = document_reopen(file) {\n        return reopened;\n    }\n", "")},
    # Opening a picture goes back to the model.
    "picturegoesback": {"tools.rs": swap("            match document_of_picture(number, &name, told) {\n                Ok(said) => {\n                    chat_say(&said);\n                    return ToolDone::Ended;\n",
                                         "            match document_of_picture(number, &name, told) {\n                Ok(said) => {\n                    chat_say(&said);\n                    return ToolDone::Back;\n")},
    # write_document does not say how a picture is shown.
    "nottold": {"tools.rs": swap("    if let Some(kinds) = pictures {\n", "    if let Some(kinds) = pictures.filter(|_| false) {\n")},
    # --- JPEG photos ---
    # A JPEG photo is not known by its first bytes, so it is not kept.
    "jpegnotkept": {"files.rs": swap("    if bytes.starts_with(&JPEG_START) {\n        return Ok(Kind::Jpeg);\n    }\n", "")},
    # A kept photo's note is not read at a start, so the photo is forgotten.
    "jpegforgotten": {"files.rs": swap("Kind::Csv, Kind::Png, Kind::Jpeg]", "Kind::Csv, Kind::Png]")},
    # open_file lists the PNG pictures only.
    "photosnotlisted": {"files.rs": swap(" || pdf_openable(file) || file.kind.picture())\n", " || pdf_openable(file) || file.kind == Kind::Png)\n")},
    # A photo is read as a PNG picture.
    "jpegaspng": {"files.rs": swap("    if kind == Kind::Jpeg {\n        // Its size as it is seen", "    if false {\n        // Its size as it is seen")},
    # More dots are taken than the notes say.
    "photolimitslarger": {"files.rs": swap("JpegLimits { dots_most: 100_000_000,", "JpegLimits { dots_most: 200_000_000,")},
    # A progressive photo keeps as many blocks as it has.
    "photoheldlarger": {"files.rs": swap("held_most: 16 * 1024 * 1024 }", "held_most: 64 * 1024 * 1024 }")},
    # open_file's words say a photo is a PNG picture.
    "photowords": {"tools.rs": swap('"Opens one of the kept JPEG photos in the frame on the screen,', '"Opens one of the kept PNG pictures in the frame on the screen,')},
}

CATCH = {
    "pngnotkept": "fetch",
    "pngforgotten": "reopen",
    "picturesnotlisted": "layout",
    "removednotsaid": "reopen",
    "limitslarger": "broken",
    "noblend": "fetch",
    "blendcut": "fetch",
    "blendblue": "fetch",
    "nonextpage": "layout",
    "nocaption": "fetch",
    "captionroom": "fetch",
    "nolimit": "layout",
    "notpainted": "fetch",
    "notfromfile": "fetch",
    "refusedopened": "broken",
    "noreopen": "reopen",
    "picturegoesback": "fetch",
    "nottold": "fetch",
    "jpegnotkept": "photos",
    "jpegforgotten": "photos",
    "photosnotlisted": "photos",
    "jpegaspng": "photos",
    "photolimitslarger": "photos",
    "photoheldlarger": "photos",
    "photowords": "photos",
}
