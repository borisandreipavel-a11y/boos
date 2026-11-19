"""Breaks made on purpose in the code that asks the model, each in a copy of the project only.
BREAKS maps a name to {file: change}."""


def swap(text, old, new):
    assert text.count(old) == 1, (old[:60], text.count(old))
    return text.replace(old, new)


def nowipe(text):
    return swap(text, "    wipe(&mut request);\n", "    // BREAK: the request is not wiped\n")


def nowipe_copy(text):
    return swap(text, "    wipe(&mut key_room);\n", "    // BREAK: the copy of the key is not wiped\n")


def nohide(text):
    return swap(text, "    key_hide(&mut signs, key);\n", "    // BREAK\n")


def cutfirst(text):
    return swap(text, "    key_hide(&mut signs, key);\n    signs.truncate(WORDS_SHOWN);\n", "    signs.truncate(WORDS_SHOWN);\n    key_hide(&mut signs, key);\n")


def length(text):
    return swap(text, "        MODEL_SITE,\n        body.len()\n", "        MODEL_SITE,\n        body.len() - 1 // BREAK\n")


def path(text):
    return swap(text, 'Step::Name("choices"), Step::Place(0)', 'Step::Name("choices"), Step::Place(1)')


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
    return swap(text, "    wipe(&mut key_room);\n",
                "    wipe(&mut key_room);\n    crate::serial::serial_print(&format!(\"TEST stack {}\\r\\n\", crate::tasks::stack_depth_now()));\n")


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
