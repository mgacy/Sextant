#!/usr/bin/env python3
"""Worker directory, prompt, signal, and artifact helpers."""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

import backend
import session_ops
import state_ops
from path_safety import PathSafetyError, artifact_path, canonical_path


class WorkerError(RuntimeError):
    pass


ROLE_TEMPLATES = {
    "tool-user": "tool-user.md",
    "friction-miner": "friction-miner.md",
    "evaluator": "evaluator.md",
    "opportunity-generator": "opportunity-generator.md",
    "critic": "critic.md",
}

ROLE_REQUIRED_ARTIFACTS = {
    "tool-user": ["report.md", "transcript-ref.json", "transcript-summary.json"],
    "friction-miner": ["friction-events.json", "report.md"],
    "evaluator": ["evaluation.md", "scorecard.json"],
    "opportunity-generator": ["candidates.md", "prioritized.json"],
    "critic": ["critique.md", "perturbation.md"],
}


def worker_id_for(role: str, iteration: int, ordinal: int = 1) -> str:
    return f"iteration-{iteration}-{role}-{ordinal:03d}"


def role_output_relpath(iteration: int, role: str) -> str:
    if role == "opportunity-generator":
        return f"iteration-{iteration}/opportunities"
    if role == "critic":
        return f"iteration-{iteration}/critique"
    return f"iteration-{iteration}/{role}"


def render_prompt(template_text: str, values: dict[str, object]) -> str:
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    if "{{" in rendered or "}}" in rendered:
        raise WorkerError("prompt template contains unresolved placeholders")
    return rendered


def prompt_values_for(run_root: Path, config: dict, iteration: int, task: dict) -> dict[str, object]:
    iteration_root = f"iteration-{iteration}"
    return {
        "RUN_DIR": str(run_root),
        "ITERATION": iteration,
        "TASK_ID": task.get("id", ""),
        "TASK_PROMPT": task.get("prompt", ""),
        "TARGET_CODEBASE_PATH": config.get("target", {}).get("codebasePath", ""),
        "TARGET_SWIFT_PATH": config.get("target", {}).get("swiftPath", ""),
        "TOOL_USER_REPORT": f"{iteration_root}/tool-user/report.md",
        "TRANSCRIPT_SUMMARY": f"{iteration_root}/tool-user/transcript-summary.json",
        "FRICTION_EVENTS_SCHEMA": "schemas/friction-events.schema.json",
        "TASK_CORPUS": config.get("taskCorpusPath", ""),
        "FRICTION_EVENTS": f"{iteration_root}/friction-miner/friction-events.json",
        "SCORECARD_SCHEMA": "schemas/scorecard.schema.json",
        "SCORECARD": f"{iteration_root}/evaluator/scorecard.json",
        "OPPORTUNITIES_SCHEMA": "schemas/opportunities.schema.json",
        "OPPORTUNITIES": f"{iteration_root}/opportunities/prioritized.json",
    }


def prepare_worker(
    *,
    run_dir: str | Path,
    config: dict,
    role: str,
    iteration: int,
    task: dict,
    now: str | None = None,
) -> dict:
    if role not in ROLE_TEMPLATES:
        raise WorkerError(f"unsupported worker role: {role}")

    timestamp = now or state_ops.utc_now()
    run_root = canonical_path(run_dir)
    output_rel = role_output_relpath(iteration, role)
    output_dir = artifact_path(run_root, output_rel)
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = artifact_path(run_root, f"{output_rel}/prompt.md")
    signal_path = artifact_path(run_root, f"{output_rel}/completion-signal.json")
    worker_ref_path = artifact_path(run_root, f"{output_rel}/worker-ref.json")
    screen_path = artifact_path(run_root, f"{output_rel}/screen.log")
    transcript_ref_path = artifact_path(run_root, f"{output_rel}/transcript-ref.json")

    template_path = Path(__file__).resolve().parents[1] / "templates" / ROLE_TEMPLATES[role]
    prompt = render_prompt(
        template_path.read_text(encoding="utf-8"),
        prompt_values_for(run_root, config, iteration, task),
    )
    prompt_path.write_text(prompt, encoding="utf-8")

    worker_id = worker_id_for(role, iteration)
    backend_name = config.get("workers", {}).get("backend")
    if backend_name == "cmux":
        backend_name = "cmux_claude"
    worker_ref = {
        "workerId": worker_id,
        "role": role,
        "backend": backend_name,
        "cwd": str(canonical_path(config["target"]["codebasePath"])),
        "outputDir": str(output_dir),
        "outputRelPath": output_rel,
        "promptPath": str(prompt_path),
        "signalPath": str(signal_path),
        "workerRefPath": str(worker_ref_path),
        "screenPath": str(screen_path),
        "transcriptRefPath": str(transcript_ref_path),
        "startedAt": timestamp,
        "status": "prepared",
    }
    write_json(worker_ref_path, worker_ref)

    transcript_ref = session_ops.initial_transcript_ref(
        role=role,
        worker_id=worker_id,
        backend=backend_name,
        workspace_ref=None,
        claude_project=config.get("target", {}).get("transcriptProjectHint", ""),
        started_at=timestamp,
    )
    write_json(transcript_ref_path, transcript_ref)
    return worker_ref


def launch_worker(
    *,
    run_dir: str | Path,
    config: dict,
    role: str,
    iteration: int,
    task: dict,
    expected_revision: int,
    worker_backend: backend.WorkerBackend,
    now: str | None = None,
) -> dict:
    worker_ref = prepare_worker(run_dir=run_dir, config=config, role=role, iteration=iteration, task=task, now=now)
    prepared_state = state_ops.record_worker_update(
        run_dir,
        expected_revision=expected_revision,
        worker={**serializable_worker_ref(worker_ref), "status": "prepared"},
        now=now,
    )
    launched = worker_backend.create_worker(worker_ref)
    launched["status"] = "launched"
    write_json(Path(worker_ref["workerRefPath"]), launched)
    if launched.get("workspaceRef"):
        update_transcript_workspace(Path(worker_ref["transcriptRefPath"]), launched["workspaceRef"])
    state_ops.record_worker_update(
        run_dir,
        expected_revision=prepared_state["revision"],
        worker={**serializable_worker_ref(launched), "status": "launched"},
        now=now,
    )
    return launched


def read_completion_signal(run_dir: str | Path, worker_ref: dict) -> dict | None:
    signal_path = Path(worker_ref["signalPath"])
    if not signal_path.exists():
        return None
    try:
        payload = json.loads(signal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkerError(f"worker completion signal is invalid JSON: {error}") from error
    validate_completion_signal(run_dir, worker_ref, payload)
    return payload


def validate_completion_signal(run_dir: str | Path, worker_ref: dict, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise WorkerError("worker completion signal must be an object")
    if payload.get("role") != worker_ref["role"]:
        raise WorkerError("worker completion role does not match worker ref")
    if payload.get("status") not in {"succeeded", "failed", "blocked"}:
        raise WorkerError("worker completion status must be succeeded, failed, or blocked")
    if not isinstance(payload.get("summary"), str) or not payload["summary"]:
        raise WorkerError("worker completion summary is required")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not all(isinstance(item, str) and item for item in artifacts):
        raise WorkerError("worker completion artifacts must be an array of non-empty strings")
    transcript_ref = payload.get("transcriptRef")
    if transcript_ref is not None and not isinstance(transcript_ref, str):
        raise WorkerError("worker completion transcriptRef must be a string or null")
    paths = artifacts + ([transcript_ref] if transcript_ref else [])
    for relpath in paths:
        try:
            resolved = artifact_path(run_dir, relpath)
        except PathSafetyError as error:
            raise WorkerError(f"worker completion artifact escapes run dir: {relpath}") from error
        if not resolved.is_file():
            raise WorkerError(f"worker completion artifact does not exist: {relpath}")

    if payload["status"] == "succeeded":
        output_rel = worker_ref["outputRelPath"]
        required = {f"{output_rel}/{name}" for name in ROLE_REQUIRED_ARTIFACTS[worker_ref["role"]]}
        present = set(artifacts)
        missing = sorted(required - present)
        if missing:
            raise WorkerError(f"worker completion is missing required artifacts: {missing}")
        if transcript_ref and transcript_ref not in present:
            raise WorkerError("worker completion transcriptRef must also be listed in artifacts")


def serializable_worker_ref(worker_ref: dict) -> dict:
    serializable = {}
    for key, value in worker_ref.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            serializable[key] = value
        elif isinstance(value, list):
            serializable[key] = value
    return serializable


def update_transcript_workspace(transcript_ref_path: Path, workspace_ref: str) -> None:
    transcript_ref = json.loads(transcript_ref_path.read_text(encoding="utf-8"))
    transcript_ref["workspaceRef"] = workspace_ref
    write_json(transcript_ref_path, transcript_ref)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--iteration", required=True, type=int)
    parser.add_argument("--task", required=True)
    parser.add_argument("--expect-revision", type=int)
    parser.add_argument("--dry-run", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    subparsers.add_parser("launch")
    args = parser.parse_args(argv)

    try:
        config = load_json(args.config)
        task = load_json(args.task)
        if args.command == "prepare":
            result = prepare_worker(
                run_dir=args.run,
                config=config,
                role=args.role,
                iteration=args.iteration,
                task=task,
            )
        else:
            if args.expect_revision is None:
                raise WorkerError("--expect-revision is required for launch")
            worker_backend = backend.backend_from_config(config, dry_run=args.dry_run)
            result = launch_worker(
                run_dir=args.run,
                config=config,
                role=args.role,
                iteration=args.iteration,
                task=task,
                expected_revision=args.expect_revision,
                worker_backend=worker_backend,
            )
    except (WorkerError, state_ops.StateError, PathSafetyError, OSError, json.JSONDecodeError, backend.BackendError) as error:
        print(f"worker operation failed: {error}", file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "worker": serializable_worker_ref(result)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
