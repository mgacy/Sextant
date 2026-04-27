#!/usr/bin/env python3
"""Fetch a usage snapshot for sextant-optimize.

The real Claude OAuth usage source is intentionally outside this repository.
For deterministic runs and tests this script accepts either --usage-file or the
SEXTANT_OPTIMIZE_USAGE_SEVEN_DAY environment variable and prints a normalized
JSON snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_usage_payload(payload: dict) -> dict:
    value = payload.get("sevenDay", payload.get("initialSevenDay"))
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("usage payload must include numeric sevenDay")
    return {"sevenDay": float(value)}


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
            if raw is None:
                raise ValueError(
                    "usage unavailable: set SEXTANT_OPTIMIZE_USAGE_SEVEN_DAY or pass --usage-file"
                )
            snapshot = {"sevenDay": float(raw)}
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "usage": snapshot}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
