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
