#!/usr/bin/env python3
"""Poll and close sextant-optimize workers."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

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

    diff_status = capture_post_run_diff_status(config, runner=runner)
    if final_status in {"succeeded", "failed", "blocked"} and diff_status["dirty"]:
        final_status = "invalidatedByDiff"
        summary = "post-run git status is dirty despite read-only worker scope"
        errors.append(summary)

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
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    repos = {
        "tool": canonical_path(config["tool"].get("repoPath", ".")),
        "target": canonical_path(config["target"]["codebasePath"]),
    }
    result = {"dirty": False, "repos": {}}
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
        repo_result = {
            "path": str(repo_path),
            "returncode": status.returncode,
            "statusPorcelain": lines,
            "failed": status.returncode != 0,
        }
        if lines:
            result["dirty"] = True
        result["repos"][name] = repo_result
    return result
