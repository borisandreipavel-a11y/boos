"""Breaks made on purpose in the reading of a good answer (the real question), each in a copy of the project only.
They are added to model_breaks.BREAKS, so that test_model.py can run them with BREAK=<name>.

Usage: python model_breaks5.py      runs every break against the cases that should catch it."""
import os
import subprocess
import sys

import model_breaks
from model_breaks import swap


def noending(text):
    return swap(text, "    let ending = json_find_text(body, ENDING).ok();\n", "    let ending: Option<String> = None; // BREAK\n")


def notrim(text):
    return swap(text, "        Ok(words) => Ok(words.trim()),\n", "        Ok(words) => Ok(words.as_str()), // BREAK\n")


def nopieces(text):
    return swap(text, "        Err(NOT_A_TEXT) => json_find_text(body, FIRST_PIECE).map_err(|_| NOT_A_TEXT),\n",
                "        Err(NOT_A_TEXT) => Err(NOT_A_TEXT), // BREAK\n")


def no5xx(text):
    return swap(text, "    let what = if (500..600).contains(&parts.number) {", "    let what = if false && (500..600).contains(&parts.number) {")


def nostrict(text):
    return swap(text, "        Err(NOT_A_TEXT | NOT_THERE) if ending.is_some() =>", "        Err(NOT_A_TEXT | NOT_THERE) => // BREAK\n")


def nothought(text):
    return swap(text, "    let thought = THOUGHTS.iter()", "    let thought = false && THOUGHTS.iter()")


def shortprefix(text):
    return swap(text, "plain_text(words, longest.saturating_add(key.len()))", "plain_text(words, longest) /* BREAK */")


def nobeginning(text):
    return swap(text, "            let shown = if beginning.is_empty() {", "            let shown = if true || beginning.is_empty() {")


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
    for name, (_, behaviours) in NEW.items():
        environment = dict(os.environ, BREAK=name, BREAKS_MODULE="model_breaks5")
        done = subprocess.run([sys.executable, os.path.join(here, "test_model.py"), behaviours], cwd=here, env=environment, capture_output=True, text=True)
        lines = [line for line in done.stdout.splitlines() if "|" in line and " s |" in line or line.startswith("FAILURES") or line.startswith("all as meant") or "BUILD FAILED" in line]
        print("== %s (cases %s)" % (name, behaviours))
        for line in lines:
            print("   " + line)
        if done.returncode != 0:
            print("   exit %d: %s" % (done.returncode, done.stderr[-400:]))
