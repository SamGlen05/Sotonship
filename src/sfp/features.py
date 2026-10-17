"""Stage 3: snapshot feature table from ONE feature dataset (DMA AIS), labelled
with sanctions-list dates.

For snapshot T (1st of each month):
  population : tankers (AIS type) seen on >=1 sampled AIS day in [T - LOOKBACK, T)
               and NOT sanctioned (UK, EU or OFAC, any programme) before T
  features   : aggregates of AIS ship-days strictly before T (see FEATURES)
  label      : first sanction (UK/EU/OFAC) in [T, T + LABEL_HORIZON_DAYS);
               for training snapshots the window is clipped at TRAIN_CUTOFF
Time safety: every input row carries a date; each filter is `< T`. Sanctions
dates are used only for (a) the label, (b) excluding already-sanctioned ships,
(c) 'flag risk' and 'near/met a sanctioned ship', which count only sanctions before T.

Output: data/processed/features.parquet (+ manifest)
"""
import duckdb
import numpy as np
import pandas as pd

from sfp import config
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, PROCESSED

AIS = INTERIM / "ais_v2"
LOOKBACK = pd.Timedelta(days=180)  # ASSUMPTION: 180-day look-back (docs/PIPELINE.md default)
ID_LOOKBACK = pd.Timedelta(days=config.IDENTITY_LOOKBACK_DAYS)

# Context features describe how much we saw, not behaviour; they are model inputs
# (so evidence is weighed by exposure) but never shown as reasons.
CONTEXT = ["days_seen", "days_since_last_seen"]
# Dropped after the AIS correlation analysis (reports/05_ais_feature_correlation.png):
# n_mmsi_12m (rho 1.0 with n_flags_12m: flag is derived from MMSI), width (rho 0.98
# with length), max_gap_h (tracks days_seen and coverage exits, not going dark).
# They stay in the table for analysis, not in the model.
FEATURES = CONTEXT + [
    "imo_number",                                   # age proxy (IMO numbers are issued in sequence)
    "length", "draught_max",
    "n_names_12m", "n_flags_12m",                   # identity churn
    "flag_risk", "flag_is_russia",
    "dest_russian_frac", "dest_notable_frac", "dest_missing_frac",
    "west_laden_frac", "east_laden_frac", "baltic_side_frac", "cross_per_day",
    "gaps_core_per_day", "spoof_per_day",
    "slow_underway_h_per_day", "anchor_h_per_day",
    "sts_count", "sts_with_sanctioned", "near_sanctioned",
]
# Domain priors for LightGBM monotone constraints (+1 risk can only rise with the value).
MONOTONE = {
    "imo_number": -1, "n_names_12m": 1, "n_flags_12m": 1, "flag_risk": 1,
    "dest_russian_frac": 1, "dest_notable_frac": 1, "dest_missing_frac": 1, "west_laden_frac": 1,
    "gaps_core_per_day": 1, "spoof_per_day": 1, "sts_with_sanctioned": 1, "near_sanctioned": 1,
}


def load_shipdays() -> pd.DataFrame:
    sd = duckdb.sql(f"SELECT * FROM read_parquet('{AIS}/shipday/*.parquet')").df()
    sd = sd.dropna(subset=["imo"])
    sd["day"] = pd.to_datetime(sd["day"])
    mid = pd.read_parquet(INTERIM / "mid_flags.parquet").set_index("mid")["flag_from_mmsi"]
    sd["flag"] = sd["mmsi"].str[:3].map(mid).fillna("Unknown")
    return sd


def _pairs(kind: str, sd: pd.DataFrame) -> pd.DataFrame:
    st = duckdb.sql(f"SELECT * FROM read_parquet('{AIS}/{kind}/*.parquet')").df()
    st["day"] = pd.to_datetime(st["day"])
    key = sd[["mmsi", "day", "imo"]].drop_duplicates(["mmsi", "day"])
    st = st.merge(key.rename(columns={"mmsi": "mmsi_a", "imo": "imo_a"}), on=["mmsi_a", "day"], how="left")
    st = st.merge(key.rename(columns={"mmsi": "mmsi_b", "imo": "imo_b"}), on=["mmsi_b", "day"], how="left")
    st = st.dropna(subset=["imo_a", "imo_b"])
    both = pd.concat([st.rename(columns={"imo_a": "imo", "imo_b": "partner"}),
                      st.rename(columns={"imo_b": "imo", "imo_a": "partner"})])
    return both[["day", "imo", "partner", "hours", "lat", "lon"]]


def load_pairs(sd: pd.DataFrame) -> dict:
    """Ship-to-ship meetings (sts) and looser lingering-nearby events (near)."""
    return {"sts": _pairs("sts", sd), "near": _pairs("near", sd)}


def sanction_dates() -> pd.Series:
    """First sanction date per IMO, any of UK / EU / OFAC, any programme."""
    lab = pd.read_parquet(INTERIM / "labels.parquet")
    return lab.set_index("imo")["first_any_on"]


def snapshot(T: pd.Timestamp, sd, pairs: dict, first_sanc: pd.Series, label_end: pd.Timestamp) -> pd.DataFrame:
    w = sd[(sd.day < T) & (sd.day >= T - LOOKBACK)].copy()
    if w.empty:
        return pd.DataFrame()
    w12 = sd[(sd.day < T) & (sd.day >= T - ID_LOOKBACK)]
    sanc_before = set(first_sanc[first_sanc < T].index)
    w["sanctioned_before_T"] = w.imo.isin(sanc_before)

    # flag risk: share of tankers flying each flag in the window already sanctioned before T
    # (smoothed toward the window mean; uses only sanctions dated before T)
    f = w.drop_duplicates("imo", keep="last").groupby("flag")["sanctioned_before_T"].agg(["sum", "count"])
    prior, m = w.drop_duplicates("imo")["sanctioned_before_T"].mean(), 10.0
    flag_risk = (f["sum"] + m * prior) / (f["count"] + m)

    pop = w[~w.sanctioned_before_T].copy()
    # laden ratio: that day's draught vs the ship's max draught in the window
    pop["laden"] = pop["draught_max"] >= config.LADEN_RATIO * pop.groupby("imo")["draught_max"].transform("max")
    pop["west_day"] = pop["n_west_cross"].fillna(0) > 0
    pop["east_day"] = pop["n_east_cross"].fillna(0) > 0
    g = pop.sort_values("day").groupby("imo")
    n_days = g["day"].nunique()
    west, east = g["west_day"].sum(), g["east_day"].sum()
    g12 = w12[w12.imo.isin(n_days.index)].groupby("imo")
    feat = pd.DataFrame({
        "days_seen": n_days,
        "days_since_last_seen": (T - g["day"].max()).dt.days,
        "imo_number": pd.to_numeric(n_days.index.to_series(), errors="coerce"),
        "length": g["length"].max(),
        "width": g["width"].max(),
        "draught_max": g["draught_max"].max(),
        "n_mmsi_12m": g12["mmsi"].nunique(),
        "n_names_12m": g12["name"].nunique(),
        "n_flags_12m": g12["flag"].nunique(),
        "dest_russian_frac": g["dest_russian"].mean(),
        "dest_notable_frac": g["dest_notable"].mean(),
        "dest_missing_frac": g["dest_missing"].mean(),
        "west_laden_frac": (pop[pop.west_day].groupby("imo")["laden"].sum() / west.where(west > 0)),
        "east_laden_frac": (pop[pop.east_day].groupby("imo")["laden"].sum() / east.where(east > 0)),
        "baltic_side_frac": (pop["mean_lon"] > config.BALTIC_SIDE_LON).groupby(pop["imo"]).mean(),
        "cross_per_day": (g["n_east_cross"].sum() + g["n_west_cross"].sum()) / n_days,
        "gaps_core_per_day": g["n_gaps_core"].sum() / n_days,
        "max_gap_h": g["max_gap_h"].max(),
        "slow_underway_h_per_day": g["slow_hours_underway"].sum() / n_days,
        "anchor_h_per_day": g["anchor_hours"].sum() / n_days,
        "spoof_per_day": g["n_spoof_jumps"].sum() / n_days,
        "flag_last": g["flag"].last(),
        "name_last": g["name"].last(),
        "mmsi_last": g["mmsi"].last(),
        "last_seen": g["day"].max(),
    })
    feat["flag_risk"] = feat["flag_last"].map(flag_risk).fillna(prior)
    feat["flag_is_russia"] = feat["flag_last"].eq("Russia").astype(int)

    def pair_feats(p, name_count, name_sanc):
        p = p[(p.day < T) & (p.day >= T - LOOKBACK)]
        p = p.assign(partner_sanctioned=p.partner.isin(sanc_before))
        pg = p.groupby("imo")
        if name_count:
            feat[name_count] = pg.size().reindex(feat.index).fillna(0)
        feat[name_sanc] = p[p.partner_sanctioned].groupby("imo")["partner"].nunique().reindex(feat.index).fillna(0)

    pair_feats(pairs["sts"], "sts_count", "sts_with_sanctioned")
    pair_feats(pairs["near"], None, "near_sanctioned")

    fs = first_sanc.reindex(feat.index)
    feat["sanctioned_on"] = fs
    feat["label"] = ((fs >= T) & (fs < min(T + pd.Timedelta(days=config.LABEL_HORIZON_DAYS), label_end))).astype(int)
    feat["T"] = T
    feat.index.name = "imo"
    return feat.reset_index()


def snapshot_dates() -> list[pd.Timestamp]:
    first_ais = pd.Timestamp(config.AIS_SAMPLE_START)
    return list(pd.date_range(first_ais + LOOKBACK, "2026-10-01", freq="MS"))


def build() -> pd.DataFrame:
    sd = load_shipdays()
    pairs = load_pairs(sd)
    first_sanc = sanction_dates()
    cutoff = pd.Timestamp(config.TRAIN_CUTOFF)
    data_date = pd.Timestamp("2026-10-16")  # lists retrieved 2026-10-16: nothing later is knowable
    rows = []
    for T in snapshot_dates():
        label_end = cutoff if T < cutoff else data_date
        f = snapshot(T, sd, pairs, first_sanc, label_end)
        if len(f):
            f["split"] = "train" if T < cutoff else "test"
            # label is complete only if the full horizon has passed before label_end
            f["label_complete"] = (T + pd.Timedelta(days=config.LABEL_HORIZON_DAYS)) <= label_end
            rows.append(f)
    return pd.concat(rows, ignore_index=True)


def main():
    df = build()
    df.to_parquet(PROCESSED / "features.parquet", index=False)
    summ = df.groupby("T").agg(ships=("imo", "size"), positives=("label", "sum"), split=("split", "first"),
                               days_seen_median=("days_seen", "median"))
    print(summ.to_string())
    n_days = len(list((AIS / "shipday").glob("*.parquet")))
    write_manifest(PROCESSED / "features.manifest.json",
                   inputs=["data/interim/ais_v2/shipday", "data/interim/ais_v2/sts", "data/interim/ais_v2/near",
                           "data/interim/labels.parquet", "data/interim/mid_flags.parquet"],
                   outputs={"rows": len(df), "ais_days_used": n_days, "features": FEATURES,
                            "per_snapshot": {str(k.date()): {"ships": int(v.ships), "positives": int(v.positives)}
                                             for k, v in summ.iterrows()}},
                   notes=f"lookback={LOOKBACK.days}d identity={ID_LOOKBACK.days}d horizon={config.LABEL_HORIZON_DAYS}d cutoff={config.TRAIN_CUTOFF}")


if __name__ == "__main__":
    main()
