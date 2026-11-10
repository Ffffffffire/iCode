# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Bounded, derived indexes for curated personal memory.

One index serves all workspaces. Only changed searchable records are tokenized;
scope views and query results are disposable. Literal and equivalent terms share
one BM25F score: recognizing the same evidence twice must not promote it twice.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from heapq import nsmallest
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
    words = [word for word in _WORDS.findall(text) if len(word) > 1 and word not in _STOP]
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
    cache: OrderedDict[tuple[str, str, bool, bool], tuple[MemoryMatch, ...]]


class _Index:
    def __init__(self) -> None:
        self.documents: dict[str, _Document] = {}
        self.postings: dict[str, set[str]] = {}
        self.anchors: dict[str, set[str]] = {}
        self.identities: dict[str, set[str]] = {}
        self.titles: dict[str, set[str]] = {}
        self.spellings: dict[str, set[str]] = {}
        self.views: OrderedDict[tuple[str | None, frozenset[str] | None], _View] = OrderedDict()

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
    ) -> tuple[MemoryMatch, ...]:
        view = self.view(workspace, eligible_ids)
        identifiers = _identifier_terms(query)
        key = (_normalize(query), identifiers, automatic, continued)
        if limit == _MAX_CANDIDATES and key in view.cache:
            view.cache.move_to_end(key)
            return view.cache[key]
        tokens = set(_tokens(query))
        query = key[0]
        lexical_query = query + " " + identifiers
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
        ranked: list[tuple[tuple[bool, bool, float, bool, str], MemoryMatch]] = []
        for mid in candidates:
            doc = self.documents[mid]
            anchored = searched & doc.anchors
            body = searched & doc.fields[2].keys()
            formats = doc.fields[1].keys() & {"@slides", "@web"}
            requested_formats = searched & {"@slides", "@web"}
            if automatic and mid not in direct and formats and requested_formats and not formats & requested_formats:
                continue
            relevant_anchors = anchored - _BACKGROUND_TERMS if automatic else anchored
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
            ranked.append(
                (
                    (mid not in direct, mid not in phrases, -score, not bool(doc.draft.workspace), mid),
                    MemoryMatch(mid, doc.revision, terms, tuple(routes)),
                )
            )
        floor = max((-rank[2] for rank, _ in ranked), default=0.0) * _AUTOMATIC_SCORE_FRACTION
        admitted = (
            (rank, match) for rank, match in ranked if not automatic or not rank[0] or not rank[1] or -rank[2] >= floor
        )
        result = tuple(match for _, match in nsmallest(limit, admitted, key=lambda pair: pair[0]))
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
    ) -> tuple[MemoryMatch, ...]:
        continued = bool(context and continues_previous_task(query))
        query = context if continued else query
        # Long pasted task input often ends with the actual request. Keep both
        # ends within the same bounded tokenizer budget instead of losing it.
        query = query if len(query) <= 4000 else query[:2000] + "\n" + query[-1999:]
        with self._lock:
            self._index.synchronize(entries)
            return self._index.search(
                query, workspace, automatic=automatic, continued=continued, eligible_ids=eligible_ids
            )

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
