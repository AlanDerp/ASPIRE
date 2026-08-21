# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Human attribution report for negative-transfer observations."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .experiment import Observation
from .serialization import content_hash, iter_jsonl, sha256_file


ATTRIBUTIONS = {"knowledge-caused", "not-knowledge-caused", "uncertain"}
MECHANISMS = {
    "over-broad-principle",
    "missed-exception",
    "stale-guidance",
    "unresolved-conflict",
    "wrong-grounding",
    "irrelevant-exposure",
    "not-applicable",
    "unknown",
}


def _validate_label(label: dict[str, Any]) -> None:
    required = {
        "case_id",
        "run_job_id",
        "role",
        "reviewer",
        "reviewed_at",
        "attribution",
        "mechanism",
        "rationale",
        "evidence_path",
        "evidence_hash",
    }
    missing = sorted(required - set(label))
    if missing:
        raise ValueError(f"negative-transfer label lacks fields: {missing}")
    if label["role"] not in {"reviewer", "adjudicator"}:
        raise ValueError("negative-transfer label role must be reviewer or adjudicator")
    if label["attribution"] not in ATTRIBUTIONS:
        raise ValueError(f"unknown negative-transfer attribution: {label['attribution']}")
    if label["mechanism"] not in MECHANISMS:
        raise ValueError(f"unknown negative-transfer mechanism: {label['mechanism']}")
    if any(
        not isinstance(label[field], str) or not label[field].strip()
        for field in ("case_id", "run_job_id", "reviewer", "reviewed_at", "rationale")
    ):
        raise ValueError("negative-transfer label text fields must be nonempty")
    evidence_path = Path(str(label["evidence_path"]))
    if not evidence_path.is_absolute() or not evidence_path.is_file():
        raise ValueError("negative-transfer evidence_path must be an existing absolute file")
    if sha256_file(evidence_path) != label["evidence_hash"]:
        raise ValueError(f"negative-transfer evidence hash mismatch: {label['case_id']}")


def review_negative_transfer(
    observations_path: Path,
    labels_path: Path,
) -> dict[str, Any]:
    observations = [
        Observation.from_dict(value) for value in iter_jsonl(observations_path)
    ]
    adverse_values = [
        value
        for value in observations
        if value.corpus_kind == "organic"
        and value.negative_transfer is not None
        and value.negative_transfer > 0
    ]
    adverse = {value.run_job_id: value for value in adverse_values}
    if "" in adverse:
        raise ValueError("negative-transfer observations require run_job_id")
    if len(adverse) != len(adverse_values):
        raise ValueError("negative-transfer observations require unique run_job_id values")
    labels = list(iter_jsonl(labels_path))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in labels:
        _validate_label(label)
        job_id = str(label["run_job_id"])
        if job_id not in adverse:
            raise ValueError(f"label does not match an adverse observation: {job_id}")
        grouped[job_id].append(label)
    if set(grouped) != set(adverse):
        raise ValueError(
            f"negative-transfer labels do not cover exact adverse jobs; "
            f"missing={sorted(set(adverse) - set(grouped))}"
        )

    cases = []
    for job_id, value in sorted(adverse.items()):
        case_labels = grouped[job_id]
        case_ids = {str(label["case_id"]) for label in case_labels}
        if len(case_ids) != 1:
            raise ValueError(f"reviewers disagree on case id for job: {job_id}")
        reviewers = [label for label in case_labels if label["role"] == "reviewer"]
        reviewer_ids = {str(label["reviewer"]) for label in reviewers}
        if len(reviewers) < 2 or len(reviewer_ids) < 2:
            raise ValueError(f"negative-transfer case needs two reviewers: {job_id}")
        reviewer_attributions = {str(label["attribution"]) for label in reviewers}
        adjudicators = [
            label for label in case_labels if label["role"] == "adjudicator"
        ]
        if len(reviewer_attributions) == 1:
            if adjudicators:
                raise ValueError(
                    f"agreed reviewer labels cannot add an adjudicator: {job_id}"
                )
            final = next(iter(reviewer_attributions))
            mechanism_votes = [
                str(label["mechanism"])
                for label in reviewers
                if label["attribution"] == final
            ]
        else:
            if len(adjudicators) != 1:
                raise ValueError(
                    f"reviewer disagreement requires exactly one adjudicator: {job_id}"
                )
            final = str(adjudicators[0]["attribution"])
            mechanism_votes = [str(adjudicators[0]["mechanism"])]
        mechanism = Counter(mechanism_votes).most_common(1)[0][0]
        cases.append(
            {
                "case_id": next(iter(case_ids)),
                "run_job_id": job_id,
                "treatment": value.treatment,
                "task_id": value.task_id,
                "task_family": value.task_family,
                "final_attribution": final,
                "mechanism": mechanism,
                "reviewers": sorted(reviewer_ids),
                "adjudicator": (
                    adjudicators[0]["reviewer"] if adjudicators else None
                ),
                "label_hashes": sorted(content_hash(label) for label in case_labels),
            }
        )

    payload = {
        "schema_version": 1,
        "ready": True,
        "observations_hash": content_hash(observations),
        "adverse_observation_count": len(adverse),
        "case_count": len(cases),
        "attribution_counts": dict(
            sorted(Counter(case["final_attribution"] for case in cases).items())
        ),
        "mechanism_counts": dict(
            sorted(Counter(case["mechanism"] for case in cases).items())
        ),
        "cases": cases,
    }
    return {**payload, "review_hash": content_hash(payload)}
