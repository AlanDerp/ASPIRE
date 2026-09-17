# Dynamic FG v2 acceptance runbook

Run offline unit tests from `aspire/sim` with the base development environment.
Real simulator acceptance requires an explicitly selected suite and experiment;
read the suite constitution and experiment instructions, then provide the required
preflight before starting services or trials.

Offline and host-isolation checks:

```bash
PYTHONPATH=../.. python3 -m unittest discover -s tests/fg -p 'test_*.py' -v
ASPIRE_OS_SANDBOX_TEST=1 PYTHONPATH=../.. python3 -m unittest \
  discover -s tests/fg -p 'test_execution_boundary.py' -v
```

The second command must run at the host boundary, outside another enclosing file
sandbox. A skip or `sandbox_apply` failure is blocked, not passed.

Do not edit `fg/experiment/acceptance-matrix.yaml` into a passing report. Copy it
to a fresh `outputs/fg_v2/<campaign-id>/`, attach each test artifact, and let
`scripts/fg/acceptance.py` fail unless F01–F18 are all recorded as passed. Store
audit artifacts under the separately protected private root. A skipped, blocked,
or missing case is not a pass.

The final report must keep execution status, Agent finish request, FG finish
decision, and environment task completion separate. Report observed/audit metrics
only over aligned comparable samples and report UNKNOWN/unsupported separately.
