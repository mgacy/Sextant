import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backend
import bootstrap
import poll
import state_ops
import worker_ops


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def config_for(repo_root, target_root, *, backend_name="mock_subprocess", timeout=3600):
    return {
        "runId": "worker-test-run",
        "tool": {
            "name": "sextant",
            "repoPath": str(repo_root),
            "versionCommand": [sys.executable, "-c", "print('0.1.0')"],
            "smokeTestCommand": [sys.executable, "-c", "print('ok')"],
        },
        "target": {
            "codebasePath": str(target_root),
            "swiftPath": "Sources",
            "transcriptProjectHint": "fixture-project",
        },
        "taskCorpusPath": "task-corpus.json",
        "workers": {
            "backend": backend_name,
            "harness": "claude",
            "maxConcurrent": 1,
            "sessionTimeoutSeconds": timeout,
        },
        "usage": {
            "source": "claudeOAuthUsageApi",
            "fetchCommand": [sys.executable, "-c", "print('{\"usage\":{\"sevenDay\":12.5}}')"],
            "required": True,
            "budgetPercent": 25,
        },
        "transcripts": {
            "extractCommand": [sys.executable, "-c", "print('{}')"],
            "maxToolCalls": 200,
            "maxMessages": 80,
            "maxSliceTurns": 40,
            "missingTranscriptPolicy": "retryThenStop",
        },
        "convergence": {
            "maxIterations": 2,
            "plateauThreshold": 2,
            "frictionThreshold": 3,
            "stopOnHighConfidenceHandoff": True,
        },
        "scope": {
            "allowImplementation": False,
            "allowDocsChanges": False,
            "allowedArtifactRoot": ".claude-tracking/tool-eval-runs",
        },
    }


class RunFixture:
    def __init__(self, temp, *, backend_name="mock_subprocess", timeout=3600):
        self.repo_root = Path(temp)
        self.target_root = self.repo_root / "target"
        self.target_root.mkdir()
        self.run_dir = self.repo_root / ".claude-tracking" / "tool-eval-runs" / "worker-test-run"
        self.run_dir.mkdir(parents=True)
        self.config = config_for(self.repo_root, self.target_root, backend_name=backend_name, timeout=timeout)
        self.tool_state = {"gitCommit": "abc123", "version": "0.1.0", "smokeTestPassed": True}
        self.usage = {
            "initialSevenDay": None,
            "latestSevenDay": None,
            "runDelta": None,
            "budgetPercent": 25,
            "fetchFailed": False,
        }
        write_json(self.run_dir / "run-config.json", self.config)
        write_json(
            self.run_dir / "optimization-state.json",
            bootstrap.initial_state(self.config, self.tool_state, self.usage, now="2026-04-27T00:00:00Z"),
        )

    def state(self):
        return state_ops.read_state(self.run_dir)


def clean_git_runner(argv, **kwargs):
    if argv[:3] == ["git", "status", "--porcelain"]:
        return completed(argv, stdout="")
    return completed(argv, returncode=99, stderr="unexpected")


class WorkerLifecycleTests(unittest.TestCase):
    def test_worker_ref_is_persisted_before_mock_launch_and_prompt_is_rendered(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_backend = backend.MockSubprocessBackend()

            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Find reducer actions."},
                expected_revision=1,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:00Z",
            )

            ref_path = Path(launched["workerRefPath"])
            prompt_path = Path(launched["promptPath"])
            self.assertTrue(ref_path.is_file())
            self.assertTrue(prompt_path.is_file())
            self.assertIn("Find reducer actions.", prompt_path.read_text(encoding="utf-8"))
            self.assertIn("worker-test-run", prompt_path.read_text(encoding="utf-8"))
            self.assertEqual(fixture.state()["workers"][0]["status"], "prepared")

            worker_backend.close_worker(launched)

    def test_mock_subprocess_lifecycle_completes_and_records_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_backend = backend.MockSubprocessBackend()
            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                expected_revision=1,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:00Z",
            )

            deadline = time.time() + 5
            result = None
            revision = 2
            while time.time() < deadline:
                result = poll.poll_worker(
                    run_dir=fixture.run_dir,
                    config=fixture.config,
                    worker_ref=launched,
                    expected_revision=revision,
                    worker_backend=worker_backend,
                    now="2026-04-27T00:01:01Z",
                    runner=clean_git_runner,
                )
                revision = result["state"]["revision"]
                if result["worker"]["status"] == "succeeded":
                    break
                time.sleep(0.05)

            self.assertIsNotNone(result)
            self.assertEqual(result["worker"]["status"], "succeeded")
            self.assertEqual(result["worker"]["artifacts"], [
                "iteration-1/tool-user/report.md",
                "iteration-1/tool-user/transcript-ref.json",
            ])

            closed = poll.close_worker(
                run_dir=fixture.run_dir,
                worker_ref=launched,
                expected_revision=revision,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:02Z",
            )
            self.assertTrue(closed["worker"]["closed"])
            self.assertEqual(closed["worker"]["status"], "closed")

    def test_malformed_completion_signal_is_recorded_as_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_backend = backend.MockSubprocessBackend(command=[sys.executable, "-c", "import time; time.sleep(1)"])
            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                expected_revision=1,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:00Z",
            )
            Path(launched["signalPath"]).write_text(
                json.dumps({"role": "tool-user", "status": "weird", "artifacts": [], "summary": "bad"}),
                encoding="utf-8",
            )

            result = poll.poll_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                worker_ref=launched,
                expected_revision=2,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:01Z",
                runner=clean_git_runner,
            )

            self.assertEqual(result["worker"]["status"], "invalidSignal")
            self.assertIn("status must be succeeded", result["worker"]["summary"])
            worker_backend.close_worker(launched)

    def test_timeout_is_recorded_and_worker_can_be_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, timeout=1)
            worker_backend = backend.MockSubprocessBackend(command=[sys.executable, "-c", "import time; time.sleep(5)"])
            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                expected_revision=1,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:00Z",
            )

            result = poll.poll_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                worker_ref=launched,
                expected_revision=2,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:02Z",
                runner=clean_git_runner,
            )

            self.assertEqual(result["worker"]["status"], "timedOut")
            closed = poll.close_worker(
                run_dir=fixture.run_dir,
                worker_ref=launched,
                expected_revision=result["state"]["revision"],
                worker_backend=worker_backend,
            )
            self.assertTrue(closed["worker"]["closed"])

    def test_post_run_diff_invalidates_successful_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_backend = backend.MockSubprocessBackend()
            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                expected_revision=1,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:00Z",
            )
            deadline = time.time() + 5
            while time.time() < deadline and not Path(launched["signalPath"]).exists():
                time.sleep(0.05)

            def dirty_runner(argv, **kwargs):
                if argv[:3] == ["git", "status", "--porcelain"]:
                    return completed(argv, stdout=" M Sources/File.swift\n")
                return completed(argv, returncode=99)

            result = poll.poll_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                worker_ref=launched,
                expected_revision=2,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:02Z",
                runner=dirty_runner,
            )

            self.assertEqual(result["worker"]["status"], "invalidatedByDiff")
            worker_backend.close_worker(launched)

    def test_completion_signal_rejects_artifact_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_ref = worker_ops.prepare_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
            )
            Path(worker_ref["signalPath"]).write_text(
                json.dumps({
                    "role": "tool-user",
                    "status": "succeeded",
                    "transcriptRef": None,
                    "artifacts": ["../escape.md"],
                    "summary": "bad",
                }),
                encoding="utf-8",
            )

            with self.assertRaises(worker_ops.WorkerError):
                worker_ops.read_completion_signal(fixture.run_dir, worker_ref)

    def test_cmux_claude_constructs_command_without_launching(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, backend_name="cmux")
            worker_ref = worker_ops.prepare_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
            )
            worker_backend = backend.CmuxClaudeBackend(dry_run=True)

            launched = worker_backend.create_worker(worker_ref)

            self.assertTrue(launched["dryRun"])
            self.assertEqual(launched["launchCommand"][0], "cmux")
            self.assertIn("claude", launched["launchCommand"])
            self.assertIn(str(Path(worker_ref["promptPath"])), launched["launchCommand"])
            self.assertNotIn(" ".join(launched["launchCommand"]), launched["launchCommand"])

    def test_cmux_launch_persists_workspace_ref_in_transcript_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, backend_name="cmux")
            worker_backend = backend.CmuxClaudeBackend(dry_run=True)

            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                expected_revision=1,
                worker_backend=worker_backend,
                now="2026-04-27T00:01:00Z",
            )

            transcript_ref = json.loads(Path(launched["transcriptRefPath"]).read_text(encoding="utf-8"))
            self.assertEqual(transcript_ref["workspaceRef"], launched["workspaceRef"])
            self.assertEqual(transcript_ref["sessionId"], "unknown-until-discovered")


if __name__ == "__main__":
    unittest.main()
