#!/usr/bin/env python3
"""Compute ordered sextant-optimize convergence decisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class ConvergenceError(ValueError):
    pass


def _usage_budget(usage: dict) -> dict:
    budget = usage.get("budgetPercent")
    run_delta = usage.get("runDelta")
    exhausted = False
    if isinstance(budget, (int, float)) and isinstance(run_delta, (int, float)):
        exhausted = run_delta >= budget
    return {
        "sevenDay": usage.get("latestSevenDay"),
        "runDelta": run_delta,
        "budget": budget,
        "budgetExhausted": exhausted,
        "fetchFailed": bool(usage.get("fetchFailed", False)),
    }


def _plateau_detected(scorecard: dict, history: list[dict], plateau_threshold: int) -> bool:
    if plateau_threshold <= 0:
        return False
    recent = [*history, scorecard][-plateau_threshold:]
    if len(recent) < plateau_threshold:
        return False
    return all(card.get("aggregate", {}).get("delta", 0) >= 0 for card in recent)


def _controlled_solved(scorecard: dict, friction_threshold: int) -> bool:
    controlled = scorecard.get("controlled") or scorecard.get("aggregate", {})
    return (
        controlled.get("frictionScore", 0) <= friction_threshold
        and controlled.get("regressions", 0) == 0
        and controlled.get("evaluationInvalid") is False
    )


def _perturbed_regression(scorecard: dict) -> bool:
    controlled = scorecard.get("controlled")
    perturbed = scorecard.get("perturbed")
    if not controlled or not perturbed:
        return False
    return controlled.get("delta", 0) < 0 and (
        perturbed.get("delta", 0) > 0 or perturbed.get("regressions", 0) > 0
    )


def decide_convergence(
    *,
    state: dict,
    config: dict,
    scorecard: dict,
    history: list[dict] | None = None,
) -> dict:
    if not isinstance(scorecard, dict):
        raise ConvergenceError("scorecard must be an object")
    history = history or []
    convergence = config.get("convergence", {})
    usage = _usage_budget(state.get("usage", {}))
    aggregate = scorecard.get("aggregate", {})
    latest_friction = aggregate.get("frictionScore")
    previous_friction = aggregate.get("previousFrictionScore")
    latest_delta = aggregate.get("delta")
    plateau = _plateau_detected(scorecard, history, int(convergence.get("plateauThreshold", 2)))
    high_confidence = (
        bool(convergence.get("stopOnHighConfidenceHandoff", False))
        and int(aggregate.get("highConfidenceOpportunities", 0)) > 0
    )
    evaluation_invalid = bool(aggregate.get("evaluationInvalid", False))
    solved = _controlled_solved(scorecard, int(convergence.get("frictionThreshold", 3)))
    perturbed_regressed = _perturbed_regression(scorecard)
    human_required = bool(aggregate.get("humanJudgmentRequired", False))

    checks = [
        (usage["budgetExhausted"], "usage budget exhausted", "stop", None),
        (
            int(state.get("currentIteration", scorecard.get("iteration", 0)))
            >= int(convergence.get("maxIterations", 1)),
            "iteration ceiling reached",
            "stop",
            None,
        ),
        (evaluation_invalid, "evaluation invalid", "stop", None),
        (high_confidence, "high-confidence handoff available", "stop", None),
        (plateau, "plateau detected", "stop", None),
        (solved, "controlled workload solved", "stop", None),
        (
            perturbed_regressed,
            "controlled tasks improved while perturbed tasks regressed",
            "stop",
            None,
        ),
        (human_required, "human judgment required", "stop", None),
    ]

    decision = "continue"
    reasons: list[str] = []
    next_phase = "toolUser"
    for matched, reason, next_decision, phase in checks:
        if matched:
            decision = next_decision
            reasons = [reason]
            next_phase = phase
            break

    return {
        "decision": decision,
        "reasons": reasons,
        "nextPhase": next_phase,
        "metrics": {
            "baselineFriction": previous_friction,
            "latestFriction": latest_friction,
            "latestDelta": latest_delta,
            "plateauDetected": plateau,
            "highConfidenceHandoff": high_confidence,
            "evaluationInvalid": evaluation_invalid,
            "controlledSolved": solved,
            "perturbedRegression": perturbed_regressed,
        },
        "usage": usage,
    }


def load_json(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scorecard", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        decision = decide_convergence(
            state=load_json(args.state),
            config=load_json(args.config),
            scorecard=load_json(args.scorecard),
        )
    except (OSError, json.JSONDecodeError, ConvergenceError) as error:
        print(f"convergence failed: {error}", file=sys.stderr)
        return 2

    output = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
