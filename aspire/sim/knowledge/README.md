# ASPIRE Knowledge Consolidation Repository

This directory is the source of truth for the skill-code-first consolidation
forest described in [`../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md`](../../../doc/aspire-upward-abstraction-knowledge-graph-blueprint.md).

The required evidence order is strict:

1. append executed `SkillCodeInstance` records;
2. freeze an immutable checkpoint;
3. audit repetition inside a vertical capability;
4. consolidate accepted clusters into canonical skills;
5. compare several canonical skills and create a review-required principle proposal;
6. add counterexamples, exceptions and falsifiers before human promotion;
7. place reviewed nodes in a vertical tree, then add optional cross-tree overlay edges.

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
```

Default thresholds are in `consolidation-policy.yaml`. `experiment/` holds the
pre-registration and evaluation inputs. Generated indexes, portfolios, and
reports should not be treated as evidence.

Validated revisions are created only through `principle review` followed by
`principle promote`. Use a manifest for every frozen evaluation; a portfolio
without a manifest is convenient for development inspection but is not a valid
experimental artifact.
