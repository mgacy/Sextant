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
3. For each iteration, launch and poll one role at a time through `scripts/worker_ops.py` and `scripts/poll.py`: Tool User, Friction Miner, Evaluator, Opportunity Generator, Critic.
4. Extract transcript summaries after Tool User completion when transcript discovery is needed.
5. Validate friction events, opportunities, and scorecards with `scripts/scorecard.py --out iteration-<n>/evaluator/scorecard.json`.
6. Compute the stop/continue decision with `scripts/check_convergence.py --out iteration-<n>/decision.json`.
7. On stop, preserve `iteration-<n>/decision.json` and `iteration-<n>/handoff.md`, record the decision with `scripts/state_ops.py record-decision`, then transition `running -> handoffReady -> waitingForExternalChange` through `scripts/state_ops.py transition`.
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

For live `cmux` runs, start from a cmux terminal so `CMUX_WORKSPACE_ID` is present. Required usage tracking reads Claude Code OAuth credentials from Keychain and fails closed if usage cannot be fetched; tests and controlled local runs may use `SEXTANT_OPTIMIZE_USAGE_SEVEN_DAY` or `fetch_usage.py --usage-file`.

Then use the script entrypoints directly:

```bash
python3 .claude/skills/sextant-optimize/scripts/worker_ops.py --run <run-dir> --config <run-dir>/run-config.json --role tool-user --iteration 1 --task <task.json> --expect-revision <n> launch
python3 .claude/skills/sextant-optimize/scripts/poll.py --run <run-dir> --config <run-dir>/run-config.json --worker-ref <run-dir>/iteration-1/tool-user/worker-ref.json --expect-revision <n> poll
python3 .claude/skills/sextant-optimize/scripts/scorecard.py --iteration 1 --compared-to baseline --task-metrics <metrics.json> --friction-events <events.json> --opportunities <opportunities.json> --out <run-dir>/iteration-1/evaluator/scorecard.json
python3 .claude/skills/sextant-optimize/scripts/check_convergence.py --state <run-dir>/optimization-state.json --config <run-dir>/run-config.json --scorecard <run-dir>/iteration-1/evaluator/scorecard.json --out <run-dir>/iteration-1/decision.json
python3 .claude/skills/sextant-optimize/scripts/state_ops.py --run <run-dir> --expect-revision <n> record-decision --decision <run-dir>/iteration-1/decision.json
```

Confirm that all generated files stay under `.claude-tracking/tool-eval-runs/<run-id>/`, `optimization-state.json` changes only through scripts, timed-out live workers are closed by cmux, and the run stops at `waitingForExternalChange` after handoff.

## Resume Surface

```bash
python3 .claude/skills/sextant-optimize/scripts/resume.py --run-id <run-id> --repo-root . --external-change-ref <git-ref-or-note>
```

Resume stops at `readyForRerun` after creating `iteration-<next>/tool-state.md` and `iteration-<next>/tool-state.json`; start the next run explicitly:

```bash
python3 .claude/skills/sextant-optimize/scripts/state_ops.py --run <run-dir> --expect-revision <n> start-rerun --tool-state <run-dir>/iteration-<next>/tool-state.json
```

The coordinator must use scripts for state transitions. It must not edit `optimization-state.json`, prompts, completion signals, transcript refs, phase files, or worker records directly.
