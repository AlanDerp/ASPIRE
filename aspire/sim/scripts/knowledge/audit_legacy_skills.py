#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Inventory legacy LIBERO Markdown skills without promoting knowledge nodes."""

from __future__ import annotations

import argparse
from pathlib import Path

from aspire.sim.cap.knowledge.legacy import audit_legacy_library
from aspire.sim.cap.knowledge.serialization import write_structured_atomic


SIM_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=SIM_ROOT / ".claude/libero/skills"
    )
    parser.add_argument(
        "--output", type=Path, default=SIM_ROOT / "knowledge/migrations/libero-legacy-audit.yaml"
    )
    args = parser.parse_args()
    report = audit_legacy_library(args.source, relative_to=SIM_ROOT)
    write_structured_atomic(args.output, report)
    print(
        f"audited {report['summary']['markdown_files']} Markdown files; "
        "created 0 knowledge nodes"
    )


if __name__ == "__main__":
    main()
