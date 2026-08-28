#!/usr/bin/env python3
"""Deterministically rebuild normalized events and Spin Records."""
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


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name}:{line_number}: expected JSON object")
            yield value


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    temporary = path.with_name(path.name + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    temporary.replace(path)
    return count


def reextract_session(session_dir: Path) -> dict[str, Any]:
    source_path = session_dir / "source_events.jsonl"
    legacy_path = session_dir / "events.jsonl"
    legacy_mode = not source_path.exists()
    if legacy_mode:
        if not legacy_path.exists():
            raise FileNotFoundError(f"no source_events.jsonl or legacy events.jsonl in {session_dir}")
        source_path = legacy_path

    source_records = list(iter_jsonl(source_path))
    if legacy_mode and source_records and set(source_records[0]) == EVENT_KEYS:
        raise ValueError("events.jsonl is already normalized; source_events.jsonl is unavailable")

    normalized = list(adapt_stream(source_records))
    events_path = session_dir / ("normalized_events.jsonl" if legacy_mode else "events.jsonl")
    spin_records = [
        event
        for event in normalized
        if event["adapter"]["name"] == "batch_spin"
        and event["payload"]["status"] == "ok"
    ]
    write_jsonl(events_path, normalized)
    write_jsonl(session_dir / "spin_records.jsonl", spin_records)

    coverage: Counter[str] = Counter()
    for event in spin_records:
        fields = event["payload"].get("fields", {})
        for field_name in ALLOWED_FIELDS:
            if isinstance(fields.get(field_name), dict) and fields[field_name].get("present"):
                coverage[field_name] += 1

    return {
        "source": source_path.name,
        "events": events_path.name,
        "legacy_mode": legacy_mode,
        "source_event_count": len(source_records),
        "event_count": len(normalized),
        "spin_count": len(spin_records),
        "field_coverage": dict(sorted(coverage.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild Collector 1.0 events from scoped source records"
    )
    parser.add_argument("session_dir", type=Path)
    args = parser.parse_args()
    result = reextract_session(args.session_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
