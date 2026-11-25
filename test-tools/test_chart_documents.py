"""Bar charts (docs/screen.md "A bar chart" and "Documents", docs/tools.md `draw_chart`): charts the model draws in the
frame, kept on the disk as documents, opened again and changed by a wish. Every scenario boots the stand-in copy of the
project (net_copy.py); the stand-in answers each line with the tool the scenario names (chart_cases.py, through
text_document_cases.py and chat_cases.py). What the kernel is meant to say, send and show comes from chart_model.py,
documents_model.py and chat_tools_model.py, written from the notes; every request for a line is compared whole, every
picture dot for dot, and the disk file is read from outside. Made-up key only.

  draw      the thing this part is done by: "draw a bar chart of how many moons each planet has" draws eight bars in the
            model's green, kept as document 1, a chart; "add Pluto with 5 moons" goes with the chart's lines and is kept
            as its second version; a table of fruit prices takes the frame; after a restart the panel lists both, and
            "open the moons chart" draws it again and goes back; F1 and a key bring it back; in Night the green, too
            faint on Night's dark grey, gives way to Night's frame colour; `setup` empties the frame.
  odd       numbers below zero, with decimals and commas, in a yellow too faint on light grey, where Blue's frame
            colour is too faint as well, so the letters' colour; every number below zero; every number zero; more bars
            than fit, bars without a number, lines after the first bar, a title longer than the frame and long labels,
            which goes back; long numbers at both ends of the scale, where only the right one is written; a chart
            without a title or a document line, named by its number, whose lines go with the next line; that chart
            drawn again as a table with draw_table, told as a table, and then as a chart once more.
  cut       a change cut off at the limit of tokens, not drawn, the chart as it was; a new chart longer than the bound on
            what the tool is given, drawn as far as its bars came whole and not kept; one with the key in a label, kept
            with stars; inputs without a chart, and a chart without a number that reads, turned down; a change asked
            for a document that is not open, which opens it, and the change that comes with the next ask; a change
            asked for a document that is not kept.
  broken    answers that break off on their way: a change of a kept chart is not drawn and the chart stays as it was;
            a new chart draws its bars that came whole and is not kept; one that broke off before any bar came whole is
            turned down; the line ends there.
  nodocs    a disk without a notebook: documents cannot be kept, so draw_chart is not offered, and asked for anyway it
            is turned down.
  small     a screen of 800 by 600 dots has no room for the frame, so documents cannot be kept there though the disk has a
            notebook: draw_chart is not offered, and asked for anyway it is turned down.

Usage: python test_chart_documents.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, chart_breaks.py), BOOS_PORT_BASE, BOOS_PROVIDER ("anthropic": every line goes
to Anthropic, in Anthropic's form; the rows, pictures and requests meant are the same)."""
import json
import os

os.environ["DIVIDED_DISK"] = ""

import chart_cases as cases
import chart_model as model
import chat_cases
import document_cases
import documents_model
from app_cases import hide
from chart_breaks import BREAKS
from chat_tools_model import CUT_OFF, ToolsChat, body_again, body_meant, key_pieces, model_row
from disk_helpers import make
from documents_model import (KIND_CHART, closed_row, documents_of, kept_line, kept_row, no_such_change_row, not_kept_row,
                             opened_row, start_lines)
from look_values import LOOKS
from net_copy import build
from table_model import drawn
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import AGAIN, BROKE, back, check_body, exchange, no_key_in, pieces_of, posts, rounds_since
from test_documents import Requests, documents_lines, new_chat, start_documents_lines
from test_text_documents import check_things, table_document, unfinished

T = chat_cases.TOKENS_LINE
NIGHT = "Kernel: this is look 2, Night. It is kept on the disk."
_copy = []


def kernel():
    """The stand-in copy, built once, with the break named by BREAK if there is one (of chart_breaks.py)."""
    if not _copy:
        name = os.environ.get("BREAK")
        if name:
            print("BREAK", name)
        _copy.append(build(PORT, roots=["a"], more=BREAKS[name] if name else None))
    return _copy[0]


def start(tag, disk, behaviours=()):
    return Run(tag, disk, behaviours=behaviours, kernel_file=kernel())


def document(number, version, name, number_line=None):
    """A chart as these tests follow it: kept from the chart `name` of chart_cases.py, written with the line
    "document N" in front when `number_line` is given."""
    written = cases.text(name, number_line)
    return dict(number=number, version=version, name=model.name_of(written), lines=model.lines_kept(written), kind=KIND_CHART)


def holds_chart(chart):
    """A step for `exchange`: from then on the frame shows this chart (chart_model.py)."""
    def step(chat):
        chat.chart, chat.table, chat.text = chart, None, None
    return step


def holds_table(table):
    """A step for `exchange`: from then on the frame shows this table (table_model.py)."""
    def step(chat):
        chat.table, chat.chart, chat.text = table, None, None
    return step


def meant_screen(chat, documents, open_number, width=1280, height=800):
    """The whole screen meant: documents_model.screen's, with the chart the chat model holds painted over the frame
    (nothing else lies there)."""
    picture = documents_model.screen(width, height, chat, [], documents, open_number)
    if getattr(chat, "chart", None) is not None:
        model.paint(picture, chat.chart, getattr(chat, "look", "Blue"))
    return picture


def keys_change_nothing(run, chat, tag, documents, open_number):
    """Page Down and Page Up while the frame shows a chart: the screen stays as it was, and nothing is asked or said."""
    asked = len(posts(run))
    run.mark()
    run.m.named_key("pgdn", pause=0.3)
    run.m.named_key("pgup", pause=0.3)
    run.shot(tag, meant_screen(chat, documents, open_number))
    said = [line for line in run.since() if line.startswith(("You:", "Kernel:", "Model:", "Tokens:", "Tool:", "Round ", "Documents:"))]
    quiet = len(posts(run)) == asked and said == []
    report(run.tag + " " + tag + " asks and says nothing", quiet, None if quiet else "got %r" % said[-3:])


def nothing_more_kept(tag, found, names_meant):
    names = sorted(name for name in found if name.startswith("document"))
    report(tag + " nothing more kept", names == names_meant, "got %r" % names)


# ---------- The scenarios ----------

def scenario_draw():
    print("draw: the moons of the planets drawn as a bar chart and kept, Pluto added by a wish, a table after it, a "
          "restart, an open, F1, Night, and setup")
    disk, _ = answered_disk("chart-draw")
    run = start("chart-draw", disk, ["chart=moons:0", "chart=pluto:1", "doc=fruit:0"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The moons, drawn whole in the model's green, which stands out from Blue's light grey: kept as document 1, which
    # is open; the line ends.
    line = "draw a bar chart of how many moons each planet has"
    moons = document(1, 1, "moons", 0)
    chart, said, whole = model.drawn(cases.text("moons", 0))
    report("draw the moons are meant whole, eight bars", whole and len(chart["bars"]) == 8, said)
    report("draw the green stands out in Blue", model.bar_colour(chart["colour"], "Blue") == (0x2E, 0x7D, 0x32))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_chart(chart)])
    report("draw a chart drawn whole does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    meant.line(line, [])
    run.shot("moons", meant_screen(chat, [moons], 1))
    keys_change_nothing(run, chat, "moons-keys", [moons], 1)

    # A change by a wish: the line goes with the chart's lines; the model draws the whole chart again, beginning with
    # "document 1", and it is kept as the document's second version.
    line = "add Pluto with 5 moons"
    pluto = document(1, 2, "pluto", 1)
    chart, said, whole = model.drawn(cases.text("pluto", 1))
    report("draw Pluto is meant whole, nine bars", whole and len(chart["bars"]) == 9, said)
    exchange(run, chat, line, [T, kept_row(said, 1, changed=True), holds_chart(chart)])
    meant.line(line, [moons], moons)
    run.shot("pluto", meant_screen(chat, [pluto], 1))

    # A table takes the frame: document 2, open.
    line = "now a table of fruit prices"
    fruit = table_document(2, 1, "fruit")
    table, said, _ = drawn(document_cases.text("fruit", 0))
    exchange(run, chat, line, [T, kept_row(said, 2), holds_table(table)])
    meant.line(line, [pluto], pluto)
    run.shot("fruit", meant_screen(chat, [fruit, pluto], 2))
    lines = run.end()
    kept = [kept_line(1, 1), kept_line(1, 2), kept_line(2, 1)]
    report("draw the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("draw", run)
    found = check_things("draw", disk, [pluto, fruit], versions=[(1, 1, moons["lines"])])
    no_key_in("draw", lines)

    # After a restart nothing is open and the frame is empty; the panel lists both, the one changed last first. Opening
    # the chart draws it again, and goes back to the model, which answers in words.
    again = start("chart-draw-2", disk, ["open=1", "look=2"])
    chat = new_chat(b"now a table of fruit prices")
    give_key(again, chat)
    meant = Requests(chat)
    got = start_documents_lines(again.lines())
    report("draw restart the lines about documents", got == start_lines(documents_of(found)), "got %r" % got)
    again.shot("restart", meant_screen(chat, [fruit, pluto], None))
    line = "open the moons chart"
    chart, _, _ = model.drawn(pluto["lines"])
    exchange(again, chat, line, [T, opened_row(pluto, model.opened_fit(chart)), holds_chart(chart)] + back())
    meant.line(line, [fruit, pluto])
    meant.again(line, 0, [pluto, fruit], pluto)
    again.shot("opened", meant_screen(chat, [pluto, fruit], 1))

    # The kernel's own lines over the screen (F1), and a key that brings the usual picture back, with the chart
    # (Backspace, which takes nothing away from an empty line).
    again.m.named_key("f1", pause=1)
    again.m.named_key("backspace", pause=0.5)
    again.shot("after-f1", meant_screen(chat, [pluto, fruit], 1))

    # Night paints the whole screen again: the model's green does not stand out from Night's dark grey, so the bars
    # take Night's frame colour, which does.
    line = "make it night"
    report("draw the green gives way to Night's frame colour", model.bar_colour(chart["colour"], "Night") == LOOKS["Night"]["panel_frame"])
    exchange(again, chat, line, [T, NIGHT])
    chat.look, chat.look_kept = "Night", "Night"
    meant.line(line, [pluto, fruit], pluto)
    again.shot("night", meant_screen(chat, [pluto, fruit], 1))

    # `setup`: the open chart is closed and the frame empties, and the first look comes back at once (docs/look.md);
    # the documents stay listed.
    again.mark()
    again.press("setup\n", chat)
    asked = again.wait_line("Kernel: what should I call you?", timeout=30)
    report("draw setup asks for the name", asked is not None, None if asked else "the question never came")
    chat.chart = chat.table = chat.text = None
    chat.look = "Blue"
    again.shot("setup", meant_screen(chat, [pluto, fruit], None))
    lines = again.end()
    meant.check("draw restart", again)
    no_key_in("draw restart", lines)


def scenario_odd():
    print("odd: numbers below zero, decimals and commas, a faint colour, bars that do not fit or have no number, long "
          "numbers at both ends, a chart without a title, and every number zero")
    disk, _ = answered_disk("chart-odd")
    run = start("chart-odd", disk, ["chart=temperatures:0", "chart=frozen:0", "chart=flat:0", "chart=many:0", "chart=wide:0",
                                    "chartbare=fruit", "words=Hello.", "doc=fruit:6", "chart=fruit:6"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    kept = []

    def whole_one(line, number, name, tag):
        """A chart drawn whole: kept as document `number`, open, and the line ends."""
        one = document(number, 1, name, 0 if name != "fruit" else None)
        chart, said, whole = model.drawn(cases.text(name, 0 if name != "fruit" else None))
        report("odd the %s chart is meant whole" % name, whole, said)
        exchange(run, chat, line, [T, kept_row(said, number), holds_chart(chart)])
        meant.line(line, list(kept), kept[0] if kept else None)
        kept.insert(0, one)
        run.shot(tag, meant_screen(chat, kept, number))
        return one, chart

    # Below zero, with decimals and commas, and a capital word with a colon: the yellow asked for is too faint on
    # Blue's light grey, and so is Blue's orange frame, so the bars take the letters' colour.
    _, chart = whole_one("the coldest days", 1, "temperatures", "temperatures")
    report("odd the yellow gives way to the letters' colour", chart["colour"] == (0xFF, 0xEB, 0x3B)
           and model.bar_colour(chart["colour"], "Blue") == LOOKS["Blue"]["panel_text"])
    # Every number below zero: the zero point at the right end. Every number zero: no bar has a length.
    whole_one("frozen worlds", 2, "frozen", "frozen")
    whole_one("nothing at all", 3, "flat", "flat")

    # More bars than fit, bars without a number, and lines after the first bar that do not count: 14 bars drawn and
    # kept with all the lines, and that goes back; the title cut to the frame's room as drawn, and to 45 signs as its
    # name.
    line = "many bars please"
    many = document(4, 1, "many", 0)
    chart, said, whole = model.drawn(cases.text("many", 0))
    report("odd the many are meant with bars left out", not whole and len(chart["bars"]) == 14 and chart["left_out"] == 2
           and chart["unread"] == 3 and chart["colour"] is None, said)
    report("odd the long title is cut", len(chart["title"]) == 46 and many["name"] == "Many bars ... more than fit in the frame, so",
           "got %r, %r" % (chart["title"], many["name"]))
    exchange(run, chat, line, [T, kept_row(said, 4), holds_chart(chart)] + back())
    meant.line(line, list(kept), kept[0])
    kept.insert(0, many)
    meant.again(line, 0, list(kept), many)
    run.shot("many", meant_screen(chat, kept, 4))

    # Long numbers at both ends of the scale: the two texts would meet, so only the right one is written.
    whole_one("a wide range", 5, "wide", "wide")
    # A chart without a title or a document line: a new one, named by its number.
    fruit, _ = whole_one("fruit as a chart", 6, "fruit", "fruit")
    report("odd the untitled one is named by its number", fruit["name"] == "" and documents_model.listed(fruit) == "document 6")

    # The next line goes with the untitled chart's lines, told as a chart's.
    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, list(kept), fruit)

    # The untitled chart drawn again as a table with draw_table: its second version is a table, and the next line goes
    # with its lines as a table's; drawn again with draw_chart, its third version is a chart once more.
    line = "make the fruit a table"
    table = table_document(6, 2, "fruit")
    drawn_table, said, _ = drawn(document_cases.text("fruit", 6))
    exchange(run, chat, line, [T, kept_row(said, 6, changed=True), holds_table(drawn_table)])
    meant.line(line, list(kept), fruit)
    kept[0] = table
    run.shot("fruit-table", meant_screen(chat, kept, 6))
    line = "and a chart again"
    fruit_again = document(6, 3, "fruit", 6)
    chart, said, _ = model.drawn(cases.text("fruit", 6))
    exchange(run, chat, line, [T, kept_row(said, 6, changed=True), holds_chart(chart)])
    meant.line(line, list(kept), table)
    kept[0] = fruit_again
    run.shot("fruit-chart-again", meant_screen(chat, kept, 6))
    lines = run.end()
    meant.check("odd", run)
    found = check_things("odd", disk, kept, versions=[(6, 1, fruit["lines"]), (6, 2, table["lines"])])
    nothing_more_kept("odd", found, sorted([name for n in range(1, 7) for name in ("document %d" % n, "document %d v1" % n)]
                                           + ["document 6 v2", "document 6 v3"]))
    no_key_in("odd", lines)


def scenario_cut():
    print("cut: a change cut off, a chart past the bound, the key, refusals, a change for a closed document, and one for "
          "no kept document")
    disk, _ = answered_disk("chart-cut")
    behaviours = ["chart=moons:0", "chartcut=pluto:1", "chartlong", "chartkey", "chartbad", "chart=none:0", "chartbare=fruit",
                  "chart=pluto:1", "again:chart=pluto:1", "chart=moons:9", "words=Hello."]
    run = start("chart-cut", disk, behaviours)
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    line = "a chart of the moons"
    moons = document(1, 1, "moons", 0)
    moons_chart, said, _ = model.drawn(cases.text("moons", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_chart(moons_chart)])
    meant.line(line, [])

    # A change that the limit of tokens cut off: not drawn, and that goes back; the chart stays as it was.
    line = "add pluto"
    exchange(run, chat, line, [CUT_OFF, T, model.cut_change_row(1)] + back())
    meant.line(line, [moons], moons)
    meant.again(line, 0, [moons], moons)
    run.shot("cut-change", meant_screen(chat, [moons], 1))

    # A new chart longer than the bound on what the tool is given: cut there, its bars that came whole drawn, not
    # kept, and nothing is open then; that goes back.
    line = "a very long chart"
    given = json.dumps({"chart": cases.LONG})
    report("cut the long one is meant past the bound", len(given) > cases.CHART_INPUTS_LONGEST, "%d bytes" % len(given))
    long_chart, said, whole = model.drawn(cases.long_cut(), whole=False)
    report("cut the long one is meant cut off", not whole and said.endswith("it was cut off, so I drew only the bars that came whole."), said)
    exchange(run, chat, line, [T, not_kept_row(said), holds_chart(long_chart)] + back())
    meant.line(line, [moons], moons)
    meant.again(line, 1, [moons])
    run.shot("long", meant_screen(chat, [moons], None))

    # A chart with the key in a label: starred where it came in, on the screen, on the disk and in every request.
    line = "a chart with my key"
    keys = dict(number=2, version=1, name="Keys", lines=model.lines_kept(hide(cases.key_chart(KEY), KEY)), kind=KIND_CHART)
    chart, said, _ = model.drawn(cases.key_chart(KEY), key=KEY)
    exchange(run, chat, line, [T, kept_row(said, 2), holds_chart(chart)])
    meant.line(line, [moons])
    run.shot("key", meant_screen(chat, [keys, moons], 2))

    # Inputs that hold no chart, and a chart without a number that reads: turned down, the frame as it was; each goes
    # back.
    for place, (line, row) in enumerate([("the wrong name", model.CANNOT_READ), ("a chart without numbers", model.NOTHING)]):
        exchange(run, chat, line, [T, row] + back())
        meant.line(line, [keys, moons], keys)
        meant.again(line, 2 + place, [keys, moons], keys)
    run.shot("refused", meant_screen(chat, [keys, moons], 2))

    # A chart without a document line: a new one, without a title, named by its number.
    line = "fruit as a chart"
    fruit = document(3, 1, "fruit")
    chart, said, _ = model.drawn(cases.text("fruit"))
    exchange(run, chat, line, [T, kept_row(said, 3), holds_chart(chart)])
    meant.line(line, [keys, moons], keys)

    # A change asked for document 1 while document 3 is open: document 1 is opened, not changed, and that goes back;
    # the next ask goes with its lines, and the change it brings is kept.
    line = "add pluto to the moons"
    pluto = document(1, 2, "pluto", 1)
    pluto_chart, said, _ = model.drawn(cases.text("pluto", 1))
    exchange(run, chat, line, [T, closed_row(1), holds_chart(moons_chart), AGAIN, T, kept_row(said, 1, changed=True), holds_chart(pluto_chart)])
    meant.line(line, [fruit, keys, moons], fruit)
    meant.again(line, 4, [moons, fruit, keys], moons)
    run.shot("closed", meant_screen(chat, [pluto, fruit, keys], 1))

    # A change asked for a document that is not kept: turned down, the chart as it was; that goes back.
    line = "change document nine"
    exchange(run, chat, line, [T, no_such_change_row(9)] + back())
    meant.line(line, [pluto, fruit, keys], pluto)
    meant.again(line, 5, [pluto, fruit, keys], pluto)

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [pluto, fruit, keys], pluto)
    run.shot("hello", meant_screen(chat, [pluto, fruit, keys], 1))
    lines = run.end()

    kept = [kept_line(1, 1), kept_line(2, 1), kept_line(3, 1), kept_line(1, 2)]
    report("cut the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("cut", run)
    found = check_things("cut", disk, [pluto, keys, fruit], versions=[(1, 1, moons["lines"])])
    nothing_more_kept("cut", found, ["document 1", "document 1 v1", "document 1 v2", "document 2", "document 2 v1", "document 3",
                                     "document 3 v1"])
    report("cut no piece of the key in the chart's lines",
           not key_pieces(found.get("document 2 v1", (0, b""))[1].decode(errors="replace"), KEY))
    everything = "\n".join(json.dumps(note_.get("body")) for note_ in posts(run))
    report("cut no piece of the key in any request", not key_pieces(everything, KEY))
    no_key_in("cut", lines)


def scenario_broken():
    print("broken: answers that break off on their way: a change of a kept chart, a new chart, and one with no bar whole")
    disk, _ = answered_disk("chart-broken")
    run = start("chart-broken", disk, ["chart=moons:0", "cut:chart=pluto:1", "cut:chart=moons:0", "cut:chart=temperatures:0",
                                       "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    none = chat_cases.NO_TOKENS_LINE

    line = "a chart of the moons"
    moons = document(1, 1, "moons", 0)
    chart, said, _ = model.drawn(cases.text("moons", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_chart(chart)])
    meant.line(line, [])

    # A change in an answer that broke off: not drawn, and the chart stays as it was; the line ends there.
    line = "add pluto"
    given = chat_cases.stream_sent(pieces_of("cut:chart=pluto:1"))[1]
    report("broken the change's document line came", unfinished(given, "chart").startswith("document 1\n"), "got %r" % given[:40])
    exchange(run, chat, line, [BROKE, none, model.cut_change_row(1)])
    meant.line(line, [moons], moons)
    report("broken a broken change does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    run.shot("change", meant_screen(chat, [moons], 1))

    # A new chart in an answer that broke off: its bars that came whole are drawn, it is not kept, and nothing is open
    # then; the line ends there.
    line = "the moons once more"
    given = chat_cases.stream_sent(pieces_of("cut:chart=moons:0"))[1]
    chart, said, whole = model.drawn(unfinished(given, "chart"), whole=False)
    report("broken the new one is meant with some of its bars", chart is not None and not whole, said)
    exchange(run, chat, line, [BROKE, none] + ([not_kept_row(said), holds_chart(chart)] if chart else [said]))
    meant.line(line, [moons], moons)
    run.shot("new", meant_screen(chat, [moons], None))

    # One that broke off before any of its bars came whole: turned down, the frame as it was.
    line = "the coldest days"
    given = chat_cases.stream_sent(pieces_of("cut:chart=temperatures:0"))[1]
    chart, said, _ = model.drawn(unfinished(given, "chart"), whole=False)
    report("broken the cold one is meant with no bar whole", chart is None and said == model.CUT_EARLY, said)
    exchange(run, chat, line, [BROKE, none] + ([not_kept_row(said), holds_chart(chart)] if chart else [said]))
    meant.line(line, [moons])
    run.shot("early", meant_screen(chat, [moons], None))

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [moons])
    lines = run.end()
    meant.check("broken", run)
    found = check_things("broken", disk, [moons])
    nothing_more_kept("broken", found, ["document 1", "document 1 v1"])
    no_key_in("broken", lines)


def scenario_nodocs():
    print("nodocs: a disk without a notebook, where documents cannot be kept: draw_chart is not offered, nor done")
    disk = make("chart-nodocs.img", "16M")
    run = Run("chart-nodocs", disk, behaviours=["chart=moons:0"], kernel_file=kernel())
    chat = ToolsChat(1280, notebook=None, kept_look=None)
    give_key(run, chat)
    line = "draw a chart of the moons"
    exchange(run, chat, line, [T, model.NOT_HERE] + back())
    run.shot("nodocs", documents_model.screen(1280, 800, chat, [], []))
    meant_bodies = [body_meant(line, [], record=chat.records[-1], key=KEY, files=None),
                    body_again(line, [], chat.agains[0], key=KEY, files=None)]
    lines = run.end()
    seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
    report("nodocs requests for a line", len(seen) == len(meant_bodies), "%d, meant %d" % (len(seen), len(meant_bodies)))
    for number, (note_, body) in enumerate(zip(seen, meant_bodies)):
        check_body("nodocs request %d" % (number + 1), note_, body)
    no_key_in("nodocs", lines)


def scenario_small():
    print("small: a screen of 800 by 600 dots has no room for the frame, so documents cannot be kept, though the disk has a "
          "notebook: draw_chart is not offered, nor done")
    disk, _ = answered_disk("chart-small")
    run = Run("chart-small", disk, behaviours=["chart=moons:0"], width=800, height=600, extra=["-vga", "cirrus"], kernel_file=kernel())
    chat = ToolsChat(800, kept_name=b"", key_entry=b"", kept_look=b"")
    give_key(run, chat)
    line = "draw a chart of the moons"
    exchange(run, chat, line, [T, model.NOT_HERE] + back())
    run.shot("small", meant_screen(chat, [], None, 800, 600))
    meant_bodies = [body_meant(line, [], record=chat.records[-1], key=KEY, screen=(800, 600)),
                    body_again(line, [], chat.agains[0], key=KEY, screen=(800, 600))]
    lines = run.end()
    seen = [note_ for note_ in posts(run) if note_.get("request for") == "a line"]
    report("small requests for a line", len(seen) == len(meant_bodies), "%d, meant %d" % (len(seen), len(meant_bodies)))
    for number, (note_, body) in enumerate(zip(seen, meant_bodies)):
        check_body("small request %d" % (number + 1), note_, body)
    no_key_in("small", lines)


SCENARIOS = {"draw": scenario_draw, "odd": scenario_odd, "cut": scenario_cut, "broken": scenario_broken, "nodocs": scenario_nodocs,
             "small": scenario_small}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
