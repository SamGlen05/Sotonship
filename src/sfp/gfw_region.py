"""Stage 1 (Global Fishing Watch, non-commercial use only): region-based tanker discovery.

The population must not be chosen from sanctions lists (that would select ships by
their future label). So we find vessels by WHERE THEY SAILED, then fetch their
identity history and events. Steps (each cached, resumable, raw written once):

  presence  4Wings AIS presence per vessel per month in each REGION
            (vessel_type other/bunker: GFW files tankers under 'other')
  identity  /vessels/search per IMO: every name/flag/MMSI period + registry records
  events    port visits, AIS gaps, loitering for tanker vessel ids, batched
  lastpos   last 30 days of daily presence cells -> approximate last position

    PYTHONPATH=src python -m sfp.gfw_region presence|identity|events|lastpos|all
"""
import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from sfp.gfw import BASE, _get, _log, _session, search_imo
from sfp.labels import clean_imo
from sfp.paths import INTERIM, RAW

OUT = RAW / "gfw"
# lon_min, lat_min, lon_max, lat_max. Europe and Middle East shipping areas.
REGIONS = {
    "baltic": (9.5, 53.5, 31.0, 66.0),
    "north_sea_channel": (-6.0, 48.0, 9.5, 62.0),
    "norwegian_barents": (4.0, 62.0, 45.0, 74.0),
    "iberia_atlantic": (-15.0, 35.0, -5.0, 48.0),
    "med_west": (-6.0, 35.0, 12.0, 45.0),
    "med_east": (12.0, 30.0, 37.0, 42.0),
    "black_sea": (27.0, 40.5, 42.0, 47.5),
    "red_sea": (32.0, 11.0, 45.0, 30.0),
    "gulf_of_aden": (45.0, 10.0, 52.0, 16.0),
    "persian_gulf_oman": (47.0, 22.0, 60.5, 31.0),
    "arabian_sea": (52.0, 10.0, 70.0, 22.0),
}
START, END = "2024-07-01", "2026-10-01"
TANKER_TYPES = {"TANKER", "BUNKER", "BUNKER_OR_TANKER"}
EVENT_DATASETS = {
    "port_visit": "public-global-port-visits-events:latest",
    "ais_gap": "public-global-gaps-events:latest",
    "loitering": "public-global-loitering-events:latest",
}


def _geo(b):
    x0, y0, x1, y1 = b
    poly = {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}
    return {"geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": poly}]}}


def report(s, params, body):
    """One 4Wings report (only one may run per user). Recovers slow ones via last-report."""
    for attempt in range(8):
        r = s.post(f"{BASE}/4wings/report", params=params, json=body, timeout=300)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 524, 503, 502):
            time.sleep(15 * (attempt + 1))
            lr = s.get(f"{BASE}/4wings/last-report", timeout=120)
            if lr.status_code == 200 and lr.json().get("status") == "finished" and lr.json().get("entries"):
                return lr.json()
            continue
        raise RuntimeError(f"4wings {r.status_code}: {r.text[:300]}")
    raise RuntimeError("4wings report kept failing")


def quarters():
    q = pd.date_range(START, END, freq="QS")
    return [(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")) for a, b in zip(q[:-1], q[1:])] + \
           ([(q[-1].strftime("%Y-%m-%d"), END)] if q[-1] < pd.Timestamp(END) else [])


def presence(s):
    for reg, b in REGIONS.items():
        for a, z in quarters():
            path = OUT / "presence" / f"{reg}_{a}.json"
            if path.exists():
                continue
            params = {"format": "JSON", "group-by": "VESSEL_ID", "temporal-resolution": "MONTHLY",
                      "spatial-aggregation": "true", "datasets[0]": "public-global-presence:latest",
                      "date-range": f"{a},{z}", "filters[0]": "vessel_type in ('other','bunker')"}
            t = time.time()
            d = report(s, params, _geo(b))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(d))
            _log(path, f"{BASE}/4wings/report presence {reg} {a},{z} bbox={b}")
            rows = list((d.get("entries") or [{}])[0].values() or [[]])[0] or []
            print(f"presence {reg} {a}: {len(rows)} rows in {time.time() - t:.0f}s", flush=True)


def presence_table() -> pd.DataFrame:
    rows = []
    for p in sorted((OUT / "presence").glob("*.json")):
        reg = re.match(r"(.+)_\d{4}-\d{2}-\d{2}\.json", p.name).group(1)
        d = json.loads(p.read_text())
        for r in (list((d.get("entries") or [{}])[0].values() or [[]])[0] or []):
            rows.append({"region": reg, "vessel_id": r["vesselId"], "month": r["date"][:7], "hours": r["hours"],
                         "imo_raw": r.get("imo"), "mmsi": r.get("mmsi"), "flag": r.get("flag"),
                         "name": r.get("shipName"), "gfw_type": r.get("vesselType")})
    df = pd.DataFrame(rows)
    df["imo"] = df["imo_raw"].map(clean_imo)
    return df


NOT_TANKER = {"CARGO", "PASSENGER", "FISHING", "TRAWLERS", "SEISMIC_VESSEL", "GEAR", "TUG", "PILOT",
              "SUPPORT", "RESEARCH", "DREDGE", "SQUID_JIGGER", "DRIFTING_LONGLINES", "SET_LONGLINES",
              "POLE_AND_LINE", "TUNA_PURSE_SEINES", "OTHER_PURSE_SEINES", "SET_GILLNETS", "FIXED_GEAR",
              "CARRIER", "REEFER", "PATROL_VESSEL", "PASSENGER_OR_CARGO", "DREDGE_NON_FISHING",
              "SUPPLY_VESSEL", "DIVE_VESSEL", "OTHER_NOT_FISHING", "RESEARCH|SEISMIC_VESSEL"}


def classify(s, batch=50, workers=4):
    """Fast first pass: batched /vessels lookups give each vessel id's registry ship type."""
    pres = presence_table()
    ids = sorted(pres.dropna(subset=["imo"]).vessel_id.unique())
    batches = [ids[i:i + batch] for i in range(0, len(ids), batch)]
    print(f"classify: {len(ids)} vessel ids with IMO, {len(batches)} batches", flush=True)

    def one(args):
        k, b = args
        path = OUT / "classify" / f"batch_{k:05d}.json"
        if path.exists():
            return
        try:
            d = _get(s, "GET", f"{BASE}/vessels", params={"datasets[0]": "public-global-vessel-identity:latest",
                                                          **{f"ids[{i}]": v for i, v in enumerate(b)}})
        except Exception as e:
            print(f"FAIL classify {k}: {str(e)[:120]}", flush=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d))

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, enumerate(batches)))


def classify_table() -> pd.DataFrame:
    """Per IMO: registry ship types seen (union over its vessel ids)."""
    rows = []
    for p in (OUT / "classify").glob("*.json"):
        for e in json.loads(p.read_text()).get("entries", []):
            for x in e.get("selfReportedInfo", []):
                imo = clean_imo(x.get("imo"))
                types = {t for r in e.get("registryInfo", []) for t in (r.get("geartypes") or [])}
                if imo:
                    rows.append({"imo": imo, "types": "|".join(sorted(types))})
    df = pd.DataFrame(rows)
    return df.groupby("imo")["types"].agg(lambda s: "|".join(sorted({t for v in s for t in v.split("|") if t})))


def candidate_imos() -> list[str]:
    """Verified tankers (registry TANKER/BUNKER) plus unverified IMOs (no registry type or only
    NON_FISHING/OTHER). Vessels the registry clearly types as something else are dropped."""
    ct = classify_table()
    keep = []
    for imo, t in ct.items():
        ts = set(filter(None, t.split("|")))
        if ts & TANKER_TYPES or not (ts & NOT_TANKER):
            keep.append(imo)
    return sorted(keep)


def identity(s, workers=4):
    imos = candidate_imos()
    todo = [i for i in imos if not (OUT / "identity" / f"{i}.json").exists()]
    print(f"identity: {len(imos)} candidate tanker IMOs, {len(todo)} to fetch", flush=True)
    n = {"done": 0}

    def one(imo):
        try:
            search_imo(s, imo)
        except Exception as e:
            print(f"FAIL identity {imo}: {str(e)[:120]}", flush=True)
        n["done"] += 1
        if n["done"] % 500 == 0:
            print(f"identity {n['done']}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))


def identity_tables():
    """Per-IMO identity periods and registry facts, for IMOs seen in presence."""
    periods, reg = [], []
    for p in (OUT / "identity").glob("*.json"):
        imo = p.stem
        d = json.loads(p.read_text())
        for e in d.get("entries", []):
            r_imo = [r for r in e.get("registryInfo", []) if str(r.get("imo")) == imo]
            for r in r_imo:
                ex = {}
                for x in r.get("extraFields") or []:
                    if isinstance(x, dict):
                        ex.update(x)
                reg.append({"imo": imo, "geartypes": "|".join(r.get("geartypes") or []), "tonnage_gt": r.get("tonnageGt"),
                            "length_m": r.get("lengthM"), "built_year": ex.get("builtYear"), "operator": ex.get("operator"),
                            "registry_flag": r.get("flag"), "registry_from": r.get("transmissionDateFrom"),
                            "registry_to": r.get("transmissionDateTo")})
            for x in e.get("selfReportedInfo", []):
                if str(x.get("imo")) == imo or r_imo:
                    periods.append({"imo": imo, "vessel_id": x["id"], "name": x.get("shipname"), "flag": x.get("flag"),
                                    "mmsi": x.get("ssvid"), "from": x.get("transmissionDateFrom"),
                                    "to": x.get("transmissionDateTo"), "positions": x.get("positionsCounter")})
    per = pd.DataFrame(periods).drop_duplicates("vessel_id")
    for c in ("from", "to"):
        per[c] = pd.to_datetime(per[c], utc=True, format="ISO8601").dt.tz_localize(None)
    return per, pd.DataFrame(reg)




def fetch_all_events(s, ds, vessel_ids):
    """All pages of one events query. Pagination is defensive: GFW occasionally returns a
    nextOffset that does not advance (seen: 2 after a 1000-row page), which then 422s."""
    import requests
    rows, offset, total = [], 0, None
    while offset is not None:
        try:
            d = _get(s, "POST", f"{BASE}/events", params={"limit": 1000, "offset": offset},
                     json={"datasets": [ds], "vessels": vessel_ids, "startDate": "2024-01-01", "endDate": "2026-10-16"})
        except requests.HTTPError as e:
            if offset and e.response is not None and e.response.status_code == 422:
                break  # keep the pages we have
            raise
        rows += d.get("entries", [])
        total = d.get("total", total)
        nxt = d.get("nextOffset")
        if nxt is None or nxt <= offset or (total is not None and nxt >= total):
            break
        offset = nxt
    return rows


def events(s, batch=25, workers=3):
    per, _ = identity_tables()
    keep = set(candidate_imos())
    pres = presence_table()
    ids = sorted(set(per[per.imo.isin(keep)].vessel_id) | set(pres[pres.imo.isin(keep)].vessel_id))
    batches = [ids[i:i + batch] for i in range(0, len(ids), batch)]
    print(f"events: {len(keep)} tanker IMOs, {len(ids)} vessel ids, {len(batches)} batches", flush=True)
    n = {"done": 0}

    def one(args):
        k, b = args
        key = hashlib.sha1(",".join(b).encode()).hexdigest()[:16]  # content-addressed: safe across reruns
        for kind, ds in EVENT_DATASETS.items():
            path = OUT / "region_events" / kind / f"batch_{key}.json"
            if path.exists():
                continue
            try:
                rows = fetch_all_events(s, ds, b)
            except Exception as e:
                print(f"FAIL events batch {k} {kind}: {str(e)[:120]}", flush=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"vessel_ids": b, "entries": rows}))
            tmp.rename(path)
        n["done"] += 1
        if n["done"] % 50 == 0:
            print(f"events {n['done']}/{len(batches)}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, enumerate(batches)))
    (OUT / "region_events" / "_retrieved.json").write_text(json.dumps(
        {"retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "batches": len(batches)}))


def lastpos(s):
    end = pd.Timestamp(END)
    a = (end - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    for reg, b in REGIONS.items():
        path = OUT / "lastpos" / f"{reg}_{a}.json"
        if path.exists():
            continue
        params = {"format": "JSON", "group-by": "VESSEL_ID", "temporal-resolution": "DAILY",
                  "spatial-resolution": "LOW", "datasets[0]": "public-global-presence:latest",
                  "date-range": f"{a},{END}", "filters[0]": "vessel_type in ('other','bunker')"}
        d = report(s, params, _geo(b))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d))
        _log(path, f"{BASE}/4wings/report lastpos {reg} {a},{END}")
        print(f"lastpos {reg} done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["presence", "classify", "identity", "events", "lastpos", "all"])
    a = ap.parse_args()
    s = _session()
    steps = ["presence", "classify", "identity", "events", "lastpos"] if a.step == "all" else [a.step]
    for st in steps:
        print(f"== {st}", flush=True)
        {"presence": presence, "classify": classify, "identity": identity, "events": events, "lastpos": lastpos}[st](s)
    print("GFW_REGION_DONE", flush=True)


if __name__ == "__main__":
    main()
