# Principle schema v1 to v2

Schema v2 adds semantic fields that cannot be inferred safely from a v1
summary: `abstraction.common_core`, `preserved_variations`, and the immutable
`quality_policy`.

Do not rewrite a v1 revision or fill these fields mechanically. Preserve the v1
file and Git history as evidence, then:

1. load its exact canonical-skill children and frozen checkpoint;
2. create a new schema-v2 proposal revision from those children;
3. have a reviewer state the common core, preserved variations, excluded
   details, and a policy no weaker than the repository policy;
4. regenerate counterexample, LOFO, and compression reports;
5. review and promote through the normal content-addressed workflow;
6. create and review a new tree revision and manifest that lock the v2 node.

The runtime rejects schema-v1 Principle files rather than guessing an
abstraction boundary. The repository shipped with this implementation contains
no v1 Principle revisions, so no in-place data conversion is required.
