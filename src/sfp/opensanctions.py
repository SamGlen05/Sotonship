"""Stage 1: parse OpenSanctions per-dataset FtM exports into dated, IMO-keyed tables.

Outputs (data/interim/):
  os_vessels.parquet  one row per (dataset, IMO): name, flag, past flags, build year,
                      type, first_seen (when OpenSanctions first saw it)
  os_events.parquet   one row per dated fact (sanction listing, detention, ban,
                      GUR catalogue entry) with event_date and known_at

known_at is the earliest date we accept the fact as public (rules in config.py):
  sanction lists : listingDate/startDate + LIST_PUBLICATION_LAG_DAYS (fallback first_seen)
  detentions/bans: startDate + PSC_PUBLICATION_LAG_DAYS
  GUR catalogue  : vessel first_seen (no listing dates; earliest 2025-10-16)
OpenSanctions is CC BY-NC 4.0: non-commercial use only.
"""
import json
import re

import pandas as pd

from sfp import config
from sfp.labels import clean_imo
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, RAW

KIND = {
    "ca_dfatd_sema_sanctions": "sanction", "ch_seco_sanctions": "sanction",
    "au_dfat_sanctions": "sanction", "nz_russia_sanctions": "sanction",
    "tokyo_mou_detention": "detention", "black_sea_mou_detention": "detention",
    "abuja_mou_detention": "detention", "paris_mou_banned": "psc_ban",
    "ua_war_sanctions": "gur_catalogue",
}


def _imo(v: dict) -> str | None:
    for x in v["properties"].get("imoNumber", []):
        if (i := clean_imo(x)):
            return i
    for r in v.get("referents", []):  # e.g. 'imo-vsl-9422964'
        m = re.match(r"imo-vsl-(\d{7})$", r)
        if m and (i := clean_imo(m.group(1))):
            return i
    return None


def _year(xs):
    for x in xs or []:
        m = re.match(r"(\d{4})", x)
        if m:
            return int(m.group(1))
    return None


def parse_dataset(ds: str):
    ves, ref = {}, {}
    sanc = []
    for line in open(RAW / "opensanctions" / ds / "entities.ftm.json"):
        e = json.loads(line)
        if e["schema"] == "Vessel":
            ves[e["id"]] = e
            for r in e.get("referents", []):
                ref[r] = e["id"]
        elif e["schema"] == "Sanction":
            sanc.append(e)
    vrows = []
    for vid, v in ves.items():
        p = v["properties"]
        vrows.append({"dataset": ds, "os_id": vid, "imo": _imo(v), "name": (p.get("name") or [None])[0],
                      "flag": "|".join(p.get("flag", [])), "past_flags": "|".join(p.get("pastFlags", [])),
                      "build_year": _year(p.get("buildDate")), "type": "|".join(p.get("type", [])),
                      "topics": "|".join(p.get("topics", [])),
                      "first_seen": v["first_seen"][:10], "last_seen": v["last_seen"][:10]})
    erows = []
    kind = KIND[ds]
    for s in sanc:
        p = s["properties"]
        ent = (p.get("entity") or [None])[0]
        vid = ent if ent in ves else ref.get(ent)
        if not vid:
            continue
        date = (p.get("listingDate") or p.get("startDate") or [None])[0]
        erows.append({"dataset": ds, "kind": kind, "os_id": vid, "imo": _imo(ves[vid]),
                      "event_date": date[:10] if date else None,
                      "end_date": (p.get("endDate") or [None])[0],
                      "first_seen": s["first_seen"][:10],
                      "vessel_first_seen": ves[vid]["first_seen"][:10],
                      "authority": "|".join(p.get("authority", [])),
                      "program": "|".join(p.get("program", []) or p.get("programId", [])),
                      "reason": " / ".join(p.get("reason", []))[:500]})
    if kind == "gur_catalogue":  # GUR has no Sanction-per-vessel dates: one row per vessel
        erows = [{"dataset": ds, "kind": kind, "os_id": vid, "imo": _imo(v), "event_date": None,
                  "end_date": None, "first_seen": v["first_seen"][:10], "vessel_first_seen": v["first_seen"][:10],
                  "authority": "GUR (Defence Intelligence of Ukraine)", "program": "UA-WS-MARE",
                  "reason": "|".join(v["properties"].get("topics", []))} for vid, v in ves.items()]
    return pd.DataFrame(vrows), pd.DataFrame(erows)


def known_at(ev: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(ev["event_date"], errors="coerce")
    fs = pd.to_datetime(ev["first_seen"])
    vfs = pd.to_datetime(ev["vessel_first_seen"])
    lag_list = pd.Timedelta(days=config.LIST_PUBLICATION_LAG_DAYS)
    lag_psc = pd.Timedelta(days=config.PSC_PUBLICATION_LAG_DAYS)
    out = pd.Series(pd.NaT, index=ev.index, dtype="datetime64[ns]")
    s = ev["kind"].eq("sanction")
    out[s] = (d[s] + lag_list).fillna(fs[s])
    p = ev["kind"].isin(["detention", "psc_ban"])
    out[p] = d[p] + lag_psc
    g = ev["kind"].eq("gur_catalogue")
    out[g] = vfs[g]
    return out


def main():
    vs, es = [], []
    for ds in KIND:
        v, e = parse_dataset(ds)
        vs.append(v)
        es.append(e)
        print(ds, len(v), len(e))
    v = pd.concat(vs, ignore_index=True)
    e = pd.concat(es, ignore_index=True)
    e["known_at"] = known_at(e)
    v.to_parquet(INTERIM / "os_vessels.parquet", index=False)
    e.to_parquet(INTERIM / "os_events.parquet", index=False)
    write_manifest(INTERIM / "opensanctions.manifest.json",
                   inputs=[f"opensanctions/{d}/entities.ftm.json" for d in KIND],
                   outputs={"os_vessels": len(v), "os_events": len(e)},
                   notes="known_at rules in config.py (PSC_PUBLICATION_LAG_DAYS, LIST_PUBLICATION_LAG_DAYS)")


if __name__ == "__main__":
    main()
