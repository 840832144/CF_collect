from __future__ import annotations

from collections.abc import Iterable, Iterator
from types import ModuleType
from typing import Any

from . import batch_spin, keepalive

ADAPTERS: tuple[ModuleType, ...] = (batch_spin, keepalive)


def adapt_record(
    record: dict[str, Any], source_event_index: int, event_index: int
) -> dict[str, Any] | None:
    """Route one source record to one exact adapter, or ignore it."""
    for adapter in ADAPTERS:
        if adapter.matches(record):
            return adapter.adapt(record, source_event_index, event_index)
    return None


def adapt_stream(records: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    event_index = 0
    for source_event_index, record in enumerate(records):
        event = adapt_record(record, source_event_index, event_index)
        if event is None:
            continue
        yield event
        event_index += 1
