"""Files opened as documents (docs/tools.md `open_file`), for test_open_file.py: the stand-in's answers about them, in
the shape of document_cases.py, which hands it every behaviour it does not know itself; the files the tests put on the
disk from outside; and the tables the stand-in's model draws from them. Every file and every site is made up. Nothing
runs when this file is imported.

Behaviours: "openfile=1" asks for open_file with the file 1; "openfilebad" with a file whose number cannot be read;
"filetable=numbers" asks for draw_table with the table "numbers" of TABLES behind the line "document 0";
"filechange=doubled:2" with the table "doubled" behind the line "document 2"."""
from chat_cases import body, call, good, message
from download_cases import CSV, PDF

# The CSV the stand-in serves at /b.csv on the made-up site (download_cases.py): a head and 300 rows, each "number,word,
# count". Its row 200 is the mark that may stand in no request but the one ask that carries the file.
FETCHED = CSV
FETCHED_ROWS = [line.split(",") for line in FETCHED.decode().split("\n")[1:] if line]
MARK = ",".join(FETCHED_ROWS[199])

# A CSV of 3,000 rows, about 84 KB: more than the 64 KB that go to the model, so its first 64 KB go, cut behind the last
# line end inside them.
BIG = b"row,word,again\n" + b"".join(b"%05d,%s,%s\n" % (number, word, word)
                                     for number, word in ((n, (b"abcdefghij"[n % 10:] + b"abcdefghij"[:n % 10])) for n in range(3000)))
BIG_ROWS = [line.split(",") for line in BIG.decode().split("\n")[1:] if line]
# A CSV whose first line is longer than the 64 KB that go: it is not opened.
LONG_LINE = b"x" * 70000 + b"\n1,2\n"
# A CSV whose bytes on the disk are not proper text (UTF-8): put there from outside, since a fetch would not keep it.
NOT_PLAIN = b"name,price\n\xff\xfe,1\n"
# A CSV as real files often are: a byte order mark, Windows line ends, a quoted cell with a comma and doubled quotes,
# letters beyond ASCII, a tab and a backslash. All of it goes to the model as it is, written the JSON way.
REAL = ("﻿name,city,note\r\n" + '"Smith, J.",Zürich,"says ""hi"""\r\n' + "Lee,Kraków,tab\there\r\n"
        + "Ng,Tōkyō,back\\slash\r\n").encode("utf-8")

TABLES = {
    # The fetched CSV's first ten rows, as the model draws them.
    "numbers": "\n".join(["title Numbers", "head Number | Word | Count"] + ["row " + " | ".join(row) for row in FETCHED_ROWS[:10]]),
    # The same rows with a column more, as a change by a wish writes them again.
    "doubled": "\n".join(["title Numbers", "head Number | Word | Count | Twice"]
                         + ["row %s | %s | %s | %d" % (number, word, count, 2 * int(count)) for number, word, count in FETCHED_ROWS[:10]]),
    # The big file's first twenty rows: more than the frame holds, so the table goes back to the model.
    "bigfirst": "\n".join(["title Rows", "head Row | Word"] + ["row %s | %s" % (row, word) for row, word, _ in BIG_ROWS[:20]]),
}


def text(name, number):
    """What the model gives draw_table under `table`: the table `name` behind the line "document N"."""
    return "document %d\n%s" % (number, TABLES[name])


def answer(kind, line, bearer):
    """Gives (bytes to send, how to end) for a behaviour about files opened as documents, or None."""
    name, _, given = kind.partition("=")
    if name == "openfile":
        return good(body(message(None, [call("open_file", {"file": int(given)})]), "tool_calls")), "goodbye"
    if name == "openfilebad":
        return good(body(message(None, [call("open_file", {"file": "the prices"})]), "tool_calls")), "goodbye"
    if name == "filetable":
        return good(body(message(None, [call("draw_table", {"table": text(given, 0)})]), "tool_calls")), "goodbye"
    if name == "filechange":
        table, number = given.split(":")
        return good(body(message(None, [call("draw_table", {"table": text(table, int(number))})]), "tool_calls")), "goodbye"
    # The behaviours for documents of text are text_document_cases.py's.
    import text_document_cases
    return text_document_cases.answer(kind, line, bearer)
