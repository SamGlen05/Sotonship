"""Stage 2 (Global Fishing Watch): analysis of the GFW tanker data itself, plus the one
comparison that decides its value: how many later-sanctioned ships each source sees
before designation (Danish AIS sample vs GFW Europe + Middle East).

Writes app/data/gfw_analysis.js and reports/06_gfw_feature_correlation.png
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from sfp import config  # noqa: E402
from sfp import global_features as gf  # noqa: E402
from sfp.gfw_region import REGIONS, presence_table  # noqa: E402
from sfp.manifest import write_manifest  # noqa: E402
from sfp.paths import INTERIM, PROCESSED, REPORTS, ROOT  # noqa: E402

LIST_BASED = {"flag_risk", "loiter_with_sanctioned", "dma_sts_with_sanctioned", "dma_near_sanctioned"}
EXTRA = ["built_year", "tonnage_gt", "registry_verified"]  # analysed, not model inputs
LABELS = {
    "hours_total": "Hours present (6m)", "n_regions": "Regions visited", "h_baltic": "Hours Baltic",
    "h_north": "Hours North Sea / Norway", "h_med": "Hours Mediterranean / Iberia", "h_black_sea": "Hours Black Sea",
    "h_red_sea": "Hours Red Sea / Aden", "h_gulf": "Hours Persian Gulf / Oman", "h_arabian": "Hours Arabian Sea",
    "imo_number": "IMO number (age proxy)", "built_year": "Build year (registry)", "tonnage_gt": "Gross tonnage",
    "registry_verified": "Registry says tanker", "n_flags_12m": "Flags used (12m)", "n_names_12m": "Names used (12m)",
    "n_mmsi_12m": "MMSIs used (12m)", "days_since_identity_change": "Days since identity change",
    "n_port_visits": "Port visits", "ports_sanctioned_trade": "Port calls RU/IR/VE/SY/KP",
    "ports_reroute_markets": "Port calls IN/CN/TR/AE/EG/MY/SG", "share_port_days_sanctioned": "Port time in RU/IR/VE/SY/KP",
    "n_gaps": "AIS gaps", "n_gaps_intentional": "Intentional AIS gaps", "gap_hours": "AIS gap hours",
    "gap_hours_max": "Longest AIS gap", "n_loiter": "Loitering events", "loiter_hours": "Loitering hours",
    "loiter_hotspot_hours": "Loitering at transfer hotspots", "dma_days_seen": "Danish AIS days seen",
    "dma_dest_russian_frac": "Danish AIS: Russian destination", "dma_west_laden_frac": "Danish AIS: westbound laden",
    "dma_gaps_core_per_day": "Danish AIS: gaps per day",
}


def main():
    pres_all = presence_table()
    pres, ident, reg, ev, cand = gf.load()
    lab = pd.read_parquet(INTERIM / "labels.parquet")
    feats = pd.read_parquet(PROCESSED / "features_global.parquet")

    # coverage per region
    cov = []
    for r in REGIONS:
        a = pres_all[pres_all.region == r]
        t = pres[pres.region == r]
        cov.append({"region": r, "vessels": int(a.vessel_id.nunique()), "imo_vessels": int(a.imo.nunique()),
                    "candidate_tankers": int(t.imo.nunique()),
                    "verified": int(t[t.imo.isin(cand.index[cand.tanker_status == "verified"])].imo.nunique())})
    monthly = pres.groupby(["region", "month"]).imo.nunique().unstack(fill_value=0)

    # identity churn: flags per IMO in the last 12 months of data
    last12 = ident[ident["to"] >= pd.Timestamp("2025-10-01")]
    churn = last12.groupby("imo").flag.nunique().value_counts().sort_index()
    flags_now = ident.sort_values("from").groupby("imo").tail(1).flag.value_counts().head(15)

    pv = ev[ev.kind == "port_visit"]
    port_c = pv.groupby("port_country").imo.nunique().sort_values(ascending=False).head(20)
    gp = ev[(ev.kind == "ais_gap")]
    lo = ev[ev.kind == "loitering"]
    hot = []
    for name, b in config.STS_HOTSPOTS.items():
        m = gf.in_box(lo.lat, lo.lon, b)
        hot.append({"hotspot": name, "tankers": int(lo[m].imo.nunique()), "hours": round(float(lo[m].duration_h.sum()), 0)})

    # coverage of later-sanctioned ships, before their designation
    sanc = lab.dropna(subset=["first_any_on"])
    first_seen_gfw = pres.groupby("imo").month_start.min()
    dma_days = pd.read_parquet(INTERIM / "ais_days.parquet") if (INTERIM / "ais_days.parquet").exists() else None
    import duckdb
    sd = duckdb.sql(f"SELECT imo, min(day) AS d FROM read_parquet('{INTERIM}/ais_v2/shipday/*.parquet') GROUP BY imo").df()
    first_seen_dma = sd.set_index("imo")["d"].astype("datetime64[ns]")
    batches = []
    for name, sel in (("UK 2026-06-16", lab.uk_batch == pd.Timestamp("2026-06-16")),
                      ("UK 2026-10-01", lab.uk_batch == pd.Timestamp("2026-10-01")),
                      ("UK 2026-10-08", lab.uk_batch == pd.Timestamp("2026-10-08")),
                      ("All first sanctions 2025-01 to 2026-10", (lab.first_any_on >= "2025-01-01"))):
        b = lab[sel]
        d0 = b.uk_designated_on if name.startswith("UK") else b.first_any_on
        g = (first_seen_gfw.reindex(b.imo).values < d0.values)
        dd = (first_seen_dma.reindex(b.imo).values < d0.values)
        batches.append({"batch": name, "ships": len(b), "gfw_before": int(np.nansum(g)), "dma_before": int(np.nansum(dd))})

    # correlation of AIS/GFW-only features at the latest snapshot (all tankers present)
    T = feats["T"].max()
    X = feats[feats["T"] == T]
    cols = [c for c in gf.FEATURES + EXTRA if c not in LIST_BASED and c in X and X[c].notna().mean() > 0.05]
    corr = X[cols].astype(float).corr(method="spearman").round(3)
    top = (corr.where(np.triu(np.ones(corr.shape, dtype=bool), k=1)).stack().sort_values(key=lambda s: -s.abs()).head(8))
    summ = [{"feature": c, "label": LABELS.get(c, c), "nonzero_pct": round(100 * (X[c].fillna(0) != 0).mean(), 1),
             "missing_pct": round(100 * X[c].isna().mean(), 1),
             "median": None if X[c].isna().all() else round(float(X[c].median()), 2),
             "p90": None if X[c].isna().all() else round(float(X[c].quantile(.9)), 2)} for c in cols]

    out = {
        "period": [str(pres.month.min()), str(pres.month.max())], "snapshot": str(T.date()),
        "regions": cov, "region_boxes": REGIONS,
        "monthly": {"months": list(monthly.columns), "rows": {r: [int(v) for v in monthly.loc[r]] for r in monthly.index}},
        "candidates": {"total": int(len(cand)), "verified": int((cand.tanker_status == "verified").sum()),
                       "unverified": int((cand.tanker_status == "unverified").sum())},
        "tankers_in_snapshot": int(len(X)),
        "flag_churn_12m": {str(int(k)): int(v) for k, v in churn.items()},
        "flags_now": {k: int(v) for k, v in flags_now.items()},
        "port_countries": {k: int(v) for k, v in port_c.items()},
        "events": {"port_visits": int((ev.kind == "port_visit").sum()), "gaps": int(len(gp)),
                   "gaps_intentional": int(gp.intentional.fillna(False).astype(bool).sum()),
                   "loitering": int(len(lo)), "tankers_with_events": int(ev.imo.nunique())},
        "hotspots": sorted(hot, key=lambda h: -h["hours"]),
        "coverage_sanctioned": batches,
        "corr": {"features": cols, "labels": [LABELS.get(c, c) for c in cols],
                 "matrix": [[None if not np.isfinite(v) else float(v) for v in row] for row in corr.values]},
        "top_pairs": [{"a": LABELS.get(a, a), "b": LABELS.get(b, b), "rho": round(float(v), 3)} for (a, b), v in top.items()],
        "summary": summ,
    }
    (ROOT / "app" / "data" / "gfw_analysis.js").write_text("window.SFP_GFW = " + json.dumps(out, separators=(",", ":"), default=str) + ";\n")

    fig, ax = plt.subplots(figsize=(11.5, 10))
    im = ax.imshow(corr.values, cmap=LinearSegmentedColormap.from_list("d", ["#2a78d6", "#f0efec", "#e34948"]), vmin=-1, vmax=1)
    lab_ = [LABELS.get(c, c) for c in cols]
    ax.set_xticks(range(len(lab_)), lab_, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(lab_)), lab_, fontsize=8)
    ax.set_title(f"Spearman correlation of global tanker signals, {len(X)} tankers, snapshot {T.date()}", loc="left",
                 fontsize=11, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7, label="Spearman rho")
    fig.text(0.01, 0.01, "Global Fishing Watch API (presence, identity, port visits, gaps, loitering), retrieved 2026-10-17; "
             "Danish Maritime Authority AIS. Non-commercial licence. No sanctions data in these signals.", fontsize=7, color="#898781")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(REPORTS / "06_gfw_feature_correlation.png", dpi=150, facecolor="#fcfcfb")
    write_manifest(REPORTS / "gfw_analysis.manifest.json", inputs=["data/interim/gfw_*.parquet"],
                   outputs={"tankers": int(len(X))}, notes="GFW non-commercial licence")
    print(json.dumps({k: out[k] for k in ("period", "candidates", "events", "coverage_sanctioned", "top_pairs")}, indent=1))


if __name__ == "__main__":
    main()
