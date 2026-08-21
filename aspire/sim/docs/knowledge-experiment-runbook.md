# Upward-abstraction knowledge experiment runbook

This runbook operationalizes the repository-level
[`../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md`](../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md).
Run commands from `aspire/sim` with `PYTHONPATH=../..`.

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

`off` is the current default. After the blueprint's shadow-entry gate passes,
`shadow` is the first integration mode: compile and log portfolios while the
Actor prompt remains unchanged. Do not switch to principle runtime until its
separate runtime gates pass.

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
```

The reporter keeps organic and synthetic groups separate and returns
`not-evaluable` until every preregistered treatment/scale/corpus cell exists.
Engineering aggregation alone is not a statistical conclusion; confidence
intervals and the preregistered non-inferiority and interaction analyses remain
required.

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
```

Invalidation never deletes revisions. It recalculates support and removes weak
or broken principles from runtime retrieval. Maintenance audit proposes
merge/split/prune work without performing destructive changes.

## 7. Completion and mode gate

Never infer completion from a green unit test or an empty valid forest. Run:

```bash
python -m aspire.sim.cap.knowledge --root knowledge completion audit \
  --golden-report knowledge/experiment/reports/golden-report.yaml \
  --experiment-report knowledge/experiment/reports/report.yaml \
  --determinism-report knowledge/experiment/reports/determinism.yaml \
  --output knowledge/experiment/reports/completion-audit.yaml
```

The result explicitly reports the maximum justified Actor mode. Missing
evidence fails closed to `off`.
