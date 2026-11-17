# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Bounded, derived indexes for curated personal memory.

One index serves all workspaces. Only changed searchable records are tokenized;
scope views and query results are disposable. Literal and equivalent terms share
one BM25F score: recognizing the same evidence twice must not promote it twice.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import lru_cache
from heapq import nsmallest
from itertools import zip_longest
from threading import RLock

from chrys.foundation.models.personal_memory import MemoryDraft, MemoryMatch, PersonalMemory

_STOP = frozenset(
    [
        "the",
        "to",
        "of",
        "it",
        "as",
        "is",
        "be",
        "on",
        "in",
        "at",
        "an",
        "or",
        "not",
        "by",
        "we",
        "do",
        "so",
        "if",
        "but",
        "this",
        "that",
        "with",
        "from",
        "have",
        "what",
        "when",
        "where",
        "how",
        "please",
        "help",
        "want",
        "need",
        "memory",
        "using",
        "use",
        "into",
        "and",
        "for",
        "you",
        "your",
        "are",
        "can",
        "should",
        "about",
        "would",
        "could",
        "prefer",
        "preference",
        "preferences",
        "user",
        "users",
        "effect",
        "effects",
        "some",
        "more",
        "make",
        "making",
        "create",
        "creating",
        "prepare",
        "preparing",
        "writing",
        "write",
        "before",
        "after",
        "during",
        "running",
        "run",
        "implement",
        "implementing",
        "debug",
        "debugging",
        "用户",
        "效果",
        "记忆",
        "系统",
        "是否",
        "如何",
        "什么",
        "这个",
        "那个",
        "这些",
        "那些",
        "当前",
        "可以",
        "需要",
        "进行",
        "内容",
        "信息",
        "使用",
        "方式",
        "偏好",
        "喜欢",
        "我们",
        "自己",
        "一个",
        "一些",
        "有些",
        "比较",
        "没有",
        "以及",
        "对于",
        "时候",
        "还有",
        "可能",
        "问题",
        "技术",
        "方案",
        "实现",
        "设计",
        "目标",
        "建议",
        "制作",
        "准备",
        "生成",
    ]
)
_CHINESE_STOP = re.compile("|".join(sorted((word for word in _STOP if not word.isascii()), key=len, reverse=True)))
# Platform vocabulary is useful for deliberate browsing, but cannot by itself
# distinguish authoring a Skill from researching an Agent Harness.
_BACKGROUND_TERMS = frozenset({"agent", "agents", "智能", "能体"})
_EDGE = frozenset("的了也就与或把被吗呢吧")
_WORDS = re.compile(r"\.net\b|[a-z0-9][a-z0-9_.-]*(?:\+\+|#)?", re.IGNORECASE)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_FILE_EXTENSIONS = frozenset({"py", "pyi", "md", "ts", "tsx", "js", "jsx", "rs", "go", "java", "json", "yaml", "yml"})
_IDENTIFIER_CUE = re.compile(r"_|[a-z0-9][A-Z]|[A-Z][A-Z][a-z]|\.(?i:" + "|".join(sorted(_FILE_EXTENSIONS)) + r")\b")
# Equivalences, not broad subject membership: rebase is not diff, statistical
# regression is not testing, and writing code is not a prose-format constraint.
_ALIASES = {
    "slides": ("ppt", "pptx", "powerpoint", "slide", "slides", "slide deck", "幻灯片", "演示文稿"),
    "diagrams": ("diagram", "diagrams", "绘图", "画图"),
    "cache": ("cache", "caches", "caching", "缓存"),
    "reports": ("report", "reports", "报告", "报表"),
    "testing": ("test", "tests", "testing", "测试"),
    "rebase": ("git rebase", "rebase", "rebasing", "变基"),
    "observability": ("observability", "可观测性"),
    "web": ("webpage", "website", "html", "网页", "网站"),
}
_ALIAS_TERMS = {alias: "@" + concept for concept, aliases in _ALIASES.items() for alias in aliases}
# Product names are not generic coding cues; aliases retain their established
# meaning when embedded as a filename component (for example PowerPoint.md).
_PROTECTED_WORDS = frozenset({".net", "icode", *_ALIAS_TERMS})
_ALIAS_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(
        re.escape(alias) for alias in sorted(_ALIAS_TERMS, key=lambda value: (-len(value), value)) if alias.isascii()
    )
    + r")(?![a-z0-9])|"
    + "|".join(
        re.escape(alias)
        for alias in sorted(_ALIAS_TERMS, key=lambda value: (-len(value), value))
        if not alias.isascii()
    )
)
_CONTINUATION = re.compile(
    r"(?:继续(?:吧|做|完善|写下一节|写下一章|做下一页|下一步)?|接着(?:做|写下一节)?|按这个来|照这个来|再详细一点|按这个风格继续(?:做下一页)?|"
    r"continue(?: with the next (?:section|chapter|step))?|go on|keep going|more detail)[。.!\uFF01\s]*",
    re.IGNORECASE,
)
_DECISION_BOUNDARY = re.compile(
    r"\s+\b(?:and|then)\s+(?=(?:check|verify|confirm|review|compare|validate|prepare|create|update|test)\b)"
    r"|[\uff0c、\s]*(?:再|并且|同时)(?=\s*(?:核对|检查|验证|确认|审查|对比|制作|生成|修改))",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY = re.compile(
    r"[。\uff01\uff1f\uff1b;]+|(?<=[.!?])\s+"
    r"|[,\uff0c]\s*(?=(?:(?:先|再|只|仅)\s*)?(?:核对|检查|验证|统计|计数|制作|生成|修改))"
)
_REFERENCED_TEXT = re.compile(r"(?ms:^[ \t]*(\x60{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[ \t]*$|\Z))|(?m:^[ \t]*>[^\n]*)")
_NON_CREATION = re.compile(
    r"^\s*(?:请\s*)?(?:(?:不要|无需|不必|别)\s*(?:做|制作|生成|创建|编写)"
    r"|(?:只|仅)(?:需|需要)?\s*(?:统计|计数|转述|引用)"
    r"|(?:please\s+)?(?:(?:do not|don't|no need to)\s+(?:make|create|prepare|write|generate)"
    r"|(?:only|just)\s+(?:count|quote|cite|transcribe))\b)",
    re.IGNORECASE,
)
_ARTIFACT_FORMATS = frozenset({"@slides", "@web"})
MAX_RECALL_ALTERNATIVES = 2
MAX_ALTERNATIVE_CHARS = 320
_FIELD_WEIGHTS = (4.0, 3.0, 1.0)
# Admission policy, not a confidence estimate. Automatic injection drops weak
# lexical tails; an explicit tool search retains them for deliberate inspection.
_AUTOMATIC_SCORE_FRACTION = 0.5
_MAX_VIEWS = 4
_MAX_QUERIES = 64
# A bounded shortlist feeds the five-entry prompt packer. Library browsing does
# not use this shortlist. Cache retention is at most 4 * 64 * 32 matches.
_MAX_CANDIDATES = 32


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def continues_previous_task(query: str) -> bool:
    return bool(_CONTINUATION.fullmatch(query.strip()))


def _literal_tokens(text: str) -> list[str]:
    words = [word for raw in _WORDS.findall(text) if len(word := raw.rstrip(".")) > 1 and word not in _STOP]
    if text.isascii():
        return words
    # Remove whole stop phrases before bigrams, so 制作技术 cannot leave 作技.
    for run in re.findall(r"[\u3400-\u9fff]+", _CHINESE_STOP.sub(" ", text)):
        words.extend(
            word
            for index in range(len(run) - 1)
            if (word := run[index : index + 2])[0] not in _EDGE and word[-1] not in _EDGE
        )
    return words


def _tokens(text: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for segment in (_normalize(text), _identifier_terms(text)):
        terms: Counter[str] = Counter()
        position = 0
        for match in _ALIAS_PATTERN.finditer(segment):
            terms.update(_literal_tokens(segment[position : match.start()]))
            terms[_ALIAS_TERMS[match[0]]] += 1
            position = match.end()
        terms.update(_literal_tokens(segment[position:]))
        # Original identifiers and their parts are two readings of the same
        # evidence. Preserve literal lookup without counting aliases twice.
        result |= terms
    return result


def _task_decisions(query: str) -> tuple[str, ...]:
    """Split explicit coordinated requests while keeping ordinary prose together."""
    query = _REFERENCED_TEXT.sub(" ", query)
    clauses = _SENTENCE_BOUNDARY.split(query)
    if any(_NON_CREATION.match(clause) for clause in clauses):
        query = " ".join(clause for clause in clauses if not _NON_CREATION.match(clause))
    return tuple(part.strip() for part in _DECISION_BOUNDARY.split(query, maxsplit=2) if part.strip())


def linked_to_decision(draft: MemoryDraft, terms: frozenset[str], *, needs_corroboration: bool) -> bool:
    """Respect specific formats even when an explicit forward link supplies the relationship."""
    condition = _tokens(draft.when_to_use).keys()
    formats = condition & _ARTIFACT_FORMATS
    if formats and not formats & terms:
        return False
    return not needs_corroboration or bool(terms & (condition | _tokens(draft.title).keys()))


def _query_window(query: str) -> str:
    # Pasted task input can end with the actual request.
    return query if len(query) <= 4000 else query[:2000] + "\n" + query[-1999:]


def decision_terms(query: str, *, automatic: bool) -> frozenset[str]:
    query = _query_window(query)
    decisions = _task_decisions(query) if automatic else (query,)
    return frozenset(term for decision in decisions for term in _tokens(decision)) - _BACKGROUND_TERMS


def _round_robin(lists: tuple[tuple[MemoryMatch, ...], ...]) -> Iterator[MemoryMatch]:
    for row in zip_longest(*lists):
        yield from (item for item in row if item is not None)


def _fuse_reformulations(lists: tuple[tuple[MemoryMatch, ...], ...]) -> tuple[MemoryMatch, ...]:
    """Fuse multiple descriptions of one decision. Exact lookups keep priority."""
    matches: dict[str, MemoryMatch] = {}
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, match in enumerate(ranked, 1):
            scores[match.memory_id] = scores.get(match.memory_id, 0.0) + 1 / (60 + rank)
            old = matches.get(match.memory_id)
            if old is None:
                matches[match.memory_id] = match
            else:
                matches[match.memory_id] = replace(
                    old,
                    terms=tuple(dict.fromkeys((*old.terms, *match.terms)))[:8],
                    routes=tuple(dict.fromkeys((*old.routes, *match.routes))),
                )
    return tuple(
        sorted(
            matches.values(),
            key=lambda match: ("identity" not in match.routes, "title" not in match.routes, -scores[match.memory_id]),
        )
    )


def _identifier_terms(text: str) -> str:
    """Extract code word boundaries before normalization, preserving protected names."""
    text = unicodedata.normalize("NFKC", text)
    # Most indexed fields are ordinary prose. Avoid parsing every word again
    # unless a code boundary or recognized file extension is present.
    if not _IDENTIFIER_CUE.search(text):
        return ""
    parts: list[str] = []
    for word in _WORDS.findall(text):
        if word.casefold() in _PROTECTED_WORDS or word.endswith(("++", "#")):
            continue
        stem, dot, extension = word.rpartition(".")
        filename = bool(dot and extension.casefold() in _FILE_EXTENSIONS)
        identifier = stem if filename else word
        if not filename and "-" in identifier:
            continue
        # Hyphens in product/model names carry meaning; split them only in a
        # recognized filename. Camel boundaries must precede case folding.
        components = (identifier.replace("-", "_") if filename else identifier).split("_")
        split = " ".join(
            component if component.casefold() in _PROTECTED_WORDS else _CAMEL_BOUNDARY.sub(" ", component)
            for component in components
        )
        if filename or split != word:
            parts.append(split)
    return _normalize(" ".join(parts))


def decision_key(query: str, workspace: str = "") -> str:
    """Identify canonical cues without storing the query or tool arguments."""
    # Long prompts still need faithful identity, but must not occupy cache
    # slots with unbounded text. Only the digest is persisted.
    return _hash_decision(query, workspace) if len(query) > 4000 else _decision_key(query, workspace)


@lru_cache(maxsize=256)
def _decision_key(query: str, workspace: str) -> str:
    return _hash_decision(query, workspace)


def _hash_decision(query: str, workspace: str) -> str:
    # Retrieval can ignore stop words; durable context equality cannot ignore
    # negation or word order. Only typography and whitespace are normalized.
    cues = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
    return hashlib.sha256((workspace + "\n" + cues).encode()).hexdigest()[:24] if cues else ""


def _one_edit(left: str, right: str) -> bool:
    if len(left) == len(right):
        different = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        return len(different) == 1 or (
            len(different) == 2
            and different[1] == different[0] + 1
            and left[different[0]] == right[different[1]]
            and left[different[1]] == right[different[0]]
        )
    shorter, longer = sorted((left, right), key=len)
    return len(longer) == len(shorter) + 1 and any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


def _spellings(term: str) -> tuple[str, ...]:
    words = _ALIASES[term[1:]] if term.startswith("@") else (term,)
    return tuple(word for word in words if word.isascii() and word.isalpha() and 6 <= len(word) <= 48)


def _deletions(word: str) -> set[str]:
    return {word, *(word[:i] + word[i + 1 :] for i in range(len(word)))}


def _posting(table: dict[str, set[str]], key: str, value: str, *, add: bool) -> None:
    if add:
        table.setdefault(key, set()).add(value)
    else:
        table[key].remove(value)
        if not table[key]:
            del table[key]


@dataclass(frozen=True, slots=True)
class _Document:
    revision: int
    draft: MemoryDraft
    title: str
    fields: tuple[Counter[str], ...]
    lengths: tuple[int, ...]
    anchors: frozenset[str]

    @classmethod
    def build(cls, entry: PersonalMemory) -> _Document:
        draft = entry.draft
        fields = tuple(
            _tokens(text)
            for text in (draft.title, " ".join((draft.when_to_use, *draft.topics, *draft.aliases)), draft.content)
        )
        return cls(
            entry.revision,
            draft,
            _normalize(draft.title),
            fields,
            tuple(sum(field.values()) for field in fields),
            frozenset(fields[0].keys() | fields[1].keys()),
        )


@dataclass(slots=True)
class _View:
    ids: frozenset[str]
    averages: tuple[float, ...]
    cache: OrderedDict[tuple[str, str, bool, bool, frozenset[str] | None], tuple[MemoryMatch, ...]]


class _Index:
    def __init__(self) -> None:
        self.documents: dict[str, _Document] = {}
        self.postings: dict[str, set[str]] = {}
        self.anchors: dict[str, set[str]] = {}
        self.identities: dict[str, set[str]] = {}
        self.titles: dict[str, set[str]] = {}
        self.spellings: dict[str, set[str]] = {}
        self.views: OrderedDict[tuple[str | None, frozenset[str] | None], _View] = OrderedDict()
        self._indexed: tuple[PersonalMemory, ...] | None = None
        self._include_inactive = False

    def _terms_changed(self, memory_id: str, doc: _Document, *, add: bool) -> None:
        for term in set().union(*doc.fields):
            _posting(self.postings, term, memory_id, add=add)
        for term in doc.anchors:
            first = term not in self.anchors
            _posting(self.anchors, term, memory_id, add=add)
            if first or term not in self.anchors:
                for key in set().union(*(_deletions(word) for word in _spellings(term))):
                    _posting(self.spellings, key, term, add=add)
        _posting(self.titles, doc.title, memory_id, add=add)
        for length in range(8, len(memory_id) + 1):
            _posting(self.identities, memory_id[:length], memory_id, add=add)

    def synchronize(self, entries: tuple[PersonalMemory, ...], *, include_inactive: bool = False) -> None:
        if self._indexed is entries and self._include_inactive == include_inactive:
            return
        active = {entry.id: entry for entry in entries if include_inactive or entry.state == "active"}
        changed = False
        for memory_id in self.documents.keys() - active.keys():
            self._terms_changed(memory_id, self.documents.pop(memory_id), add=False)
            changed = True
        for memory_id, entry in active.items():
            old = self.documents.get(memory_id)
            if old is not None and old.draft == entry.draft:
                if old.revision != entry.revision:
                    self.documents[memory_id] = replace(old, revision=entry.revision)
                    changed = True
                continue
            doc = _Document.build(entry)
            if old is not None:
                self._terms_changed(memory_id, old, add=False)
            self.documents[memory_id] = doc
            self._terms_changed(memory_id, doc, add=True)
            changed = True
        if changed:
            self.views.clear()
        self._indexed = entries
        self._include_inactive = include_inactive

    def view(self, workspace: str | None, eligible_ids: frozenset[str] | None) -> _View:
        key = (workspace, eligible_ids)
        view = self.views.get(key)
        if view is None:
            ids = frozenset(
                mid
                for mid, doc in self.documents.items()
                if (workspace is None or not doc.draft.workspace or doc.draft.workspace == workspace)
                and (eligible_ids is None or mid in eligible_ids)
            )
            view = _View(
                ids,
                tuple(sum(self.documents[mid].lengths[i] for mid in ids) / max(1, len(ids)) for i in range(3)),
                OrderedDict(),
            )
            self.views[key] = view
            if len(self.views) > _MAX_VIEWS:
                self.views.popitem(last=False)
        self.views.move_to_end(key)
        return view

    def search(
        self,
        query: str,
        workspace: str | None,
        *,
        automatic: bool,
        continued: bool,
        limit: int = _MAX_CANDIDATES,
        eligible_ids: frozenset[str] | None = None,
        exact_action_terms: frozenset[str] | None = None,
    ) -> tuple[MemoryMatch, ...]:
        view = self.view(workspace, eligible_ids)
        identifiers = _identifier_terms(query)
        key = (_normalize(query), identifiers, automatic, continued, exact_action_terms)
        if limit == _MAX_CANDIDATES and key in view.cache:
            view.cache.move_to_end(key)
            return view.cache[key]
        tokens = set(_tokens(query))
        query = key[0]
        lexical_query = query + " " + identifiers
        identifier_parts = set(_tokens(identifiers)) if identifiers and _WORDS.fullmatch(query) else set()
        literal_identifier = tokens - identifier_parts
        aliases = {_ALIAS_TERMS[match[0]]: match[0] for match in _ALIAS_PATTERN.finditer(lexical_query)}
        direct: set[str] = set()
        for identity in re.findall(r"(?<![a-z0-9])[a-f0-9]{8,16}(?![a-z0-9])", query):
            # Automatic recall must not interpret a commit hash in a task as a
            # deliberate memory lookup. Explicit tool queries keep prefix lookup.
            if (
                automatic
                and query != identity
                and not re.search(rf"(?:\bmemory\b|记忆)\s*[:\uFF1A#]?\s*{identity}\b", query)
            ):
                continue
            found = self.identities.get(identity, set()) & view.ids
            if len(found) == 1:
                direct.update(found)
        # A short title appearing somewhere in a long query is lexical evidence,
        # not an exact lookup. Otherwise "Cache" outranks "Cache invalidation".
        titles = {query, *re.findall(r'["“《]([^"”》]+)["”》]', query)}
        phrases = set().union(*(self.titles.get(title, set()) for title in titles)) & view.ids
        corrected: dict[str, str] = {}
        for token in sorted(tokens):
            if self.postings.get(token, set()) & view.ids or not _spellings(token):
                continue
            nearby = set().union(*(self.spellings.get(key, set()) for key in _deletions(token)))
            nearby = {
                term
                for term in nearby
                if self.anchors[term] & view.ids and any(_one_edit(token, word) for word in _spellings(term))
            }
            if len(nearby) == 1:
                corrected[next(iter(nearby))] = token
        searched = tokens | corrected.keys()
        postings = {term: self.postings.get(term, set()) & view.ids for term in searched}
        candidates = direct | phrases | set().union(*postings.values())
        idf = {term: math.log1p((len(view.ids) - len(ids) + 0.5) / (len(ids) + 0.5)) for term, ids in postings.items()}
        requested_formats = searched & _ARTIFACT_FORMATS
        ranked: list[tuple[bool, bool, float, bool, str]] = []
        for mid in candidates:
            doc = self.documents[mid]
            anchored = searched & doc.anchors
            body = searched & doc.fields[2].keys()
            # Finding "policy" alone is insufficient when the whole lookup is RetryPolicy.
            if (
                len(identifier_parts) > 1
                and mid not in direct
                and mid not in phrases
                and not literal_identifier & anchored
                and len(identifier_parts & (anchored | body)) < 2
            ):
                continue
            formats = doc.fields[1].keys() & _ARTIFACT_FORMATS
            if automatic and mid not in direct and formats and requested_formats and not formats & requested_formats:
                continue
            relevant_anchors = anchored - _BACKGROUND_TERMS if automatic else anchored
            if exact_action_terms is not None:
                # An action needs literal support from its target.
                action_anchors = relevant_anchors & tokens
                if (formats and not formats & exact_action_terms) or (
                    len(action_anchors) < 2 and not action_anchors & exact_action_terms
                ):
                    continue
            if mid not in direct and mid not in phrases and not relevant_anchors and (automatic or len(body) < 2):
                continue
            matched = anchored | body
            score = 0.0
            for term in sorted(matched):
                frequency = sum(
                    weight * field[term] / (0.25 + 0.75 * doc.lengths[i] / max(1, view.averages[i]))
                    for i, (field, weight) in enumerate(zip(doc.fields, _FIELD_WEIGHTS, strict=True))
                )
                score += idf[term] * 2.2 * frequency / (1.2 + frequency)
            ranked.append((mid not in direct, mid not in phrases, -score, not bool(doc.draft.workspace), mid))
        floor = max((-rank[2] for rank in ranked), default=0.0) * _AUTOMATIC_SCORE_FRACTION
        admitted = (rank for rank in ranked if not automatic or not rank[0] or not rank[1] or -rank[2] >= floor)
        matches: list[MemoryMatch] = []
        # Many broad queries rank thousands of candidates. Only the shortlist
        # needs display terms and explanations.
        for _, _, _, _, mid in nsmallest(limit, admitted):
            doc = self.documents[mid]
            matched = searched & (doc.anchors | doc.fields[2].keys())
            routes = []
            if mid in direct:
                routes.append("identity")
            if mid in phrases:
                routes.append("title")
            if any(not term.startswith("@") for term in matched & tokens):
                routes.append("keywords")
            if matched & aliases.keys():
                routes.append("topic")
            if matched & corrected.keys():
                routes.append("spelling")
            if any(_normalize(alias) in query for alias in doc.draft.aliases):
                routes.append("alias")
            if continued:
                routes.append("context")
            terms = tuple(
                f"{corrected[term]} → {term.lstrip('@')}" if term in corrected else aliases.get(term, term)
                for term in sorted(matched, key=lambda term: (-idf[term], term))
            )[:8]
            matches.append(MemoryMatch(mid, doc.revision, terms, tuple(routes)))
        result = tuple(matches)
        if limit != _MAX_CANDIDATES:
            return result
        view.cache[key] = result
        if len(view.cache) > _MAX_QUERIES:
            view.cache.popitem(last=False)
        return result


class MemoryRetriever:
    """A store-owned, thread-safe, disposable index; nothing is written to disk."""

    def __init__(self) -> None:
        self._index = _Index()
        self._lock = RLock()

    def search(
        self,
        entries: tuple[PersonalMemory, ...],
        query: str,
        workspace: str,
        *,
        automatic: bool,
        context: str = "",
        eligible_ids: frozenset[str] | None = None,
        alternatives: tuple[str, ...] = (),
        action_targets: tuple[str, ...] | None = None,
    ) -> tuple[MemoryMatch, ...]:
        continued = bool(context and continues_previous_task(query))
        query = context if continued else query
        query = _query_window(query)
        exact_action_terms = None
        if action_targets is not None:
            exact_action_terms = frozenset(
                term
                for target in action_targets
                if len(terms := _tokens(target)) == 1
                for term in terms
                if not term.startswith("@") or (target.startswith("@") and term in _ARTIFACT_FORMATS)
            )
        with self._lock:
            self._index.synchronize(entries)
            queries = _task_decisions(query) if automatic and action_targets is None else (query,)
            # Alternate wording belongs to one deliberate lookup. Equivalent
            # term sets contribute a single ranking to the fusion.
            if alternatives and not automatic:
                by_terms = {frozenset(_tokens(query)): query}
                for alternative in alternatives[:MAX_RECALL_ALTERNATIVES]:
                    alternate = alternative.strip()[:MAX_ALTERNATIVE_CHARS]
                    if alternate:
                        by_terms.setdefault(frozenset(_tokens(alternate)), alternate)
                queries = tuple(by_terms.values())
            lists = tuple(
                self._index.search(
                    decision,
                    workspace,
                    automatic=automatic,
                    continued=continued,
                    eligible_ids=eligible_ids,
                    exact_action_terms=exact_action_terms,
                )
                for decision in queries
            )
            if len(lists) <= 1:
                return lists[0] if lists else ()
            if alternatives and not automatic:
                return _fuse_reformulations(lists)[:_MAX_CANDIDATES]
            unique: dict[str, MemoryMatch] = {}
            for match in _round_robin(lists):
                unique.setdefault(match.memory_id, match)
            return tuple(unique.values())[:_MAX_CANDIDATES]

    def browse(self, entries: tuple[PersonalMemory, ...], query: str) -> tuple[MemoryMatch, ...]:
        """Library-only search: all supplied states/scopes, without recall limits or side effects."""
        with self._lock:
            self._index.synchronize(entries, include_inactive=True)
            return self._index.search(query[:4000], None, automatic=False, continued=False, limit=len(entries))

    def near_duplicates(self, entries: tuple[PersonalMemory, ...], draft: MemoryDraft) -> tuple[PersonalMemory, ...]:
        candidates = self.search(
            tuple(replace(e, state="active") for e in entries),
            draft.title + " " + draft.content + " " + draft.when_to_use,
            draft.workspace,
            automatic=False,
        )
        ids = {m.memory_id for m in candidates}
        content = _normalize(draft.content)
        return tuple(
            e
            for e in entries
            if e.id in ids
            and e.draft.workspace == draft.workspace
            and e.draft.kind == draft.kind
            and _normalize(e.draft.when_to_use) == _normalize(draft.when_to_use)
            and len(content) >= 24
            and SequenceMatcher(None, content, _normalize(e.draft.content), autojunk=False).ratio() >= 0.92
        )
