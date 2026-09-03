#!/usr/bin/env python3
"""Every filesystem location this repository depends on, resolved once.

Why this module exists
----------------------
Workload scripts sit at different depths — ``fabric/lakehouse/deploy_lakehouse.py`` is
two levels below the repository root, ``foundry/deploy_foundry_agents.py`` is one. A
``Path(__file__).parent.parent`` chain therefore means a *different* directory in each
of them, and the chain is silently wrong the moment a file is moved between workloads.
That is how a deploy script ends up reading an empty ``artifacts/`` and reporting
success on zero rows.

Resolve the root from this module's own location instead, and derive everything from it.
This file is the only place in the repository allowed to count directory levels.
"""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "ROOT",
    "ARTIFACTS",
    "CONTRACTS",
    "POWERBI",
    "CONFIG_FILE",
    "STATE_FILE",
    "CONFIG_EXAMPLE",
    "STATE_EXAMPLE",
]

#: Repository root. This file is ``<root>/fabric/_shared/paths.py``, hence ``parents[2]``.
ROOT = Path(__file__).resolve().parents[2]

#: Seed data, one CSV per target table, uploaded by the workload that owns that table.
#: Committed on purpose: the demo must reproduce with no tenant.
ARTIFACTS = ROOT / "artifacts" / "lakehouse_data"

#: Advertiser contracts — the unstructured half of every agent answer.
CONTRACTS = ROOT / "design" / "contracts"

#: The Power BI workload folder: the PBIR report lives beside the scripts that deploy it.
POWERBI = ROOT / "fabric" / "powerbi"

#: One config and one state for the whole repository, not one per workload. Both are
#: gitignored — they carry tenant, capacity and item GUIDs. See the ``*.example`` twins.
CONFIG_FILE = ROOT / "config.yaml"
STATE_FILE = ROOT / "state.json"
CONFIG_EXAMPLE = ROOT / "config.example.yaml"
STATE_EXAMPLE = ROOT / "state.example.json"
