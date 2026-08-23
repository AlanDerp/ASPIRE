# Experiment corpora

Store frozen organic checkpoint references and generated controlled-stress
corpora here. Synthetic records must retain `synthetic: true` and
`evidence_eligible: false`; they cannot be copied into `skill-code-instances/`.

Controlled snapshots follow `controlled-stress-corpus-schema.yaml`. They are
cumulative: every record shared by 1x and 4x is byte-identical, so scale does
not silently change content. Run `experiment audit-stress` independently for
every scale and retain the result using `stress-repetition-audit-schema.yaml`.
The checkpoint map must lock each audit path and hash before preregistration.
