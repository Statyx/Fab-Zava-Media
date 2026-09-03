# `design/contracts/` — the contract corpus

5 framework contracts between Zava Media and its advertisers. English, fictional, and
written so that each one answers a different question about the same pacing anomaly.

| File | Advertiser | The clause that matters |
|---|---|---|
| `ADV-001-contoso-mobility.md` | Contoso Mobility | a make-good clause **exists** for over-delivery |
| `ADV-002-fabrikam-beauty.md` | Fabrikam Beauty | under-delivery triggers a 2 % penalty |
| `ADV-003-northwind-foods.md` | Northwind Foods | — no anomaly in the dataset; the control case |
| `ADV-004-litware-retail.md` | Litware Retail | compensation for over-delivery is **expressly excluded** |
| `ADV-005-adventureworks-travel.md` | AdventureWorks Travel | an unreported variance is itself a breach of mandate |

## Why this folder is a specification, not data

These files are uploaded to Foundry IQ and retrieved verbatim by the Zava-Media-Contracts
agent. That agent is forbidden from producing figures — a test asserts it — because the
demo's whole point is the split: the Fabric data agent answers *how big is the gap*, the
contracts agent answers *what the contract says about it*, and neither one answers alone.

Contoso and Litware are the pair that makes it land: same over-delivery, opposite
contractual outcome. A model that guesses from the number alone gets one of them wrong.
