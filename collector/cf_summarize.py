#!/usr/bin/env python3
"""Build value-free Collector 1.0 JSON and Markdown summaries."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.batch_spin import ALLOWED_FIELDS
from adapters.registry import adapt_stream

EVENT_KEYS = {"event", "adapter", "source", "payload"}
SUMMARY_SCHEMA_VERSION = "cf-session-summary-v1"


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path.name}:{line_number}: expected JSON object")
            yield record


def normalized_events(path: Path) -> list[dict[str, Any]]:
    records = list(iter_jsonl(path))
    if not records:
        return []
    if set(records[0]) == EVENT_KEYS:
        for index, record in enumerate(records, start=1):
            if set(record) != EVENT_KEYS:
                raise ValueError(f"{path.name}:{index}: invalid event envelope")
        return records
    return list(adapt_stream(records))


def summarize(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    event_names: Counter[str] = Counter()
    adapters: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    truncations = 0
    spin_count = 0
    field_coverage: Counter[str] = Counter()

    for event in events:
        event_names[str(event["event"].get("name", "unknown"))] += 1
        adapter_name = str(event["adapter"].get("name", "unknown"))
        adapters[adapter_name] += 1
        payload = event["payload"]
        status = str(payload.get("status", "unknown"))
        statuses[status] += 1
        for warning in payload.get("warnings", []):
            warnings[str(warning)] += 1
        if payload.get("truncated"):
            truncations += 1
        if adapter_name != "batch_spin" or status != "ok":
            continue
        spin_count += 1
        fields = payload.get("fields", {})
        for field_name in ALLOWED_FIELDS:
            field = fields.get(field_name)
            if isinstance(field, dict) and field.get("present"):
                field_coverage[field_name] += 1

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "event_count": sum(event_names.values()),
        "event_names": dict(sorted(event_names.items())),
        "adapters": dict(sorted(adapters.items())),
        "statuses": dict(sorted(statuses.items())),
        "warnings": dict(sorted(warnings.items())),
        "truncated_event_count": truncations,
        "spin": {
            "spin_count": spin_count,
            "field_coverage": dict(sorted(field_coverage.items())),
            "note": "value-free aggregate; event values remain in local session artifacts",
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    spin = summary["spin"]
    lines = [
        "# 【游戏】 Collector Session Summary",
        "",
        f"- Event count: {summary['event_count']}",
        f"- Spin count: {spin['spin_count']}",
        f"- Truncated events: {summary['truncated_event_count']}",
        "",
        "## Adapter counts",
        "",
    ]
    for name, count in summary["adapters"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Spin field coverage", ""])
    for name in ALLOWED_FIELDS:
        lines.append(f"- `{name}`: {spin['field_coverage'].get(name, 0)}/{spin['spin_count']}")
    lines.extend(["", "> 脱敏聚合；逐笔值与 source records 仅保存在本地 Session。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a value-free 【游戏】 session summary")
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument(
        "--spin-records",
        type=Path,
        help="Compatibility argument; normalized spin records are summarized from events",
    )
    args = parser.parse_args()
    result = summarize(normalized_events(args.events))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"summary -> {args.output}", flush=True)
    else:
        print(rendered, end="")
    if args.markdown:
        args.markdown.write_text(render_markdown(result), encoding="utf-8")
        print(f"summary -> {args.markdown}", flush=True)


if __name__ == "__main__":
    main()
