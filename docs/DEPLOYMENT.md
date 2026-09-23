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
| Node.js 22.12+ and `npm --prefix app ci` | install the locked React/Vite/Rayfin dependencies before the `application` step |
| Permission to create/configure an Entra SPA registration and deploy a Rayfin Fabric App in the target workspace | the hosted console is part of the deployment, not a separate optional demo |

`config.yaml` and `state.json` are gitignored. `state.json` is written by the deploy
steps themselves — never edit it by hand.

**A full tenant migration includes the hosted application.** Recreating Fabric items
and Foundry agents alone leaves the audience-facing console on its previous tenant.
Install the Node dependencies even when the Python backend dependencies are already present.
On Windows, use `npm.cmd` if PowerShell execution policy prevents the `npm.ps1` launcher
from running; no execution-policy change is needed.

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
python deploy_all.py                    # Fabric → Foundry → hosted application → warm-up
python deploy_all.py --fabric-only      # Fabric backend only; no Foundry or application
python deploy_all.py --foundry-only     # Foundry backend only; no application
python deploy_all.py --app-only         # application only, using existing backend state
python deploy_all.py --from ontology    # resume from a step through to the end
python deploy_all.py --from application # resume just the hosted application
python deploy_all.py application        # equivalent explicit application step
python deploy_all.py ontology graph     # only these steps, canonical order kept
python deploy_all.py --skip generate_data
python deploy_all.py --warmup           # warm-up only, right before the demo
```

Every step is idempotent: it reads state first and creates only what is missing, so a
re-run after a failure resumes rather than duplicating.

`--fabric-only`, `--foundry-only` and `--app-only` are mutually exclusive **filters**
over the selected positional steps or `--from` range. For example,
`--from ontology --fabric-only` stops at `data_agent`, while `--from ontology` continues
through `application`. `--skip application` deliberately produces a backend-only run,
not a complete migration. A range with no steps left after filtering is an error.

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
| 15 | `application` | `fabric.application.deploy_application` | completed Fabric/Foundry state, Node dependencies, target tenant/workspace |

Three hard edges in that table:

- **Step 7 needs both 4 and 6.** The ontology binds entities to Delta tables *and* one
  TimeSeries to the KQL table. Run it early and it deploys against a half-built store.
- **Step 13 needs step 11 published, not merely created.** A connection can only point
  at a published artifact; a draft data agent has no stable answer surface to bind to.
- **Step 15 follows the backend, including step 14.** The console must be rebuilt and
  published against the target tenant's actual item IDs and endpoints, not the source
  tenant's saved frontend environment.

Then one step the chain **cannot** perform, because no REST API exists for it:

| Step | Artifact | Depends on |
|---|---|---|
| Workspace task flow | `taskflow/zava_media_taskflow.json`, imported by hand | every item above |

---

## Verifying

```bash
python -m pytest tests/ -q          # offline regression gate, before deploying
npm --prefix app run lint
npm --prefix app test
npm --prefix app run build:fabric
python -m foundry.verify_foundry    # three routing probes, after the deploy
```

`verify_foundry` is not optional decoration: it proves the supervisor actually routes to
the two subordinate protocols rather than answering from its own prompt.

Neither green offline tests nor successful API probes prove the hosted console works.
After the application step, open the **actual `application_url` from `state.json`** in
a clean browser session and verify:

1. Sign-in reaches the intended tenant for both the Entra SPA and Rayfin/Fabric
   authentication paths. Check the signed-in account rather than relying on cached SSO.
2. Embedded Fabric items resolve to the target workspace, including the report and
   data agent. Check browser console/network failures and unexpected old-tenant URLs.
3. A quantitative-only question is answered by Fabric; a contractual-only question
   retrieves the contract; the combined Contoso Spain Q3 question returns both with
   citations, through the hosted console.
4. Reloading the hosted URL preserves a working application and can refresh its
   authentication without returning to the source tenant.

Record the hosted URL, target tenant/workspace and browser/probe outcomes in your
deployment evidence. The orchestrator reports **steps completed**, not a verified demo:
backend-only output explicitly says the application was not deployed, even if an older
`application_url` remains in state. Do not report a full migration as complete until
the hosted/browser validation has passed.

---

## Application deployment and tenant isolation

`python -m fabric.application.deploy_application` is the standalone equivalent of the
orchestrator's `application` step. It creates or reuses the Entra SPA registration,
derives the console environment from the current `config.yaml` and `state.json`,
targets Rayfin explicitly, creates or reuses hosting, and publishes the console. Its
persisted outputs are:

- `application_url` — the actual hosted URL, not a guessed portal or vanity URL;
- `application_id` — the hosted Fabric application item;
- `application_client_id` and `application_tenant_id` — the Entra SPA identity;
- `application_workspace_id` — the workspace containing the application.

### Two application authentication paths

The console uses an **Entra SPA/MSAL registration** for delegated access to its
Fabric/Foundry integrations, and **Rayfin Fabric-brokered authentication** for the hosted
application. Both must work on the target tenant. Register the actual hosted redirect
URI on the SPA; a valid Rayfin session alone does not establish that the SPA's tenant,
redirects, permissions and consent are correct.

All `VITE_*` values are browser-visible build configuration. Public client IDs, tenant
IDs, item IDs, service URLs and Rayfin's publishable key are not credentials.
**Never put client secrets, access/refresh tokens or private service keys in `VITE_*`.**
The explicit deployment token supplied to Rayfin is process-only, not frontend config.

### Independent caches are independent targets

Azure CLI (`az`), Azure Developer CLI (`azd`, if used), Rayfin CLI and browser/MSAL
sessions have independent authentication caches. `az account set` pins Azure CLI; it
does **not** switch the others. Rayfin's local deployment registry can also retain a
different active workspace independently of Azure CLI.

The application deployment must use the configured target tenant, the workspace from
state, and an explicit Rayfin token/target rather than trusting the CLI's cached
selection. Do not invoke an unqualified `rayfin up` as a migration shortcut. Reuse of
an application is safe only within the intended tenant/workspace; do not carry a
source-tenant application URL or identity into the new target.

The local Vite/Rayfin target environment is derived from deployment state during the
application step. Do not hand-copy old tenant IDs, item IDs, endpoints or publishable
keys into frontend files. Review local development and production environment
overrides as well as Rayfin's registry when diagnosing stale targeting: changing the
Azure CLI account does not rebuild an already-published bundle or replace those files.

For CLI details matching the installed packages, use `npx rayfin docs` from `app`
(for example, `npx rayfin docs get --id rayfin-guide:app-backend/deploy.md`).

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
5. **Step 15 failing** does not invalidate completed backend steps, but the migration
   is incomplete. Check Node dependencies, Entra registration/redirect permissions and
   the explicit Rayfin tenant/workspace target; resume with
   `python deploy_all.py --app-only`. A successful redeploy still needs hosted browser
   validation, not just an HTTP success from a deployment API.
