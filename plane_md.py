"""Markdown table cell helpers shared by plane_snapshot / plane_write / plane_diff.

esc_md_cell is not a full inverse of unesc_md_cell for newlines: escaping
collapses newlines to spaces, so unesc cannot restore them.
"""

# Plane intake triage status: API numeric value ↔ markdown label.
INTAKE_STATUS = {
    -2: "pending",
    -1: "rejected",
    0: "snoozed",
    1: "accepted",
    2: "duplicate",
}
INTAKE_STATUS_VALUE = {label: value for value, label in INTAKE_STATUS.items()}

# Plane state.group id → display label for module summary columns/rows.
# Order is table column order. Do not use API completed_issues/etc. (unreliable).
STATE_GROUP_COLS = [
    ("completed", "Done"),
    ("started", "In Progress"),
    ("unstarted", "Todo"),
    ("backlog", "Backlog"),
    ("cancelled", "Cancelled"),
]


def format_item_id(prefix: str, seq) -> str:
    """Format a work-item identifier as PREFIX-seq (e.g. CT-42)."""
    return f"{prefix}-{seq}"


def count_by_state_group(group_ids) -> dict:
    """Count known Plane state.group ids; ignore None and unknown values."""
    counts = {g: 0 for g, _ in STATE_GROUP_COLS}
    for grp in group_ids:
        if grp in counts:
            counts[grp] += 1
    return counts


def esc_md_cell(text: str) -> str:
    """Escape pipe characters and collapse newlines for markdown table cells."""
    return text.replace("|", "\\|").replace("\n", " ")


def unesc_md_cell(text: str) -> str:
    """Unescape pipe characters from markdown table cells."""
    return text.replace("\\|", "|")
