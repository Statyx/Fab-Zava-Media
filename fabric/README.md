# `fabric/` — Microsoft Fabric deployment code

One package per Fabric workload. The folder name tells you which artifact the code
produces, so a change to the ontology never sends you reading the report builder.

| Folder | Produces | Entry point |
|---|---|---|
| `_shared/` | nothing — shared plumbing | not runnable |
| `workspace/` | the workspace, assigned to the capacity | `deploy_workspace.py` |
| `lakehouse/` | lakehouse, CSV upload, CSV → Delta notebook | `deploy_lakehouse.py`, `deploy_setup_notebook.py` |
| `realtime/` | eventhouse, KQL table, 20 160 pacing rows | `deploy_eventhouse.py`, `preload_pacing.py` |
| `ontology/` | Fabric IQ ontology — 7 entities, 9 relationships | `deploy_ontology.py` |
| `graph/` | graph population and refresh (the ontology does *not* populate) | `deploy_graph.py`, `refresh_graph.py` |
| `powerbi/` | Direct Lake semantic model + the PBIR report | `deploy_semantic_model.py`, `deploy_report.py` |
| `data_agent/` | the published Zava_Media_Analyst data agent | `deploy_data_agent.py` |

## Running one of them

From the repository root, as a module:

```bash
python -m fabric.ontology.deploy_ontology
```

Not by path — see [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md#invocation-model) for why.

## Conventions

- Every script starts with the three-line prologue that calls
  `fabric._shared.platform_env.bootstrap()` before any third-party import. The test
  suite enforces this: it repairs `PATH` and forces UTF-8 stdout, and a script that
  imports `requests` first dies on a Windows console mid-deploy.
- No filesystem path is built with `parent.parent` chains. Import it from
  `fabric._shared.paths`, which resolves everything once against the repository root.
- No hard-coded GUIDs. Tenant, capacity and item IDs live in the gitignored
  `config.yaml` / `state.json`; a test fails the build if one appears in code.
- Every step is idempotent — read state, create only what is missing.
