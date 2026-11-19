"""The model for the look's own tests: keyed_model.KeyedChat, which knows the question for a look, with the look
entry given by the test (kept_look, None for no entry) and nothing answered for the test (auto_look off).
The row helpers are kept here under their old names for the tests that use them."""
from keyed_model import (KeyedChat, LOOK_QUESTION as QUESTION, NOT_A_NUMBER, SO_IT_LASTS, CANNOT_ADD,  # noqa: F401
                         look_named as named, this_is, stays, kept_row, not_kept, unknown_kept)


class LookChat(KeyedChat):
    def __init__(self, screen_width, kept_look=None, **options):
        super().__init__(screen_width, kept_look=kept_look, auto_look=False, **options)
