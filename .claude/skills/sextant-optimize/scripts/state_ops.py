#!/usr/bin/env python3
"""Authoritative mutation helpers for sextant-optimize state."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from path_safety import PathSafetyError, artifact_path, canonical_path


STATE_FILE = "optimization-state.json"
LOCK_FILE = ".optimization-state.lock"

VALID_TRANSITIONS = {
    "running": {"handoffReady", "completed", "failed"},
    "handoffReady": {"waitingForExternalChange", "failed"},
    "waitingForExternalChange": {"readyForRerun", "failed"},
    "readyForRerun": {"running", "failed"},
    "completed": set(),
    "failed": set(),
}


class StateError(RuntimeError):
    pass


class StateLockError(StateError):
    pass


class RevisionMismatchError(StateError):
    pass


class InvalidTransitionError(StateError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_path(run_dir: str | Path) -> Path:
    return artifact_path(run_dir, STATE_FILE)


def read_state(run_dir: str | Path) -> dict:
    with state_path(run_dir).open(encoding="utf-8") as handle:
        return json.load(handle)


def initialize_state(run_dir: str | Path, state: dict) -> dict:
    run_root = canonical_path(run_dir)
    path = state_path(run_root)
    if path.exists():
        raise StateError(f"state already exists: {path}")
    payload = copy.deepcopy(state)
    payload.setdefault("revision", 1)
    payload.setdefault("updatedAt", payload.get("createdAt") or utc_now())
    with state_lock(run_root):
        if path.exists():
            raise StateError(f"state already exists: {path}")
        atomic_write_json(path, payload)
    return payload


@contextmanager
def state_lock(run_dir: str | Path):
    run_root = canonical_path(run_dir)
    lock_path = artifact_path(run_root, LOCK_FILE)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise StateLockError(f"state lock already held: {lock_path}") from error

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def _assert_revision(state: dict, expected_revision: int) -> None:
    actual = state.get("revision")
    if actual != expected_revision:
        raise RevisionMismatchError(f"expected revision {expected_revision}, found {actual}")


def _commit_mutation(
    run_dir: str | Path,
    *,
    expected_revision: int,
    mutator: Callable[[dict, str], None],
    now: str | None = None,
) -> dict:
    timestamp = now or utc_now()
    path = state_path(run_dir)
    with state_lock(run_dir):
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
        _assert_revision(state, expected_revision)

        next_state = copy.deepcopy(state)
        mutator(next_state, timestamp)
        next_state["revision"] = expected_revision + 1
        next_state["updatedAt"] = timestamp
        atomic_write_json(path, next_state)
        return next_state


def transition_status(
    run_dir: str | Path,
    *,
    expected_revision: int,
    new_status: str,
    now: str | None = None,
) -> dict:
    def mutate(state: dict, timestamp: str) -> None:
        current = state.get("status")
        if new_status not in VALID_TRANSITIONS.get(current, set()):
            raise InvalidTransitionError(f"invalid status transition: {current} -> {new_status}")
        state["status"] = new_status
        if new_status == "waitingForExternalChange":
            state.setdefault("decision", {})["nextPhase"] = None
            state.setdefault("errors", [])

    return _commit_mutation(run_dir, expected_revision=expected_revision, mutator=mutate, now=now)


def record_worker_update(
    run_dir: str | Path,
    *,
    expected_revision: int,
    worker: dict,
    now: str | None = None,
) -> dict:
    def mutate(state: dict, timestamp: str) -> None:
        if state.get("status") != "running":
            raise InvalidTransitionError("worker updates require running state")
        workers = state.setdefault("workers", [])
        workers.append({**worker, "recordedAt": timestamp})

    return _commit_mutation(run_dir, expected_revision=expected_revision, mutator=mutate, now=now)


def record_decision(
    run_dir: str | Path,
    *,
    expected_revision: int,
    decision: dict,
    now: str | None = None,
) -> dict:
    def mutate(state: dict, _timestamp: str) -> None:
        if state.get("status") != "running":
            raise InvalidTransitionError("decision updates require running state")
        if decision.get("decision") not in {"continue", "stop"}:
            raise StateError("decision.decision must be continue or stop")
        if not isinstance(decision.get("reasons"), list):
            raise StateError("decision.reasons must be an array")
        if "nextPhase" not in decision:
            raise StateError("decision.nextPhase is required")
        state["decision"] = copy.deepcopy(decision)

    return _commit_mutation(run_dir, expected_revision=expected_revision, mutator=mutate, now=now)


def record_iteration_result(
    run_dir: str | Path,
    *,
    expected_revision: int,
    iteration: int,
    scorecard_path: str,
    artifacts: list[str] | None = None,
    now: str | None = None,
) -> dict:
    def mutate(state: dict, timestamp: str) -> None:
        if state.get("status") != "running":
            raise InvalidTransitionError("iteration recording requires running state")
        if iteration != state.get("currentIteration"):
            raise StateError("can only record the current iteration")
        scorecard = artifact_path(run_dir, scorecard_path)
        if not scorecard.is_file():
            raise StateError(f"scorecard does not exist: {scorecard_path}")
        record = {
            "iteration": iteration,
            "scorecard": scorecard_path,
            "artifacts": artifacts or [],
            "recordedAt": timestamp,
        }
        state.setdefault("iterations", []).append(record)

    return _commit_mutation(run_dir, expected_revision=expected_revision, mutator=mutate, now=now)


def mark_ready_for_rerun(
    run_dir: str | Path,
    *,
    expected_revision: int,
    external_change: dict,
    now: str | None = None,
) -> dict:
    def mutate(state: dict, timestamp: str) -> None:
        current = state.get("status")
        if "readyForRerun" not in VALID_TRANSITIONS.get(current, set()):
            raise InvalidTransitionError(f"invalid status transition: {current} -> readyForRerun")
        next_iteration = int(state["currentIteration"]) + 1
        state["status"] = "readyForRerun"
        state.setdefault("iterations", []).append(
            {
                "iteration": next_iteration,
                "directory": f"iteration-{next_iteration}",
                "externalChange": {**external_change, "recordedAt": timestamp},
                "status": "readyForRerun",
            }
        )

    return _commit_mutation(run_dir, expected_revision=expected_revision, mutator=mutate, now=now)


def start_rerun(
    run_dir: str | Path,
    *,
    expected_revision: int,
    tool_state: dict,
    now: str | None = None,
) -> dict:
    def mutate(state: dict, timestamp: str) -> None:
        current = state.get("status")
        if "running" not in VALID_TRANSITIONS.get(current, set()):
            raise InvalidTransitionError(f"invalid status transition: {current} -> running")
        next_iteration = int(state["currentIteration"]) + 1
        pending = None
        for iteration_record in reversed(state.setdefault("iterations", [])):
            if iteration_record.get("iteration") == next_iteration and iteration_record.get("status") == "readyForRerun":
                pending = iteration_record
                break
        if pending is None:
            raise StateError("readyForRerun state is missing pending rerun metadata")
        state["status"] = "running"
        state["currentIteration"] = next_iteration
        state["toolState"] = copy.deepcopy(tool_state)
        state["decision"] = {"decision": "continue", "reasons": [], "nextPhase": "toolUser"}
        state["workers"] = []
        pending["startedAt"] = timestamp
        pending["status"] = "running"

    return _commit_mutation(run_dir, expected_revision=expected_revision, mutator=mutate, now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--expect-revision", required=True, type=int)
    subparsers = parser.add_subparsers(dest="command", required=True)

    transition_parser = subparsers.add_parser("transition")
    transition_parser.add_argument("--status", required=True)
    decision_parser = subparsers.add_parser("record-decision")
    decision_parser.add_argument("--decision", required=True)
    iteration_parser = subparsers.add_parser("record-iteration")
    iteration_parser.add_argument("--iteration", required=True, type=int)
    iteration_parser.add_argument("--scorecard", required=True)
    iteration_parser.add_argument("--artifact", action="append", default=[])
    rerun_parser = subparsers.add_parser("start-rerun")
    rerun_parser.add_argument("--tool-state", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "transition":
            state = transition_status(
                canonical_path(args.run),
                expected_revision=args.expect_revision,
                new_status=args.status,
            )
        elif args.command == "record-decision":
            state = record_decision(
                canonical_path(args.run),
                expected_revision=args.expect_revision,
                decision=json.loads(Path(args.decision).read_text(encoding="utf-8")),
            )
        elif args.command == "record-iteration":
            state = record_iteration_result(
                canonical_path(args.run),
                expected_revision=args.expect_revision,
                iteration=args.iteration,
                scorecard_path=args.scorecard,
                artifacts=args.artifact,
            )
        elif args.command == "start-rerun":
            state = start_rerun(
                canonical_path(args.run),
                expected_revision=args.expect_revision,
                tool_state=json.loads(Path(args.tool_state).read_text(encoding="utf-8")),
            )
        else:
            raise StateError(f"unsupported command: {args.command}")
    except (StateError, PathSafetyError, OSError, json.JSONDecodeError) as error:
        print(f"state mutation failed: {error}", file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "revision": state["revision"], "status": state["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
