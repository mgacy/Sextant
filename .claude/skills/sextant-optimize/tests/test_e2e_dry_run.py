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
import check_convergence
import poll
import resume
import state_ops
import worker_ops


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def config_for(repo_root, target_root):
    return {
        "runId": "e2e-dry-run",
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
            "backend": "mock_subprocess",
            "harness": "claude",
            "maxConcurrent": 1,
            "sessionTimeoutSeconds": 30,
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


def fake_runner(commit="abc123", version="0.1.0"):
    def run(argv, **kwargs):
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return completed(argv, stdout=f"{commit}\n")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return completed(argv, stdout="")
        if argv == [sys.executable, "-c", "print('0.1.0')"]:
            return completed(argv, stdout=f"{version}\n")
        if argv == [sys.executable, "-c", "print('ok')"]:
            return completed(argv, stdout="ok\n")
        if argv == [sys.executable, "-c", "print('{\"usage\":{\"sevenDay\":12.5}}')"]:
            return completed(argv, stdout='{"usage":{"sevenDay":12.5}}\n')
        return completed(argv, returncode=99, stderr=f"unexpected command: {argv}")

    return run


def role_worker_command():
    code = r"""
import json
import os
from pathlib import Path

role = os.environ["SEXTANT_WORKER_ROLE"]
output_dir = Path(os.environ["SEXTANT_WORKER_OUTPUT_DIR"])
output_rel = os.environ["SEXTANT_WORKER_OUTPUT_REL"]
signal_path = Path(os.environ["SEXTANT_WORKER_SIGNAL_PATH"])
output_dir.mkdir(parents=True, exist_ok=True)
artifacts = []

def write_text(name, text):
    path = output_dir / name
    path.write_text(text, encoding="utf-8")
    artifacts.append(f"{output_rel}/{name}")

def write_json(name, payload):
    path = output_dir / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifacts.append(f"{output_rel}/{name}")

if role == "tool-user":
    write_text("report.md", "# Tool User\nUsed sextant, then rg for parent context.\n")
    write_json("transcript-summary.json", {"sessionId": "session-001", "toolCalls": [{"name": "sextant"}, {"name": "rg"}]})
elif role == "friction-miner":
    write_json("friction-events.json", {"events": [{
        "id": "friction-001",
        "taskId": "controlled-task",
        "source": {"kind": "transcript", "sessionRef": "fixture-project/session-001", "turn": 4},
        "category": "fallbackSearch",
        "severity": "medium",
        "evidence": "Tool User ran rg after Sextant because parent reducer context was missing.",
        "expectedToolBehavior": "Sextant should provide enough parent context to avoid broad text search.",
        "suspectedFixLocus": "sextant",
        "proposedFix": "Expose parent declaration context in structural query output.",
        "verified": True
    }]})
    write_text("report.md", "One verified fallback-search event.\n")
elif role == "evaluator":
    write_json("scorecard.json", {
        "iteration": 1,
        "comparedTo": "baseline",
        "tasks": [{
            "id": "controlled-task",
            "group": "controlled",
            "answerQuality": "grounded",
            "sextantQueries": 1,
            "fallbackRgQueries": 1,
            "fileReadsAfterTool": 1,
            "failedAttempts": 0,
            "adHocScripts": 0,
            "manualJsonFiltering": 0,
            "newFrictionEvents": 1,
            "frictionScore": 7,
            "previousFrictionScore": 12,
            "delta": -5
        }],
        "aggregate": {
            "frictionScore": 7,
            "previousFrictionScore": 12,
            "delta": -5,
            "regressions": 0,
            "newFriction": 1,
            "evaluationInvalid": False,
            "highConfidenceOpportunities": 1
        },
        "controlled": {
            "frictionScore": 7,
            "previousFrictionScore": 12,
            "delta": -5,
            "regressions": 0,
            "newFriction": 1,
            "evaluationInvalid": False,
            "highConfidenceOpportunities": 1
        },
        "perturbed": {
            "frictionScore": 0,
            "previousFrictionScore": 0,
            "delta": 0,
            "regressions": 0,
            "newFriction": 0,
            "evaluationInvalid": False,
            "highConfidenceOpportunities": 0
        }
    })
    write_text("evaluation.md", "Grounded answer with one high-confidence opportunity.\n")
elif role == "opportunity-generator":
    write_json("prioritized.json", {
        "opportunities": [{
            "id": "opportunity-001",
            "title": "Expose parent declaration context",
            "sourceFrictionIds": ["friction-001"],
            "suspectedFixLocus": "sextant",
            "confidence": "high",
            "expectedImpact": "Reduce fallback text searches after structural queries.",
            "recommendedNextStep": "Prototype parent context in enum-case output."
        }],
        "prioritized": ["opportunity-001"]
    })
    write_text("candidates.md", "Prioritized one Sextant opportunity.\n")
elif role == "critic":
    write_text("critique.md", "Opportunity is evidence-backed; stop for handoff.\n")
    write_text("perturbation.md", "Perturbed task not run in mock dry run.\n")
else:
    raise SystemExit(f"unknown role: {role}")

signal = {
    "role": role,
    "status": "succeeded",
    "transcriptRef": f"{output_rel}/transcript-ref.json",
    "artifacts": [f"{output_rel}/transcript-ref.json", *artifacts],
    "summary": f"{role} completed in mock dry run.",
}
signal_path.write_text(json.dumps(signal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"{role} completed")
"""
    return [sys.executable, "-c", code]


class EndToEndDryRunTests(unittest.TestCase):
    def launch_and_poll_role(self, run_dir, config, role, task, worker_backend):
        state = state_ops.read_state(run_dir)
        launched = worker_ops.launch_worker(
            run_dir=run_dir,
            config=config,
            role=role,
            iteration=1,
            task=task,
            expected_revision=state["revision"],
            worker_backend=worker_backend,
            now="2026-04-27T01:00:00Z",
        )

        signal_path = Path(launched["signalPath"])
        deadline = time.time() + 5
        while time.time() < deadline and not signal_path.exists():
            time.sleep(0.05)
        self.assertTrue(signal_path.exists(), f"{role} did not write completion signal")

        state = state_ops.read_state(run_dir)
        result = poll.poll_worker(
            run_dir=run_dir,
            config=config,
            worker_ref=launched,
            expected_revision=state["revision"],
            worker_backend=worker_backend,
            now="2026-04-27T01:00:01Z",
            runner=fake_runner(),
        )
        self.assertEqual(result["worker"]["status"], "succeeded")
        self.assertTrue(result["worker"]["artifacts"])
        return result["worker"]

    def test_complete_mock_dry_run_reaches_handoff_and_waiting_for_external_change(self):
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp)
            target_root = repo_root / "target"
            target_root.mkdir()
            config = config_for(repo_root, target_root)
            config_path = repo_root / "run-config.json"
            write_json(config_path, config)

            run_dir = bootstrap.bootstrap(config_path, repo_root=repo_root, skip_prerequisites=True)
            self.assertEqual(state_ops.read_state(run_dir)["status"], "running")
            write_json(run_dir / "task-corpus.json", {"tasks": [{"id": "controlled-task", "prompt": "Trace reducer actions."}]})

            task = {"id": "controlled-task", "prompt": "Trace reducer actions."}
            worker_backend = backend.MockSubprocessBackend(command=role_worker_command())
            roles = ["tool-user", "friction-miner", "evaluator", "opportunity-generator", "critic"]
            completed_workers = [
                self.launch_and_poll_role(run_dir, config, role, task, worker_backend)
                for role in roles
            ]

            for worker in completed_workers:
                prompt_text = Path(run_dir / worker["artifacts"][0]).parent.joinpath("prompt.md").read_text(encoding="utf-8")
                self.assertNotIn("{{", prompt_text)
                self.assertNotIn("}}", prompt_text)

            scorecard_path = run_dir / "iteration-1" / "evaluator" / "scorecard.json"
            decision = check_convergence.decide_convergence(
                state=state_ops.read_state(run_dir),
                config=config,
                scorecard=json.loads(scorecard_path.read_text(encoding="utf-8")),
            )
            self.assertEqual(decision["decision"], "stop")
            self.assertEqual(decision["reasons"], ["high-confidence handoff available"])
            write_json(run_dir / "iteration-1" / "decision.json", decision)
            (run_dir / "iteration-1" / "handoff.md").write_text(
                "# Handoff\n\nHigh-confidence opportunity: expose parent declaration context.\n",
                encoding="utf-8",
            )

            state = state_ops.record_iteration_result(
                run_dir,
                expected_revision=state_ops.read_state(run_dir)["revision"],
                iteration=1,
                scorecard_path="iteration-1/evaluator/scorecard.json",
                artifacts=[
                    "iteration-1/friction-miner/friction-events.json",
                    "iteration-1/evaluator/scorecard.json",
                    "iteration-1/opportunities/prioritized.json",
                    "iteration-1/critique/critique.md",
                    "iteration-1/decision.json",
                    "iteration-1/handoff.md",
                ],
            )
            state = state_ops.record_decision(
                run_dir,
                expected_revision=state["revision"],
                decision=decision,
            )
            state = state_ops.transition_status(
                run_dir,
                expected_revision=state["revision"],
                new_status="handoffReady",
            )
            state = state_ops.transition_status(
                run_dir,
                expected_revision=state["revision"],
                new_status="waitingForExternalChange",
            )

            self.assertEqual(state["status"], "waitingForExternalChange")
            self.assertIsNone(state["decision"]["nextPhase"])
            self.assertTrue((run_dir / "iteration-1" / "handoff.md").is_file())
            unchanged_tool_state = state_ops.read_state(run_dir)["toolState"]
            with self.assertRaises(resume.NoExternalChangeError):
                resume.resume_after_external_change(
                    run_dir,
                    repo_root=repo_root,
                    external_change_ref="no-change",
                    runner=fake_runner(
                        commit=unchanged_tool_state["gitCommit"],
                        version=unchanged_tool_state["version"],
                    ),
                )
            self.assertEqual(state_ops.read_state(run_dir)["status"], "waitingForExternalChange")


if __name__ == "__main__":
    unittest.main()
