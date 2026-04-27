import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_convergence
import scorecard


def friction_events(*events):
    return {"events": list(events)}


def event(**overrides):
    payload = {
        "id": "friction-001",
        "taskId": "controlled-task",
        "source": {
            "kind": "transcript",
            "sessionRef": "project/session",
            "turn": 12,
        },
        "category": "fallbackSearch",
        "severity": "medium",
        "evidence": "Tool User ran rg after Sextant because the output omitted parent context.",
        "expectedToolBehavior": "Sextant should expose enough parent context to avoid broad fallback search.",
        "suspectedFixLocus": "sextant",
        "proposedFix": "Expose parent declaration metadata for enum case matches.",
        "verified": True,
    }
    payload.update(overrides)
    return payload


def opportunities(*items):
    return {
        "opportunities": list(items),
        "prioritized": [item["id"] for item in items],
    }


def opportunity(**overrides):
    payload = {
        "id": "opportunity-001",
        "title": "Expose parent context",
        "sourceFrictionIds": ["friction-001"],
        "suspectedFixLocus": "sextant",
        "confidence": "high",
        "expectedImpact": "Reduce fallback search.",
        "recommendedNextStep": "Prototype parent context output.",
    }
    payload.update(overrides)
    return payload


def task_metric(**overrides):
    payload = {
        "id": "controlled-task",
        "group": "controlled",
        "answerQuality": "grounded",
        "sextantQueries": 1,
        "fallbackRgQueries": 0,
        "fileReadsAfterTool": 1,
        "failedAttempts": 0,
        "adHocScripts": 0,
        "manualJsonFiltering": 0,
        "previousFrictionScore": 8,
    }
    payload.update(overrides)
    return payload


def scorecard_payload(**aggregate_overrides):
    aggregate = {
        "frictionScore": 4,
        "previousFrictionScore": 9,
        "delta": -5,
        "regressions": 0,
        "newFriction": 0,
        "evaluationInvalid": False,
        "highConfidenceOpportunities": 0,
    }
    aggregate.update(aggregate_overrides)
    return {
        "iteration": 1,
        "comparedTo": "baseline",
        "tasks": [],
        "aggregate": aggregate,
        "controlled": dict(aggregate),
        "perturbed": {
            "frictionScore": 0,
            "previousFrictionScore": 0,
            "delta": 0,
            "regressions": 0,
            "newFriction": 0,
            "evaluationInvalid": False,
            "highConfidenceOpportunities": 0,
        },
    }


def state(iteration=1, usage=None):
    return {
        "currentIteration": iteration,
        "usage": usage
        or {
            "latestSevenDay": 12,
            "runDelta": 0,
            "budgetPercent": 25,
            "fetchFailed": False,
        },
    }


def config(**convergence_overrides):
    convergence = {
        "maxIterations": 3,
        "plateauThreshold": 2,
        "frictionThreshold": 3,
        "stopOnHighConfidenceHandoff": True,
    }
    convergence.update(convergence_overrides)
    return {"convergence": convergence}


class ScorecardValidationTests(unittest.TestCase):
    def test_friction_events_require_allowed_category_and_locus(self):
        scorecard.validate_friction_events(friction_events(event()))

        with self.assertRaisesRegex(scorecard.ScorecardError, "category"):
            scorecard.validate_friction_events(friction_events(event(category="vibes")))

        with self.assertRaisesRegex(scorecard.ScorecardError, "suspectedFixLocus"):
            scorecard.validate_friction_events(friction_events(event(suspectedFixLocus="compiler")))

    def test_verified_events_require_transcript_evidence_and_turn(self):
        with self.assertRaisesRegex(scorecard.ScorecardError, "transcript evidence"):
            scorecard.validate_friction_events(
                friction_events(event(source={"kind": "report", "sessionRef": "report", "turn": None}))
            )

        with self.assertRaisesRegex(scorecard.ScorecardError, "transcript turn"):
            scorecard.validate_friction_events(
                friction_events(event(source={"kind": "transcript", "sessionRef": "project/session", "turn": None}))
            )

        scorecard.validate_friction_events(
            friction_events(
                event(
                    verified=False,
                    source={"kind": "report", "sessionRef": "friction-miner/report.md", "turn": None},
                )
            )
        )

    def test_answer_quality_is_validated_and_unsupported_invalidates_evaluation(self):
        with self.assertRaisesRegex(scorecard.ScorecardError, "answerQuality"):
            scorecard.score_task(task_metric(answerQuality="confident"))

        unsupported = scorecard.build_scorecard(
            iteration=1,
            compared_to="baseline",
            task_metrics=[task_metric(answerQuality="unsupported")],
            friction_events_payload=friction_events(),
            opportunities_payload=opportunities(),
        )

        self.assertTrue(unsupported["aggregate"]["evaluationInvalid"])
        self.assertEqual(unsupported["tasks"][0]["frictionScore"], 12)

    def test_scoring_rubric_weights_fallbacks_failures_scripts_filtering_and_quality(self):
        scored = scorecard.score_task(
            task_metric(
                answerQuality="partial",
                sextantQueries=2,
                fallbackRgQueries=1,
                fileReadsAfterTool=3,
                failedAttempts=1,
                adHocScripts=1,
                manualJsonFiltering=2,
                newFrictionEvents=1,
                previousFrictionScore=25,
            )
        )

        self.assertEqual(scored["frictionScore"], 25)
        self.assertEqual(scored["delta"], 0)

    def test_controlled_and_perturbed_aggregates_are_separate(self):
        built = scorecard.build_scorecard(
            iteration=1,
            compared_to="baseline",
            task_metrics=[
                task_metric(id="controlled-task", previousFrictionScore=8),
                task_metric(
                    id="perturbed-task",
                    group="perturbed",
                    fallbackRgQueries=2,
                    fileReadsAfterTool=2,
                    previousFrictionScore=3,
                ),
            ],
            friction_events_payload=friction_events(event(taskId="controlled-task")),
            opportunities_payload=opportunities(opportunity()),
        )

        self.assertEqual(built["controlled"]["frictionScore"], 4)
        self.assertEqual(built["controlled"]["delta"], -4)
        self.assertEqual(built["perturbed"]["frictionScore"], 9)
        self.assertEqual(built["perturbed"]["regressions"], 1)
        self.assertEqual(built["aggregate"]["highConfidenceOpportunities"], 1)

    def test_high_confidence_opportunity_count_excludes_low_confidence_and_non_tool_loci(self):
        count = scorecard.high_confidence_opportunity_count(
            opportunities(
                opportunity(id="opportunity-001", confidence="high", suspectedFixLocus="sextant"),
                opportunity(id="opportunity-002", confidence="medium", suspectedFixLocus="sextant"),
                opportunity(id="opportunity-003", confidence="high", suspectedFixLocus="targetCodebase"),
            )
        )

        self.assertEqual(count, 1)


class ConvergenceDecisionTests(unittest.TestCase):
    def test_stop_priority_order_prefers_usage_budget_then_iteration_then_invalid_then_handoff(self):
        high_confidence_invalid = scorecard_payload(
            evaluationInvalid=True,
            highConfidenceOpportunities=2,
        )

        usage_stop = check_convergence.decide_convergence(
            state=state(iteration=3, usage={"latestSevenDay": 40, "runDelta": 25, "budgetPercent": 25}),
            config=config(maxIterations=3),
            scorecard=high_confidence_invalid,
        )
        self.assertEqual(usage_stop["reasons"], ["usage budget exhausted"])

        iteration_stop = check_convergence.decide_convergence(
            state=state(iteration=3),
            config=config(maxIterations=3),
            scorecard=high_confidence_invalid,
        )
        self.assertEqual(iteration_stop["reasons"], ["iteration ceiling reached"])

        invalid_stop = check_convergence.decide_convergence(
            state=state(iteration=1),
            config=config(maxIterations=3),
            scorecard=high_confidence_invalid,
        )
        self.assertEqual(invalid_stop["reasons"], ["evaluation invalid"])

        handoff_stop = check_convergence.decide_convergence(
            state=state(iteration=1),
            config=config(maxIterations=3),
            scorecard=scorecard_payload(highConfidenceOpportunities=1),
        )
        self.assertEqual(handoff_stop["reasons"], ["high-confidence handoff available"])

    def test_plateau_solved_and_perturbed_regression_are_ordered_after_handoff(self):
        plateau = check_convergence.decide_convergence(
            state=state(iteration=1),
            config=config(stopOnHighConfidenceHandoff=False),
            history=[scorecard_payload(delta=0)],
            scorecard=scorecard_payload(delta=0),
        )
        self.assertEqual(plateau["reasons"], ["plateau detected"])

        solved = check_convergence.decide_convergence(
            state=state(iteration=1),
            config=config(stopOnHighConfidenceHandoff=False, plateauThreshold=3, frictionThreshold=4),
            scorecard=scorecard_payload(frictionScore=4, delta=-5),
        )
        self.assertEqual(solved["reasons"], ["controlled workload solved"])

        regressed = scorecard_payload(frictionScore=8, delta=-3)
        regressed["controlled"]["delta"] = -5
        regressed["controlled"]["frictionScore"] = 8
        regressed["perturbed"]["delta"] = 2
        regressed["perturbed"]["regressions"] = 1
        decision = check_convergence.decide_convergence(
            state=state(iteration=1),
            config=config(stopOnHighConfidenceHandoff=False, plateauThreshold=3, frictionThreshold=3),
            scorecard=regressed,
        )
        self.assertEqual(decision["reasons"], ["controlled tasks improved while perturbed tasks regressed"])

    def test_continue_when_no_stop_condition_matches(self):
        decision = check_convergence.decide_convergence(
            state=state(iteration=1),
            config=config(stopOnHighConfidenceHandoff=False, plateauThreshold=3, frictionThreshold=3),
            scorecard=scorecard_payload(frictionScore=6, delta=-2),
        )

        self.assertEqual(decision["decision"], "continue")
        self.assertEqual(decision["nextPhase"], "toolUser")
        self.assertFalse(decision["usage"]["budgetExhausted"])


if __name__ == "__main__":
    unittest.main()
