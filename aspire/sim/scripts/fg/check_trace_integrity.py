#!/usr/bin/env python3
"""Validate that public FG observations and verdict references form a closed trace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def check(root: Path) -> dict:
    observations_path = root / "fg/observations.observed.jsonl"
    verdicts_path = root / "fg/verdicts.jsonl"
    evidence_path = root / "evidence/derived/measurements.jsonl"
    snapshots_path = root / "fg/snapshots.jsonl"
    errors = []
    observations = [json.loads(line) for line in observations_path.read_text().splitlines() if line.strip()] if observations_path.exists() else []
    verdicts = [json.loads(line) for line in verdicts_path.read_text().splitlines() if line.strip()] if verdicts_path.exists() else []
    evidence_rows = [json.loads(line) for line in evidence_path.read_text().splitlines() if line.strip()] if evidence_path.exists() else []
    snapshots = [json.loads(line) for line in snapshots_path.read_text().splitlines() if line.strip()] if snapshots_path.exists() else []
    # Recompute refs through production models, preventing copied strings from
    # satisfying integrity after evidence or snapshot content is changed.
    from aspire.sim.cap.factual_grounding.observations import FGObservation, FGSnapshot, FGVerdict
    from aspire.sim.cap.perception.evidence import EvidenceRecord

    observation_models = [FGObservation(**{
        **item, "evidence_refs": tuple(item["evidence_refs"]),
        "sensor_refs": tuple(item["sensor_refs"]),
    }) for item in observations]
    refs = {item.ref for item in observation_models}
    evidence_refs = {
        EvidenceRecord(**{**item, "sensor_refs": tuple(item["sensor_refs"])}).ref
        for item in evidence_rows
    }
    for index, observation in enumerate(observation_models, start=1):
        for ref in observation.evidence_refs:
            if ref not in evidence_refs:
                errors.append(
                    f"observation line {index} has dangling evidence ref {ref}"
                )
    for index, verdict in enumerate(verdicts, start=1):
        for ref in verdict.get("based_on", []):
            if ref not in refs:
                errors.append(f"verdict line {index} has dangling observation ref {ref}")
    for index, item in enumerate(snapshots, start=1):
        snapshot_observed = tuple(FGObservation(**{
            **value, "evidence_refs": tuple(value["evidence_refs"]),
            "sensor_refs": tuple(value["sensor_refs"]),
        }) for value in item.get("observed", ()))
        snapshot_verdicts = tuple(FGVerdict(**{
            **value, "based_on": tuple(value["based_on"]),
            "next_probe_options": tuple(value["next_probe_options"]),
        }) for value in item.get("public_verdicts", ()))
        snapshot = FGSnapshot(
            int(item["spec_revision"]), str(item["event_id"]),
            observed=snapshot_observed, public_verdicts=snapshot_verdicts,
        )
        if snapshot.public_hash != item.get("public_hash"):
            errors.append(f"snapshot line {index} has an invalid public hash")
    return {
        "schema_version": 1,
        "passed": bool(observations and verdicts and evidence_rows and snapshots) and not errors,
        "errors": errors,
        "observation_count": len(observations),
        "verdict_count": len(verdicts),
        "evidence_count": len(evidence_rows),
        "snapshot_count": len(snapshots),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__": main()
