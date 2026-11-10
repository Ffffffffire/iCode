# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Personal-memory display text shared by screens and sidebar widgets."""

from chrys.foundation.i18n import msg

RECALL_TIP = msg(
    "tui.personal_memory.recall_tip",
    fallback="Provided to the agent for reference. This does not confirm it was applied in the answer.",
)

__all__ = ["RECALL_TIP"]
