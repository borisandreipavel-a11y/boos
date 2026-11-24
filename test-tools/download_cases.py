"""Files from the web, for the tests of downloads (test_downloads.py): what the stand-in (model_server.py) answers to a
GET for a file, by the site's name and the path, and what the kernel is meant to say about each, worked out from the
notes (docs/tools.md, docs/network.md), not from the kernel's code. Every site name and every file is made up; in the
stand-in copy of the kernel every site's name leads to the stand-in on this computer (net_copy.py), so no test reaches a
real site.

    answer, ending = answer_get("files.example.org", "/a.pdf")     # ending: "goodbye", "cut" or "hold"
"""
import random

SITE = "files.example.org"
OTHER = "other.example.net"
SITES = [SITE, OTHER]

FILE_MOST = 4 * 1024 * 1024


def filler(seed, length):
    """Bytes of every value, the same every time for the same seed."""
    picker = random.Random(seed)
    return bytes(picker.randrange(256) for _ in range(length))


def text_filler(seed, rows):
    picker = random.Random(seed)
    return "".join("%d,%s,%d\n" % (row, "".join(picker.choice("abcdefghij") for _ in range(8)), picker.randrange(1000)) for row in range(rows)).encode()


# The files, as the stand-in sends them.
PDF = b"%PDF-1.7\n" + filler(1, 12000) + b"\n%%EOF\n"
CSV = b"number,word,count\n" + text_filler(2, 300)
DOCX = b"PK\x03\x04" + filler(3, 5000)
XLSX = b"PK\x03\x04" + filler(4, 7000)
TEXT = "Plain words in a plain text, with a few signs: é 中.\n".encode() * 20
ODD = b"\x7fELF" + filler(5, 900)
PACK = b"PK\x03\x04" + filler(6, 800)
ZERO_TEXT = b"words\x00more words\n"

DOCX_KIND = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_KIND = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def head(first, notes):
    return first + b"".join(b"\r\n" + name + b": " + value for name, value in notes) + b"\r\n\r\n"


def plain(data, kind, length=True, first=b"HTTP/1.1 200 OK", more=()):
    notes = [(b"Content-Type", kind.encode())] + list(more)
    if length:
        notes.append((b"Content-Length", b"%d" % len(data)))
    notes.append((b"Connection", b"close"))
    return head(first, notes) + data


def sent_on(number, words, location):
    return head(b"HTTP/1.1 %d %s" % (number, words), [(b"Location", location.encode()), (b"Content-Length", b"0"), (b"Connection", b"close")])


def chunked(data):
    pieces = b"".join(b"%x\r\n" % len(piece) + piece + b"\r\n" for piece in (data[:1000], data[1000:])) + b"0\r\n\r\n"
    return head(b"HTTP/1.1 200 OK", [(b"Content-Type", b"application/pdf"), (b"Transfer-Encoding", b"chunked"), (b"Connection", b"close")]) + pieces


# (site, path) -> (bytes the stand-in sends, how it ends): "goodbye" (the link's goodbye, then the connection is
# closed), "cut" (closed without the goodbye) or "hold" (held open, saying nothing more).
FILES = {
    (SITE, "/a.pdf"): (plain(PDF, "application/pdf"), "goodbye"),
    (SITE, "/go/a.pdf"): (sent_on(302, b"Found", "../a.pdf"), "goodbye"),
    (SITE, "/b.csv"): (plain(CSV, "text/csv", length=False), "goodbye"),
    (SITE, "/c.docx"): (plain(DOCX, DOCX_KIND), "goodbye"),
    (SITE, "/notes.txt"): (plain(TEXT, "text/plain; charset=utf-8"), "goodbye"),
    (SITE, "/d.xlsx"): (sent_on(301, b"Moved Permanently", "https://%s/sheets/d.xlsx" % OTHER), "goodbye"),
    (OTHER, "/sheets/d.xlsx"): (plain(XLSX, "application/octet-stream"), "goodbye"),
    (OTHER, "/e.pdf"): (plain(PDF, "application/pdf"), "goodbye"),
    (SITE, "/gz.pdf"): (plain(PDF, "application/pdf", more=[(b"Content-Encoding", b"gzip")]), "goodbye"),
    (SITE, "/chunked.pdf"): (chunked(PDF), "goodbye"),
    (SITE, "/big.pdf"): (head(b"HTTP/1.1 200 OK", [(b"Content-Type", b"application/pdf"), (b"Content-Length", b"5000000"),
                                                    (b"Connection", b"close")]), "cut"),
    (SITE, "/plain.pdf"): (sent_on(302, b"Found", "http://%s/a.pdf" % SITE), "goodbye"),
    (SITE, "/loop/1"): (sent_on(302, b"Found", "/loop/2"), "goodbye"),
    (SITE, "/loop/2"): (sent_on(307, b"Temporary Redirect", "/loop/1"), "goodbye"),
    (SITE, "/missing.pdf"): (plain(b"<html><body>Not here</body></html>\n", "text/html", first=b"HTTP/1.1 404 Not Found"), "goodbye"),
    (SITE, "/page.html"): (plain(b"<html><body>A page</body></html>\n", "text/html"), "goodbye"),
    (SITE, "/badlength.pdf"): (head(b"HTTP/1.1 200 OK", [(b"Content-Type", b"application/pdf"), (b"Content-Length", b"12x"),
                                                         (b"Connection", b"close")]) + PDF, "goodbye"),
    (SITE, "/short.pdf"): (head(b"HTTP/1.1 200 OK", [(b"Content-Type", b"application/pdf"), (b"Content-Length", b"20000"),
                                                     (b"Connection", b"close")]) + PDF[:5000], "cut"),
    (SITE, "/cut.csv"): (plain(CSV[:3000], "text/csv", length=False), "cut"),
    (SITE, "/odd.bin"): (plain(ODD, "application/octet-stream"), "goodbye"),
    (SITE, "/pack.zip"): (plain(PACK, "application/zip"), "goodbye"),
    (SITE, "/zero.txt"): (plain(ZERO_TEXT, "text/plain"), "goodbye"),
    (SITE, "/silent.pdf"): (b"", "hold"),
}
for hop in range(1, 7):
    FILES[(SITE, "/hops/%d" % hop)] = (sent_on(302, b"Found", "/hops/%d" % (hop + 1)), "goodbye")
FILES[(SITE, "/hops/7")] = (plain(PDF, "application/pdf"), "goodbye")


def answer_get(site, path):
    """What the stand-in sends for a GET of `path` from `site`, and how it ends; a 404 for anything else. The made-up
    pictures under /pictures/ are picture_files.py's, made only when one is asked for."""
    found = FILES.get((site, path))
    if found:
        return found
    if site == SITE and path.startswith("/pictures/"):
        import picture_files
        data = picture_files.served(path)
        if data is not None:
            return plain(data, "image/png"), "goodbye"
    return plain(b"<html><body>No such file here</body></html>\n", "text/html", first=b"HTTP/1.1 404 Not Found"), "goodbye"


# ---------- What the kernel is meant to say (docs/tools.md, "download_file") ----------

def size_words(length):
    """A size in words, as the notes say: bytes, KB rounded to the nearest, or MB to a tenth."""
    if length == 1:
        return "1 byte"
    if length < 1024:
        return "%d bytes" % length
    if length < 1024 * 1024:
        return "%d KB" % ((length + 512) // 1024)
    tenths = (length * 10 + 512 * 1024) // (1024 * 1024)
    return "%d MB" % (tenths // 10) if tenths % 10 == 0 else "%d.%d MB" % (tenths // 10, tenths % 10)


KINDS = {"pdf": "a PDF", "docx": "a Word file", "xlsx": "an Excel file", "txt": "a text", "csv": "a CSV table", "png": "a PNG picture"}


def new_site(name, site):
    return ["Kernel: %s is on %s, a site I have not fetched from before." % (name, site), ASK]


def sent_to_new(site, other):
    return ["Kernel: %s sends me on to %s, a site I have not fetched from before." % (site, other), ASK]


ASK = "Kernel: may I? Type yes to allow it from now on; anything else is a no."


def fetching(name, site):
    return "Kernel: I am fetching %s from %s." % (name, site)


def kept(name, number, kind, data, site):
    return "Kernel: I kept \"%s\" as file %d, %s of %s from %s." % (name, number, KINDS[kind], size_words(len(data)), site)


def not_fetched(name, site, why):
    return "Kernel: I did not fetch %s from %s, because %s." % (name, site, why)


def not_kept(name, site, why):
    return "Kernel: I did not keep %s from %s, because %s." % (name, site, why)


def not_allowed(site):
    return "Kernel: I did not fetch it, since %s was not allowed." % site


def address_refused(text, why):
    return "Kernel: the model asked me to fetch \"%s\", but %s." % (text, why)


# Each file the scenario "refusals" asks for, and the row it is meant to bring (docs/tools.md, "Why a file is not kept").
REFUSALS = [
    ("/gz.pdf", lambda: not_fetched("gz.pdf", SITE, "it sent the file packed (\"gzip\"), which I do not take")),
    ("/chunked.pdf", lambda: not_fetched("chunked.pdf", SITE, "it sent the file in pieces with their lengths in between (\"chunked\"), "
                                                              "which it should not for this kind of request")),
    ("/big.pdf", lambda: not_fetched("big.pdf", SITE, "the file is 4.8 MB, more than the 4 MB I take")),
    ("/plain.pdf", lambda: "Kernel: I did not fetch plain.pdf, because %s sends me on to an address I cannot use: "
                           "it is not an encrypted address (https)." % SITE),
    ("/loop/1", lambda: "Kernel: I did not fetch 1, because %s sends me back to an address I was sent from." % SITE),
    ("/hops/1", lambda: "Kernel: I did not fetch 1, because %s sends me on more than 5 times." % SITE),
    ("/missing.pdf", lambda: not_fetched("missing.pdf", SITE, "it answered 404 Not Found")),
    ("/page.html", lambda: not_kept("page.html", SITE, "it is a kind of file I do not keep (the site calls it \"text/html\")")),
    ("/badlength.pdf", lambda: not_fetched("badlength.pdf", SITE, "it gave a length I cannot read")),
    ("/short.pdf", lambda: not_fetched("short.pdf", SITE, "the file did not come whole: 5000 of 20000 bytes came")),
    ("/cut.csv", lambda: not_fetched("cut.csv", SITE, "the file did not come whole: the connection ended without the site's goodbye")),
    ("/odd.bin", lambda: not_kept("odd.bin", SITE, "it is a kind of file I do not keep (the site calls it \"application/octet-stream\")")),
    ("/pack.zip", lambda: not_kept("pack.zip", SITE, "it is a packed file, but neither its address nor the site says it is a Word or an Excel file")),
    ("/zero.txt", lambda: not_kept("zero.txt", SITE, "it is said to be text, but it is not plain text")),
]

# Addresses the model may give that are turned down before anything is sent.
BAD_ADDRESSES = [
    ("http://%s/a.pdf" % SITE, "it is not an encrypted address (https)"),
    ("https://someone:secret@%s/a.pdf" % SITE, "it holds a name and a password"),
    ("https://%s:8443/a.pdf" % SITE, "it names a port other than 443"),
    ("https://10.0.2.2/a.pdf", "its site's name is not one I can look up"),
    ("ftp://%s/a.pdf" % SITE, "it is no address that begins with https://"),
]
