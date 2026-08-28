from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.common import EVENT_SCHEMA_VERSION

MANIFEST_SCHEMA_VERSION = "cf-session-manifest-v1"
SOURCE_EVENT_SCHEMA_VERSION = "task-0024-scoped-source-v1"

ARTIFACTS = {
    "manifest": "session_manifest.json",
    "source_events": "source_events.jsonl",
    "events": "events.jsonl",
    "spin_records": "spin_records.jsonl",
    "summary_json": "summary.json",
    "summary_markdown": "summary.md",
}


class SessionArtifacts:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.paths = {name: session_dir / filename for name, filename in ARTIFACTS.items()}

    def prepare_new(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        existing = [path.name for path in self.paths.values() if path.exists()]
        if existing:
            raise FileExistsError(
                "session already contains Collector artifacts: " + ", ".join(sorted(existing))
            )
        for name in ("source_events", "events", "spin_records"):
            self.paths[name].touch(exist_ok=False)

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def append_source(self, record: dict[str, Any]) -> None:
        self._append_jsonl(self.paths["source_events"], record)

    def append_event(self, event: dict[str, Any]) -> None:
        self._append_jsonl(self.paths["events"], event)

    def append_spin(self, event: dict[str, Any]) -> None:
        self._append_jsonl(self.paths["spin_records"], event)

    def write_manifest(
        self,
        *,
        session_id: str,
        runtime: dict[str, Any],
        mode: str,
        limits: dict[str, Any],
        start_utc: str,
        end_utc: str,
        counts: dict[str, int],
        final_status: str,
    ) -> dict[str, Any]:
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "session_id": session_id,
            "runtime": runtime,
            "mode": mode,
            "limits": limits,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "final_status": final_status,
            "counts": dict(counts),
            "artifacts": {
                "source_events": {
                    "path": ARTIFACTS["source_events"],
                    "schema_version": SOURCE_EVENT_SCHEMA_VERSION,
                    "local_only": True,
                },
                "events": {
                    "path": ARTIFACTS["events"],
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "local_only": True,
                },
                "spin_records": {
                    "path": ARTIFACTS["spin_records"],
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "local_only": True,
                },
                "summary_json": {
                    "path": ARTIFACTS["summary_json"],
                    "schema_version": "cf-session-summary-v1",
                    "local_only": True,
                },
                "summary_markdown": {
                    "path": ARTIFACTS["summary_markdown"],
                    "schema_version": "cf-session-summary-md-v1",
                    "local_only": True,
                },
            },
        }
        self.paths["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return manifest
