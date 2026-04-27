#!/usr/bin/env python3
"""cmux/Claude session command helpers for sextant-optimize workers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CmuxClaudeCommand:
    argv: list[str]
    workspace_ref: str


def build_cmux_claude_command(
    *,
    worker_id: str,
    cwd: str | Path,
    prompt_path: str | Path,
    output_dir: str | Path,
) -> CmuxClaudeCommand:
    """Build the argv-only command used to launch a Claude worker in cmux.

    The command is intentionally constructed without a shell and returned for
    dry-run tests. The worker lifecycle code decides whether to execute it.
    """

    workspace_ref = f"cmux:{worker_id}"
    argv = [
        "cmux",
        "new",
        "--name",
        worker_id,
        "--cwd",
        str(cwd),
        "--",
        "claude",
        "--file",
        str(prompt_path),
    ]
    return CmuxClaudeCommand(argv=argv, workspace_ref=workspace_ref)


def initial_transcript_ref(
    *,
    role: str,
    worker_id: str,
    backend: str,
    workspace_ref: str | None,
    claude_project: str,
    started_at: str,
) -> dict:
    return {
        "role": role,
        "workerId": worker_id,
        "backend": backend,
        "workspaceRef": workspace_ref,
        "claudeProject": claude_project,
        "sessionId": "unknown-until-discovered",
        "startedAt": started_at,
        "completedAt": None,
        "status": "pending",
    }


def is_known_session_id(session_id: str | None) -> bool:
    return bool(session_id and session_id != "unknown-until-discovered")


def update_transcript_ref(
    transcript_ref: dict,
    *,
    session_id: str | None = None,
    claude_project: str | None = None,
    completed_at: str | None = None,
    status: str | None = None,
) -> dict:
    updated = dict(transcript_ref)
    if session_id:
        updated["sessionId"] = session_id
    if claude_project:
        updated["claudeProject"] = claude_project
    if completed_at is not None:
        updated["completedAt"] = completed_at
    if status:
        updated["status"] = status
    return updated


def write_transcript_ref(path: str | Path, transcript_ref: dict) -> None:
    Path(path).write_text(json.dumps(transcript_ref, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_transcript_ref(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cc_session_scope_args(*, claude_project: str | None = None, project_path: str | Path | None = None) -> list[str]:
    if claude_project:
        return ["--claude-project", claude_project]
    if project_path:
        return ["--project", str(project_path)]
    return []


def run_cc_session_json(
    argv: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    completed = runner(
        argv,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise SessionError(f"cc-session-tool failed: {message}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SessionError(f"cc-session-tool returned invalid JSON: {error}") from error
    if payload.get("ok") is not True:
        raise SessionError(f"cc-session-tool returned unsuccessful response: {payload}")
    return payload


def session_from_list_row(row: dict, fallback_project: str | None = None) -> dict:
    session_id = row.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise SessionError("cc-session-tool list row is missing session_id")
    session_ref = row.get("session_ref") if isinstance(row.get("session_ref"), dict) else {}
    project = session_ref.get("project") or row.get("project") or fallback_project
    return {"sessionId": session_id, "claudeProject": project}


def discover_session_identity(
    *,
    transcript_ref: dict,
    target_codebase_path: str | Path,
    cc_session_tool: str = "cc-session-tool",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict | None:
    if is_known_session_id(transcript_ref.get("sessionId")):
        return {
            "sessionId": transcript_ref["sessionId"],
            "claudeProject": transcript_ref.get("claudeProject"),
        }

    started_at = transcript_ref.get("startedAt")
    completed_at = transcript_ref.get("completedAt")
    list_args = [cc_session_tool, "list", "--after", started_at, "--last", "5"]
    if completed_at:
        list_args.extend(["--before", completed_at])

    scoped = run_cc_session_json(
        [*list_args, "--project", str(target_codebase_path)],
        runner=runner,
    )
    scoped_rows = scoped.get("data") if isinstance(scoped.get("data"), list) else []
    if scoped_rows:
        return session_from_list_row(scoped_rows[0], transcript_ref.get("claudeProject"))

    claude_project = transcript_ref.get("claudeProject")
    if claude_project:
        broad = run_cc_session_json(
            [*list_args, "--all-projects", "--project-glob", claude_project],
            runner=runner,
        )
        broad_rows = broad.get("data") if isinstance(broad.get("data"), list) else []
        if broad_rows:
            return session_from_list_row(broad_rows[0], claude_project)

    return None
