#!/usr/bin/env python3
"""Validate friction artifacts and compute Sextant optimization scorecards."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


ALLOWED_CATEGORIES = {
    "fallbackSearch",
    "failedAttempt",
    "manualFiltering",
    "largeOutput",
    "missingContext",
    "documentationGap",
    "interfaceMismatch",
    "performanceOrTruncation",
    "toolUserUnfamiliarity",
    "notSextantAppropriate",
}

ALLOWED_FIX_LOCI = {
    "sextant",
    "sextantDocs",
    "agentPrompt",
    "orchestrator",
    "harness",
    "targetCodebase",
    "none",
    "unknown",
}

ALLOWED_ANSWER_QUALITY = {"grounded", "partial", "unsupported", "invalid"}
ALLOWED_GROUPS = {"controlled", "perturbed"}
HIGH_CONFIDENCE_LOCI = {"sextant", "sextantDocs", "agentPrompt"}

QUALITY_PENALTIES = {
    "grounded": 0,
    "partial": 4,
    "unsupported": 10,
    "invalid": 10,
}

CATEGORY_WEIGHTS = {
    "fallbackSearch": 2,
    "failedAttempt": 2,
    "manualFiltering": 1,
    "largeOutput": 1,
    "missingContext": 2,
    "documentationGap": 1,
    "interfaceMismatch": 2,
    "performanceOrTruncation": 2,
    "toolUserUnfamiliarity": 1,
    "notSextantAppropriate": 0,
}


class ScorecardError(ValueError):
    pass


def _require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ScorecardError(f"{label} must be an object")
    return value


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScorecardError(f"{label} must be a non-empty string")
    return value


def _require_non_negative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ScorecardError(f"{label} must be a non-negative integer")
    return value


def validate_friction_events(payload: dict) -> list[dict]:
    payload = _require_object(payload, "friction events payload")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ScorecardError("events must be an array")

    seen: set[str] = set()
    for index, event in enumerate(events):
        event = _require_object(event, f"events[{index}]")
        event_id = _require_non_empty_string(event.get("id"), f"events[{index}].id")
        if event_id in seen:
            raise ScorecardError(f"duplicate friction event id: {event_id}")
        seen.add(event_id)

        _require_non_empty_string(event.get("taskId"), f"events[{index}].taskId")
        category = event.get("category")
        if category not in ALLOWED_CATEGORIES:
            raise ScorecardError(f"events[{index}].category is not allowed: {category!r}")
        locus = event.get("suspectedFixLocus")
        if locus not in ALLOWED_FIX_LOCI:
            raise ScorecardError(f"events[{index}].suspectedFixLocus is not allowed: {locus!r}")
        if event.get("severity") not in {"low", "medium", "high"}:
            raise ScorecardError(f"events[{index}].severity must be low, medium, or high")
        _require_non_empty_string(event.get("evidence"), f"events[{index}].evidence")
        _require_non_empty_string(event.get("expectedToolBehavior"), f"events[{index}].expectedToolBehavior")
        _require_non_empty_string(event.get("proposedFix"), f"events[{index}].proposedFix")
        if not isinstance(event.get("verified"), bool):
            raise ScorecardError(f"events[{index}].verified must be boolean")

        source = _require_object(event.get("source"), f"events[{index}].source")
        if source.get("kind") not in {"transcript", "report"}:
            raise ScorecardError(f"events[{index}].source.kind must be transcript or report")
        _require_non_empty_string(source.get("sessionRef"), f"events[{index}].source.sessionRef")
        turn = source.get("turn")
        if turn is not None:
            _require_non_negative_int(turn, f"events[{index}].source.turn")

        if event["verified"]:
            if source.get("kind") != "transcript":
                raise ScorecardError(f"events[{index}] verified events require transcript evidence")
            if not isinstance(turn, int) or isinstance(turn, bool):
                raise ScorecardError(f"events[{index}] verified events require a transcript turn")

    return events


def validate_opportunities(payload: dict, *, events_by_id: dict[str, dict] | None = None) -> list[dict]:
    payload = _require_object(payload, "opportunities payload")
    opportunities = payload.get("opportunities")
    prioritized = payload.get("prioritized")
    if not isinstance(opportunities, list):
        raise ScorecardError("opportunities must be an array")
    if not isinstance(prioritized, list) or not all(isinstance(item, str) for item in prioritized):
        raise ScorecardError("prioritized must be an array of ids")

    seen: set[str] = set()
    for index, opportunity in enumerate(opportunities):
        opportunity = _require_object(opportunity, f"opportunities[{index}]")
        opportunity_id = _require_non_empty_string(opportunity.get("id"), f"opportunities[{index}].id")
        if opportunity_id in seen:
            raise ScorecardError(f"duplicate opportunity id: {opportunity_id}")
        seen.add(opportunity_id)
        _require_non_empty_string(opportunity.get("title"), f"opportunities[{index}].title")
        if opportunity.get("suspectedFixLocus") not in ALLOWED_FIX_LOCI:
            raise ScorecardError(f"opportunities[{index}].suspectedFixLocus is not allowed")
        if opportunity.get("confidence") not in {"low", "medium", "high"}:
            raise ScorecardError(f"opportunities[{index}].confidence must be low, medium, or high")
        source_ids = opportunity.get("sourceFrictionIds")
        if not isinstance(source_ids, list) or not source_ids:
            raise ScorecardError(f"opportunities[{index}].sourceFrictionIds must be non-empty")
        for source_id in source_ids:
            _require_non_empty_string(source_id, f"opportunities[{index}].sourceFrictionIds[]")
            if events_by_id is not None:
                event = events_by_id.get(source_id)
                if event is None:
                    raise ScorecardError(f"opportunities[{index}] references unknown friction event: {source_id}")
                source = event.get("source", {})
                if (
                    event.get("verified") is not True
                    or source.get("kind") != "transcript"
                    or not event.get("evidence")
                ):
                    raise ScorecardError(
                        f"opportunities[{index}] references friction event without verified transcript evidence: {source_id}"
                    )
        _require_non_empty_string(opportunity.get("expectedImpact"), f"opportunities[{index}].expectedImpact")
        _require_non_empty_string(opportunity.get("recommendedNextStep"), f"opportunities[{index}].recommendedNextStep")

    missing = set(prioritized) - seen
    if missing:
        raise ScorecardError(f"prioritized references unknown opportunity ids: {sorted(missing)}")
    return opportunities


def high_confidence_opportunity_count(
    opportunities_payload: dict,
    *,
    friction_events_payload: dict | None = None,
) -> int:
    if friction_events_payload is not None:
        events = validate_friction_events(friction_events_payload)
        events_by_id = {event["id"]: event for event in events}
    else:
        validate_opportunities(opportunities_payload)
        return 0
    return sum(
        1
        for opportunity in validate_opportunities(opportunities_payload, events_by_id=events_by_id)
        if opportunity["confidence"] == "high" and opportunity["suspectedFixLocus"] in HIGH_CONFIDENCE_LOCI
    )


def _event_score(event: dict) -> int:
    return CATEGORY_WEIGHTS[event["category"]] + (1 if event["severity"] == "high" else 0)


def score_task(metric: dict, events: list[dict] | None = None, new_friction_events: int = 0) -> dict:
    metric = _require_object(metric, "task metric")
    task_id = _require_non_empty_string(metric.get("id"), "task.id")
    quality = metric.get("answerQuality")
    if quality not in ALLOWED_ANSWER_QUALITY:
        raise ScorecardError(f"{task_id}.answerQuality must be one of {sorted(ALLOWED_ANSWER_QUALITY)}")

    group = metric.get("group", "controlled")
    if group not in ALLOWED_GROUPS:
        raise ScorecardError(f"{task_id}.group must be controlled or perturbed")

    counts = {
        key: _require_non_negative_int(metric.get(key, 0), f"{task_id}.{key}")
        for key in (
            "sextantQueries",
            "fallbackRgQueries",
            "fileReadsAfterTool",
            "failedAttempts",
            "adHocScripts",
            "manualJsonFiltering",
        )
    }
    previous = _require_non_negative_int(metric.get("previousFrictionScore", 0), f"{task_id}.previousFrictionScore")
    task_events = events or []
    new_events = _require_non_negative_int(
        metric.get("newFrictionEvents", len(task_events) if task_events else new_friction_events),
        f"{task_id}.newFrictionEvents",
    )
    event_score = sum(_event_score(event) for event in task_events)
    friction_score = event_score

    result = {
        "id": task_id,
        "group": group,
        "answerQuality": quality,
        **counts,
        "newFrictionEvents": new_events,
        "eventFrictionScore": event_score,
        "qualityPenaltyDiagnostic": QUALITY_PENALTIES[quality],
        "frictionScore": friction_score,
        "previousFrictionScore": previous,
        "delta": friction_score - previous,
    }
    return result


def aggregate_tasks(tasks: list[dict]) -> dict:
    friction = sum(task["frictionScore"] for task in tasks)
    previous = sum(task["previousFrictionScore"] for task in tasks)
    return {
        "frictionScore": friction,
        "previousFrictionScore": previous,
        "delta": friction - previous,
        "regressions": sum(1 for task in tasks if task["delta"] > 0),
        "newFriction": sum(task["newFrictionEvents"] for task in tasks),
        "evaluationInvalid": any(task["answerQuality"] in {"unsupported", "invalid"} for task in tasks),
    }


def build_scorecard(
    *,
    iteration: int,
    compared_to: str,
    task_metrics: list[dict],
    friction_events_payload: dict,
    opportunities_payload: dict,
) -> dict:
    if not isinstance(iteration, int) or iteration < 1:
        raise ScorecardError("iteration must be a positive integer")
    _require_non_empty_string(compared_to, "compared_to")
    events = validate_friction_events(friction_events_payload)
    events_by_task: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        events_by_task[event["taskId"]].append(event)

    tasks = [score_task(metric, events=events_by_task.get(metric.get("id"), [])) for metric in task_metrics]
    if not tasks:
        raise ScorecardError("task_metrics must not be empty")

    aggregate = aggregate_tasks(tasks)
    validate_opportunities(opportunities_payload, events_by_id={event["id"]: event for event in events})
    aggregate["highConfidenceOpportunities"] = high_confidence_opportunity_count(
        opportunities_payload,
        friction_events_payload=friction_events_payload,
    )

    grouped = {
        "controlled": aggregate_tasks([task for task in tasks if task["group"] == "controlled"]),
        "perturbed": aggregate_tasks([task for task in tasks if task["group"] == "perturbed"]),
    }
    grouped["controlled"]["highConfidenceOpportunities"] = aggregate["highConfidenceOpportunities"]
    grouped["perturbed"]["highConfidenceOpportunities"] = 0

    return {
        "iteration": iteration,
        "comparedTo": compared_to,
        "tasks": tasks,
        "aggregate": aggregate,
        "controlled": grouped["controlled"],
        "perturbed": grouped["perturbed"],
    }


def load_json(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--compared-to", required=True)
    parser.add_argument("--task-metrics", required=True)
    parser.add_argument("--friction-events", required=True)
    parser.add_argument("--opportunities", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        scorecard = build_scorecard(
            iteration=args.iteration,
            compared_to=args.compared_to,
            task_metrics=load_json(args.task_metrics)["tasks"],
            friction_events_payload=load_json(args.friction_events),
            opportunities_payload=load_json(args.opportunities),
        )
    except (OSError, json.JSONDecodeError, ScorecardError) as error:
        print(f"scorecard failed: {error}", file=sys.stderr)
        return 2

    output = json.dumps(scorecard, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
