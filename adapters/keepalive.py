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

NAME = "keepalive"
COMMAND = "keepalive"
EVENT_NAME = "state.keepalive"

# These paths were already present in the accepted TASK-0024 zero-operation
# baseline. They are fixed inputs here, not newly recovered schema.
ALLOWED_FIELD_PATHS = {
    "coins": ("coins",),
    "chips": ("chips",),
    "avg_bet.bc": ("avg_bet", "bc"),
}
EXPECTED_TYPES = {name: "number" for name in ALLOWED_FIELD_PATHS}


def matches(record: dict[str, Any]) -> bool:
    return base_matches(record, COMMAND)


def adapt(
    record: dict[str, Any], source_event_index: int, event_index: int
) -> dict[str, Any]:
    payload_node = table_field(argument_value(record, 2), "[2]")
    warnings: list[str] = []
    if not isinstance(payload_node, dict) or payload_node.get("type") != "table":
        body = {
            "status": "skipped",
            "reason": "malformed-shape",
            "command": COMMAND,
            "fields": {name: {"present": False} for name in ALLOWED_FIELD_PATHS},
            "warnings": ["missing-payload:arg[2].[2]"],
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
    for name, path in ALLOWED_FIELD_PATHS.items():
        field = normalized_field(table_path(payload_node, path))
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
        or bool(payload_node.get("truncated"))
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
