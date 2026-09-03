# Deployment

The operational runbook: what to run, in what order, and what to do when a step fails.
The *reasoning* behind that order lives in [ARCHITECTURE.md](ARCHITECTURE.md) § 8 — this
file is the one you keep open while deploying.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Azure CLI, logged in (`az login`) | every Fabric and ARM call takes its token from the CLI |
| An **F-SKU** Fabric capacity | Fabric IQ (ontology, graph) is not available on trial |
| `config.yaml` at the repository root | copy `config.example.yaml`, fill `capacity_id` + `tenant_id` |
| Python 3.12, `pip install -r requirements.txt` | — |

`config.yaml` and `state.json` are gitignored. `state.json` is written by the deploy
steps themselves — never edit it by hand.

---

## Invocation model

Deployment code is grouped one Python package per Fabric workload. A step is therefore
run **as a module, from the repository root**:

```bash
python -m fabric.lakehouse.deploy_lakehouse
```

Running the file by path (`python fabric/lakehouse/deploy_lakehouse.py`) fails: the
repository root would not be on `sys.path`, and `fabric._shared.platform_env` — the
module every script bootstraps from — would not resolve. `deploy_all.py` sits at the
root for exactly that reason, so the orchestrator needs no ceremony:

```bash
python deploy_all.py                    # full chain: Fabric, then Foundry, then warm-up
python deploy_all.py --fabric-only      # stop at the published data agent
python deploy_all.py --foundry-only     # Foundry half only, against existing state
python deploy_all.py --from ontology    # resume from a step through to the end
python deploy_all.py ontology graph     # only these steps, canonical order kept
python deploy_all.py --skip generate_data
python deploy_all.py --warmup           # warm-up only, right before the demo
```

Every step is idempotent: it reads state first and creates only what is missing, so a
re-run after a failure resumes rather than duplicating.

---

## Order, and what each step depends on

| # | Step name | Module | Depends on |
|---|---|---|---|
| 1 | `generate_data` | `design.notebooks.generate_data` | nothing — offline, seed 42 |
| 2 | `workspace` | `fabric.workspace.deploy_workspace` | `capacity_id` from config |
| 3 | `lakehouse` | `fabric.lakehouse.deploy_lakehouse` | step 2 → `workspace_id` |
| 4 | `setup_notebook` | `fabric.lakehouse.deploy_setup_notebook` | step 3 → `lakehouse_id` |
| 5 | `eventhouse` | `fabric.realtime.deploy_eventhouse` | step 2 → `workspace_id` |
| 6 | `preload_pacing` | `fabric.realtime.preload_pacing` | step 5 → `query_service_uri`, `kql_db_name` |
| 7 | `ontology` | `fabric.ontology.deploy_ontology` | steps 4 **and** 6 — Delta tables *and* the KQL table |
| 8 | `graph` | `fabric.graph.deploy_graph` | step 7 → `ontology_id` |
| 9 | `semantic_model` | `fabric.powerbi.deploy_semantic_model` | step 3 → `lakehouse_sql_endpoint` |
| 10 | `report` | `fabric.powerbi.deploy_report` | step 9 → `semantic_model_id` |
| 11 | `data_agent` | `fabric.data_agent.deploy_data_agent` | steps 7 **and** 9 |
| 12 | `foundry_project` | `foundry.deploy_foundry_project` | subscription + region from config |
| 13 | `foundry_connection` | `foundry.deploy_foundry_connection` | step 11, **published** |
| 14 | `foundry_agents` | `foundry.deploy_foundry_agents` | step 13 → the connection |

Two hard edges in that table:

- **Step 7 needs both 4 and 6.** The ontology binds entities to Delta tables *and* one
  TimeSeries to the KQL table. Run it early and it deploys against a half-built store.
- **Step 13 needs step 11 published, not merely created.** A connection can only point
  at a published artifact; a draft data agent has no stable answer surface to bind to.

Then one step the chain **cannot** perform, because no REST API exists for it:

| Step | Artifact | Depends on |
|---|---|---|
| Workspace task flow | `taskflow/zava_media_taskflow.json`, imported by hand | every item above |

---

## Verifying

```bash
python -m pytest tests/ -q          # 192 tests — the gate, run it before deploying
python -m foundry.verify_foundry    # three routing probes, after the deploy
```

`verify_foundry` is not optional decoration: it proves the supervisor actually routes to
the two subordinate protocols rather than answering from its own prompt.

---

## When a step fails

1. **Read the state.** `state.json` holds every GUID written so far; the failing step
   names the key it could not find.
2. **Resume, don't restart.** `python deploy_all.py --from <step>` picks up where it
   stopped. Restarting from scratch is safe but slow.
3. **Capacity errors at step 2** are almost always an F-SKU/trial mismatch or a region
   mismatch between the capacity and `capacity_region`.
4. **Step 13 failing on a missing data agent** means step 11 created it but did not
   publish it. Re-run `python -m fabric.data_agent.deploy_data_agent`.
