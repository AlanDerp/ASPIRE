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
PYTHONPATH=../.. python -m aspire.sim.cap.knowledge --root knowledge completion audit
```

Default thresholds are in `consolidation-policy.yaml`. `experiment/` holds the
pre-registration and evaluation inputs. Generated indexes, portfolios, and
reports should not be treated as evidence.

Validated revisions are created only through `principle review` followed by
`principle promote`. Both repetition stages use content-addressed reports and
their policies; shared instance-level reports are stored once rather than copied
into every skill. `forest validate` recomputes them against the frozen code.
Use a manifest for every frozen evaluation; a portfolio without a manifest is
convenient for development inspection but is not a valid experimental artifact.
