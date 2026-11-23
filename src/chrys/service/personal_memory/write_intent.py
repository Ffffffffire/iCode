# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Ground durable write authorization in the current user's words.

Two layers share this module. ``save_request`` recognizes a request form and is
only a fast path: a miss defers to a visible confirmation, never to a refusal.
``validate_consent`` checks the span a write relies on without reading its
meaning, so every language gets the same guarantees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MEMORY_NAME = (
    r"(?:(?:我(?:自己)?的|你的|(?:my|your|our|the|this|that|a)\b)\s*)?(?:用户级\s*)?"
    r"(?:(?:个人|个性化|长期|(?:personal(?:ized)?|long[- ]term)\b)\s*)?"
    r"(?:记忆(?:库)?|memor(?:y|ies)(?:[ \t]+(?:bank|store))?)(?:[ \t]*(?:里面|里|中))?"
)
# A destination must end as a noun. For example, memory.md and memory settings
# describe files or settings rather than a request to retain the lesson.
_DESTINATION = _MEMORY_NAME + (
    r"(?=[ \t\r]*(?:$|[。\uff01\uff1f\uff1b\uff0c\uff1a,;!?:\n]|\.(?![\w/\\])|"
    r"以便|用于|便于|方便|作为|留作|留着|备用|供|下次|后再|for\b|so\b))"
)
_STORAGE_ACTION = (
    rf"(?:写|存|保存|记|记录|加|添加|沉淀|纳)(?:到|进|入(?:到)?|至)\s*{_DESTINATION}"
    rf"|(?:存|保存|记录|留)(?:为|成)\s*(?:一条\s*)?{_DESTINATION}"
    rf"|(?:save|store|write|record|add)\b[^。.!?;,\n]{{0,120}}?\b(?:to|into|in|as)\s+{_DESTINATION}"
)
_CORRECTION_ACTION = (
    rf"(?:更新|修改|修正|纠正)\s*(?:这[条个]|(?:现有|已有|原有)的?)?\s*{_DESTINATION}"
    rf"|(?:update|correct|revise)\s+{_DESTINATION}"
)
_REMEMBER_ACTION = r"记住|记下来|remember\b"
_NEGATION = (
    r"(?:不要|不必|不用|不需要|无需|不(?=写入|存入|保存|记录|更新)|别|勿|没有要求|没有让|没让|"
    r"don['\u2019]t\b|do not\b|never\b)"
)
_SENTENCE_END = re.compile(r"[。\uff01\uff1f\uff1b.!?;\n]")
_CLAUSE_END = r"。\uff01\uff1f\uff1b.!?;\n\uff0c,"
_REQUEST_PREFIX = (
    rf"(?:^|(?<=[{_CLAUSE_END}])|(?<=[后并再])|(?<=and )|(?<=then ))\s*"
    r"(?:如果方便\s*[\uff0c,]\s*|if possible,\s*)?"
    r"(?:(?:请|麻烦你?|帮我|你要|你可以|希望你|我希望你|然后|接着|同时|顺便)\s*|"
    r"please\s+|can you\s+|could you\s+|i want you to\s+){0,3}"
)
_TOPIC = (
    r"(?:这些|这[条个套份]|(?:上述|以上|上面)(?:的)?)(?:提示词|偏好|结论|方法|经验|知识|要点|结果|分析|总结|做法|规则)"
)
_SAVE_REQUEST = re.compile(
    _REQUEST_PREFIX
    + rf"(?P<reference_zh>(?:[把将][^{_CLAUSE_END}]{{1,120}}?|{_TOPIC}))?\s*(?:(?:请|帮我|麻烦你?)\s*){{0,2}}"
    + rf"(?:(?P<storage>{_STORAGE_ACTION})|(?P<correction>{_CORRECTION_ACTION})|(?:{_REMEMBER_ACTION}))"
    + r"(?P<reference_en>\s+(?:it|this|that)(?:\s+(?:lesson|method|analysis|conclusion))?(?=\s*(?:$|[.!?;,\n])))?",
    re.IGNORECASE,
)
_DECLINE_STORAGE = re.compile(
    rf"{_NEGATION}\s*(?:[\uff0c,][^{_CLAUSE_END}]{{0,120}}[\uff0c,])?"
    rf"[^{_CLAUSE_END}]*(?:{_REMEMBER_ACTION}|{_STORAGE_ACTION}|{_CORRECTION_ACTION})",
    re.IGNORECASE,
)
_INDIRECT_REQUEST = re.compile(
    r"^\s*(?:如果|假如|假设|例如|比如|举例|示例|例子|[他她它]们?(?:说|让|要求)|"
    r"if\b|suppose\b|for example\b|(?:he|she|they)\s+(?:said|asked)\b)",
    re.IGNORECASE,
)
_FUTURE_USE = re.compile(
    r"\s*(?:如果(?:方便\s*[\uff0c,]\s*|(?=下次)))?(?:请\s*)?(?:下次|以后|今后)"
    rf"(?:[^{_CLAUSE_END}]{{0,60}}[\uff0c,]\s*)?(?:也|就|请|继续|仍然|\s){{0,10}}"
    r"(?:照|按|沿用|采用)(?:这个|这套|该|上述|同样的)(?:习惯|偏好|方法|做法|规则|流程)"
    r"|(?:if possible,\s*)?(?:please\s+)?(?:keep|use|apply|follow|reuse)\s+(?:this|that)"
    r"(?:\s+(?:preference|rule|method|approach|lesson|workflow))?\s+"
    r"(?:for\s+next\s+time|the\s+next\s+time\b|in\s+(?:future|later)\s+(?:sessions|tasks))",
    re.IGNORECASE,
)
_NEGATION_WORD = re.compile(_NEGATION, re.IGNORECASE)
_LITERAL_MEMORY_NAME = re.compile(_MEMORY_NAME, re.IGNORECASE)
# Object-first Chinese ("知识点整理到记忆里面") and memory-as-instrument
# ("通过记忆机制进行沉淀") put the action outside the request-prefix grammar.
_TAIL_STORAGE = re.compile(
    rf"(?:整理|归纳|汇总|梳理|沉淀|记录|保存)(?:到|进|入(?:到)?|至)\s*{_DESTINATION}"
    rf"|(?:通过|用|借助|靠)\s*{_MEMORY_NAME}\s*(?:机制|功能|系统)?\s*(?:来|去)?\s*(?:进行)?"
    rf"(?:沉淀|记录|保存|记下|留存)",
    re.IGNORECASE,
)
# A slash command occupies the same offsets as a request prefix would.
_COMMAND_PREFIX = re.compile(r"^[ \t]*/[A-Za-z][\w.-]*[ \t]+")
MAX_CONSENT_CHARS = 200
MAX_CONSENT_BATCH = 20
_QUOTED_TEXT = re.compile(
    r"(?ms:^[ \t]*\x60{3}.*?(?:^[ \t]*\x60{3}[ \t]*$|\Z)|^[ \t]*~~~.*?(?:^[ \t]*~~~[ \t]*$|\Z))|"
    r"(?m:^[ \t]*>[^\n]*)|\x60[^\x60\n]*\x60|\"[^\"\n]*\"|(?<!\w)'[^'\n]*'(?!\w)|“[^”]*”|"
    r"\u2018[^\u2019]*\u2019|「[^」]*」|『[^』]*』"
)


@dataclass(frozen=True, slots=True)
class SaveRequest:
    quote: str
    correction: bool = False
    refers_to_material: bool = False


@dataclass(frozen=True, slots=True)
class ConsentDecision:
    ok: bool
    reason: str = ""


def unquoted_text(text: str, *, keep_memory_names: bool = False) -> str:
    """Preserve offsets while masking quotes and pasted examples."""

    def mask(match: re.Match[str]) -> str:
        quoted = match[0]
        if keep_memory_names and quoted[0] in "\x60\"'“\u2018「『" and _LITERAL_MEMORY_NAME.fullmatch(quoted[1:-1]):
            return " " + quoted[1:-1] + " "
        return " " * len(quoted)

    return _QUOTED_TEXT.sub(mask, text)


def user_quote_occurs(text: str, unquoted: str, quote: str) -> bool:
    """Allow quoted terms inside the user's own evidence, preserving provenance."""
    offset = text.find(quote) if quote else -1
    while offset >= 0:
        if any(character.isalnum() for character in unquoted[offset : offset + len(quote)]):
            return True
        offset = text.find(quote, offset + len(quote))
    return False


def declines_memory(text: str) -> bool:
    return _DECLINE_STORAGE.search(unquoted_text(text, keep_memory_names=True)) is not None


def _quoted_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Ranges that hold pasted material; a quoted memory name stays the user's own words."""

    kept = unquoted_text(text, keep_memory_names=True)
    full = unquoted_text(text)
    return tuple(
        (match.start(), match.end())
        for match in _QUOTED_TEXT.finditer(text)
        if kept[match.start() : match.end()] == full[match.start() : match.end()]
    )


def validate_consent(message: str, span: str, *, batch_size: int = 1) -> ConsentDecision:
    """Check a write's authorization span without reading what it means.

    Positions, lengths and counts decide; the words do not. That keeps the
    guarantees identical for every language: the span must appear in the message
    outside pasted examples, stay short enough to be a request, and cover at most
    a bounded batch.
    """

    span = span.strip()
    if not span:
        return ConsentDecision(False, "consent_span_missing")
    if len(span) > MAX_CONSENT_CHARS:
        return ConsentDecision(False, "consent_span_too_long")
    if batch_size > MAX_CONSENT_BATCH:
        return ConsentDecision(False, "consent_batch_too_large")
    quoted = _quoted_ranges(message)
    offset = message.find(span)
    pasted_only = False
    while offset >= 0:
        end = offset + len(span)
        if not any(start < end and offset < stop for start, stop in quoted):
            return ConsentDecision(True)
        pasted_only = True
        offset = message.find(span, end)
    return ConsentDecision(False, "consent_span_pasted" if pasted_only else "consent_span_missing")


def save_request(text: str, intent_quote: str = "") -> SaveRequest | None:
    """Find a retention target or a grounded direction to reuse a method later."""
    visible = unquoted_text(text, keep_memory_names=True)
    visible = _COMMAND_PREFIX.sub(lambda match: " " * len(match.group()), visible)
    for match in _SAVE_REQUEST.finditer(visible):
        prefix = _SENTENCE_END.split(visible[: match.start()])[-1]
        if _INDIRECT_REQUEST.match(prefix):
            continue
        reference = match["reference_zh"] or match["reference_en"]
        # A directed write without an inline statement still adopts earlier material.
        has_inline_statement = visible[match.end() :].lstrip().startswith((":", "\uff1a"))
        return SaveRequest(
            quote=text[match.start() : match.end()].strip(),
            correction=bool(match["correction"]),
            refers_to_material=bool(reference or (match["storage"] and not has_inline_statement)),
        )

    tail = _TAIL_STORAGE.search(visible)
    if tail is not None:
        prefix = _SENTENCE_END.split(visible[: tail.start()])[-1]
        if not _INDIRECT_REQUEST.match(prefix):
            return SaveRequest(quote=text[tail.start() : tail.end()].strip(), refers_to_material=True)

    quote = intent_quote.strip()
    offset = visible.find(quote) if quote else -1
    reuse = _FUTURE_USE.match(quote)
    if offset < 0 or reuse is None or _NEGATION_WORD.search(reuse[0]):
        return None
    if _INDIRECT_REQUEST.match(_SENTENCE_END.split(visible[:offset])[-1]):
        return None
    return SaveRequest(quote, refers_to_material=True)
