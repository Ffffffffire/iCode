# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Summarize what the memory tools did, from trajectory rows.

Every memory tool call records one ``memory.*`` event (see
``chrys.foundation.trajectory.event_types``): committed saves, rejected saves with
their code, served recalls with entry and character counts, and consent outcomes.
Nothing else carries those facts, so this script reads them back per session.

Usage::

    uv run python scripts/memory_traffic_report.py                    # every session
    uv run python scripts/memory_traffic_report.py --session <id>     # one session
    uv run python scripts/memory_traffic_report.py --json             # machine-readable

The propose failure rate is ``rejected / (rejected + committed)``: both sides are
propose calls that reached the store, so the ratio answers "how often does a write
attempt get refused". A rejection with code ``memory_consent_invalid`` is a
near-miss worth reading on its own, and a high share of ``recall_served`` rows per
committed save means the agent is inspecting the library often between writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONSENT_CONFIRMED = "confirmed"
CONSENT_DECLINED = "declined"


@dataclass
class TrafficReport:
    """What one or more sessions did with the memory tools."""

    sessions: int = 0
    events: int = 0
    committed: int = 0
    rejected: int = 0
    rejections: dict[str, int] = field(default_factory=dict)
    recalls: int = 0
    recalled_entries: int = 0
    recalled_characters: int = 0
    views: dict[str, int] = field(default_factory=dict)
    consent_confirmed: int = 0
    consent_declined: int = 0
    consent_asked: int = 0
    unchanged: int = 0

    @property
    def propose_attempts(self) -> int:
        return self.committed + self.rejected

    @property
    def failure_rate(self) -> float:
        """Share of write attempts that were refused; 0.0 when nothing was attempted."""
        return self.rejected / self.propose_attempts if self.propose_attempts else 0.0

    @property
    def recalls_per_commit(self) -> float:
        """How many library inspections each committed save took, as a ratio."""
        return self.recalls / self.committed if self.committed else 0.0


def summarize(sessions: Iterable[Iterable[Mapping[str, Any]]]) -> TrafficReport:
    """Aggregate memory events from one envelope iterable per session."""
    report = TrafficReport()
    for events in sessions:
        report.sessions += 1
        for event in events:
            event_type = str(event.get("event_type", ""))
            if not event_type.startswith("memory."):
                continue
            report.events += 1
            payload = event.get("payload") or {}
            if event_type == "memory.save.committed":
                report.committed += 1
                if payload.get("outcome") == "unchanged":
                    report.unchanged += 1
            elif event_type == "memory.save.rejected":
                report.rejected += 1
                code = str(payload.get("code") or "unknown")
                report.rejections[code] = report.rejections.get(code, 0) + 1
            elif event_type == "memory.recall.served":
                report.recalls += 1
                report.recalled_entries += _int(payload.get("entries"))
                report.recalled_characters += _int(payload.get("characters"))
                view = str(payload.get("view") or "unknown")
                report.views[view] = report.views.get(view, 0) + 1
            elif event_type == "memory.consent.asked":
                report.consent_asked += 1
            elif event_type == "memory.consent.resolved":
                if payload.get("outcome") == CONSENT_DECLINED:
                    report.consent_declined += 1
                else:
                    report.consent_confirmed += 1
    return report


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def session_events(session_dir: Path) -> Iterator[Mapping[str, Any]]:
    """Yield the parsed trajectory rows of one session, skipping a torn tail line."""
    path = session_dir / "trajectory" / "events.jsonl"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def session_dirs(root: Path, session_id: str = "") -> list[Path]:
    """Session directories under *root*, or just the named one."""
    if session_id:
        named = root / session_id
        return [named] if named.is_dir() else []
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))


def render(report: TrafficReport) -> str:
    """A short text report, ordered from the decision to the detail."""
    lines = [
        f"sessions: {report.sessions}   memory events: {report.events}",
        (
            f"writes: {report.committed} committed ({report.unchanged} unchanged), {report.rejected} rejected"
            f"   failure rate: {report.failure_rate:.1%}"
        ),
    ]
    if report.rejections:
        lines.append("rejection codes:")
        for code, count in sorted(report.rejections.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"  {count:5d}  {code}")
    average = report.recalled_characters // report.recalls if report.recalls else 0
    lines.append(
        f"recalls: {report.recalls} ({report.recalls_per_commit:.2f} per committed save)"
        f"   entries: {report.recalled_entries}   characters: {report.recalled_characters}"
        f"   average: {average}"
    )
    if report.views:
        views = ", ".join(f"{view}={count}" for view, count in sorted(report.views.items()))
        lines.append(f"recall views: {views}")
    lines.append(
        f"consent: asked {report.consent_asked}, confirmed {report.consent_confirmed},"
        f" declined {report.consent_declined}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize memory tool traffic from trajectory rows.")
    parser.add_argument("--session", default="", help="one session id instead of every session")
    parser.add_argument("--root", default="", help="sessions root (defaults to the configured one)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    sessions_root = Path(args.root) if args.root else _default_root()
    directories = session_dirs(sessions_root, args.session)
    if not directories:
        print(f"No sessions under {sessions_root}", file=sys.stderr)
        return 1
    report = summarize(session_events(directory) for directory in directories)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2) if args.json else render(report))
    return 0


def _default_root() -> Path:
    from chrys.foundation.config.settings import resolve_sessions_dir

    return resolve_sessions_dir()


if __name__ == "__main__":
    raise SystemExit(main())
