# App spec — Zava Media Cockpit

A browser-only cockpit over the Zava Media demo: Fabric answers *how much*, Foundry answers
*what the contract says*, and the screen states which one answered.

This spec is **not a design exercise**. Almost every decision below was already made, paid for
and shipped in two applications that exist on disk. What follows is a port with the domain
swapped, plus the handful of decisions that are genuinely new to Zava.

---

## 0. Read these before writing a screen

`Apps-Brain/agents/app-frontend-agent/design_tokens.md` §8 opens with a correction that applies
directly here:

> Building from §1–§7 alone yields a flat white-card app that is not our house style. […] Before
> writing a single screen, open `Fab-Marketing-Campaign/app-v2/src` and read `main.css`,
> `components/AppShell.tsx`, `components/KpiCard.tsx`, `hooks/useTheme.ts`. Copy that system.

So, in order:

| # | Read | For |
|---|---|---|
| 1 | `Fab-Marketing-Campaign/app-v2/src/main.css` | the two colour layers, `.glass`, the mesh, the dark retrofit block |
| 2 | `Fab-Marketing-Campaign/app-v2/src/components/AppShell.tsx` | 84 px header, `cover` mode, the provenance footer |
| 3 | `Fab-Marketing-Campaign/app-v2/src/data/personas.ts` | the accent palette and the *shape* of a registry — but **not** the persona model, superseded in §4 |
| 4 | `Fab-Network-Operations/app/src/` | the newer split, and the model that shipped: `WorkspaceLayout`, `AssistantRail`, `domain/nav.ts`, `domain/openers.ts` |
| 5 | `Apps-Brain/agents/app-frontend-agent/app_shell_blueprint.md` | the distilled rules, and `known_issues.md` #15–#20 for why each exists |
| 6 | `fabric/powerbi/deploy_semantic_model.py` | measures l. 82–356 and — easy to skip, expensive to miss — **relationships l. 368–392** |

Nothing in this spec supersedes those files. Where this spec and the shipped app disagree, the
shipped app is right and this spec has a bug.

---

## 1. Runtime

**Fabric App on Rayfin**, static SPA, brokered auth — the default in
`Apps-Brain/agents/fabric-apps-agent`. Same shape as `app-v2/rayfin/rayfin.yml`.

No server, no database. Two transports only:

- **Power BI `executeQueries`** against `SM_Zava_Media` for every figure (DAX, sub-second).
- **Foundry A2A** against the `Zava-Media-Agent` supervisor for every explanation.

Deviate to `operations-portal-agent` (FastAPI + static) only if a Power BI embed or an RTI tile
becomes the centre of gravity. It is not, today: the pacing story is one panel, not the product.

**Region.** Sweden Central, capacity and Foundry project matching. The hosting region stays off
screen — it is infrastructure trivia during a demo and belongs on `/diagnostic`.

---

## 2. Route manifest

| Path | Screen | Auth | Listed in nav |
|---|---|---|---|
| `/auth` | sign-in | public, redirects when signed in | no |
| `/` | cover | required | — (it *is* the nav) |
| `/portefeuille` | portfolio measures, ontology paths | required | yes, header pills |
| `/livraison` | delivery vs plan, the three regimes, pacing | required | yes, header pills |
| `/contrats` | the five master agreements — **no figures** | required | yes, header pills |
| `/facturation` | delivered-not-billed, the grain panel, rebates | required | yes, header pills |
| `/architecture` | the chain and the boundary rule | required | yes, secondary row |
| `/diagnostic` | connectivity proof | **outside the guard** | **no** |
| `/preview/*` | the same screens without a tenant | **DEV only** | no |
| `*` | → `/` | — | — |

`/diagnostic` is unlisted and unguarded on purpose. It is the only screen that reports *which*
link in the chain failed, and it has to answer when sign-in itself is what broke. Delisting is
not deleting — `known_issues.md` #19.

`/preview` is guarded by `import.meta.env.DEV`, which is **statically false** in a production
build: the subtree is dropped at bundle time rather than merely hidden. Screens can be iterated
on without a tenant, and cannot be reached once shipped.

There is exactly **one** navigation. The blueprint's failure mode #15 is two navigations over
the same subject: in `app-v2` a four-step arc held every chart and no chat while four personas
held every chat and no chart. Do not reintroduce it under another name (no "Parcours", no
"Étapes", no "Scénarios" row).

---

## 3. Shell invariants

Ported verbatim from `AppShell.tsx` and `main.css`. Do not re-derive.

| Decision | Value | Why |
|---|---|---|
| `html { font-size }` | **115 %** | read off a projector from several metres; every size in `rem` so one dial moves everything. Never a `px` font-size. |
| Header | 84 px, `sticky top-0 z-30` | — |
| Header background | `var(--header-bg)` + `blur(24px)` | **dark in both themes** — the one fixed anchor while the page repaints |
| Content width | `max-w-[1400px]` wide / `max-w-6xl` column | cover and cockpit want width; utility screens read better in a column |
| Cockpit grid | `content: 1fr` + assistant rail **22 rem** (24 rem at `xl`) | a fraction *shares* growth, a rail *assigns* it — #16 |
| Cards | `.glass rounded-xl` | never `bg-white` |
| Dark mode | `data-theme` on `<html>`, pre-mount inline script, `try/catch` around `localStorage` | storage is partitioned and sometimes refused inside the Fabric iframe |
| Colours | `var(--…)` only | two layers: Tailwind ramp *and* the surface variables |

`--bg-secondary` (page) and `--bg-card-solid` (card) **must differ**, or cards dissolve into the
page and only their borders draw them. Guard it:

```ts
expect(readVar(lightVars, '--bg-secondary')).not.toBe(readVar(lightVars, '--bg-card-solid'));
```

---

## 4. Sections, not personas

**This section supersedes the persona model.** The port started from
`app-v2/src/data/personas.ts`, but the generation that actually shipped — the
`Fab-Network-Operations` console — had already abandoned it, and for a reason worth restating:
a persona is a claim about *who is asking*, and the app cannot verify it. Four icons imply four
systems and there is one. Worse, it forces every question to be filed under a job title, when
the question a demo needs is filed under a **subject**.

So the four "personas" are **sections**, and the routing key is not a person but an
`OpenerFamily`:

| Family | Section | Focus anchor | Owns |
|---|---|---|---|
| `portfolio` | `/portefeuille` | `mesures` | portfolio measures over the period |
| `graph` | `/portefeuille` | `relations` | the advertiser-via-brand traversal |
| `delivery` | `/livraison` | `ecarts` | delivery vs plan by market, clickable rows |
| `pacing` | `/livraison` | `pacing` | CTR / eCPM, and the deliberate absence of GRP |
| `contract` | `/contrats` | `regimes` | the five master agreements, three remedy regimes |
| `billing` | `/facturation` | `manquants` | delivered-not-billed, the forfeiture window |

Two consequences that are easy to lose:

- **Six families, four sections.** `graph` and `pacing` do not get a route of their own; they
  get an *anchor* inside one. A family is a question shape, not a page, and inventing a page per
  family is how the second navigation grows back.
- **The mapping is total.** `SECTION_BY_FAMILY` and `FOCUS_BY_FAMILY` are
  `Record<OpenerFamily, string>`, so a new family is a type error rather than a card that
  navigates nowhere. `domain.test.ts` additionally asserts every target is a route the nav
  actually carries — a family pointing at an unlisted path strands the reader: the card
  navigates, the rail highlights nothing, and there is no way back.

Section accents are the house accents from `app-v2/src/data/personas.ts`, reused unchanged —
the palette survived the model change, the taxonomy did not.

---

## 5. The question registry — two registers, one selector

Every clickable figure carries **two strings**, and they are not the same string:

- `prompt` — what is sent. Names its table and its column explicitly.
- `label` — what is shown. Business language, no identifier.

This is not politeness. `app-v2` records three correct answers to "how many at risk"
(800 / 825 / 593) depending on the column read: an unscoped question is **under-specified, not
unstable**. Zava has the same trap, sharper — see §6.

Registry shape (`domain/openers.ts`):

```ts
export type OpenerFamily =
  | 'portfolio' | 'delivery' | 'pacing' | 'graph' | 'contract' | 'billing';
export type OpenerKind = 'mixed' | 'single';

export interface Opener {
  id: string;
  family: OpenerFamily;
  kind: OpenerKind;     // 'mixed' = needs both the model and the corpus
  label: string;        // shown — business language, never an identifier
  prompt: string;       // sent — names table and column
  exercises: string;    // what this question is here to prove
}
```

`HOUSE_STYLE` is a single exported constant appended to **every** prompt. It restates, in the
agent's own register, what `foundry/verify_foundry.py` enforces — so the contract is stated once
and the answer contract in §7 has something to check against. Per-question style instructions
drift; a shared constant cannot.

### Selection

```ts
selectOpeners(pool)   // one per family, in registry order — full coverage
starters(pool)        // selectOpeners(pool).slice(0, 3) — cover FIRST, then cap
followUps(asked, pool)
```

The order matters and is the single most expensive lesson in the blueprint. **Never `slice(0, n)`
on the raw list.** A cap over an ordered list does not sample it, it truncates it — and in
`app-v2` that silently removed the entire ontology capability from every set of openers, with
nothing failing to say so (#17). `starters` slices the *covered* selection, so the cap can drop a
family but can never drop it systematically.

Two invariants are pinned in `domain.test.ts` rather than left to review:

- every family is reachable from `selectOpeners`;
- at least one `mixed` question appears in the first three.

The second is the demo's whole argument: if the opening three are all single-source, the first
thing the room sees is a dashboard.

### The questions that must exist

Bind each to the artefact it is expected to reach. *Expected, never guaranteed* — the agent picks
its own route at runtime and the badge under the answer is the only statement of what happened.

| `expects` | Question (label) | Reaches |
|---|---|---|
| `model` | Écart de livraison par marché au T3 | `[Delivery vs Plan %]`, `[Planned Impressions]`, `[Delivered Impressions]` |
| `model` | Combien de campagnes ont sur-livré, combien ont sous-livré | `[Over-delivered Campaigns]`, `[Under-delivered Campaigns]` |
| `model` | L'écart entre ce qui a été dépensé et ce qui a été facturé | `[Billing vs Spend Gap (EUR)]` |
| `model` | Le CPM effectif par levier | `[Effective CPM (EUR)]` |
| `ontology` | Quelle régie porte les campagnes en écart | `MediaOwner ← Invoice → Campaign → Market`, 3 hops |
| `ontology` | Quelles marques appartiennent à cet annonceur | `AdvertiserHasBrand` |
| `ontology` | Quelles factures sont en litige, et pour quelles campagnes | `InvoiceForCampaign`, `invoice_status = 'Disputed'` |
| `contract` | Que prévoit le contrat en cas d'écart de livraison | corpus, articles 6.x |
| `contract` | Sous quel délai une facture omise devient irrécouvrable | corpus, article 9.2 |
| **`mixed`** | **Quels marchés s'écartent au T3, et que prévoit le contrat en face** | both subordinates |
| **`mixed`** | **Qu'est-ce qui a été diffusé et jamais facturé, et jusqu'à quand est-ce réclamable** | both subordinates |

**The first click must be `mixed`.** A supervisor with one reachable source is a relay: every
question becomes a forty-second pass-through with nothing to cross-reference. The `mixed`
questions are the only staging where the supervisor visibly supervises.

Two ontology traps to respect, both from `fabric/data_agent/deploy_data_agent.py`:

- The advertiser is reached **through the brand** (`Advertiser → Brand → Campaign`). The direct
  path is deliberately absent from the model.
- The first canned questions in the marketing demo all *looked* relational and none of them left
  the semantic model. A question that merely looks like a graph question is not one. Copy the
  phrasings from `FEWSHOTS` rather than rewriting them.

---

## 6. Panels — every figure is a named measure

Nothing is recomputed client-side. The app must not be able to silently disagree with
`Zava_Media_Report`. Each KPI carries the measure that produced it in a `title`, never printed
under the card: twenty English identifiers on screen read as instrumentation to a business
audience (`design_tokens.md` §8.7).

**Direction** — `[Total Campaigns]`, period from `dim_date`, 5 indexed agreements,
`[Over-delivered Campaigns]` + `[Under-delivered Campaigns]`; then the three remedy cards and the
unbilled callout.

**Livraison** — `fact_delivery` row count, `pacing_events` row count,
markets outside tolerance and max variance from `[Delivery vs Plan %]`; then a diverging bar per
market, centred on the guaranteed target.

**Contrats** — 5 agreements, 3 remedy regimes, the 120-day claim window, and **zero figures
produced**, by construction.

**Facturation** — `[Billing vs Spend Gap (EUR)]`, the campaigns concerned, the omitted rows, the
forfeiture date.

### The grain trap is a feature, show it

`fact_billing` is *stored* at **campaign × media owner × month**, and the naive reading of that
is "group by all three". **The semantic model does not allow it.**

`deploy_semantic_model.py` (l. 368–392) wires `fact_delivery` to four dimensions —
`dim_campaign`, `dim_channel`, `dim_media_owner`, `dim_date` — but wires `fact_billing` to only
**two**: `dim_campaign` and `dim_media_owner`. There is **no relationship to `dim_date`**, and
every relationship is `oneDirection`.

The consequence is not cosmetic. Slicing by month filters the *spend* and leaves the *billing*
unfiltered, so the gap grows with every month added to the selection — a number that is wrong in
a way that looks like a finding. Nothing errors.

So the only queryable grain is **campaign × media owner**: 2 campaigns × 3 media owners =
**six** rows for **two** campaigns. Both numbers are correct; they answer different questions.
The generator reports 6, the test asserts 2.

`GRAIN_DAX` therefore returns the six rows and **derives both counts client-side** in `mapGrain`.
That is deliberate: asking the model for the two counts as two separate measures lets them drift
apart, which is precisely the failure the panel exists to make visible.

Put both on screen, side by side, each labelled with its grain. This is the cheapest possible
demonstration that a question which does not name its table is under-specified — and it costs one
panel.

### What is exact

Only these are ground truth, locked by the test suite. Everything else must be read from a
measure at runtime or not shown at all.

| Case | Figure | Article | Consequence |
|---|---|---|---|
| Contoso Mobility × Spain × Q3 | **+12,00 %** | ADV-001 art. 6.1–6.2 | not billable, plus a 50 % make-good of the excess, within 45 days, without the client asking |
| Litware Retail × UK × Q3 | **+11,00 %** | ADV-004 art. 6.3 | nothing — compensation, credit and carry-over expressly excluded |
| Fabrikam Beauty × Italy × Q3 | **−8,00 %** | ADV-002 art. 6.2 | 2 % penalty on net media budget, owed by the agency, without formal notice |
| 2 UK campaigns never billed | **649 159 €** | ADV-004 art. 9.2 | 120-day window, forfeited 28/01/2027 |

Three variances of the same order, three opposite outcomes. That contrast **is** the demo; the
app's job is to make it land in one click.

---

## 7. The answer contract, mirrored client-side

`foundry/verify_foundry.py :: check_answer_contract` already enforces this server-side. The app
renders the same contract, so a violation is visible rather than merely logged.

- Exactly **one** `### SOURCE` marker. Two locations are read as two presentations and both get
  filled.
- Prose ≤ 30 lines, SOURCE block ≤ 6 lines.
- **No identifiers in the prose** — no bracketed measure, no backticked token, no `dim_`/`fact_`
  table, no literal value set, no comparison operator. They go in the SOURCE block.
- No full-precision ratio (`0.xxxxxx`). Percentage only.

Render the SOURCE block in monospace under a rule, muted, with the route badge and the **live**
duration beside it.

Route badges: `Chiffres` · `Graphe de relations` · `Clauses` · `Chiffres + clauses`.

Plain language must not **outrank** an assertion: a declared step is not an observed step. The
badge says what the agent reported firing, not what we hoped it would fire.

---

## 8. Latency — measure before designing

**This is the one genuinely open decision, and it blocks a real design choice.**

The reference app runs 40–160 s, mean 61,5 s, for a supervisor round-trip. The Zava chain has
**never been measured**. Do that first: instrument `verify_foundry.py`'s three probes, record
n ≥ 20 per family, publish the distribution.

Then:

- **< 10 s** → stream, no further work.
- **otherwise, on stage** → replay, under the four conditions of `known_issues.md` #18:
  1. nothing hand-written — every replayed answer captured from a live run;
  2. the replay **declares itself** on screen;
  3. the question list is derived by the UI's own selector, not a separate list;
  4. a miss is fail-safe — normalise case and whitespace **only**, then fall through to live.

The displayed duration is **always** the live one, even in replay. See
`app-v2/src/services/frozen.ts` and `__tests__/frozen.test.ts` for the shape.

---

## 9. Test gate

Each of these exists because the failure it catches was invisible in review. The file names
below are the ones that shipped, not aspirational.

| Test | Asserts |
|---|---|
| `domain.test.ts` | `selectOpeners` covers **every** family; pin the *coverage*, not the count |
| `domain.test.ts` | at least one `mixed` question survives into the first three starters |
| `domain.test.ts` | every `prompt` names a table and a column; no `label` contains an identifier |
| `domain.test.ts` | every `*_DAX` in `queries.ts` cites only measures that exist in `SM_Zava_Media` |
| `domain.test.ts` | `HOUSE_STYLE` is appended to every prompt — one shared constant, never per-question |
| `domain.test.ts` | every family routes to a path the nav actually lists, and has a focus anchor |
| `domain.test.ts` | `/diagnostic` is absent from the navigation |
| `tokens.test.ts` | `--bg-secondary ≠ --bg-card-solid`; the dark ramp defines every `--sev-*`; no inlined severity colour outside the severity module |
| `screens.test.tsx` | `/diagnostic` renders **without** an auth context |
| `screens.test.tsx` | the cover offers a door to every section, and shows a question rather than an identifier |
| `screens.test.tsx` | `ContratsPage` **never imports the query layer** — see below |

The measure test is the one that would be skipped and should not be. A misspelt measure name
does **not** fail loudly inside a `ROW(...)`: it comes back as an empty cell and renders as a
confident `0`. The 32 real measure names are pinned in the test file, so inventing a measure is
a red test rather than a plausible number on stage.

The `ContratsPage` test is deliberately **structural, not visual**. The obvious form —
render the page and assert no digit appears — cannot work: the page quotes clause terms
("50 %", "45 jours", "art. 6.1") which are text, not measurements. A regex over rendered text
would either pass on a page full of KPIs or fail on faithful contract language. What matters is
the wiring: if the module never imports `useDax` or `@/data/queries`, it *cannot* display a
measured figure. That is the load-bearing invariant of the whole demo, and it would otherwise
break silently — because a page with numbers on it looks *better*.

---

## 10. Deployment — one honest caveat

**ARM cannot create the connection consumed by the Fabric data-agent tool.** The tool resolves a
`CustomKeys` connection of category `AzureFabric`; ARM has no such category, the only Fabric
category it accepts (`MicrosoftFabric`) is restricted to AAD/`UserEntraToken`, and the data plane
does not create connections. **An ARM deployment returning 200 is therefore not proof of
success.** A manual portal step stays in the path. Say so in `/architecture` rather than
discovering it on stage.

Two more, same commit, both A2A:

- `properties.audience` must be a **first-class field**. Writing it only under
  `properties.metadata.audience` is accepted, stored, and ignored — the symptom is
  *"Failed to fetch agentic identity access token"* with an empty body.
- The caller needs **Foundry Agent Consumer** on the target project, and propagation returns
  **404** — not 403 — for several minutes: 404, 404, 404, 403, 200.

And before the first Foundry run: open each agent alone in the playground, force each tool to
fire, choose **Always approve**. Approval cannot be completed inside a multi-agent run, and the
error looks exactly like a routing bug.

---

## 11. Frozen vs free to iterate

| Frozen — a shipped app already paid for this | Free to iterate |
|---|---|
| Cover, four sections, unlisted diagnostic | the copy on every screen |
| One navigation | which anchor a family focuses |
| Rail at 22 rem, content at `1fr` | the diverging-bar rendering |
| Three starters, coverage before the cap | which three questions |
| `prompt` + `label`, both registers | their wording |
| 115 % root font size | — |
| Dark header in both themes | the accent per section |
| Colours via tokens only | — |
| Provenance in `title`, never on stage | — |
| The `### SOURCE` contract | — |
| `/contrats` shows no measured figure | everything else on that page |

Fix colours **at the moment screens are merged**, not after: that is when hardcoded `bg-white`
enters, and it is half an app unreadable at night.

---

## 12. Open questions

1. **Latency** (§8) — blocks live-vs-replay. Measure first. Until it is measured,
   `frozen-answers.generated.json` ships **empty**, which is fail-safe: every miss falls through
   to live.
2. **Does the pacing panel earn its place?** RTI is the most spectacular surface and the one that
   needs a warm-up. If it stays, it needs a declared warm-up step in the run sheet.
3. **`.env` is not provisioned.** `.env.example` lists the real variables. Without
   `VITE_SEMANTIC_MODEL_ID` the app renders its structure and no numbers — which is the intended
   failure, but it is not a demo.

---

**What this app does not prove.** Preview surfaces with no announced GA date. Latency never
measured under load. Five contracts — a demonstration corpus, not a document estate. A single
principal. And a deployment path with a manual step in it.
