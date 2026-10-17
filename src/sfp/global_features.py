"""Stage 3 (global): snapshot features for tankers seen in Europe and the Middle East,
from Global Fishing Watch (worldwide behaviour) plus Danish AIS where available.

Population at T: candidate tankers (found by AIS presence in the REGIONS, never by a
sanctions list) present in any region in the 6 calendar months before T, and not
sanctioned (UK/EU/OFAC, any programme) before T.
Every input is filtered to timestamps strictly before T:
  presence months < T's month; events with end < T; identity periods with from < T.
Sanctions dates enter only as the label, the exclusion of already-sanctioned ships,
flag risk, and 'loitered next to a sanctioned tanker' (sanctions dated before T).

Output: data/processed/features_global.parquet (+ manifest)
"""
import numpy as np
import pandas as pd

from sfp import config
from sfp import features as dma
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, PROCESSED

LB = pd.Timedelta(days=config.GFW_LOOKBACK_DAYS)
REGION_GROUPS = {
    "h_baltic": ["baltic"], "h_north": ["north_sea_channel", "norwegian_barents"],
    "h_med": ["med_west", "med_east", "iberia_atlantic"], "h_black_sea": ["black_sea"],
    "h_red_sea": ["red_sea", "gulf_of_aden"], "h_gulf": ["persian_gulf_oman"], "h_arabian": ["arabian_sea"],
}
CONTEXT = ["hours_total", "n_regions"]
FEATURES = CONTEXT + list(REGION_GROUPS) + [
    # Registry build year, tonnage and "registry says tanker" are NOT model inputs: 71% of
    # later-sanctioned ships in the regions have no registry ship type, and the registry is
    # today's undated snapshot (records can vanish after a designation). Age comes from the
    # IMO number instead. Registry fields stay in the table for display and size estimates.
    "imo_number",
    "n_flags_12m", "n_names_12m", "n_mmsi_12m", "days_since_identity_change", "flag_risk",
    "n_port_visits", "ports_sanctioned_trade", "ports_reroute_markets", "share_port_days_sanctioned",
    "n_gaps", "n_gaps_intentional", "gap_hours", "gap_hours_max",
    "n_loiter", "loiter_hours", "loiter_hotspot_hours", "loiter_with_sanctioned",
    "chokepoint_passages", "dark_passages", "hormuz_passages", "dark_hormuz_passages",
    # Danish AIS signals (NaN when the ship was not seen in Danish waters)
    "dma_days_seen", "dma_dest_russian_frac", "dma_west_laden_frac", "dma_gaps_core_per_day",
    "dma_sts_with_sanctioned", "dma_near_sanctioned",
]
MONOTONE = {
    "imo_number": -1, "n_flags_12m": 1, "n_names_12m": 1, "n_mmsi_12m": 1, "flag_risk": 1,
    "ports_sanctioned_trade": 1, "share_port_days_sanctioned": 1, "n_gaps_intentional": 1, "gap_hours": 1,
    "loiter_hotspot_hours": 1, "loiter_with_sanctioned": 1, "dark_passages": 1, "dark_hormuz_passages": 1,
    "dma_dest_russian_frac": 1, "dma_west_laden_frac": 1, "dma_sts_with_sanctioned": 1, "dma_near_sanctioned": 1,
}
# Optional dataset groups, used by the ablation (sfp.ablation) to measure each source's value.
# Dated facts only: other authorities' listings (CA/CH/AU, known on the listing date),
# GUR catalogue entries (known from OpenSanctions first_seen), port-state detentions (+30 d lag).
OTHER_LISTS = ["other_lists_n", "days_since_other_listing", "gur_listed", "psc_detentions_3y", "psc_banned"]
LOITER_PAIR_KM = 5.0  # ASSUMPTION: two tankers loitering at overlapping times within 5 km


def load():
    pres = pd.read_parquet(INTERIM / "gfw_presence.parquet")
    pres["month_start"] = pd.to_datetime(pres["month"] + "-01")
    ident = pd.read_parquet(INTERIM / "gfw_identity.parquet")
    reg = pd.read_parquet(INTERIM / "gfw_registry.parquet")
    ev = pd.read_parquet(INTERIM / "gfw_events.parquet")
    cand = pd.read_parquet(INTERIM / "gfw_candidates.parquet").set_index("imo")
    return pres, ident, reg, ev, cand


def registry_static(reg: pd.DataFrame) -> pd.DataFrame:
    r = reg.copy()
    r["built_year"] = pd.to_numeric(r["built_year"], errors="coerce")
    r["tonnage_gt"] = pd.to_numeric(r["tonnage_gt"], errors="coerce")
    g = r.groupby("imo")
    return pd.DataFrame({"built_year": g["built_year"].median(), "tonnage_gt": g["tonnage_gt"].max(),
                         "operator": g["operator"].agg(lambda s: next((x for x in s if x), None))})


def in_box(lat, lon, b):
    return (lon >= b[0]) & (lon <= b[2]) & (lat >= b[1]) & (lat <= b[3])


def loiter_with_sanctioned(lo: pd.DataFrame, sanc: set) -> pd.Series:
    """Count, per IMO, loitering events that overlap in time with a loitering event of an
    already-sanctioned tanker within LOITER_PAIR_KM."""
    if lo.empty:
        return pd.Series(dtype=float)
    lo = lo.dropna(subset=["lat", "lon"]).copy()
    lo["cell"] = list(zip((lo.lat * 10).round().astype(int), (lo.lon * 10).round().astype(int)))
    s = lo[lo.imo.isin(sanc)]
    if s.empty:
        return pd.Series(dtype=float)
    u = lo[~lo.imo.isin(sanc)]
    # neighbouring cells (0.1 deg ~ 11 km) to catch pairs across cell edges
    sx = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            t = s.copy()
            t["cell"] = [(a + di, b + dj) for a, b in t["cell"]]
            sx.append(t)
    s = pd.concat(sx)
    m = u.merge(s, on="cell", suffixes=("", "_s"))
    m = m[(m.start < m.end_s) & (m.start_s < m.end)]
    la1, lo1, la2, lo2 = map(np.radians, (m.lat, m.lon, m.lat_s, m.lon_s))
    d = 2 * 6371 * np.arcsin(np.sqrt(np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2))
    m = m[d < LOITER_PAIR_KM]
    return m.drop_duplicates(["imo", "start"]).groupby("imo").size()


def basin_of(lat, lon):
    for name, b in config.BASINS.items():
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]:
            return name
    return None


def passages(pv: pd.DataFrame, gaps: pd.DataFrame) -> pd.DataFrame:
    """Chokepoint passages inferred from consecutive port calls on opposite sides of a basin
    boundary; dark when an intentional AIS gap overlaps the time between the calls."""
    if pv.empty:
        return pd.DataFrame(columns=["imo", "basin", "left", "arrived", "from_port", "to_port", "dark_h", "direction"])
    p = pv.dropna(subset=["lat", "lon"]).sort_values(["imo", "start"]).copy()
    p["basin"] = [basin_of(a, b) for a, b in zip(p.lat, p.lon)]
    p["next_basin"] = p.groupby("imo")["basin"].shift(-1)
    p["next_start"] = p.groupby("imo")["start"].shift(-1)
    p["next_port"] = p.groupby("imo")["port_name"].shift(-1)
    x = p[p.next_start.notna() & (p.basin.fillna("open sea") != p.next_basin.fillna("open sea"))].copy()
    x["crossed"] = np.where(x.basin.notna(), x.basin, x.next_basin)
    x["direction"] = np.where(x.basin.notna(), "out of", "into")
    rows = []
    g = gaps.groupby("imo") if len(gaps) else None
    for r in x.itertuples():
        dark = 0.0
        if g is not None and r.imo in g.groups:
            gg = g.get_group(r.imo)
            o = gg[(gg.start < r.next_start) & (gg.end > r.end)]
            dark = float(o.duration_h.fillna(0).sum())
        rows.append({"imo": r.imo, "basin": r.crossed, "left": r.end, "arrived": r.next_start,
                     "from_port": r.port_name, "to_port": r.next_port, "dark_h": dark, "direction": r.direction})
    return pd.DataFrame(rows)


def other_list_feats(f_index, os_ev, T):
    o = os_ev[os_ev.known_at < T]
    out = pd.DataFrame(index=f_index)
    s = o[o.kind == "sanction"]
    out["other_lists_n"] = s.groupby("imo").dataset.nunique().reindex(f_index).fillna(0)
    out["days_since_other_listing"] = (T - s.groupby("imo").known_at.max()).dt.days.reindex(f_index)
    out["gur_listed"] = o[o.kind == "gur_catalogue"].groupby("imo").size().reindex(f_index).fillna(0).clip(upper=1)
    d = o[(o.kind == "detention") & (pd.to_datetime(o.event_date, errors="coerce") >= T - pd.Timedelta(days=3 * 365))]
    out["psc_detentions_3y"] = d.groupby("imo").size().reindex(f_index).fillna(0)
    out["psc_banned"] = o[o.kind == "psc_ban"].groupby("imo").size().reindex(f_index).fillna(0).clip(upper=1)
    return out


def snapshot(T, pres, ident, ev, cand, regstat, first_sanc, label_end, dma_snap=None, os_ev=None):
    sanc_before = set(first_sanc[first_sanc < T].index)
    p = pres[(pres.month_start < T) & (pres.month_start >= T - LB - pd.Timedelta(days=31))]
    p = p[p.month_start >= (T - pd.DateOffset(months=6))]
    if p.empty:
        return pd.DataFrame()
    p = p[p.imo.isin(cand.index)]
    present = set(p.imo)

    # identity as of T
    idt = ident[ident["from"] < T].copy()
    idt["to_c"] = idt["to"].clip(upper=T)
    cur = idt.sort_values("from").groupby("imo").tail(1).set_index("imo")
    win12 = idt[idt["to_c"] >= T - pd.Timedelta(days=365)]
    g12 = win12.groupby("imo")
    last_change = idt.groupby("imo")["from"].max()

    # flag risk over everyone present (sanctioned included), sanctions before T only
    fl = pd.DataFrame({"imo": sorted(present)})
    fl["flag"] = fl.imo.map(cur["flag"])
    fl["s"] = fl.imo.isin(sanc_before)
    agg = fl.groupby("flag")["s"].agg(["sum", "count"])
    prior, m_ = fl["s"].mean(), 10.0
    flag_risk = (agg["sum"] + m_ * prior) / (agg["count"] + m_)

    pop = sorted(present - sanc_before)
    f = pd.DataFrame(index=pd.Index(pop, name="imo"))
    ph = p.groupby(["imo", "region"])["hours"].sum().unstack(fill_value=0)
    for k, regs in REGION_GROUPS.items():
        f[k] = ph.reindex(columns=regs, fill_value=0).sum(axis=1).reindex(f.index).fillna(0)
    f["hours_total"] = ph.sum(axis=1).reindex(f.index).fillna(0)
    f["n_regions"] = (ph > 0).sum(axis=1).reindex(f.index).fillna(0)
    f["imo_number"] = pd.to_numeric(f.index.to_series(), errors="coerce")
    f = f.join(regstat[["built_year", "tonnage_gt"]], how="left")
    f["registry_verified"] = cand["tanker_status"].reindex(f.index).eq("verified").astype(int)
    f["n_flags_12m"] = g12["flag"].nunique().reindex(f.index)
    f["n_names_12m"] = g12["name"].nunique().reindex(f.index)
    f["n_mmsi_12m"] = g12["mmsi"].nunique().reindex(f.index)
    f["days_since_identity_change"] = (T - last_change).dt.days.reindex(f.index)
    f["flag_last"] = cur["flag"].reindex(f.index)
    f["name_last"] = cur["name"].reindex(f.index)
    f["mmsi_last"] = cur["mmsi"].reindex(f.index)
    f["flag_risk"] = f["flag_last"].map(flag_risk).fillna(prior)

    e = ev[(ev.end < T) & (ev.end >= T - LB)]
    pv = e[e.kind == "port_visit"]
    pg = pv.groupby("imo")
    f["n_port_visits"] = pg.size().reindex(f.index).fillna(0)
    st = pv.port_country.isin(config.SANCTIONED_TRADE_PORT_COUNTRIES)
    f["ports_sanctioned_trade"] = pv[st].groupby("imo").size().reindex(f.index).fillna(0)
    f["ports_reroute_markets"] = pv[pv.port_country.isin(config.REROUTE_MARKETS)].groupby("imo").size().reindex(f.index).fillna(0)
    dur = pv.assign(h=pv.duration_h.fillna(0))
    tot = dur.groupby("imo")["h"].sum()
    f["share_port_days_sanctioned"] = (dur[st].groupby("imo")["h"].sum() / tot.where(tot > 0)).reindex(f.index).fillna(0)
    gp = e[e.kind == "ais_gap"]
    f["n_gaps"] = gp.groupby("imo").size().reindex(f.index).fillna(0)
    f["n_gaps_intentional"] = gp[gp.intentional.fillna(False).astype(bool)].groupby("imo").size().reindex(f.index).fillna(0)
    f["gap_hours"] = gp.groupby("imo")["duration_h"].sum().reindex(f.index).fillna(0)
    f["gap_hours_max"] = gp.groupby("imo")["duration_h"].max().reindex(f.index).fillna(0)
    lo = e[e.kind == "loitering"]
    f["n_loiter"] = lo.groupby("imo").size().reindex(f.index).fillna(0)
    f["loiter_hours"] = lo.groupby("imo")["duration_h"].sum().reindex(f.index).fillna(0)
    hot = np.zeros(len(lo), dtype=bool)
    for b in config.STS_HOTSPOTS.values():
        hot |= in_box(lo.lat, lo.lon, b).to_numpy()
    f["loiter_hotspot_hours"] = lo[hot].groupby("imo")["duration_h"].sum().reindex(f.index).fillna(0)
    lo_all = ev[(ev.kind == "loitering") & (ev.end < T) & (ev.end >= T - LB)]
    f["loiter_with_sanctioned"] = loiter_with_sanctioned(lo_all, sanc_before).reindex(f.index).fillna(0)

    ps = passages(pv, gp)
    ps = ps[ps.arrived < T] if len(ps) else ps
    pgp = ps.groupby("imo") if len(ps) else None
    for col, cond in (("chokepoint_passages", lambda d: d), ("dark_passages", lambda d: d[d.dark_h > 0]),
                      ("hormuz_passages", lambda d: d[d.basin == "Persian Gulf"]),
                      ("dark_hormuz_passages", lambda d: d[(d.basin == "Persian Gulf") & (d.dark_h > 0)])):
        f[col] = cond(ps).groupby("imo").size().reindex(f.index).fillna(0) if len(ps) else 0.0

    if dma_snap is not None and len(dma_snap):
        d = dma_snap.set_index("imo")
        for a, b in (("dma_days_seen", "days_seen"), ("dma_dest_russian_frac", "dest_russian_frac"),
                     ("dma_west_laden_frac", "west_laden_frac"), ("dma_gaps_core_per_day", "gaps_core_per_day"),
                     ("dma_sts_with_sanctioned", "sts_with_sanctioned"), ("dma_near_sanctioned", "near_sanctioned")):
            f[a] = d[b].reindex(f.index)
    if os_ev is not None:
        f = f.join(other_list_feats(f.index, os_ev, T))
    for c in FEATURES + OTHER_LISTS:
        if c not in f:
            f[c] = np.nan

    fs = first_sanc.reindex(f.index)
    f["sanctioned_on"] = fs
    f["label"] = ((fs >= T) & (fs < min(T + pd.Timedelta(days=config.LABEL_HORIZON_DAYS), label_end))).astype(int)
    f["T"] = T
    return f.reset_index()


def snapshot_dates():
    first = pd.read_parquet(INTERIM / "gfw_presence.parquet")["month"].min()
    return list(pd.date_range(pd.Timestamp(first + "-01") + pd.DateOffset(months=6), "2026-10-01", freq="MS"))


def build():
    pres, ident, reg, ev, cand = load()
    regstat = registry_static(reg)
    first_sanc = dma.sanction_dates()
    sd = dma.load_shipdays()
    pairs = dma.load_pairs(sd)
    os_ev = pd.read_parquet(INTERIM / "os_events.parquet").dropna(subset=["imo", "known_at"])
    cutoff, data_date = pd.Timestamp(config.TRAIN_CUTOFF), pd.Timestamp("2026-10-16")
    rows = []
    for T in snapshot_dates():
        label_end = cutoff if T < cutoff else data_date
        dsnap = dma.snapshot(T, sd, pairs, first_sanc, label_end)
        f = snapshot(T, pres, ident, ev, cand, regstat, first_sanc, label_end, dsnap, os_ev)
        if len(f):
            f["split"] = "train" if T < cutoff else "test"
            f["label_complete"] = (T + pd.Timedelta(days=config.LABEL_HORIZON_DAYS)) <= label_end
            rows.append(f)
            print(T.date(), len(f), int(f.label.sum()), flush=True)
    return pd.concat(rows, ignore_index=True)


def main():
    df = build()
    df.to_parquet(PROCESSED / "features_global.parquet", index=False)
    summ = df.groupby("T").agg(ships=("imo", "size"), positives=("label", "sum"))
    write_manifest(PROCESSED / "features_global.manifest.json",
                   inputs=["data/interim/gfw_*.parquet", "data/interim/ais_v2", "data/interim/labels.parquet"],
                   outputs={"rows": len(df), "features": FEATURES,
                            "per_snapshot": {str(k.date()): {"ships": int(v.ships), "positives": int(v.positives)}
                                             for k, v in summ.iterrows()}},
                   notes=f"GFW lookback {config.GFW_LOOKBACK_DAYS}d; population from regional presence, not lists")


if __name__ == "__main__":
    main()
