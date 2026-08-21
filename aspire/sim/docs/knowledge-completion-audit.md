# Upward-abstraction blueprint completion audit

Status date: 2026-08-21

This audit treats missing evidence as failure, not as implicit success. Run the
machine-readable audit from the repository root with:

```bash
PYTHONPATH=. python -m aspire.sim.cap.knowledge \
  --root aspire/sim/knowledge completion audit \
  --output aspire/sim/knowledge/experiment/reports/completion-audit.yaml
```

The current result is `incomplete`; the maximum justified Actor mode is `off`.
The empty authoritative knowledge repository passes structural validation only
vacuously, so that result is not evidence that the shadow-entry gate passed.

## Objective-level evidence

| Requirement | Status | Authoritative evidence |
| --- | --- | --- |
| Preserve the untouched project | Passed | annotated tag `original-version` resolves to upstream commit `680bad4df1dabe2463e20069e16f6978630fe1d7` |
| Move the blueprint into root `doc/` | Passed | source and destination SHA-256 both equal `f4fdb97b913b3f2fc42b8def922c154655184a6b867581430b256d796586cc01` |
| Implement the engineering architecture | Passed with runtime-independent tests | commits `7fe24fb` and `b24a299`; knowledge models, repository, dual repetition audits, forest/overlay, index, retrieval, lifecycle, experiment compiler and Actor boundary |
| Complete the blueprint's empirical program | Not passed | no organic corpus, human golden labels, 20-task comparison, held-out A--F execution, or prespecified conclusion |

## Milestone audit

| Milestone | Status | Remaining evidence |
| --- | --- | --- |
| M0 preregistration and baselines | Partial | H1--H6, metrics, A/B and margin exist; a hash-locked freeze command now validates the task split, checkpoint map and execution variables, but real artifacts are not yet available and the checked-in preregistration remains a draft |
| M1 corpus and vertical forest | Partial | schemas, repository, fingerprints and validators exist; real instances, two checkpoints and 10--20 expert golden principles do not |
| M2 upward abstraction | Engineering implemented | two content-addressed repetition audits, explicit cluster acceptance, hash-checked counterexample search, placement report and review-only promotion exist; real reviewer artifacts remain |
| M3 top-down retrieval | Engineering implemented | three-layer index, tree selection, gates, bounded descent, overlay, fallback, portfolios and A--F compilers are tested |
| M4 shadow and experiment | Partial | fix-loop recorder, contamination guards, isolated A--F experiment injection, deterministic rebuild verifier and missing-safe report aggregation exist; real 1x/4x/16x/64x organic runs, labels and GPU execution do not |
| M5 lifecycle and conclusion | Partial | invalidation, maintenance audit and a task-clustered prespecified claim auditor exist; measured workload, total-cost observations, case review and final go/no-go evidence do not |

## Definition-of-Done audit

### Research design

| Item | Status |
| --- | --- |
| H1--H6 preregistered | Draft only; not frozen |
| A--F controls runnable through one compiler interface | Passed by CLI end-to-end test |
| Model, prompt, corpus, checkpoint, seed and budget fairness fixed | Tamper-detecting freeze/runtime checks exist; real locks are missing |
| Organic and synthetic reported separately | Implemented; no observations exist |
| Scale-degradation slopes and confidence intervals | Implemented; no observations exist |
| Explicit failure conclusion | Claim-audit code exists; observations required to resolve it are missing |

### Skill consolidation forest

| Item | Status |
| --- | --- |
| No direct principle generation | Enforced by checkpoint membership, canonical-skill repetition graph, review revisions and exact promotion events |
| Canonical skills trace to repeated code | Enforced by shared content-addressed instance audit and explicit cluster review |
| Principle rule/scope/exception/falsifier | Enforced for validated revisions |
| Diverse support and operational grounding | Enforced structurally; not demonstrated on real data |
| Vertical tree and overlay invariants | Implemented and tested |
| Weak/broken invalidation propagation | Implemented and tested |
| Hub/merge/split/conflict/prune audit | Implemented non-destructively |
| Revision/evidence rollback | Immutable revisions plus Git and append-only evidence implemented |

### Retrieval

| Item | Status |
| --- | --- |
| Flat, canonical, summary, principle-tree and graph interfaces | A--F compiler implemented |
| Strict fan-out, skill and token bounds | Implemented and tested |
| Explicit fallback and exclusions | Persisted in every portfolio |
| Version lock, determinism and contamination guard | Implemented; deterministic verifier exists, but no real verification report exists |
| Exceptions and rejected guidance in Actor context | Implemented and tested |

### Conclusion quality

All six conclusion-quality items remain unproved because the required organic,
held-out, adversarial and maintenance observations do not exist. In particular,
there is no evidence yet for non-inferiority, a flatter active/maintenance
slope, unchanged negative transfer, or total-cost advantage.

## Non-negotiable next evidence

1. Supply the real model, prompt, disjoint task split, checkpoint map and
   execution configuration to `experiment freeze-preregistration`; do not use
   placeholders to make the gate pass.
2. Acquire real development `SkillCodeInstance` records and freeze at least two
   organic checkpoints without held-out leakage.
3. Produce 10--20 principles with two independent reviewers and all four
   support/hard-negative/exception/falsifier polarities.
4. Record deterministic tree/index/A--F portfolio rebuild evidence for at least
   20 task contexts.
5. Only after the shadow gate passes, run the fixed A--F held-out, adversarial
   and maintenance matrix and generate the prespecified conclusion.

Synthetic stress data may validate mechanics but must never satisfy any of
these organic or held-out evidence requirements.
