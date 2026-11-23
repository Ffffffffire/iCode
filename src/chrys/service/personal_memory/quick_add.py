# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Turn a one-line ``/memory add`` argument into a memory draft.

The command is a consent artifact: the user typed it, so no language guessing
happens here. The only decisions are formatting ones, kept pure so they can be
checked without a screen.
"""

from __future__ import annotations

from chrys.foundation.models.personal_memory import MemoryDraft

TITLE_CHARS = 60
CONTENT_CHARS = 600
_SENTENCE_ENDS = "。！？；!?;\n"  # noqa: RUF001 - the CJK stops are the boundaries being matched


class QuickAddError(ValueError):
    """The command line cannot become a memory without more detail."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _title_of(text: str) -> str:
    head = text
    for index, character in enumerate(text):
        if character in _SENTENCE_ENDS:
            head = text[:index]
            break
    head = head.strip(" \t，,：:")  # noqa: RUF001 - trimmed punctuation from the user's own line
    if len(head) > TITLE_CHARS:
        head = head[:TITLE_CHARS].rstrip()
    return head or text[:TITLE_CHARS]


def draft_from_text(text: str) -> MemoryDraft:
    """Keep the user's words as content and take the first sentence as the title."""

    content = " ".join(text.split())
    if not content:
        raise QuickAddError("memory_text_missing")
    if len(content) > CONTENT_CHARS:
        raise QuickAddError("memory_text_too_long")
    return MemoryDraft(title=_title_of(content), content=content, when_to_use="")
