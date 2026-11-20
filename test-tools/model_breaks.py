"""Breaks made on purpose in the code that asks the model, each in a copy of the project only.
BREAKS maps a name to {file: change}."""


def swap(text, old, new):
    assert text.count(old) == 1, (old[:60], text.count(old))
    return text.replace(old, new)


def nowipe(text):
    return swap(text, "    wipe(&mut request);\n", "    // BREAK: the request is not wiped\n")


# The end of model_tell, the question's path: model_app has a room of its own, ended the same way.
TELL_END = "        question_ask(interface, card, sockets, name_server, &key_room[..key_length])\n    };\n"


def nowipe_copy(text):
    return swap(text, TELL_END + "    wipe(&mut key_room);\n", TELL_END + "    // BREAK: the copy of the key is not wiped\n")


def nohide(text):
    # In words_cut, which every row with the model's words goes through; app_sentence hides the key in a script too.
    return swap(text, "    key_hide(&mut signs, key);\n    signs.truncate(longest);\n", "    // BREAK\n    signs.truncate(longest);\n")


def cutfirst(text):
    return swap(text, "    key_hide(&mut signs, key);\n    signs.truncate(longest);\n", "    signs.truncate(longest);\n    key_hide(&mut signs, key);\n")


def length(text):
    return swap(text, "        MODEL_SITE,\n        body.len()\n", "        MODEL_SITE,\n        body.len() - 1 // BREAK\n")


def path(text):
    # The path to the model's words; the paths to the pieces, the ending and the thoughts begin the same way.
    return swap(text, "const WORDS: &[Step<'static>] = &[Step::Name(\"choices\"), Step::Place(0)",
                "const WORDS: &[Step<'static>] = &[Step::Name(\"choices\"), Step::Place(1)")


def toolong(text):
    return swap(text, "        if answer.len() + bytes.len() <= ANSWER_ROOM {\n", "        if true { // BREAK\n")


def nokeycheck(text):
    return swap(text, "                if secret_length() == 0 {\n", "                if false { // BREAK\n")


def othername(text):
    # The request goes to the provider's machine, but the link is told to expect another site's certificate.
    return swap(text, "    let result = site_exchange(interface, card, sockets, name_server, MODEL_SITE, &request,", "    let result = site_exchange(interface, card, sockets, name_server, \"other.example\", &request,")


def stack_tasks(text):
    # Not a break: a measurement. Every new task's stack is filled with a pattern.
    text = swap(text, "        let top = stack + TASK_STACK_SIZE as u64;\n",
                "        let top = stack + TASK_STACK_SIZE as u64;\n        core::ptr::write_bytes(stack as *mut u8, 0xA5, TASK_STACK_SIZE); // TEST\n")
    return text + """
// TEST: how many bytes of the running task's stack were ever touched.
pub fn stack_depth_now() -> usize {
    unsafe {
        let stack = TASKS[CURRENT_TASK].stack as *const u8;
        let mut untouched = 0;
        while untouched < TASK_STACK_SIZE && stack.add(untouched).read_volatile() == 0xA5 {
            untouched += 1;
        }
        TASK_STACK_SIZE - untouched
    }
}
"""


def stack_model(text):
    return swap(text, TELL_END + "    wipe(&mut key_room);\n",
                TELL_END + "    wipe(&mut key_room);\n    crate::serial::serial_print(&format!(\"TEST stack {}\\r\\n\", crate::tasks::stack_depth_now()));\n")


# name: (the cases of test_model.py that should catch it, whether the memory is searched after the last answer)
CATCH = {
    "nowipe": ("good", True),
    "nowipe_copy": ("good", True),
    "nohide": ("echo,echopart", False),
    "cutfirst": ("echocut", False),
    "length": ("good", False),
    "path": ("good", False),
    "toolong": ("huge", False),
    "nokeycheck": ("good", False),
    "othername": ("good", False),
}
# Known not to be caught (docs/testing.md): what was left behind had been written over by the time of the dump.
MISSES = {"nowipe", "nowipe_copy"}

BREAKS = {
    "stack": {"tasks.rs": stack_tasks, "model.rs": stack_model},
    "nowipe": {"model.rs": nowipe},
    "nowipe_copy": {"model.rs": nowipe_copy},
    "nohide": {"model.rs": nohide},
    "cutfirst": {"model.rs": cutfirst},
    "length": {"model.rs": length},
    "path": {"model.rs": path},
    "toolong": {"model.rs": toolong},
    "nokeycheck": {"chat.rs": nokeycheck},
    "othername": {"model.rs": othername},
}
