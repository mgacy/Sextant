# Sextant Optimize

Coordinate bounded Sextant tool-friction evaluation runs. This skill is repo-local workflow infrastructure for evaluating how agents use `sextant`; it is not product code for `Sources/` or `Tests/`.

## Boundaries

- Act as coordinator only.
- Do not perform substantive tool-friction analysis inline.
- Do not write research documents, planning documents, or Sextant implementation changes during a run.
- Do not hand-edit optimization state, worker prompts, completion signals, phase files, or worker records.
- Use script-owned JSON state and artifacts under `.claude-tracking/tool-eval-runs/<run-id>/`.
- Stop at handoff when the run identifies high-confidence changes or requires human judgment.

## Expected Flow

1. Validate a placeholder-free run config created from `templates/run-config.json`.
2. Run `scripts/bootstrap.py` to create `.claude-tracking/tool-eval-runs/<run-id>/`, capture tool state, fetch usage, and initialize `optimization-state.json`.
3. Read the current state revision, then use `scripts/worker_ops.py` primitives to prepare and launch exactly one role at a time through the configured backend.
4. Use `scripts/poll.py` primitives to poll each worker until completion, invalid signal, timeout, backend failure, or read-only diff invalidation. Close workers through the backend when polling says they are terminal or timed out.
5. Run roles in this order for each iteration: Tool User, Friction Miner, Evaluator, Opportunity Generator, Critic.
6. Use `scripts/extract_transcript.py` after Tool User completion when transcript refs need discovery or bounded transcript summaries.
7. Use `scripts/scorecard.py --out ...` and `scripts/check_convergence.py --out ...` for validation, scoring, and durable continue/stop decisions.
8. Use `scripts/state_ops.py` subcommands for decisions, iteration records, handoff readiness, `waitingForExternalChange`, and explicit rerun starts.
9. Use `scripts/resume.py` only after an external Sextant/tool change lands; resume must recapture tool state, create the next iteration artifacts, and stop at `readyForRerun`.
10. Report the current state, role summaries, stop reason, and handoff path. Do not continue past handoff without an external change.

## Script-Owned State

The coordinator may read artifacts and summarize them to the user, but must not hand-edit these files:

- `optimization-state.json`
- worker prompts
- worker completion signals
- transcript refs or summaries
- worker records
- phase or decision files owned by scripts

Every state mutation must go through `state_ops.py`, `poll.py`, `worker_ops.py`, or `resume.py` with the current expected revision. `scorecard.py` and `check_convergence.py` may write their own JSON outputs but must not mutate `optimization-state.json`.

## Handoff Stop

When convergence returns `decision: "stop"`, write or preserve the iteration handoff artifact under `iteration-<n>/handoff.md`, record the decision through `state_ops.py`, transition `running -> handoffReady -> waitingForExternalChange`, and stop. The handoff should point to evidence-backed artifacts rather than embedding a new research or implementation plan.

## Live Safety

For live `cmux_claude` runs, bootstrap must run from an environment with `CMUX_WORKSPACE_ID`, and required usage fetching must succeed through Claude Code OAuth credentials or an explicit override. A timed-out worker must be closed through `cmux close-workspace` before the timeout is recorded as terminal.

## Static Contracts

Schemas live in `schemas/`. Prompt templates live in `templates/`. Starter Sextant task scenarios live in `examples/task-corpus.json`.
