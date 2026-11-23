"""Breaks the look on purpose, one break at a time, in a copy of the project (copy_break.py), and sees whether
test_look.py catches each one, booting the copy's kernel: the looks and the line `look`, and the question for a look
at the end of the onboarding. The project itself is only read, so other tests can run beside these.
Usage: python run_look_breaks.py [break ...]   (default: all)
BREAKS is data: run_tests.py runs the same breaks."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# label: (file, old, new, scenarios of test_look.py that must catch it)
BREAKS = {
    # The looks and the line `look`.
    "the panel not painted again": ("look.rs", "    chat_paint();\n    screen_panel_again();\n", "    chat_paint();\n", ["pick"]),
    "the background not painted again": ("look.rs", "    screen_background();\n    chat_paint();\n", "    chat_paint();\n", ["pick"]),
    "the panel's text not remembered": ("screen.rs", "        PANEL_SHOWN = true;\n", "        PANEL_SHOWN = false;\n", ["pick"]),
    "the kernel's letters keep the first look's colour": ("chat.rs", "            Speaker::Kernel => look.chat_kernel,\n",
        "            Speaker::Kernel => Colour { red: 0, green: 60, blue: 140 },\n", ["pick"]),
    "the sentence stays white": ("screen.rs", "    screen_text(40, 40, SENTENCE, 2, look.sentence);\n",
        "    screen_text(40, 40, SENTENCE, 2, Colour { red: 255, green: 255, blue: 255 });\n", ["pick"]),
    "a number one off": ("look.rs", "                IN_USE = number - 1;\n", "                IN_USE = number % LOOKS.len();\n", ["pick"]),
    "a tried look not shown at once": ("chat.rs", "            if look_changed {\n                look_paint();\n",
        "            if false {\n                look_paint();\n", ["pick"]),
    "the kept look not written": ("look.rs", "return match notebook_keep(LOOK_ENTRY, look().name.as_bytes())", "return match Ok::<(), &'static str>(())", ["pick"]),
    "the kept look not read at startup": ("look.rs", "    match notebook_find(LOOK_ENTRY) {\n",
        "    match Ok::<Option<Vec<u8>>, &'static str>(None) {\n", ["pick"]),
    "the answer kept as the last line": ("chat.rs", "            let said = core::mem::take(chat_line());\n            line_taken();\n            let mut rows = Vec::new();\n",
        "            let said = core::mem::take(chat_line());\n            line_taken();\n            let _ = notebook_keep(LAST_LINE, said.as_bytes());\n            let mut rows = Vec::new();\n",
        ["pick"]),
    "a look kept although none was tried": ("look.rs", "    if tried && kept != Some(in_use) {\n", "    if kept != Some(in_use) {\n", ["atonce"]),
    "a kept look found whatever its capitals": ("look.rs", "one.name.as_bytes() == kept.as_slice()", "one.name.as_bytes().eq_ignore_ascii_case(kept.as_slice())",
        ["odd"]),
    "no row for a kept look the kernel does not know": ("look.rs",
        "                None => Some(format!(\"Kernel: the look kept on the disk is not one I know, so the screen keeps {}.\", look_named())),\n",
        "                None => None,\n", ["odd"]),
    # The question for a look at the end of the onboarding.
    "the onboarding never asks for a look": ("onboarding.rs", "    if look_due(setting_up) {\n", "    if false {\n", ["pick"]),
    "the closing words not taken away": ("onboarding.rs", "        free_words_drop(&mut rows);\n", "", ["pick"]),
    "asked although the notebook holds an answer": ("look.rs", "    notebook_ready() && (setting_up || !unsafe { ANSWERED })\n",
        "    notebook_ready()\n", ["pick"]),
    "not asked after setup": ("look.rs", "    notebook_ready() && (setting_up || !unsafe { ANSWERED })\n",
        "    notebook_ready() && !unsafe { ANSWERED }\n", ["setup"]),
    "Enter alone at once notes nothing": ("look.rs", "    if !answered && notebook_ready() {\n", "    if false {\n", ["atonce"]),
    "an entry with no signs not taken as an answer": ("look.rs",
        "        Ok(Some(kept)) if kept.is_empty() => {\n            unsafe { ANSWERED = true };\n",
        "        Ok(Some(kept)) if kept.is_empty() => {\n", ["atonce"]),
    "a look the kernel does not know taken as an answer": ("look.rs",
        "                None => Some(format!(\"Kernel: the look kept on the disk is not one I know, so the screen keeps {}.\", look_named())),\n",
        "                None => {\n                    unsafe { ANSWERED = true };\n                    Some(format!(\"Kernel: the look kept on the disk is not one I know, so the screen keeps {}.\", look_named()))\n                }\n",
        ["odd"]),
    "the question not last at startup": ("chat.rs", "    if onboarding_waiting() || look_asking() {\n", "    if onboarding_waiting() {\n", ["odd"]),
    "the first row says one question when the look follows": ("onboarding.rs", "    key_follows || look_due(false)\n", "    key_follows\n",
        ["norandom"]),
    "no question after the key is locked": ("onboarding.rs",
        "        Err(reason) => vec![format!(\"Kernel: I could not lock the key, because {}, so it lasts only until the machine is switched off.\", reason)],\n    };\n    finish(rows)\n",
        "        Err(reason) => vec![format!(\"Kernel: I could not lock the key, because {}, so it lasts only until the machine is switched off.\", reason)],\n    };\n    unsafe {\n        WAITING = Waiting::Nothing;\n        SETTING_UP = false;\n    }\n    rows\n",
        ["locked"]),
}

def main():
    from copy_break import NotMade, make
    from places import RUNS
    kernel_out = os.path.join(RUNS, "look-break-kernel.efi")
    results, not_made = [], 0
    for label in sys.argv[1:] or list(BREAKS):
        file, old, new, scenarios = BREAKS[label]
        print("BREAK ON PURPOSE:", label, flush=True)
        try:
            kernel = make(file, old, new, kernel_out)
        except (NotMade, RuntimeError) as reason:
            not_made += 1
            print("   THE BREAK WAS NOT MADE |", str(reason)[-400:], flush=True)
            continue
        run = subprocess.run([sys.executable, "test_look.py"] + scenarios, cwd=HERE, capture_output=True, text=True,
                             env=dict(os.environ, KERNEL_FILE=kernel, KERNEL_BREAK=json.dumps([file, old, new])))
        last = [l for l in run.stdout.splitlines() if l.startswith("FAILURES:")]
        caught = bool(last) and last[-1] != "FAILURES: none"
        wrong = [l.strip() for l in run.stdout.splitlines() if ("dots wrong" in l or ("terminal and disk" in l and "as meant" not in l) or "VAIN" in l)]
        print("   caught" if caught else "   NOT CAUGHT", "|", (wrong[0][:170] if wrong else (run.stdout + run.stderr)[-400:]), flush=True)
        results.append((label, caught))
    print("caught %d of %d%s" % (sum(c for _, c in results), len(results), "; %d not made" % not_made if not_made else ""))
    sys.exit(1 if not_made else 0)


if __name__ == "__main__":
    main()
