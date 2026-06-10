import json
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from io import StringIO
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backend
import bootstrap
import poll
import session_ops
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
            self.run_dir / "git-status.json",
            {
                "tool": {"statusPorcelain": []},
                "target": {"statusPorcelain": []},
            },
        )
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


class FailingCloseBackend:
    """Delegates to a real backend but always fails to close the workspace."""

    name = "mock_subprocess"

    def __init__(self, inner):
        self.inner = inner

    def create_worker(self, worker_ref):
        return self.inner.create_worker(worker_ref)

    def poll_worker(self, worker_ref):
        return self.inner.poll_worker(worker_ref)

    def read_worker_screen(self, worker_ref, max_lines):
        return self.inner.read_worker_screen(worker_ref, max_lines)

    def close_worker(self, worker_ref):
        return backend.CloseResult(closed=False, status="closeFailed", exit_code=None)


class TranscriptDeletingBackend:
    """Simulates post-create bookkeeping failure by removing the transcript ref."""

    name = "cmux_claude"

    def __init__(self):
        self.closed = []

    def create_worker(self, worker_ref):
        Path(worker_ref["transcriptRefPath"]).unlink()
        return {**worker_ref, "workspaceRef": "workspace:9"}

    def poll_worker(self, worker_ref):
        raise AssertionError("poll_worker should not be called")

    def read_worker_screen(self, worker_ref, max_lines):
        raise AssertionError("read_worker_screen should not be called")

    def close_worker(self, worker_ref):
        self.closed.append(worker_ref.get("workspaceRef"))
        return backend.CloseResult(closed=True, status="closed", exit_code=None)


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
            self.assertEqual(fixture.state()["workers"][1]["status"], "launched")

            worker_backend.close_worker(launched)

    def test_worker_ops_cli_prepares_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            task_path = fixture.run_dir / "task.json"
            write_json(task_path, {"id": "task-1", "prompt": "Use Sextant."})

            with redirect_stdout(StringIO()):
                result = worker_ops.main([
                    "--run",
                    str(fixture.run_dir),
                    "--config",
                    str(fixture.run_dir / "run-config.json"),
                    "--role",
                    "tool-user",
                    "--iteration",
                    "1",
                    "--task",
                    str(task_path),
                    "prepare",
                ])

            self.assertEqual(result, 0)
            self.assertTrue((fixture.run_dir / "iteration-1" / "tool-user" / "worker-ref.json").is_file())

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
            revision = fixture.state()["revision"]
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
                "iteration-1/tool-user/transcript-summary.json",
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
                expected_revision=fixture.state()["revision"],
                worker_backend=worker_backend,
                now="2026-04-27T00:01:01Z",
                runner=clean_git_runner,
            )

            self.assertEqual(result["worker"]["status"], "invalidSignal")
            self.assertIn("status must be succeeded", result["worker"]["summary"])
            self.assertTrue(result["worker"]["closeResult"]["closed"])

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
                expected_revision=fixture.state()["revision"],
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
                expected_revision=fixture.state()["revision"],
                worker_backend=worker_backend,
                now="2026-04-27T00:01:02Z",
                runner=dirty_runner,
            )

            self.assertEqual(result["worker"]["status"], "invalidatedByDiff")
            self.assertTrue(result["worker"]["closeResult"]["closed"])

    def test_git_status_failure_invalidates_successful_worker(self):
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

            def failing_git_runner(argv, **kwargs):
                if argv[:3] == ["git", "status", "--porcelain"]:
                    return completed(argv, returncode=128, stderr="not a git repo")
                return completed(argv, returncode=99)

            result = poll.poll_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                worker_ref=launched,
                expected_revision=fixture.state()["revision"],
                worker_backend=worker_backend,
                now="2026-04-27T00:01:02Z",
                runner=failing_git_runner,
            )

            self.assertEqual(result["worker"]["status"], "invalidatedByDiff")
            self.assertTrue(result["worker"]["diffStatus"]["failed"])
            self.assertIn("post-run git status failed", result["worker"]["errors"])
            self.assertTrue(result["worker"]["closeResult"]["closed"])

    def test_timeout_close_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, timeout=1)
            inner = backend.MockSubprocessBackend(command=[sys.executable, "-c", "import time; time.sleep(5)"])
            launched = worker_ops.launch_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
                expected_revision=1,
                worker_backend=inner,
                now="2026-04-27T00:01:00Z",
            )

            result = poll.poll_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                worker_ref=launched,
                expected_revision=fixture.state()["revision"],
                worker_backend=FailingCloseBackend(inner),
                now="2026-04-27T00:01:02Z",
                runner=clean_git_runner,
            )

            self.assertEqual(result["worker"]["status"], "timedOut")
            self.assertFalse(result["worker"]["closeResult"]["closed"])
            self.assertEqual(result["worker"]["closeResult"]["status"], "closeFailed")
            self.assertTrue(any("close failed" in error for error in result["worker"]["errors"]))
            inner.close_worker(launched)

    def test_corrupt_baseline_status_is_surfaced_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            (fixture.run_dir / "git-status.json").write_text("not json", encoding="utf-8")

            diff = poll.capture_post_run_diff_status(
                fixture.config,
                run_dir=fixture.run_dir,
                runner=clean_git_runner,
            )

            self.assertIn("unreadable", diff["baselineLoadError"])

    def test_launch_bookkeeping_failure_closes_workspace_and_records_launch_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, backend_name="cmux")
            worker_backend = TranscriptDeletingBackend()

            with self.assertRaises(FileNotFoundError):
                worker_ops.launch_worker(
                    run_dir=fixture.run_dir,
                    config=fixture.config,
                    role="tool-user",
                    iteration=1,
                    task={"id": "task-1", "prompt": "Use Sextant."},
                    expected_revision=1,
                    worker_backend=worker_backend,
                    now="2026-04-27T00:01:00Z",
                )

            self.assertEqual(worker_backend.closed, ["workspace:9"])
            statuses = [worker["status"] for worker in fixture.state()["workers"]]
            self.assertEqual(statuses, ["prepared", "launchFailed"])
            ref = json.loads(
                (fixture.run_dir / "iteration-1" / "tool-user" / "worker-ref.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ref["status"], "launchFailed")
            self.assertFalse(ref.get("closed") is False)

    def test_completion_signal_rejects_missing_artifact_file(self):
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
                    "artifacts": ["iteration-1/tool-user/report.md"],
                    "summary": "claims an artifact that was never written",
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(worker_ops.WorkerError, "does not exist"):
                worker_ops.read_completion_signal(fixture.run_dir, worker_ref)

    def test_completion_signal_requires_transcript_ref_listed_in_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_ref = worker_ops.prepare_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
            )
            output_dir = Path(worker_ref["outputDir"])
            (output_dir / "report.md").write_text("# Report\n", encoding="utf-8")
            (output_dir / "transcript-summary.json").write_text("{}", encoding="utf-8")
            (output_dir / "extra.json").write_text("{}", encoding="utf-8")
            Path(worker_ref["signalPath"]).write_text(
                json.dumps({
                    "role": "tool-user",
                    "status": "succeeded",
                    "transcriptRef": "iteration-1/tool-user/extra.json",
                    "artifacts": [
                        "iteration-1/tool-user/report.md",
                        "iteration-1/tool-user/transcript-ref.json",
                        "iteration-1/tool-user/transcript-summary.json",
                    ],
                    "summary": "transcript ref is not listed in artifacts",
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(worker_ops.WorkerError, "must also be listed in artifacts"):
                worker_ops.read_completion_signal(fixture.run_dir, worker_ref)

    def test_post_run_diff_compares_baseline_ignores_run_artifacts_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            write_json(
                fixture.run_dir / "git-status.json",
                {
                    "tool": {"statusPorcelain": [" M preexisting.txt"]},
                    "target": {"statusPorcelain": []},
                },
            )

            def baseline_and_artifact_runner(argv, **kwargs):
                if argv[:3] == ["git", "status", "--porcelain"] and kwargs.get("cwd") == str(fixture.repo_root.resolve()):
                    return completed(
                        argv,
                        stdout=(
                            " M preexisting.txt\n"
                            "?? .claude-tracking/tool-eval-runs/worker-test-run/iteration-1/handoff.md\n"
                        ),
                    )
                if argv[:3] == ["git", "status", "--porcelain"]:
                    return completed(argv, stdout="")
                return completed(argv, returncode=99)

            clean = poll.capture_post_run_diff_status(
                fixture.config,
                run_dir=fixture.run_dir,
                runner=baseline_and_artifact_runner,
            )
            self.assertFalse(clean["dirty"])

            def failed_runner(argv, **kwargs):
                if argv[:3] == ["git", "status", "--porcelain"] and kwargs.get("cwd") == str(fixture.target_root.resolve()):
                    return completed(argv, returncode=128, stderr="not a git repo")
                if argv[:3] == ["git", "status", "--porcelain"]:
                    return completed(argv, stdout="")
                return completed(argv, returncode=99)

            failed = poll.capture_post_run_diff_status(
                fixture.config,
                run_dir=fixture.run_dir,
                runner=failed_runner,
            )
            self.assertTrue(failed["failed"])
            self.assertFalse(failed["repos"]["tool"]["failed"])
            self.assertTrue(failed["repos"]["target"]["failed"])

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

    def test_completion_signal_rejects_missing_required_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            worker_ref = worker_ops.prepare_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="evaluator",
                iteration=1,
                task={"id": "task-1", "prompt": "Evaluate."},
            )
            output_dir = Path(worker_ref["outputDir"])
            (output_dir / "evaluation.md").write_text("# Evaluation\n", encoding="utf-8")
            Path(worker_ref["signalPath"]).write_text(
                json.dumps({
                    "role": "evaluator",
                    "status": "succeeded",
                    "transcriptRef": None,
                    "artifacts": ["iteration-1/evaluator/evaluation.md"],
                    "summary": "missing scorecard",
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(worker_ops.WorkerError, "missing required artifacts"):
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
            self.assertEqual(launched["claudeCommand"][0], "claude")
            self.assertIn(str(Path(worker_ref["promptPath"])), launched["claudeCommand"])
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

    def test_parse_workspace_ref_returns_none_when_no_ref_is_found(self):
        self.assertIsNone(session_ops.parse_workspace_ref(""))
        self.assertIsNone(session_ops.parse_workspace_ref("created something\n"))
        self.assertIsNone(session_ops.parse_workspace_ref('{"unrelated": 1}'))
        self.assertEqual(session_ops.parse_workspace_ref("workspace:7\n"), "workspace:7")
        self.assertEqual(
            session_ops.parse_workspace_ref('{"workspaceRef": "workspace:9"}'),
            "workspace:9",
        )

    def test_live_cmux_launch_rejects_unparseable_workspace_ref(self):
        def garbled_runner(argv, **kwargs):
            if argv[:2] == ["cmux", "new-workspace"]:
                return completed(argv, stdout="launched, no ref printed\n")
            return completed(argv, returncode=99, stderr="unexpected")

        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, backend_name="cmux")
            worker_ref = worker_ops.prepare_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
            )
            worker_backend = backend.CmuxClaudeBackend(runner=garbled_runner)

            with self.assertRaisesRegex(backend.BackendError, "did not report a workspace ref"):
                worker_backend.create_worker(worker_ref)

    def test_live_cmux_launch_failure_propagates_without_recording_launched_state(self):
        def failing_runner(argv, **kwargs):
            if argv[:2] == ["cmux", "new-workspace"]:
                return completed(argv, returncode=1, stderr="cmux daemon unavailable")
            return completed(argv, returncode=99, stderr="unexpected")

        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, backend_name="cmux")
            worker_backend = backend.CmuxClaudeBackend(runner=failing_runner)

            with self.assertRaisesRegex(backend.BackendError, "cmux daemon unavailable"):
                worker_ops.launch_worker(
                    run_dir=fixture.run_dir,
                    config=fixture.config,
                    role="tool-user",
                    iteration=1,
                    task={"id": "task-1", "prompt": "Use Sextant."},
                    expected_revision=1,
                    worker_backend=worker_backend,
                    now="2026-04-27T00:01:00Z",
                )

            ref = json.loads(
                (fixture.run_dir / "iteration-1" / "tool-user" / "worker-ref.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ref["status"], "prepared")
            statuses = [worker["status"] for worker in fixture.state()["workers"]]
            self.assertEqual(statuses, ["prepared"])

    def test_live_cmux_backend_polls_reads_and_closes_workspace(self):
        calls = []

        def fake_runner(argv, **kwargs):
            calls.append(argv)
            if argv[:2] == ["cmux", "new-workspace"]:
                return completed(argv, stdout="workspace:7\n")
            if argv[:2] == ["cmux", "surface-health"]:
                return completed(argv, stdout="healthy\n")
            if argv[:2] == ["cmux", "read-screen"]:
                return completed(argv, stdout="line1\nline2\n")
            if argv[:2] == ["cmux", "close-workspace"]:
                return completed(argv)
            return completed(argv, returncode=99, stderr="unexpected")

        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp, backend_name="cmux")
            worker_ref = worker_ops.prepare_worker(
                run_dir=fixture.run_dir,
                config=fixture.config,
                role="tool-user",
                iteration=1,
                task={"id": "task-1", "prompt": "Use Sextant."},
            )
            worker_backend = backend.CmuxClaudeBackend(runner=fake_runner)
            launched = worker_backend.create_worker(worker_ref)

            self.assertEqual(launched["workspaceRef"], "workspace:7")
            self.assertEqual(worker_backend.poll_worker(launched).status, "running")
            self.assertEqual(worker_backend.read_worker_screen(launched, 10).lines, ["line1", "line2"])
            self.assertTrue(worker_backend.close_worker(launched).closed)
            self.assertIn(["cmux", "close-workspace", "--workspace", "workspace:7"], calls)

    def test_timeout_closes_worker_before_recording_terminal_status(self):
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
                expected_revision=fixture.state()["revision"],
                worker_backend=worker_backend,
                now="2026-04-27T00:01:02Z",
                runner=clean_git_runner,
            )

            self.assertEqual(result["worker"]["status"], "timedOut")
            self.assertTrue(result["worker"]["closeResult"]["closed"])


if __name__ == "__main__":
    unittest.main()
