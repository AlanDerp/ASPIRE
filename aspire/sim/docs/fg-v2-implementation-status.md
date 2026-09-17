# Dynamic FG v2 implementation status

Status date: 2026-09-16

The opt-in P0–P7 engineering path described by
`doc/FG-rebuild-implementation-plan.md` is implemented through the production trial
dispatch: strict AgentTurn parsing, task-language requirements, dynamic targets and
coverage review, event-aligned public observations, observed verdicts, temporal
windows, public probes, finish gating, private audit comparison, development probe
proposals, and reviewed frozen VerificationSkill loading. Public snapshots now carry
recomputable hashes and complete evidence references.

The dynamic loop now also supports the existing image/video VDM as a fail-closed,
batch visual verifier for Actor-authored FG targets. VDM scene-change prose and
per-target FG verdicts are projected as separate prompt sections. The harness checks
target identity, result coverage, value type, direct evidence, independent-view
requirements, confidence, probe allowlists, and provisional-verdict consistency
before converting a VDM response into public evidence. The harness, not the VDM,
recomputes target satisfaction.

Private audit modes use a fresh macOS `sandbox-exec` worker for generated Python and
JSON allowlist RPC for public robot APIs. A host-level test verified that the public
RPC remains callable while the configured private audit root cannot be read. Other
platforms fail closed until an equivalent OS isolation backend is implemented.

The default remains legacy/off. Unit and fake end-to-end checks can establish the
mechanics, fail-closed behavior and public/private data separation. They do not
establish real perception accuracy, OS-level isolation, task success, transfer, or
a performance improvement over `codex/merge`.

Real acceptance remains pending until a suite and experiment are explicitly selected,
their preflight is approved, and P8 L2/L3/L4 artifacts are produced. In particular,
the repository currently has no completed `outputs/fg_v2/<campaign-id>` report and no
real promoted VerificationSkill. The existing public verifier can consume explicit
public FG measurements or provenance-bearing entity point clouds, but the selected
suite still has to connect its live RGB/depth/segmentation producer and validate
accuracy. The acceptance tool treats all missing real artifacts as not run rather
than success.
