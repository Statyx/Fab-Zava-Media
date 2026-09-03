# Architecture — Zava Media

Technical companion to [`README.md`](../README.md). The README explains *why* the demo
exists; this file explains *how it is built* and *where it breaks*.

---

## 1. Data model

A single Lakehouse, `ZavaMediaLH`, with `dim` / `fact` schemas. One star, three fact
tables sharing the same conformed dimensions.

### Dimensions

| Table | Rows | Grain | Notes |
|---|---:|---|---|
| `dim_advertiser` | 5 | advertiser | carries `legal_entity`, used to match the contract corpus |
| `dim_brand` | 10 | brand | 2 per advertiser |
| `dim_market` | 5 | country | FR, ES, IT, UK, DE |
| `dim_channel` | 7 | channel | `cpm_eur` drives planned impressions; `grp_channel` marks offline |
| `dim_media_owner` | 6 | supplier | agency discount + rebate terms per owner |
| `dim_campaign` | 80 | campaign | advertiser × brand × market × quarter × objective |
| `dim_date` | 365 | day | 2026-04-01 → 2027-03-31 |

### Facts

| Table | Rows | Grain | Purpose |
|---|---:|---|---|
| `fact_plan` | 720 | campaign × channel × media owner × **month** | what was committed |
| `fact_delivery` | 21 960 | campaign × channel × media owner × **day** | what actually ran |
| `fact_billing` | 657 | campaign × media owner × **month** | what was invoiced |

The three tables form the agency's central triangle: **planned → delivered → billed**.
Most real-world disputes live in the gaps between them, which is exactly what the demo
interrogates.

### Real-time

`pacing_events` — 20 160 hourly rows, landing in an Eventhouse. Each row carries a
`pacing_index`: delivery over a trailing 7-day window against the pro-rata plan. This is
the stream that hangs off the *same* ontology entity as the batch facts.

---

## 2. Why the numbers are exact

`normalised_weights()` builds a weekday-shaped random weight vector, then divides it by
its own sum. Each placement's quarterly total therefore lands **precisely** on
`planned × ratio` — the daily curve looks organic, the quarterly aggregate does not
drift.

This is deliberate. The demo's credibility rests on the agent's number being
challengeable in the room. "+12 %" has to be +12.00 %, not +11.7 %.

Spend and impressions use **two independent** normalised vectors:

```
spend_ratio      ~ N(1.0, 0.015)     # tracks the plan regardless
impression_ratio = the anomaly       # carries the story
```

That asymmetry encodes the media semantics: **over-delivery is more inventory for the
same money**. If spend moved with impressions, over-delivery would just be an overspend,
and the make-good clause would be the wrong contractual question. `test_smoke.py` asserts
this explicitly.

`anomaly_markets_for()` force-includes any market named by an anomaly when drawing a
brand's four-of-five markets. Without it, the random draw can silently delete the
storyline while every test on row counts still passes.

The unbilled gap is **omitted rows**, not a status flag. Finding it requires
`LEFT JOIN ... WHERE invoice_id IS NULL`. A test asserts that no `Unbilled` value exists
in `invoice_status`, so the demo cannot be shortcut with a filter.

Two grains coexist here and both are correct: `fact_billing` is keyed on
campaign × media owner × month, so the **2** unbilled campaign-months asserted by the
test are **6** omitted invoice rows in the generator's own log. Expect the discrepancy;
it is not a bug.

---

## 3. Ontology — `ONT_Zava_Media`

Six entity types, five relationships. The ontology is what makes *campaign*,
*delivery* and *market* mean one thing across the report, the Data Agent and the graph.

| ID | Entity | Bound to |
|---|---|---|
| 1001 | Advertiser | `dim_advertiser` |
| 1002 | Brand | `dim_brand` |
| 1003 | Campaign | `dim_campaign` |
| 1004 | Placement | `fact_plan` |
| 1005 | MediaOwner | `dim_media_owner` |
| 1006 | Market | `dim_market` |

| ID | Relationship |
|---|---|
| 3001 | Advertiser → Brand |
| 3002 | Brand → Campaign |
| 3003 | Campaign → Placement |
| 3004 | Placement → MediaOwner |
| 3005 | Campaign → Market |

`Campaign` additionally carries a **TimeSeries binding** to `pacing_events` in the
Eventhouse. Batch and stream on one entity is the part of Fabric IQ that has no
equivalent in a conventional semantic layer.

ID ranges follow the brain's convention: entities 1001–1099, properties 2001–2999,
relationships 3001–3099, time series 4001–4099. GUIDs are deterministic — MD5 of a seed
string — so redeployment is idempotent.

### Trap: the empty Graph Model

A pure-API `updateDefinition` on the ontology leaves the Graph Model **empty**. Only a
schema save in the UI triggers generation. The API path is to build and push the graph
definition explicitly, then run a job with `jobType=RefreshGraph`. That path is owned by
`graph-agent` in Azure-Brain — do not reinvent it here.

---

## 4. Fabric ⟷ Foundry wiring

The portal and the SDK are **sequential, not competing** — and `deploy_foundry_connection.py`
now attempts the portal half from ARM, using the two GUIDs already in `state.json`:

1. **Connection.** The Fabric Data Agent's URL embeds two GUIDs: the workspace ID between
   `groups/` and `/aiskills`, the artifact ID between `aiskills/` and `?`. Those are exactly
   `workspace_id` and `data_agent_id`, which the Fabric deploy already recorded — so the
   script builds the connection from state and falls back to printed portal steps if the
   ARM shape is refused.
2. **Code.** Resolve the connection **by name** (`zava_media_dataagent`). Never hardcode the
   GUIDs — they are environment-specific and a hardcoded pair silently binds the demo to one
   tenant. `test_connections_are_resolved_by_name_not_by_guid` enforces it.

Required at the time of writing (both preview surfaces):

- `allow_preview=True` on `AIProjectClient` — without it the preview tools are simply
  absent, and the error never says "preview"
- the tool is `MicrosoftFabricPreviewTool` / `fabric_dataagent_preview`

### Three agents, not two

The obvious design is two agents: the Fabric data agent for numbers, and a Foundry
supervisor holding the Fabric tool plus a `file_search` over the contracts. **That design
does not work**, and it fails in the worst available way.

On a tenant, a supervisor carrying both a connection-backed tool and `file_search` **never
calls the connection**. It answers everything — including quantitative questions — out of
the document corpus. `tool_choice="required"` does not fix it: the model satisfies the
constraint with the wrong tool. Naming the tool in the prompt does not fix it either.

The cause is asymmetry of self-description. `file_search` announces what it is for. A
connection-backed tool surfaces only under its connection *name*, which says nothing about
what sits behind it. The model picks the tool it can read.

So the fix is structural, not textual: the contracts corpus goes **behind A2A** as its own
agent, `Zava-Media-Contracts`. Both supervisor tools are then opaque and connection-backed,
and the model must tell them apart by name — which is what the routing contract in the
prompt actually describes.

| Agent | Where | Holds | Answers |
|---|---|---|---|
| `Zava_Media_Analyst` | Fabric | Ontology + semantic model | The number |
| `Zava-Media-Contracts` | Foundry | Vector store over the contracts | The clause, verbatim |
| `Zava-Media-Agent` | Foundry | The two connections, nothing else | Crosses them |

For this demo that is not decoration. The entire commercial argument is *the number and the
clause come from different systems and are traceable to both*. A supervisor that quotes
"+12 %" out of a PDF looks perfectly fluent and destroys the argument silently.

`config.yaml` carries `wrap_fabric_in_a2a: false` as a documented escape hatch: set it if a
live run still misroutes, and the Fabric leg is wrapped in A2A too, giving the fully
symmetric shape.

### Trap: tool approval

Tool approval **cannot be completed inside a workflow or multi-agent run** — the run just
errors. Run each agent alone in the playground first, force each tool, choose *Always
approve this tool*, and only then run the orchestration. An unapproved tool fails in a way
that looks exactly like a routing bug.

### The wrapper prompt

The orchestrator's prompt for the Fabric tool must carry both clauses:

- *"the response must come only from the tool output"* — stops the model answering from
  its own priors when the tool returns something unexpected
- *"do not generate summaries or remove any data"* — stops it silently truncating a
  result set into a sentence

Omitting the second is the more common failure, and the harder to notice: the answer
looks fine and is quietly incomplete.

Beyond those two, `build_supervisor_instructions()` implements an eight-clause answer
contract whose clause numbering matches `Foundry-Brain/orchestration_patterns.md` Pattern F,
so the two can be diffed. The clause with the least obvious payoff is **carry no figure in
the instructions**: a grounded agent holding a hardcoded fact is worse than an ungrounded
one, because it looks sourced. `test_supervisor_prompt_carries_no_figure` fails the build if
a digit ever appears in the prompt.

---

## 5. Deployment order

One command runs the whole chain — Fabric then Foundry; every step is idempotent, so it
resumes rather than duplicating:

```bash
python deploy_all.py                       # full deploy, then a warm-up
python deploy_all.py --fabric-only         # stop at the published data agent
python deploy_all.py --foundry-only        # only the Foundry half, against existing state
python deploy_all.py --from ontology       # resume from a step to the end
python deploy_all.py ontology graph        # run only these (canonical order kept)
python deploy_all.py --warmup              # warm-up only, right before the demo
python -m foundry.verify_foundry           # three routing probes, after the deploy
```

Run these from the repository root: deployment code is grouped one package per workload,
so the root must be on `sys.path`. The runnable module path of every step is in
[DEPLOYMENT.md](DEPLOYMENT.md); the table below is about *why* the order is what it is.

The canonical order, and the artifact each step needs from the previous one:

| # | Step | Script | Needs |
|---|---|---|---|
| 1 | Generate the dataset | `design/notebooks/generate_data.py` | — (offline) |
| 2 | Workspace + capacity | `fabric/workspace/deploy_workspace.py` | `capacity_id` |
| 3 | Lakehouse + CSV upload | `fabric/lakehouse/deploy_lakehouse.py` | `workspace_id` |
| 4 | CSV → Delta tables | `fabric/lakehouse/deploy_setup_notebook.py` | `lakehouse_id` |
| 5 | Eventhouse + KQL table | `fabric/realtime/deploy_eventhouse.py` | `workspace_id` |
| 6 | Ingest pacing events | `fabric/realtime/preload_pacing.py` | `query_service_uri`, `kql_db_name` |
| 7 | Ontology (Fabric IQ) | `fabric/ontology/deploy_ontology.py` | Delta tables **and** the KQL table |
| 8 | Graph population + refresh | `fabric/graph/deploy_graph.py` | `ontology_id` |
| 9 | Semantic model | `fabric/powerbi/deploy_semantic_model.py` | `lakehouse_sql_endpoint` |
| 10 | Power BI report | `fabric/powerbi/deploy_report.py` | `semantic_model_id` |
| 11 | Data agent (published) | `fabric/data_agent/deploy_data_agent.py` | `ontology_id` **and** `semantic_model_id` |
| 12 | Foundry project + model | `foundry/deploy_foundry_project.py` | subscription, region |
| 13 | Fabric data agent connection | `foundry/deploy_foundry_connection.py` | **published** data agent |
| 14 | Contracts agent + supervisor | `foundry/deploy_foundry_agents.py` | the connection |

Step 10 sits between the model and the data agent because it binds to the model by id,
and because everything after it is Foundry — the report is the last purely-Fabric artifact.

Then one step the chain **cannot** perform:

| # | Step | Script | Needs |
|---|---|---|---|
| — | Workspace task flow | `taskflow/zava_media_taskflow.json`, imported by hand | every item above |

Task flows are a workspace **UI feature**, not a Fabric item type. There is no REST
endpoint, no item to POST, nothing to poll — the only way in is the portal's *Import a task
flow* button. The JSON also carries tasks and edges only, so item assignments and canvas
positions do not survive an export/import round trip and must be redone. It is last because
it assigns the items the fourteen steps create. `taskflow/README.md` has the assignment
table, and `tests/test_taskflow.py` validates the file offline, since nothing else will.

Ordering rules that are not obvious, and each cost a debugging session:

- **Publish the Data Agent.** An unpublished agent is invisible to Foundry. The connection
  appears to be created and then resolves to nothing. `deploy_data_agent.py` therefore
  writes the `published/` tree as well as `draft/` — `test_data_agent_is_published_not_just_drafted`
  fails the build if that mirror is ever broken.
- **Refresh the graph before creating the Data Agent**, or the agent binds to an ontology
  with no traversable graph and every relationship question returns nothing — successfully.
- **Ingest the pacing events before deploying the ontology.** The TimeSeries binding
  resolves against a KQL table that must already exist.
- **A connection is not validated at creation.** Step 12 returns HTTP 200 against a target
  that does not exist; reachability is only proven at invoke, which is why step 13 reads the
  agent card back and `verify_foundry.py` exists at all.
- **`az account set` runs first.** `deploy_all.py` reads `az_subscription` from
  `config.yaml`; without it `az` can silently sit on another tenant and every call returns
  404 EntityNotFound, which reads exactly like a permissions problem.

### Capacity, region and tenant prerequisites

Verified against Microsoft Learn (fetched 2026-02, primary source, not a summary).

| Requirement | This demo | Source |
|---|---|---|
| Capacity SKU | **F2 or higher**, paid (or P1+). Trial SKUs cannot use Azure OpenAI. Ours is an **F8** — sufficient | [Create a Fabric data agent § Prerequisites](https://learn.microsoft.com/fabric/data-science/how-to-create-data-agent) |
| Capacity region | **Sweden Central** — inside the **EU Data Boundary** | [Copilot in Fabric § Available regions](https://learn.microsoft.com/fabric/fundamentals/copilot-fabric-overview#available-regions) |
| Cross-geo processing | **Not required.** The Azure OpenAI service backing Fabric Copilot is deployed in US datacenters *and in the EU Data Boundary*; an EU capacity maps to EU hosting, so the tenant switch stays off | same |
| Tenant switches | Copilot on; **Standalone Copilot experience** on (Admin portal → Copilot). Without the second one, data agents fail inside Copilot scenarios even when every other Copilot switch is green | [Data agent tutorial](https://learn.microsoft.com/fabric/data-science/data-agent-end-to-end-tutorial) |

Three things worth knowing before someone "helpfully" moves this demo:

- **F64 is not required.** The F64 figure circulating for Fabric AI is the old Copilot
  threshold. Data agents need F2. The F64 number in the consumption doc is an *example*
  used to size CU cost, not a floor.
- **A UK capacity would be worse than a Swedish one**, not better. The region table maps
  UK → EU Data Boundary as a *cross-geo* hop requiring the tenant switch; EU → EU does not.
  For a client whose whole argument is auditability under the French transparency regime,
  "the data never left the EU boundary and no override was enabled" is part of the pitch.
- **Do not reason from the Text Analytics region list.** That table (North Europe, West
  Europe, France Central, Norway East, Switzerland, UK South/West) excludes Sweden Central
  and governs Text Analytics and Translator only — not the Azure OpenAI path the data
  agent uses.

Keep the Foundry project in **Sweden Central** too. The call path is already
`orchestrator → tool → data agent → DAX`; a cross-region hop is latency added to a chain
that is the accepted cost of the boundary rule, not a place to spend more.

Both the capacity ID and tenant ID live in `config.yaml`, which is gitignored.

---

## 6. Coexistence with an existing Databricks estate

Relevant when the client already runs Databricks and is evaluating Fabric alongside it,
rather than instead of it. Four patterns, documented in full in
`Azure-Brain/Fabric-Brain/agents/migration-databricks-agent/coexistence_interop.md`:

| Pattern | Direction | When |
|---|---|---|
| **A** | Databricks writes Delta directly into OneLake | Databricks stays the transformation engine; Fabric consumes |
| **B** | Fabric shortcuts onto ADLS/Unity Catalog external locations | Data stays put; no copy, no second physical truth |
| **C** | Fabric Mirroring of Unity Catalog | Read-only replica, managed by Fabric |
| **D** | Both read the same ADLS via shortcut | Neither owns the other |

For a demo, **B** is usually the honest one to show: it makes the point that adopting
Fabric IQ does not require moving the lake or retiring the existing pipelines. The
semantic and agentic layers are what is being added — not a second copy of the data.

---

## 7. What this demo does not prove

Stated plainly, because a demo that oversells is worse than one that is narrow.

- The Fabric Data Agent tool in Foundry and the ontology are **preview** surfaces.
  Behaviour and API shapes can change.
- Latency of the full chain has not been measured under load. It is not fast.
- The contracts are five short documents. Retrieval quality over a real corpus of
  hundreds of contracts, with amendments and versions, is a different problem.
- Nothing here addresses identity passthrough at scale — the demo runs as one principal.
- **The chain has not been run against a live tenant.** Everything is structurally
  validated — 160 offline tests — which catches shape errors and catches nothing about
  behaviour. Three things in particular are unproven: which `category` ARM accepts for a
  Fabric data agent connection (`deploy_foundry_connection.py` probes three and records the
  winner), the availability of the chosen model and version in Sweden Central, and whether
  `MicrosoftFabricPreviewTool` competes with a self-describing tool the way `file_search`
  does — that last one is an inference from a neighbouring measurement, which is why the
  escape hatch exists rather than a claim that it is not needed.
