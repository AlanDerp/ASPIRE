# Upward-abstraction blueprint implementation status

Status date: 2026-08-23

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
| Repetition before canonicalization | `repetition.py`, `consolidation.py`; thresholds only nominate clusters, explicit pairwise review accepts them, and shared audit/policy artifacts are stored once by content hash |
| No direct principle generation | Proposal recomputes a connected canonical-skill repetition audit over exact frozen child revisions; direct CLI save is absent and exact promotion events gate Actor visibility |
| Explicit principle review | `review.py`, `review_artifacts.py`; proposal → candidate → validated with hash-checked counterexample dispositions, all-family LOFO evidence, exceptions and falsifiers |
| Counterexample and placement review | `counterexample.py`, `placement.py`, `tree_review.py`; frozen-development candidate search plus content-addressed parent/depth/fan-out/coverage/cycle reports for every promoted tree placement |
| Vertical forest + overlay | `forest.py`, `tree_review.py`, `overlay_review.py`; both primary tree structure and cross-tree relations pass exact base-manifest-bound proposal → review → promotion gates before activation |
| Exact revision locks | `KnowledgeManifest`; checkpoint plus exact skill/principle/tree/edge versions and development partition; proposed trees/edges are rejected at manifest save |
| Rebuildable three-layer index | `index.py`; checkpoint instances, active manifest nodes, FTS, tree/overlay and materialized principle metrics |
| Tree-first retrieval | `retrieval.py`; applicability, scope, exception, support, API, per-principle fan-out, global skill and token gates |
| Overlay behavior | guarded `requires`, `exception-to`, `contradicts`, and `can-follow`; only exact promotion-event-bound revisions enter Actor context, projections, manifests, or SQLite indexes |
| Explicit fallback | Canonical fallback and reasoned exclusions are persisted in every `Portfolio` |
| Lifecycle | `lifecycle.py`; append-only invalidation, blast radius and sufficient/weak/broken support propagation |
| Explosion maintenance | `maintenance.py`; non-destructive merge/split/conflict/hub/prune audit |
| Maintenance experiment and total cost | reviewer-labeled B/E invalidation-surface simulation plus trace-backed construction/maintenance resource ledger under preregistered weights |
| Negative-transfer case review | exact adverse run-job coverage, two trace-backed reviewers, disagreement adjudication and mechanism attribution before H5 can pass |
| Deterministic views | vertical forest, task-family, overlay incoming/outgoing, and lineage projections with content hashes |
| A–F comparable interface | `experiment.py`; flat code, canonical, summary tree, principle tree, forest+graph, and no-exception treatments |
| Controlled stress growth | `stress.py`; seed-locked prefix-stable 1x/4x/16x/64x snapshots, real category-specific AST/contract perturbations, independently hash-checked repetition audits, and immutable evidence/promotion ineligibility |
| Statistical report and claim audit | complete metric schema with missing-is-not-zero semantics, treatment/scale/seed coverage, artifact fairness locks, `log2(N_code)` slopes, task-clustered bootstrap CIs, non-inferiority, exposure, overlay, exception, cost and blast-radius decisions |
| Preregistration freeze | `preregistration.py`; validates H1--H6/A--F, disjoint and corpus-specific evaluation partitions, organic/synthetic checkpoint eligibility and all fixed execution variables, then hash-locks every source artifact |
| Golden evaluation | manifest/revision/child/evidence-locked exact items, two independent reviewers per item, retained disagreement, polarity coverage and faithfulness gate |
| ASPIRE fast path | fix-loop records exact executed code in `knowledge/` and legacy Markdown in one promotion; slow consolidation stays checkpoint-driven |
| Actor runtime modes | `knowledge/runtime.py` and `CodeExecutionEnvBase`; hash-locked off/shadow/production B-D-E plus isolated A--F experiment loading, prompt injection, reset/step telemetry, and per-trial `knowledge_runtime.json` provenance |
| A--F execution harness | `run_plan.py`; exact frozen task/treatment/scale/corpus/seed matrix, generated ASPIRE configs, no-shell commands, timeout/resume state, and observation-lock validation |
| Completion and determinism gates | `completion.py`, `verification.py`; fail-closed Actor-mode audit and independent semantic rebuild comparison for forest/index/A--F portfolios |

The end-to-end test starts with six executed code files and reaches three
canonical skills, a reviewed/validated principle, a vertical tree, a base
manifest, a reviewed/promoted overlay edge, an active manifest, an SQLite index,
and all A–F portfolios through the real CLI entry point.

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
- no task-clustered confidence interval currently establishes D/E success non-inferiority to B;
- no observed slope currently establishes that D beats B/C or E beats D;
- no observed negative-transfer comparison currently establishes that F is
  worse than E;
- no measured shadow fallback rate, recall@8, p95 compilation latency, or
  trace-backed total maintenance cost has crossed the blueprint's runtime gates.

Therefore the research claim is **not yet evaluable**, and `off` remains the
only justified default mode. `shadow` is the next integration stage after its
golden and integrity gates pass; principle runtime must not be enabled solely
because the engineering tests pass.

The requirement-by-requirement evidence matrix is maintained in
[`knowledge-completion-audit.md`](knowledge-completion-audit.md); its current
machine-readable snapshot is under `knowledge/experiment/reports/`.

## Verification commands

Run from the repository root:

```bash
PYTHONPATH=. python3 -m unittest -q \
  aspire.sim.tests.test_knowledge \
  aspire.sim.tests.test_knowledge_cli \
  aspire.sim.tests.test_preregistration \
  aspire.sim.tests.test_knowledge_runtime \
  aspire.sim.tests.test_record_skill_promotion
PYTHONPATH=. mypy --ignore-missing-imports aspire/sim/cap/knowledge
git diff --check
```
