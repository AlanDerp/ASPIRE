# Upward-abstraction blueprint implementation status

Status date: 2026-08-21

The authoritative blueprint is
[`../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md`](../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md).
This document separates engineering completion from empirical research claims.

## Baseline and migration

- The untouched upstream commit is `680bad4df1dabe2463e20069e16f6978630fe1d7`.
- Annotated tag `original-version` points to that commit with annotation
  `original version`.
- The migrated blueprint has the same SHA-256 as the source in `cap-x`:
  `f4fdb97b913b3f2fc42b8def922c154655184a6b867581430b256d796586cc01`.
- The pre-existing untracked Chinese documentation files are not part of this
  implementation and were not modified.

## Engineering gates implemented

| Blueprint capability | Evidence |
| --- | --- |
| Skill-code-first acquisition | `cap/knowledge/ingest.py`; exact executed symbol or line range, source hash, AST/API fingerprints, development-only partition gate |
| Frozen consolidation checkpoints | `checkpoints.py`; immutable instance IDs and content hashes |
| Repetition before canonicalization | `repetition.py`, `consolidation.py`; multi-instance/task/success/share thresholds and API-aware duplicate gate |
| No direct principle generation | Proposal requires repeated canonical skills; model requires checkpoint and repetition-audit provenance |
| Explicit principle review | `review.py`; proposal → reviewed candidate → validated revision with reviewer, counterexample, exception and leave-family-out reports |
| Vertical forest + overlay | `forest.py`; cycles, primary parents, vertical membership, declared children and dangling edges validated |
| Exact revision locks | `KnowledgeManifest`; checkpoint plus exact skill/principle/tree/edge versions and development partition |
| Rebuildable three-layer index | `index.py`; checkpoint instances, active manifest nodes, FTS, tree/overlay and materialized principle metrics |
| Tree-first retrieval | `retrieval.py`; applicability, scope, exception, support, API, per-principle fan-out, global skill and token gates |
| Overlay behavior | guarded `requires`, `exception-to`, `contradicts`, and `can-follow`; exclusions enter Actor-visible context |
| Explicit fallback | Canonical fallback and reasoned exclusions are persisted in every `Portfolio` |
| Lifecycle | `lifecycle.py`; append-only invalidation, blast radius and sufficient/weak/broken support propagation |
| Explosion maintenance | `maintenance.py`; non-destructive merge/split/conflict/hub/prune audit |
| Deterministic views | vertical forest, task-family, overlay incoming/outgoing, and lineage projections with content hashes |
| A–F comparable interface | `experiment.py`; flat code, canonical, summary tree, principle tree, forest+graph, and no-exception treatments |
| Controlled stress growth | `stress.py`; 1x/4x/16x/64x synthetic records marked ineligible for evidence and success claims |
| Statistical report inputs | treatment/scale/seed coverage, artifact fairness locks, `log2(N_code)` slopes, bootstrap CIs and paired non-inferiority comparisons |
| Golden evaluation | reviewer-level labels, retained disagreement, polarity coverage and faithfulness gate |
| ASPIRE fast path | fix-loop records exact executed code in `knowledge/` and legacy Markdown in one promotion; slow consolidation stays checkpoint-driven |

The end-to-end test starts with six executed code files and reaches three
canonical skills, a reviewed/validated principle, a vertical tree, a manifest,
an SQLite index, and all A–F portfolios through the real CLI entry point.

## Empirical gates not yet satisfied

These items require evidence that is not present in the original repository and
must not be fabricated:

- no organic `SkillCodeInstance` corpus has yet been acquired from real ASPIRE
  development runs under the new recorder;
- no preregistered organic checkpoints at the intended scales have been frozen;
- no 10–20-principle golden corpus has been independently labeled by two human
  reviewers;
- no 20-task retrieval/token comparison has been run;
- no LIBERO held-out A–F GPU execution has been run with fixed model, prompt,
  seeds, API and token budget;
- no confidence interval currently establishes D/E success non-inferiority to B;
- no observed slope currently establishes that D beats B/C or E beats D;
- no observed negative-transfer comparison currently establishes that F is
  worse than E;
- no measured shadow fallback rate, recall@8, p95 compilation latency, or total
  maintenance cost has crossed the blueprint's runtime gates.

Therefore the research claim is **not yet evaluable**, and `shadow` remains the
only justified default mode. Principle runtime must not be enabled solely
because the engineering tests pass.

## Verification commands

Run from the repository root:

```bash
PYTHONPATH=. python3 -m unittest -q \
  aspire.sim.tests.test_knowledge \
  aspire.sim.tests.test_knowledge_cli \
  aspire.sim.tests.test_record_skill_promotion
PYTHONPATH=. mypy --ignore-missing-imports aspire/sim/cap/knowledge
git diff --check
```
