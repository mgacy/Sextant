#!/usr/bin/env python3
"""Poll and close sextant-optimize workers."""

from __future__ import annotations

import subprocess
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import json

import backend
import state_ops
import worker_ops
from path_safety import canonical_path


class PollError(RuntimeError):
    pass


def parse_utc(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def poll_worker(
    *,
    run_dir: str | Path,
    config: dict,
    worker_ref: dict,
    expected_revision: int,
    worker_backend: backend.WorkerBackend,
    now: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    timestamp = now or state_ops.utc_now()
    timeout_seconds = int(config.get("workers", {}).get("sessionTimeoutSeconds", 3600))
    elapsed = (parse_utc(timestamp) - parse_utc(worker_ref["startedAt"])).total_seconds()

    signal_payload = None
    final_status = None
    summary = None
    errors: list[str] = []

    if elapsed > timeout_seconds:
        final_status = "timedOut"
        summary = f"worker exceeded timeout of {timeout_seconds} seconds"
    else:
        try:
            signal_payload = worker_ops.read_completion_signal(run_dir, worker_ref)
        except worker_ops.WorkerError as error:
            final_status = "invalidSignal"
            summary = str(error)
            errors.append(str(error))

    backend_status = worker_backend.poll_worker(worker_ref)
    if final_status is None and signal_payload is not None:
        final_status = signal_payload["status"]
        summary = signal_payload["summary"]
    elif final_status is None and backend_status.status in {"failed", "unknown"}:
        final_status = backend_status.status
        summary = backend_status.summary
    elif final_status is None:
        final_status = backend_status.status
        summary = backend_status.summary

    close_update = None
    if final_status == "timedOut":
        close_result = worker_backend.close_worker(worker_ref)
        close_update = {
            "closed": close_result.closed,
            "status": close_result.status,
            "exitCode": close_result.exit_code,
        }
        if not close_result.closed:
            errors.append(f"timed-out worker close failed: {close_result.status}")

    diff_status = capture_post_run_diff_status(config, run_dir=run_dir, runner=runner)
    if final_status in {"succeeded", "failed", "blocked"} and diff_status["dirty"]:
        final_status = "invalidatedByDiff"
        summary = "post-run git status is dirty despite read-only worker scope"
        errors.append(summary)
    if diff_status.get("failed"):
        if final_status in {"succeeded", "failed", "blocked"}:
            final_status = "invalidatedByDiff"
            summary = "post-run git status failed during read-only worker verification"
        errors.append("post-run git status failed")

    update = {
        "workerId": worker_ref["workerId"],
        "role": worker_ref["role"],
        "backend": worker_ref["backend"],
        "status": final_status,
        "summary": summary,
        "exitCode": backend_status.exit_code,
        "polledAt": timestamp,
        "artifacts": signal_payload.get("artifacts", []) if signal_payload else [],
        "transcriptRef": signal_payload.get("transcriptRef") if signal_payload else None,
        "diffStatus": diff_status,
        "closeResult": close_update,
        "errors": errors,
    }
    state = state_ops.record_worker_update(
        run_dir,
        expected_revision=expected_revision,
        worker=update,
        now=timestamp,
    )
    return {"state": state, "worker": update}


def close_worker(
    *,
    run_dir: str | Path,
    worker_ref: dict,
    expected_revision: int,
    worker_backend: backend.WorkerBackend,
    now: str | None = None,
) -> dict:
    timestamp = now or state_ops.utc_now()
    close_result = worker_backend.close_worker(worker_ref)
    update = {
        "workerId": worker_ref["workerId"],
        "role": worker_ref["role"],
        "backend": worker_ref["backend"],
        "status": close_result.status,
        "exitCode": close_result.exit_code,
        "closed": close_result.closed,
        "closedAt": timestamp,
    }
    state = state_ops.record_worker_update(
        run_dir,
        expected_revision=expected_revision,
        worker=update,
        now=timestamp,
    )
    return {"state": state, "worker": update}


def capture_post_run_diff_status(
    config: dict,
    *,
    run_dir: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    repos = {
        "tool": canonical_path(config["tool"].get("repoPath", ".")),
        "target": canonical_path(config["target"]["codebasePath"]),
    }
    result = {"dirty": False, "failed": False, "repos": {}}
    baseline = _load_baseline_status(run_dir)
    for name, repo_path in repos.items():
        status = runner(
            ["git", "status", "--porcelain"],
            cwd=str(repo_path),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        lines = status.stdout.splitlines() if status.returncode == 0 else []
        baseline_lines = set(baseline.get(name, {}).get("statusPorcelain", []))
        changed_lines = [
            line
            for line in lines
            if line not in baseline_lines and not _is_allowed_run_artifact_status(line, repo_path, config)
        ]
        repo_result = {
            "path": str(repo_path),
            "returncode": status.returncode,
            "statusPorcelain": lines,
            "baselineStatusPorcelain": sorted(baseline_lines),
            "changedStatusPorcelain": changed_lines,
            "failed": status.returncode != 0,
        }
        if changed_lines:
            result["dirty"] = True
        if status.returncode != 0:
            result["failed"] = True
        result["repos"][name] = repo_result
    return result


def _load_baseline_status(run_dir: str | Path) -> dict:
    path = Path(run_dir) / "git-status.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _status_path(line: str) -> str:
    body = line[3:] if len(line) > 3 else ""
    if " -> " in body:
        body = body.split(" -> ", 1)[1]
    return body.strip()


def _is_allowed_run_artifact_status(line: str, repo_path: Path, config: dict) -> bool:
    rel = _status_path(line)
    if not rel:
        return False
    artifact_root = config.get("scope", {}).get("allowedArtifactRoot")
    tool_repo = canonical_path(config["tool"].get("repoPath", "."))
    if repo_path != tool_repo or not artifact_root:
        return False
    normalized = rel.replace("\\", "/")
    return normalized == artifact_root or normalized.startswith(artifact_root.rstrip("/") + "/")


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--worker-ref", required=True)
    parser.add_argument("--expect-revision", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("poll")
    subparsers.add_parser("close")
    args = parser.parse_args(argv)

    try:
        config = load_json(args.config)
        worker_ref = load_json(args.worker_ref)
        worker_backend = backend.backend_from_config(config, dry_run=args.dry_run)
        if args.command == "poll":
            result = poll_worker(
                run_dir=args.run,
                config=config,
                worker_ref=worker_ref,
                expected_revision=args.expect_revision,
                worker_backend=worker_backend,
            )
        else:
            result = close_worker(
                run_dir=args.run,
                worker_ref=worker_ref,
                expected_revision=args.expect_revision,
                worker_backend=worker_backend,
            )
    except (PollError, backend.BackendError, worker_ops.WorkerError, state_ops.StateError, OSError, json.JSONDecodeError) as error:
        print(f"poll operation failed: {error}", file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
