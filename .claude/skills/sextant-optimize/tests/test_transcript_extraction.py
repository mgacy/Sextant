import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_transcript
import session_ops
import worker_ops


def completed(argv, payload, returncode=0):
    stdout = json.dumps(payload) if isinstance(payload, dict) else payload
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")


def config_for(target_root, *, policy="retryThenStop", max_tool=2, max_messages=2, max_files=2, max_slice=2):
    return {
        "target": {
            "codebasePath": str(target_root),
            "swiftPath": "Sources",
            "transcriptProjectHint": "fixture-project",
        },
        "transcripts": {
            "extractCommand": [sys.executable, str(SCRIPTS / "extract_transcript.py")],
            "maxToolCalls": max_tool,
            "maxMessages": max_messages,
            "maxFileReferences": max_files,
            "maxSliceTurns": max_slice,
            "missingTranscriptPolicy": policy,
        },
    }


def transcript_ref(**overrides):
    ref = {
        "role": "tool-user",
        "workerId": "iteration-1-tool-user-001",
        "backend": "cmux_claude",
        "workspaceRef": "cmux:iteration-1-tool-user-001",
        "claudeProject": "fixture-project",
        "sessionId": "unknown-until-discovered",
        "startedAt": "2026-04-27T00:01:00Z",
        "completedAt": "2026-04-27T00:04:00Z",
        "status": "pending",
    }
    ref.update(overrides)
    return ref


def ok(data, total=None):
    count = total if total is not None else (len(data) if isinstance(data, list) else 1)
    return {"ok": True, "data": data, "_meta": {"total": count, "returned": count, "hasMore": False}}


class FixtureRunner:
    def __init__(self, *, scoped_list=None, broad_list=None):
        self.commands = []
        self.scoped_list = scoped_list if scoped_list is not None else []
        self.broad_list = broad_list if broad_list is not None else []

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        command = argv[1]
        if command == "list":
            if "--all-projects" in argv:
                return completed(argv, ok(self.broad_list, len(self.broad_list)))
            return completed(argv, ok(self.scoped_list, len(self.scoped_list)))
        if command == "shape":
            return completed(argv, ok({
                "session_id": argv[2],
                "agent_id": None,
                "turns": [
                    {"n": 1, "role": "user", "type": "user", "block_index": 0},
                    {"n": 2, "role": "assistant", "type": "tool_use", "block_index": 0, "tools": ["Read"]},
                    {"n": 3, "role": "assistant", "type": "tool_use", "block_index": 0, "tools": ["Grep"]},
                ],
                "summary": {
                    "total_turns": 5,
                    "user_messages": 1,
                    "tool_calls": {"Read": 1, "Grep": 1},
                    "first_edit_turn": None,
                    "duration_minutes": 3.0,
                },
            }))
        if command == "tools":
            return completed(argv, ok({
                "session_id": argv[2],
                "agent_id": None,
                "tool_calls": [
                    {"turn": 2, "tool": "Read", "input_summary": "file='A.swift'", "outcome": "success"},
                    {"turn": 3, "tool": "Grep", "input_summary": "pattern='Reducer'", "outcome": "success"},
                    {"turn": 4, "tool": "Read", "input_summary": "file='B.swift'", "outcome": "success"},
                ],
            }))
        if command == "messages":
            return completed(argv, ok({
                "session_id": argv[2],
                "agent_id": None,
                "messages": [
                    {"n": 1, "role": "user", "content": [{"type": "text", "text": "task"}]},
                    {"n": 2, "role": "assistant", "content": [{"type": "tool_use", "name": "Read"}]},
                    {"n": 3, "role": "assistant", "content": [{"type": "tool_use", "name": "Grep"}]},
                ],
            }))
        if command == "files":
            return completed(argv, ok({
                "session_id": argv[2],
                "agent_id": None,
                "group_by": "file",
                "files": [
                    {"path": "/repo/A.swift", "operations": ["read"], "turns": [2], "errored": False},
                    {"path": "/repo/B.swift", "operations": ["grep"], "turns": [3], "errored": False},
                    {"path": "/repo/C.swift", "operations": ["read"], "turns": [4], "errored": False},
                ],
            }))
        if command == "slice":
            return completed(argv, ok({
                "session_id": argv[2],
                "agent_id": None,
                "entries": [
                    {"type": "user", "message": {"content": "task"}},
                    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
                ],
            }))
        return completed(argv, {"ok": False}, returncode=2)


class TranscriptExtractionTests(unittest.TestCase):
    def test_worker_launch_writes_pending_transcript_ref_placeholder(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            target = Path(temp) / "target"
            run_dir.mkdir()
            target.mkdir()
            config = {
                "target": {
                    "codebasePath": str(target),
                    "swiftPath": "Sources",
                    "transcriptProjectHint": "fixture-project",
                },
                "workers": {"backend": "cmux", "harness": "claude"},
            }

            worker_ref = worker_ops.prepare_worker(
                run_dir=run_dir,
                config=config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                now="2026-04-27T00:01:00Z",
            )

            ref = json.loads(Path(worker_ref["transcriptRefPath"]).read_text(encoding="utf-8"))
            self.assertEqual(ref["sessionId"], "unknown-until-discovered")
            self.assertEqual(ref["status"], "pending")
            self.assertEqual(ref["startedAt"], "2026-04-27T00:01:00Z")

    def test_session_id_lookup_uses_existing_ref_and_bounds_summary(self):
        runner = FixtureRunner()
        config = config_for("/tmp/target", max_tool=2, max_messages=2, max_files=2, max_slice=2)

        ref, summary = extract_transcript.discover_then_extract(
            config=config,
            transcript_ref=transcript_ref(sessionId="session-1234", status="pending"),
            cc_session_tool="cc-session-tool",
            runner=runner,
        )

        self.assertEqual(ref["sessionId"], "session-1234")
        self.assertEqual(ref["status"], "discovered")
        self.assertFalse(any(command[1] == "list" for command in runner.commands))
        self.assertEqual([call["tool"] for call in summary["toolCalls"]], ["Read", "Grep"])
        self.assertEqual(len(summary["messages"]), 2)
        self.assertEqual(len(summary["fileReferences"]), 2)
        self.assertEqual(len(summary["turnSlices"]), 2)
        self.assertEqual(summary["truncated"], {
            "toolCalls": True,
            "messages": True,
            "fileReferences": True,
            "turnSlices": True,
        })

    def test_project_time_window_fallback_discovers_session_from_all_projects(self):
        runner = FixtureRunner(
            scoped_list=[],
            broad_list=[
                {
                    "session_id": "session-fallback",
                    "timestamp": "2026-04-27T00:03:00Z",
                    "session_ref": {"session_id": "session-fallback", "project": "fixture-project"},
                }
            ],
        )
        config = config_for("/tmp/target")

        ref, summary = extract_transcript.discover_then_extract(
            config=config,
            transcript_ref=transcript_ref(),
            cc_session_tool="cc-session-tool",
            runner=runner,
        )

        self.assertEqual(ref["sessionId"], "session-fallback")
        self.assertEqual(ref["claudeProject"], "fixture-project")
        self.assertEqual(summary["status"], "extracted")
        list_commands = [command for command in runner.commands if command[1] == "list"]
        self.assertIn("--project", list_commands[0])
        self.assertIn("--all-projects", list_commands[1])
        self.assertIn("--project-glob", list_commands[1])

    def test_retry_then_stop_marks_missing_after_two_discovery_attempts(self):
        runner = FixtureRunner(scoped_list=[], broad_list=[])
        config = config_for("/tmp/target", policy="retryThenStop")

        ref, summary = extract_transcript.discover_then_extract(
            config=config,
            transcript_ref=transcript_ref(),
            cc_session_tool="cc-session-tool",
            runner=runner,
        )

        self.assertEqual(ref["status"], "missing")
        self.assertEqual(summary["status"], "stopRequired")
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(len([command for command in runner.commands if command[1] == "list"]), 4)

    def test_mark_unevaluable_policy_does_not_retry_missing_transcript(self):
        runner = FixtureRunner(scoped_list=[], broad_list=[])
        config = config_for("/tmp/target", policy="markUnevaluable")

        ref, summary = extract_transcript.discover_then_extract(
            config=config,
            transcript_ref=transcript_ref(),
            cc_session_tool="cc-session-tool",
            runner=runner,
        )

        self.assertEqual(ref["status"], "missing")
        self.assertEqual(summary["status"], "unevaluable")
        self.assertEqual(summary["attempts"], 1)
        self.assertEqual(len([command for command in runner.commands if command[1] == "list"]), 2)

    def test_extract_for_paths_updates_ref_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "run-config.json"
            ref_path = root / "transcript-ref.json"
            summary_path = root / "transcript-summary.json"
            target = root / "target"
            target.mkdir()
            config_path.write_text(json.dumps(config_for(target)), encoding="utf-8")
            ref_path.write_text(json.dumps(transcript_ref(sessionId="session-1234")), encoding="utf-8")

            result = extract_transcript.extract_for_paths(
                config_path=config_path,
                transcript_ref_path=ref_path,
                summary_path=summary_path,
                runner=FixtureRunner(),
            )

            updated_ref = json.loads(ref_path.read_text(encoding="utf-8"))
            written_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(updated_ref["status"], "discovered")
            self.assertEqual(result["summary"]["status"], "extracted")
            self.assertEqual(written_summary["session"]["sessionId"], "session-1234")


if __name__ == "__main__":
    unittest.main()
