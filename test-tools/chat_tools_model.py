"""Every line to the model, worked out from the notes apart from the kernel's code (docs/tools.md, docs/chat.md,
docs/model.md): the request a line is sent with (the instruction text, the line, the list of tools for what the
disk holds, the limit), the rows the kernel says at once and when the answer comes, and the chat box where every
line but `key` and `setup` goes to the model. Nothing runs when this file is imported."""
import re

from app_cases import clean, hide
from keyed_model import ORDER, KeyedChat

MODEL = "deepseek/deepseek-v4.1-flash-1017"
LIMIT = 1000
REQUEST_MOST = 45
WORDS_SHOWN = 300
NAME_LONGEST = 64

CHAT_INSTRUCTIONS = (
    "You are the voice of a small home-made operating system. "
    "The person at the machine types one line at a time into its chat box, and you see only that line, not the ones before it. "
    "Answer in plain words, in one or two short sentences, or use one of the tools when the person wants something done that a tool does. "
    "Use run_app for a kept app that fits the wish, and make_app only when none fits."
)

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
                "Use it only when the person wants an app and no kept app fits.",
                {"request": {"type": "string", "description": "What the app does, in at most 45 signs, such as: a dice that rolls"}},
                ["request"])


def run_app_tool(apps):
    """`apps`: (number, request) of the kept apps, the one kept last first."""
    told = ("Runs one of the kept apps again, as it was written, without writing it anew. The kept apps, by number: "
            + "; ".join("%d: %s" % (number, request) for number, request in apps) + ".")
    return tool("run_app", told, {"app": {"type": "integer", "enum": [number for number, _ in apps],
                                          "description": "The number of the kept app"}}, ["app"])


def pick_look_tool():
    return tool("pick_look", "Changes the colours of the whole screen to one of these looks, and keeps it for later starts: " + LOOKS_TOLD + ".",
                {"look": {"type": "integer", "enum": list(range(1, len(ORDER) + 1)), "description": "The number of the look"}}, ["look"])


def turn_page_tool(pages, shown):
    return tool("turn_page",
                "Shows another page of the panel of kept apps near the top left of the screen. It has %d pages, the app kept last first, "
                "and shows page %d now." % (pages, shown),
                {"page": {"type": "integer", "description": "The number of the page, from 1 to %d" % pages}}, ["page"])


def tools_meant(apps, shown=1):
    """The list of tools for a disk with these kept apps (the one kept last first), the panel showing page `shown`."""
    tools = [MAKE_APP]
    if apps:
        tools.append(run_app_tool(apps))
    tools.append(pick_look_tool())
    pages = -(-len(apps) // 5)
    if pages > 1:
        tools.append(turn_page_tool(pages, shown))
    return tools


def body_meant(line, apps, shown=1):
    """The whole request for a line, as Python's JSON reader reads it."""
    return {"model": MODEL, "messages": [{"role": "system", "content": CHAT_INSTRUCTIONS}, {"role": "user", "content": line}],
            "tools": tools_meant(apps, shown), "max_tokens": LIMIT, "stream": False}


# ---------- Rows ----------

ASKING = "Kernel: I am asking the model."
NO_KEY = 'Kernel: I cannot ask the model, because no key is kept. Send the line "key" first.'
NO_ADDRESS = "Kernel: I cannot ask the model, because this machine has no address on the network"
BUSY = "Kernel: I cannot ask the model, because the answer to what I asked before has not come yet"
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


def making(request):
    return 'Kernel: I am asking the model to make "%s".' % request


def running(request):
    return 'Kernel: I am running the app made for "%s".' % request


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
    """keyed_model.KeyedChat where every line but `key` and `setup` goes to the model (docs/chat.md): the row the
    kernel says at once. What comes later is added with say() (a row of the kernel's), model() (the model's words)
    and pick() (the tool pick_look)."""

    def key(self, sign):
        busy = self.secret_asked or self.waiting or self.look_asking
        if not busy and sign == "\n" and self.line and self.line not in ("key", "setup"):
            mine = self.person() + ": " + self.line
            if not self.secret_held:
                reply = NO_KEY
            elif self.network == "none":
                reply = NO_ADDRESS
            elif self.network == "busy":
                reply = BUSY
            else:
                reply = ASKING
            self.said += [mine, reply]
            self.add("person", mine)
            self.add("kernel", reply)
            if self.can_keep:
                self.kept.append(("last line", self.line.encode()))
            self.line = ""
            return
        super().key(sign)

    def row(self, text):
        """A whole row as it is, such as one that begins with "Model:"."""
        self.said.append(text)
        self.add("kernel", text)

    def model(self, words, key=""):
        self.row(model_row(words, key))

    def pick(self, number):
        """The tool pick_look: the look in use and kept, and the row about it."""
        if not 1 <= number <= len(ORDER):
            self.say("the model asked for look %d, but there are only %d looks." % (number, len(ORDER)))
            return
        name = ORDER[number - 1]
        self.look = name
        named = "look %d, %s" % (number, name)
        if not self.can_keep:
            self.say("this is %s. It lasts until the machine is switched off, because there is no notebook to keep it in." % named)
        elif self.look_kept == name:
            self.say("this is %s, which is kept on the disk already." % named)
        else:
            self.look_kept = name
            self.look_answered = True
            self.kept.append(("look", name.encode()))
            self.say("this is %s. It is kept on the disk." % named)


def tokens_lines(lines):
    """The terminal's lines about tokens."""
    return [line for line in lines if line.startswith("Tokens:")]


def key_pieces(text, key, least=6):
    """Whether a piece of the key, six signs long, stands anywhere in `text`."""
    return any(key[start:start + least] in text for start in range(len(key) - least + 1))


def only_plain(text):
    return re.fullmatch(r"[ -~]*", text) is not None
