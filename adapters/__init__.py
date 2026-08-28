"""Collector 1.0 adapters for scoped inbound source records."""

from .registry import ADAPTERS, adapt_record, adapt_stream

__all__ = ["ADAPTERS", "adapt_record", "adapt_stream"]
