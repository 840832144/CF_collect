#!/usr/bin/env python3
# cf_summarize.py — Cash Frenzy 会话脱敏结构摘要（值不进入摘要）
# 改编自 TASK-0024 `summarize_task0024.py`；新增 spin_records 聚合（只统计、不含绝对数值）。
#
# 用法：
#   python cf_summarize.py <session_dir>/events.jsonl --output <session_dir>/summary.json
#   python cf_summarize.py <session_dir>/events.jsonl --spin-records <session_dir>/spin_records.jsonl
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

VALUE_KEYS = {"value", "identity", "captured_at", "error"}
SAFE_COMMAND = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/-]{0,127}$")
DIRECT_FIELD_NAMES = {
    "base_win", "bonus_base_win", "coins", "feature", "result",
    "total_win", "win_lines", "win_pos_list",
}


def iter_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def collect_value(node: Any, path: str, fields: Counter[tuple[str, str]], truncations: Counter[str]) -> None:
    if not isinstance(node, dict):
        return
    value_type = str(node.get("type", "unknown"))
    fields[(path, value_type)] += 1
    if node.get("truncated"):
        truncations[str(node.get("reason", "unspecified"))] += 1
    if value_type != "table":
        return
    for field in node.get("fields", []):
        if not isinstance(field, dict):
            continue
        key = str(field.get("key", "<missing-key>"))
        collect_value(field.get("value"), f"{path}.{key}", fields, truncations)


def table_field(node: Any, key: str) -> Any:
    if not isinstance(node, dict) or node.get("type") != "table":
        return None
    for field in node.get("fields", []):
        if isinstance(field, dict) and field.get("key") == key:
            return field.get("value")
    return None


def extract_command(record: dict[str, Any]) -> str | None:
    for argument in record.get("arguments", []):
        if not isinstance(argument, dict) or argument.get("index") != 2:
            continue
        command = table_field(argument.get("value"), "[1]")
        if not isinstance(command, dict) or command.get("type") != "string":
            return None
        value = command.get("value")
        if isinstance(value, str) and SAFE_COMMAND.fullmatch(value):
            return value
        return "<redacted-command>"
    return None


def is_direct_field(path: str) -> bool:
    return path.startswith("arg[2].[2].") and path.rsplit(".", 1)[-1] in DIRECT_FIELD_NAMES


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    kinds: Counter[str] = Counter()
    message_types: Counter[str] = Counter()
    fields: Counter[tuple[str, str]] = Counter()
    truncations: Counter[str] = Counter()
    scope_threads: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    command_direct_events: Counter[str] = Counter()
    command_direct_fields: Counter[tuple[str, str, str]] = Counter()
    record_count = 0

    for record in records:
        record_count += 1
        kind = str(record.get("kind", "unknown"))
        kinds[kind] += 1
        if "messageType" in record:
            message_types[str(record["messageType"])] += 1
        if kind in {"probe-truncated", "host-truncated"} or record.get("truncated"):
            truncations[str(record.get("reason", "unspecified"))] += 1
        if kind == "inbound-scope-summary":
            scope_threads[str(record.get("threadId", "unknown"))] += 1
        if kind != "lua-pcall-args":
            continue
        record_fields: Counter[tuple[str, str]] = Counter()
        for argument in record.get("arguments", []):
            if not isinstance(argument, dict):
                continue
            index = argument.get("index", "?")
            path = f"arg[{index}]"
            collect_value(argument.get("value"), path, fields, truncations)
            collect_value(argument.get("value"), path, record_fields, Counter())
        command = extract_command(record)
        if command is not None:
            commands[command] += 1
            direct_fields = {
                (path, value_type)
                for path, value_type in record_fields
                if is_direct_field(path)
            }
            if direct_fields:
                command_direct_events[command] += 1
            for path, value_type in direct_fields:
                command_direct_fields[(command, path, value_type)] += 1

    return {
        "schema_version": "cf-structure-summary-v1",
        "record_count": record_count,
        "event_kinds": dict(sorted(kinds.items())),
        "message_types": dict(sorted(message_types.items())),
        "scope_thread_count": len(scope_threads),
        "commands": [
            {
                "command": command,
                "count": count,
                "direct_event_count": command_direct_events[command],
                "direct_fields": [
                    {"path": path, "type": value_type, "count": field_count}
                    for (field_command, path, value_type), field_count
                    in sorted(command_direct_fields.items())
                    if field_command == command
                ],
            }
            for command, count in sorted(commands.items())
        ],
        "field_paths": [
            {"path": path, "type": value_type, "count": count}
            for (path, value_type), count in sorted(fields.items())
        ],
        "truncations": dict(sorted(truncations.items())),
    }


def spin_summary(spin_path: Path) -> dict[str, Any]:
    """spin_records.jsonl 的脱敏聚合：只统计字段覆盖率，不输出绝对数值。"""
    total = 0
    field_counts: Counter[str] = Counter()
    with spin_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            total += 1
            for key in ("base_win", "bonus_base_win", "total_win", "coins",
                        "win_lines_count", "win_pos_list_count"):
                if key in record:
                    field_counts[key] += 1
    return {
        "schema_version": "cf-spin-summary-v1",
        "spin_count": total,
        "field_coverage": dict(sorted(field_counts.items())),
        "note": "value-free aggregate; raw values stay in local-only spin_records.jsonl",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a value-free Cash Frenzy session summary")
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--spin-records", type=Path)
    args = parser.parse_args()
    result = summarize(iter_records(args.events))
    if args.spin_records and args.spin_records.exists():
        result["spin"] = spin_summary(args.spin_records)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"summary -> {args.output}", flush=True)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
