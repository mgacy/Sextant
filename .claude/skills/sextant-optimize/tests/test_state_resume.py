import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bootstrap
import resume
import state_ops


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def config_for(repo_root, target_root):
    return {
        "runId": "state-test-run",
        "tool": {
            "name": "sextant",
            "repoPath": ".",
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
            "backend": "cmux",
            "harness": "claude",
            "maxConcurrent": 1,
            "sessionTimeoutSeconds": 3600,
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


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fake_runner(commit="abc123", version="0.1.0", smoke_returncode=0):
    def run(argv, **kwargs):
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return completed(argv, stdout=f"{commit}\n")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return completed(argv, stdout="")
        if argv == [sys.executable, "-c", "print('0.1.0')"]:
            return completed(argv, stdout=f"{version}\n")
        if argv == [sys.executable, "-c", "print('ok')"]:
            return completed(argv, returncode=smoke_returncode, stdout="ok\n")
        return completed(argv, returncode=99, stderr=f"unexpected command: {argv}")

    return run


class RunFixture:
    def __init__(self, temp):
        self.repo_root = Path(temp)
        self.target_root = self.repo_root / "target"
        self.target_root.mkdir()
        self.run_dir = self.repo_root / ".claude-tracking" / "tool-eval-runs" / "state-test-run"
        self.run_dir.mkdir(parents=True)
        self.config = config_for(self.repo_root, self.target_root)
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

    def write_state(self, state):
        write_json(self.run_dir / "optimization-state.json", state)


class StateOperationTests(unittest.TestCase):
    def test_atomic_write_replaces_state_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)

            updated = state_ops.transition_status(
                fixture.run_dir,
                expected_revision=1,
                new_status="handoffReady",
                now="2026-04-27T00:01:00Z",
            )

            self.assertEqual(updated["status"], "handoffReady")
            self.assertEqual(updated["revision"], 2)
            self.assertEqual(fixture.state()["updatedAt"], "2026-04-27T00:01:00Z")
            self.assertEqual(list(fixture.run_dir.glob(".optimization-state.json.*.tmp")), [])

    def test_existing_lock_blocks_state_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            (fixture.run_dir / ".optimization-state.lock").write_text("locked\n", encoding="utf-8")

            with self.assertRaises(state_ops.StateLockError):
                state_ops.transition_status(
                    fixture.run_dir,
                    expected_revision=1,
                    new_status="handoffReady",
                )

    def test_revision_check_rejects_stale_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            state_ops.transition_status(fixture.run_dir, expected_revision=1, new_status="handoffReady")

            with self.assertRaises(state_ops.RevisionMismatchError):
                state_ops.transition_status(
                    fixture.run_dir,
                    expected_revision=1,
                    new_status="waitingForExternalChange",
                )

    def test_valid_status_transition_chain_and_invalid_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)

            with self.assertRaises(state_ops.InvalidTransitionError):
                state_ops.transition_status(fixture.run_dir, expected_revision=1, new_status="readyForRerun")

            state = state_ops.transition_status(fixture.run_dir, expected_revision=1, new_status="handoffReady")
            state = state_ops.transition_status(
                fixture.run_dir,
                expected_revision=state["revision"],
                new_status="waitingForExternalChange",
            )
            self.assertEqual(state["status"], "waitingForExternalChange")
            self.assertIsNone(state["decision"]["nextPhase"])
            state = state_ops.mark_ready_for_rerun(
                fixture.run_dir,
                expected_revision=state["revision"],
                external_change={
                    "ref": "commit:def456",
                    "previousToolState": fixture.tool_state,
                    "recapturedToolState": {"gitCommit": "def456", "version": "0.2.0", "smokeTestPassed": True},
                },
                now="2026-04-27T00:02:00Z",
            )
            self.assertEqual(state["status"], "readyForRerun")
            state = state_ops.start_rerun(
                fixture.run_dir,
                expected_revision=state["revision"],
                tool_state={"gitCommit": "def456", "version": "0.2.0", "smokeTestPassed": True},
            )
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["currentIteration"], 2)

    def test_iteration_result_requires_existing_scorecard_and_appends(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)

            with self.assertRaises(state_ops.StateError):
                state_ops.record_iteration_result(
                    fixture.run_dir,
                    expected_revision=1,
                    iteration=1,
                    scorecard_path="iteration-1/evaluator/scorecard.json",
                )

            scorecard = fixture.run_dir / "iteration-1" / "evaluator" / "scorecard.json"
            scorecard.parent.mkdir(parents=True)
            write_json(scorecard, {"ok": True})
            state = state_ops.record_iteration_result(
                fixture.run_dir,
                expected_revision=1,
                iteration=1,
                scorecard_path="iteration-1/evaluator/scorecard.json",
                artifacts=["iteration-1/evaluator/scorecard.json"],
            )

            self.assertEqual(state["iterations"][0]["scorecard"], "iteration-1/evaluator/scorecard.json")


class ResumeFlowTests(unittest.TestCase):
    def waiting_state(self, fixture):
        state = fixture.state()
        state["status"] = "waitingForExternalChange"
        state["revision"] = 4
        fixture.write_state(state)

    def test_resume_exits_when_no_external_change_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            self.waiting_state(fixture)

            with self.assertRaises(resume.NoExternalChangeError):
                resume.resume_after_external_change(
                    fixture.run_dir,
                    repo_root=fixture.repo_root,
                    external_change_ref="no-change",
                    runner=fake_runner(commit="abc123", version="0.1.0"),
                )

            self.assertFalse((fixture.run_dir / "iteration-2").exists())
            self.assertEqual(fixture.state()["status"], "waitingForExternalChange")
            self.assertEqual(fixture.state()["revision"], 4)

    def test_resume_requires_waiting_for_external_change(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)

            with self.assertRaises(resume.ResumeError):
                resume.resume_after_external_change(
                    fixture.run_dir,
                    repo_root=fixture.repo_root,
                    external_change_ref="commit:def456",
                    runner=fake_runner(commit="def456", version="0.2.0"),
                )

    def test_valid_resume_recaptures_tool_state_and_creates_next_iteration(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = RunFixture(temp)
            self.waiting_state(fixture)

            result = resume.resume_after_external_change(
                fixture.run_dir,
                repo_root=fixture.repo_root,
                external_change_ref="commit:def456",
                runner=fake_runner(commit="def456", version="0.2.0"),
            )

            state = result["state"]
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["currentIteration"], 2)
            self.assertEqual(state["revision"], 6)
            self.assertEqual(state["toolState"]["gitCommit"], "def456")
            self.assertEqual(state["toolState"]["version"], "0.2.0")
            self.assertTrue((fixture.run_dir / "iteration-2").is_dir())
            self.assertTrue((fixture.run_dir / "iteration-2" / "git-status.json").is_file())
            self.assertEqual(state["iterations"][-1]["directory"], "iteration-2")
            self.assertEqual(state["iterations"][-1]["externalChange"]["ref"], "commit:def456")
            self.assertEqual(state["iterations"][-1]["externalChange"]["previousToolState"]["gitCommit"], "abc123")
            self.assertEqual(
                state["iterations"][-1]["externalChange"]["recapturedToolState"]["gitCommit"],
                "def456",
            )


if __name__ == "__main__":
    unittest.main()
