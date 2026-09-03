# `design/` — specifications and the generator that realises them

This folder is the *contract*; `fabric/` and `foundry/` are the *implementation*. If a
number is disputed during the demo, the answer is here.

| Folder | Contents |
|---|---|
| `contracts/` | the 5 framework contracts (English, fictional) — the corpus the Contracts agent retrieves from |
| `notebooks/` | `generate_data.py`, the deterministic seeded generator (seed 42) |

## `notebooks/generate_data.py`

Offline, no tenant, no credential. It writes the 11 CSVs into
`artifacts/lakehouse_data/`, which are committed on purpose so the repository
reproduces the demo without a deploy.

```bash
python -m design.notebooks.generate_data
```

It is also step 1 of `deploy_all.py`. Re-running it is idempotent — same seed, same
bytes — so it is safe to leave in the chain.

## The anomalies are exact by construction

The delivered-vs-planned deltas the agent is meant to find are produced from
normalised daily weights, not sampled noise. They are therefore checkable by hand in
front of an audience, and `tests/test_smoke.py` asserts them to 0.05 percentage points.
Change the generator and that test tells you which story beat you just broke.
