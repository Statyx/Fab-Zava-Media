#!/usr/bin/env python3
"""
Batch-ingest pacing_events.csv into the Eventhouse KQL table, then verify the count.

Idempotent by construction: the table is cleared before ingest, so re-running this
leaves exactly one copy of the trailing pacing window rather than appending a second.
"""
import os, sys, time
from platform_env import bootstrap
bootstrap()

from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from helpers import (load_config, load_state, get_kusto_token, kusto_mgmt,
                     kusto_streaming_ingest, print_step)

RAW = Path(__file__).parent.parent / "data" / "raw"
CHUNK = 5000   # rows per streaming-ingest call (the API caps a request at ~4 MB)
TS_COL = 0     # pacing_events.timestamp — first column, per config.yaml kql_tables


def shift_window_to_now(rows):
    """Slide the pacing window so its newest row lands on the current hour.

    The generated CSV is anchored on the quarter end, which sits in the future for
    most of the quarter — every `ago(...)` query and the ontology's TimeSeries
    binding on Campaign then read as empty. Re-anchoring here rather than in
    generate_data.py keeps the committed CSV deterministic while making each
    deploy land a window that ends "now". Relative spacing is preserved, so the
    planted pacing anomalies survive the shift untouched.
    """
    if not rows:
        return rows, None
    stamps = [datetime.fromisoformat(r.split(",", 1)[0]) for r in rows]
    newest = max(stamps)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if newest.tzinfo is None:
        now = now.replace(tzinfo=None)
    delta = now - newest
    shifted = [ts + delta for ts in stamps]
    out = [f"{ts.isoformat()},{r.split(',', 1)[1]}" for ts, r in zip(shifted, rows)]
    return out, (min(shifted), max(shifted), delta)


def ingest_csv(quri, ktok, db, table):
    path = RAW / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — run `python src/generate_data.py` first.")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    data = lines[1:]  # drop the header — Kusto CSV ingestion does not skip it
    data, window = shift_window_to_now(data)
    if window:
        lo, hi, delta = window
        print(f"   window re-anchored by {delta.days}d {delta.seconds // 3600}h "
              f"-> {lo:%Y-%m-%d %H:%M} .. {hi:%Y-%m-%d %H:%M} UTC")
    for i in range(0, len(data), CHUNK):
        kusto_streaming_ingest(quri, ktok, db, table, "\n".join(data[i:i + CHUNK]) + "\n")
        print(f"   sent {min(i + CHUNK, len(data)):,}/{len(data):,}")
    return len(data)


def row_count(quri, ktok, db, table):
    r = requests.post(f"{quri}/v1/rest/query",
                      headers={"Authorization": f"Bearer {ktok}",
                               "Content-Type": "application/json; charset=utf-8"},
                      json={"db": db, "csl": f"{table} | count"}, timeout=60)
    try:
        return r.json()["Tables"][0]["Rows"][0][0]
    except Exception:
        return "?"


def main():
    cfg = load_config(); state = load_state()
    quri = state["query_service_uri"]
    db = state.get("kql_db_name") or cfg["eventhouse_name"]
    ktok = get_kusto_token(quri)

    tables = [t["name"] for t in cfg["kql_tables"].values()]

    print_step(1, 2, f"Ingest {len(tables)} KQL table(s) into '{db}' (clear + streaming)")
    sent = {}
    for name in tables:
        try:
            kusto_mgmt(quri, ktok, db, f".clear table {name} data")
        except Exception:
            pass
        sent[name] = ingest_csv(quri, ktok, db, name)
        print(f"   {name}: sent {sent[name]:,} rows")

    print_step(2, 2, "Verify row counts (after ingest settles)")
    time.sleep(20)
    ok = True
    for name in tables:
        cnt = row_count(quri, ktok, db, name)
        flag = "" if cnt == sent[name] else "   ⚠ mismatch"
        if cnt != sent[name]:
            ok = False
        print(f"   {name}: {cnt} rows in KQL (sent {sent[name]:,}){flag}")

    if not ok:
        print("\n⚠  Counts differ — streaming ingestion can lag a few seconds. "
              "Re-check before demoing; if it persists, the table schema and the CSV "
              "column order have diverged (they must match exactly).")
    print("\nOK. Next: deploy_ontology.py")


if __name__ == "__main__":
    main()
