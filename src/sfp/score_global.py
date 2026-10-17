"""Stage 5 data (global): score every candidate tanker in Europe and the Middle East at the
latest snapshot and write the dashboard data (app/data/vessels.js, land.js).

Production model: LightGBM on every global snapshot whose 90-day label window has passed,
Platt-calibrated on the last held-out complete snapshots. Honest performance is the
backtest (python -m sfp.model --set global). Every elevated score carries reasons, each
with dated evidence; scores with no evidence-backed reason are flagged for manual review.
"""
import json

import numpy as np
import pandas as pd
from shapely.geometry import box, shape
from sklearn.linear_model import LogisticRegression

from sfp import config
from sfp import global_features as gf
from sfp.manifest import write_manifest
from sfp.model import make_gbm, use_set
from sfp.paths import INTERIM, PROCESSED, RAW, ROOT
from sfp.reasons import est_build_year

APP = ROOT / "app" / "data"
DATA_DATE = pd.Timestamp("2026-10-16")
MAP_BOX = (-20.0, 5.0, 72.0, 75.0)
COUNTRY = {"RUS": "Russia", "IRN": "Iran", "VEN": "Venezuela", "SYR": "Syria", "PRK": "North Korea", "IND": "India",
           "CHN": "China", "TUR": "Turkey", "ARE": "UAE", "EGY": "Egypt", "MYS": "Malaysia", "SGP": "Singapore"}
LABELS = {
    "h_baltic": "Hours in the Baltic", "h_north": "Hours in North Sea / Norway", "h_med": "Hours in Mediterranean / Iberia",
    "h_black_sea": "Hours in the Black Sea", "h_red_sea": "Hours in Red Sea / Gulf of Aden", "h_gulf": "Hours in Persian Gulf / Gulf of Oman",
    "h_arabian": "Hours in the Arabian Sea", "imo_number": "IMO number (age proxy)", "built_year": "Build year (registry)",
    "tonnage_gt": "Gross tonnage", "registry_verified": "Registry confirms tanker", "n_flags_12m": "Flags used, 12 months",
    "n_names_12m": "Names used, 12 months", "n_mmsi_12m": "MMSI numbers used, 12 months",
    "days_since_identity_change": "Days since last identity change", "flag_risk": "Flag's share of sanctioned tankers",
    "n_port_visits": "Port visits", "ports_sanctioned_trade": "Port calls in Russia / Iran / Venezuela / Syria / N. Korea",
    "ports_reroute_markets": "Port calls in India / China / Turkey / UAE / Egypt / Malaysia / Singapore",
    "share_port_days_sanctioned": "Share of port time in sanctioned-trade countries", "n_gaps": "AIS gaps",
    "n_gaps_intentional": "AIS gaps flagged intentional", "gap_hours": "Hours with AIS off", "gap_hours_max": "Longest AIS gap (h)",
    "n_loiter": "Loitering events", "loiter_hours": "Loitering hours", "loiter_hotspot_hours": "Loitering hours at transfer hotspots",
    "loiter_with_sanctioned": "Loitered next to a sanctioned tanker",
    "dma_days_seen": "Danish AIS days seen", "dma_dest_russian_frac": "Danish AIS: share of days with a Russian destination",
    "dma_west_laden_frac": "Danish AIS: westbound passages laden", "dma_gaps_core_per_day": "Danish AIS: gaps in coverage per day",
    "dma_sts_with_sanctioned": "Danish AIS: meetings with sanctioned tankers", "dma_near_sanctioned": "Danish AIS: lingered near sanctioned tankers",
}


def hull_value(cls, build_year, year_now=2026):
    """Age-adjusted value from 5-year-old class benchmarks (config, sourced)."""
    v5 = config.VALUE_5YR_USD[cls]
    if build_year is None or not np.isfinite(build_year):
        age = 20.0  # typical age of the scored fleet when unknown
    else:
        age = max(0.0, year_now - build_year)
    f = max(config.HULL_VALUE_FLOOR, 1 - config.HULL_DEPRECIATION_PER_YEAR * max(0.0, age - 5))
    v = v5 * f
    return {"hull_usd": round(v, -5), "hull_low": round(v * (1 - config.HULL_VALUE_RANGE), -5),
            "hull_high": round(v * (1 + config.HULL_VALUE_RANGE), -5), "age": round(age)}


def size_class(length, gt, build_year=None, year_basis=None):
    out = None
    if length is not None and np.isfinite(length):
        for mx, name, dwt, hull in config.SIZE_CLASSES:
            if length <= mx:
                out = {"class": name, "dwt": dwt, "basis": f"{length:.0f} m AIS length"}
                break
    elif gt is not None and np.isfinite(gt):
        name = next(n for mx, n in config.SIZE_BY_GT if gt <= mx)
        _, _, dwt, hull = next(c for c in config.SIZE_CLASSES if c[1] == name)
        out = {"class": name, "dwt": dwt, "basis": f"{gt:,.0f} GT registry tonnage"}
    if out:
        out.update(hull_value(out["class"], build_year))
        out["age_basis"] = year_basis or "assumed 20 years"
    return out


def land(box_):
    g = json.load(open(RAW / "naturalearth" / "ne_10m_land.geojson"))
    clip = box(*box_)
    out = []
    for f in g["features"]:
        s = shape(f["geometry"]).intersection(clip)
        if s.is_empty:
            continue
        s = s.simplify(0.012, preserve_topology=True)  # detailed enough to zoom into straits
        for p in getattr(s, "geoms", [s]):
            if p.geom_type == "Polygon" and p.area > 0.0008:
                out.append([[round(x, 2), round(y, 2)] for x, y in p.exterior.coords])
    return out


def band_of(top_pct):
    return "high" if top_pct <= config.BAND_HIGH_TOP_PCT else "medium" if top_pct <= config.BAND_MEDIUM_TOP_PCT else "low"


def backtest_insights(feat):
    """Out-of-sample facts from the backtest model (trained before 2026-05-01):
    how often ships in each band were really sanctioned within 90 days, and each ship's
    risk-rank trend over the test months."""
    sc = pd.read_parquet(PROCESSED / "scores_all_snapshots_global.parquet")
    comp = feat.loc[(feat.split == "test"), ["imo", "T", "label_complete"]]
    sc = sc.merge(comp, on=["imo", "T"])
    sc["top_pct"] = sc.groupby("T")["lightgbm"].rank(pct=True, ascending=False, method="max") * 100
    sc["band"] = sc["top_pct"].map(band_of)
    done = sc[sc.label_complete]
    stats = {"months": sorted(str(t.date()) for t in done["T"].unique()), "base_rate": float(done.label.mean()),
             "bands": {b: {"tanker_months": int(len(g)), "sanctioned": int(g.label.sum()), "rate": float(g.label.mean())}
                       for b, g in done.groupby("band")}}
    trend = {imo: [[str(t.date()), round(float(p), 1)] for t, p in zip(g["T"], g.top_pct)]
             for imo, g in sc.sort_values("T").groupby("imo")}
    return stats, trend


def production(feat):
    use_set("global")
    meta = json.loads((PROCESSED / "model_meta_global.json").read_text())
    chosen = meta["selection"]["chosen"]["gbm"]
    F = gf.FEATURES
    done = feat[(feat["T"] + pd.Timedelta(days=config.LABEL_HORIZON_DAYS)) <= DATA_DATE]
    Ts = sorted(done["T"].unique())
    hold = Ts[-3:]
    a, c = done[~done["T"].isin(hold)], done[done["T"].isin(hold)]
    m0 = make_gbm(chosen, a.label).fit(a[F], a.label)
    platt = LogisticRegression().fit(m0.predict(c[F], raw_score=True).reshape(-1, 1), c.label)
    m = make_gbm(chosen, done.label).fit(done[F], done.label)
    return m, platt, float(done.label.mean()), {"trained_on": [str(t.date()) for t in Ts], "calibrated_on": [str(t.date()) for t in hold],
                                                "rows": len(done), "positives": int(done.label.sum()),
                                                "base_rate_90d": float(done.label.mean()), "params": chosen}


def reasons_for(r, contrib, ev_i, idt_i, pop, T, ctx):
    out = []

    def pct_others(col, cond):
        return f"{100 * cond(pop[col]).mean():.0f}%"

    for f, c in sorted(contrib.items(), key=lambda kv: -kv[1]):
        if c <= 0 or f in gf.CONTEXT:
            continue
        v = r.get(f)
        v = 0 if v is None or (isinstance(v, float) and not np.isfinite(v)) else v
        t = None
        if f == "ports_sanctioned_trade" and v > 0:
            pv = ev_i[(ev_i.kind == "port_visit") & ev_i.port_country.isin(config.SANCTIONED_TRADE_PORT_COUNTRIES)]
            places = ", ".join(f"{p.port_name if isinstance(p.port_name, str) else 'unnamed anchorage'} "
                               f"({COUNTRY.get(p.port_country, p.port_country)}) {p.start.date()}" for p in pv.tail(3).itertuples())
            t = ("Port calls in sanctioned-trade countries", f"{int(v)} port call(s) in Russia, Iran, Venezuela, Syria or North Korea in the "
                 f"180 days before {T.date()}: {places}. {pct_others(f, lambda s: s > 0)} of scored tankers made any.", "port")
        elif f == "share_port_days_sanctioned" and v > 0:
            t = ("Port time in sanctioned-trade countries", f"{v:.0%} of its port time was in sanctioned-trade countries.", "port")
        elif f in ("n_gaps_intentional", "gap_hours", "gap_hours_max", "n_gaps") and r.get("n_gaps", 0) > 0:
            gi = ev_i[ev_i.kind == "ais_gap"]
            g = gi.sort_values("duration_h").tail(1)
            longest = f"; longest {g.duration_h.iloc[0]:.0f} h from {g.start.iloc[0].date()}" if len(g) else ""
            t = ("AIS switched off", f"{int(r.get('n_gaps', 0))} AIS gap(s), {int(r.get('n_gaps_intentional', 0))} judged likely intentional by "
                 f"Global Fishing Watch, {r.get('gap_hours', 0):.0f} h in total{longest}. {pct_others('n_gaps_intentional', lambda s: s > 0)} of scored tankers had an intentional gap.", "gap")
        elif f == "loiter_with_sanctioned" and v > 0:
            t = ("Loitered next to sanctioned tankers", f"{int(v)} loitering event(s) overlapping in time, within {gf.LOITER_PAIR_KM:.0f} km, "
                 f"with a tanker already sanctioned at the time: a pattern consistent with ship-to-ship transfer.", "loiter_pair")
        elif f == "loiter_hotspot_hours" and v > 0:
            t = ("Loitering at a transfer hotspot", f"{v:.0f} h loitering in reported ship-to-ship transfer areas.", "hotspot")
        elif f in ("loiter_hours", "n_loiter") and r.get("n_loiter", 0) > 0:
            t = ("Loitering at sea", f"{int(r.get('n_loiter', 0))} loitering event(s), {r.get('loiter_hours', 0):.0f} h at under 2 kn far from shore.", "loiter")
        elif f in ("n_flags_12m", "n_names_12m", "n_mmsi_12m", "days_since_identity_change"):
            ch = idt_i[idt_i["from"] >= T - pd.Timedelta(days=365)]
            if len(ch) and (r.get("n_flags_12m", 1) > 1 or r.get("n_names_12m", 1) > 1 or r.get("n_mmsi_12m", 1) > 1):
                parts = "; ".join(f"{x['from'].date()}: {x['name']} under flag {x['flag']} (MMSI {x['mmsi']})" for _, x in ch.tail(3).iterrows())
                t = ("Identity changes", f"{int(r.get('n_flags_12m', 1))} flag(s), {int(r.get('n_names_12m', 1))} name(s) and "
                     f"{int(r.get('n_mmsi_12m', 1))} MMSI number(s) in 12 months. Latest: {parts}.", None)
        elif f == "flag_risk":
            t = (f"Flag: {r.get('flag_last')}", f"Flag {r.get('flag_last')} as of {T.date()}: {v:.1%} (smoothed) of tankers present under "
                 f"this flag in the last 6 months were already sanctioned, against {ctx['sanc_share']:.1%} across all flags.", None)
        elif f == "imo_number":
            y = r.get("built_year") if r.get("built_year") and np.isfinite(r.get("built_year")) else est_build_year(r["imo"])
            if y:
                t = ("Older tonnage", f"Built around {int(y)}"
                     + (" (registry)" if r.get("built_year") and np.isfinite(r.get("built_year")) else " (estimated from IMO number)")
                     + f". Already-sanctioned tankers present in these waters have a median estimated build year of "
                     f"{ctx['year_sanc']:.0f}, against {ctx['year_other']:.0f} for the others.", None)
        elif f.startswith("h_") and v > 0:
            t = (LABELS[f].replace("Hours in", "Time in"), f"{v:.0f} hours of AIS presence in the 6 months before {T.date()}.", None)
        elif f == "dma_dest_russian_frac" and v > 0:
            t = ("Russian port destination (Danish AIS)", f"Announced a Russian port on {v:.0%} of days seen in Danish waters.", "dma")
        elif f == "dma_west_laden_frac" and v > 0:
            t = ("Left the Baltic loaded (Danish AIS)", f"{v:.0%} of westbound Danish straits passages were laden.", "dma")
        elif f in ("dma_sts_with_sanctioned", "dma_near_sanctioned") and v > 0:
            t = ("Met sanctioned tankers (Danish AIS)", f"Met or lingered near {int(v)} already-sanctioned tanker(s) in Danish waters.", "dma")
        elif f in ("dark_passages", "dark_hormuz_passages") and r.get("dark_passages", 0) > 0:
            t = ("Crossed a chokepoint with AIS off", f"{int(r.get('dark_passages', 0))} passage(s) through a chokepoint (Hormuz, Bab el-Mandeb, "
                 f"Danish straits or Bosporus) in the 180 days before {T.date()} during which AIS was switched off. "
                 f"{pct_others('dark_passages', lambda s: s > 0)} of scored tankers did this.", "dark_passage")
        elif f in ("hormuz_passages", "chokepoint_passages") and r.get(f, 0) > 0:
            t = ("Strait of Hormuz passages" if f == "hormuz_passages" else "Chokepoint passages",
                 f"{int(v)} passage(s) inferred from port calls on both sides"
                 + (" of the Strait of Hormuz" if f == "hormuz_passages" else " of a chokepoint")
                 + f" in the 180 days before {T.date()}. AIS transit counts through Hormuz fell about 95% from March 2026 (IMF PortWatch), "
                   "so passages seen only through port calls deserve a closer look." if f == "hormuz_passages" else
                 f"{int(v)} chokepoint passage(s) inferred from port calls in the 180 days before {T.date()}.", "passage")
        elif f in ("registry_verified", "tonnage_gt") or f == "ports_reroute_markets":
            continue
        if t and not any(x["title"] == t[0] for x in out):
            out.append({"feature": f, "title": t[0], "text": t[1], "evidence_kind": t[2], "contrib": round(float(c), 3)})
    return out[:6]  # the six signals that raise the score most


def evidence_for(ev_i, idt_i, T, first_sanc, name_of, sanc_lo, ps_i=None):
    e = []
    if ps_i is not None:
        for x in ps_i.itertuples():
            fp = x.from_port if isinstance(x.from_port, str) else "unnamed anchorage"
            tp = x.to_port if isinstance(x.to_port, str) else "unnamed anchorage"
            gate = {"Persian Gulf": "Strait of Hormuz", "Red Sea": "Bab el-Mandeb or Suez", "Baltic": "Danish straits",
                    "Black Sea": "Bosporus"}.get(x.basin, x.basin)
            e.append({"date": str(x.arrived.date()), "type": "Chokepoint passage" + (" with AIS off" if x.dark_h > 0 else ""),
                      "kind": "dark_passage" if x.dark_h > 0 else "passage", "lat": None, "lon": None,
                      "text": f"Moved {x.direction} the {x.basin} via the {gate}: port call at {fp} ended {x.left.date()}, next at {tp} on {x.arrived.date()}"
                              + (f"; AIS off for {x.dark_h:.0f} h in between (likely intentional)" if x.dark_h > 0 else "")})
    for x in ev_i[ev_i.kind == "port_visit"].itertuples():
        if x.port_country in config.SANCTIONED_TRADE_PORT_COUNTRIES:
            e.append({"date": str(x.start.date()), "type": "Port call", "kind": "port", "lat": x.lat, "lon": x.lon,
                      "text": f"{x.port_name if isinstance(x.port_name, str) else 'Unnamed anchorage'} ({COUNTRY.get(x.port_country, x.port_country)}), {x.duration_h or 0:.0f} h"})
    for x in ev_i[ev_i.kind == "ais_gap"].itertuples():
        e.append({"date": str(x.start.date()), "type": "AIS gap", "kind": "gap", "lat": x.off_lat, "lon": x.off_lon,
                  "text": f"AIS off for {x.duration_h or 0:.0f} h" + (" (likely intentional)" if x.intentional else "")
                          + (f", off at {x.off_lat:.2f}, {x.off_lon:.2f}" if x.off_lat == x.off_lat and x.off_lat is not None else "")})
    for x in ev_i[ev_i.kind == "loitering"].itertuples():
        hs = next((n for n, b in config.STS_HOTSPOTS.items() if b[0] <= x.lon <= b[2] and b[1] <= x.lat <= b[3]), None)
        if hs:
            e.append({"date": str(x.start.date()), "type": "Loitering at hotspot", "kind": "hotspot", "lat": x.lat, "lon": x.lon,
                      "text": f"{x.duration_h or 0:.0f} h at under 2 kn in {hs}"})
        p = sanc_lo[(sanc_lo.start < x.end) & (x.start < sanc_lo.end) & ((sanc_lo.lat - x.lat).abs() < 0.06) & ((sanc_lo.lon - x.lon).abs() < 0.09)]
        for y in p.drop_duplicates("imo").itertuples():
            e.append({"date": str(x.start.date()), "type": "Loitered next to sanctioned tanker", "kind": "loiter_pair", "lat": x.lat, "lon": x.lon,
                      "text": f"Loitered alongside {name_of.get(y.imo, 'unknown')} (IMO {y.imo}), sanctioned since {first_sanc[y.imo].date()}"})
    for _, x in idt_i[idt_i["from"] >= T - pd.Timedelta(days=365)].iterrows():
        e.append({"date": str(x["from"].date()), "type": "Identity period starts", "kind": "identity", "lat": None, "lon": None,
                  "text": f"Broadcasting as {x['name']}, flag {x['flag']}, MMSI {x['mmsi']}"})
    for z in e:
        z["source"] = "Global Fishing Watch"
    return sorted(e, key=lambda z: z["date"], reverse=True)[:30]


def main():
    feat = pd.read_parquet(PROCESSED / "features_global.parquet")
    T = feat["T"].max()
    model, platt, base, meta = production(feat)
    now = feat[feat["T"] == T].copy().reset_index(drop=True)
    raw = model.predict(now[gf.FEATURES], raw_score=True)
    now["p90"] = platt.predict_proba(raw.reshape(-1, 1))[:, 1]
    contrib = model.predict(now[gf.FEATURES], pred_contrib=True)[:, :-1]
    now["top_pct"] = 100 * (1 - now["p90"].rank(pct=True, method="max")) + 100 / len(now)
    band_stats, trend = backtest_insights(feat)

    pres, ident, reg, ev, cand = gf.load()
    lab = pd.read_parquet(INTERIM / "labels.parquet").set_index("imo")
    first_sanc = lab["first_any_on"]
    lp = pd.read_parquet(INTERIM / "gfw_lastpos.parquet").set_index("imo") if (INTERIM / "gfw_lastpos.parquet").exists() else pd.DataFrame()
    dlen = pd.read_parquet(INTERIM / "vessel_master.parquet").set_index("imo")
    ev_w = ev[(ev.end < T) & (ev.end >= T - gf.LB)]
    idt = ident[ident["from"] < T]
    name_of = idt.sort_values("from").groupby("imo")["name"].last()
    sanc_set = set(first_sanc[first_sanc < T].index)
    sanc_lo = ev_w[(ev_w.kind == "loitering") & ev_w.imo.isin(sanc_set)]
    from sfp.score import list_status_factory
    list_status = list_status_factory(lab)
    present = set(pres[(pres.month_start < T) & (pres.month_start >= T - pd.DateOffset(months=6))].imo)
    yrs = pd.Series({i: est_build_year(i) for i in present}, dtype=float)
    ctx = {"sanc_share": len(present & sanc_set) / max(len(present), 1),
           "year_sanc": yrs[yrs.index.isin(sanc_set)].median(), "year_other": yrs[~yrs.index.isin(sanc_set)].median()}
    ev_g = dict(tuple(ev_w.groupby("imo")))
    ps_w = gf.passages(ev_w[ev_w.kind == "port_visit"], ev_w[ev_w.kind == "ais_gap"])
    ps_w = ps_w[ps_w.arrived < T]
    ps_g = dict(tuple(ps_w.groupby("imo")))
    ev_all = dict(tuple(ev.groupby("imo")))           # full 2024-2026 history for the dossier
    id_all = dict(tuple(ident.sort_values("from").groupby("imo")))
    ose = pd.read_parquet(INTERIM / "os_events.parquet")
    det_all = dict(tuple(ose[ose.kind == "detention"].groupby("imo")))

    def history(imo, full=True):
        h = {"identity": [], "ports": [], "gaps": [], "detentions": []}
        n_ports, n_gaps = (40, 20) if full else (8, 4)
        for x in id_all.get(imo, ident.iloc[:0]).to_dict("records"):
            h["identity"].append({"from": str(x["from"].date()) if pd.notna(x["from"]) else None,
                                  "to": str(x["to"].date()) if pd.notna(x["to"]) else None,
                                  "name": x["name"], "flag": x["flag"], "mmsi": x["mmsi"]})
        e = ev_all.get(imo, ev.iloc[:0])
        for x in e[e.kind == "port_visit"].sort_values("start").tail(n_ports).itertuples():
            h["ports"].append({"date": str(x.start.date()), "port": x.port_name, "country": x.port_country,
                               "hours": None if pd.isna(x.duration_h) else round(float(x.duration_h)), "lat": x.lat, "lon": x.lon})
        g = e[(e.kind == "ais_gap") & (e.duration_h >= 24)].sort_values("start").tail(n_gaps)
        for x in g.itertuples():
            h["gaps"].append({"date": str(x.start.date()), "hours": round(float(x.duration_h)), "intentional": bool(x.intentional) if x.intentional == x.intentional else None})
        for x in det_all.get(imo, ose.iloc[:0]).itertuples():
            h["detentions"].append({"date": x.event_date, "authority": x.authority, "reason": (x.reason or "")[:160]})
        return h
    idt_g = dict(tuple(idt.sort_values("from").groupby("imo")))
    empty_ev, empty_id = ev_w.iloc[:0], idt.iloc[:0]

    def pos(imo):
        if imo in lp.index:
            x = lp.loc[imo]
            return {"lat": float(x.lat), "lon": float(x.lon), "ts": str(pd.Timestamp(x.date).date()), "sog": None, "destination": None,
                    "source": "Global Fishing Watch presence (0.1° cell)"}
        return None

    vessels = []
    for i, r in now.iterrows():
        imo = r.imo
        ev_i, idt_i = ev_g.get(imo, empty_ev), idt_g.get(imo, empty_id)
        c = dict(zip(gf.FEATURES, contrib[i]))
        why = reasons_for(r.to_dict(), c, ev_i, idt_i, now, T, ctx)
        evid = evidence_for(ev_i, idt_i, T, first_sanc, name_of, sanc_lo, ps_g.get(imo))
        for w in why:
            w["evidence"] = [x for x in evid if x["kind"] == w.pop("evidence_kind", None)][:3] if w.get("evidence_kind") else []
        rel = r.p90 / base if base else 0
        band = band_of(r.top_pct)
        if band != "low" and not why:
            why = [{"feature": None, "title": "No single dominant signal", "evidence": [], "contrib": None,
                    "text": "The score comes from a combination of weak signals. Review manually before relying on it."}]
        length = dlen["length"].get(imo) if "length" in dlen and imo in dlen.index else None
        by = r.built_year if pd.notna(r.built_year) else est_build_year(imo)
        sc = size_class(length if length is not None else np.nan, r.tonnage_gt, by,
                        "registry build year" if pd.notna(r.built_year) else ("estimated from IMO number" if by else None))
        regions = {k: round(float(r[k])) for k in gf.REGION_GROUPS if r[k] > 0}
        vessels.append({
            "imo": imo, "name": r.name_last, "mmsi": r.mmsi_last, "flag": r.flag_last, "length": None if length is None or not np.isfinite(length) else float(length),
            "size": sc, "status": "unsanctioned", "p90": round(float(r.p90), 4), "rel": round(float(rel), 2), "band": band,
            "top_pct": round(float(r.top_pct), 2), "trend": trend.get(imo, []), "build_year": None if not by else int(by),
            "tanker_status": cand.tanker_status.get(imo),
            "drivers": [{"feature": k, "label": LABELS.get(k, k), "value": None if pd.isna(r[k]) else round(float(r[k]), 3), "contrib": round(float(v), 3)}
                        for k, v in sorted(((k, v) for k, v in c.items() if k not in gf.CONTEXT), key=lambda kv: -abs(kv[1]))[:6 if band != "low" else 4]],
            "reasons": why, "evidence": evid if band != "low" else evid[:6],
            "coverage": {"hours": round(float(r.hours_total)), "regions": regions, "dma_days": None if pd.isna(r.dma_days_seen) else int(r.dma_days_seen)},
            "names_seen": sorted(set(idt_i.name.dropna()))[:8], "mmsis_seen": sorted(set(idt_i.mmsi.dropna()))[:8],
            "main_region": max(regions, key=regions.get) if regions else None,
            "last_pos": pos(imo), "track": [],
            "lists": list_status(imo), "history": history(imo, full=band != "low"),
        })

    # sanctioned tankers present in the regions (shown, not predicted)
    pres_w = pres[(pres.month_start < T) & (pres.month_start >= T - pd.DateOffset(months=6))]
    for imo in sorted(set(pres_w.imo) & sanc_set):
        vessels.append({"imo": imo, "name": name_of.get(imo), "flag": idt_g.get(imo, empty_id).flag.iloc[-1] if imo in idt_g else None,
                        "status": "sanctioned", "sanctioned_on": str(first_sanc[imo].date()), "last_pos": pos(imo),
                        "coverage": {"hours": round(float(pres_w[pres_w.imo == imo].hours.sum()))}, "lists": list_status(imo),
                        "history": history(imo, full=False),
                        "size": size_class(np.nan, pd.to_numeric(reg[reg.imo == imo].tonnage_gt, errors="coerce").max())})
    seen = {v["imo"] for v in vessels}
    for imo in lab.index.difference(list(seen)):
        st = lab.loc[imo, "first_any_on"]
        vessels.append({"imo": imo, "name": dlen["name_current"].get(imo) if imo in dlen.index else None, "status": "no_ais",
                        "lists": list_status(imo), "sanctioned_on": None if pd.isna(st) else str(st.date())})

    def clean(o):
        if isinstance(o, float):
            return round(o, 4) if np.isfinite(o) else None
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, np.floating):
            return clean(float(o))
        if isinstance(o, pd.Timestamp):
            return str(o.date())
        if isinstance(o, (np.integer, np.bool_)):
            return o.item()
        return o

    for v in vessels:
        if v.get("last_pos") and not v.get("last_seen"):
            v["last_seen"] = v["last_pos"]["ts"]
    bt = PROCESSED / "backtest_global.json"
    data = {"generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="minutes"), "scope": "global",
            "snapshot": str(T.date()), "data_date": str(DATA_DATE.date()),
            "ais_window": [str((T - gf.LB).date()), str((T - pd.Timedelta(days=1)).date())],
            "regions": {k: v for k, v in __import__("sfp.gfw_region", fromlist=["REGIONS"]).REGIONS.items()},
            "map_box": MAP_BOX, "model": meta, "base_rate_90d": base,
            "assumptions": {"size_classes": [{"max_length": a, "class": b, "dwt": c, "hull_usd": d} for a, b, c, d in config.SIZE_CLASSES],
                            "cargo_load_factor": config.CARGO_LOAD_FACTOR, "barrels_per_tonne": config.BARRELS_PER_TONNE,
                            "oil_price_usd_bbl": config.OIL_PRICE_USD_BBL, "band_high_x": config.BAND_HIGH_X, "band_medium_x": config.BAND_MEDIUM_X},
            "backtest": json.loads(bt.read_text()) if bt.exists() else None, "band_stats": band_stats,
            "insight_figures": {"ofac_ieepa_max_usd": config.OFAC_IEEPA_MAX_USD, "ofsi_max_gbp": config.OFSI_MAX_GBP,
                                "ig_oil_pollution_limit_usd": config.IG_OIL_POLLUTION_LIMIT_USD,
                                "ig_overspill_limit_usd": config.IG_OVERSPILL_LIMIT_USD,
                                "value_5yr_usd": config.VALUE_5YR_USD, "hull_range": config.HULL_VALUE_RANGE,
                                "band_high_top_pct": config.BAND_HIGH_TOP_PCT, "band_medium_top_pct": config.BAND_MEDIUM_TOP_PCT,
                                "sources": {
                                    "hull": "KOBC 5-year-old benchmarks 1 Oct 2026 (via ShipUniverse); 2026 sales of 2006-built Suezmaxes ~$50.8M (Tsakos)",
                                    "oil": "Brent futures ~$89-103/bbl Aug-Sep 2026 (TASS)",
                                    "ofac": "OFAC inflation adjustment, Federal Register 2025-00786 (Jan 2025)",
                                    "ofsi": "Policing and Crime Act 2017 s.146 (greater of GBP 1m or 50% of breach value)",
                                    "ig": "International Group P&I 2026/27 renewal circulars (North Standard, Skuld, London P&I)"}},
            "vessels": clean(vessels)}
    # Split: a light index loads with the page; full detail per ship lives in N_SHARDS
    # JSON files fetched on demand (keeps the page small as coverage grows).
    INDEX_KEYS = ("imo", "name", "mmsi", "flag", "status", "p90", "rel", "band", "main_region", "sanctioned_on",
                  "names_seen", "mmsis_seen", "last_seen", "top_pct")
    N_SHARDS = 40
    shards = {k: {} for k in range(N_SHARDS)}
    index = []
    for v in data["vessels"]:
        k = int(v["imo"]) % N_SHARDS
        light = {x: v[x] for x in INDEX_KEYS if x in v and v[x] is not None}
        if v.get("last_pos"):
            light["last_pos"] = {"lat": v["last_pos"]["lat"], "lon": v["last_pos"]["lon"]}
        if v.get("size"):
            light["size"] = {k2: v["size"][k2] for k2 in ("class", "dwt", "hull_usd") if k2 in v["size"]}
        light["shard"] = k
        index.append(light)
        shards[k][v["imo"]] = v
    data["vessels"] = index
    data["sharded"] = True
    APP.mkdir(parents=True, exist_ok=True)
    (APP / "detail").mkdir(exist_ok=True)
    for k, d in shards.items():
        (APP / "detail" / f"{k:02d}.json").write_text(json.dumps(d, separators=(",", ":"), default=str))
    (APP / "vessels.js").write_text("window.SFP_DATA = " + json.dumps(data, separators=(",", ":"), default=str) + ";\n")
    (APP / "land.js").write_text("window.SFP_LAND = " + json.dumps(land(MAP_BOX), separators=(",", ":")) + ";\n")
    elev = [v for v in vessels if v.get("band") in ("high", "medium")]
    write_manifest(PROCESSED / "score_global.manifest.json", inputs=["data/processed/features_global.parquet"],
                   outputs={"scored": len(now), "vessels": len(vessels), "elevated": len(elev)}, notes="GFW non-commercial")
    print(f"snapshot {T.date()}: scored {len(now)}, total {len(vessels)}, elevated {len(elev)}, "
          f"with evidence-backed reasons {sum(1 for v in elev if any(x['feature'] for x in v['reasons']))}")
    print("model:", meta)


if __name__ == "__main__":
    main()
