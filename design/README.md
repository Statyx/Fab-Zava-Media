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

## IQ comparison reference

`python -m design.notebooks.export_iq_reference` reads the existing CSVs and ontology
bindings without changing them. It writes `app/src/data/iq-reference.generated.json` for
the **Repository example** in IQ in practice. Explicit table lookups and a separately
instantiated relationship traversal must produce the same campaign/media-owner membership.
The exporter fails on dangling relationships or disagreements, and includes an input
fingerprint. This is local reference data, not a recording of Fabric or an agent answer.
Regenerate it after changing any relevant CSV or ontology binding.

`python -m design.notebooks.export_iq_dossiers` then produces the two action-dossier
references, including complete verbatim articles from the fictional contracts and the
explicitly simulated Finance note in `artifacts/iq_context/work-notes.json`. It fixes the
scenario date after Q3 closes; it never presents future quarter data as current actuals.
These references are not live captures. The optional Fabric/Foundry recorder is separate.

The same command exports `artifacts/iq_context/web-notes.json` into the separate
`app/src/data/iq-web-context.generated.json`: two fictional announcements for the Web IQ
step. Source/date, scenario and case scope are validated. These notes never enter the
Fabric/Foundry prompts or capture fingerprint, and remain marked simulated in the drafts.
