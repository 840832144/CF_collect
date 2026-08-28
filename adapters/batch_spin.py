from __future__ import annotations

from typing import Any

from .common import (
    argument_value,
    base_matches,
    event_envelope,
    field_warnings,
    normalized_field,
    table_field,
    table_path,
)

NAME = "batch_spin"
COMMAND = "batch_spin"
EVENT_NAME = "spin.record"

# TASK-0024 confirmed these six fields. Collector 1.0 deliberately does not
# discover or emit any other keys found on the same object.
ALLOWED_FIELDS = (
    "base_win",
    "bonus_base_win",
    "total_win",
    "coins",
    "win_lines",
    "win_pos_list",
)
EXPECTED_TYPES = {
    "base_win": "number",
    "bonus_base_win": "number",
    "total_win": "number",
    "coins": "number",
    "win_lines": "table",
    "win_pos_list": "table",
}


def matches(record: dict[str, Any]) -> bool:
    return base_matches(record, COMMAND)


def adapt(
    record: dict[str, Any], source_event_index: int, event_index: int
) -> dict[str, Any]:
    arg2 = argument_value(record, 2)
    payload_node = table_field(arg2, "[2]")
    direct = table_path(payload_node, ("list", "[1]"))
    warnings: list[str] = []

    if payload_node is None:
        warnings.append("missing-payload:arg[2].[2]")
    if direct is None:
        warnings.append("missing-direct-result:arg[2].[2].list.[1]")
    if not isinstance(direct, dict) or direct.get("type") != "table":
        body = {
            "status": "skipped",
            "reason": "malformed-shape",
            "command": COMMAND,
            "fields": {name: {"present": False} for name in ALLOWED_FIELDS},
            "warnings": warnings,
            "truncated": bool(record.get("truncated")),
        }
        return event_envelope(
            name=EVENT_NAME,
            adapter_name=NAME,
            record=record,
            source_event_index=source_event_index,
            event_index=event_index,
            payload=body,
        )

    fields: dict[str, dict[str, Any]] = {}
    for name in ALLOWED_FIELDS:
        field = normalized_field(table_field(direct, name))
        fields[name] = field
        warnings.extend(field_warnings(name, field, EXPECTED_TYPES[name]))

    present_count = sum(1 for field in fields.values() if field.get("present"))
    status = "ok" if present_count else "skipped"
    body = {
        "status": status,
        "reason": None if status == "ok" else "no-allowlisted-fields",
        "command": COMMAND,
        "fields": fields,
        "warnings": warnings,
        "truncated": bool(record.get("truncated"))
        or bool(direct.get("truncated"))
        or any(field.get("truncated") for field in fields.values()),
    }
    return event_envelope(
        name=EVENT_NAME,
        adapter_name=NAME,
        record=record,
        source_event_index=source_event_index,
        event_index=event_index,
        payload=body,
    )
