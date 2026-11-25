"""Bar charts in documents of text (docs/screen.md "Charts" and "A bar chart", docs/tools.md `write_document`): charts
the model writes among paragraphs and tables, laid out on pages, kept on the disk with the document, opened again and
changed by a wish; and a chart kept alone before charts stood in documents, read as a document of text. Every scenario
boots the stand-in copy of the project (net_copy.py); the stand-in answers each line with the document the scenario
names (chart_cases.py, through text_document_cases.py and chat_cases.py). What the kernel is meant to say, send and show
comes from text_document_model.py and chart_model.py, documents_model.py and chat_tools_model.py, written from the notes;
every request for a line is compared whole, every picture dot for dot, and the disk file is read from outside. Made-up
key only.

  guide     the thing this part is done by: "write a short guide to the moons of the planets with a chart of how many
            each has and a table of the largest moons" writes one document of two pages, a paragraph and the chart in the
            model's green on the first, the table on the second, kept as document 1; "add Pluto with 5 moons to the
            chart" goes with its lines and is kept as its second version; after a restart the panel lists it, and "open
            the moons guide" shows it and goes back; F1 and a key bring it back; in Night the green, too faint on Night's
            dark grey, gives way to Night's frame colour; `setup` empties the frame.
  odd       four charts in one document: numbers below zero, with decimals and commas, in a yellow too faint on light
            grey, where the letters' colour takes its place; every number below zero; every number zero; long numbers at
            both ends of the scale; the second chart begun on the next page, since a chart never splits. More bars than a
            page holds, labels and a title longer than their room, bars without a number, a colour that waits for the
            next chart, a bar after a paragraph that begins a chart, and a chart with nothing to draw, which goes back.
            Bars alone, a document named by its number, whose lines go with the next line; Night.
  cut       a change cut off at the limit of tokens, not drawn, the document as it was; a new document cut off inside
            its chart, drawn as far as its bars came whole and not kept; a chart with the key as a label, kept with
            stars.
  old       a disk put together from outside with a chart drawn alone by draw_chart before charts stood in documents
            (kind 3): the start lists it, it opens as a document of text holding the chart, told as one, and a paragraph
            added by a wish keeps its next version as a document of text.

Usage: python test_chart_documents.py [scenario ...]        (with none: all)
Environment: BREAK (a break on purpose, chart_breaks.py), BOOS_PORT_BASE, BOOS_PROVIDER ("anthropic": every line goes
to Anthropic, in Anthropic's form; the rows, pictures and requests meant are the same)."""
import json
import os

os.environ["DIVIDED_DISK"] = ""

import chart_cases as cases
import chart_model
import chat_cases
import text_document_model as model
from chart_breaks import BREAKS
from chat_tools_model import CUT_OFF, body_meant, key_pieces, model_row
from documents_model import KIND_CHART, KIND_TEXT, documents_of, kept_line, kept_row, not_kept_row, note, opened_row, start_lines
from look_values import LOOKS
from net_copy import build
from test_apps_kept import KEY, PORT, Run, answered_disk, failures, give_key, report
from test_chat_tools import back, exchange, no_key_in, posts, rounds_since
from test_documents import Requests, documents_lines, new_chat, start_documents_lines
from test_text_documents import check_things, holds_text, meant_screen, turn
from app_cases import hide

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
    """A document of text with charts as these tests follow it: kept from the document `name` of chart_cases.py,
    written with the line "document N" in front when `number_line` is given."""
    written = cases.text(name, number_line)
    return dict(number=number, version=version, name=model.name_of(written), lines=model.lines_kept(written), kind=KIND_TEXT)


def nothing_more_kept(tag, found, names_meant):
    names = sorted(name for name in found if name.startswith("document"))
    report(tag + " nothing more kept", names == sorted(names_meant), "got %r" % names)


# ---------- The scenarios ----------

def scenario_guide():
    print("guide: a guide with a paragraph, a chart and a table, Pluto added by a wish, a restart, an open, F1, Night, "
          "and setup")
    disk, _ = answered_disk("cd-guide")
    run = start("cd-guide", disk, ["chartdoc=guide:0", "chartdoc=pluto:1"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # The guide, written whole on two pages: the paragraph and the chart in the model's green, which stands out from
    # Blue's light grey, on the first; the table on the second. Kept as document 1, which is open; the line ends.
    line = "write a short guide to the moons of the planets with a chart of how many each has and a table of the largest moons"
    guide = document(1, 1, "guide", 0)
    laid, said, whole = model.written(cases.text("guide", 0))
    report("guide the guide is meant whole, on two pages", whole and len(laid["pages"]) == 2, said)
    chart = [item for item in laid["pages"][0] if item[0] == "chart"]
    report("guide its chart, on the first page, has eight bars in the model's green", len(chart) == 1 and len(chart[0][4]) == 8
           and chart_model.bar_colour(chart[0][3], "Blue") == (0x2E, 0x7D, 0x32))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(laid)])
    report("guide a document written whole does not go back", rounds_since(run) == [], "got %r" % rounds_since(run))
    meant.line(line, [])
    run.shot("guide", meant_screen(chat, [guide], 1))
    turn(run, chat, "pgdn", "guide-table", [guide], 1)
    turn(run, chat, "pgup", "guide-chart-again", [guide], 1)

    # A change by a wish: the line goes with the guide's lines; the model writes it whole again with Pluto in its chart,
    # beginning with "document 1", and it is kept as the document's second version, shown from its first page.
    line = "add Pluto with 5 moons to the chart"
    pluto = document(1, 2, "pluto", 1)
    laid, said, whole = model.written(cases.text("pluto", 1))
    report("guide Pluto is meant whole, nine bars", whole and [len(item[4]) for item in laid["pages"][0] if item[0] == "chart"] == [9], said)
    exchange(run, chat, line, [T, kept_row(said, 1, changed=True), holds_text(laid)])
    meant.line(line, [guide], guide)
    run.shot("pluto", meant_screen(chat, [pluto], 1))
    lines = run.end()
    kept = [kept_line(1, 1), kept_line(1, 2)]
    report("guide the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("guide", run)
    found = check_things("guide", disk, [pluto], versions=[(1, 1, guide["lines"])])
    no_key_in("guide", lines)

    # After a restart nothing is open and the frame is empty; the panel lists the guide. Opening it shows its first page,
    # and goes back to the model, which answers in words.
    again = start("cd-guide-2", disk, ["open=1", "look=2"])
    chat = new_chat(b"add Pluto with 5 moons to the chart")
    give_key(again, chat)
    meant = Requests(chat)
    got = start_documents_lines(again.lines())
    report("guide restart the lines about documents", got == start_lines(documents_of(found)), "got %r" % got)
    again.shot("restart", meant_screen(chat, [pluto], None))
    line = "open the moons guide"
    laid, _, _ = model.written(pluto["lines"])
    exchange(again, chat, line, [T, opened_row(pluto, model.opened_fit(laid)), holds_text(laid)] + back())
    meant.line(line, [pluto])
    meant.again(line, 0, [pluto], pluto)
    again.shot("opened", meant_screen(chat, [pluto], 1))

    # The kernel's own lines over the screen (F1), and a key that brings the usual picture back, with the chart
    # (Backspace, which takes nothing away from an empty line).
    again.m.named_key("f1", pause=1)
    again.m.named_key("backspace", pause=0.5)
    again.shot("after-f1", meant_screen(chat, [pluto], 1))

    # Night paints the whole screen again: the model's green does not stand out from Night's dark grey, so the bars take
    # Night's frame colour, which does.
    line = "make it night"
    report("guide the green gives way to Night's frame colour", chart_model.bar_colour((0x2E, 0x7D, 0x32), "Night") == LOOKS["Night"]["panel_frame"])
    exchange(again, chat, line, [T, NIGHT])
    chat.look, chat.look_kept = "Night", "Night"
    meant.line(line, [pluto], pluto)
    again.shot("night", meant_screen(chat, [pluto], 1))

    # `setup`: the open document is closed and the frame empties, and the first look comes back at once (docs/look.md);
    # the documents stay listed.
    again.mark()
    again.press("setup\n", chat)
    asked = again.wait_line("Kernel: what should I call you?", timeout=30)
    report("guide setup asks for the name", asked is not None, None if asked else "the question never came")
    chat.text = chat.table = None
    chat.look = "Blue"
    again.shot("setup", meant_screen(chat, [pluto], None))
    lines = again.end()
    meant.check("guide restart", again)
    no_key_in("guide restart", lines)


def scenario_odd():
    print("odd: four charts of odd numbers over two pages, more bars than a page holds and other left-outs, bars alone, "
          "and Night")
    disk, _ = answered_disk("cd-odd")
    run = start("cd-odd", disk, ["chartdoc=numbers:0", "chartdoc=many:0", "chartdocbare=fruit", "words=Hello.", "look=2"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    # Four charts on two pages, each dot for dot: the second does not fit under the first, so it begins the next page.
    # The yellow asked for is too faint on Blue's light grey, and so is Blue's orange frame: the letters' colour.
    line = "charts of odd numbers"
    numbers = document(1, 1, "numbers", 0)
    laid, said, whole = model.written(cases.text("numbers", 0))
    report("odd the numbers are meant whole, on two pages, the second chart at the top of the second",
           whole and len(laid["pages"]) == 2 and laid["pages"][1][0][:2] == ("chart", 0), said)
    report("odd the yellow gives way to the letters' colour", chart_model.bar_colour((0xFF, 0xEB, 0x3B), "Blue") == LOOKS["Blue"]["panel_text"])
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(laid)])
    meant.line(line, [])
    run.shot("numbers", meant_screen(chat, [numbers], 1))
    turn(run, chat, "pgdn", "numbers-2", [numbers], 1)

    # More bars than a page holds under a title cut to the row, bars without a number, a colour that waits for the next
    # chart, a bar after a paragraph that begins a chart in that colour, and a chart with nothing to draw: all said, and
    # the document goes back.
    line = "many bars please"
    many = document(2, 1, "many", 0)
    laid, said, whole = model.written(cases.text("many", 0))
    report("odd the many are meant with bars left out", not whole and laid["fit"] == dict(columns=False, bars=True, unread=3, empty=1), said)
    report("odd the lone bars take the colour that waited", laid["pages"][1][-1][0] == "chart" and laid["pages"][1][-1][3] == (255, 0, 0))
    exchange(run, chat, line, [T, kept_row(said, 2), holds_text(laid)] + back())
    meant.line(line, [numbers], numbers)
    meant.again(line, 0, [many, numbers], many)
    run.shot("many", meant_screen(chat, [many, numbers], 2))
    turn(run, chat, "pgdn", "many-2", [many, numbers], 2)

    # Bars alone, without a title, a chart line or a document line: a new document named by its number, its stray
    # `document` line kept with its lines.
    line = "fruit prices as a chart"
    fruit = document(3, 1, "fruit")
    laid, said, whole = model.written(cases.text("fruit"))
    report("odd the fruit is meant whole", whole, said)
    report("odd the fruit is named by its number, its stray document line kept", fruit["name"] == "" and "document 7" in fruit["lines"])
    exchange(run, chat, line, [T, kept_row(said, 3), holds_text(laid)])
    meant.line(line, [many, numbers], many)
    run.shot("fruit", meant_screen(chat, [fruit, many, numbers], 3))

    # The next line goes with the fruit's lines, told as a document of text's.
    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [fruit, many, numbers], fruit)

    # Night paints the page again: no colour was asked for, and Night's frame colour stands out.
    line = "make it night"
    exchange(run, chat, line, [T, NIGHT])
    chat.look, chat.look_kept = "Night", "Night"
    meant.line(line, [fruit, many, numbers], fruit)
    run.shot("fruit-night", meant_screen(chat, [fruit, many, numbers], 3))
    lines = run.end()
    meant.check("odd", run)
    found = check_things("odd", disk, [numbers, many, fruit])
    nothing_more_kept("odd", found, ["document 1", "document 1 v1", "document 2", "document 2 v1", "document 3", "document 3 v1"])
    no_key_in("odd", lines)


def scenario_cut():
    print("cut: a change cut off, a new document cut off inside its chart, and the key as a label")
    disk, _ = answered_disk("cd-cut")
    run = start("cd-cut", disk, ["chartdoc=guide:0", "chartdoccut=pluto:1:14", "chartdoccut=guide:0:9", "chartdockey", "words=Hello."])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)

    line = "a guide to the moons"
    guide = document(1, 1, "guide", 0)
    laid, said, _ = model.written(cases.text("guide", 0))
    exchange(run, chat, line, [T, kept_row(said, 1), holds_text(laid)])
    meant.line(line, [])

    # A change that the limit of tokens cut off inside its chart: not drawn, and that goes back; the guide stays as it
    # was.
    line = "add pluto"
    report("cut the change is meant cut after Pluto's bar", cases.cut("pluto", 1, 14)[1].endswith("bar Pluto | 5"))
    exchange(run, chat, line, [CUT_OFF, T, model.cut_change_row(1)] + back())
    meant.line(line, [guide], guide)
    meant.again(line, 0, [guide], guide)
    run.shot("cut-change", meant_screen(chat, [guide], 1))

    # A new document cut off inside its chart: drawn as far as its bars came whole, not kept, and nothing is open then;
    # that goes back.
    line = "a guide cut short"
    laid, said, whole = model.written(cases.cut("guide", 0, 9)[1], whole=False)
    report("cut the short one is meant with three bars", not whole and len(laid["pages"][0][-1][4]) == 3, said)
    exchange(run, chat, line, [CUT_OFF, T, not_kept_row(said), holds_text(laid)] + back())
    meant.line(line, [guide], guide)
    meant.again(line, 1, [guide])
    run.shot("cut-new", meant_screen(chat, [guide], None))

    # A chart with the key as a label: starred where it came in, on the screen, on the disk and in every request.
    line = "a chart with my key"
    keys = dict(number=2, version=1, name="Keys", lines=model.lines_kept(hide(cases.key_document(KEY), KEY)), kind=KIND_TEXT)
    laid, said, _ = model.written(cases.key_document(KEY), key=KEY)
    exchange(run, chat, line, [T, kept_row(said, 2), holds_text(laid)])
    meant.line(line, [guide])
    run.shot("key", meant_screen(chat, [keys, guide], 2))

    line = "hello"
    exchange(run, chat, line, [model_row("Hello."), T])
    meant.line(line, [keys, guide], keys)
    lines = run.end()
    kept = [kept_line(1, 1), kept_line(2, 1)]
    report("cut the terminal's lines about keeping", documents_lines(lines) == kept, "got %r" % documents_lines(lines))
    meant.check("cut", run)
    found = check_things("cut", disk, [guide, keys])
    nothing_more_kept("cut", found, ["document 1", "document 1 v1", "document 2", "document 2 v1"])
    report("cut no piece of the key in the document's lines",
           not key_pieces(found.get("document 2 v1", (0, b""))[1].decode(errors="replace"), KEY))
    everything = "\n".join(json.dumps(note_.get("body")) for note_ in posts(run))
    report("cut no piece of the key in any request", not key_pieces(everything, KEY))
    no_key_in("cut", lines)


def scenario_old():
    print("old: a chart kept alone before charts stood in documents opens as a document of text, and takes a paragraph "
          "by a wish")
    # As a person's run of draw_chart left it: two versions of document 1, the second with Pluto, its note of kind 3.
    items = [("document 1 v1", cases.OLD_V1.encode()), ("document 1 v2", cases.OLD.encode()),
             ("document 1", note(2, "Moons of the planets", KIND_CHART))]
    disk, _ = answered_disk("cd-old", items)
    run = start("cd-old", disk, ["open=1", "chartdoc=oldplus:1"])
    chat = new_chat()
    give_key(run, chat)
    meant = Requests(chat)
    old = dict(number=1, version=2, name="Moons of the planets", lines=cases.OLD, kind=KIND_CHART)
    got = start_documents_lines(run.lines())
    wanted = ["Documents: 1 is kept on the disk:", 'Documents: document 1, "Moons of the planets"']
    report("old the start lists the old chart", got == wanted, "got %r" % got)
    run.shot("start", meant_screen(chat, [old], None))

    # Opened: its lines read as a document of its title holding one chart, without a title of its own, in the green it
    # was drawn in; told to the model as a document of text, with write_document.
    line = "open the moons chart"
    laid, _, whole = model.written(cases.OLD)
    report("old the old chart is meant as a document of one page, its chart of nine bars",
           whole and len(laid["pages"]) == 1 and laid["pages"][0] == [laid["pages"][0][0]] and laid["pages"][0][0][0] == "chart"
           and laid["pages"][0][0][2] is None and len(laid["pages"][0][0][4]) == 9)
    exchange(run, chat, line, [T, opened_row(old, model.opened_fit(laid)), holds_text(laid)] + back())
    meant.line(line, [old])
    meant.again(line, 0, [old], old)
    run.shot("opened", meant_screen(chat, [old], 1))

    # A paragraph added by a wish: the whole document written again with write_document, kept as its third version, a
    # document of text.
    line = "add a paragraph about the giants"
    plus = document(1, 3, "oldplus", 1)
    laid, said, _ = model.written(cases.text("oldplus", 1))
    exchange(run, chat, line, [T, kept_row(said, 1, changed=True), holds_text(laid)])
    meant.line(line, [old], old)
    run.shot("plus", meant_screen(chat, [plus], 1))
    lines = run.end()
    report("old the terminal's lines about documents", documents_lines(lines) == wanted + [kept_line(1, 3)], "got %r" % documents_lines(lines))
    meant.check("old", run)
    found = check_things("old", disk, [plus], versions=[(1, 1, cases.OLD_V1), (1, 2, cases.OLD)])
    nothing_more_kept("old", found, ["document 1", "document 1 v1", "document 1 v2", "document 1 v3"])
    no_key_in("old", lines)


SCENARIOS = {"guide": scenario_guide, "odd": scenario_odd, "cut": scenario_cut, "old": scenario_old}


def main():
    import sys
    for name in sys.argv[1:] or list(SCENARIOS):
        SCENARIOS[name]()
    print("FAILURES: %s" % failures if failures else "FAILURES: none (all as meant)")


if __name__ == "__main__":
    main()
