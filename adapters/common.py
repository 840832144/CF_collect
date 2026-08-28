from __future__ import annotations

from typing import Any, Iterable

EVENT_SCHEMA_VERSION = "cf-event-v1"
ADAPTER_VERSION = "1.0.0"
TARGET_KIND = "lua-pcall-args"
TARGET_MESSAGE_TYPE = 3


def table_field(node: Any, key: str) -> Any:
    """Return one value node from a serialized Lua table."""
    if not isinstance(node, dict) or node.get("type") != "table":
        return None
    fields = node.get("fields", [])
    if not isinstance(fields, list):
        return None
    for field in fields:
        if isinstance(field, dict) and field.get("key") == key:
            return field.get("value")
    return None


def argument_value(record: dict[str, Any], index: int) -> Any:
    arguments = record.get("arguments", [])
    if not isinstance(arguments, list):
        return None
    for argument in arguments:
        if isinstance(argument, dict) and argument.get("index") == index:
            return argument.get("value")
    return None


def extract_command(record: dict[str, Any]) -> str | None:
    arg2 = argument_value(record, 2)
    command = table_field(arg2, "[1]")
    if not isinstance(command, dict) or command.get("type") != "string":
        return None
    value = command.get("value")
    return value if isinstance(value, str) else None


def table_path(node: Any, keys: Iterable[str]) -> Any:
    current = node
    for key in keys:
        current = table_field(current, key)
        if current is None:
            break
    return current


def normalized_field(node: Any) -> dict[str, Any]:
    """Copy one allowlisted field without copying nested table contents."""
    if node is None:
        return {"present": False}
    if not isinstance(node, dict):
        return {"present": True, "type": "unknown", "malformed": True}

    value_type = str(node.get("type", "unknown"))
    result: dict[str, Any] = {"present": True, "type": value_type}
    if value_type in {"number", "string", "boolean"} and "value" in node:
        result["value"] = node["value"]
    elif value_type == "table":
        fields = node.get("fields", [])
        result["element_count"] = len(fields) if isinstance(fields, list) else 0
    if node.get("truncated"):
        result["truncated"] = True
        result["truncation_reason"] = str(node.get("reason", "unspecified"))
    return result


def source_metadata(record: dict[str, Any], source_event_index: int) -> dict[str, Any]:
    return {
        "kind": str(record.get("kind", "unknown")),
        "event_index": source_event_index,
        "message_type": record.get("messageType"),
        "scope_id": record.get("scopeId"),
        "thread_id": record.get("threadId"),
    }


def event_envelope(
    *,
    name: str,
    adapter_name: str,
    record: dict[str, Any],
    source_event_index: int,
    event_index: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact Collector 1.0 top-level event contract."""
    return {
        "event": {
            "name": name,
            "schema_version": EVENT_SCHEMA_VERSION,
            "index": event_index,
            "captured_at": record.get("captured_at"),
        },
        "adapter": {"name": adapter_name, "version": ADAPTER_VERSION},
        "source": source_metadata(record, source_event_index),
        "payload": payload,
    }


def base_matches(record: dict[str, Any], command: str) -> bool:
    return (
        isinstance(record, dict)
        and record.get("kind") == TARGET_KIND
        and record.get("messageType") == TARGET_MESSAGE_TYPE
        and extract_command(record) == command
    )


def field_warnings(
    field_name: str, field: dict[str, Any], expected_type: str
) -> list[str]:
    warnings: list[str] = []
    if not field.get("present"):
        warnings.append(f"missing-field:{field_name}")
        return warnings
    if field.get("type") != expected_type:
        warnings.append(f"field-type-change:{field_name}:{field.get('type', 'unknown')}")
    if field.get("truncated"):
        warnings.append(
            f"truncated:{field_name}:{field.get('truncation_reason', 'unspecified')}"
        )
    return warnings
