# Upward-abstraction knowledge experiment runbook

This runbook operationalizes the repository-level
[`../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md`](../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md).
Run commands from `aspire/sim` with `PYTHONPATH=../..`.

## 0. Freeze the research design

Keep the checked-in preregistration as a draft until the real model, base
prompt, disjoint task split, organic/synthetic checkpoint map, and execution
configuration are known. The task split must contain nonempty `development`,
`held-out`, `adversarial`, and `maintenance` lists. The checkpoint map must
contain every preregistered scale under both `organic` and `synthetic`; organic
entries set `evidence_eligible: true`, synthetic entries set it to `false`.
`evaluation_partitions` fixes which disjoint task lists must be run for each
corpus kind.
The job catalog contains exactly those task IDs. Each entry points to an
absolute `TaskContext` and ASPIRE environment YAML and records the semantic
hash of each file.

The execution configuration fixes `model_id`, `temperature`, `simulator`,
`execution_api`, `perception_backend`, `task_seeds`, `token_budget`,
`max_runs`, `max_retries`, `retrieval_lexical_normalization`, and
`held_out_writeback: false`. It also stores a no-shell `runner_command` argument
list with `{config_path}`, `{model_id}`, `{prompt_path}`, `{seed}` and
`{observation_path}` placeholders, an absolute hash-pinned executable, and a
positive `runner_timeout_seconds`.
Freeze once, before A--F execution:

```bash
python -m aspire.sim.cap.knowledge --root knowledge \
  experiment freeze-preregistration \
  --draft knowledge/experiment/preregistration.yaml \
  --model-id <exact-model-and-version> --prompt <base-prompt.txt> \
  --task-split <task-split.yaml> --checkpoint-map <checkpoint-map.yaml> \
  --execution-config <execution-config.yaml> \
  --job-catalog <job-catalog.yaml> \
  --frozen-at <RFC3339-time> \
  --output knowledge/experiment/preregistration-frozen.yaml
```

The output stores semantic hashes and absolute source paths. Completion audit
reloads every source and fails if a file or the frozen document changes. Do not
overwrite the draft with guessed values and do not re-freeze after seeing
held-out results; a changed design starts a separately versioned experiment.

## 1. Development acquisition

After a task program has actually executed, ingest its relevant code symbol with
task, task-family, goal, observed effect, and development outcomes. The command
rejects `--source-partition held-out`.

```bash
python -m aspire.sim.cap.knowledge --root knowledge instance ingest \
  --id skill-code.libero.<task>.<symbol> \
  --vertical transport --task <task> --task-family <family> \
  --code <executed.py> --symbol <symbol> --goal '<goal>' \
  --outcomes <development-outcomes.yaml>
```

Do not ingest prose from `.claude/libero/skills/` or `findings.md` as execution
evidence. The legacy audit only inventories migration candidates.

## 2. Slow-path consolidation

Freeze at the preregistered threshold, audit repetition, and canonicalize only
accepted clusters:

```bash
python -m aspire.sim.cap.knowledge --root knowledge checkpoint freeze \
  --id snapshot-n20 --policy knowledge/consolidation-policy.yaml
python -m aspire.sim.cap.knowledge --root knowledge repetition audit \
  --checkpoint snapshot-n20 --policy knowledge/consolidation-policy.yaml \
  --output knowledge/proposals/repetition-n20.yaml
python -m aspire.sim.cap.knowledge --root knowledge skill canonicalize \
  --checkpoint snapshot-n20 --cluster <accepted-cluster-id> \
  --policy knowledge/consolidation-policy.yaml --review <cluster-review.yaml>
```

The cluster review must explicitly accept the exact cluster, identify the
reviewer and time, explain the equivalence rationale, and confirm that the
pair assessments were inspected. Similarity thresholds only nominate a
cluster; they never authorize canonicalization by themselves.

A principle proposal requires at least three canonical skills across at least
two task families. The command first performs a second, canonical-skill-level
repetition audit and rejects a disconnected candidate set. Instance-level
pairwise reports are stored once under content-addressed `proposals/` artifacts;
canonical skills reference their hash. Canonical-skill-level audit payloads,
policies, exact child revisions, and content hashes stay with the principle.
`forest validate` reloads and recomputes both layers.
Review creates a newer candidate revision; promotion creates another newer
validated revision. The review file must name the reviewer, exceptions (or an
explicit empty-exception review), falsifiers, a counterexample report, and a
leave-one-family-out report.

```bash
python -m aspire.sim.cap.knowledge --root knowledge principle propose \
  --checkpoint snapshot-n20 \
  --skills <skill-1>@<version> <skill-2>@<version> <skill-3>@<version> \
  --policy knowledge/consolidation-policy.yaml
python -m aspire.sim.cap.knowledge --root knowledge principle counterexamples \
  --id <principle-id> --from-version 1.0.0 \
  --output knowledge/proposals/<principle-id>/counterexamples.yaml
python -m aspire.sim.cap.knowledge --root knowledge principle finalize-lofo \
  --id <principle-id> --from-version 1.0.0 \
  --report <reviewed-lofo-input.yaml> \
  --output knowledge/proposals/<principle-id>/lofo.yaml
python -m aspire.sim.cap.knowledge --root knowledge principle review \
  --id <principle-id> --version 1.1.0 --review <review.yaml>
python -m aspire.sim.cap.knowledge --root knowledge principle promote \
  --id <principle-id> --from-version 1.1.0 --version 1.2.0
```

The review file must reference the generated counterexample report. The CLI
verifies its content hash, development checkpoint, principle revision and
search coverage before creating the candidate revision. High-severity leads
require an explicit disposition. The LOFO report must cover every task family,
name evaluated development tasks and grounding skills, pass every holdout, and
match its content hash. Search candidates are leads for human disposition,
never automatic counterevidence conclusions.

## 3. Freeze the active view

Save a development-only manifest containing the checkpoint and exact versions,
then run the integrity gate and build the derived index:

```bash
python -m aspire.sim.cap.knowledge --root knowledge manifest save --file <manifest.yaml>
python -m aspire.sim.cap.knowledge --root knowledge forest validate
python -m aspire.sim.cap.knowledge --root knowledge forest placement \
  --principle <principle-id> --principle-version <version> \
  --tree <tree-id> --tree-version <version> --parent <root-or-principle-id> \
  --output knowledge/proposals/<principle-id>/placement.yaml
python -m aspire.sim.cap.knowledge --root knowledge overlay validate \
  --manifest libero-active --manifest-version 1.0.0
python -m aspire.sim.cap.knowledge --root knowledge index build \
  --checkpoint snapshot-n20 --manifest libero-active --manifest-version 1.0.0 \
  --output knowledge/projections/libero-active.sqlite3
```

Placement analysis is read-only and reports primary parent, depth, direct
fan-out, active operational coverage, reparenting, and potential cycles before
the tree revision is saved.

## 4. Compile A–F under fixed inputs

For every task, treatment, scale, and seed, use the same checkpoint, manifest,
task context, model settings, execution limits, and token budget:

```bash
for treatment in A B C D E F; do
  python -m aspire.sim.cap.knowledge --root knowledge experiment compile \
    --treatment "$treatment" --checkpoint snapshot-n20 \
    --manifest libero-active --manifest-version 1.0.0 \
    --context <task-context.yaml> \
    --output "<artifacts>/${treatment}.yaml" \
    --markdown "<artifacts>/${treatment}.md"
done
```

After all derived portfolios are built, list each one in a portfolio catalog
with `corpus_kind`, `scale`, `split`, `task_id`, `treatment`, absolute `path`
and semantic `hash`. Materialize the exact Cartesian matrix before starting
any runner:

```bash
python -m aspire.sim.cap.knowledge --root knowledge experiment plan \
  --preregistration knowledge/experiment/preregistration-frozen.yaml \
  --portfolio-catalog <portfolio-catalog.yaml> \
  --output-root <immutable-run-directory> \
  --output <immutable-run-directory>/plan.yaml
python -m aspire.sim.cap.knowledge --root knowledge experiment run \
  --plan <immutable-run-directory>/plan.yaml \
  --state <immutable-run-directory>/state.yaml \
  --observations <immutable-run-directory>/observations.jsonl
```

`plan` rejects missing, duplicate or extra A--F cells and checks every
portfolio against its frozen checkpoint, manifest, task-context hash and token
budget. It writes one ASPIRE config per portfolio and one job per seed, but does
not execute anything. `run` invokes the frozen argument vector without a shell,
enforces the timeout, persists logs/state after every job, and accepts only an
observation whose artifact locks match the job. Use `--resume` only with that
same plan and state.

`off` is the current default. After the blueprint's shadow-entry gate passes,
`shadow` is the first integration mode: compile and log portfolios while the
Actor prompt remains unchanged. Do not switch to principle runtime until its
separate runtime gates pass.

For an actual A--F research run, use the internal `experiment` runtime mode
with exactly one portfolio. It is deliberately separate from the production
Actor modes and permits A, C and F only inside fixed evaluation configs:

```bash
python -m aspire.sim.cap.knowledge --root knowledge experiment runtime-config \
  --mode experiment --portfolio C=<artifacts>/C.yaml \
  --output <artifacts>/runtime-C.yaml
```

Generate a hash-locked runtime block after compiling all six shadow artifacts:

```bash
python -m aspire.sim.cap.knowledge --root knowledge experiment runtime-config \
  --mode shadow \
  --portfolio A=<artifacts>/A.yaml --portfolio B=<artifacts>/B.yaml \
  --portfolio C=<artifacts>/C.yaml --portfolio D=<artifacts>/D.yaml \
  --portfolio E=<artifacts>/E.yaml --portfolio F=<artifacts>/F.yaml \
  --output <artifacts>/knowledge-runtime.yaml
```

Place the generated `knowledge:` object under `env.cfg.knowledge` in the ASPIRE
evaluation YAML. `CodeExecutionEnvBase` verifies every hash and fairness lock at
construction. Shadow mode records all six hashes in reset/step telemetry but
does not alter the Actor prompt. Actor-visible modes accept only B (`canonical`),
D (`principle-tree`), or E (`principle-graph`) artifacts. Each trial persists
this provenance as `knowledge_runtime.json` beside `code.py`, including
timeout-recovery trials. Treat a missing file as an invalid experimental
observation whenever `knowledge` is configured.

Before presenting a rebuild as deterministic, verify it twice from the same
manifest and task contexts:

```bash
python -m aspire.sim.cap.knowledge --root knowledge \
  experiment verify-determinism \
  --checkpoint snapshot-n20 \
  --manifest libero-active --manifest-version 1.0.0 \
  --context <task-context-1.yaml> --context <task-context-2.yaml> \
  --output knowledge/experiment/reports/determinism.yaml
```

The verifier compares semantic hashes for the forest, overlay, SQLite tables,
and all A--F portfolios across two independent rebuilds.

## 5. Scale and reporting

Generate controlled stress data separately from organic snapshots:

```bash
python -m aspire.sim.cap.knowledge --root knowledge experiment build-corpus \
  --checkpoint snapshot-n20 --scales 1,4,16,64 --seed 11 \
  --output knowledge/experiment/corpora/stress-seed-11.yaml
python -m aspire.sim.cap.knowledge --root knowledge experiment report \
  --observations <observations.jsonl> \
  --preregistration knowledge/experiment/preregistration.yaml \
  --output knowledge/experiment/reports/report.yaml
python -m aspire.sim.cap.knowledge --root knowledge \
  experiment negative-transfer-review \
  --observations <observations.jsonl> \
  --labels <negative-transfer-reviewer-labels.jsonl> \
  --output knowledge/experiment/reports/negative-transfer-review.yaml
python -m aspire.sim.cap.knowledge --root knowledge experiment claim-audit \
  --observations <observations.jsonl> \
  --preregistration knowledge/experiment/preregistration-frozen.yaml \
  --cost-report knowledge/experiment/reports/cost-report.yaml \
  --maintenance-simulation knowledge/experiment/reports/maintenance-simulation.yaml \
  --negative-transfer-review knowledge/experiment/reports/negative-transfer-review.yaml \
  --output knowledge/experiment/reports/claim-audit.yaml
```

The reporter keeps organic and synthetic groups separate and returns
`not-evaluable` until every preregistered treatment/scale/corpus cell exists.
Unmeasured optional metrics remain `null`; they are never interpreted as zero.
Every observation is checked against the frozen model, prompt, budget, seed,
task partition, checkpoint ID, corpus hash and code count. Six treatments that
are mutually consistent but jointly use the wrong artifact still fail, as do
duplicate treatment rows in one experimental cell.
The claim auditor uses task-clustered bootstrap intervals for slope,
non-inferiority, exposure, overlay, exception, maintenance-cost and blast-radius
rules. It remains `not-evaluable` unless every prespecified comparison spans the
minimum independent tasks and task families.
Every adverse organic job is separately reviewed by two people; disagreements
require adjudication. H5 additionally requires the preregistered fraction of F
failures to be attributed to knowledge/exception mechanisms rather than merely
showing a numerical difference.

For the manually reviewed golden corpus, retain one JSONL row per reviewer and
run:

```bash
python -m aspire.sim.cap.knowledge --root knowledge experiment golden-report \
  --labels knowledge/experiment/relevance-labels/golden.jsonl \
  --output knowledge/experiment/reports/golden-report.yaml
```

The report is not `ready` until it covers at least 10 principles, two reviewers,
and support, hard-negative, exception, and falsifier judgments.

## 6. Lifecycle

Use read-only impact analysis before recording a development invalidation:

```bash
python -m aspire.sim.cap.knowledge --root knowledge impact show <ref>
python -m aspire.sim.cap.knowledge --root knowledge impact invalidate <ref> \
  --reason '<development evidence>'
python -m aspire.sim.cap.knowledge --root knowledge maintenance audit \
  --output knowledge/proposals/maintenance-audit.yaml
python -m aspire.sim.cap.knowledge --root knowledge maintenance simulate \
  --scenarios <reviewed-maintenance-scenarios.yaml> \
  --output knowledge/experiment/reports/maintenance-simulation.yaml
python -m aspire.sim.cap.knowledge --root knowledge maintenance cost-report \
  --ledger <trace-backed-cost-events.jsonl> \
  --preregistration knowledge/experiment/preregistration-frozen.yaml \
  --output knowledge/experiment/reports/cost-report.yaml
```

Invalidation never deletes revisions. It recalculates support and removes weak
or broken principles from runtime retrieval. Maintenance audit proposes
merge/split/prune work without performing destructive changes.

Maintenance scenarios contain reviewer-labeled affected skills, principles and
tasks. Simulation compares B's vertical canonical search surface with E's
localized graph impact without recording an invalidation. Cost events retain
raw human minutes, compute seconds, model tokens and monetary cost plus a
hash-locked timing/log artifact; the primary total converts them with weights
frozen in the preregistration. Claim audit rejects cost values that do not equal
the independent cost report and requires a valid maintenance simulation.

## 7. Completion and mode gate

Never infer completion from a green unit test or an empty valid forest. Run:

```bash
python -m aspire.sim.cap.knowledge --root knowledge completion audit \
  --golden-report knowledge/experiment/reports/golden-report.yaml \
  --experiment-report knowledge/experiment/reports/report.yaml \
  --determinism-report knowledge/experiment/reports/determinism.yaml \
  --claim-audit knowledge/experiment/reports/claim-audit.yaml \
  --output knowledge/experiment/reports/completion-audit.yaml
```

The result explicitly reports the maximum justified Actor mode. Missing
evidence fails closed to `off`.
