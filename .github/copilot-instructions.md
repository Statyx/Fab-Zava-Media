# Copilot instructions — Fab-Zava-Media

A Microsoft Fabric + Azure AI Foundry demo: a media-agency pacing story where a Fabric
data agent answers *how big is the delivery gap* and a Foundry contracts agent answers
*what the contract says about it*. Neither answers alone — that split is the demo.

## Repository layout is not negotiable

Deployment code is grouped **one package per Fabric workload**, never flat in `src/`:

```
fabric/{_shared,workspace,lakehouse,realtime,ontology,graph,powerbi,data_agent}/
foundry/            design/{contracts,notebooks}/       artifacts/lakehouse_data/
```

When adding a deploy script, put it in the folder named after the artifact it creates,
and name it `deploy_<artifact>.py`. Shared plumbing goes in `fabric/_shared/` — if it
knows about a specific artifact, it is not shared.

Seed data lives in `artifacts/`, never inside `fabric/`. `design/` is specification;
`fabric/` and `foundry/` are implementation.

## Invocation model

Scripts are run as modules from the repository root:
`python -m fabric.ontology.deploy_ontology`. Running by path fails on purpose — see
`docs/DEPLOYMENT.md`. Do **not** "fix" that by adding `sys.path` manipulation to a
script; that is the copy-pasted glue this structure exists to delete.

## Hard rules the test suite enforces

- Every deploy script opens with the three-line prologue calling
  `fabric._shared.platform_env.bootstrap()` **before any third-party import**.
- `import winreg` appears in `platform_env.py` and nowhere else.
- No hard-coded `shell=True`; use `platform_env.AZ_NEEDS_SHELL`.
- No hard-coded GUIDs — they belong in the gitignored `config.yaml` / `state.json`.
- No `parent.parent` path chains — import from `fabric._shared.paths`.
- Every step is idempotent: read state, create only what is missing.

## Before proposing a change

```bash
python -m pytest tests/ -q      # 192 tests, and they encode the demo storyline
```

The tests are not a formality: they assert the exact pacing anomalies the audience is
invited to challenge by hand. A green suite is the definition of done here.

## Deeper context

- `docs/ARCHITECTURE.md` — why the deploy order is what it is
- `docs/DEPLOYMENT.md` — how to run it, and what to do when a step fails
- `fabric/README.md`, `foundry/README.md`, `design/README.md` — per-theme conventions
