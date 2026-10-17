"""Stage 1: Global Fishing Watch raw JSON -> tidy interim tables (all keyed on IMO).

  gfw_presence.parquet   imo, region, month, hours (summed over the IMO's vessel ids)
  gfw_identity.parquet   imo, vessel_id, name, flag, mmsi, from, to   (time-bounded periods)
  gfw_registry.parquet   imo, registry ship types, tonnage, length, build year, operator
  gfw_events.parquet     imo, kind, start, end, lat, lon + kind-specific fields
  gfw_lastpos.parquet    imo, date, lat, lon (latest presence cell in the last 30 days)
  gfw_candidates.parquet imo, tanker_status (verified / unverified)
"""
import json

import pandas as pd

from sfp.gfw_region import OUT, TANKER_TYPES, candidate_imos, classify_table, identity_tables, presence_table
from sfp.manifest import write_manifest
from sfp.paths import INTERIM


def events_table(id2imo: dict) -> pd.DataFrame:
    rows = []
    for kind in ("port_visit", "ais_gap", "loitering"):
        for p in sorted((OUT / "region_events" / kind).glob("batch_*.json")):
            for e in json.loads(p.read_text()).get("entries", []):
                vid = (e.get("vessel") or {}).get("id")
                imo = id2imo.get(vid)
                if not imo:
                    continue
                pos = e.get("position") or {}
                r = {"imo": imo, "vessel_id": vid, "kind": kind, "start": e["start"], "end": e["end"],
                     "lat": pos.get("lat"), "lon": pos.get("lon"),
                     "shore_km": (e.get("distances") or {}).get("startDistanceFromShoreKm")}
                if kind == "port_visit":
                    pv = e.get("port_visit") or {}
                    a = pv.get("intermediateAnchorage") or pv.get("startAnchorage") or {}
                    r.update(port_country=a.get("flag"), port_name=a.get("name"), port_id=a.get("id"),
                             at_dock=a.get("atDock"), duration_h=pv.get("durationHrs"))
                elif kind == "ais_gap":
                    g = e.get("gap") or {}
                    off, on = g.get("offPosition") or {}, g.get("onPosition") or {}
                    r.update(intentional=g.get("intentionalDisabling"), duration_h=g.get("durationHours"),
                             off_lat=off.get("lat"), off_lon=off.get("lon"), on_lat=on.get("lat"), on_lon=on.get("lon"))
                else:
                    lo = e.get("loitering") or {}
                    r.update(duration_h=lo.get("totalTimeHours"), avg_shore_km=lo.get("averageDistanceFromShoreKm"),
                             avg_speed_kn=lo.get("averageSpeedKnots"))
                rows.append(r)
    cols = ["imo", "vessel_id", "kind", "start", "end", "lat", "lon", "shore_km", "port_country", "port_name", "port_id",
            "at_dock", "duration_h", "intentional", "off_lat", "off_lon", "on_lat", "on_lon", "avg_shore_km", "avg_speed_kn"]
    ev = pd.DataFrame(rows, columns=cols).drop_duplicates(["imo", "kind", "start", "end"])
    for c in ("start", "end"):
        ev[c] = pd.to_datetime(ev[c], utc=True, format="ISO8601").dt.tz_localize(None)
    for c in ("lat", "lon", "off_lat", "off_lon", "on_lat", "on_lon", "duration_h", "shore_km", "avg_shore_km", "avg_speed_kn"):
        if c in ev:
            ev[c] = pd.to_numeric(ev[c], errors="coerce")
    return ev


def lastpos_table(vid2imo: dict) -> pd.DataFrame:
    rows = []
    for p in (OUT / "lastpos").glob("*.json"):
        d = json.loads(p.read_text())
        for r in (list((d.get("entries") or [{}])[0].values() or [[]])[0] or []):
            imo = vid2imo.get(r.get("vesselId"))
            if imo and r.get("lat") is not None:
                rows.append({"imo": imo, "date": r["date"], "lat": r["lat"], "lon": r["lon"], "hours": r.get("hours")})
    lp = pd.DataFrame(rows, columns=["imo", "date", "lat", "lon", "hours"])
    if lp.empty:
        return lp
    lp["date"] = pd.to_datetime(lp["date"])
    return lp.sort_values(["date", "hours"]).groupby("imo").tail(1)


def main():
    pres = presence_table()
    cands = candidate_imos()
    ct = classify_table()
    cand = pd.DataFrame({"imo": cands})
    cand["tanker_status"] = cand.imo.map(lambda i: "verified" if set(ct.get(i, "").split("|")) & TANKER_TYPES else "unverified")
    per, reg = identity_tables()
    per = per[per.imo.isin(cands)]
    reg = reg[reg.imo.isin(cands)]
    p = (pres[pres.imo.isin(cands)].groupby(["imo", "region", "month"], as_index=False)["hours"].sum())
    id2imo = dict(zip(per.vessel_id, per.imo)) | dict(zip(pres.vessel_id, pres.imo))
    ev = events_table(id2imo)
    lp = lastpos_table(id2imo)
    outs = {"gfw_presence": p, "gfw_identity": per, "gfw_registry": reg, "gfw_events": ev,
            "gfw_lastpos": lp, "gfw_candidates": cand}
    for k, v in outs.items():
        v.to_parquet(INTERIM / f"{k}.parquet", index=False)
        print(k, v.shape)
    write_manifest(INTERIM / "gfw.manifest.json", inputs=["gfw/presence", "gfw/classify", "gfw/identity",
                                                         "gfw/region_events", "gfw/lastpos"],
                   outputs={k: len(v) for k, v in outs.items()},
                   notes="Global Fishing Watch API v3, non-commercial licence; see data/raw/manifest.jsonl for URLs")


if __name__ == "__main__":
    main()
