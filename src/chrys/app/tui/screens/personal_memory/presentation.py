# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Consistent local-time labels for memory details, history and list rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from chrys.foundation.i18n import MessageDef, MessageRef
from chrys.foundation.i18n.formatting import sanitize_legacy_scalar

from . import messages as m


def format_memory_time(
    value: str, render: Callable[[MessageDef | MessageRef], str], *, now: datetime | None = None
) -> str:
    """Recent past is relative; future reminders and older records keep their local date."""
    if not value:
        return ""
    try:
        local = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return sanitize_legacy_scalar(value)
    seconds = ((now or datetime.now(UTC)) - local).total_seconds()
    if 0 <= seconds < 60:
        return render(m.JUST_NOW)
    if 60 <= seconds < 3600:
        return render(m.MINUTES_AGO.bind(minutes=int(seconds // 60)))
    if 3600 <= seconds < 86400:
        return render(m.HOURS_AGO.bind(hours=int(seconds // 3600)))
    if 86400 <= seconds < 7 * 86400:
        return render(m.DAYS_AGO.bind(days=int(seconds // 86400)))
    return local.strftime("%Y-%m-%d %H:%M")
