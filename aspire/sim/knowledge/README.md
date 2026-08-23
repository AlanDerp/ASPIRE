# ASPIRE Knowledge Consolidation Repository

This directory is the source of truth for the skill-code-first consolidation
forest described in [`../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md`](../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md).

The required evidence order is strict:

1. append executed `SkillCodeInstance` records;
2. freeze an immutable checkpoint;
3. audit repetition inside a vertical capability;
4. review nominated clusters and consolidate only explicitly accepted ones
   into canonical skills;
5. audit repeated invariants across several canonical skills and create a
   review-required principle proposal only for a connected candidate cluster;
6. add counterexamples, exceptions and falsifiers before human promotion;
7. propose a vertical tree, review every principle placement, and promote the
   exact tree revision against a base manifest;
8. propose, review, and promote optional cross-tree overlay edges against an
   exact base manifest before adding them to a newer active manifest.

A finding, Markdown recipe, or single code sample must never directly create a
canonical skill or validated principle. SQLite files and Markdown portfolios are
derived views; YAML/JSONL and Git history are authoritative.

## Quick start

Run these commands from `aspire/sim`:

```bash
PYTHONPATH=../.. python -m aspire.sim.cap.knowledge --root knowledge init
PYTHONPATH=../.. python -m aspire.sim.cap.knowledge --root knowledge forest validate
PYTHONPATH=../.. python scripts/knowledge/audit_legacy_skills.py
PYTHONPATH=../.. python -m aspire.sim.cap.knowledge --root knowledge experiment --help
PYTHONPATH=../.. python -m aspire.sim.cap.knowledge --root knowledge completion audit
```

Default thresholds are in `consolidation-policy.yaml`. `experiment/` holds the
pre-registration and evaluation inputs. Generated indexes, portfolios, and
reports should not be treated as evidence.

Validated principles are created only through `principle review` followed by
`principle promote`. Actor-visible overlay edges likewise require `overlay
propose`, `overlay review`, and `overlay promote`; a direct repository write or
status edit is not an activation path. Vertical trees require `forest
propose-tree`, placement artifacts, `forest review-tree`, and `forest
promote-tree`; saving a tree revision alone never activates it. Both repetition stages use
content-addressed reports and their policies; shared instance-level reports are
stored once rather than copied
into every skill. `forest validate` recomputes them against the frozen code.
Use a manifest for every frozen evaluation; a portfolio without a manifest is
convenient for development inspection but is not a valid experimental artifact.
