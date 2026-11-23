"""The table of tests that run_tests.py runs: one entry per suite, and the lists of breaks on purpose.

A suite entry says:
- name: how the runner calls it (a suite with `split` becomes one job per scenario, "<name> <scenario>");
- command: the script and its arguments, run from this folder;
- watches: the files outside test-tools that it is about, besides the ones that every start runs through. A change
  to a kernel file that no entry watches runs every suite, because nearly every file of the kernel runs at every
  start; a change to a test script runs every suite that uses it (read from the scripts' imports, nothing to list);
- split (optional): run each scenario as a job of its own, so that they can run at once: True for the scenarios of
  the script's SCENARIOS, "file.py NAME" for the keys of the dict NAME in that file, or a list of the names the
  script takes as arguments (each must stand in the script's text);
- leave_out (optional, with split): scenarios that are not run, each with the reason, as {scenario: why};
- env (optional): environment for the script, as {name: value};
- alone (optional): nothing else of the same run at the same time (for a script that changes the project's own
  source for a moment);
- seconds (optional): about how long it takes, so that the longest jobs start first. A run notes the real times
  in its work folder and uses those afterwards.

To add a suite: one entry here. A new test_*.py that is neither in an entry nor in EXCUSED stops the runner, so a
test cannot be left out by mistake. This file holds data only: run_tests.py reads it, and compares it with the
version on master to run only the entries that changed."""

# The 46 kinds of answer to a request for an app (runrandom twice: random numbers must differ from run to run).
APP_KINDS = ("app,appfenced,appprose,appopen,appclose,apptwo,appmarksonly,appcut,appfiltered,appthink,appnull,appexact,appover,"
             "appodd,appecho,apppieces,appspaces,appcrlf,appnoending,apponeline,slowapp,realrefusal,upstream,upstreambare,huge,"
             "nothttp,otherform,streamed,runshow,runprint,runcut,runcut41,runexact40,runsplit,runloop,runmemory,runmistake,"
             "runsyntax,runmanyshow,runmanyprint,runrandom,runrandom,runreal,runslow,runnil,runrecurse")
# The 39 kinds of answer to `ask`: every one that test_model.py knows (its MEANT).
MODEL_KINDS = ("wrongkey,credit,echo,echopart,echoescaped,echocut,good,goodlong,harmful,flaterror,keepopen,page,nobody,chunked,"
               "cutoff,nothttp,huge,silent,empty,lengthempty,lengthnull,nullthink,pieces,lengthwords,filtered,filteredwords,spaces,"
               "nocontent,oddending,noending,blank,echo200,nochoices,streamed,otherform,echobody,notfound,upstream,upstreambare")
# The good answers among them, which the stand-in can send piece by piece, as a line asks for its answer: the rows meant
# are the same.
MODEL_PIECE_KINDS = "good,goodlong,lengthempty,lengthnull,nullthink,pieces,lengthwords,filtered,filteredwords,spaces,nocontent,oddending,noending,blank,echo200"

# Kernel files that only some suites go through. Every other file in src/ is on the path of every start.
STAND_IN = ["src/model.rs", "src/page.rs", "src/errand.rs"]  # asking the provider (the stand-in in tests)
APPS = ["src/apps.rs"]
SECRET = ["src/secret.rs"]  # a key or a password typed and kept
FILES = ["src/files.rs", "src/download.rs", "src/notebook.rs", "src/parts.rs", "src/disk.rs", "src/tls.rs"]  # files from the web, kept
DOCUMENTS = ["src/documents.rs", "src/drawing.rs", "src/notebook.rs"]  # tables kept as documents

SUITES = [
    dict(name="app", command=["test_app.py", APP_KINDS, "dump"], watches=STAND_IN + APPS + SECRET, seconds=420),
    dict(name="app nocard", command=["test_app.py", "nocard"], watches=STAND_IN + APPS, seconds=25),
    dict(name="app first start keylater", command=["test_app_first_start.py", "keylater"], watches=STAND_IN + APPS + SECRET, seconds=40),
    dict(name="app first start keyfirst", command=["test_app_first_start.py", "keyfirst"], watches=STAND_IN + APPS + SECRET, seconds=40),
    dict(name="try", command=["test_try.py"], split=True, watches=STAND_IN + SECRET,
         seconds=dict(refused=60, setup=50, answers=95, during=62, nocard=30, busy=88, odd200=38)),
    dict(name="key model", command=["test_key_model.py"], watches=STAND_IN + SECRET, seconds=55),
    dict(name="key", command=["test_key.py"], split=True, watches=SECRET,
         seconds=dict(locked=100, older=60, thisstart=68, setup=72, stays=22, odd=138, norandom=37, small=68, noscreen=51, during=24)),
    dict(name="name", command=["test_name3.py"], split=True, watches=[],
         seconds=dict(first=68, enter=38, limit=42, none=22, upgrade=35, unanswered=33, odd=34, damaged=36, small=28, noscreen=32)),
    dict(name="key memory", command=["test_key_memory.py"], watches=SECRET, seconds=230),
    # The secret line, and the start's own report (lines to the prompt, plain text only): boot_count.py's check, made
    # from this test's start, which is the same kind of start.
    dict(name="secret line", command=["test_secret_keyed.py"], watches=SECRET, seconds=100),
    # The chat box's limits and every sign, then Shift in the same start (test_shift.py's steps).
    dict(name="chat box and shift", command=["test_more.py", "more-shift", "shift"], watches=[], seconds=75),
    # The line typed in the chat box: 200 signs, the row being typed growing upward, the keys that edit the line, Up
    # and Down, and a long line typed while an answer comes in (test_chat_line.py).
    dict(name="chat line", command=["test_chat_line.py"], split=True, watches=STAND_IN,
         seconds=dict(edit=125, small=85, noscreen=70, restart=75, stream=95)),
    dict(name="model", command=["test_model.py", MODEL_KINDS], env={"DIVIDED_DISK": ""}, watches=STAND_IN + SECRET, seconds=260),
    dict(name="model piece by piece", command=["test_model.py", MODEL_PIECE_KINDS, "pieces"], env={"DIVIDED_DISK": ""},
         watches=STAND_IN + SECRET, seconds=120),
    dict(name="look", command=["test_look.py"], split=True, watches=SECRET,
         seconds=dict(pick=66, atonce=33, his=42, setup=39, norandom=18, stays=38, nonotebook=22, odd=86, locked=55, damaged=20,
                      small=35, noscreen=29)),
    dict(name="look on a person's path", command=["test_look_his.py"], watches=["make-disk.ps1"] + SECRET, seconds=120),
    dict(name="look reset", command=["test_look_reset.py"], split=True, watches=SECRET,
         seconds=dict(atonce=40, midway=35, again=40, unchanged=40, nonotebook=22, damaged=40, locked=55, noscreen=32, small=21)),
    # Every scenario boots the stand-in copy. "older" builds the kernel of an older commit from a clean export of it.
    dict(name="apps kept", command=["test_apps_kept.py"], split=True, watches=STAND_IN + APPS,
         leave_out={"times": "a measurement of how long keeping and opening take, with no verdict"},
         seconds=dict(first=55, make=105, echo=40, outside=20, requests=65, look=25, small=20, damaged=20, full=100, failing=60,
                      cut=360, older=90)),
    # Every line to the model, in the stand-in copy, whose stand-in answers each line with words or a tool call
    # (model_server.py). src/tools.rs is watched by no entry, so a change to it runs every suite: every line goes there.
    dict(name="chat tools", command=["test_chat_tools.py"], split=True, watches=STAND_IN + APPS,
         seconds=dict(nokey=30, words=80, dice=70, pages=45, odd=130, busy=40, nocard=20, nodisk=30, remember=90, forgetting=110,
                      bound=125, rounds=120, table=110, tablesmall=40, inputs=120, inputsodd=150, stream=120)),
    # Files fetched from the web and kept on the disk, in the stand-in copy, whose stand-in serves made-up files.
    dict(name="downloads", command=["test_downloads.py"], split=True, watches=STAND_IN + FILES,
         seconds=dict(fetch=110, refusals=330, remove=110, startlines=60, full=50)),
    # Documents: tables kept on the disk, opened and changed by a wish, in the stand-in copy.
    dict(name="documents", command=["test_documents.py"], split=True, watches=STAND_IN + DOCUMENTS,
         seconds=dict(keep=120, cut=110, odd=120, broken=70)),
    # The kernel's own lines on the screen. "noserial" and "later" build a copy of their own (lines_copy.py).
    dict(name="lines", command=["test_lines.py"], split=["start", "early", "small", "noscreen", "noserial", "later", "held"],
         watches=[], seconds=dict(start=45, early=20, small=45, noscreen=20, noserial=75, later=30, held=25)),
    # The stop screen after a failure or a panic made on purpose, each in a copy built for it.
    dict(name="lines stop", command=["test_lines_stop.py"], split="lines_checks.py STOP_CASES", watches=[],
         seconds={"stop-firmware": 15, "stop-own": 15, "stop-panic": 15, "stop-picture": 20, "stop-view": 20, "stop-task": 40}),
    # The boot disk (make-boot-disk.ps1): a new one read from outside, QEMU started from it alone, another kernel
    # written into it, and the files the script must refuse.
    dict(name="boot disk", command=["test_boot_disk.py"], split=["made", "start", "again", "refuses"],
         watches=["make-boot-disk.ps1", "make-disk.ps1"], seconds=dict(made=20, start=40, again=60, refuses=60)),
    # The script's breaks on purpose: each made in a copy of the script, which the boot disk's test must catch. They
    # change no file of the kernel, so they run as one job, through their own list.
    dict(name="boot disk breaks", command=["run_boot_disk_breaks.py"], watches=["make-boot-disk.ps1", "make-disk.ps1"],
         seconds=300),
    # Intel's network card (src/intel_card.rs), as QEMU plays it. "again", "many" and "page" build a copy of their own
    # (net_copy.py). src/intel_card.rs is watched by no entry: every start with a virtio card asks it whether an Intel
    # card is in use, so a change to it runs every suite.
    dict(name="intel card", command=["test_intel_card.py"], split=True, watches=[],
         seconds=dict(start=35, address=30, model545=30, both=30, fallback=30, nothing=35, asking=35, again=60, many=90,
                      page=100)),
    # The model's answers and three scenarios of every line to the model, with the Intel card in place of the virtio
    # card (BOOS_NETWORK_CARD, read by boot.py).
    dict(name="model on the Intel card", command=["test_model.py", MODEL_KINDS], env={"DIVIDED_DISK": "", "BOOS_NETWORK_CARD": "e1000"},
         watches=STAND_IN + SECRET, seconds=260),
    dict(name="chat tools on the Intel card", command=["test_chat_tools.py"], split=["words", "dice", "odd"],
         env={"BOOS_NETWORK_CARD": "e1000"}, watches=STAND_IN + APPS, seconds=dict(words=80, dice=70, odd=130)),
]

# Scripts named test_*.py or run_*_breaks.py that are no entry of their own, and why.
EXCUSED = {
    "test_shift.py": "runs in test_more.py's start (the entry 'chat box and shift')",
    "run_regress_try.py": "an older list of suites, run one after another; run_tests.py all covers it",
    "run_regress_look.py": "an older list of suites, run one after another; run_tests.py all covers it",
    "run_regress_apps.py": "an older list of suites, run one after another; run_tests.py all covers it",
    "run_regress_kept.py": "an older list of suites, run one after another; run_tests.py all covers it",
}

# Files no test runs or reads: a change to them alone boots nothing. Anything not named here or in an entry, and not
# words only (WORDS), runs everything.
NO_TEST = [".github/", "lua/", "release/", "run.bat", "run-boot-disk.bat", "test-tools/check_lua.py", "test-tools/export_check.py", "test-tools/time_look.py",
           "test-tools/time_repaint.py", "test-tools/time_lines.py", "test-tools/make_lock_values.py", "test-tools/restore.py",
           "test-tools/crlf.py"]
# Words only: a change to these boots nothing.
WORDS = [".md", "LICENSE", "LICENSE-MIT", "LICENSE-APACHE", ".gitignore", ".gitattributes"]

# The lists of breaks on purpose, and how many each must hold, so that a list that loses breaks is noticed.
BREAK_COUNTS = {"apps": 17, "try": 10, "key": 25, "look": 23, "model": 17, "kept": 17, "reset": 8, "lines": 18, "tools": 50,
                "intel": 10, "downloads": 10, "documents": 11}

# Breaks on purpose known not to be caught, from any list, each with the reason (docs/testing.md tells more). The runner
# still makes and runs them, and counts them as missed, as meant. The key's and the model's lists name their own
# (MISSES in run_key_breaks.py and model_breaks.py).
KNOWN_MISSES = {}

# The first failure that caught each break on purpose when it was run alone and to the end. A run that stops at the
# first failure counts a break as caught only when its first failure is this one; any other first failure (a wait in
# vain under load, say) makes the runner run that break again alone and to the end.
CAUGHT_BY = {
    'break apps: noinstructions': 'request 1',
    'break apps: nomarks': 'appfenced: run row',
    'break apps: nolength': 'appcut: a run that was not meant',
    'break apps: nolimit': 'appover: a run that was not meant',
    'break apps: noclean': 'appodd: script lines',
    'break apps: nocut': 'appodd: script lines',
    'break apps: nohide': 'appecho: app lines',
    'break apps: asktokens': 'line request 1',
    'break apps: nolead': 'request 1',
    'break apps: norun': 'app: run row',
    'break apps: noseed': 'random numbers repeat from run to run',
    'break apps: noseedlua': 'random numbers repeat from run to run',
    'break apps: nocut40': 'runcut41: run row',
    'break apps: fuelkind': 'runloop: run row',
    'break apps: gaveupkind': 'runmemory: run row',
    'break apps: mistakekind': 'runmistake: run row',
    'break apps: shownothing': 'runprint: run row',
    'break try: the refused key not wiped': 'try-b memory',
    'break try: the refused key kept': 'try-b memory',
    'break try: the try lends the kept key': 'try-a 1-refused-asked-again',
    'break try: keys typed during the try taken': 'try-d 2-refused-after-the-wait',
    'break try: nothing said about signs not taken': 'try-d 2-refused-after-the-wait',
    'break try: 403 taken as unknown': 'try-c 1-known-403',
    'break try: a reasonless 401 not taken as unknown': 'try-c 6-unread-401',
    'break try: a 403 page taken as known': 'try-c 3-page-403',
    'break try: a key that cannot be tried not kept': 'try-e 2-locked',
    "break try: the try's answer not handed to the onboarding": "try-a waited for ('choose a password', 'does not know that key')",
    'break key: no least length': 'locked 3-too-short',
    'break key: the typed signs not wiped': '2-key-handed-over: key whole 2 (meant 1), loose 0',
    'break key: the password not forgotten after locking': '5-locked: pw whole 1 (meant 0), loose 0',
    'break key: the second password not compared': 'locked 4-differ',
    'break key: the key typed as a plain line': 'locked 1-key-typed-as-stars',
    'break key: the unlocked key not kept': 'locked-2 4-asked',
    'break key: no key not noted': 'first terminal/disk',
    'break key: every refusal taken for a wrong password': 'odd-version 1-refused',
    'break key: the question for a new key not used at setup': 'stays 2-key-question-again',
    'break key: line: the 201st sign taken': 'line-edit 6-200-the-limit',
    'break key: line: the rows of what was said not made fewer': 'line-edit 3-95-two-rows',
    'break key: line: the rows not painted again when the row being typed grows': 'line-edit 3-95-two-rows',
    'break key: line: a sign put at the end, not at the place': 'line-edit 10-changed-below-the-tails',
    'break key: line: Delete taking the sign before the place': 'line-edit 10-changed-below-the-tails',
    'break key: line: Right not moving the place': 'line-edit 8-on-a-typed-underscore',
    'break key: line: the place shown as a _ over its sign': 'line-edit 7-home',
    'break key: line: Left not known behind the mark': 'line-edit 11-taken-before-the-place',
    'break key: line: the new keys typed into a secret': 'line-edit 20-stars-stay-five',
    'break key: line: the line sent not kept for Up': 'line-edit 14-up-brings-it-back',
    'break key: line: Down losing what was typed': 'line-edit 18-down-the-draft-again',
    'break key: line: Up while the kernel asks a question of its own': 'line-restart-2 4-up-during-the-name-question',
    'break key: line: the kept line not read for Up at a start': 'line-restart-2 3-up-brings-it-back',
    'break key: line: the kept line said cut at 50': 'line-restart-2 2-said-again-whole',
    'break look: the panel not painted again': 'pick-1 1-name-question',
    'break look: the background not painted again': 'pick-1 1-name-question',
    "break look: the panel's text not remembered": 'pick-1 1-name-question',
    "break look: the kernel's letters keep the first look's colour": 'pick-1 3-night',
    'break look: the sentence stays white': 'pick-1 3-night',
    'break look: a number one off': 'pick-1 3-night',
    'break look: a tried look not shown at once': 'pick-1 3-night',
    'break look: the kept look not written': 'pick-1 terminal/disk',
    'break look: the kept look not read at startup': 'pick-2 1-next-start-in-night-no-question',
    'break look: the answer kept as the last line': 'pick-1 terminal/disk',
    'break look: a look kept although none was tried': 'at-once-1 1-blue-stays',
    'break look: a kept look found whatever its capitals': 'case 1-blue-a-row-and-the-question',
    'break look: no row for a kept look the kernel does not know': 'unknown 1-blue-a-row-and-the-question',
    'break look: the onboarding never asks for a look': 'pick-1 2-list-from-the-onboarding',
    'break look: the closing words not taken away': 'pick-1 2-list-from-the-onboarding',
    'break look: asked although the notebook holds an answer': 'pick-2 1-next-start-in-night-no-question',
    'break look: not asked after setup': 'setup-1 1-question-after-setup',
    'break look: Enter alone at once notes nothing': 'at-once-1 terminal/disk',
    'break look: an entry with no signs not taken as an answer': 'at-once-2 1-no-question',
    'break look: a look the kernel does not know taken as an answer': 'unknown 1-blue-a-row-and-the-question',
    'break look: the question not last at startup': 'unknown 1-blue-a-row-and-the-question',
    'break look: the first row says one question when the look follows': 'norandom 1-a-few-questions',
    'break look: no question after the key is locked': "locked-1 waited for ('pick a look by number',)",
    'break model: nohide': 'echo',
    'break model: cutfirst': 'echocut',
    'break model: length': 'stand-in: length note right',
    'break model: path': 'good',
    'break model: toolong': 'huge',
    'break model: nokeycheck': 'good',
    'break model: othername': 'good',
    'break model: shortprefix': 'echocut',
    'break model: nobeginning': 'otherform',
    'break model: noending': 'lengthwords',
    'break model: notrim': 'spaces',
    'break model: nopieces': 'pieces',
    'break model: no5xx': 'upstream',
    'break model: nostrict': 'nochoices',
    'break model: nothought': 'lengthempty',
    'break kept: nowholecheck': 'outside lines about apps',
    'break kept: noorder': 'outside lines about apps',
    'break kept: nopiecelimits': 'kept-outside start',
    'break kept: nofullpieces': 'kept-outside start',
    'break kept: nothinglimit': 'kept-outside start',
    'break kept: piecesdecideend': 'kept-outside start',
    'break kept: noroom': 'kept-full-script entries added',
    'break kept: nopieceadvance': 'failing the next line not kept',
    'break kept: nokeep': "kept-make kept 'a dice that rolls'",
    'break kept: keepstopped': "kept-make not kept 'an app with a mistak'",
    'break kept: nosamerequest': 'make entries added',
    'break kept: oldestfirst': 'kept-make-again start',
    'break kept: requestnotcleaned': 'kept-requests start',
    'break kept: leadingzero': 'kept-requests start',
    'break kept: notwholelisted': 'kept-outside start',
    'break kept: nolookrepaint': 'kept-look night',
    'break kept: sixapps': 'kept-small start',
    'break reset: setup leaves the look as it was': 'at-once-1 2-blue-at-once',
    'break reset: the first look not put in use': 'at-once-1 2-blue-at-once',
    'break reset: the screen not painted again at setup': 'at-once-1 2-blue-at-once',
    'break reset: the first look not kept on the disk': 'midway-1 terminal/disk',
    'break reset: the look kept before still counted as kept': 'again-1 2-night-kept',
    'break reset: an entry although look 1 is kept': 'unchanged-blue terminal/disk',
    'break reset: nothing said when the first look cannot be kept': 'damaged-1 3-rows-about-the-look',
    'break reset: the rows about the look without the closing words': 'damaged-1 3-rows-about-the-look',
    'break lines: the lines not shown while the machine starts': 'start',
    'break lines: the usual picture not held': 'start',
    'break lines: the start screen never ends': 'start',
    'break lines: the usual picture not painted when the lines go': 'start',
    "break lines: the tasks' lines not painted by the main loop": 'start',
    'break lines: F1 does nothing': 'start',
    'break lines: a key does not end the lines': 'start',
    'break lines: F1 held down counted again': 'held',
    'break lines: lines printed while F1 shows them not painted': 'later',
    'break lines: the screen not filled when the lines are painted whole': 'small',
    'break lines: the older lines do not move up': 'small',
    'break lines: a long line not carried on in the next row': 'small',
    'break lines: the lines kept only with a serial port': 'noserial',
    'break lines: the stop screen not painted after a failure': 'stop-picture',
    'break lines: the stop screen not painted after a panic': 'stop-panic',
    'break lines: the report left off the stop screen': 'stop-own',
    "break lines: a failure early on painted in the lines' colours": 'stop-firmware',
    'break lines: no stop screen while the lines cover the screen': 'stop-view',
    'break tools: echo': "tools-nokey 'hello'",
    'break tools: nokeycheck': "tools-nokey 'hello'",
    'break tools: nolooktool': 'words the request for a line',
    'break tools: norunlist': 'dice the line asked about again',
    'break tools: nopagetool': 'pages the first request',
    'break tools: kernelwords': "tools-words 'hello'",
    'break tools: notokens': "tools-words 'hello'",
    'break tools: nocache': "tools-words 'count please'",
    'break tools: nomore': "tools-odd 'two looks'",
    'break tools: nokeyhide': "tools-odd 'an app with my key'",
    'break tools: remake': "tools-dice-again 'roll the dice'",
    'break tools: rawrequest': "tools-odd 'an app with my key'",
    'break tools: nonumbertext': "tools-odd 'as text'",
    'break tools: looknotkept': "tools-odd 'two looks'",
    'break tools: pagenotturned': 'tools-pages page-2',
    'break tools: jsonfraction': 'words the check of JSON at startup',
    'break tools: norecord': 'remember the second request goes with the first',
    'break tools: nolinememory': "tools-remember 'I would like a dice to r'",
    'break tools: nokernelrows': 'remember the first line asked about again',
    'break tools: nopersonlabel': 'remember the second request goes with the first',
    'break tools: nostar': 'forgetting line 2',
    'break tools: nolinecount': 'bound line 12',
    'break tools: nobytebound': 'bound line 22',
    'break tools: nosetupforget': 'forgetting line 9',
    'break tools: noforgettool': 'forgetting line 2',
    'break tools: forgetnothing': 'forgetting line 6',
    'break tools: awaitedkept': 'forgetting line 9',
    'break tools: noback': "tools-rounds 'pick a look'",
    'break tools: lookback': 'rounds a look that is picked does not go back',
    'break tools: appnoback': "tools-dice 'I would like a dice to r'",
    'break tools: asksfour': 'rounds the fix: two asks again',
    'break tools: lastwithtools': 'rounds line request 3',
    'break tools: twice': "tools-rounds 'two looks at once'",
    'break tools: newpiece': 'rounds line request 3',
    'break tools: nostarkept': 'rounds line request 15',
    'break tools: tablefaint': 'tools-table fruit',
    'break tools: tablewanted': "tools-table 'a broken one'",
    'break tools: headnotchecked': 'inputsodd the bad head is left out',
    'break tools: valueswanted': "tools-inputsodd 'run with a wrong name'",
    'break tools: inputsnotkept': "tools-inputs 'convert 12 km'",
    'break tools: missingtaken': "tools-inputs 'convert km to miles'",
    'break tools: numbernotchecked': "tools-inputsodd 'make missing'",
    'break tools: nodone': "tools-stream 'think first'",
    'break tools: noholdback': 'tools-stream words',
    'break tools: nohidesofar': 'tools-stream keyed',
    'break tools: firstpart': "tools-stream 'a table, cut'",
    'break tools: nochunked': "tools-stream 'in chunks'",
    'break tools: brokendone': "tools-stream 'a dice, cut'",
    'break tools: growstays': 'tools-stream thought',
    'break tools: nothinking': 'tools-stream thinking',
    'break downloads: noidentity': 'dl-fetch GET /go/a.pdf',
    'break downloads: nolengthcap': "dl-refusals 'You: fetch /big.pdf'",
    'break downloads: chunkedtaken': "dl-refusals 'You: fetch /chunked.pdf'",
    'break downloads: packedtaken': "dl-refusals 'You: fetch /gz.pdf'",
    'break downloads: noyes': "dl-fetch 'You: get https://files.example.org/go/a.pdf'",
    'break downloads: sixhops': "dl-refusals 'You: fetch /hops/1'",
    'break downloads: sitenotkept': 'fetch sites kept',
    'break downloads: removenotkept': 'remove file 1 removed',
    'break downloads: notebookwhole': "fetch the notebook's room",
    'break downloads: noloopcheck': "dl-refusals 'You: fetch /loop/1'",
    'break intel: receiving never switched on': 'start: the network lines are not as meant',
    'break intel: the card may not reach memory': 'start: the network lines are not as meant',
    'break intel: a used card not started over': 'again: the second setup did not start the card over, once',
    'break intel: the address read with its bytes swapped': 'start: the network lines are not as meant',
    "break intel: a packet's length read from the wrong place": 'start: the network lines are not as meant',
    'break intel: a received slot never handed back': 'many: not every one of 600 questions was answered',
    'break intel: the send ring does not go round': 'many: not every one of 600 questions was answered',
    'break intel: the virtio card not looked for first': 'both: the network lines are not as meant',
    'break intel: no Intel card after a virtio card that cannot be set up': 'fallback: the network lines are not as meant',
    'break intel: the gateway asked once only': 'asking: the kernel asked for the gateway 1 times, not twice',
    'break documents: cutchangekept': "doc-cut 'add their moons'",
    'break documents: closedchanged': "doc-cut 'add moons to the planets'",
    'break documents: wantedwithoutopen': "doc-cut 'add moons to the planets'",
    'break documents: documentlinekept': 'keep request 2',
    'break documents: nolines': 'keep request 2',
    'break documents: openends': "doc-keep-2 'open the planets'",
    'break documents: namenotcleaned': 'doc-odd squares',
    'break documents: oldestfirst': 'keep restart the lines about documents',
    'break documents: numberreused': "doc-odd-2 'fruit please'",
    'break documents: nopanel': 'doc-keep-2 restart',
    'break documents: setupkeepsopen': 'doc-keep-2 setup',
}
