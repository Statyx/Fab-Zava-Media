# Task Flow — `Zava Media`

The visual map at the top of the workspace list view. It is the first thing a customer sees
when the workspace opens, and it is the only artifact here that explains the shape of the
solution without anyone talking.

## Import it

**There is no REST API for task flows.** They are not a Fabric item type, so `deploy_all.py`
cannot create this — it is a deliberate manual step, not an omission.

1. Open the **Zava Media** workspace → **List view**
2. Task flow area → **Import a task flow**
3. Select `zava_media_taskflow.json`
4. **Assign the items.** The JSON carries tasks and edges only — item assignments and canvas
   positions are not part of the export format, so they do not survive an import.

| Task | Assign |
|---|---|
| Ingest plan, delivery and billing | *(nothing — the CSVs are Files, not items)* |
| Lakehouse | `ZavaMediaLH` |
| CSV to Delta | the setup notebook |
| Live pacing | `RT_Zava_Media` (Eventhouse) + its KQL database |
| Ontology | `ONT_Zava_Media` |
| Semantic model | `SM_Zava_Media` |
| Report | `Zava_Media_Report` |
| Data agent | `Zava_Media_Analyst` |

Run it **after** `deploy_all.py`, or the items do not exist yet to be assigned.

## Two things that will bite

- **One task flow per workspace.** Importing replaces whatever is there. There is no merge.
- **An item belongs to exactly one task.** Assigning it elsewhere moves it; it does not copy.

Unassigning an item never deletes it, and deleting a task never deletes its items — the
canvas is purely visual. Connectors are arrows for humans: they carry no dependency, no
scheduling, and no data flow.

## Why the Foundry agents are not on the canvas

A task flow maps **Fabric items**. `Zava_Media_Contracts` and `Zava_Media_Agent` live in a
Foundry project, in a different resource provider, and cannot be assigned to a task. Drawing
them here would suggest Fabric owns them.

The seam is real and worth showing on a slide instead: Fabric answers *the number*, Foundry
answers *the clause*, and the demo's whole claim is that those come from different systems.
`docs/ARCHITECTURE.md` § 4 has the diagram.
