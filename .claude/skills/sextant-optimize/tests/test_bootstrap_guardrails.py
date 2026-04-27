import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bootstrap
import fetch_usage
from path_safety import PathSafetyError, artifact_path, ensure_contained


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def base_config(repo_root, target_root):
    return {
        "runId": "20260427T002948Z",
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


class BootstrapGuardrailTests(unittest.TestCase):
    def test_config_rejects_shell_string_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            config["tool"]["versionCommand"] = "swift run sextant --version"

            with self.assertRaises(bootstrap.ConfigError):
                bootstrap.validate_config(config)

    def test_config_rejects_shell_executable_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            config["tool"]["smokeTestCommand"] = ["sh", "-c", "swift run sextant --help"]

            with self.assertRaises(bootstrap.ConfigError):
                bootstrap.validate_config(config)

    def test_config_rejects_docs_or_implementation_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            config["scope"]["allowImplementation"] = True

            with self.assertRaises(bootstrap.ConfigError):
                bootstrap.validate_config(config)

    def test_prerequisite_failure_names_missing_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)

            with self.assertRaises(bootstrap.PrerequisiteError) as context:
                bootstrap.check_prerequisites(config, which=lambda _: None)

            self.assertIn("python3", context.exception.missing)
            self.assertIn("cmux", context.exception.missing)
            self.assertIn("claude", context.exception.missing)
            self.assertIn("cc-session-tool", context.exception.missing)
            self.assertIn("swift", context.exception.missing)

    def test_prerequisites_run_concrete_commands_and_require_cmux_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append(argv)
                return completed(argv)

            bootstrap.check_prerequisites(
                config,
                which=lambda name: f"/bin/{name}",
                runner=fake_runner,
                env={"CMUX_WORKSPACE_ID": "workspace:1"},
            )

            self.assertIn(["python3", "--version"], calls)
            self.assertIn(["swift", "--version"], calls)
            self.assertIn(["cc-session-tool", "--help"], calls)
            self.assertIn(["cmux", "version"], calls)
            self.assertIn(["claude", "--version"], calls)

            with self.assertRaises(bootstrap.PrerequisiteError) as context:
                bootstrap.check_prerequisites(
                    config,
                    which=lambda name: f"/bin/{name}",
                    runner=fake_runner,
                    env={},
                )
            self.assertIn("CMUX_WORKSPACE_ID", context.exception.missing)

    def test_run_directory_created_under_allowed_artifact_root(self):
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp)
            config = base_config(repo_root, repo_root)

            run_dir = bootstrap.create_run_directory(config, repo_root=repo_root)

            self.assertTrue(run_dir.is_dir())
            self.assertEqual(run_dir.name, config["runId"])
            artifact_root = (repo_root / ".claude-tracking" / "tool-eval-runs").resolve()
            self.assertEqual(run_dir.parent, artifact_root)

    def test_git_status_capture_records_commit_and_porcelain(self):
        calls = []

        def fake_runner(argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return completed(argv, stdout="abc123\n")
            if argv[:3] == ["git", "status", "--porcelain"]:
                return completed(argv, stdout=" M .claude/skills/file.py\n?? scratch.txt\n")
            return completed(argv, returncode=99, stderr="unexpected")

        with tempfile.TemporaryDirectory() as temp:
            capture = bootstrap.git_capture(Path(temp), runner=fake_runner)

        self.assertEqual(capture["commit"], "abc123")
        self.assertEqual(capture["statusPorcelain"], [" M .claude/skills/file.py", "?? scratch.txt"])
        self.assertFalse(capture["commitCommandFailed"])
        self.assertFalse(capture["statusCommandFailed"])
        self.assertEqual(len(calls), 2)

    def test_usage_fetch_required_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)

            def failing_runner(argv, **kwargs):
                return completed(argv, returncode=2, stderr="usage unavailable")

            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.fetch_usage_snapshot(config, repo_root=root, runner=failing_runner)

    def test_usage_fetch_optional_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            config["usage"]["required"] = False

            def failing_runner(argv, **kwargs):
                return completed(argv, returncode=2, stderr="usage unavailable")

            usage = bootstrap.fetch_usage_snapshot(config, repo_root=root, runner=failing_runner)

            self.assertTrue(usage["fetchFailed"])
            self.assertIsNone(usage["initialSevenDay"])
            self.assertEqual(usage["budgetPercent"], 25)

    def test_usage_fetch_success_normalizes_initial_and_latest_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)

            def success_runner(argv, **kwargs):
                return completed(argv, stdout='{"ok": true, "usage": {"sevenDay": 18.25}}')

            usage = bootstrap.fetch_usage_snapshot(config, repo_root=root, runner=success_runner)

            self.assertFalse(usage["fetchFailed"])
            self.assertEqual(usage["initialSevenDay"], 18.25)
            self.assertEqual(usage["latestSevenDay"], 18.25)
            self.assertEqual(usage["runDelta"], 0)

    def test_usage_fetch_reports_fetch_failed_payload_as_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)

            def failed_payload_runner(argv, **kwargs):
                return completed(argv, stdout='{"sevenDay": 0, "fetchFailed": true}')

            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.fetch_usage_snapshot(config, repo_root=root, runner=failed_payload_runner)

    def test_fetch_usage_oauth_path_reads_keychain_and_usage_api(self):
        with tempfile.TemporaryDirectory() as temp:
            original_cache = fetch_usage.TOKEN_CACHE
            fetch_usage.TOKEN_CACHE = Path(temp) / "token-cache"
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append(argv)
                if argv[:3] == ["security", "find-generic-password", "-s"]:
                    return completed(argv, stdout='{"claudeAiOauth":{"accessToken":"token-123"}}')
                if argv and argv[0] == "curl":
                    self.assertIn("authorization: Bearer token-123", argv)
                    return completed(argv, stdout='{"seven_day":{"utilization":37}}')
                return completed(argv, returncode=99, stderr="unexpected")

            try:
                usage = fetch_usage.fetch_oauth_usage(runner=fake_runner)
            finally:
                fetch_usage.TOKEN_CACHE = original_cache

            self.assertEqual(usage, {"sevenDay": 37.0})
            self.assertEqual(calls[0][0], "security")
            self.assertEqual(calls[1][0], "curl")


class PathSafetyTests(unittest.TestCase):
    def test_relative_parent_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            root.mkdir()

            with self.assertRaises(PathSafetyError):
                artifact_path(root, "../escape.json")

    def test_absolute_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            outside = Path(temp) / "outside.json"
            root.mkdir()

            with self.assertRaises(PathSafetyError):
                ensure_contained(root, outside)

    def test_absolute_path_inside_root_is_allowed_for_config_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            root.mkdir()
            inside = root / "run-config.json"

            self.assertEqual(ensure_contained(root, inside), inside.resolve())

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            outside = Path(temp) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(PathSafetyError):
                artifact_path(root, "link/escape.json")


if __name__ == "__main__":
    unittest.main()
