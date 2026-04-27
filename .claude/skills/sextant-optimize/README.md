# Sextant Optimize

Repo-local orchestrator skill for bounded Sextant tool-friction evaluation loops.

## Automated Validation

```bash
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests -p 'test_e2e_dry_run.py'
```

## Config Template

Create a run-specific config from:

```text
.claude/skills/sextant-optimize/templates/run-config.json
```

Run-specific configs may contain private local paths and should stay under ignored run artifacts, for example:

```text
.claude-tracking/tool-eval-runs/<run-id>/run-config.json
```

## Coordinator Flow

The coordinator is responsible for sequencing scripts, not for editing state by hand or doing the role analysis inline:

1. Create a run-specific `run-config.json` from `templates/run-config.json`.
2. Bootstrap the run directory with `scripts/bootstrap.py`.
3. For each iteration, launch and poll one role at a time: Tool User, Friction Miner, Evaluator, Opportunity Generator, Critic.
4. Extract transcript summaries after Tool User completion when transcript discovery is needed.
5. Validate friction events, opportunities, and scorecards with `scripts/scorecard.py`.
6. Compute the stop/continue decision with `scripts/check_convergence.py`.
7. On stop, preserve `iteration-<n>/decision.json` and `iteration-<n>/handoff.md`, then transition `running -> handoffReady -> waitingForExternalChange` through `scripts/state_ops.py`.
8. Resume only with `scripts/resume.py` after an external Sextant/tool change is available.

## Mock Dry Run

The end-to-end mock run is automated and does not require live `cmux` or Claude:

```bash
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests -p 'test_e2e_dry_run.py'
```

Expected artifact checklist for a complete dry run:

- `.claude-tracking/tool-eval-runs/<run-id>/run-config.json`
- `.claude-tracking/tool-eval-runs/<run-id>/optimization-state.json`
- `.claude-tracking/tool-eval-runs/<run-id>/git-status.json`
- `iteration-1/tool-user/report.md`
- `iteration-1/tool-user/transcript-ref.json`
- `iteration-1/tool-user/transcript-summary.json`
- `iteration-1/friction-miner/friction-events.json`
- `iteration-1/friction-miner/report.md`
- `iteration-1/evaluator/scorecard.json`
- `iteration-1/evaluator/evaluation.md`
- `iteration-1/opportunities/prioritized.json`
- `iteration-1/opportunities/candidates.md`
- `iteration-1/critique/critique.md`
- `iteration-1/critique/perturbation.md`
- `iteration-1/decision.json`
- `iteration-1/handoff.md`

The final state should be `waitingForExternalChange` after a handoff stop. A resume attempt with unchanged tool state must leave the run waiting.

## Failure-Path Validation

Run the full skill suite before live use; it covers missing prerequisites, required and optional usage failures, worker timeout, malformed worker signals, invalid scorecards, convergence stop priority, path escape rejection, stale revisions, and no-external-change resume behavior:

```bash
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests
```

Useful focused checks:

```bash
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests -p 'test_bootstrap_guardrails.py'
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests -p 'test_worker_lifecycle.py'
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests -p 'test_scorecard_convergence.py'
python3 -B -m unittest discover .claude/skills/sextant-optimize/tests -p 'test_state_resume.py'
```

## Live Validation

Use only after the full test suite and mock dry-run test pass. Keep the first live run controlled: one Tool User task, one Friction Miner, one Evaluator, no overnight loop, and `scope.allowImplementation: false`.

```bash
python3 .claude/skills/sextant-optimize/scripts/bootstrap.py --config .claude-tracking/tool-eval-runs/<run-id>/run-config.json --repo-root .
```

Then launch/poll role workers through the coordinator skill flow. Confirm that all generated files stay under `.claude-tracking/tool-eval-runs/<run-id>/`, `optimization-state.json` changes only through scripts, and the run stops at `waitingForExternalChange` after handoff.

## Resume Surface

```bash
python3 .claude/skills/sextant-optimize/scripts/resume.py --run-id <run-id> --repo-root . --external-change-ref <git-ref-or-note>
```

The coordinator must use scripts for state transitions. It must not edit `optimization-state.json`, prompts, completion signals, transcript refs, phase files, or worker records directly.
