"""Every line to the model, worked out from the notes apart from the kernel's code (docs/tools.md, docs/chat.md,
docs/model.md): the request a line is sent with (the instruction text with the record of what was said before it,
the line, the list of tools for what the disk holds and whether anything is remembered, the limit), the rows the
kernel says at once and when the answer comes, and the chat box where every line but `key` and `setup` goes to the
model. Nothing runs when this file is imported."""
import re

import table_model
from app_cases import clean, hide
from conversation_model import FORGOT  # noqa: F401 (the row the tool `forget` gets, for the tests)
from keyed_model import ORDER, KeyedChat
from picture import ASKING, BUSY, NO_ADDRESS, NO_KEY  # noqa: F401 (the rows a line gets at once, for the tests)

MODEL = "deepseek/deepseek-v4.1-flash-1017"
LIMIT = 4000  # the most tokens of an answer to a line (docs/tools.md)
REQUEST_MOST = 45
WORDS_SHOWN = 300
NAME_LONGEST = 64

CHAT_INSTRUCTIONS = (
    "You are the voice of a small home-made operating system. "
    "The person at the machine types one line at a time into its chat box. "
    "You get the newest line, and below these instructions a record of the last lines before it and what came of them, if there were any. "
    "If the person asks you to forget what was said or to start over, use forget: saying so in words forgets nothing. "
    "Answer in plain words, in one or two short sentences, or use one of the tools when the person wants something done that a tool does. "
    "Use run_app for a kept app that fits the wish, and make_app only when none fits. "
    "An app can take inputs, such as a distance to convert: give them to make_app as its inputs, each with its value, never in its request; "
    "for a kept app that fits the wish, use run_app with the new values. "
    "If the person has not said a value an app needs and there is no obvious one, ask them for it in plain words."
)

# What stands between the instructions and the record of what was said before the line, when anything was.
RECORD_LEAD = ("\n\nWhat was said before the newest line, oldest first. "
               "\"Person:\" is the person at the machine, \"Model:\" is you, and \"Kernel:\" is the operating system saying what happened.\n")

LOOK_WORDS = {
    "Blue": "a dark blue screen, light boxes with orange frames",
    "Night": "an almost black screen, dark grey boxes, light letters",
    "Paper": "a white screen, white boxes with grey frames, like a printed page",
    "Contrast": "black and yellow, the easiest to read",
}
LOOKS_TOLD = "; ".join("%d %s (%s)" % (place + 1, name, LOOK_WORDS[name]) for place, name in enumerate(ORDER))


def tool(name, description, inputs, required):
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": inputs, "required": required}}}


MAKE_APP = tool("make_app",
                "Has a new app written for the person and runs it; an app that runs to its end is kept. "
                "Use it only when the person wants an app and no kept app fits. "
                "Give the app inputs for what a wish may change, such as a distance to convert, each with its value for this run.",
                {"request": {"type": "string",
                             "description": "What the app does in general, without its inputs or this run's values, in at most 45 signs, such as: "
                                            "converts km to miles"},
                 "inputs": {"type": "string",
                            "description": "The inputs the app takes at every run, at most 4, one line each: name | kind | what it is | its value "
                                           "for this run. A name has letters, digits or _ and begins with a letter; a kind is number, text or "
                                           "yes/no. Such as: km | number | the distance in kilometres | 5. Empty for an app that takes none."}},
                ["request", "inputs"])

# What run_app takes besides the app's number while any kept app has inputs, then required too (docs/tools.md).
VALUES = {"type": "string", "description": "A value for each input of the app, one line each: name | value, such as: km | 12. Empty for an app "
                                          "that takes none."}


def inputs_listed(inputs):
    """How run_app lists a kept app's inputs, (name, kind, about) each, behind its request."""
    out = ""
    for place, (name, kind, about) in enumerate(inputs):
        out += ", taking " if place == 0 else (" and " if place + 1 == len(inputs) else ", ")
        out += "%s (a %s: %s)" % (name, kind, about)
    return out


# The tool that fetches a file from the web and keeps it, offered while files can be kept (docs/tools.md).
DOWNLOAD_FILE = tool("download_file",
                     "Fetches a file from the internet over an encrypted link and keeps it on the disk: "
                     "a PDF, a Word or Excel file (.docx, .xlsx), plain text or CSV, of at most 4 MB. "
                     "Use it when the person wants a file fetched or downloaded from an address, and give the address exactly as the person gave it. "
                     "The person is asked before a site is contacted for the first time.",
                     {"address": {"type": "string", "description": "The file's address, beginning with https://"}}, ["address"])


def remove_file_tool(files):
    """`files`: (number, "name, a PDF of 12 KB") of the kept files, the one kept last first."""
    told = ("Removes one of the kept files from the disk for good, once the person says yes. The kept files, by number: "
            + "; ".join("%d: %s" % (number, file) for number, file in files) + ".")
    return tool("remove_file", told, {"file": {"type": "integer", "enum": [number for number, _ in files],
                                              "description": "The number of the kept file"}}, ["file"])


def run_app_tool(apps):
    """`apps`: (number, request), or (number, request, inputs) with (name, kind, about) for each input, of the kept apps,
    the one kept last first. While any has inputs, the tool says so and takes their values too."""
    apps = [app if len(app) == 3 else (app[0], app[1], []) for app in apps]
    with_inputs = any(inputs for _, _, inputs in apps)
    told = ("Runs one of the kept apps again, as it was written, without writing it anew"
            + (", with a value for each of its inputs" if with_inputs else "") + ". The kept apps, by number: "
            + "; ".join("%d: %s%s" % (number, request, inputs_listed(inputs)) for number, request, inputs in apps) + ".")
    properties = {"app": {"type": "integer", "enum": [number for number, _, _ in apps], "description": "The number of the kept app"}}
    if with_inputs:
        properties["values"] = VALUES
    return tool("run_app", told, properties, ["app", "values"] if with_inputs else ["app"])


def pick_look_tool():
    return tool("pick_look", "Changes the colours of the whole screen to one of these looks, and keeps it for later starts: " + LOOKS_TOLD + ".",
                {"look": {"type": "integer", "enum": list(range(1, len(ORDER) + 1)), "description": "The number of the look"}}, ["look"])


def turn_page_tool(pages, shown):
    return tool("turn_page",
                "Shows another page of the panel of kept apps near the top left of the screen. It has %d pages, the app kept last first, "
                "and shows page %d now." % (pages, shown),
                {"page": {"type": "integer", "description": "The number of the page, from 1 to %d" % pages}}, ["page"])


# The tool that forgets what was said, offered only while something is remembered. It needs no inputs, so it has no
# list of the inputs it requires.
FORGET = {"type": "function", "function": {"name": "forget",
                                           "description": "Forgets everything said before the newest line, so that the next line starts afresh. "
                                                          "Only this tool makes the system forget; saying so in words does not. "
                                                          "Use it whenever the person asks to forget what was said, to start over, or for a clean slate.",
                                           "parameters": {"type": "object", "properties": {}}}}


def tools_meant(apps, shown=1, remembered=False, screen=(1280, 800), files=()):
    """The list of tools for a disk with these kept apps (the one kept last first), the panel showing page `shown`,
    `draw_table` if the screen (width, height), or None for none, has room for a table, `download_file` unless `files`
    is None (no room for files, as on a disk that is not divided), `remove_file` for the kept files in `files`
    ((number, words), the one kept last first), and `forget` if anything said is remembered."""
    tools = [MAKE_APP]
    if apps:
        tools.append(run_app_tool(apps))
    tools.append(pick_look_tool())
    table = table_model.tool_meant(*screen) if screen else None
    if table:
        tools.append(table)
    if files is not None:
        tools.append(DOWNLOAD_FILE)
        if files:
            tools.append(remove_file_tool(files))
    pages = -(-len(apps) // 5)
    if pages > 1:
        tools.append(turn_page_tool(pages, shown))
    if remembered:
        tools.append(FORGET)
    return tools


def instructions_meant(record="", key=""):
    """The system message: the instruction text, and the record of what was said before the line behind it, if
    anything was, with every piece of the key starred."""
    return CHAT_INSTRUCTIONS + (RECORD_LEAD + hide(record, key) if record else "")


def body_meant(line, apps, shown=1, record="", key="", screen=(1280, 800), files=()):
    """The whole request for a line, as Python's JSON reader reads it: `record` is what was said before it (a picture.Chat
    keeps the record each line went with in `records`); every piece of `key` in the line and the record is starred;
    `screen` is the screen's (width, height), or None."""
    return {"model": MODEL, "messages": [{"role": "system", "content": instructions_meant(record, key)},
                                         {"role": "user", "content": hide(line, key)}],
            "tools": tools_meant(apps, shown, remembered=bool(record), screen=screen, files=files), "max_tokens": LIMIT, "stream": False}


# ---------- Asking about a line again, when what a tool did goes back to the model ----------

# At most this many asks about one line, the first included; the last goes without the list of tools.
ASKS_MOST = 3

# What stands before the rows the line brought so far, behind the record of the lines before it, and what ends the
# instruction text of the last ask.
AGAIN_LEAD = ("\n\nWhat came of the newest line so far, oldest first. "
              "\"Model:\" is you, and \"Kernel:\" is the operating system saying what happened. "
              "The person has typed nothing since. If what they wanted is done, say in plain words what came of it. "
              "Use a tool again only if it is not done. A new app is written from its request and its inputs alone, "
              "so to fix an app, use make_app with a request that says what to do differently.\n")
LAST_ASK = "\n\nYou are asked about this line for the last time, and no tools are offered now: answer in plain words."


def body_again(line, apps, split, last=False, shown=1, key="", screen=(1280, 800), files=()):
    """The whole request when the model is asked about `line` again: `split` is what it goes with (a picture.Chat keeps
    it in `agains`): the record of the lines before it and the rows the line brought so far. The list of tools is the
    one for the disk as it is then, with `forget`, since the line is remembered; the last ask has none."""
    record, done = split
    told = instructions_meant(record, key) + AGAIN_LEAD + hide(done, key) + (LAST_ASK if last else "")
    body = {"model": MODEL, "messages": [{"role": "system", "content": told}, {"role": "user", "content": hide(line, key)}],
            "max_tokens": LIMIT, "stream": False}
    if not last:
        body["tools"] = tools_meant(apps, shown, remembered=True, screen=screen, files=files)
    return body


def round_line(number):
    """The terminal's line when the model is asked about a line again, the `number`th time."""
    return "Round %d of %d: the model is asked again, with what came of the line so far%s" % (
        number, ASKS_MOST, ", without tools" if number == ASKS_MOST else "")


def left_on_screen(text):
    """What an app left on the screen, as the kernel remembers it when what the app did goes back to the model."""
    return 'the app left this on the screen: "%s".' % text


def terminal_says(printed):
    """The interpreter's line about an app's mistake, without "App: ", as the kernel remembers it then."""
    return 'the terminal says: "%s".' % printed


NOT_TWICE = "Kernel: the model asked for the same thing again for this line, so I did not do it twice."
NO_TOOL_LAST = "Kernel: the model asked for a tool in its last answer about this line, when none was offered, so I did nothing."


# ---------- Rows (those a line gets at once are in picture.py) ----------

MORE = "Kernel: the model asked for more than one thing at once, so I do only the first."
CANNOT_READ = {
    "make_app": "Kernel: the model asked for an app, but I could not read what the app should do.",
    "run_app": "Kernel: the model asked to run a kept app, but I could not read which one.",
    "pick_look": "Kernel: the model asked for another look, but I could not read which one.",
    "turn_page": "Kernel: the model asked for another page of the panel of apps, but I could not read which one.",
}
NO_REQUEST = "Kernel: the model asked for an app, but did not say what it should do."
THOUGHT_ALL = "Kernel: the model's answer was empty, because it spent all of its %d tokens thinking." % LIMIT
CUT_OFF = "Kernel: the model's answer was cut off at the limit of %d tokens." % LIMIT


def words_cut(words, key, longest):
    """The kernel's way with words from the provider: cleaned byte for byte, the key hidden, cut at `longest`."""
    return hide(clean(words)[:longest + len(key)], key)[:longest]


def model_row(words, key=""):
    return "Model: " + words_cut(words.strip(), key, WORDS_SHOWN)


def request_cleaned(request):
    """A request the model gave: the key hidden in it first (with all it gave the tool), then cleaned byte for byte,
    spaces at either end dropped, and cut at 45 signs."""
    plain = "".join(chr(b) if 32 <= b <= 126 else "." for b in request.encode("utf-8"))
    return plain.strip()[:REQUEST_MOST].rstrip()


def values_said(values):
    """The values of an app's inputs, (name, kind, value) each, as the kernel's sentences name them behind the request: a
    text in quotes and cut at 40 signs with "..." behind, the others as they were checked."""
    out = ""
    for place, (name, kind, given) in enumerate(values):
        out += ", with " if place == 0 else (" and " if place + 1 == len(values) else ", ")
        out += '%s "%s"' % (name, given if len(given) <= 40 else given[:40] + "...") if kind == "text" else "%s %s" % (name, given)
    return out


def making(request, values=()):
    return 'Kernel: I am asking the model to make "%s"%s.' % (request, values_said(values))


def running(request, values=()):
    return 'Kernel: I am running the app made for "%s"%s.' % (request, values_said(values))


def no_such_app(number):
    return "Kernel: the model asked for app %d, but no kept app has that number." % number


def cannot_do(name, key=""):
    return 'Kernel: the model asked for something I cannot do: "%s".' % words_cut(name, key, NAME_LONGEST)


def page_row(page, pages):
    return "Kernel: the panel of apps shows page %d of %d." % (page, pages)


def no_page_row(page, pages):
    if pages == 0:
        return "Kernel: the model asked for another page of the panel of apps, but no app is kept."
    return "Kernel: the model asked for page %d of the panel of apps, but it has %d %s." % (page, pages, "page" if pages == 1 else "pages")


def refused_row(message):
    return 'Kernel: the provider turned the question down (401): "%s".' % message


class ToolsChat(KeyedChat):
    """keyed_model.KeyedChat, where every line but `key` and `setup` goes to the model (picture.Chat) and the model may
    pick a look (KeyedChat.pick). What comes later is added with say() (a row of the kernel's), row() (a whole row)
    and model() (the model's words, as the kernel shows them)."""

    def model(self, words, key=""):
        self.row(model_row(words, key))


def tokens_lines(lines):
    """The terminal's lines about tokens."""
    return [line for line in lines if line.startswith("Tokens:")]


def key_pieces(text, key, least=6):
    """Whether a piece of the key, six signs long, stands anywhere in `text`."""
    return any(key[start:start + least] in text for start in range(len(key) - least + 1))


def only_plain(text):
    return re.fullmatch(r"[ -~]*", text) is not None
