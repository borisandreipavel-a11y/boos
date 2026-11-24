"""Breaks on purpose for the key and the password, and for the line typed in the chat box (test_chat_line.py), each alone, in a copy of the project (copy_break.py). For each:
copy the project's sources afresh, make the break, build, and run the test that should catch it with the copy's
kernel. The project itself is only read. A break whose old text no longer stands once in its file is reported as not
made, and the others still run.
Usage: python run_key_breaks.py [break ...]   (default: all)
BREAKS is data: run_tests.py runs the same breaks."""
import os
import subprocess
import sys

MEMORY = ["test_key_memory.py"]
LOCKED = ["test_key.py", "locked"]
LINE_EDIT = ["test_chat_line.py", "edit"]
LINE_RESTART = ["test_chat_line.py", "restart"]
# name: (file in src, old text, new text, the test that should catch it)
BREAKS = {
    "the typed signs not wiped": ("chat.rs", "            wipe(typed);\n            kernel_rows(&rows);\n", "            kernel_rows(&rows);\n", MEMORY),
    "the password not forgotten after locking": ("onboarding.rs", "    let locked = secret_lock();\n    password_forget();\n",
                                                 "    let locked = secret_lock();\n", MEMORY),
    "the locking's own rooms not wiped": ("secret.rs", "    wipe(&mut secret);\n    wipe(&mut password);\n    locked\n", "    locked\n", MEMORY),
    "the unlocking's room not wiped": ("secret.rs", "    wipe(&mut room);\n    kept\n", "    kept\n", MEMORY),
    "no least length": ("onboarding.rs", "    if typed.len() < PASSWORD_LEAST {", "    if false {", LOCKED),
    "the second password not compared": ("onboarding.rs", "    if !password_same(typed) {", "    if false {", LOCKED),
    "the key typed as a plain line": ("onboarding.rs", "matches!(waiting(), Waiting::Key | Waiting::Trying", "matches!(waiting(), Waiting::Trying", LOCKED),
    "the unlocked key not kept": ("secret.rs", "        Ok(length) => Ok(secret_keep(&room[..length], provider)),", "        Ok(length) => Ok(length),", LOCKED),
    "no key not noted": ("onboarding.rs", "    if unsafe { KEY_ANSWERED } {\n        return Vec::new();\n    }\n    match notebook_keep(key_entry(), &[]) {",
                         "    if true {\n        return Vec::new();\n    }\n    match notebook_keep(key_entry(), &[]) {", ["test_name3.py", "first"]),
    "every refusal taken for a wrong password": ("onboarding.rs", "        Err(reason) if reason == NOT_UNLOCKED => vec![", "        Err(_) if true => vec![",
                                                 ["test_key.py", "odd"]),
    "the question for a new key not used at setup": ("onboarding.rs",
                                                     "    String::from(if setting_up && !locked_key().is_empty() { KEY_QUESTION_AGAIN } else { KEY_QUESTION })",
                                                     "    String::from(if false { KEY_QUESTION_AGAIN } else { KEY_QUESTION })", ["test_key.py", "stays"]),
    # The line typed in the chat box (docs/chat.md).
    "line: the 201st sign taken": ("chat.rs", "const CHAT_LINE_LIMIT: usize = 200;", "const CHAT_LINE_LIMIT: usize = 201;", LINE_EDIT),
    "line: the rows of what was said not made fewer": ("chat.rs",
        "    let fit = (style.rows as usize).saturating_sub(typing.shown.saturating_sub(1) as usize);\n",
        "    let fit = style.rows as usize;\n", LINE_EDIT),
    "line: the rows not painted again when the row being typed grows": ("chat.rs", "    if before == Some(after) && room > 0 {\n",
        "    if room > 0 {\n", LINE_EDIT),
    "line: a sign put at the end, not at the place": ("chat.rs", "            line.insert(at, letter as char);\n",
        "            line.push(letter as char);\n", LINE_EDIT),
    "line: Delete taking the sign before the place": ("chat.rs", "            chat_line().remove(at);\n",
        "            chat_line().remove(at.saturating_sub(1));\n", LINE_EDIT),
    "line: Right not moving the place": ("chat.rs",
        "        RIGHT_KEY => {\n            if at >= chat_line().len() {\n                return;\n            }\n            chat_at_put(at + 1);\n",
        "        RIGHT_KEY => {\n            if at >= chat_line().len() {\n                return;\n            }\n", LINE_EDIT),
    "line: the place shown as a _ over its sign": ("chat.rs",
        "            screen_rectangle(left, top, sign_width, letter_height, look.chat_person);\n"
        "            screen_text(left, top, &text[cell..cell + 1], style.text_size, look.chat_typing);\n",
        "            screen_text(left, top, \"_\", style.text_size, look.chat_person);\n", LINE_EDIT),
    "line: Left not known behind the mark": ("keyboard.rs", "            LEFT_NUMBER => return Some(LEFT_KEY),\n", "", LINE_EDIT),
    "line: the new keys typed into a secret": ("chat.rs",
        "    if !matches!(letter, BACKSPACE | b'\\n' | b' '..=b'~') {\n        return;\n    }\n", "", LINE_EDIT),
    "line: the line sent not kept for Up": ("chat.rs", "            last_sent_put(said.clone());\n", "", LINE_EDIT),
    "line: Down losing what was typed": ("chat.rs", "            *chat_line() = typed;\n            chat_at_put(typed_at);\n",
        "            let _ = (typed, typed_at);\n            chat_line().clear();\n            chat_at_put(0);\n", LINE_EDIT),
    "line: Up while the kernel asks a question of its own": ("chat.rs", "            if kernel_question() || set_aside_holds() {\n",
        "            if set_aside_holds() {\n", LINE_RESTART),
    "line: the kept line not read for Up at a start": ("chat.rs", "            last_sent_put(said);\n", "", LINE_RESTART),
    "line: the kept line said cut at 50": ("chat.rs", "kept.iter().take(CHAT_LINE_LIMIT)", "kept.iter().take(50)", LINE_RESTART),
}
# Known not to be caught (docs/testing.md): what is left in those rooms has been written over by the time of the dump.
MISSES = {"the locking's own rooms not wiped", "the unlocking's room not wiped"}


def main():
    from copy_break import NotMade, make
    from places import HERE, RUNS
    kernel_out = os.path.join(RUNS, "key-break-kernel.efi")
    caught = not_made = 0
    names = sys.argv[1:] or list(BREAKS)
    for name in names:
        file, old, new, command = BREAKS[name]
        try:
            kernel = make(file, old, new, kernel_out)
        except NotMade as reason:
            not_made += 1
            print("%-46s THE BREAK CANNOT BE MADE: %s" % (name, reason), flush=True)
            continue
        except RuntimeError as reason:
            not_made += 1
            print("%-46s THE BREAK DID NOT BUILD: %s" % (name, str(reason)[-400:]), flush=True)
            continue
        run = subprocess.run([sys.executable] + command, cwd=HERE, capture_output=True, text=True,
                             env=dict(os.environ, KERNEL_FILE=kernel))
        last = [line for line in run.stdout.splitlines() if line.startswith("FAILURES:")]
        is_caught = bool(last) and last[-1] != "FAILURES: none"
        caught += is_caught
        print("%-46s %s | %s" % (name, "caught" if is_caught else ("NOT CAUGHT (documented)" if name in MISSES else "NOT CAUGHT"),
                                 (last[-1] if last else run.stdout[-300:])[:170]), flush=True)
    print("caught %d of %d%s" % (caught, len(names), "; %d not made" % not_made if not_made else ""))
    sys.exit(1 if not_made else 0)


if __name__ == "__main__":
    main()
