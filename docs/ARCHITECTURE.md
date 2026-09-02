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

The portal and the SDK are **sequential, not competing**.

1. **Portal.** Create the connection from the Fabric Data Agent's URL. Two GUIDs are
   embedded in it: the workspace ID sits between `groups/` and `/aiskills`, the artifact
   ID between `aiskills/` and `?`. The portal turns those into a **named** project
   connection.
2. **Code.** Resolve the connection **by name** (`zava_media_dataagent`). Never hardcode
   the GUIDs — they are environment-specific and a hardcoded pair silently binds the demo
   to one tenant.

Required at the time of writing (both preview surfaces):

- `allow_preview=True` on `AIProjectClient`
- the tool is `MicrosoftFabricPreviewTool` / `fabric_dataagent_preview`

### Trap: tool approval

Tool approval **cannot be completed inside a workflow preview**. Run each agent alone in
the playground first, approve the tool there, and only then run the orchestration. A
workflow that has never been approved fails in a way that looks like a routing bug.

### The wrapper prompt

The orchestrator's prompt for the Fabric tool must carry both clauses:

- *"the response must come only from the tool output"* — stops the model answering from
  its own priors when the tool returns something unexpected
- *"do not generate summaries or remove any data"* — stops it silently truncating a
  result set into a sentence

Omitting the second is the more common failure, and the harder to notice: the answer
looks fine and is quietly incomplete.

---

## 5. Deployment order

Each step depends on the previous one's artifact ID.

```
workspace → lakehouse → load CSVs → eventhouse → pacing stream
         → ontology → graph refresh
         → semantic model → report
         → data agent (publish!)
         → Foundry project → connection → knowledge base → orchestrator
```

Two ordering rules that are not obvious:

- **Publish the Data Agent.** An unpublished agent is invisible to Foundry. The
  connection will appear to be created and then resolve to nothing.
- **Refresh the graph before creating the Data Agent**, or the agent binds to an ontology
  with no traversable graph and every relationship question fails.

Prerequisites: an F-SKU capacity ID and tenant ID in `src/config.yaml`, both in
**Sweden Central**. Keep the Foundry project in the same region — the call path is
already `orchestrator → tool → data agent → DAX`; a cross-region hop is latency added to
a chain that is the accepted cost of the boundary rule, not a place to spend more.

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
