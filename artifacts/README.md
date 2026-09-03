# `artifacts/` — generated data, committed on purpose

Seed data lives here and never inside `fabric/`. The rule is simple: `fabric/` holds
code that *deploys*, `artifacts/` holds bytes that get *uploaded*. Mixing them makes it
impossible to tell, at a glance, what a workload folder is responsible for.

| Folder | Contents | Produced by |
|---|---|---|
| `lakehouse_data/` | 11 CSVs — the whole demo dataset | `python -m design.notebooks.generate_data` |

These files are committed deliberately, not by accident: the repository has to
reproduce the demo storyline for someone with no Fabric tenant, and `tests/test_smoke.py`
asserts their row counts and the anomalies inside them.
