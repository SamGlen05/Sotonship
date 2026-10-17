"""Stage 5 data: score every tanker at the latest snapshot and write the dashboard data.

Production model = LightGBM retrained on every snapshot whose label window is complete
(T + horizon <= data date), Platt-calibrated on the last held-out complete snapshots.
The backtest (sfp.model) is the honest performance estimate; this file only serves views.

Writes app/data/vessels.js (window.SFP_DATA = {...}) and app/data/land.js.
"""
import json

import duckdb
import numpy as np
import pandas as pd
from shapely.geometry import box, mapping, shape
from sklearn.linear_model import LogisticRegression

from sfp import config
from sfp import reasons
from sfp.features import AIS, CONTEXT, FEATURES, LOOKBACK, load_pairs, load_shipdays
from sfp.manifest import write_manifest
from sfp.model import make_gbm
from sfp.paths import INTERIM, PROCESSED, RAW, ROOT

APP_DATA = ROOT / "app" / "data"
DATA_DATE = pd.Timestamp("2026-10-16")  # lists retrieved 2026-10-16
MAP_BOX = (2.0, 53.0, 22.0, 61.0)        # lon_min, lat_min, lon_max, lat_max

LABELS = {
    "days_seen": "Sampled days seen in Danish waters",
    "days_since_last_seen": "Days since last seen",
    "imo_number": "IMO number (age proxy)",
    "n_mmsi_12m": "Different MMSI numbers, 12 months",
    "n_names_12m": "Different names, 12 months",
    "n_flags_12m": "Different flags (from MMSI), 12 months",
    "dest_missing_frac": "Share of days with blank destination",
    "west_laden_frac": "Westbound straits passages laden",
    "east_laden_frac": "Eastbound straits passages laden",
    "baltic_side_frac": "Share of days on the Baltic side",
    "near_sanctioned": "Sanctioned tankers lingered next to",
    "length": "Length (m)", "width": "Beam (m)", "draught_max": "Max draught (m)",
    "dest_russian_frac": "Share of days announcing a Russian port",
    "dest_notable_frac": "Share of days with 'FOR ORDERS'-style destination",
    "cross_per_day": "Straits crossings per day seen",
    "gaps_core_per_day": "AIS gaps inside coverage per day",
    "max_gap_h": "Longest AIS gap (h)",
    "slow_underway_h_per_day": "Slow drifting hours per day (not moored)",
    "anchor_h_per_day": "Hours at anchor per day",
    "spoof_per_day": "Implausible position jumps per day",
    "sts_count": "Ship-to-ship meetings",
    "sts_with_sanctioned": "Meetings with already-sanctioned tankers",
    "flag_risk": "Flag's share of already-sanctioned tankers",
    "flag_is_russia": "Russian flag",
}


OS_NAMES = {"ca_dfatd_sema_sanctions": "Canada sanctions", "ch_seco_sanctions": "Switzerland sanctions",
            "au_dfat_sanctions": "Australia sanctions", "paris_mou_banned": "Paris MoU ban",
            "ua_war_sanctions": "GUR War&Sanctions catalogue", "tokyo_mou_detention": "Tokyo MoU detention",
            "black_sea_mou_detention": "Black Sea MoU detention", "abuja_mou_detention": "Abuja MoU detention"}


def list_status_factory(lab: pd.DataFrame):
    """Today's list status for a vessel card (context, not model input), each entry dated."""
    ose = pd.read_parquet(INTERIM / "os_events.parquet")
    ose = ose[ose.kind.isin(["sanction", "psc_ban", "gur_catalogue", "detention"])]
    by = dict(tuple(ose.sort_values("known_at").groupby("imo")))

    def list_status(imo):
        out = []
        if imo in lab.index:
            r = lab.loc[imo]
            for k, nm in (("uk_any_on", "UK Sanctions List"), ("eu_any_on", "EU designated vessels"),
                          ("us_any_on", "US OFAC SDN")):
                if pd.notna(r[k]):
                    out.append({"list": nm, "date": str(r[k].date())})
        for x in by.get(imo, ose.iloc[:0]).itertuples():
            d = x.event_date or (str(x.known_at.date()) if pd.notna(x.known_at) else None)
            out.append({"list": OS_NAMES[x.dataset], "date": d, "kind": x.kind})
        return out
    return list_status


def size_class(length):
    if length is None or not np.isfinite(length):
        return None
    for mx, name, dwt, hull in config.SIZE_CLASSES:
        if length <= mx:
            return {"class": name, "dwt": dwt, "hull_usd": hull}
    return None


def production_model(feat: pd.DataFrame):
    chosen = json.loads((PROCESSED / "model_meta.json").read_text())["selection"]["chosen"]["gbm"]
    done = feat[(feat["T"] + pd.Timedelta(days=config.LABEL_HORIZON_DAYS)) <= DATA_DATE]
    Ts = sorted(done["T"].unique())
    hold = Ts[-3:] if len(Ts) > 4 else Ts[-1:]
    fit_part, cal_part = done[~done["T"].isin(hold)], done[done["T"].isin(hold)]
    m0 = make_gbm(chosen, fit_part.label).fit(fit_part[FEATURES], fit_part.label)
    raw = m0.predict(cal_part[FEATURES], raw_score=True).reshape(-1, 1)
    platt = LogisticRegression(C=1.0).fit(raw, cal_part.label) if cal_part.label.nunique() > 1 else None
    pos = done.label.sum()
    m = make_gbm(chosen, done.label).fit(done[FEATURES], done.label)
    base_rate = float(done.label.mean())
    meta = {"trained_on": [str(t.date()) for t in Ts], "calibrated_on": [str(t.date()) for t in hold],
            "rows": len(done), "positives": int(pos), "base_rate_90d": base_rate, "params": chosen}
    return m, platt, base_rate, meta


def land_geojson():
    g = json.load(open(RAW / "naturalearth" / "ne_10m_land.geojson"))
    clip = box(*MAP_BOX)
    polys = []
    for f in g["features"]:
        s = shape(f["geometry"]).intersection(clip)
        if not s.is_empty:
            polys.append(s.simplify(0.01, preserve_topology=True))
    coords = []
    for s in polys:
        for p in getattr(s, "geoms", [s]):
            if p.geom_type == "Polygon" and p.area > 0.0005:
                coords.append([[round(x, 3), round(y, 3)] for x, y in p.exterior.coords])
    return coords


def main():
    feat = pd.read_parquet(PROCESSED / "features.parquet")
    T_now = feat["T"].max()
    model, platt, base_rate, meta = production_model(feat)
    now = feat[feat["T"] == T_now].copy()
    raw = model.predict(now[FEATURES], raw_score=True)
    now["p90"] = platt.predict_proba(raw.reshape(-1, 1))[:, 1] if platt else model.predict_proba(now[FEATURES])[:, 1]
    contrib = model.predict(now[FEATURES], pred_contrib=True)[:, :-1]

    lab = pd.read_parquet(INTERIM / "labels.parquet").set_index("imo")
    master = pd.read_parquet(INTERIM / "vessel_master.parquet").set_index("imo")
    sd = load_shipdays()
    pairs = load_pairs(sd)
    sts, near = pairs["sts"], pairs["near"]
    win = sd[(sd.day < T_now) & (sd.day >= T_now - LOOKBACK)]
    first_sanc = lab["first_any_on"]
    ctx = reasons.Context(win, first_sanc, T_now)
    rows = now.set_index("imo")
    name_of = sd.sort_values("day").groupby("imo")["name"].last()

    # last-day track per ship (one point per 30 min) for the map
    last_day = win.sort_values("day").groupby("imo").tail(1)[["imo", "mmsi", "day"]]
    tracks = {}
    for day, g in last_day.groupby("day"):
        p = duckdb.sql(f"""SELECT mmsi, lat, lon, ts FROM '{AIS}/pos/{day.date()}.parquet'
                           WHERE mmsi IN ({','.join(f"'{m}'" for m in g.mmsi)})
                           AND minute(ts) % 30 < {config.AIS_RESAMPLE_MINUTES} ORDER BY mmsi, ts""").df()
        for mmsi, t in p.groupby("mmsi"):
            tracks[mmsi] = [[round(a, 4), round(b, 4)] for a, b in zip(t.lat, t.lon)]

    list_status = list_status_factory(lab)

    vessels = []
    for i, r in enumerate(now.itertuples()):
        imo = r.imo
        w = win[win.imo == imo].sort_values("day")
        c = dict(zip(FEATURES, contrib[i]))
        drivers = sorted(((k, v) for k, v in c.items() if k not in CONTEXT), key=lambda kv: -abs(kv[1]))
        ev = []
        for _, x in w[w.dest_russian].iterrows():
            ev.append({"date": str(x.day.date()), "type": "Russian port destination",
                       "text": f"Broadcast destination '{x.destinations}'", "lat": x.last_lat, "lon": x.last_lon})
        for _, x in w[w.n_gaps_core > 0].iterrows():
            ev.append({"date": str(x.day.date()), "type": "AIS gap in coverage",
                       "text": f"{int(x.n_gaps_core)} silence(s) of 2 h or more inside receiver coverage; longest {x.max_gap_h:.1f} h",
                       "lat": x.last_lat, "lon": x.last_lon})
        for _, x in w[w.n_spoof_jumps > 0].iterrows():
            ev.append({"date": str(x.day.date()), "type": "Position jump",
                       "text": f"{int(x.n_spoof_jumps)} position jump(s) implying more than {config.SPOOF_SPEED_KN} kn",
                       "lat": x.last_lat, "lon": x.last_lon})
        for _, x in w[w.dest_notable].iterrows():
            ev.append({"date": str(x.day.date()), "type": "Vague destination",
                       "text": f"Broadcast destination '{x.destinations}'", "lat": x.last_lat, "lon": x.last_lon})
        s = sts[(sts.imo == imo) & (sts.day < T_now) & (sts.day >= T_now - LOOKBACK)]
        for _, x in s.iterrows():
            ps = first_sanc.get(x.partner)
            flag = pd.notna(ps) and ps < x.day
            ev.append({"date": str(x.day.date()), "type": "Ship-to-ship meeting",
                       "text": f"{x.hours:.1f} h within {config.STS_DISTANCE_NM} nm of {name_of.get(x.partner, 'unknown')} (IMO {x.partner})"
                               + (f", sanctioned since {ps.date()}" if flag else ""),
                       "lat": x.lat, "lon": x.lon})
        nb = near[(near.imo == imo) & (near.day < T_now) & (near.day >= T_now - LOOKBACK)]
        for _, x in nb.iterrows():
            ps = first_sanc.get(x.partner)
            if pd.notna(ps) and ps < x.day:
                ev.append({"date": str(x.day.date()), "type": "Near sanctioned tanker",
                           "text": f"{x.hours:.1f} h within {config.NEAR_DISTANCE_NM} nm of {name_of.get(x.partner, 'unknown')} "
                                   f"(IMO {x.partner}), sanctioned since {ps.date()}", "lat": x.lat, "lon": x.lon})
        ev.sort(key=lambda e: e["date"], reverse=True)
        sc = size_class(r.length)
        why = reasons.build(rows.loc[imo].to_dict() | {"imo": imo}, c, w, ev, ctx)
        last = w.iloc[-1]
        rel = r.p90 / base_rate if base_rate else 0
        band = "high" if rel >= config.BAND_HIGH_X else "medium" if rel >= config.BAND_MEDIUM_X else "low"
        if band != "low" and not why:  # never show an unexplained elevated score
            why = [{"feature": None, "title": "No single dominant signal",
                    "text": "The score is raised by a combination of weak signals and by limited observation "
                            f"({int(r.days_seen)} sampled day(s)). Review manually before relying on it.",
                    "evidence": [], "contrib": None}]
        vessels.append({
            "imo": imo, "name": r.name_last, "mmsi": r.mmsi_last, "flag": r.flag_last,
            "flags_seen": sorted(set(w.flag)), "names_seen": sorted(set(w.name.dropna())), "mmsis_seen": sorted(set(w.mmsi)),
            "length": None if pd.isna(r.length) else float(r.length), "size": sc,
            "status": "unsanctioned", "p90": round(float(r.p90), 4), "rel": round(float(rel), 2), "band": band,
            "drivers": [{"feature": k, "label": LABELS[k], "value": None if pd.isna(getattr(r, k)) else round(float(getattr(r, k)), 3),
                         "contrib": round(float(v), 3)} for k, v in drivers[:6]],
            "reasons": why,
            "evidence": ev[:25],
            "days_seen": int(r.days_seen), "first_seen": str(w.day.min().date()), "last_seen": str(w.day.max().date()),
            "last_pos": {"lat": last.last_lat, "lon": last.last_lon, "ts": str(last.last_ts), "sog": last.last_sog,
                         "destination": last.destinations},
            "track": tracks.get(last.mmsi, []),
            "lists": list_status(imo),
        })

    # ships already sanctioned that were seen in the window (shown, not predicted)
    sanc = win[win.imo.isin(first_sanc[first_sanc < T_now].index)].sort_values("day").groupby("imo").tail(1)
    for _, last in sanc.iterrows():
        sc = size_class(last.length)
        vessels.append({"imo": last.imo, "name": last["name"], "mmsi": last.mmsi, "flag": last.flag,
                        "length": None if pd.isna(last.length) else float(last.length), "size": sc,
                        "status": "sanctioned", "sanctioned_on": str(first_sanc[last.imo].date()),
                        "days_seen": int(win[win.imo == last.imo].day.nunique()),
                        "first_seen": str(win[win.imo == last.imo].day.min().date()), "last_seen": str(last.day.date()),
                        "last_pos": {"lat": last.last_lat, "lon": last.last_lon, "ts": str(last.last_ts),
                                     "sog": last.last_sog, "destination": last.destinations},
                        "track": tracks.get(last.mmsi, []), "lists": list_status(last.imo)})

    # listed ships never seen in the Danish AIS window: searchable, flagged as no data
    seen = {v["imo"] for v in vessels}
    for imo in lab.index.difference(list(seen)):
        nm = master["name_current"].get(imo) if imo in master.index else None
        st = lab.loc[imo, "first_any_on"]
        vessels.append({"imo": imo, "name": nm, "status": "no_ais", "lists": list_status(imo),
                        "sanctioned_on": None if pd.isna(st) else str(st.date())})

    def clean(o):
        if isinstance(o, float) and not np.isfinite(o):
            return None
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating,)):
            return clean(float(o))
        if isinstance(o, (np.integer,)):
            return int(o)
        return o

    n_days = len(list((AIS / "shipday").glob("*.parquet")))
    data = {
        "generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="minutes"),
        "snapshot": str(T_now.date()), "data_date": str(DATA_DATE.date()),
        "ais_window": [str((T_now - LOOKBACK).date()), str((T_now - pd.Timedelta(days=1)).date())],
        "ais_days_total": n_days, "model": meta, "base_rate_90d": base_rate,
        "assumptions": {"size_classes": [{"max_length": a, "class": b, "dwt": c, "hull_usd": d}
                                         for a, b, c, d in config.SIZE_CLASSES],
                        "cargo_load_factor": config.CARGO_LOAD_FACTOR, "barrels_per_tonne": config.BARRELS_PER_TONNE,
                        "oil_price_usd_bbl": config.OIL_PRICE_USD_BBL,
                        "band_high_x": config.BAND_HIGH_X, "band_medium_x": config.BAND_MEDIUM_X},
        "backtest": json.loads((PROCESSED / "backtest.json").read_text()) if (PROCESSED / "backtest.json").exists() else None,
        "vessels": clean(vessels),
    }
    APP_DATA.mkdir(parents=True, exist_ok=True)
    (APP_DATA / "vessels.js").write_text("window.SFP_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
    (APP_DATA / "land.js").write_text("window.SFP_LAND = " + json.dumps(land_geojson(), separators=(",", ":")) + ";\n")
    write_manifest(PROCESSED / "score.manifest.json", inputs=["data/processed/features.parquet"],
                   outputs={"vessels": len(vessels), "scored": int((now.shape[0])), "snapshot": str(T_now.date())},
                   notes="production model trained on complete-label snapshots; see backtest.json for honest metrics")
    print(f"snapshot {T_now.date()}: scored {len(now)}, sanctioned-seen {len(sanc)}, total searchable {len(vessels)}")
    print("bands:", pd.Series([v.get("band") for v in vessels if v["status"] == "unsanctioned"]).value_counts().to_dict())
    print("model:", meta)
    elev = [v for v in vessels if v.get("band") in ("high", "medium")]
    print("elevated ships:", len(elev), "| with evidence-backed reasons:",
          sum(1 for v in elev if any(x["feature"] for x in v["reasons"])),
          "| reason titles:", pd.Series([x["title"] for v in elev for x in v["reasons"]]).value_counts().head(10).to_dict())


if __name__ == "__main__":
    main()
