#!/usr/bin/env python3
"""Worker backend adapters for sextant-optimize."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import session_ops


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerStatus:
    status: str
    exit_code: int | None = None
    summary: str | None = None


@dataclass(frozen=True)
class ScreenSnapshot:
    lines: list[str]


@dataclass(frozen=True)
class CloseResult:
    closed: bool
    status: str
    exit_code: int | None = None


class WorkerBackend(Protocol):
    name: str

    def create_worker(self, worker_ref: dict) -> dict:
        ...

    def poll_worker(self, worker_ref: dict) -> WorkerStatus:
        ...

    def read_worker_screen(self, worker_ref: dict, max_lines: int) -> ScreenSnapshot:
        ...

    def close_worker(self, worker_ref: dict) -> CloseResult:
        ...


class MockSubprocessBackend:
    name = "mock_subprocess"

    def __init__(self, *, command: list[str] | None = None) -> None:
        self.command = command
        self._processes: dict[str, subprocess.Popen] = {}

    def create_worker(self, worker_ref: dict) -> dict:
        command = self.command or _default_mock_command()
        env = os.environ.copy()
        env.update(
            {
                "SEXTANT_WORKER_ID": worker_ref["workerId"],
                "SEXTANT_WORKER_ROLE": worker_ref["role"],
                "SEXTANT_WORKER_OUTPUT_DIR": worker_ref["outputDir"],
                "SEXTANT_WORKER_OUTPUT_REL": worker_ref["outputRelPath"],
                "SEXTANT_WORKER_SIGNAL_PATH": worker_ref["signalPath"],
                "SEXTANT_WORKER_TRANSCRIPT_REF": worker_ref["transcriptRefPath"],
            }
        )
        stdout_path = Path(worker_ref["screenPath"])
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = stdout_path.open("ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=worker_ref["cwd"],
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                shell=False,
            )
        finally:
            stdout.close()
        self._processes[worker_ref["workerId"]] = process
        return {**worker_ref, "pid": process.pid, "launchCommand": command}

    def poll_worker(self, worker_ref: dict) -> WorkerStatus:
        process = self._processes.get(worker_ref["workerId"])
        if process is None:
            return WorkerStatus(status="unknown", summary="worker process is not registered")
        exit_code = process.poll()
        if exit_code is None:
            return WorkerStatus(status="running")
        if exit_code == 0:
            return WorkerStatus(status="exited", exit_code=exit_code)
        return WorkerStatus(status="failed", exit_code=exit_code)

    def read_worker_screen(self, worker_ref: dict, max_lines: int) -> ScreenSnapshot:
        path = Path(worker_ref["screenPath"])
        if not path.exists():
            return ScreenSnapshot(lines=[])
        return ScreenSnapshot(lines=path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:])

    def close_worker(self, worker_ref: dict) -> CloseResult:
        process = self._processes.get(worker_ref["workerId"])
        if process is None:
            return CloseResult(closed=False, status="unknown")
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        return CloseResult(closed=True, status="closed", exit_code=process.returncode)


class CmuxClaudeBackend:
    name = "cmux_claude"

    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.commands: list[list[str]] = []

    def create_worker(self, worker_ref: dict) -> dict:
        command = session_ops.build_cmux_claude_command(
            worker_id=worker_ref["workerId"],
            cwd=worker_ref["cwd"],
            prompt_path=worker_ref["promptPath"],
            output_dir=worker_ref["outputDir"],
        )
        self.commands.append(command.argv)
        launched = {
            **worker_ref,
            "workspaceRef": command.workspace_ref,
            "launchCommand": command.argv,
        }
        if self.dry_run:
            return {**launched, "dryRun": True}
        process = subprocess.Popen(command.argv, cwd=worker_ref["cwd"], shell=False)
        return {**launched, "pid": process.pid}

    def poll_worker(self, worker_ref: dict) -> WorkerStatus:
        return WorkerStatus(status="pending", summary="cmux polling is not available in dry-run helper")

    def read_worker_screen(self, worker_ref: dict, max_lines: int) -> ScreenSnapshot:
        return ScreenSnapshot(lines=[])

    def close_worker(self, worker_ref: dict) -> CloseResult:
        if worker_ref.get("dryRun"):
            return CloseResult(closed=True, status="dryRun")
        return CloseResult(closed=False, status="manualCloseRequired")


def backend_from_config(config: dict, *, mock_command: list[str] | None = None, dry_run: bool = False) -> WorkerBackend:
    backend_name = config.get("workers", {}).get("backend")
    harness = config.get("workers", {}).get("harness")
    if backend_name == "mock_subprocess":
        return MockSubprocessBackend(command=mock_command)
    if backend_name in {"cmux", "cmux_claude"} and harness == "claude":
        return CmuxClaudeBackend(dry_run=dry_run)
    raise BackendError(f"unsupported worker backend: {backend_name!r} harness={harness!r}")


def _default_mock_command() -> list[str]:
    code = r"""
import json
import os
from pathlib import Path

output_dir = Path(os.environ["SEXTANT_WORKER_OUTPUT_DIR"])
output_rel = os.environ["SEXTANT_WORKER_OUTPUT_REL"]
signal_path = Path(os.environ["SEXTANT_WORKER_SIGNAL_PATH"])
role = os.environ["SEXTANT_WORKER_ROLE"]
report = output_dir / "report.md"
report.write_text("# Mock worker report\n", encoding="utf-8")
signal = {
    "role": role,
    "status": "succeeded",
    "transcriptRef": f"{output_rel}/transcript-ref.json",
    "artifacts": [f"{output_rel}/report.md", f"{output_rel}/transcript-ref.json"],
    "summary": "Mock worker completed successfully.",
}
signal_path.write_text(json.dumps(signal), encoding="utf-8")
print("mock worker completed")
"""
    return [sys.executable, "-c", code]
