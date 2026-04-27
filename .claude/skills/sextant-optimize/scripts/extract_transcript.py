#!/usr/bin/env python3
"""Bounded transcript extraction through cc-session-tool."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import session_ops
import state_ops
from path_safety import PathSafetyError, artifact_path, canonical_path


class TranscriptExtractionError(RuntimeError):
    pass


DEFAULT_MAX_FILE_REFERENCES = 80
DEFAULT_MAX_CONTENT_CHARS = 500


def bounded(items: list, maximum: int) -> tuple[list, bool]:
    return items[:maximum], len(items) > maximum


def transcript_config(config: dict) -> dict:
    values = config.get("transcripts", {})
    return {
        "maxToolCalls": int(values.get("maxToolCalls", 200)),
        "maxMessages": int(values.get("maxMessages", 80)),
        "maxFileReferences": int(values.get("maxFileReferences", DEFAULT_MAX_FILE_REFERENCES)),
        "maxSliceTurns": int(values.get("maxSliceTurns", 40)),
        "missingTranscriptPolicy": values.get("missingTranscriptPolicy", "retryThenStop"),
    }


def command_scope(transcript_ref: dict, config: dict) -> list[str]:
    claude_project = transcript_ref.get("claudeProject")
    if claude_project:
        return ["--claude-project", claude_project]
    return ["--project", config["target"]["codebasePath"]]


def run_cc(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess],
) -> dict:
    return session_ops.run_cc_session_json(command, runner=runner)


def extract_bounded_summary(
    *,
    config: dict,
    transcript_ref: dict,
    cc_session_tool: str = "cc-session-tool",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    limits = transcript_config(config)
    session_id = transcript_ref["sessionId"]
    if not session_ops.is_known_session_id(session_id):
        raise TranscriptExtractionError("cannot extract transcript without a discovered session id")

    scope = command_scope(transcript_ref, config)

    shape = run_cc([cc_session_tool, "shape", session_id, *scope], runner=runner)["data"]
    tools = run_cc([cc_session_tool, "tools", session_id, *scope], runner=runner)["data"]
    messages = run_cc(
        [
            cc_session_tool,
            "messages",
            session_id,
            *scope,
            "--max-content",
            str(DEFAULT_MAX_CONTENT_CHARS),
            "--max-tool-result",
            str(DEFAULT_MAX_CONTENT_CHARS),
        ],
        runner=runner,
    )["data"]
    files = run_cc([cc_session_tool, "files", session_id, *scope, "--group-by", "file"], runner=runner)["data"]

    total_turns = int(shape.get("summary", {}).get("total_turns") or 0)
    slice_end = min(total_turns, limits["maxSliceTurns"])
    if slice_end > 0:
        slice_payload = run_cc(
            [
                cc_session_tool,
                "slice",
                session_id,
                *scope,
                "--turn",
                f"1-{slice_end}",
                "--max-content",
                str(DEFAULT_MAX_CONTENT_CHARS),
            ],
            runner=runner,
        )["data"]
        slice_entries = slice_payload.get("entries", [])
    else:
        slice_entries = []

    tool_calls, tool_truncated = bounded(tools.get("tool_calls", []), limits["maxToolCalls"])
    message_rows, messages_truncated = bounded(messages.get("messages", []), limits["maxMessages"])
    file_rows, files_truncated = bounded(files.get("files", []), limits["maxFileReferences"])
    turn_slice_rows, slices_truncated = bounded(slice_entries, limits["maxSliceTurns"])

    return {
        "schemaVersion": 1,
        "status": "extracted",
        "session": {
            "role": transcript_ref.get("role"),
            "workerId": transcript_ref.get("workerId"),
            "backend": transcript_ref.get("backend"),
            "workspaceRef": transcript_ref.get("workspaceRef"),
            "claudeProject": transcript_ref.get("claudeProject"),
            "sessionId": session_id,
            "startedAt": transcript_ref.get("startedAt"),
            "completedAt": transcript_ref.get("completedAt"),
        },
        "limits": limits,
        "truncated": {
            "toolCalls": tool_truncated,
            "messages": messages_truncated,
            "fileReferences": files_truncated,
            "turnSlices": slices_truncated or total_turns > limits["maxSliceTurns"],
        },
        "shapeSummary": shape.get("summary", {}),
        "turns": shape.get("turns", [])[:limits["maxSliceTurns"]],
        "toolCalls": tool_calls,
        "messages": message_rows,
        "fileReferences": file_rows,
        "turnSlices": turn_slice_rows,
    }


def missing_transcript_summary(*, transcript_ref: dict, config: dict, attempts: int) -> dict:
    policy = transcript_config(config)["missingTranscriptPolicy"]
    if policy == "retryThenStop":
        status = "stopRequired"
        reason = "transcript identity was not discovered after retry attempts"
    elif policy == "markUnevaluable":
        status = "unevaluable"
        reason = "transcript identity was not discovered and policy marks this run unevaluable"
    else:
        raise TranscriptExtractionError(f"unsupported missing transcript policy: {policy}")

    return {
        "schemaVersion": 1,
        "status": status,
        "reason": reason,
        "attempts": attempts,
        "session": {
            "role": transcript_ref.get("role"),
            "workerId": transcript_ref.get("workerId"),
            "backend": transcript_ref.get("backend"),
            "workspaceRef": transcript_ref.get("workspaceRef"),
            "claudeProject": transcript_ref.get("claudeProject"),
            "sessionId": transcript_ref.get("sessionId"),
            "startedAt": transcript_ref.get("startedAt"),
            "completedAt": transcript_ref.get("completedAt"),
        },
    }


def discover_then_extract(
    *,
    config: dict,
    transcript_ref: dict,
    completed_at: str | None = None,
    cc_session_tool: str = "cc-session-tool",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[dict, dict]:
    attempts = 1 if transcript_config(config)["missingTranscriptPolicy"] == "markUnevaluable" else 2
    updated_ref = session_ops.update_transcript_ref(
        transcript_ref,
        completed_at=completed_at if completed_at is not None else transcript_ref.get("completedAt"),
    )

    identity = None
    for _ in range(attempts):
        identity = session_ops.discover_session_identity(
            transcript_ref=updated_ref,
            target_codebase_path=config["target"]["codebasePath"],
            cc_session_tool=cc_session_tool,
            runner=runner,
        )
        if identity:
            break

    if not identity:
        status = "missing"
        summary = missing_transcript_summary(transcript_ref=updated_ref, config=config, attempts=attempts)
        return session_ops.update_transcript_ref(updated_ref, status=status), summary

    discovered_ref = session_ops.update_transcript_ref(
        updated_ref,
        session_id=identity["sessionId"],
        claude_project=identity.get("claudeProject"),
        status="discovered",
    )
    return discovered_ref, extract_bounded_summary(
        config=config,
        transcript_ref=discovered_ref,
        cc_session_tool=cc_session_tool,
        runner=runner,
    )


def extract_for_paths(
    *,
    config_path: str | Path,
    transcript_ref_path: str | Path,
    summary_path: str | Path | None = None,
    completed_at: str | None = None,
    cc_session_tool: str = "cc-session-tool",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    transcript_path = Path(transcript_ref_path)
    transcript_ref = session_ops.load_transcript_ref(transcript_path)
    updated_ref, summary = discover_then_extract(
        config=config,
        transcript_ref=transcript_ref,
        completed_at=completed_at,
        cc_session_tool=cc_session_tool,
        runner=runner,
    )
    session_ops.write_transcript_ref(transcript_path, updated_ref)

    if summary_path is not None:
        Path(summary_path).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {"transcriptRef": updated_ref, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--transcript-ref", required=True)
    parser.add_argument("--summary")
    parser.add_argument("--completed-at")
    parser.add_argument("--cc-session-tool", default="cc-session-tool")
    args = parser.parse_args(argv)

    try:
        result = extract_for_paths(
            config_path=canonical_path(args.config),
            transcript_ref_path=canonical_path(args.transcript_ref),
            summary_path=artifact_path(Path(args.transcript_ref).resolve().parent, Path(args.summary).name)
            if args.summary
            else None,
            completed_at=args.completed_at or state_ops.utc_now(),
            cc_session_tool=args.cc_session_tool,
        )
    except (TranscriptExtractionError, session_ops.SessionError, PathSafetyError, OSError, json.JSONDecodeError) as error:
        print(f"transcript extraction failed: {error}", file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "status": result["summary"]["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
