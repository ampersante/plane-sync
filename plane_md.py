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


def format_item_id(prefix: str, seq) -> str:
    """Format a work-item identifier as PREFIX-seq (e.g. CT-42)."""
    return f"{prefix}-{seq}"


def esc_md_cell(text: str) -> str:
    """Escape pipe characters and collapse newlines for markdown table cells."""
    return text.replace("|", "\\|").replace("\n", " ")


def unesc_md_cell(text: str) -> str:
    """Unescape pipe characters from markdown table cells."""
    return text.replace("\\|", "|")
