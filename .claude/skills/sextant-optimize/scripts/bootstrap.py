#!/usr/bin/env python3
"""Bootstrap a sextant-optimize run directory and initial state."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from path_safety import PathSafetyError, canonical_path, ensure_contained


COMMAND_FIELDS = (
    ("tool", "versionCommand"),
    ("tool", "smokeTestCommand"),
    ("usage", "fetchCommand"),
    ("transcripts", "extractCommand"),
)


class BootstrapError(RuntimeError):
    pass


class ConfigError(BootstrapError):
    pass


class PrerequisiteError(BootstrapError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("missing prerequisites: " + ", ".join(missing))
        self.missing = missing


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_command(command: object, dotted_path: str) -> list[str]:
    if isinstance(command, str):
        raise ConfigError(f"{dotted_path} must be an argv array, not a shell string")
    if not isinstance(command, list) or not command:
        raise ConfigError(f"{dotted_path} must be a non-empty argv array")
    if not all(isinstance(part, str) and part for part in command):
        raise ConfigError(f"{dotted_path} must contain only non-empty strings")
    executable = Path(command[0]).name
    if executable in {"sh", "bash", "zsh", "fish"} and "-c" in command[1:]:
        raise ConfigError(f"{dotted_path} must not invoke a shell")
    return command


def validate_config(config: dict) -> None:
    for section, key in COMMAND_FIELDS:
        validate_command(config.get(section, {}).get(key), f"{section}.{key}")

    scope = config.get("scope", {})
    if scope.get("allowImplementation") is not False:
        raise ConfigError("scope.allowImplementation must be false for evaluation runs")
    if scope.get("allowDocsChanges") is not False:
        raise ConfigError("scope.allowDocsChanges must be false for evaluation runs")

    run_id = config.get("runId")
    if not isinstance(run_id, str) or not run_id or "/" in run_id or ".." in run_id:
        raise ConfigError("runId must be a non-empty path-safe string")

    target_path = config.get("target", {}).get("codebasePath")
    if not isinstance(target_path, str) or not Path(target_path).is_absolute():
        raise ConfigError("target.codebasePath must be an absolute path")


def check_prerequisites(
    config: dict,
    *,
    which: Callable[[str], str | None] = shutil.which,
    require_live_backend: bool = True,
) -> None:
    required = ["python3", "swift", "cc-session-tool"]
    workers = config.get("workers", {})
    if require_live_backend and workers.get("backend") == "cmux":
        required.append("cmux")
    if require_live_backend and workers.get("harness") == "claude":
        required.append("claude")

    missing = [tool for tool in required if which(tool) is None]
    if missing:
        raise PrerequisiteError(missing)

    try:
        json.dumps({"json": True})
    except Exception as error:
        raise PrerequisiteError([f"json support unavailable: {error}"]) from error


def run_command(
    argv: list[str],
    *,
    cwd: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    return runner(
        argv,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def git_capture(repo_path: Path, *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    commit = run_command(["git", "rev-parse", "HEAD"], cwd=repo_path, runner=runner)
    status = run_command(["git", "status", "--porcelain"], cwd=repo_path, runner=runner)
    return {
        "path": str(repo_path),
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "statusPorcelain": status.stdout.splitlines() if status.returncode == 0 else [],
        "commitCommandFailed": commit.returncode != 0,
        "statusCommandFailed": status.returncode != 0,
    }


def create_run_directory(config: dict, *, repo_root: Path) -> Path:
    artifact_root = ensure_contained(repo_root, config["scope"]["allowedArtifactRoot"])
    run_dir = ensure_contained(artifact_root, config["runId"])
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def capture_tool_state(
    config: dict,
    *,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[dict, dict]:
    tool_repo = ensure_contained(repo_root, config["tool"].get("repoPath", "."))
    target_repo = canonical_path(config["target"]["codebasePath"])

    version_result = run_command(config["tool"]["versionCommand"], cwd=tool_repo, runner=runner)
    smoke_result = run_command(config["tool"]["smokeTestCommand"], cwd=tool_repo, runner=runner)

    tool_git = git_capture(tool_repo, runner=runner)
    target_git = git_capture(target_repo, runner=runner)
    tool_state = {
        "gitCommit": tool_git["commit"] or "unknown",
        "version": version_result.stdout.strip() if version_result.returncode == 0 else None,
        "smokeTestPassed": smoke_result.returncode == 0,
    }
    git_status = {"tool": tool_git, "target": target_git}
    return tool_state, git_status


def fetch_usage_snapshot(
    config: dict,
    *,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    usage_config = config["usage"]
    result = run_command(usage_config["fetchCommand"], cwd=repo_root, runner=runner)
    if result.returncode != 0:
        if usage_config.get("required", False):
            raise BootstrapError("required usage fetch failed: " + (result.stderr.strip() or "unknown error"))
        return {
            "initialSevenDay": None,
            "latestSevenDay": None,
            "runDelta": None,
            "budgetPercent": usage_config["budgetPercent"],
            "fetchFailed": True,
        }

    try:
        payload = json.loads(result.stdout)
        usage = payload.get("usage", payload)
        seven_day = usage["sevenDay"]
    except Exception as error:
        if usage_config.get("required", False):
            raise BootstrapError(f"required usage fetch returned invalid JSON: {error}") from error
        return {
            "initialSevenDay": None,
            "latestSevenDay": None,
            "runDelta": None,
            "budgetPercent": usage_config["budgetPercent"],
            "fetchFailed": True,
        }

    return {
        "initialSevenDay": seven_day,
        "latestSevenDay": seven_day,
        "runDelta": 0,
        "budgetPercent": usage_config["budgetPercent"],
        "fetchFailed": False,
    }


def initial_state(config: dict, tool_state: dict, usage: dict, *, now: str) -> dict:
    return {
        "schemaVersion": 1,
        "runId": config["runId"],
        "status": "running",
        "currentIteration": 1,
        "revision": 1,
        "createdAt": now,
        "updatedAt": now,
        "toolState": tool_state,
        "usage": usage,
        "workers": [],
        "iterations": [],
        "decision": {"decision": "continue", "reasons": [], "nextPhase": "toolUser"},
        "errors": [],
    }


def bootstrap(config_path: Path, *, repo_root: Path, skip_prerequisites: bool = False) -> Path:
    config = load_json(config_path)
    validate_config(config)
    if not skip_prerequisites:
        check_prerequisites(config)
    run_dir = create_run_directory(config, repo_root=repo_root)
    tool_state, git_status = capture_tool_state(config, repo_root=repo_root)
    usage = fetch_usage_snapshot(config, repo_root=repo_root)
    now = utc_now()

    (run_dir / "run-config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    (run_dir / "git-status.json").write_text(json.dumps(git_status, indent=2, sort_keys=True) + "\n")
    (run_dir / "optimization-state.json").write_text(
        json.dumps(initial_state(config, tool_state, usage, now=now), indent=2, sort_keys=True) + "\n"
    )
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--skip-prerequisites", action="store_true")
    args = parser.parse_args(argv)

    try:
        run_dir = bootstrap(
            Path(args.config),
            repo_root=canonical_path(args.repo_root),
            skip_prerequisites=args.skip_prerequisites,
        )
    except (BootstrapError, PathSafetyError, OSError, json.JSONDecodeError) as error:
        print(f"bootstrap failed: {error}", file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "runDir": str(run_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
