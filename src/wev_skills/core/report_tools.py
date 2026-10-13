"""The tool-selection part of the delivery report, for one task.

The two token figures are sums of rough per-tool constants. They are labeled as estimates
wherever they appear, and no difference between them is computed or called a saving.
"""

from __future__ import annotations

from typing import Any

from wev_skills import i18n
from wev_skills.state.model import TaskRecord


def section(record: TaskRecord, lang: str | None = None) -> dict[str, Any] | None:
    """What was offered, selected and dropped for the task, and every restored tool (a miss).

    ``None`` when no selection ran for the task (``harness.tool_selection: off``).
    """
    chosen = record.tool_selection
    if chosen is None:
        return None
    return {
        "offered": list(chosen.offered),
        "selected": list(chosen.selected),
        "dropped": list(chosen.dropped),
        "profile": chosen.profile,
        "source": chosen.source,
        "reasons": list(chosen.reasons),
        "estimated_definition_tokens": {
            "label": i18n.t("decisions.tools.report.estimate_label", lang),
            "offered": chosen.estimated_tokens_offered,
            "selected": chosen.estimated_tokens_selected,
        },
        "misses": [miss.to_dict() for miss in record.tool_misses],
        "miss_count": len(record.tool_misses),
    }
