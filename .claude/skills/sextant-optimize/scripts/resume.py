#!/usr/bin/env python3
"""Resume a sextant-optimize run after an external tool change."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

import bootstrap
import state_ops
from path_safety import PathSafetyError, artifact_path, canonical_path, ensure_contained


class ResumeError(RuntimeError):
    pass


class NoExternalChangeError(ResumeError):
    pass


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def run_dir_for(repo_root: Path, run_id: str) -> Path:
    artifact_root = ensure_contained(repo_root, ".claude-tracking/tool-eval-runs")
    return ensure_contained(artifact_root, run_id)


def has_external_change(previous_tool_state: dict, recaptured_tool_state: dict) -> bool:
    keys = ("gitCommit", "version", "smokeTestPassed")
    return any(previous_tool_state.get(key) != recaptured_tool_state.get(key) for key in keys)


def resume_after_external_change(
    run_dir: Path,
    *,
    repo_root: Path,
    external_change_ref: str,
    runner: Callable[..., object] = bootstrap.subprocess.run,
) -> dict:
    run_dir = canonical_path(run_dir)
    config = load_json(artifact_path(run_dir, "run-config.json"))
    state = state_ops.read_state(run_dir)
    if state.get("status") != "waitingForExternalChange":
        raise ResumeError("resume requires waitingForExternalChange state")

    recaptured_tool_state, git_status = bootstrap.capture_tool_state(config, repo_root=repo_root, runner=runner)
    previous_tool_state = state["toolState"]
    if not has_external_change(previous_tool_state, recaptured_tool_state):
        raise NoExternalChangeError("no external tool-state change detected")

    next_iteration = int(state["currentIteration"]) + 1
    iteration_dir = artifact_path(run_dir, f"iteration-{next_iteration}")
    iteration_dir.mkdir(parents=False, exist_ok=False)
    artifact_path(run_dir, f"iteration-{next_iteration}/git-status.json").write_text(
        json.dumps(git_status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    external_change = {
        "ref": external_change_ref,
        "previousToolState": previous_tool_state,
        "recapturedToolState": recaptured_tool_state,
    }
    ready_state = state_ops.mark_ready_for_rerun(
        run_dir,
        expected_revision=state["revision"],
        external_change=external_change,
    )
    running_state = state_ops.start_rerun(
        run_dir,
        expected_revision=ready_state["revision"],
        tool_state=recaptured_tool_state,
    )
    return {
        "state": running_state,
        "iterationDir": str(iteration_dir),
        "gitStatusPath": str(artifact_path(run_dir, f"iteration-{next_iteration}/git-status.json")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run")
    target.add_argument("--run-id")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--external-change-ref", required=True)
    args = parser.parse_args(argv)

    repo_root = canonical_path(args.repo_root)
    run_dir = canonical_path(args.run) if args.run else run_dir_for(repo_root, args.run_id)
    try:
        result = resume_after_external_change(
            run_dir,
            repo_root=repo_root,
            external_change_ref=args.external_change_ref,
        )
    except NoExternalChangeError as error:
        print(json.dumps({"ok": False, "reason": "no_external_change", "message": str(error)}, sort_keys=True))
        return 3
    except (
        ResumeError,
        state_ops.StateError,
        bootstrap.BootstrapError,
        PathSafetyError,
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(f"resume failed: {error}", file=sys.stderr)
        return 2

    state = result["state"]
    print(
        json.dumps(
            {
                "ok": True,
                "status": state["status"],
                "revision": state["revision"],
                "currentIteration": state["currentIteration"],
                "iterationDir": result["iterationDir"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
