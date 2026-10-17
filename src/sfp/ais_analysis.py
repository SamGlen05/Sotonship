"""Stage 2 (AIS only): analysis of the Danish Maritime Authority AIS sample itself.

Uses NO sanctions list or other dataset: every number comes from data/interim/ais_v2.
Feature correlations are computed for ALL tankers seen (no sanctioned/unsanctioned
split) at the latest snapshot, on the AIS-only features (flag_risk and the
sanctioned-partner counts are excluded because they use list dates).

Writes app/data/analysis.js and reports/05_ais_feature_correlation.png
"""
import json

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sfp import config  # noqa: E402
from sfp.features import AIS, FEATURES, load_pairs, load_shipdays, snapshot, snapshot_dates  # noqa: E402
from sfp.manifest import write_manifest  # noqa: E402
from sfp.paths import REPORTS, ROOT  # noqa: E402

LIST_BASED = {"flag_risk", "sts_with_sanctioned", "near_sanctioned"}
DROPPED = ["n_mmsi_12m", "width", "max_gap_h"]  # analysed here; removed from the model for redundancy
AIS_FEATURES = [f for f in FEATURES if f not in LIST_BASED]
AIS_FEATURES = AIS_FEATURES[:4] + ["width"] + AIS_FEATURES[4:6] + ["n_mmsi_12m"] + AIS_FEATURES[6:] + ["max_gap_h"]
LABELS = {
    "days_seen": "Days seen", "days_since_last_seen": "Days since last seen", "imo_number": "IMO number (age proxy)",
    "length": "Length", "width": "Beam", "draught_max": "Max draught",
    "n_mmsi_12m": "MMSIs used (12m)", "n_names_12m": "Names used (12m)", "n_flags_12m": "Flags used (12m)",
    "flag_is_russia": "Russian flag", "dest_russian_frac": "Russian-port destination",
    "dest_notable_frac": "'FOR ORDERS' destination", "dest_missing_frac": "Blank destination",
    "west_laden_frac": "Westbound laden", "east_laden_frac": "Eastbound laden", "baltic_side_frac": "Baltic-side share",
    "cross_per_day": "Straits crossings/day", "gaps_core_per_day": "AIS gaps/day", "max_gap_h": "Longest AIS gap",
    "spoof_per_day": "Position jumps/day", "slow_underway_h_per_day": "Drifting h/day", "anchor_h_per_day": "Anchor h/day",
    "sts_count": "Ship-to-ship meetings",
}


def daily_stats() -> pd.DataFrame:
    return duckdb.sql(f"""
        SELECT day, count(*) FILTER (WHERE mobile = 'Class A') AS class_a,
               count(*) FILTER (WHERE mobile = 'Class A' AND ship_type = 'Tanker') AS tankers,
               avg((imo_ais IS NOT NULL)::INT) FILTER (WHERE ship_type = 'Tanker') AS tanker_imo_share,
               avg((draught_max IS NOT NULL)::INT) FILTER (WHERE ship_type = 'Tanker') AS tanker_draught_share,
               sum(n_msgs) AS messages
        FROM read_parquet('{AIS}/static/*.parquet') GROUP BY day ORDER BY day
    """).df()


def type_mix() -> pd.DataFrame:
    return duckdb.sql(f"""
        SELECT coalesce(ship_type, 'Not reported') AS ship_type, count(*) AS vessel_days
        FROM read_parquet('{AIS}/static/*.parquet') WHERE mobile = 'Class A'
        GROUP BY 1 ORDER BY 2 DESC
    """).df()


def density(step=0.1) -> dict:
    """Tanker position density on a grid (fixes per cell, all sampled days)."""
    g = duckdb.sql(f"""
        WITH t AS (SELECT DISTINCT mmsi, day FROM read_parquet('{AIS}/static/*.parquet')
                   WHERE mobile = 'Class A' AND ship_type = 'Tanker')
        SELECT floor(p.lat / {step}) * {step} AS lat, floor(p.lon / {step}) * {step} AS lon, count(*) AS n
        FROM read_parquet('{AIS}/pos/*.parquet', filename = true) p
        JOIN t ON p.mmsi = t.mmsi AND CAST(p.ts AS DATE) = t.day
        WHERE p.lat BETWEEN 53 AND 61 AND p.lon BETWEEN 2 AND 22
        GROUP BY 1, 2
    """).df()
    return {"step": step, "cells": [[round(a, 2), round(b, 2), int(n)] for a, b, n in zip(g.lat, g.lon, g.n)]}


def destinations(sd: pd.DataFrame, top=15) -> list:
    d = sd.dropna(subset=["destinations"]).assign(dest=lambda x: x.destinations.str.split("|")).explode("dest")
    d["dest"] = d["dest"].str.strip()
    v = d.groupby("dest")["imo"].nunique().sort_values(ascending=False).head(top)
    return [{"destination": k, "tankers": int(n)} for k, n in v.items()]


def monthly_behaviour(sd: pd.DataFrame) -> list:
    m = sd.assign(month=sd.day.dt.to_period("M").astype(str)).groupby("month").agg(
        tanker_days=("imo", "size"), tankers=("imo", "nunique"),
        dest_russian=("dest_russian", "mean"), dest_notable=("dest_notable", "mean"),
        gap_days=("n_gaps_core", lambda s: float((s.fillna(0) > 0).mean())),
        spoof_days=("n_spoof_jumps", lambda s: float((s.fillna(0) > 0).mean())))
    return [{"month": k, **{c: (round(float(v), 4) if isinstance(v, float) else int(v)) for c, v in r.items()}}
            for k, r in m.iterrows()]


def main():
    sd = load_shipdays()
    pairs = load_pairs(sd)
    T = snapshot_dates()[-1]
    no_lists = pd.Series(dtype="datetime64[ns]")  # no sanctions information at all
    feat = snapshot(T, sd, pairs, no_lists, pd.Timestamp("2026-10-16"))
    X = feat[AIS_FEATURES].astype(float)
    corr = X.corr(method="spearman").round(3)
    summary = []
    for f in AIS_FEATURES:
        s = X[f]
        summary.append({"feature": f, "label": LABELS[f], "missing_pct": round(100 * s.isna().mean(), 1),
                        "nonzero_pct": round(100 * (s.fillna(0) != 0).mean(), 1),
                        "median": None if s.isna().all() else round(float(s.median()), 3),
                        "p90": None if s.isna().all() else round(float(s.quantile(0.9)), 3)})
    pairs_sorted = (corr.where(np.triu(np.ones(corr.shape, dtype=bool), k=1)).stack()
                    .sort_values(key=lambda s: -s.abs()).head(8))
    daily = daily_stats()
    daily["day"] = pd.to_datetime(daily["day"]).dt.date
    out = {
        "snapshot": str(T.date()), "window_days": 180, "tankers_in_snapshot": len(feat),
        "sampled_days": len(daily), "first_day": str(daily.day.min()), "last_day": str(daily.day.max()),
        "daily": [{"day": str(r.day), "class_a": int(r.class_a), "tankers": int(r.tankers),
                   "tanker_imo_share": round(float(r.tanker_imo_share), 4),
                   "tanker_draught_share": round(float(r.tanker_draught_share), 4), "messages": int(r.messages)}
                  for r in daily.itertuples()],
        "type_mix": type_mix().head(10).to_dict("records"),
        "tankers_total": int(sd.imo.nunique()),
        "destinations": destinations(sd),
        "monthly": monthly_behaviour(sd),
        "density": density(),
        "corr": {"features": AIS_FEATURES, "labels": [LABELS[f] for f in AIS_FEATURES],
                 "matrix": [[None if not np.isfinite(v) else float(v) for v in row] for row in corr.values]},
        "top_pairs": [{"a": LABELS[a], "b": LABELS[b], "rho": round(float(v), 3)} for (a, b), v in pairs_sorted.items()],
        "summary": summary,
        "thresholds": {"gap_h": config.AIS_INTRADAY_GAP_HOURS, "sts_nm": config.STS_DISTANCE_NM,
                       "sts_h": config.STS_MIN_HOURS, "spoof_kn": config.SPOOF_SPEED_KN},
    }
    p = ROOT / "app" / "data"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analysis.js").write_text("window.SFP_ANALYSIS = " + json.dumps(out, separators=(",", ":"), default=str) + ";\n")

    # static heatmap for README / pitch (diverging blue-grey-red, Spearman)
    fig, ax = plt.subplots(figsize=(11, 9.5))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])
    im = ax.imshow(corr.values, cmap=cmap, vmin=-1, vmax=1)
    lab = [LABELS[f] for f in AIS_FEATURES]
    ax.set_xticks(range(len(lab)), lab, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(lab)), lab, fontsize=8)
    ax.set_title(f"Spearman correlation of AIS features, {len(feat)} tankers, snapshot {T.date()}", loc="left",
                 fontsize=11, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7, label="Spearman rho")
    fig.text(0.01, 0.01, f"Danish Maritime Authority historical AIS, {len(daily)} sampled days "
             f"{daily.day.min()} to {daily.day.max()}. No sanctions data used.", fontsize=7, color="#898781")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(REPORTS / "05_ais_feature_correlation.png", dpi=150, facecolor="#fcfcfb")
    write_manifest(REPORTS / "ais_analysis.manifest.json", inputs=["data/interim/ais_v2"],
                   outputs={"tankers": len(feat), "sampled_days": len(daily)}, notes="AIS only; no list data")
    print(json.dumps({k: out[k] for k in ("snapshot", "tankers_in_snapshot", "sampled_days", "tankers_total", "top_pairs")}, indent=1))


if __name__ == "__main__":
    main()
