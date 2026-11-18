# Task Boundary Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reduce extra tasks and useless review questions while preserving current task recall and context completion.

**Architecture:** Keep incremental tracking, full-context interpretation, checking and one targeted repair. Compare prompt-only and explicit context_only classification with shared output rules. Route supported non-task context and standalone status reports separately from confirmations; retain conditional work as non-automatic candidates.

**Tech Stack:** Python, unittest, SQLite, existing recorded DeepSeek client.

**Spec:** ../../task-boundary-design.md

## Global Constraints

- Original runs and labels remain frozen; new outputs go to runs/2026-11-15-task-boundary.
- No keyword-based removal; normal short acceptance, team work, missing dates and implicit needs remain supported.
- Do not hide classification disputes. Only supported context_only and fully supported status reports take the new silent routes.
- Conditional work never creates automatically; suggestions remain proposals for adoption.
- No new model stage unless controlled experiments show it necessary.
- No Git exists; before.zip and source/config hashes replace commits/worktrees. User approved implementation/testing; execute natively without another approval gate.

## Review Focus

- Context is later adopted as current work, including across the eight-segment checkpoint.
- A product decision and its implementation task share an utterance.
- A status report has a real unresolved relation or time claim and must not disappear.
- Optional repair removes a wrong event without changing unaffected records.
- Conditional work and a group proposal retain their actual commitment and cannot silently become automatic writes.

### Task 1: Context and review routing

**Files:** tests/test_task_boundary.py; meeting_eval/context_state.py; context_new_work.py; extract.py; context_pipeline.py; service.py.
**Interfaces:** Existing canonical_ledger/canonical_records/reduce_context; output adds context_records and commitment details in review projections, reuses reports.

- [x] Add tests for context_only validation, silent retention, disputed classification, later promotion, frozen C17 report routing and unsupported-time control, conditional candidate and suggestion question, Service rendering/no writes.
- [x] Run `python -X utf8 -m unittest discover -s tests -p test_task_boundary.py -v`; observe expected failures.
- [x] Implement minimum contracts and bump context protocol/validation versions.
- [x] Run focused tests and full `python -X utf8 -m unittest discover -s tests -v`; inspect results.

### Task 2: Semantic experiments and paired inputs

**Files:** prompts/*-context-v1.txt; experiments/task-boundary/{run.py,fixtures.json}; independent run directories.
**Interfaces:** Normal Service.process; runner can freeze stored ledger/initial interpretation and provide prompt-only A vs context_only B without modifying model inputs with labels.

- [x] Add task-boundary prompts with explicit context preservation, quoted-speech scope, commitment distinctions and classification checks.
- [x] Prepare 14 paired groups plus role/acceptance and cross-checkpoint controls; save expectations separately from model input.
- [x] Compare A/B with frozen upstream and a small check-only arm; preserve first responses, inspect actual outputs and call counts.
- [x] Select by semantic evidence, test C26/M2 repeated paired trials; add decision history or another stage only if necessary.

### Task 3: Full validation and source review

**Files:** experiments/task-boundary validation/review helpers; runs/.../full; docs/task-boundary-results.md; docs/HANDOVER.md.
**Interfaces:** Existing frozen manifest jobs, normal Service entry, independent stores; freshly reviewed prediction-to-gold matches.

- [x] Freeze selected source/prompts; rerun 30 corpus excerpts, continuous roles, 10 context/cancellation scenarios, 13 update scenarios and M1/M2.
- [x] Review each new prediction, confirmation and relevant context; score original/audited labels separately. Record structural failures and recovery separately.
- [x] Run final program suite and fresh-context code review, resolve important findings with tests.
- [x] Report actual before/after task quality, false confirmations, remaining errors and usage; update handover.

## Execution ledger

- Setup: before.zip saved; no Git repository. Tasks 1/2 share new context kind and reducer output; Task 3 consumes unchanged Service API. No conflicting interfaces found.
- Ruling: use a narrow context-v1 conditional reducer, leaving older strategies unchanged; actual model quality is evaluated by new calls, not source-text assertions.
- Task 1: observed new tests fail before implementation; implemented contracts and rendering. 134 tests pass after two independent-review fixes.
- Task 2: A/B frozen-ledger comparison and two rounds on C24/C26/M2; check-only arm; 33 paired/perturbed cases. A draft with duplicate type definitions is excluded from formal comparison. No stable causal superiority of the new type established; B retained as an explicit experimental contract, not promoted as a proven globally better strategy.
- Task 3: full and full-v2 completed (54 cases each), cross and final cross-v2, C1 history-decision ablation. C1 did not solve M2 and is not integrated. Final first-pass corpus: audited 17/18 correct, zero extra tasks; C19 one-shot recovery gives 18/18. Full final run 53 processed/1 partial; 13 update contracts, 23 context criteria and 12 old cross checks pass. Extra M2 semantic checks fail.
- Final limitations: M2 range decision still creates extra candidates/questions; C20 retains an unsupported manuscript question; paired P07b over-clarifies reference. These fail full semantic acceptance and are preserved in results/handover, not hidden by routing.
- Final artifacts: docs/task-boundary-results.md, updated docs/HANDOVER.md, runs/2026-11-15-task-boundary/{summary,usage,verification}.json. Production files match full-v2/source.zip.
