from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from adapters import batch_spin, keepalive
from adapters.registry import adapt_record, adapt_stream
from collector.cf_rextract import reextract_session
from collector.cf_summarize import render_markdown, summarize
from collector.readiness import REQUIRED_LUA_HOOKS, classify_ready_payload
from collector.session_artifacts import ARTIFACTS, SessionArtifacts
from tests.synthetic_records import make_batch_spin_record, make_keepalive_record, scalar

ROOT = Path(__file__).resolve().parents[1]
EVENT_KEYS = {"event", "adapter", "source", "payload"}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class AdapterTests(unittest.TestCase):
    def test_batch_spin_exact_contract_and_six_field_freeze(self) -> None:
        self.assertEqual(
            (
                "base_win",
                "bonus_base_win",
                "total_win",
                "coins",
                "win_lines",
                "win_pos_list",
            ),
            batch_spin.ALLOWED_FIELDS,
        )
        event = adapt_record(make_batch_spin_record(), 4, 0)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(EVENT_KEYS, set(event))
        self.assertEqual("batch_spin", event["adapter"]["name"])
        self.assertEqual("spin.record", event["event"]["name"])
        self.assertEqual(4, event["source"]["event_index"])
        self.assertEqual("ok", event["payload"]["status"])
        self.assertEqual(batch_spin.ALLOWED_FIELDS, tuple(event["payload"]["fields"]))

    def test_extra_fields_are_not_discovered_or_emitted(self) -> None:
        record = make_batch_spin_record()
        direct_fields = (
            record["arguments"][1]["value"]["fields"][1]["value"]["fields"][0]["value"]
            ["fields"][0]["value"]["fields"]
        )
        direct_fields.append({"key": "feature", "value": scalar("string", "do-not-emit")})
        direct_fields.append({"key": "result", "value": scalar("number", 999999)})
        event = adapt_record(record, 0, 0)
        assert event is not None
        rendered = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("feature", rendered)
        self.assertNotIn("result", rendered)
        self.assertNotIn("do-not-emit", rendered)
        self.assertNotIn("999999", rendered)

    def test_registry_fails_closed_for_non_targets(self) -> None:
        self.assertIsNone(adapt_record(make_batch_spin_record(command="tick"), 0, 0))
        self.assertIsNone(adapt_record(make_batch_spin_record(kind="other"), 0, 0))
        self.assertIsNone(adapt_record(make_batch_spin_record(message_type=1), 0, 0))

    def test_malformed_batch_spin_is_a_skipped_event(self) -> None:
        event = adapt_record(make_batch_spin_record(include_direct=False), 0, 0)
        assert event is not None
        self.assertEqual("skipped", event["payload"]["status"])
        self.assertEqual("malformed-shape", event["payload"]["reason"])
        self.assertIn(
            "missing-direct-result:arg[2].[2].list.[1]", event["payload"]["warnings"]
        )

    def test_type_and_truncation_warnings(self) -> None:
        record = make_batch_spin_record()
        direct_fields = (
            record["arguments"][1]["value"]["fields"][1]["value"]["fields"][0]["value"]
            ["fields"][0]["value"]["fields"]
        )
        for field in direct_fields:
            if field["key"] == "base_win":
                field["value"] = scalar("string", "changed")
            if field["key"] == "win_lines":
                field["value"]["truncated"] = True
                field["value"]["reason"] = "depth-budget"
        event = adapt_record(record, 0, 0)
        assert event is not None
        warnings = event["payload"]["warnings"]
        self.assertIn("field-type-change:base_win:string", warnings)
        self.assertIn("truncated:win_lines:depth-budget", warnings)
        self.assertTrue(event["payload"]["truncated"])

    def test_keepalive_only_emits_fixed_known_paths(self) -> None:
        event = adapt_record(make_keepalive_record(), 2, 0)
        assert event is not None
        self.assertEqual("keepalive", event["adapter"]["name"])
        self.assertEqual(keepalive.ALLOWED_FIELD_PATHS.keys(), event["payload"]["fields"].keys())
        rendered = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("unapproved", rendered)
        self.assertNotIn("must-not-escape", rendered)
        self.assertNotIn("extra", rendered)

    def test_input_is_read_only_and_event_indices_are_deterministic(self) -> None:
        records = [make_batch_spin_record(), make_keepalive_record(), make_batch_spin_record(command="tick")]
        before = copy.deepcopy(records)
        events = list(adapt_stream(records))
        self.assertEqual(before, records)
        self.assertEqual([0, 1], [event["event"]["index"] for event in events])
        self.assertEqual([0, 1], [event["source"]["event_index"] for event in events])


class SessionTests(unittest.TestCase):
    def test_fixed_manifest_and_artifact_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp) / "session_test"
            session_dir.mkdir()
            (session_dir / "probe.out.log").write_text("", encoding="utf-8")
            artifacts = SessionArtifacts(session_dir)
            artifacts.prepare_new()
            for name in ("source_events", "events", "spin_records"):
                self.assertTrue(artifacts.paths[name].exists())
            manifest = artifacts.write_manifest(
                session_id="session_test",
                runtime={"package": "example.package", "app_version": "1", "instance": "test", "adb_serial": "test"},
                mode="lua",
                limits={"max_depth": 4},
                start_utc="2026-08-28T00:00:00+00:00",
                end_utc="2026-08-28T00:01:00+00:00",
                counts={"source_events": 2, "events": 2, "batch_spin": 1},
                final_status="stopped",
            )
            self.assertEqual(set(ARTIFACTS) - {"manifest"}, set(manifest["artifacts"]))
            self.assertEqual("cf-session-manifest-v1", manifest["schema_version"])
            rendered = json.dumps(manifest)
            self.assertNotIn(str(session_dir), rendered)

    def test_new_session_reextract_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            source = session_dir / "source_events.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps(record) for record in [make_batch_spin_record(), make_keepalive_record()]
                )
                + "\n",
                encoding="utf-8",
            )
            before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            first = reextract_session(session_dir)
            first_events = (session_dir / "events.jsonl").read_bytes()
            first_spins = (session_dir / "spin_records.jsonl").read_bytes()
            second = reextract_session(session_dir)
            self.assertEqual(first, second)
            self.assertEqual(first_events, (session_dir / "events.jsonl").read_bytes())
            self.assertEqual(first_spins, (session_dir / "spin_records.jsonl").read_bytes())
            self.assertEqual(before_hash, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(2, first["event_count"])
            self.assertEqual(1, first["spin_count"])
            for event in jsonl(session_dir / "events.jsonl"):
                self.assertEqual(EVENT_KEYS, set(event))

    def test_legacy_raw_events_remain_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            legacy = session_dir / "events.jsonl"
            legacy.write_text(json.dumps(make_batch_spin_record()) + "\n", encoding="utf-8")
            before = legacy.read_bytes()
            result = reextract_session(session_dir)
            self.assertTrue(result["legacy_mode"])
            self.assertEqual("normalized_events.jsonl", result["events"])
            self.assertEqual(before, legacy.read_bytes())
            self.assertTrue((session_dir / "normalized_events.jsonl").exists())

    def test_summary_is_value_free(self) -> None:
        event = adapt_record(make_batch_spin_record(), 0, 0)
        assert event is not None
        result = summarize([event])
        rendered = json.dumps(result, ensure_ascii=False)
        markdown = render_markdown(result)
        self.assertEqual(1, result["spin"]["spin_count"])
        self.assertNotIn("100", rendered)
        self.assertNotIn("coins\": {\"present", rendered)
        self.assertIn("`coins`: 1/1", markdown)


class ReadinessTests(unittest.TestCase):
    def test_lua_ready_requires_both_scoped_hooks(self) -> None:
        partial = classify_ready_payload(
            "lua",
            {"kind": "hook-status", "mode": "lua", "installed": ["lua_pcall"]},
        )
        assert partial is not None
        self.assertEqual("rejected", partial["status"])
        self.assertEqual(["onUIThreadReceiveMessage"], partial["missing_hooks"])

        complete = classify_ready_payload(
            "lua",
            {"kind": "hook-status", "mode": "lua", "installed": list(REQUIRED_LUA_HOOKS)},
        )
        assert complete is not None
        self.assertEqual("verified", complete["status"])
        self.assertEqual([], complete["missing_hooks"])

    def test_unrelated_or_failed_stability_messages_are_not_ready(self) -> None:
        self.assertIsNone(classify_ready_payload("lua", {"kind": "lua-pcall-args"}))
        rejected = classify_ready_payload(
            "stability", {"kind": "stability-ready", "modulePresent": False}
        )
        assert rejected is not None
        self.assertEqual("rejected", rejected["status"])


class DeploymentRegressionTests(unittest.TestCase):
    def test_one_click_route_and_android_hook_scope_are_preserved(self) -> None:
        run = (ROOT / "run_collector.ps1").read_text(encoding="utf-8")
        ordered = [
            'Step "0. Preflight"',
            'Step "1. Start renamed frida-server"',
            'Step "2. Stage gadget + config into game namespace"',
            'Step "3. ADB forward"',
            'Step "4. Bootstrap gadget (cold start game)"',
            'Step "5. Start probe, wait READY"',
            'Step "6. PLAYER PHASE"',
            'Step "7. Extract + summarize"',
            'Step "8. Forced cleanup"',
        ]
        self.assertEqual(ordered, sorted(ordered, key=run.index))
        self.assertIn("[string]$ProjectRoot = $PSScriptRoot", run)
        self.assertIn('"--mode", "lua"', run)
        self.assertIn("-PythonPath $venvPy", run)
        self.assertNotIn(">=20", run)
        self.assertIn("} finally {", run)
        self.assertIn("Invoke-CollectorCleanup", run)
        self.assertIn("Test-ProbeReadyState", run)
        self.assertNotIn("$c.Split(' ')", run)
        self.assertNotIn("$c.Substring(6)", run)

        probe = (ROOT / "collector" / "cf_probe.py").read_text(encoding="utf-8")
        self.assertIn("Interceptor.attach(dispatch", probe)
        self.assertIn("Interceptor.attach(pcall", probe)
        self.assertIn("const scopes = {};", probe)
        self.assertIn("if (scope === undefined || scope.depth <= 0) return;", probe)
        self.assertNotIn("Stalker.", probe)
        self.assertNotIn("libEncryptorP", probe)
        loaded_to_print = probe[probe.index("script.load()") : probe.index("print(", probe.index("script.load()"))]
        self.assertNotIn('persist("ready")', loaded_to_print)
        self.assertIn("while not ready", loaded_to_print)
        self.assertIn("classify_ready_payload", probe)

    def test_root_is_manual_and_not_part_of_collector_cleanup(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        root_doc = (ROOT / "docs" / "ROOT_TOGGLE.md").read_text(encoding="utf-8")
        run = (ROOT / "run_collector.ps1").read_text(encoding="utf-8")
        self.assertNotIn("临时 Root 在 Session 后清理/回滚", readme)
        self.assertIn("Collector 只检测、不改变 BlueStacks Root", readme)
        self.assertIn("Root 始终由 User 手动控制", root_doc)
        self.assertIn("cleanup did not change BlueStacks Root", run)

    def test_cleanup_injection_suite_and_server_ownership_contract(self) -> None:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "tests" / "Test-Cleanup.ps1"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Cleanup injectable tests: PASS (7/7)", result.stdout)

        shape_result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "tests" / "Test-ProductionCollectionShapes.ps1"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            0,
            shape_result.returncode,
            shape_result.stdout + shape_result.stderr,
        )
        self.assertIn(
            "Production collection shape tests: PASS (10/10)",
            shape_result.stdout,
        )

        helper = (ROOT / "collector" / "cf_start_frida_server.ps1").read_text(
            encoding="utf-8"
        )
        run = (ROOT / "run_collector.ps1").read_text(encoding="utf-8")
        for field in ("pid", "remote_path", "started_by_run"):
            self.assertIn(field, helper)
            self.assertIn(field, run)
        self.assertIn("Stop-ExactRemoteServer", run)
        self.assertIn("Get-ExactRemoteServerPids", run)
        self.assertIn("process rollback", helper)
        self.assertIn("file rollback", helper)
        self.assertNotIn("pkill", run.lower())
        self.assertNotIn("killall", run.lower())
        self.assertNotRegex(run, r"return\s+,")
        self.assertNotRegex(helper, r"return\s+,")
        self.assertNotRegex(helper, r"\$pid\b")
        self.assertNotRegex(run, r"\$pid\b")
        self.assertIn("Probe/server/forward/Gadget/config/cf_* are absent", run)
        self.assertLess(run.index('Name "temp-gadget-config"'), run.index("push $gadgetHost"))
        self.assertLess(run.index('Name "adb-forward:$gadgetPort"'), run.index('forward "tcp:$gadgetPort"'))
        self.assertLess(run.index('Name "package-process:$pkg"'), run.index("cf_bootstrap_gadget.py"))


if __name__ == "__main__":
    unittest.main()
