"""The stand-in provider's answers to a request for an app, and an outside model of what the kernel is meant
to make of them. Shared by tls/model_server.py (which sends the answers) and test_app.py (which judges the
kernel). The model of the kernel's rules is written here from docs/apps.md and the design, not from the
kernel's code."""

# A small app, as a model might write it.
SCRIPT = 'local sides = 6\nlocal roll = math.random(1, sides)\nprint("You rolled a " .. roll)\nshow("Dice: " .. roll)\n'

# Exactly as long as the box takes (32768 bytes), and one byte longer.
EXACT = "\n".join(["-- " + "a" * 60] * 511 + ["-- " + "a" * 61])
OVER = EXACT + "b"
assert len(EXACT) == 32768 and len(OVER) == 32769

# Tabs, both kinds of line end, signs that are not plain, a line longer than 200 signs, empty lines, spaces at
# the ends of lines, and a line of spaces only.
ODD = ("local t = {}\n\tfor i = 1, 3 do\r\n\t\tt[i] = i * 2\n\tend\nprint(\"tab\\there\")\n"
       "-- \x1b[31mred\x07 bell\nlocal s = \"é中\"\n-- " + "z" * 300 + "\n\n   \nshow(\"done\")   \n\n\n")

# The script the real model wrote in a person's own run (pasted back), a dice of six faces drawn with signs.
FACES = ["[     o     ]", "[  o     o  ]", "[  o  o  o  ]", "[ o  o  o  o ]", "[ o o o o o ]", "[o o o o o o]"]
REAL = ("local faces = {\n" + "".join('  "%s",\n' % face for face in FACES[:5]) + '  "%s"\n}\n' % FACES[5] +
        'for i = 1, 8 do\n  show("Rolling " .. faces[math.random(1, 6)])\nend\n'
        'local n = math.random(1, 6)\nshow("Rolled " .. n .. " " .. faces[n])')

# Scripts that are run, each with a known outcome (see run_expect below).
RUN_SCRIPTS = {
    "runshow": 'show("Hello from the app")',
    "runprint": 'print("one")\nprint("two", 3)',
    "runcut": 'show(string.rep("ab", 30))',
    "runcut41": 'show("' + "c" * 41 + '")',
    "runexact40": 'show("' + "d" * 40 + '")',
    "runsplit": 'show("a" .. string.rep("é", 20))',
    "runloop": "while true do end",
    "runmemory": 'local t = {}\nwhile true do\n  t[#t + 1] = string.rep("x", 4096)\nend',
    "runmistake": 'local a = 1\nlocal b = 2\nlocal c = nil + 1\nshow("never")',
    "runsyntax": "Here is your app, enjoy it!",
    "runmanyshow": "for i = 1, 21 do\n  show(i)\nend",
    "runmanyprint": "for i = 1, 101 do\n  print(i)\nend",
    "runrandom": "print(math.random(1, 1000000), math.random(1, 1000000))",
    "runreal": REAL,
    "runslow": 'local s = ""\nwhile true do\n  s = string.rep("x", 100) .. "y"\nend',
    "runnil": "show()",
    "runrecurse": "local function deeper(n)\n  return deeper(n + 1) + 1\nend\nshow(deeper(1))",
}

INSTRUCTIONS = (
    "You write small apps for a home-made operating system. Each app is one script in the language Lua 5.4. "
    "Answer with the script only: no words before or after it, and no ``` marks around it.\n"
    "\n"
    "The script runs once, from its first line to its last, and then ends. It runs in a locked box: it cannot read keys, "
    "files, the clock or the network, and it cannot wait. Lua's string, table and math libraries are there; io, os, "
    "require, debug, coroutine and utf8 are not. math.random works.\n"
    "\n"
    "Two functions put out what the app has to say:\n"
    "- show(text) puts one line of at most 40 characters in a box on the screen. This is what the person "
    "at the machine sees. Each show replaces the line shown before, and the last one stays on the screen after the "
    "script has ended. A longer text is cut at 40 characters, and a 21st show stops the script.\n"
    "- print(...) writes one line to a log beside the screen. A line longer than 200 characters is cut, and a 101st "
    "print stops the script.\n"
    "\n"
    "Use only plain English letters, digits and the signs of a US keyboard; any other character comes out as a dot.\n"
    "\n"
    "The script's budget of work is small, about four thousand rounds of a simple loop in all, so keep loops short. "
    "A script longer than 32 KB is refused.\n"
    "\n"
    "If the request cannot be done with these, write a script that shows in a few words what cannot be done.\n"
)
LEAD = "Make this app: "
TOKENS = 4000


def answer(kind, bearer):
    """The message and the way the answer ended, for each kind of answer to a request for an app. None if the
    kind is not one of these."""
    a = {"role": "assistant"}
    table = {
        "app": ({**a, "content": SCRIPT}, "stop"),
        "appfenced": ({**a, "content": "```lua\n" + SCRIPT + "```"}, "stop"),
        "appprose": ({**a, "content": "Here is your app:\n\n```lua\n" + SCRIPT + "```\n\nEnjoy it!"}, "stop"),
        "appopen": ({**a, "content": "```lua\n" + SCRIPT}, "stop"),
        "appclose": ({**a, "content": SCRIPT + "```\n"}, "stop"),
        "apptwo": ({**a, "content": "```lua\nprint(1)\n```\nor else\n```lua\nprint(2)\n```\n"}, "stop"),
        "appmarksonly": ({**a, "content": "```lua\n```"}, "stop"),
        "appcut": ({**a, "content": "local sides = 6\nlocal roll = math.ran"}, "length"),
        "appfiltered": ({**a, "content": SCRIPT}, "content_filter"),
        "appthink": ({**a, "content": "", "reasoning_content": "Let me think about the dice. " * 300}, "length"),
        "appnull": ({**a, "content": None}, "stop"),
        "appexact": ({**a, "content": EXACT}, "stop"),
        "appover": ({**a, "content": OVER}, "stop"),
        "appodd": ({**a, "content": ODD}, "stop"),
        "appecho": ({**a, "content": 'local key = "' + bearer + '"\nprint(key)\nshow("hello")\n'}, "stop"),
        "apppieces": ({**a, "content": [{"type": "text", "text": SCRIPT}]}, "stop"),
        "appspaces": ({**a, "content": "\n\n   " + SCRIPT + "   \n\n"}, "stop"),
        "appcrlf": ({**a, "content": SCRIPT.replace("\n", "\r\n")}, "stop"),
        "appnoending": ({**a, "content": SCRIPT}, None),
        "apponeline": ({**a, "content": "show(\"hi\")"}, "stop"),
    }
    for name, script in RUN_SCRIPTS.items():
        table[name] = ({**a, "content": script}, "stop")
    return table.get(kind)


# ---------- What a run is meant to give, worked out by hand from Lua's rules and the kernel's ----------

RAN = "the app ran to its end."
SHOWED_NOTHING = "the app ran to its end, but it showed nothing on the screen."
MISTAKE = "the app was stopped, because it has a mistake in it; the terminal says which."
TOO_MUCH_WORK = "the app was stopped, because it did too much work."
GAVE_UP = "the app was stopped, because the interpreter gave up, most likely for lack of memory."
DICE_KINDS = ["app", "appfenced", "appprose", "appopen", "appclose", "apppieces", "appspaces", "appcrlf", "appnoending", "slowapp"]


def run_expect(kind, key):
    """For a kind whose script is taken and run: (the row after the run, a judge of the App lines, a giver of the
    texts the box may show after the run). The judge takes the run's App lines and says whether they are as meant.
    The giver takes them too and gives the texts the box may show; an empty list means the box keeps what it showed
    before. None for a kind whose script is not run."""
    exactly = lambda wanted: (lambda lines: lines == wanted)
    nothing = exactly([])
    keeps = lambda lines: []
    shows = lambda text: (lambda lines: [text])

    def dice_lines(lines):
        return len(lines) == 1 and lines[0] in ["App: You rolled a %d" % n for n in range(1, 7)]

    def dice_panel(lines):
        return ["Dice: " + lines[0][len("App: You rolled a "):]] if dice_lines(lines) else ["(no such line)"]

    def stopped_at(line_number):
        prefix = 'App: Lua stopped: [string "app"]:%d:' % line_number
        return lambda lines: len(lines) == 1 and lines[0].startswith(prefix)

    def random_line(lines):
        if len(lines) != 1 or not lines[0].startswith("App: "):
            return False
        numbers = lines[0][len("App: "):].split(" ")
        return len(numbers) == 2 and all(n.isdigit() and 1 <= int(n) <= 1000000 for n in numbers)

    if kind in DICE_KINDS:
        return RAN, dice_lines, dice_panel
    table = {
        "apptwo": (SHOWED_NOTHING, exactly(["App: 1"]), keeps),
        "apponeline": (RAN, nothing, shows("hi")),
        "appexact": (SHOWED_NOTHING, nothing, keeps),
        "appodd": (RAN, exactly(["App: tab.here"]), shows("done")),
        "appecho": (RAN, exactly(["App: " + "*" * len(key)]) if len(key) >= 6 else None, shows("hello")),
        "runshow": (RAN, nothing, shows("Hello from the app")),
        "runprint": (SHOWED_NOTHING, exactly(["App: one", "App: two 3"]), keeps),
        "runcut": (RAN, nothing, shows("ab" * 20)),
        "runcut41": (RAN, nothing, shows("c" * 40)),
        "runexact40": (RAN, nothing, shows("d" * 40)),
        "runsplit": (RAN, nothing, shows("a" + "." * 39)),
        "runloop": (TOO_MUCH_WORK, nothing, keeps),
        "runmemory": (GAVE_UP, nothing, keeps),
        "runmistake": (MISTAKE, stopped_at(3), keeps),
        "runsyntax": (MISTAKE, stopped_at(1), keeps),
        "runmanyshow": ("the app was stopped, because it showed too many texts.", nothing, shows("20")),
        "runmanyprint": ("the app was stopped, because it printed too many texts.", exactly(["App: %d" % n for n in range(1, 101)]), keeps),
        "runrandom": (SHOWED_NOTHING, random_line, keeps),
        "runreal": (RAN, nothing, lambda lines: ["Rolled %d %s" % (n, FACES[n - 1]) for n in range(1, 7)]),
        "runslow": (TOO_MUCH_WORK, nothing, keeps),
        "runnil": (RAN, nothing, shows("nil")),
        # Calls without end: the fuel runs out before anything else does (seen, and so meant).
        "runrecurse": (TOO_MUCH_WORK, nothing, keeps),
    }
    return table.get(kind)


# ---------- An outside model of what the kernel is meant to do with such answers ----------

def rust_lines(text):
    """Lines as Rust's str::lines() gives them: split at each byte 10, one byte 13 at the end of a line
    dropped, and no line after a last byte 10."""
    if text == "":
        return []
    pieces = text.split("\n")
    if pieces[-1] == "":
        pieces.pop()
    return [piece[:-1] if piece.endswith("\r") else piece for piece in pieces]


def script_meant(words):
    """The script the kernel is meant to take out of the model's words, or None when there is none."""
    lines = rust_lines(words)
    marks = [place for place, line in enumerate(lines) if line.lstrip().startswith("```")]
    if not marks:
        kept = lines
    elif len(marks) == 1:
        only = marks[0]
        kept = lines[only + 1:] if all(line.strip() == "" for line in lines[:only]) else lines[:only]
    else:
        kept = lines[marks[0] + 1:marks[1]]
    script = "\n".join(kept).strip()
    return script


def clean(text):
    out = []
    for byte in text.encode("utf-8", "surrogatepass"):
        if byte == 13:
            continue
        out.append(chr(byte) if 32 <= byte <= 126 else ".")
    return "".join(out)


def hide(words, key):
    """A star over every run of signs that stands in the key and is six signs long or longer, or over the whole
    key if it is shorter."""
    least = min(6, len(key))
    if least == 0:
        return words
    marks = [False] * len(words)
    for start in range(len(words)):
        for key_start in range(len(key)):
            same = 0
            while start + same < len(words) and key_start + same < len(key) and words[start + same] == key[key_start + same]:
                same += 1
            if same >= least:
                for place in range(start, start + same):
                    marks[place] = True
    return "".join("*" if mark else sign for sign, mark in zip(words, marks))


def listing_meant(script):
    """The terminal's lines for a script: its number, and the line cleaned with a tab as two spaces, cut at
    200 signs."""
    out = []
    for number, line in enumerate(rust_lines(script), 1):
        shown = clean(line.replace("\t", "  "))[:200]
        out.append("Script %d:" % number if shown == "" else "Script %d: %s" % (number, shown))
    return out


def outcome(kind, key):
    """(the sentence the kernel is meant to say, the terminal lines of the script) for an app kind."""
    message, ending = answer(kind, key)
    content = message.get("content")
    if isinstance(content, list):
        content = content[0]["text"]
    words = (content or "").strip() if isinstance(content, str) else None
    if words:
        if ending == "length":
            return "the model's app was cut off at the limit of %d tokens, so it is not whole." % TOKENS, []
        if ending == "content_filter":
            return "the provider held part of the model's app back, so it is not whole.", []
        script = script_meant(words)
        if script == "":
            return "the model's answer is no app, because there is no script in it.", []
        if len(script.encode()) > 32768:
            return "the model's answer is no app, because the script is %d bytes long, and the box takes at most 32768." % len(script.encode()), []
        script = hide(script, key)
        count = len(rust_lines(script))
        return "the model wrote an app of %d %s. It is shown in the terminal." % (count, "line" if count == 1 else "lines"), listing_meant(script)
    # No words.
    thought = bool((message.get("reasoning_content") or "").strip())
    if ending is None and words is None:
        return None, []
    why = ""
    if ending == "length" and thought:
        why = ", because it spent all of its %d tokens thinking" % TOKENS
    elif ending == "length":
        why = ", because it reached the limit of %d tokens" % TOKENS
    elif ending == "content_filter":
        why = ", because the provider held it back"
    return "the model's answer was empty%s." % why, []
