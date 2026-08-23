# Knowledge manifests

Each manifest freezes one checkpoint plus exact semantic versions for every
canonical skill, principle, vertical tree, and overlay edge used by a run.
Evaluation records must store `<manifest-id>@<version>`. Never edit a manifest
revision in place; save a newer version instead.

Overlay review uses a development base manifest that locks the exact source and
target node revisions. After promotion, create a newer manifest revision whose
`edge_versions` locks the promoted edge. A manifest containing a proposal,
candidate, or validated edge without its exact promotion event fails closed.
