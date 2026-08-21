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
  --policy knowledge/consolidation-policy.yaml
```

A principle proposal requires at least three canonical skills across at least
two task families. Review creates a newer candidate revision; promotion creates
another newer validated revision. The review file must name the reviewer,
exceptions (or an explicit empty-exception review), falsifiers, a counterexample
report, and a leave-one-family-out report.

```bash
python -m aspire.sim.cap.knowledge --root knowledge principle propose \
  --checkpoint snapshot-n20 --skills <skill-1> <skill-2> <skill-3>
python -m aspire.sim.cap.knowledge --root knowledge principle review \
  --id <principle-id> --version 1.1.0 --review <review.yaml>
python -m aspire.sim.cap.knowledge --root knowledge principle promote \
  --id <principle-id> --from-version 1.1.0 --version 1.2.0
```

## 3. Freeze the active view

Save a development-only manifest containing the checkpoint and exact versions,
then run the integrity gate and build the derived index:

```bash
python -m aspire.sim.cap.knowledge --root knowledge manifest save --file <manifest.yaml>
python -m aspire.sim.cap.knowledge --root knowledge forest validate
python -m aspire.sim.cap.knowledge --root knowledge index build \
  --checkpoint snapshot-n20 --manifest libero-active --manifest-version 1.0.0 \
  --output knowledge/projections/libero-active.sqlite3
```

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

`shadow` is the first integration mode: compile and log portfolios while the
actor still sees the legacy library. Do not switch to principle runtime until
the engineering gates in the blueprint pass.

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
