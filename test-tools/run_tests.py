"""Runs the tests: only what a change needs, or everything, several test machines at once.

    python run_tests.py                only what the files changed since master need (committed or not)
    python run_tests.py all            everything: every suite once and every break on purpose
    python run_tests.py ... --list     says what would run and why, and runs nothing
    options: --workers N (test machines at once; by default as many as the free memory takes, at most 4),
             --base REF (compare with REF instead of master), --files PATH... (run what a change to these files
             needs, whatever git says), --to-the-end (breaks run to the end, not stopped at their first failure),
             --only NAME... (only the jobs whose names start so), --share I/N (only the I-th of N shares of the
             jobs picked, dealt the same way on every computer, so that N computers together run each job once),
             --own-breaks (of the breaks on purpose, only the change's own and the first of each list; with `all`,
             everything still runs)

No window, no question. Folders and ports come from the environment as for every test (places.py, ports.py): each
test machine gets a work folder of its own under this checkout's (w1, w2, ...) and a range of stand-in ports of its
own (BOOS_PORT_BASE, plus 100 for each). It prints one line per job as it ends, a table at the end, and ends with 0
only when every suite passed and every break on purpose was caught, the documented misses excepted.

What each job is: suites.py. How the breaks on purpose are run: the lists below (CATALOGUES)."""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Nothing from outside may change what the jobs test: a KERNEL_FILE left set would have every suite boot another kernel.
STRIPPED = ("KERNEL_FILE", "KERNEL_BREAK", "BREAK", "DIVIDED_DISK", "BOOS_PROJECT", "RAW", "KEY_PAUSE", "BREAKS_MODULE", "CHAT_LOOK", "BOOS_COPIES",
            "BOOS_NETWORK_CARD")
CLEARED = [_name for _name in STRIPPED if _name in os.environ]  # said at the start of main(), so that it is not missed
for _name in STRIPPED:
    os.environ.pop(_name, None)

import suites  # noqa: E402
from places import KERNEL, PROJECT, WORK  # noqa: E402
from ports import port_base  # noqa: E402

COPIES = os.path.join(WORK, "copies")
os.environ["BOOS_COPIES"] = COPIES  # the copies are shared by all the run's test machines (copy_break.py, net_copy.py)
TIMES = os.path.join(WORK, "run-tests", "times.json")
PRINTING = threading.Lock()


def say(text):
    with PRINTING:
        print(text, flush=True)


# ---------------------------------------------------------------- the scripts: scenarios, imports, kinds

def tree_of(script):
    return ast.parse(open(os.path.join(HERE, script), encoding="utf-8").read())


def assigned(script, name):
    for node in ast.walk(tree_of(script)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    return None


def scenarios_of(script, name="SCENARIOS"):
    """The scenario names of a script's SCENARIOS (or of another dict that `name` names), dict(name=function, ...) or
    {"name": ..., ...}, read from its text."""
    value = assigned(script, name)
    if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "dict" and value.keywords:
        return [keyword.arg for keyword in value.keywords]
    if isinstance(value, ast.Dict) and value.keys and all(isinstance(key, ast.Constant) for key in value.keys):
        return [key.value for key in value.keys]
    raise SystemExit("%s has no %s = dict(...) or {...} to split by" % (script, name))


def split_names(entry, leaving_out=True):
    """The scenarios a split entry runs as jobs of their own: its script's SCENARIOS (split=True), the keys of a dict
    in another file (split="file.py NAME"), or the names given (split=[...]); less those it leaves out."""
    split = entry["split"]
    if split is True:
        names = scenarios_of(entry["command"][0])
    elif isinstance(split, str):
        file, name = split.split()
        names = scenarios_of(file, name)
    else:
        names = list(split)
    return [n for n in names if not (leaving_out and n in entry.get("leave_out", {}))]


def local_modules():
    return {name[:-3] for name in os.listdir(HERE) if name.endswith(".py")}


def needs_of(script, known=None):
    """The test-tools files a script uses: what it imports, and scripts it names (model_server.py, say), and theirs."""
    known = known or local_modules()
    seen, todo = set(), [script[:-3] if script.endswith(".py") else script]
    while todo:
        module = todo.pop()
        if module in seen or module not in known:
            continue
        seen.add(module)
        for node in ast.walk(tree_of(module + ".py")):
            if isinstance(node, ast.Import):
                todo += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                todo.append(node.module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(".py"):
                todo.append(node.value[:-3])
    return seen


# ---------------------------------------------------------------- jobs

class Job:
    def __init__(self, name, command, env=None, seconds=60, kind="suite", catalogue=None, brk=None, expect="pass",
                 watches=(), alone=False, prepare=None, needs=(), target=None, stop_early=False, misses=False, checks=()):
        self.name, self.command, self.env, self.kind = name, command, dict(env or {}), kind
        self.catalogue, self.brk, self.expect, self.watches, self.alone = catalogue, brk, expect, list(watches), alone
        self.prepare, self.needs, self.target, self.stop_early = prepare, set(needs), target, stop_early
        # misses: the command is a list of breaks that reports what it did not catch ("NOT CAUGHT: none" when every
        # check named for the break, `checks`, caught it), and its own verdict is read.
        self.misses, self.checks = misses, list(checks)
        self.seconds = seconds
        self.reason = ""
        self.again = False  # a break run again alone and to the end


def suite_jobs():
    jobs = []
    for entry in suites.SUITES:
        script = entry["command"][0]
        seconds = entry.get("seconds", 60)
        common = dict(env=entry.get("env"), watches=entry.get("watches", []), alone=entry.get("alone", False),
                      needs=needs_of(script))
        if entry.get("split"):
            for scenario in split_names(entry):
                share = seconds.get(scenario, 60) if isinstance(seconds, dict) else seconds
                jobs.append(Job("%s %s" % (entry["name"], scenario), entry["command"] + [scenario], seconds=share, **common))
        else:
            jobs.append(Job(entry["name"], entry["command"], seconds=seconds if isinstance(seconds, (int, float)) else 60, **common))
    return jobs


class NotMade(Exception):
    pass


def check_change(change, file):
    """Runs a break's change over the file it changes, as it is now; raises NotMade if its old text is not there once."""
    path = os.path.join(PROJECT, "interpreter", "src", "lib.rs") if file == "interpreter" else os.path.join(PROJECT, "src", file)
    text = open(path, "rb").read().decode().replace("\r\n", "\n")
    try:
        if change(text) == text:
            raise NotMade("the change leaves %s as it was" % file)
    except AssertionError as reason:
        raise NotMade("in %s: %s" % (file, reason))


def target_of(file):
    return "interpreter/src/lib.rs" if file == "interpreter" else "src/" + file


def break_jobs():
    """Every break on purpose of every list, as jobs, with a check that each can be made in the source as it is."""
    from copy_break import NotMade as CopyNotMade
    from copy_break import check as copy_check
    jobs, problems = [], []

    def add(catalogue, name, command, env, changes, expect, files, seconds, prepare=None, checks=None):
        if "break %s: %s" % (catalogue, name) in suites.KNOWN_MISSES:
            expect = "miss"
        job = Job("break %s: %s" % (catalogue, name), command, env=env, seconds=seconds, kind="break", catalogue=catalogue,
                  brk=name, expect=expect, needs=set().union(*[needs_of(f) for f in files]) | needs_of(command[0]),
                  prepare=prepare, stop_early=checks is None, misses=checks is not None, checks=checks or ())
        job.target = [target_of(file) for file, _ in changes]
        for file, change in changes:
            try:
                change(file)
            except (NotMade, CopyNotMade) as reason:
                problems.append("%s: cannot be made: %s" % (job.name, reason))
        jobs.append(job)

    # Apps: in the stand-in copy, through test_app.py with BREAK.
    import app_breaks
    for name, changes in app_breaks.BREAKS.items():
        add("apps", name, ["test_app.py", app_breaks.CATCH[name]], {"BREAK": name},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()], "caught",
            ["app_breaks.py"], 40)
    # The try of a key: in the stand-in copy, through test_try.py with BREAK.
    import run_try_breaks
    try_breaks = ast.literal_eval(assigned("test_try.py", "TRY_BREAKS"))
    for name, scenario in run_try_breaks.WHICH.items():
        file, old, new = try_breaks[name]
        add("try", name, ["test_try.py", scenario], {"BREAK": name},
            [(file, lambda file, o=old, n=new: copy_check(file, o, n))], "caught", ["run_try_breaks.py"], 60)
    # The model: in the stand-in copy, through test_model.py with BREAK, on a disk that is not divided.
    import model_breaks
    import model_breaks5
    model = [(name, cases, dump) for name, (cases, dump) in model_breaks.CATCH.items()]
    model += [(name, cases, False) for name, (_, cases) in model_breaks5.NEW.items()]
    for name, cases, dump in model:
        changes = model_breaks.BREAKS[name]
        add("model", name, ["test_model.py", cases] + (["dump"] if dump else []), {"BREAK": name, "DIVIDED_DISK": ""},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()],
            "miss" if name in model_breaks.MISSES else "caught", ["model_breaks.py", "model_breaks5.py"], 35)
    # The key and the password: in the break copy, the test booting the copy's kernel.
    import run_key_breaks
    for name, (file, old, new, command) in run_key_breaks.BREAKS.items():
        add("key", name, list(command), {}, [(file, lambda file, o=old, n=new: copy_check(file, o, n))],
            "miss" if name in run_key_breaks.MISSES else "caught", ["run_key_breaks.py", "copy_break.py"], 120,
            prepare=(file, old, new))
    # The look: in the break copy, test_look.py's scenarios booting the copy's kernel.
    import run_look_breaks
    for name, (file, old, new, scenarios) in run_look_breaks.BREAKS.items():
        add("look", name, ["test_look.py"] + list(scenarios), {}, [(file, lambda file, o=old, n=new: copy_check(file, o, n))],
            "caught", ["run_look_breaks.py", "copy_break.py"], 60, prepare=(file, old, new))
    # Apps kept on the disk: in the stand-in copy, through test_apps_kept.py with BREAK.
    import apps_kept_breaks
    for name, changes in apps_kept_breaks.BREAKS.items():
        add("kept", name, ["test_apps_kept.py", apps_kept_breaks.CATCH[name]], {"BREAK": name},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()], "caught",
            ["apps_kept_breaks.py"], 60)
    # Every line to the model: in the stand-in copy, through test_chat_tools.py with BREAK.
    import chat_tools_breaks
    for name, changes in chat_tools_breaks.BREAKS.items():
        add("tools", name, ["test_chat_tools.py", chat_tools_breaks.CATCH[name]], {"BREAK": name},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()], "caught",
            ["chat_tools_breaks.py"], 60)
    # Files from the web: in the stand-in copy, through test_downloads.py with BREAK.
    import download_breaks
    for name, changes in download_breaks.BREAKS.items():
        add("downloads", name, ["test_downloads.py", download_breaks.CATCH[name]], {"BREAK": name},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()], "caught",
            ["download_breaks.py"], 60)
    # Documents: in the stand-in copy, through test_documents.py with BREAK.
    import documents_breaks
    for name, changes in documents_breaks.BREAKS.items():
        add("documents", name, ["test_documents.py", documents_breaks.CATCH[name]], {"BREAK": name},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()], "caught",
            ["documents_breaks.py"], 60)
    # Files opened as documents: in the stand-in copy, through test_open_file.py with BREAK.
    import open_file_breaks
    for name, changes in open_file_breaks.BREAKS.items():
        add("open file", name, ["test_open_file.py", open_file_breaks.CATCH[name]], {"BREAK": name},
            [(file, lambda file, c=change: check_change(c, file)) for file, change in changes.items()], "caught",
            ["open_file_breaks.py"], 60)
    # Intel's network card: in the break copy, test_intel_card.py's scenarios booting the copy's kernel ("many" and
    # "page" carry the break into a copy of their own, through KERNEL_BREAK).
    import run_intel_card_breaks
    for name, (file, old, new, scenarios) in run_intel_card_breaks.BREAKS.items():
        add("intel", name, ["test_intel_card.py"] + list(scenarios), {}, [(file, lambda file, o=old, n=new: copy_check(file, o, n))],
            "caught", ["run_intel_card_breaks.py", "copy_break.py"], 60, prepare=(file, old, new))
    # `setup` bringing back the first look: in the break copy, test_look_reset.py's scenarios booting the copy's kernel.
    import run_reset_breaks
    for name, (file, old, new, scenarios) in run_reset_breaks.BREAKS.items():
        add("reset", name, ["test_look_reset.py"] + list(scenarios), {}, [(file, lambda file, o=old, n=new: copy_check(file, o, n))],
            "caught", ["run_reset_breaks.py", "copy_break.py"], 60, prepare=(file, old, new))
    # The kernel's own lines: each break through run_lines_breaks.py itself (read here from its text, since it runs
    # when imported), which makes it in its own copy (lines_copy.py) and counts it as caught only when every check
    # named for it catches it. Its own verdict is read; it does not stop at a first failure.
    lines_breaks = ast.literal_eval(assigned("run_lines_breaks.py", "BREAKS"))
    for label, (file, old, new, checks) in lines_breaks.items():
        add("lines", label, ["run_lines_breaks.py", label], {}, [(file, lambda file, o=old, n=new: copy_check(file, o, n))],
            "caught", ["run_lines_breaks.py"], 90, checks=checks)
    return jobs, problems


# ---------------------------------------------------------------- checks of the table itself

def table_problems(jobs):
    problems = []
    listed = {entry["command"][0] for entry in suites.SUITES}
    for name in sorted(os.listdir(HERE)):
        if (name.startswith("test_") and name.endswith(".py")) or (name.startswith("run_") and name.endswith("_breaks.py")):
            if name not in listed and name not in suites.EXCUSED and name not in CATALOGUE_FILES:
                problems.append("%s is in no entry of suites.py and not excused there" % name)
    for entry in suites.SUITES:
        names = split_names(entry, leaving_out=False) if entry.get("split") else []
        unknown = set(entry.get("leave_out", {})) - set(names)
        if unknown:
            problems.append("the entry '%s' leaves out scenarios its script does not have: %s" % (entry["name"], sorted(unknown)))
        if isinstance(entry.get("split"), list):
            text = open(os.path.join(HERE, entry["command"][0]), encoding="utf-8").read()
            absent = [n for n in names if '"%s"' % n not in text and "'%s'" % n not in text]
            if absent:
                problems.append("the entry '%s' names scenarios its script does not know: %s" % (entry["name"], absent))
    kinds = suites.APP_KINDS.split(",")
    if len(kinds) != 46:
        problems.append("suites.APP_KINDS holds %d kinds, not the 46 of app_cases.py" % len(kinds))
    meant = assigned("test_model.py", "MEANT")
    model_known = {ast.literal_eval(key) for key in meant.keys} if isinstance(meant, ast.Dict) else set()
    if set(suites.MODEL_KINDS.split(",")) != model_known:
        problems.append("suites.MODEL_KINDS differs from the kinds test_model.py knows: %s" % sorted(set(suites.MODEL_KINDS.split(",")) ^ model_known))
    counts = {}
    for job in jobs:
        if job.kind == "break":
            counts[job.catalogue] = counts.get(job.catalogue, 0) + 1
    if counts != suites.BREAK_COUNTS:
        problems.append("the lists of breaks hold %s, suites.BREAK_COUNTS says %s" % (counts, suites.BREAK_COUNTS))
    breaks = {job.name for job in jobs if job.kind == "break"}
    for name in sorted(set(suites.KNOWN_MISSES) - breaks):
        problems.append("suites.KNOWN_MISSES names a break that no list holds: %s" % name)
    for name in sorted(set(suites.KNOWN_MISSES) & set(suites.CAUGHT_BY)):
        problems.append("%s is in suites.KNOWN_MISSES and has a first failure in suites.CAUGHT_BY" % name)
    return problems


CATALOGUE_FILES = {"run_key_breaks.py", "run_try_breaks.py", "run_look_breaks.py", "run_app_breaks.py", "run_apps_kept_breaks.py",
                   "run_reset_breaks.py", "run_lines_breaks.py", "run_chat_tools_breaks.py", "run_intel_card_breaks.py"}


# ---------------------------------------------------------------- what a change needs

def git(*args):
    done = subprocess.run(["git"] + list(args), cwd=PROJECT, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout


def changed_files(base):
    point = git("merge-base", "HEAD", base).strip()
    files = set(git("diff", "--name-only", point, "HEAD").split())
    files |= set(git("diff", "--name-only", "HEAD").split())
    files |= set(git("ls-files", "--others", "--exclude-standard").split())
    return point, sorted(f.replace("\\", "/") for f in files)


def table_on(point):
    """suites.SUITES, CAUGHT_BY and KNOWN_MISSES as they were at `point` (empty if suites.py was not there)."""
    if point is None:
        return {}, {}, {}
    try:
        text = git("show", "%s:test-tools/suites.py" % point)
    except RuntimeError:
        return {}, {}, {}
    space = {}
    exec(compile(text, "suites.py at " + point, "exec"), space)  # the table holds data only
    return ({entry["name"]: entry for entry in space.get("SUITES", [])}, space.get("CAUGHT_BY", {}),
            space.get("KNOWN_MISSES", {}))


def plan_changed(jobs, files, point):
    """Picks the jobs that the changed files need, each with its reason."""
    picked = {}

    def pick(job, why):
        picked.setdefault(job.name, (job, why))

    everything = None
    test_tools = {}
    for path in files:
        if any(path.endswith(word) or path == word for word in suites.WORDS):
            continue
        if any(path.startswith(prefix) or path == prefix for prefix in suites.NO_TEST):
            continue
        if path == "test-tools/suites.py":
            entries_then, caught_then, misses_then = table_on(point)
            entries_now = {entry["name"]: entry for entry in suites.SUITES}
            for name, entry in entries_now.items():
                if entries_then.get(name) != entry:
                    for job in jobs:
                        if job.kind == "suite" and (job.name == name or job.name.startswith(name + " ")):
                            pick(job, "its entry in suites.py changed")
            for name in set(suites.CAUGHT_BY) | set(caught_then):
                if suites.CAUGHT_BY.get(name) != caught_then.get(name):
                    for job in jobs:
                        if job.name == name:
                            pick(job, "its first failure in suites.py changed")
            for name in set(suites.KNOWN_MISSES) | set(misses_then):
                if suites.KNOWN_MISSES.get(name) != misses_then.get(name):
                    for job in jobs:
                        if job.name == name:
                            pick(job, "its known miss in suites.py changed")
            continue
        if path.startswith("test-tools/") and path.endswith(".py"):
            module = path[len("test-tools/"):-3]
            if module in ("run_tests", "turns"):
                everything = everything or "the runner changed (%s)" % path
                continue
            test_tools[module] = path
            continue
        watched = [job for job in jobs if job.kind == "suite" and path in job.watches]
        targeted = [job for job in jobs if job.kind == "break" and path in (job.target or [])]
        for job in targeted:
            pick(job, "it breaks %s" % path)
        if watched:
            for job in watched:
                pick(job, "it watches %s" % path)
        else:
            everything = everything or "%s is on the path of every start, or no entry names it" % path
    for module, path in test_tools.items():
        for job in jobs:
            if module in job.needs:
                pick(job, "it uses %s" % path)
    if everything:
        for job in jobs:
            if job.kind == "suite":
                pick(job, everything)
    chosen = []
    for job, why in picked.values():
        job.reason = why
        chosen.append(job)
    return chosen


# ---------------------------------------------------------------- a change's own breaks on purpose (--own-breaks)

def listed(text):
    """What a file of test-tools sets at its top level: every entry of a dict with words for keys, as {(dict, key):
    (its text, the names it uses)}, and the text of every other function or name it sets, as {name: text}. A list of
    breaks names each break so, with its change and the scenario that must catch it."""
    text = text.replace("\r\n", "\n")
    entries, others = {}, {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return entries, others
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    for key, value in zip(node.value.keys, node.value.values):
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            uses = {name.id for name in ast.walk(value) if isinstance(name, ast.Name)}
                            entries[(target.id, key.value)] = (ast.get_source_segment(text, value), uses)
        elif isinstance(node, (ast.FunctionDef, ast.Assign)):
            names = [node.name] if isinstance(node, ast.FunctionDef) else [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in names:
                others[name] = ast.get_source_segment(text, node)
    return entries, others


def text_at(commit, path):
    """A file of the project as it is at `commit`, or as it is now (None), read as UTF-8 both ways, so that the same
    text compares equal; empty if it is not there."""
    try:
        if commit is None:
            data = open(os.path.join(PROJECT, *path.split("/")), "rb").read()
        else:
            shown = subprocess.run(["git", "show", "%s:%s" % (commit, path)], cwd=PROJECT, capture_output=True)
            if shown.returncode != 0:
                return ""
            data = shown.stdout
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def own_breaks(jobs, files, point, head=None):
    """The breaks on purpose that are a change's own, as {name: (job, reason)}, comparing `point` with `head` (None:
    the files as they are now):
    - its line in a list changed: an entry under its name, in a dict at the top of a test-tools file it uses, is new,
      or its text changed, or a function or name of that file that the entry uses (a new break is so, recorded or
      not; a break of another list with the same name comes along);
    - its first failure or its known miss in suites.py is new or changed.
    A change inside a helper that a list imports from another file shows only when every break runs."""
    lines = {}
    for path in files:
        if path.startswith("test-tools/") and path.endswith(".py") and path != "test-tools/suites.py":
            then_entries, then_others = listed(text_at(point, path))
            now_entries, now_others = listed(text_at(head, path))
            moved = {name for name in set(then_others) | set(now_others) if then_others.get(name) != now_others.get(name)}
            keys = set()
            for entry in set(then_entries) | set(now_entries):
                was, now = then_entries.get(entry), now_entries.get(entry)
                if was is None or now is None or was[0] != now[0] or now[1] & moved:
                    keys.add(entry[1])
            lines[path[len("test-tools/"):-3]] = keys
    _, caught_then, misses_then = table_on(point)
    if head is None:
        caught_now, misses_now = suites.CAUGHT_BY, suites.KNOWN_MISSES
    else:
        _, caught_now, misses_now = table_on(head)
    own = {}
    for job in jobs:
        if job.kind != "break":
            continue
        where = sorted(module for module, keys in lines.items() if module in job.needs and job.brk in keys)
        if where:
            own[job.name] = (job, "its line in %s.py is new or changed" % where[0])
        elif caught_now.get(job.name) != caught_then.get(job.name):
            own[job.name] = (job, "its first failure in suites.py changed")
        elif misses_now.get(job.name) != misses_then.get(job.name):
            own[job.name] = (job, "its known miss in suites.py changed")
    return own


def sample_breaks(jobs):
    """The first break by name of each list, among those meant to be caught: a change to what makes and judges
    breaks then shows without running them all."""
    first = {}
    for job in sorted((job for job in jobs if job.kind == "break" and job.expect == "caught"), key=lambda job: job.name):
        first.setdefault(job.catalogue, job)
    return list(first.values())


def keep_own(jobs, picked, files, point):
    """For --own-breaks: of what the change needs, every suite, and of the breaks on purpose only its own, with the
    sample of every list when anything at all is picked. Every other break runs when everything runs."""
    chosen = [job for job in picked if job.kind == "suite"]
    mine = own_breaks(jobs, files, point)
    for job, why in mine.values():
        job.reason = why
        chosen.append(job)
    if chosen:
        for job in sample_breaks(jobs):
            if job.name not in mine:
                job.reason = "the sample of its list"
                chosen.append(job)
    names = {job.name for job in chosen}
    left = len([job for job in picked if job.kind == "break" and job.name not in names])
    say("--own-breaks: %d break(s) of the change's own and %d of the sample; %d other break(s) it touches are left for "
        "the whole set" % (len(mine), len(chosen) - len(mine) - sum(job.kind == "suite" for job in chosen), left))
    return chosen


# ---------------------------------------------------------------- running one job

def kill_tree(process):
    if process.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass


def ports_free(base, seconds=15):
    """Waits until the first stand-in ports of a range can be taken again (a stopped stand-in held one)."""
    import socket
    deadline = time.time() + seconds
    while time.time() < deadline:
        free = True
        for port in range(base + 1, base + 4):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    free = False
        if free:
            return True
        time.sleep(0.5)
    return False


def sweep(folder):
    """Ends test machines left running from `folder` (a job that stopped without quitting its QEMU). Only machines
    whose command line names that folder: never another checkout's, never a window of the person's own."""
    if os.name != "nt":
        return 0
    query = ("Get-CimInstance Win32_Process -Filter \"Name='qemu-system-x86_64.exe'\" | "
             "ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.CommandLine }")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True)
    ended = 0
    for line in done.stdout.splitlines():
        number, _, command = line.strip().partition(" ")
        if number.isdigit() and os.path.normcase(folder) in os.path.normcase(command):
            subprocess.run(["taskkill", "/F", "/PID", number], capture_output=True)
            ended += 1
    return ended


def notes_kept(runs, since, stem):
    """Copies the notes of every stand-in (`*server.log` in `runs`, see model_server.py) written since `since` to
    `stem` and a dot and the notes' own name, beside a job's output: a later job on the same test machine may write
    notes of the same name, which would leave nothing to read of this job's requests and answers. A copy that fails
    is passed over."""
    try:
        names = os.listdir(runs)
    except OSError:
        return
    for name in names:
        path = os.path.join(runs, name)
        try:
            if name.endswith("server.log") and os.path.getmtime(path) >= since:
                shutil.copyfile(path, stem + "." + name)
        except OSError:
            pass


class Worker:
    def __init__(self, number, run_folder):
        self.number = number
        self.work = os.path.join(WORK, "w%d" % number)
        self.port_base = port_base() + 100 * (number - 1)
        self.run_folder = run_folder

    def env(self, job):
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
        env.update(BOOS_TEST_WORK=self.work, BOOS_PORT_BASE=str(self.port_base), BOOS_COPIES=COPIES, PYTHONUNBUFFERED="1")
        env.update(job.env)
        return env

    def run(self, job):
        """Runs one job and gives back its result: (verdict, first failure, seconds, detail, stopped at the first
        failure)."""
        verdict, first, seconds, detail, stopped = self._run(job)
        return verdict, first, seconds, detail, stopped

    def _run(self, job):
        started = time.time()
        log_path = os.path.join(self.run_folder, "".join(c if c.isalnum() or c in "-_" else "-" for c in job.name)[:90]
                                + ("-again" if job.again else "") + ".txt")
        env = self.env(job)
        with open(log_path, "w", encoding="utf-8") as log:
            log.write("# %s\n# python %s\n# worker %d, ports from %d, work %s\n" % (
                job.name, " ".join(a if len(a) < 80 else a[:60] + "..." for a in job.command), self.number, self.port_base, self.work))
            if job.prepare:
                from copy_break import NotMade as CopyNotMade
                from copy_break import make
                file, old, new = job.prepare
                try:
                    env["KERNEL_FILE"] = make(file, old, new, os.path.join(self.work, "runs", "break-kernel.efi"))
                    # The break itself too, for a copy of the kernel that the test builds of its own (look_standin.py).
                    env["KERNEL_BREAK"] = json.dumps([file, old, new])
                except CopyNotMade as reason:
                    log.write("NOT MADE: %s\n" % reason)
                    return "not made", None, time.time() - started, str(reason), False
                except RuntimeError as reason:
                    log.write("DID NOT BUILD: %s\n" % reason)
                    return "not made", None, time.time() - started, str(reason)[-300:], False
                log.write("# the copy built with the break, %.1f s\n" % (time.time() - started))
            process = subprocess.Popen([sys.executable] + job.command, cwd=HERE, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            limit = max(600, 4 * job.seconds)
            out_of_time = threading.Event()

            def too_long():
                out_of_time.set()
                kill_tree(process)
            timer = threading.Timer(limit, too_long)
            timer.start()
            lines, first, stopped = [], None, False
            for line in process.stdout:
                line = line.rstrip("\n")
                lines.append(line)
                log.write("%7.1f %s\n" % (time.time() - started, line))
                log.flush()
                if line.startswith("FAILED: ") and first is None:
                    first = line[len("FAILED: "):]
                    if job.stop_early and not job.again:
                        stopped = True
                        kill_tree(process)
                        break
            timer.cancel()
            kill_tree(process)
            seconds = time.time() - started
            timed_out = out_of_time.is_set()
            log.write("# ended after %.1f s%s\n" % (seconds, ", stopped at the first failure" if stopped else (", TIMED OUT" if timed_out else "")))
        notes_kept(os.path.join(self.work, "runs"), started, log_path[:-len(".txt")])
        if stopped or timed_out or process.returncode not in (0, None):
            ended = sweep(self.work)
            if ended:
                say("    (ended %d test machine(s) left by %s)" % (ended, job.name))
            ports_free(self.port_base)
        if job.misses:
            return self.misses_verdict(job, lines, seconds, timed_out)
        verdicts = [l for l in lines if l.startswith("FAILURES:") or l.strip() == "all as meant"]
        if stopped:
            return "failed", first, seconds, "", True
        if timed_out:
            return "error", first, seconds, "timed out after %d s" % seconds, False
        if not verdicts:
            tail = [l for l in lines if l.strip()][-3:]
            return "error", first, seconds, "no verdict line: " + " | ".join(tail)[-300:], False
        last = verdicts[-1].strip()
        if last in ("FAILURES: none", "all as meant", "FAILURES: none (all as meant)"):
            if first is not None:
                return "error", first, seconds, "the verdict says none, but a failure was printed", False
            return "passed", None, seconds, "", False
        return "failed", first, seconds, last[:200], False

    @staticmethod
    def misses_verdict(job, lines, seconds, timed_out):
        """A list that reports what it did not catch: one line per check named for the break ("<label> <check>
        caught" or "... NOT CAUGHT"), then "NOT CAUGHT: none" or the misses. The break counts as caught (its tests
        failed) only when every check named for it says so; the first of them stands for its first failure."""
        if timed_out:
            return "error", None, seconds, "timed out after %d s" % seconds, False
        said = [l.strip() for l in lines if l.startswith("NOT CAUGHT:")]
        if not said:
            tail = [l for l in lines if l.strip()][-3:]
            return "error", None, seconds, "no verdict line: " + " | ".join(tail)[-300:], False
        reports = [l[len(job.brk):].split() for l in lines if l.startswith(job.brk + " ")]
        caught = [words[0] for words in reports if words[1:] == ["caught"]]
        if said[-1] == "NOT CAUGHT: none":
            if sorted(caught) != sorted(job.checks):
                return "error", None, seconds, "none missed, but the checks said caught are %s, not %s" % (caught, job.checks), False
            return "failed", caught[0], seconds, "", False
        return "passed", None, seconds, said[-1][:200], False


# ---------------------------------------------------------------- the run

class Run:
    def __init__(self, jobs, workers, run_folder):
        self.queue = sorted(jobs, key=lambda job: -job.seconds)
        self.workers = [Worker(n, run_folder) for n in range(1, workers + 1)]
        self.lock = threading.Condition()
        self.busy = 0
        self.alone_running = False
        self.results = []
        self.stop = threading.Event()

    def next_job(self):
        with self.lock:
            while True:
                if not self.queue:
                    return None
                job = self.queue[0]
                if job.alone:
                    if self.busy == 0 and not self.alone_running:
                        self.queue.pop(0)
                        self.alone_running = True
                        self.busy += 1
                        return job
                elif not self.alone_running:
                    self.queue.pop(0)
                    self.busy += 1
                    return job
                self.lock.wait(1)

    def done_with(self, job):
        with self.lock:
            self.busy -= 1
            if job.alone:
                self.alone_running = False
            self.lock.notify_all()

    def again(self, job):
        """Queues a break to run again alone and to the end."""
        twin = Job(job.name, job.command, env=job.env, seconds=job.seconds, kind=job.kind, catalogue=job.catalogue,
                   brk=job.brk, expect=job.expect, alone=True, prepare=job.prepare, stop_early=False, misses=job.misses,
                   checks=job.checks)
        twin.again = True
        twin.reason = job.reason
        with self.lock:
            self.queue.append(twin)
            self.lock.notify_all()

    def work(self, worker):
        from turns import give_back, take_seat
        while True:
            job = self.next_job()
            if job is None:
                return
            seat = take_seat()
            try:
                verdict, first, seconds, detail, stopped = worker.run(job)
            finally:
                give_back(seat)
            self.judge(job, verdict, first, seconds, detail, stopped)
            self.done_with(job)

    def judge(self, job, verdict, first, seconds, detail, stopped):
        if job.kind == "suite":
            status = {"passed": "PASS", "failed": "FAIL"}.get(verdict, "ERROR")
            note = (first or detail) if status != "PASS" else ""
        else:
            recorded = suites.CAUGHT_BY.get(job.name)
            if verdict == "not made":
                status, note = "NOT MADE", detail
            elif verdict == "error":
                status, note = "ERROR", detail
            elif verdict == "failed" and stopped and recorded != first:
                # Caught, but not as when it was run alone: run it again alone, to the end, before it counts.
                self.again(job)
                say("%s  %-8s %-62s %5d s  first failure %r, recorded %r: again, alone" % (
                    time.strftime("%H:%M:%S"), "AGAIN", job.name[:62], seconds, first, recorded))
                return
            elif verdict == "failed":
                status = "CAUGHT" if job.expect == "caught" else "CAUGHT*"
                note = "by %s" % first + ("" if recorded == first else " (recorded: %r)" % recorded)
            else:
                status = "MISSED" if job.expect == "miss" else "NOT CAUGHT"
                note = "documented as not caught" if job.expect == "miss" else ""
        self.results.append(dict(name=job.name, status=status, seconds=seconds, note=note, first=first, kind=job.kind,
                                 again=job.again))
        say("%s  %-8s %-62s %5d s  %s" % (time.strftime("%H:%M:%S"), status, job.name[:62], seconds, note[:150]))

    def go(self):
        threads = [threading.Thread(target=self.work, args=(worker,), daemon=True) for worker in self.workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()


def default_workers():
    """As many test machines as the free memory and the free commit take, at most 4 and at most one for each two
    processors. One machine with its test needs about 0.6 GB of memory and 2 GB of commit."""
    count = min(4, max(1, (os.cpu_count() or 2) // 2))
    if os.name == "nt":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("free", ctypes.c_ulonglong), ("commit_limit", ctypes.c_ulonglong), ("commit_free", ctypes.c_ulonglong),
                        ("virtual_total", ctypes.c_ulonglong), ("virtual_free", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]
        status = Status()
        status.length = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            gb = 1024 ** 3
            count = min(count, int(status.free / gb / 0.6), int(status.commit_free / gb / 2.0))
    return max(1, count)


def share_of(jobs, text):
    """The I-th of N shares of the jobs, for --share I/N: dealt longest first by the table's seconds (then by name),
    each to the share with the least time so far. Recorded times are not used, so that every computer deals the
    same table the same way and N computers that each run one share run every job exactly once."""
    try:
        number, count = (int(part) for part in text.split("/"))
    except ValueError:
        raise SystemExit("--share takes I/N, such as 2/3")
    if not 1 <= number <= count:
        raise SystemExit("--share takes I/N with I from 1 to N, such as 2/3")
    shares = [[] for _ in range(count)]
    loads = [0] * count
    for job in sorted(jobs, key=lambda job: (-job.seconds, job.name)):
        i = loads.index(min(loads))
        shares[i].append(job)
        loads[i] += job.seconds
    mine = shares[number - 1]
    return mine, "share %d of %d: %d of the %d jobs picked (about %d of %d minutes by the table)" % (
        number, count, len(mine), len(jobs), loads[number - 1] / 60, sum(loads) / 60)


def kernel_mark():
    return hashlib.sha256(open(KERNEL, "rb").read()).hexdigest()[:16] if os.path.exists(KERNEL) else "none"


def main():
    if CLEARED:
        print("cleared from the environment, as every run does: %s" % ", ".join(CLEARED), flush=True)
    args = sys.argv[1:]
    everything = "all" in args
    listing = "--list" in args
    to_the_end = "--to-the-end" in args
    own = "--own-breaks" in args
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else None
    base = args[args.index("--base") + 1] if "--base" in args else "master"

    def words_after(option):
        if option not in args:
            return []
        rest = args[args.index(option) + 1:]
        return rest[:next((i for i, word in enumerate(rest) if word.startswith("--")), len(rest))]
    only = words_after("--only")
    share = words_after("--share")
    given = [path.replace("\\", "/") for path in words_after("--files")]

    jobs = suite_jobs()
    breaks, problems = break_jobs()
    jobs += breaks
    problems = table_problems(jobs) + problems
    if everything:
        picked = jobs
        for job in picked:
            job.reason = "everything"
    elif given:
        if own:
            raise SystemExit("--own-breaks compares the lists of breaks with a branch (--base), not with --files")
        say("as if these files changed: %s" % ", ".join(given))
        picked = plan_changed(jobs, given, None)
    else:
        try:
            point, files = changed_files(base)
        except RuntimeError as reason:
            say("cannot tell what changed (%s): everything runs" % reason)
            point, files, picked = None, [], jobs
        else:
            say("changed since %s (%s): %s" % (base, point[:7], ", ".join(files) if files else "nothing"))
            picked = plan_changed(jobs, files, point)
            if own:
                picked = keep_own(jobs, picked, files, point)
    if only:
        picked = [job for job in picked if any(job.name.startswith(word) for word in only)]
    if share:
        # Dealt before recorded times replace the table's seconds below.
        picked, note = share_of(picked, share[0])
        say(note)
    if to_the_end:
        for job in picked:
            job.stop_early = False
    times = {}
    if os.path.exists(TIMES):
        try:
            times = json.load(open(TIMES))
        except ValueError:
            times = {}
    for job in picked:
        job.seconds = times.get(job.name, job.seconds)

    for problem in problems:
        say("PROBLEM  " + problem)
    suites_picked = [job for job in picked if job.kind == "suite"]
    breaks_picked = [job for job in picked if job.kind == "break"]
    if listing:
        for job in sorted(picked, key=lambda job: (job.kind, job.name)):
            say("  %-6s %-64s %s" % (job.kind, job.name[:64], job.reason))
        say("%d suites' jobs and %d breaks on purpose would run%s" % (len(suites_picked), len(breaks_picked),
                                                                      "" if not problems else "; %d problems above" % len(problems)))
        return 1 if problems else 0
    if not picked:
        say("nothing to boot for these changes%s" % ("" if not problems else "; %d problems above" % len(problems)))
        return 1 if problems else 0

    count = workers or default_workers()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_folder = os.path.join(WORK, "run-tests", stamp)
    os.makedirs(run_folder, exist_ok=True)
    began = time.time()
    say("%d jobs (%d of suites, %d breaks on purpose), %d test machine(s) at once; logs in %s" % (
        len(picked), len(suites_picked), len(breaks_picked), count, run_folder))

    import build_all
    from turns import build_turn
    try:
        with build_turn():
            build_all.build(PROJECT)
    except SystemExit:
        say("THE BUILD FAILED: nothing was booted")
        return 1
    mark = kernel_mark()
    if any(job.prepare for job in picked):
        import copy_break
        copy_break.warm()
    if any("net_copy" in job.needs for job in picked):
        import net_copy
        from ports import standin_port
        net_copy.build(standin_port(1), roots=["a"])
    say("built and warmed in %d s; the kernel %s" % (time.time() - began, mark))

    run = Run(picked, count, run_folder)
    run.go()

    if kernel_mark() != mark:
        problems.append("the project's kernel changed during the run")
    for result in run.results:
        times[result["name"]] = round(result["seconds"])
    os.makedirs(os.path.dirname(TIMES), exist_ok=True)
    json.dump(times, open(TIMES, "w"), indent=0, sort_keys=True)

    good = {"PASS", "CAUGHT", "MISSED", "CAUGHT*"}
    bad = [r for r in run.results if r["status"] not in good]
    lines = ["", "%-10s %-64s %7s  %s" % ("", "job", "seconds", "note")]
    for result in sorted(run.results, key=lambda r: (r["status"] in good, r["kind"], r["name"])):
        lines.append("%-10s %-64s %7d  %s" % (result["status"], result["name"][:64], result["seconds"], result["note"][:120]))
    tally = {}
    for result in run.results:
        tally[result["status"]] = tally.get(result["status"], 0) + 1
    lines.append("")
    lines.append("%s; %d jobs in %.1f min with %d test machine(s) at once" % (
        ", ".join("%s %d" % (status, n) for status, n in sorted(tally.items())), len(run.results), (time.time() - began) / 60, count))
    records = [r for r in run.results if r["kind"] == "break" and r["first"] and suites.CAUGHT_BY.get(r["name"]) != r["first"]
               and r["status"].startswith("CAUGHT")]
    if records:
        lines.append("first failures not yet in suites.CAUGHT_BY (each from a run alone and to the end):")
        lines += ["    %r: %r," % (r["name"], r["first"]) for r in records if r["again"] or to_the_end]
    for problem in problems:
        lines.append("PROBLEM  " + problem)
    verdict = "ALL AS MEANT" if not bad and not problems else "NOT AS MEANT"
    lines.append(verdict)
    say("\n".join(lines))
    with open(os.path.join(run_folder, "summary.txt"), "w", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")
    return 0 if verdict == "ALL AS MEANT" else 1


if __name__ == "__main__":
    sys.exit(main())
