from __future__ import annotations

from typing import Any

from adapters.batch_spin import EXPECTED_TYPES


def table(fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "fields": [{"key": key, "value": value} for key, value in fields.items()],
    }


def scalar(value_type: str, value: Any = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": value_type}
    if value is not None:
        node["value"] = value
    return node


def make_batch_spin_record(
    *,
    command: str = "batch_spin",
    kind: str = "lua-pcall-args",
    message_type: int = 3,
    include_direct: bool = True,
    fields: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if fields is None:
        fields = {
            name: (
                table({"[1]": scalar("number", 1)})
                if expected_type == "table"
                else scalar("number", index + 10)
            )
            for index, (name, expected_type) in enumerate(EXPECTED_TYPES.items())
        }
    list_fields = {"[1]": table(fields)} if include_direct else {}
    payload = table({"list": table(list_fields)})
    arg2 = table(
        {
            "[1]": scalar("string", command),
            "[2]": payload,
        }
    )
    return {
        "captured_at": "2026-08-28T00:00:00+00:00",
        "kind": kind,
        "messageType": message_type,
        "scopeId": 7,
        "threadId": 11,
        "arguments": [
            {"index": 1, "value": scalar("number", 2)},
            {"index": 2, "value": arg2},
        ],
    }


def make_keepalive_record(command: str = "keepalive") -> dict[str, Any]:
    payload = table(
        {
            "coins": scalar("number", 100),
            "chips": scalar("number", 200),
            "avg_bet": table({"bc": scalar("number", 5), "extra": scalar("number", 9)}),
            "unapproved": scalar("string", "must-not-escape"),
        }
    )
    arg2 = table({"[1]": scalar("string", command), "[2]": payload})
    return {
        "captured_at": "2026-08-28T00:00:01+00:00",
        "kind": "lua-pcall-args",
        "messageType": 3,
        "scopeId": 8,
        "threadId": 11,
        "arguments": [{"index": 2, "value": arg2}],
    }
