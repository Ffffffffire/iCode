# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Titles carry the topic, so a rename stays searchable and short.

The rules mirror how iCode titles sessions: a noun phrase about the topic, not a
sentence with a conclusion, and no trailing punctuation.
"""

from __future__ import annotations

MAX_TITLE_CHARS = 40
_SENTENCE_ENDS = ("\u3002", ".", "!", "\uff01", "?", "\uff1f", "\uff1b", ";", "\uff0c", ",")


def title_problem(title: str) -> str:
    """Return why *title* cannot serve as a topic, or an empty string when it can."""

    value = title.strip()
    if not value:
        return "Give the memory a short title."
    if "\n" in value or "\r" in value:
        return "Keep the title on one line."
    if len(value) > MAX_TITLE_CHARS:
        return f"Shorten the title to at most {MAX_TITLE_CHARS} characters."
    if value.endswith(_SENTENCE_ENDS):
        return "Drop the sentence punctuation from the title."
    if "\uff0c" in value or "," in value:
        return "Use a noun phrase; move the clause after the comma into the content."
    return ""
