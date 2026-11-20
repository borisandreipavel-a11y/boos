"""Breaks made on purpose in the reading of a good answer (the real question), each in a copy of the project only.
They are added to model_breaks.BREAKS, so that test_model.py can run them with BREAK=<name>.

Usage: python model_breaks5.py      runs every break against the cases that should catch it, on a disk that is not
divided (as the model's cases need), and says how many were caught. It ends with 1 if a break could not be made."""
import os
import subprocess
import sys

import model_breaks
from model_breaks import swap


def noending(text):
    # In model_sentence, the question's path: app_sentence reads the ending the same way.
    return swap(text, "    // What stands there is compared and never said itself.\n    let ending = json_find_text(body, ENDING).ok();\n",
                "    // What stands there is compared and never said itself.\n    let ending: Option<String> = None; // BREAK\n")


def notrim(text):
    # In model_sentence, the question's path: app_sentence takes the spaces off the same way.
    return swap(text, "    // The model's words, without the spaces and line ends before and after.\n    let found = model_words(body);\n"
                      "    let words = match &found {\n        Ok(words) => Ok(words.trim()),\n",
                "    // The model's words, without the spaces and line ends before and after.\n    let found = model_words(body);\n"
                "    let words = match &found {\n        Ok(words) => Ok(words.as_str()), // BREAK\n")


def nopieces(text):
    return swap(text, "        Err(NOT_A_TEXT) => json_find_text(body, FIRST_PIECE).map_err(|_| NOT_A_TEXT),\n",
                "        Err(NOT_A_TEXT) => Err(NOT_A_TEXT), // BREAK\n")


def no5xx(text):
    return swap(text, "    let what = if (500..600).contains(&parts.number) {", "    let what = if false && (500..600).contains(&parts.number) {")


def nostrict(text):
    # In model_sentence, the question's path (its sentence counts ANSWER_TOKENS; app_sentence's counts APP_TOKENS).
    return swap(text, "        Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() => empty_sentence(body, out_of_room, held_back, cut_short, ANSWER_TOKENS),",
                "        Err(NOT_A_TEXT | NOT_THERE) => empty_sentence(body, out_of_room, held_back, cut_short, ANSWER_TOKENS), // BREAK")


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
