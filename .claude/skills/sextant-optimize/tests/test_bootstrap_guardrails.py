import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
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

    def test_prerequisite_command_failure_names_command_and_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)

            def failing_runner(argv, **kwargs):
                if argv == ["swift", "--version"]:
                    return completed(argv, returncode=1, stderr="swift broken")
                if argv == ["cc-session-tool", "--help"]:
                    raise subprocess.TimeoutExpired(argv, 120)
                return completed(argv)

            with self.assertRaises(bootstrap.PrerequisiteError) as context:
                bootstrap.check_prerequisites(
                    config,
                    which=lambda name: f"/bin/{name}",
                    runner=failing_runner,
                    env={"CMUX_WORKSPACE_ID": "workspace:1"},
                )

            missing = context.exception.missing
            self.assertIn("swift --version (exit 1)", missing)
            self.assertTrue(
                any("cc-session-tool --help" in entry and "TimeoutExpired" in entry for entry in missing)
            )

    def test_prerequisites_treat_cmux_claude_backend_like_cmux(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            config["workers"]["backend"] = "cmux_claude"

            with self.assertRaises(bootstrap.PrerequisiteError) as context:
                bootstrap.check_prerequisites(
                    config,
                    which=lambda name: None if name == "cmux" else f"/bin/{name}",
                    runner=lambda argv, **kwargs: completed(argv),
                    env={"CMUX_WORKSPACE_ID": "workspace:1"},
                )
            self.assertEqual(context.exception.missing, ["cmux"])

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
            self.assertIn(["cmux", "version"], calls)

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

            stderr = StringIO()
            with redirect_stderr(stderr):
                usage = bootstrap.fetch_usage_snapshot(config, repo_root=root, runner=failing_runner)

            self.assertTrue(usage["fetchFailed"])
            self.assertIsNone(usage["initialSevenDay"])
            self.assertEqual(usage["budgetPercent"], 25)
            self.assertIn("optional usage fetch failed", stderr.getvalue())

    def test_usage_fetch_optional_invalid_payload_warns_and_degrades(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root, root)
            config["usage"]["required"] = False

            def invalid_payload_runner(argv, **kwargs):
                return completed(argv, stdout="not json")

            stderr = StringIO()
            with redirect_stderr(stderr):
                usage = bootstrap.fetch_usage_snapshot(config, repo_root=root, runner=invalid_payload_runner)

            self.assertTrue(usage["fetchFailed"])
            self.assertIn("invalid payload", stderr.getvalue())

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

    def test_parse_usage_payload_extracts_optional_five_hour_window(self):
        payload = {
            "seven_day": {
                "utilization": 4.0,
                "resets_at": "2026-06-10T16:59:59.930251+00:00",
            },
            "five_hour": {
                "utilization": 27.0,
                "resets_at": "2026-06-10T02:49:59.930229+00:00",
            },
        }

        snapshot = fetch_usage.parse_usage_payload(payload)

        self.assertEqual(snapshot["sevenDay"], 4.0)
        self.assertEqual(snapshot["fiveHour"], 27.0)
        self.assertEqual(snapshot["fiveHourResetsAt"], "2026-06-10T02:49:59.930229+00:00")

    def test_parse_usage_payload_without_five_hour_keeps_seven_day_only(self):
        payload = {
            "seven_day": {
                "utilization": 12.5,
            },
        }

        snapshot = fetch_usage.parse_usage_payload(payload)

        self.assertEqual(snapshot["sevenDay"], 12.5)
        self.assertNotIn("fiveHour", snapshot)
        self.assertNotIn("fiveHourResetsAt", snapshot)

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
                    self.assertTrue(all("token-123" not in arg for arg in argv))
                    header_args = [arg for arg in argv if arg.startswith("@")]
                    self.assertEqual(len(header_args), 1)
                    header_file = Path(header_args[0][1:])
                    self.assertEqual(
                        header_file.read_text(encoding="utf-8").strip(),
                        "authorization: Bearer token-123",
                    )
                    self.assertEqual(stat.S_IMODE(os.stat(header_file).st_mode), 0o600)
                    return completed(argv, stdout='{"seven_day":{"utilization":37}}')
                return completed(argv, returncode=99, stderr="unexpected")

            try:
                usage = fetch_usage.fetch_oauth_usage(runner=fake_runner)
            finally:
                fetch_usage.TOKEN_CACHE = original_cache

            self.assertEqual(usage, {"sevenDay": 37.0})
            self.assertEqual(calls[0][0], "security")
            self.assertEqual(calls[1][0], "curl")

    def test_token_cache_respects_ttl_permissions_and_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            original_cache = fetch_usage.TOKEN_CACHE
            fetch_usage.TOKEN_CACHE = Path(temp) / "token-cache"
            try:
                fetch_usage._write_cached_token("token-abc")
                self.assertEqual(stat.S_IMODE(os.stat(fetch_usage.TOKEN_CACHE).st_mode), 0o600)
                mtime = os.stat(fetch_usage.TOKEN_CACHE).st_mtime

                self.assertEqual(fetch_usage._read_cached_token(now=mtime + 1), "token-abc")
                self.assertIsNone(
                    fetch_usage._read_cached_token(now=mtime + fetch_usage.TOKEN_TTL_SECONDS + 1)
                )

                os.chmod(fetch_usage.TOKEN_CACHE, 0o644)
                self.assertIsNone(fetch_usage._read_cached_token(now=mtime + 1))
                os.chmod(fetch_usage.TOKEN_CACHE, 0o600)

                fetch_usage.TOKEN_CACHE.write_text("", encoding="utf-8")
                self.assertIsNone(fetch_usage._read_cached_token())
            finally:
                fetch_usage.TOKEN_CACHE = original_cache

    def test_fetch_usage_oauth_failure_modes_raise_detailed_errors(self):
        keychain_ok = '{"claudeAiOauth":{"accessToken":"token-123"}}'

        def runner_for(keychain=None, curl=None):
            def run(argv, **kwargs):
                if argv[:3] == ["security", "find-generic-password", "-s"]:
                    if keychain is not None:
                        return keychain(argv)
                    return completed(argv, stdout=keychain_ok)
                if argv and argv[0] == "curl":
                    if curl is None:
                        raise AssertionError("curl should not run for this case")
                    return curl(argv)
                return completed(argv, returncode=99, stderr="unexpected")

            return run

        cases = [
            (
                "keychain read fails",
                runner_for(keychain=lambda argv: completed(argv, returncode=1, stderr="locked")),
                "could not read Claude Code credentials",
                False,
            ),
            (
                "keychain payload is not JSON",
                runner_for(keychain=lambda argv: completed(argv, stdout="not json")),
                "credentials are not JSON",
                False,
            ),
            (
                "keychain payload is missing the token",
                runner_for(keychain=lambda argv: completed(argv, stdout='{"claudeAiOauth":{}}')),
                "could not extract OAuth token",
                False,
            ),
            (
                "keychain token is empty",
                runner_for(keychain=lambda argv: completed(argv, stdout='{"claudeAiOauth":{"accessToken":""}}')),
                "could not extract OAuth token",
                False,
            ),
            (
                "curl exits nonzero",
                runner_for(curl=lambda argv: completed(argv, returncode=7, stderr="connection refused")),
                "curl exit 7: connection refused",
                True,
            ),
            (
                "usage response is not JSON",
                runner_for(curl=lambda argv: completed(argv, stdout="<html>unauthorized</html>")),
                "invalid usage payload",
                False,
            ),
            (
                "usage response is missing sevenDay",
                runner_for(curl=lambda argv: completed(argv, stdout='{"unexpected": true}')),
                "invalid usage payload",
                False,
            ),
        ]

        for label, runner, expected, cache_kept in cases:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as temp:
                    original_cache = fetch_usage.TOKEN_CACHE
                    fetch_usage.TOKEN_CACHE = Path(temp) / "token-cache"
                    try:
                        with self.assertRaisesRegex(ValueError, expected):
                            fetch_usage.fetch_oauth_usage(runner=runner)
                        self.assertEqual(fetch_usage.TOKEN_CACHE.exists(), cache_kept)
                    finally:
                        fetch_usage.TOKEN_CACHE = original_cache


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
