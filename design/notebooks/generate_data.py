#!/usr/bin/env python3
"""
Generate synthetic media-agency data for the Zava Media demo.

Zava Media is a fictional media agency. It plans, buys and reconciles media
investment for five fictional advertisers across five European markets.

Produces:
  Reference / plan / actuals (Lakehouse, NonTimeSeries binding)
      artifacts/lakehouse_data/dim_advertiser.csv     artifacts/lakehouse_data/dim_brand.csv
      artifacts/lakehouse_data/dim_market.csv         artifacts/lakehouse_data/dim_channel.csv
      artifacts/lakehouse_data/dim_media_owner.csv    artifacts/lakehouse_data/dim_campaign.csv
      artifacts/lakehouse_data/dim_date.csv
      artifacts/lakehouse_data/fact_plan.csv          artifacts/lakehouse_data/fact_delivery.csv
      artifacts/lakehouse_data/fact_billing.csv
  Live pacing (Eventhouse, TimeSeries binding)
      artifacts/lakehouse_data/pacing_events.csv

The whole demo turns on the PLANNED -> DELIVERED -> BILLED triangle, with
anomalies planted from config so the agent has something real to find:

  * Contoso Mobility / Spain / Q3   -> +12% impressions for the same spend
  * Fabrikam Beauty  / Italy  / Q3  ->  -8% impressions (under-delivery)
  * Litware Retail   / UK     / Q3  -> +11%, but its contract has NO make-good
                                       clause -> same numbers, different answer
  * Litware Retail   / UK     / Sep -> delivered, never invoiced (anti-join)

Daily series are NORMALISED so each placement's quarterly total lands exactly
on its ratio. That matters: the percentage the agent reports must be
reproducible by hand, or the demo cannot be challenged in the room.

Deterministic (seeded) - re-running yields byte-identical data.
Pure Python + pandas.
"""
import calendar
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fabric._shared.paths import ARTIFACTS as RAW, CONFIG_FILE

# Click-through rate by channel. Offline channels get no clicks.
CTR = {"CH-DV": 0.0085, "CH-SOC": 0.0120, "CH-SEA": 0.0410, "CH-RMN": 0.0065}

# Agency commercial terms per media owner: (agency discount off gross, year-end rebate).
OWNER_TERMS = {
    "MO-001": (0.18, 0.040),
    "MO-002": (0.12, 0.025),
    "MO-003": (0.15, 0.030),
    "MO-004": (0.16, 0.035),
    "MO-005": (0.10, 0.020),
    "MO-006": (0.12, 0.028),
}


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_date(s):
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def months_in(start, end):
    """Ordered list of 'YYYY-MM' month keys covered by [start, end]."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def normalised_weights(rng, n, weekday_of):
    """n positive weights summing to exactly 1.0.

    Carries a weekday effect so the daily curve looks like media delivery
    rather than white noise, then renormalises. Renormalising is what makes
    the quarterly total land exactly on its target ratio.
    """
    # Mon..Sun - media delivery dips at the weekend on most channels.
    weekday_factor = [1.05, 1.08, 1.06, 1.04, 1.00, 0.82, 0.78]
    raw = [weekday_factor[weekday_of(i)] * rng.uniform(0.85, 1.15) for i in range(n)]
    total = sum(raw)
    return [w / total for w in raw]


# ──────────────────────────────────────────────────────────────────
# Reference dimensions
# ──────────────────────────────────────────────────────────────────
def build_reference(cfg):
    df_adv = pd.DataFrame([
        {"advertiser_id": a["id"], "advertiser_name": a["name"], "legal_entity": a["legal_entity"],
         "industry": a["industry"], "hq_market_id": a["hq_market"],
         "account_director": a["account_director"]}
        for a in cfg["advertisers"]])

    df_brand = pd.DataFrame([
        {"brand_id": b["id"], "brand_name": b["name"], "advertiser_id": b["advertiser_id"],
         "category": b["category"]}
        for b in cfg["brands"]])

    df_market = pd.DataFrame([
        {"market_id": m["id"], "market_name": m["name"], "country_code": m["country_code"],
         "currency": m["currency"], "region": m["region"]}
        for m in cfg["markets"]])

    df_channel = pd.DataFrame([
        {"channel_id": c["id"], "channel_name": c["name"], "channel_group": c["group"],
         "measurement_unit": c["unit"], "rate_card_cpm_eur": c["cpm_eur"],
         "is_grp_channel": bool(c["grp_channel"])}
        for c in cfg["channels"]])

    df_owner = pd.DataFrame([
        {"media_owner_id": o["id"], "media_owner_name": o["name"], "owner_type": o["type"],
         "channels_sold": "|".join(o["channels"]),
         "primary_channel_id": o["channels"][0],
         "agency_discount_pct": round(OWNER_TERMS[o["id"]][0] * 100, 1),
         "rebate_pct": round(OWNER_TERMS[o["id"]][1] * 100, 1)}
        for o in cfg["media_owners"]])

    year = cfg["generation"]["year"]
    rows, d = [], date(year, 1, 1)
    while d.year == year:
        rows.append({
            "date_key": d.isoformat(), "year": d.year, "quarter": f"{d.year}-Q{(d.month - 1) // 3 + 1}",
            "month": f"{d.year:04d}-{d.month:02d}", "month_name": calendar.month_name[d.month],
            "day_of_month": d.day, "week_of_year": d.isocalendar()[1],
            "day_of_week": d.isoweekday(), "day_name": calendar.day_name[d.weekday()],
            "is_weekend": d.isoweekday() >= 6,
        })
        d += timedelta(days=1)
    df_date = pd.DataFrame(rows)

    return {"dim_advertiser": df_adv, "dim_brand": df_brand, "dim_market": df_market,
            "dim_channel": df_channel, "dim_media_owner": df_owner, "dim_date": df_date}


# ──────────────────────────────────────────────────────────────────
# Campaigns + placements
# ──────────────────────────────────────────────────────────────────
def anomaly_markets_for(cfg, advertiser_id):
    """Markets an anomaly targets for this advertiser - always force-selected.

    Without this, the random market draw can drop the market the whole demo
    question is about, and the storyline silently disappears.
    """
    return sorted({a["market_id"] for a in cfg["anomalies"].values()
                   if a.get("advertiser_id") == advertiser_id and a.get("market_id")})


def build_campaigns(cfg, ref):
    gen = cfg["generation"]
    seed = gen["seed"]
    market_ids = [m["id"] for m in cfg["markets"]]
    objectives = cfg["campaign_objectives"]
    brand_to_adv = {b["id"]: b["advertiser_id"] for b in cfg["brands"]}
    brand_name = {b["id"]: b["name"] for b in cfg["brands"]}
    market_code = {m["id"]: m["country_code"] for m in cfg["markets"]}

    channel_ids = [c["id"] for c in cfg["channels"]]
    owners_for_channel = {
        cid: sorted([o["id"] for o in cfg["media_owners"] if cid in o["channels"]])
        for cid in channel_ids
    }

    campaigns, placements = [], []
    seq = 0
    for q in gen["quarters"]:
        q_start, q_end = parse_date(q["start"]), parse_date(q["end"])
        for b in cfg["brands"]:
            adv_id = brand_to_adv[b["id"]]
            rng = random.Random(f"{seed}|markets|{b['id']}|{q['id']}")
            forced = anomaly_markets_for(cfg, adv_id)
            pool = [m for m in market_ids if m not in forced]
            rng.shuffle(pool)
            chosen = sorted(forced + pool[:max(0, gen["markets_per_brand"] - len(forced))])

            for mkt in chosen:
                seq += 1
                cid = f"CMP-{seq:04d}"
                crng = random.Random(f"{seed}|campaign|{cid}")
                objective = objectives[crng.randrange(len(objectives))]
                budget = round(crng.uniform(180_000, 1_450_000), -3)

                campaigns.append({
                    "campaign_id": cid,
                    "campaign_name": f"{brand_name[b['id']]} {market_code[mkt]} {q['id']} {objective}",
                    "advertiser_id": adv_id, "brand_id": b["id"], "market_id": mkt,
                    "objective": objective, "quarter": q["id"],
                    "start_date": q_start.isoformat(), "end_date": q_end.isoformat(),
                    "status": "Closed" if q["id"] < gen["quarters"][-1]["id"] else "Live",
                    "planned_budget_eur": budget,
                })

                # Pick distinct channels, then a media owner that actually sells each.
                chans = channel_ids[:]
                crng.shuffle(chans)
                picked = sorted(chans[:gen["placements_per_campaign"]])
                split = [crng.uniform(0.6, 1.4) for _ in picked]
                tot = sum(split)
                for ch, w in zip(picked, split):
                    owners = owners_for_channel[ch]
                    owner = owners[crng.randrange(len(owners))]
                    placements.append({
                        "campaign_id": cid, "channel_id": ch, "media_owner_id": owner,
                        "quarter": q["id"], "advertiser_id": adv_id, "market_id": mkt,
                        "start_date": q_start, "end_date": q_end,
                        "budget_eur": round(budget * w / tot, 2),
                    })

    return pd.DataFrame(campaigns), placements


# ──────────────────────────────────────────────────────────────────
# Plan
# ──────────────────────────────────────────────────────────────────
def build_plan(cfg, placements):
    seed = cfg["generation"]["seed"]
    cpm = {c["id"]: c["cpm_eur"] for c in cfg["channels"]}
    is_grp = {c["id"]: bool(c["grp_channel"]) for c in cfg["channels"]}

    rows, seq = [], 0
    for p in placements:
        months = months_in(p["start_date"], p["end_date"])
        rng = random.Random(f"{seed}|plan|{p['campaign_id']}|{p['channel_id']}|{p['media_owner_id']}")
        w = [rng.uniform(0.8, 1.2) for _ in months]
        tot = sum(w)
        for month, wi in zip(months, w):
            seq += 1
            budget = p["budget_eur"] * wi / tot
            impressions = budget / cpm[p["channel_id"]] * 1000.0
            rows.append({
                "plan_id": f"PLN-{seq:05d}",
                "campaign_id": p["campaign_id"], "channel_id": p["channel_id"],
                "media_owner_id": p["media_owner_id"], "month": month,
                "planned_budget_eur": round(budget, 2),
                "planned_impressions": int(round(impressions)),
                "planned_grp": round(impressions / 1000.0 * 0.012, 2) if is_grp[p["channel_id"]] else 0.0,
            })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────
# Delivery
# ──────────────────────────────────────────────────────────────────
def resolve_impression_ratio(cfg, placement, rng):
    """The planted ratio if this placement is in an anomaly, else near-1 noise."""
    for name, a in sorted(cfg["anomalies"].items()):
        if "impression_ratio" not in a:
            continue
        if (a["advertiser_id"] == placement["advertiser_id"]
                and a["market_id"] == placement["market_id"]
                and a["quarter"] == placement["quarter"]):
            return float(a["impression_ratio"]), name
    return min(1.06, max(0.94, rng.gauss(1.0, 0.02))), None


def build_delivery(cfg, placements, df_plan):
    seed = cfg["generation"]["seed"]
    is_grp = {c["id"]: bool(c["grp_channel"]) for c in cfg["channels"]}

    plan_by_placement = (df_plan.groupby(["campaign_id", "channel_id", "media_owner_id"])
                         .agg(planned_budget_eur=("planned_budget_eur", "sum"),
                              planned_impressions=("planned_impressions", "sum"))
                         .to_dict("index"))

    rows, tagged = [], []
    for p in placements:
        key = (p["campaign_id"], p["channel_id"], p["media_owner_id"])
        planned = plan_by_placement[key]
        rng = random.Random(f"{seed}|delivery|{'|'.join(key)}")

        impression_ratio, anomaly = resolve_impression_ratio(cfg, p, rng)
        # Over-delivery in media means MORE inventory for the SAME money -
        # spend tracks the plan regardless of what was delivered.
        spend_ratio = min(1.04, max(0.96, rng.gauss(1.0, 0.015)))

        target_spend = planned["planned_budget_eur"] * spend_ratio
        target_impr = planned["planned_impressions"] * impression_ratio

        n_days = (p["end_date"] - p["start_date"]).days + 1
        days = [p["start_date"] + timedelta(days=i) for i in range(n_days)]
        w_spend = normalised_weights(rng, n_days, lambda i: days[i].weekday())
        w_impr = normalised_weights(rng, n_days, lambda i: days[i].weekday())

        ctr = CTR.get(p["channel_id"], 0.0)
        for d, ws, wi in zip(days, w_spend, w_impr):
            impressions = int(round(target_impr * wi))
            rows.append({
                "date_key": d.isoformat(), "campaign_id": p["campaign_id"],
                "channel_id": p["channel_id"], "media_owner_id": p["media_owner_id"],
                "impressions": impressions,
                "clicks": int(round(impressions * ctr)) if ctr else 0,
                "spend_net_eur": round(target_spend * ws, 2),
                "delivered_grp": round(impressions / 1000.0 * 0.012, 2) if is_grp[p["channel_id"]] else 0.0,
            })

        if anomaly:
            tagged.append((anomaly, p["campaign_id"], p["market_id"], impression_ratio))

    return pd.DataFrame(rows), tagged


# ──────────────────────────────────────────────────────────────────
# Billing
# ──────────────────────────────────────────────────────────────────
def build_billing(cfg, df_delivery, df_campaign):
    seed = cfg["generation"]["seed"]
    unbilled = cfg["anomalies"].get("unbilled", {})
    camp_meta = df_campaign.set_index("campaign_id")[["advertiser_id", "market_id"]].to_dict("index")

    d = df_delivery.copy()
    d["month"] = d["date_key"].str.slice(0, 7)
    grouped = (d.groupby(["campaign_id", "media_owner_id", "month"], as_index=False)
               .agg(net=("spend_net_eur", "sum")))
    grouped = grouped.sort_values(["campaign_id", "media_owner_id", "month"]).reset_index(drop=True)

    last_month = max(grouped["month"])
    rows, seq, skipped = [], 0, 0
    for r in grouped.itertuples(index=False):
        meta = camp_meta[r.campaign_id]
        # Planted gap: delivered, never invoiced. Rows are OMITTED, not flagged -
        # finding it has to be a real anti-join, not a status filter.
        if (unbilled and meta["advertiser_id"] == unbilled.get("advertiser_id")
                and meta["market_id"] == unbilled.get("market_id")
                and r.month == unbilled.get("month")):
            skipped += 1
            continue

        seq += 1
        discount, rebate_pct = OWNER_TERMS[r.media_owner_id]
        net = round(float(r.net), 2)
        gross = round(net / (1.0 - discount), 2)
        rebate = round(net * rebate_pct, 2)
        y, m = int(r.month[:4]), int(r.month[5:])
        invoice_date = date(y, m, calendar.monthrange(y, m)[1]) + timedelta(days=15)
        rng = random.Random(f"{seed}|billing|{r.campaign_id}|{r.media_owner_id}|{r.month}")
        if r.month < last_month:
            status = "Paid" if rng.random() > 0.12 else "Issued"
        else:
            status = "Issued"

        rows.append({
            "invoice_id": f"INV-{seq:05d}", "campaign_id": r.campaign_id,
            "media_owner_id": r.media_owner_id, "month": r.month,
            "gross_amount_eur": gross, "net_amount_eur": net,
            "rebate_amount_eur": rebate, "net_net_amount_eur": round(net - rebate, 2),
            "invoice_status": status, "invoice_date": invoice_date.isoformat(),
        })
    return pd.DataFrame(rows), skipped


# ──────────────────────────────────────────────────────────────────
# Live pacing (Eventhouse / TimeSeries binding on Campaign)
# ──────────────────────────────────────────────────────────────────
def build_pacing(cfg, placements, df_plan):
    gen = cfg["generation"]
    seed, days, step = gen["seed"], gen["pacing_days"], gen["pacing_interval_min"]
    last_q = gen["quarters"][-1]
    q_start, q_end = parse_date(last_q["start"]), parse_date(last_q["end"])

    plan_by_placement = (df_plan.groupby(["campaign_id", "channel_id", "media_owner_id"])
                         .agg(planned_budget_eur=("planned_budget_eur", "sum"),
                              planned_impressions=("planned_impressions", "sum"))
                         .to_dict("index"))

    n_steps = int(days * 24 * 60 / step)
    end_dt = datetime(q_end.year, q_end.month, q_end.day, 23, 0, tzinfo=timezone.utc)
    times = [end_dt - timedelta(minutes=step * (n_steps - 1 - k)) for k in range(n_steps)]
    quarter_days = (q_end - q_start).days + 1

    rows = []
    for p in placements:
        if p["quarter"] != last_q["id"]:
            continue
        key = (p["campaign_id"], p["channel_id"], p["media_owner_id"])
        planned = plan_by_placement[key]
        rng = random.Random(f"{seed}|pacing|{'|'.join(key)}")
        ratio, _ = resolve_impression_ratio(cfg, p, random.Random(f"{seed}|delivery|{'|'.join(key)}"))

        # Hourly run-rate the placement should hit to land exactly on plan.
        expected_hourly_impr = planned["planned_impressions"] / (quarter_days * 24.0)
        expected_hourly_spend = planned["planned_budget_eur"] / (quarter_days * 24.0)

        for ts in times:
            hour_factor = 0.55 + 0.75 * (1 - abs(13 - ts.hour) / 13.0)
            jitter = rng.uniform(0.88, 1.12)
            impr = expected_hourly_impr * ratio * hour_factor * jitter
            spend = expected_hourly_spend * hour_factor * rng.uniform(0.94, 1.06)
            rows.append({
                "timestamp": ts.isoformat(), "campaign_id": p["campaign_id"],
                "channel_id": p["channel_id"], "media_owner_id": p["media_owner_id"],
                "impressions_delta": int(round(impr)), "spend_delta": round(spend, 2),
                # >1 = ahead of plan, <1 = behind. The number a trader looks at.
                "pacing_index": round(ratio * jitter, 4),
            })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────
def main():
    cfg = load_config()
    RAW.mkdir(parents=True, exist_ok=True)

    print("Generating Zava Media reference data...")
    ref = build_reference(cfg)

    print("Generating campaigns and placements...")
    df_campaign, placements = build_campaigns(cfg, ref)

    print("Generating plan / delivery / billing...")
    df_plan = build_plan(cfg, placements)
    df_delivery, tagged = build_delivery(cfg, placements, df_plan)
    df_billing, skipped = build_billing(cfg, df_delivery, df_campaign)

    print("Generating live pacing events...")
    df_pacing = build_pacing(cfg, placements, df_plan)

    tables = {
        **ref,
        "dim_campaign": df_campaign,
        "fact_plan": df_plan,
        "fact_delivery": df_delivery,
        "fact_billing": df_billing,
        "pacing_events": df_pacing,
    }
    for name in sorted(tables):
        path = RAW / f"{name}.csv"
        tables[name].to_csv(path, index=False, encoding="utf-8")
        print(f"   {name:20s} {len(tables[name]):>7d} rows -> {path.name}")

    # ── Expected answers, so the operator can challenge the agent ──
    print("\nPlanted anomalies (the agent must find these):")
    by_anomaly = {}
    for name, cid, mkt, ratio in tagged:
        by_anomaly.setdefault(name, {"markets": set(), "campaigns": 0, "ratio": ratio})
        by_anomaly[name]["markets"].add(mkt)
        by_anomaly[name]["campaigns"] += 1
    for name in sorted(by_anomaly):
        a = by_anomaly[name]
        delta = (a["ratio"] - 1.0) * 100.0
        print(f"   {name:24s} {delta:+6.1f}% impressions vs plan  "
              f"({a['campaigns']} placements, markets: {', '.join(sorted(a['markets']))})")
    print(f"   {'unbilled':24s} {skipped} delivered month(s) with NO invoice row (anti-join)")
    print("\nDone.")


if __name__ == "__main__":
    main()
