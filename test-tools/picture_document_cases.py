"""Documents with pictures (docs/screen.md "A document of text", "Pictures"), for test_picture_documents.py: the
stand-in's answers about them, in the shape of text_document_cases.py, which hands this file every behaviour it does
not know itself, and the documents the stand-in's model writes. The pictures themselves are picture_files.py's. Nothing
runs when this file is imported.

Behaviours: "picdoc=kinds1:0" asks for write_document with the document "kinds1" of TEXTS behind the line "document 0"
(or another number)."""
from chat_cases import body, call, good, message

TEXTS = {
    # The harbour picture opened as document 1, written again with a caption and a paragraph under it.
    "caption": "title Harbour\npicture 1 | The harbour at dawn\ntext A picture fetched from the made-up site, shrunk to fit the page.",
    # Four kinds of picture, each with a caption, on one page (picture_files.py, files 1 to 4).
    "kinds1": ("title Kinds one\npicture 1 | grey of 16 bits, a see-through key\npicture 2 | a palette of 4 bits\n"
               "picture 3 | colour and alpha of 16 bits\npicture 4 | interlaced"),
    # Four more, without captions, and a table after them (files 5 to 8).
    "kinds2": "title Kinds two\npicture 5\npicture 6\npicture 7\npicture 8\nhead File | Kind\nrow 8 | palette in pieces",
    # The layout: a paragraph, a wide picture after it on the first page, a table, a tall picture that needs a page of
    # its own, and pictures that cannot be shown: a number never kept, a CSV file, and a fifth picture line.
    "layout": ("title Layout of pictures\n"
               "text Pictures stand in a document of text as its paragraphs and tables do, each where its line stands. "
               "A picture never splits: it begins on the page where it stands if it fits there whole with its caption, "
               "and on the next page otherwise. This paragraph is long enough to take several rows of the page, so that the "
               "wide picture after it begins lower down.\n"
               "picture 2 | A wide one\n"
               "head Name | Dots\nrow tall | 200 by 600\nrow wide | 1000 by 100\n"
               "picture 1 | A tall one\n"
               "picture 9\n"
               "picture 5 | Not a picture\n"
               "picture 4 | One too many\n"
               "picture three | a line without a number\n"
               "text The end."),
}


def text(name, number=None):
    """What the model gives write_document under `lines`: the document `name`, behind the line "document N" if given."""
    return ("document %d\n" % number if number is not None else "") + TEXTS[name]


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour about documents with pictures, or None."""
    name, _, given = kind.partition("=")
    if name == "picdoc":
        document, number = given.split(":")
        return good(body(message(None, [call("write_document", {"lines": text(document, int(number))})]), "tool_calls")), "goodbye"
    return None
