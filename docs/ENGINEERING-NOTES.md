# Engineering notes

The failure modes this repository is built to prevent, and the reasoning behind the wiring.

This file exists so the [README](../README.md) can stay a reader's page. Everything below is
for whoever **maintains** the demo: read it before changing a deploy script, a measure, an
ontology binding or an agent prompt. Every item here was a real failure that deployed cleanly.

---

## Why the contracts sit behind their own agent

**Why the contracts sit behind their own agent.** The obvious shape puts `file_search` on
the supervisor directly. On a tenant, a supervisor holding a connection-backed tool *and*
`file_search` never calls the connection — it answers everything, numbers included, out of
the documents. `tool_choice="required"` does not rescue it; the model meets the constraint
with the wrong tool. `file_search` describes its own purpose, a connection tool surfaces
only under its name, and the model picks the tool it can read. Pushing the corpus behind
A2A makes both tools opaque, so the routing contract in the prompt is the only thing telling
them apart — which is what it was written to do. Full reasoning in
[ARCHITECTURE § 4](ARCHITECTURE.md).

---

## Mandatory testing gate

```bash
python -m pytest tests/ -v --tb=short
```

**192 tests, no tenant required.** Five files, five different jobs.

`test_smoke.py` guards the **dataset**. It asserts the exact anomaly percentages
(+12.00 / +11.00 / −8.00), that background noise stays visibly below them, that spend
does *not* move with the over-delivered impressions (otherwise the make-good clause
would be the wrong question), that the unbilled gap is a real anti-join with no status
flag leaking the answer, and that the three contracts still say three different things.

`test_deploy_scripts.py` guards the **seams between the deploy scripts** — every failure
it catches would otherwise ship as a deploy that succeeds and is wrong:

- an ontology entity bound to a column that no longer exists in the CSV (→ empty graph,
  no error)
- a DAX measure the data agent tells the LLM to use, that is not in the semantic model
  (→ the model invents plausible, unverifiable DAX)
- a GQL few-shot citing an edge label that was renamed (→ returns nothing, successfully)
- a data agent written to `draft/` only (→ invisible to Foundry, looks deployed)
- a second join path to `dim_advertiser` (→ Power BI silently deactivates one and the
  advertiser-level figure changes)
- KQL columns reordered against the CSV (→ positional ingestion loads campaign IDs into
  the channel column)
- a column or measure whose *name* implies a contractual entitlement — that half of the
  question belongs to Foundry, and the boundary is enforced in the model, not just in a
  prompt

`test_foundry_scripts.py` guards the **Foundry failures that deploy cleanly** — every one
of them produces a green deploy followed by an agent that answers fluently from the wrong
place:

- a `file_search` attached to the supervisor (→ the Fabric tool never fires and the numbers
  come out of a PDF)
- a figure hardcoded in the supervisor prompt (→ an answer that looks sourced and is not)
- the `### SOURCE` marker drifting between the prompt that mandates it and the verifier that
  splits on it (→ a correct answer fails verification and someone "fixes" the agent)
- an A2A connection pointed at the card path instead of the base path (→ created with HTTP
  200, resolves at invoke, never before)
- one protocol written without re-listing the others (→ merge-patch replaces the array and
  silently disables `responses`)
- a date-shaped api-version on the Agents data plane (→ 400, reads as a broken route)
- a GUID hardcoded where a connection name belongs (→ works here, breaks on promotion)

`test_taskflow.py` guards the **one artifact no API validates**. Task flows have no REST
endpoint, so the workspace canvas is imported by hand in front of the customer and the
portal either parses it or says "import failed" with no line number. The guard catches a
non-ASCII character anywhere in the prose (invisible in a diff, fatal to the parser), a BOM,
`taskType` instead of `type`, an edge pointing at an id no task declares (draws nothing,
raises nothing), and an item renamed in `config.example.yaml` but not on the canvas. It also
asserts the two Foundry agents stay *off* the canvas: a task flow maps Fabric items, and
putting them there would imply Fabric owns them.

`test_report.py` guards the **PBIR traps that VALIDATE cleanly**. It asserts on the
*generated* PBIR folder rather than on the generator's source, because that is where the
damage shows: a report that hangs forever on "Loading your report..." passes
`powerbi-report-author validate` with 0 errors, and so does a report whose 27 visuals were
never validated at all because their `$schema` 404s. It pins the visual schema version
upstream, requires every schema URL to be absolute, checks `version` is `2.0.0`, that the
base theme is a real built-in shipping its own JSON, that every page folder appears in
`pageOrder`, that no visual falls off the canvas, that non-data visuals carry no query, and
that the central claim is actually on the canvas.

Harmonise the clauses, smooth an anomaly, or rename a measure on one side of a seam, and
the suite fails — which is the intent. The demo can break while every file still looks fine.


---

## The fourth case, and why the percentages are exact

A fourth case needs a genuine anti-join rather than a status flag:

| Finding | Value | Contract | Answer |
|---|---:|---|---|
| Two Litware UK campaigns delivered in 09/2026 with **no invoice row at all** | **649 159 €** | ADV-004 art. 9.2 (120-day billing window) | Still recoverable — **time-barred on 28 January 2027** |

> The generator reports this as **6** and the test asserts **2** — same finding, two
> grains. `fact_billing` is keyed on campaign × media owner × month, so 2 campaign-months
> across 3 media owners means 6 omitted invoice rows.

Neither side alone is useful. The data says *"an invoice is missing."* The contract says
*"you have 120 days."* Only the two together say *"649 k€, deadline 28 January."*

Every percentage above is **exact by construction**, not approximate. The generator
normalises its daily weight vectors so each placement lands precisely on
`planned × ratio`. That matters: in the room, the number has to survive being checked
by hand on a napkin.

---

## Why the boundary is a commercial argument, not a preference

For a French advertising engagement this is not a design preference, it is the
commercial argument: under the transparency regime governing advertising purchasing
(loi n° 93-122 of 29 January 1993, extended to programmatic), an agency has to be able
to show *how* a figure was produced. A number computed inside a language model cannot
be shown. A number computed in DAX can.

---

## Running a single step

Every folder is a real Python package, so a script is run as a module **from the
repository root**, which is what puts the root on `sys.path`:

```bash
python -m fabric.lakehouse.deploy_lakehouse
python -m foundry.verify_foundry
```

`python fabric/lakehouse/deploy_lakehouse.py` does *not* work, deliberately: the
alternative was a `sys.path` fix-up copy-pasted into all 22 scripts. `deploy_all.py`
lives at the root precisely so `python deploy_all.py` needs no such ceremony.

`config.yaml` and `state.json` are gitignored — they carry tenant, capacity and
item GUIDs. `state.example.json` shows the shape; every ID in it is written by a
`deploy_*.py` step, never by hand.

---

## Dataset facts

| Fact | Value |
|---|---|
| Generator seed | 42 — same input, same bytes |
| Period covered | 2026-04-01 → 2027-03-31 (Q2 + Q3 active) |
| Campaigns | 80 across 5 advertisers, 10 brands, 5 markets |
| Delivery rows | 21 960 daily rows |
| Pacing events | 20 160 hourly rows with a trailing 7-day pacing index |
| Currency | EUR throughout, including the UK market (deliberate simplification) |
| Language | English throughout — contracts, code and docs. The French transparency law is cited *in* the contracts (ADV-005) where it belongs, not used as the document language |

---

## What it demonstrates

1. **A classic BI baseline** — plan vs delivery vs billing across five advertisers,
   five markets, seven channels, two quarters.
2. **Fabric IQ** — one ontology gives *campaign*, *delivery* and *market* a single
   definition, shared by the report, the Data Agent and the graph. Batch facts and the
   real-time pacing stream hang off the **same entity**.
3. **A Fabric Data Agent** — natural-language questions answered in DAX, with the query
   visible.
4. **Foundry orchestration** — an agent that calls the Fabric Data Agent as a *tool* and
   the contract corpus as a *knowledge source*, then reconciles them.
5. **The seam neither product covers** — the contractual consequence of a data finding.

---

## Public-repo hygiene

Written to be publishable. The agency is **Zava Media**; the advertisers are Microsoft's
canonical fictional companies (Contoso, Fabrikam, Northwind, Litware, Adventure Works);
the media owners are invented. Every contract opens with a fictional-document notice, and
a test enforces that notice. No real GUID, endpoint, customer name or account path
appears anywhere.

Verified with the umbrella scanner:

```bash
python ../Azure-Brain/Meta-Brain/tools/scan_public_safety.py .
```
