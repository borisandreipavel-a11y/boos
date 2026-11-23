"""Breaks made on purpose in the reading of a good answer (to a line sent to the model), each in a copy of the project only.
They are added to model_breaks.BREAKS, so that test_model.py can run them with BREAK=<name>.

Usage: python model_breaks5.py      runs every break against the cases that should catch it, on a disk that is not
divided (as the model's cases need), and says how many were caught. It ends with 1 if a break could not be made."""
import os
import subprocess
import sys

import model_breaks
from model_breaks import swap


def noending(text):
    # In chat_reply, the path of a line, which test_model.py sends. app_sentence reads the ending in the same words,
    # so the lines after them, which only chat_reply has, find the place. model_sentence (the fixed question's path,
    # which only the try of a key takes now) reads it the same way too.
    return swap(text, "    let ending = json_find_text(body, ENDING).ok();\n    let out_of_room = ending.as_deref() == Some(\"length\");\n"
                      "    let held_back = ending.as_deref() == Some(\"content_filter\");\n\n    // The first tool the model asked for.",
                "    let ending: Option<String> = None; // BREAK\n    let out_of_room = ending.as_deref() == Some(\"length\");\n"
                "    let held_back = ending.as_deref() == Some(\"content_filter\");\n\n    // The first tool the model asked for.")


def notrim(text):
    # In chat_reply, the path of a line, which test_model.py sends: both of its trims, the one that finds words of
    # spaces only and the one that takes the spaces off what is shown. model_sentence (the fixed question's path,
    # which only the try of a key takes now) and app_sentence take the spaces off the same way.
    return swap(text, "        Ok(words) if !words.trim().is_empty() => Some(words_shown(words.trim(), key)),\n",
                "        Ok(words) if !words.is_empty() => Some(words_shown(words, key)), // BREAK\n")


def nopieces(text):
    return swap(text, "        Err(NOT_A_TEXT) => json_find_text(body, FIRST_PIECE).map_err(|_| NOT_A_TEXT),\n",
                "        Err(NOT_A_TEXT) => Err(NOT_A_TEXT), // BREAK\n")


def no5xx(text):
    return swap(text, "    let what = if (500..600).contains(&parts.number) {", "    let what = if false && (500..600).contains(&parts.number) {")


def nostrict(text):
    # In chat_reply, the path of a line, which test_model.py sends (indented deeper than the same rule in
    # model_sentence, the fixed question's path, which only the try of a key takes now).
    return swap(text, "            Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => empty_sentence(body, out_of_room, held_back, cut_short, LINE_TOKENS),",
                "            Err(NOT_A_TEXT | NOT_THERE) => empty_sentence(body, out_of_room, held_back, cut_short, LINE_TOKENS), // BREAK")


def nothought(text):
    return swap(text, "    let thought = THOUGHTS.iter()", "    let thought = false && THOUGHTS.iter()")


def shortprefix(text):
    return swap(text, "plain_text(words, longest.saturating_add(key.len()))", "plain_text(words, longest) /* BREAK */")


def nobeginning(text):
    return swap(text, "    let shown = if beginning.is_empty() {", "    let shown = if true || beginning.is_empty() {")


NEW = {
    "shortprefix": ({"model.rs": shortprefix}, "echocut,echobody"),
    "nobeginning": ({"model.rs": nobeginning}, "streamed,otherform"),
    "noending": ({"model.rs": noending}, "lengthwords,lengthempty,filteredwords"),
    "notrim": ({"model.rs": notrim}, "spaces,blank"),
    "nopieces": ({"model.rs": nopieces}, "pieces"),
    "no5xx": ({"model.rs": no5xx}, "upstream,upstreambare"),
    "nostrict": ({"model.rs": nostrict}, "nochoices"),
    "nothought": ({"model.rs": nothought}, "lengthempty,nocontent"),
}
for name, (change, _) in NEW.items():
    model_breaks.BREAKS[name] = change


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    caught = not_made = 0
    for name, (_, behaviours) in NEW.items():
        # The model's cases type "key" and "ask" as ordinary lines: a divided disk would open the onboarding instead.
        environment = dict(os.environ, BREAK=name, BREAKS_MODULE="model_breaks5", DIVIDED_DISK="")
        done = subprocess.run([sys.executable, os.path.join(here, "test_model.py"), behaviours], cwd=here, env=environment, capture_output=True, text=True)
        lines = [line for line in done.stdout.splitlines() if "|" in line and " s |" in line or line.startswith("FAILURES") or line.startswith("all as meant") or "BUILD FAILED" in line]
        verdict = [line for line in done.stdout.splitlines() if line.startswith(("FAILURES", "all as meant"))]
        # A break that cannot be made stops the copy's build with an error, before the test has a verdict.
        made = bool(verdict)
        is_caught = made and verdict[-1].startswith("FAILURES")
        caught += is_caught
        not_made += not made
        print("== %s (cases %s): %s" % (name, behaviours, "caught" if is_caught else ("NOT CAUGHT" if made else "THE BREAK WAS NOT MADE")))
        for line in lines:
            print("   " + line)
        if done.returncode != 0:
            print("   exit %d: %s" % (done.returncode, done.stderr[-400:]))
    print("caught %d of %d%s" % (caught, len(NEW), "; %d not made" % not_made if not_made else ""))
    sys.exit(1 if not_made else 0)
