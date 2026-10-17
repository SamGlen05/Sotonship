"""Stage 1: Global Fishing Watch API v3 (non-commercial use only; attribution required).

For each IMO: resolve GFW vessel ids (identity + flag/name history), then fetch
worldwide AIS gaps, encounters, loitering and port visits. Raw JSON responses are
written once to data/raw/gfw/ and logged in data/raw/manifest.jsonl.

Needs GFW_API_TOKEN in .env (never printed or logged).
Checked against the live API on 2026-10-17: identity history (name, flag, MMSI with
transmission dates) and port visits / gaps / loitering are current to mid-October 2026;
tanker-to-tanker encounters are not in the public encounters dataset.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

from sfp.paths import INTERIM, ROOT, RAW

BASE = "https://gateway.api.globalfishingwatch.org/v3"
EVENT_DATASETS = {
    "ais_gap": "public-global-gaps-events:latest",
    "encounter": "public-global-encounters-events:latest",
    "loitering": "public-global-loitering-events:latest",
    "port_visit": "public-global-port-visits-events:latest",
}
OUT = RAW / "gfw"


def _session() -> requests.Session:
    load_dotenv(ROOT / ".env")
    tok = os.environ.get("GFW_API_TOKEN")
    if not tok:
        raise SystemExit("GFW_API_TOKEN missing from .env (get one at globalfishingwatch.org/our-apis/tokens)")
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


def _log(path, url):
    with open(RAW / "manifest.jsonl", "a") as m:
        m.write(json.dumps({"file": str(path.relative_to(RAW)), "url": url,
                            "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "bytes": path.stat().st_size}) + "\n")


def _get(s, method, url, **kw):
    for attempt in range(5):
        r = s.request(method, url, timeout=60, **kw)
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def search_imo(s, imo: str) -> dict:
    path = OUT / "identity" / f"{imo}.json"
    if path.exists():
        return json.loads(path.read_text())
    url = f"{BASE}/vessels/search"
    params = {"query": imo, "datasets[0]": "public-global-vessel-identity:latest",
              "includes[0]": "MATCH_CRITERIA", "includes[1]": "OWNERSHIP"}
    data = _get(s, "GET", url, params=params)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    _log(path, url + f"?query={imo}")
    return data


def vessel_ids(identity: dict, imo: str) -> list[str]:
    """Every GFW vessel id (one per MMSI period) whose self-reported or registry IMO matches."""
    ids = []
    for e in identity.get("entries", []):
        reg = any(str(r.get("imo") or "") == imo for r in e.get("registryInfo", []))
        for sr in e.get("selfReportedInfo", []):
            if str(sr.get("imo") or "") == imo or reg:
                ids.append(sr["id"])
    return sorted(set(ids))


def fetch_events(s, imo: str, ids: list[str], start: str, end: str) -> None:
    for kind, ds in EVENT_DATASETS.items():
        path = OUT / "events" / kind / f"{imo}.json"
        if path.exists() or not ids:
            continue
        url, offset, rows = f"{BASE}/events", 0, []
        while offset is not None:
            body = {"datasets": [ds], "vessels": ids[:50], "startDate": start, "endDate": end}
            d = _get(s, "POST", url, params={"limit": 200, "offset": offset}, json=body)
            rows += d.get("entries", [])
            offset = d.get("nextOffset")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"imo": imo, "vessel_ids": ids, "start": start, "end": end, "entries": rows}))
        _log(path, f"{url} datasets={ds} start={start} end={end}")


def tanker_imos() -> list[str]:
    """Every tanker IMO we know of: sanctions lists, Danish AIS, OpenSanctions records."""
    m = pd.read_parquet(INTERIM / "vessel_master.parquet")
    imos = set(m[m.is_tanker].imo)
    osv = pd.read_parquet(INTERIM / "os_vessels.parquet")
    imos |= set(osv[osv.type.str.contains("tank", case=False, na=False)].imo.dropna())
    return sorted(imos)


def main():
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--limit", type=int, default=None, help="max IMOs (develop on a few first)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    s = _session()
    imos = tanker_imos()[: a.limit]
    print(f"fetching {len(imos)} tanker IMOs, {a.start} to {a.end}", flush=True)
    done = {"n": 0, "fail": 0}

    def one(imo):
        try:
            ident = search_imo(s, imo)
            fetch_events(s, imo, vessel_ids(ident, imo), a.start, a.end)
        except Exception as e:  # keep going; a rerun resumes (files are written once)
            done["fail"] += 1
            print(f"FAIL {imo}: {e.__class__.__name__} {str(e)[:120]}", flush=True)
        done["n"] += 1
        if done["n"] % 100 == 0:
            print(f"{done['n']}/{len(imos)} (failed {done['fail']})", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, imos))
    print(f"GFW_DONE {done['n']} imos, {done['fail']} failed", flush=True)


if __name__ == "__main__":
    main()
