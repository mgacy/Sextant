#!/usr/bin/env python3
"""Fetch a Claude usage snapshot for sextant-optimize."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
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
    return {"sevenDay": float(value)}


def _read_cached_token(now: float | None = None) -> str | None:
    now = now or time.time()
    try:
        age = now - TOKEN_CACHE.stat().st_mtime
        if age > TOKEN_TTL_SECONDS:
            return None
        return TOKEN_CACHE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_cached_token(token: str) -> None:
    TOKEN_CACHE.write_text(token, encoding="utf-8")
    TOKEN_CACHE.chmod(stat.S_IRUSR | stat.S_IWUSR)


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
            f"authorization: Bearer {token}",
            "https://api.anthropic.com/oauth/usage",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("usage API request failed")
    payload = json.loads(completed.stdout)
    return parse_usage_payload(payload)


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
