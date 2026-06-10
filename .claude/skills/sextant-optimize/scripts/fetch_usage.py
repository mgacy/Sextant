#!/usr/bin/env python3
"""Fetch a Claude usage snapshot for sextant-optimize.

Three input paths, in priority order: an explicit `--usage-file` JSON payload,
the `SEXTANT_OPTIMIZE_USAGE_SEVEN_DAY` environment override, and the live
Claude OAuth usage API (token read from the macOS keychain, cached briefly on
disk with owner-only permissions). Every path fails closed: any error exits 2
with a JSON error object on stderr so callers never mistake a failed fetch for
a real snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


TOKEN_CACHE = Path(os.environ.get("TMPDIR", "/tmp")) / ".sextant_optimize_claude_token_cache"
TOKEN_TTL_SECONDS = 900


def parse_usage_payload(payload: dict) -> dict:
    value = payload.get("sevenDay", payload.get("initialSevenDay"))
    if value is None and isinstance(payload.get("seven_day"), dict):
        value = payload["seven_day"].get("utilization")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("usage payload must include numeric sevenDay")
    snapshot = {
        "sevenDay": float(value),
    }
    five_hour = payload.get("five_hour")
    if isinstance(five_hour, dict):
        utilization = five_hour.get("utilization")
        if isinstance(utilization, (int, float)) and not isinstance(utilization, bool):
            snapshot["fiveHour"] = float(utilization)
        resets_at = five_hour.get("resets_at")
        if isinstance(resets_at, str) and resets_at:
            snapshot["fiveHourResetsAt"] = resets_at
    return snapshot


def _read_cached_token(now: float | None = None) -> str | None:
    now = now or time.time()
    try:
        info = TOKEN_CACHE.stat()
        if stat.S_IMODE(info.st_mode) & 0o077:
            return None
        if now - info.st_mtime > TOKEN_TTL_SECONDS:
            return None
        return TOKEN_CACHE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_cached_token(token: str) -> None:
    TOKEN_CACHE.unlink(missing_ok=True)
    fd = os.open(TOKEN_CACHE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)


def _invalidate_cached_token() -> None:
    try:
        TOKEN_CACHE.unlink()
    except OSError:
        pass


def _oauth_token_from_keychain(*, runner=subprocess.run) -> str:
    cached = _read_cached_token()
    if cached:
        return cached
    completed = runner(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("could not read Claude Code credentials from keychain")
    try:
        credentials = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("Claude Code credentials are not JSON") from error
    token = credentials.get("claudeAiOauth", {}).get("accessToken")
    if not isinstance(token, str) or not token:
        raise ValueError("could not extract OAuth token from keychain credentials")
    _write_cached_token(token)
    return token


def fetch_oauth_usage(*, runner=subprocess.run) -> dict:
    token = _oauth_token_from_keychain(runner=runner)
    header_fd, header_path = tempfile.mkstemp(prefix=".sextant_usage_header.")
    try:
        with os.fdopen(header_fd, "w", encoding="utf-8") as handle:
            handle.write(f"authorization: Bearer {token}\n")
        completed = runner(
            [
                "curl",
                "-s",
                "-m",
                "5",
                "-H",
                "accept: application/json",
                "-H",
                "anthropic-beta: oauth-2025-04-20",
                "-H",
                f"@{header_path}",
                "https://api.anthropic.com/oauth/usage",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    finally:
        os.unlink(header_path)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "no stderr"
        raise ValueError(f"usage API request failed: curl exit {completed.returncode}: {detail}")
    try:
        payload = json.loads(completed.stdout)
        return parse_usage_payload(payload)
    except ValueError as error:
        # A non-JSON or malformed payload usually means an expired or revoked
        # token (the API returns an error body), so drop the cached token to
        # force a fresh keychain read on the next attempt.
        _invalidate_cached_token()
        raise ValueError(f"usage API returned an invalid usage payload: {error}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usage-file")
    args = parser.parse_args(argv)

    try:
        if args.usage_file:
            payload = json.loads(Path(args.usage_file).read_text(encoding="utf-8"))
            snapshot = parse_usage_payload(payload)
        else:
            raw = os.environ.get("SEXTANT_OPTIMIZE_USAGE_SEVEN_DAY")
            snapshot = {"sevenDay": float(raw)} if raw is not None else fetch_oauth_usage()
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "usage": snapshot}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
