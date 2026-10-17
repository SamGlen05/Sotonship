"""Stage 2: preliminary exploration. Writes charts to reports/ and the numbers
behind every statement to reports/explore_numbers.json.

Questions (docs/PIPELINE.md, Stage 2): timing, cross-list lead/lag, coverage,
contrast, data quality. Lead time and leakage need Stage 3 snapshots; only the
leakage *risks* visible from the raw tables are reported here.
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sfp import config  # noqa: E402
from sfp.manifest import write_manifest  # noqa: E402
from sfp.paths import INTERIM, REPORTS  # noqa: E402

# Reference palette (dataviz skill, light mode), slots 1-3 only.
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
SURF, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
    "font.family": "sans-serif", "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False,
})

NUM: dict = {}
SRC = ("Sources: UK Sanctions List (report 16-Oct-2026); EU designated vessels (DMA, 24-07-2026); "
       "OFAC SDN advanced XML (issue 2026-10-15). Retrieved 2026-10-16.")


def foot(fig, text=SRC):
    fig.text(0.01, 0.005, text, fontsize=7, color=MUTED, ha="left", va="bottom")


# ---------------------------------------------------------------- 1. timing
def timing(l: pd.DataFrame):
    cols = [("UK (Russia regime)", "uk_designated_on"), ("EU (Reg. 833/2014 Art. 3s)", "eu_listed_on"),
            ("US OFAC (RUSSIA-EO14024)", "us_designated_on")]
    months = pd.period_range("2022-01", "2026-10", freq="M")
    fig, axes = plt.subplots(3, 1, figsize=(10, 6.2), sharex=True, sharey=True)
    for ax, (title, c) in zip(axes, cols):
        s = l[c].dropna().dt.to_period("M").value_counts().reindex(months, fill_value=0)
        x = months.to_timestamp()
        ax.bar(x, s.values, width=24, color=C1, edgecolor=SURF, linewidth=0.5)
        ax.set_title(f"{title}: {int(s.sum())} vessels since Jan 2022", fontsize=10)
        ax.axvline(pd.Timestamp(config.TRAIN_CUTOFF), color=INK2, lw=1)
        for k in (s.sort_values().index[-2:]):
            ax.annotate(int(s[k]), (k.to_timestamp(), s[k]), xytext=(0, 2), textcoords="offset points",
                        ha="center", fontsize=8, color=INK2)
        NUM.setdefault("timing", {})[c] = {str(k): int(v) for k, v in s[s > 0].items()}
    axes[0].text(pd.Timestamp(config.TRAIN_CUTOFF), axes[0].get_ylim()[1] * 0.9, " training cut-off 2026-05-01",
                 fontsize=8, color=INK2)
    axes[-1].set_ylabel("vessels designated per month")
    fig.suptitle("Vessel designations come in large, irregular batches", x=0.01, ha="left", fontweight="bold")
    foot(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(REPORTS / "01_designation_timing.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 2. cross-list
def cross_list(l: pd.DataFrame):
    uk = l.dropna(subset=["uk_designated_on"]).copy()
    prior = uk[["eu_listed_on", "us_designated_on"]].min(axis=1)
    uk["listed_elsewhere_first"] = prior < uk["uk_designated_on"]
    g = (uk.groupby("uk_batch")
         .agg(n=("imo", "size"), prior=("listed_elsewhere_first", "sum")).query("n >= 5"))
    g["uk_first"] = g["n"] - g["prior"]
    NUM["uk_batches_listed_elsewhere_first"] = {str(k.date()): {"n": int(r.n), "listed_elsewhere_first": int(r.prior)}
                                               for k, r in g.iterrows()}
    lag = (uk["uk_designated_on"] - prior).dt.days
    NUM["uk_lag_days_when_following"] = lag[lag > 0].describe().round(1).to_dict()
    NUM["uk_counts"] = {"followed_eu_or_us": int((lag > 0).sum()), "uk_first": int((lag < 0).sum()),
                        "same_day": int((lag == 0).sum()), "uk_only": int(lag.isna().sum())}

    fig, ax = plt.subplots(figsize=(10, 4.2))
    lab = [d.strftime("%Y-%m-%d") for d in g.index]
    x = np.arange(len(g))
    ax.bar(x, g["prior"], color=C1, width=0.7, label="already on EU or US list", edgecolor=SURF, linewidth=1)
    ax.bar(x, g["uk_first"], bottom=g["prior"], color=C2, width=0.7, label="UK first or UK only",
           edgecolor=SURF, linewidth=1)
    ax.set_xticks(x, lab, rotation=55, ha="right", fontsize=8)
    for i, d in enumerate(g.index):
        if d.strftime("%Y-%m-%d") in config.TEST_BATCHES_UK:
            ax.annotate(f"test batch: {int(g.prior.iloc[i])} of {int(g.n.iloc[i])}\nlisted elsewhere first",
                        (i, g.n.iloc[i]), xytext=(0, 38), textcoords="offset points", ha="center", fontsize=8,
                        color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.set_ylabel("ships in UK batch")
    ax.set_xlabel("UK designation batch (dates within 2 days grouped)", color=MUTED, fontsize=8)
    ax.legend(loc="upper left")
    ax.set_title("Most recent UK ship batches follow an earlier EU listing")
    foot(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(REPORTS / "02_uk_batches_cross_list.png", dpi=150)
    plt.close(fig)


def follow_the_leader_baseline(l: pd.DataFrame):
    """Baseline a sceptical judge will propose: rank not-yet-UK ships by how
    recently another regime listed them. Uses only list dates before T."""
    out = {}
    for T, batch in [("2026-06-01", ["2026-06-16"]), ("2026-09-01", ["2026-10-01", "2026-10-02"])]:
        T = pd.Timestamp(T)
        cand = l[~(l.uk_designated_on < T)]
        d = cand[["eu_listed_on", "us_designated_on"]].where(cand[["eu_listed_on", "us_designated_on"]] < T)
        cand = cand.assign(last_foreign=d.max(axis=1)).dropna(subset=["last_foreign"])
        cand = cand.sort_values("last_foreign", ascending=False).reset_index(drop=True)
        pos = set(l.imo[l.uk_designated_on.isin(pd.to_datetime(batch))])
        out[f"T={T.date()} batch={'+'.join(batch)}"] = {
            "batch_size": len(pos), "pool_size": len(cand),
            "in_pool": int(cand.imo.isin(pos).sum()),
            **{f"hits@{k}": int(cand.head(k).imo.isin(pos).sum()) for k in (25, 50, 100)}}
    NUM["baseline_follow_the_leader"] = out


# ---------------------------------------------------------------- 3. coverage + 4. contrast
def ais_status(l: pd.DataFrame, days: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Status of each tanker on each AIS sample day, using list dates only."""
    t = days[days.ship_type.eq("Tanker")].merge(l, on="imo", how="left").merge(
        master[["imo", "build_year", "build_year_source", "n_mmsi", "flag_from_mmsi"]], on="imo", how="left")
    t["day"] = pd.to_datetime(t["day"])
    d = t["first_designated_on"]
    t["status"] = np.select([d <= t["day"], d > t["day"]], ["already designated", "designated later"],
                            default="not designated (as of 2026-10-16)")
    t["mmsi_flag"] = t["mmsi"].str[:3].map(pd.read_parquet(INTERIM / "mid_flags.parquet")
                                          .set_index("mid")["flag_from_mmsi"])
    t["foc"] = t["mmsi_flag"].isin(config.FLAGS_OF_CONVENIENCE)
    return t


def coverage(l: pd.DataFrame, t: pd.DataFrame, n_days: int, day_range: tuple):
    seen_before = {}
    for b in [["2026-02-24"], ["2026-06-16"], ["2026-10-01"], ["2026-10-08"]]:
        pos = l[l.uk_batch.isin(pd.to_datetime(b))]
        d0 = pd.Timestamp(b[0])
        seen = t[(t.day < d0) & t.imo.isin(pos.imo)].imo.nunique()
        seen_any = t[t.imo.isin(pos.imo)].imo.nunique()
        seen_before["+".join(b)] = {"batch_size": len(pos), "seen_before_designation": int(seen),
                                    "seen_any_sample_day": int(seen_any)}
    NUM["coverage_uk_batches_in_danish_ais_sample"] = seen_before
    NUM["ais_sample"] = {"n_days": n_days, "first_day": day_range[0], "last_day": day_range[1],
                         "tanker_imos": int(t.imo.nunique()), "tanker_days": len(t),
                         "tanker_imos_per_day_median": float(t.groupby("day").imo.nunique().median())}

    fig, ax = plt.subplots(figsize=(8, 3.4))
    keys = list(seen_before)
    y = np.arange(len(keys))
    n = np.array([seen_before[k]["batch_size"] for k in keys])
    s = np.array([seen_before[k]["seen_before_designation"] for k in keys])
    ax.barh(y, n, color=GRID, height=0.6, label="ships in UK batch")
    ax.barh(y, s, color=C1, height=0.6, label="seen in Danish AIS sample before designation")
    for i in range(len(keys)):
        ax.text(n[i] + 0.6, i, f"{s[i]} of {n[i]}", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, [f"UK {k}" for k in keys])
    ax.invert_yaxis()
    ax.set_xlabel("ships")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title(f"Coverage: {n_days} sampled days of Danish AIS see only part of each batch")
    foot(fig, f"DMA historical AIS, {n_days} days sampled {day_range[0]} to {day_range[1]}; UK Sanctions List 16-Oct-2026.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(REPORTS / "03_coverage_uk_batches.png", dpi=150)
    plt.close(fig)


def contrast(t: pd.DataFrame):
    # one row per IMO: status at its first sample day (avoid counting the same ship twice)
    v = t.sort_values("day").groupby("imo").agg(
        status=("status", "first"), build_year=("build_year", "first"),
        build_year_source=("build_year_source", "first"), foc=("foc", "first"),
        mmsi_flag=("mmsi_flag", "first"), dest_russian=("dest_russian", "max"),
        dest_notable=("dest_notable", "max"), n_mmsi=("n_mmsi", "first"),
        spoof=("n_spoof_jumps", "max"), gaps=("n_gaps_intraday", "max"),
        crossed=("crossed_straits", "max"), days_seen=("day", "nunique"))
    order = ["already designated", "designated later", "not designated (as of 2026-10-16)"]
    rows = {}
    for s in order:
        g = v[v.status == s]
        rows[s] = {
            "ships": len(g),
            "build_year_known_%": round(100 * g.build_year.notna().mean(), 1),
            "median_build_year": float(g.build_year.median()) if g.build_year.notna().any() else None,
            "flag_of_convenience_%": round(100 * g.foc.mean(), 1),
            "russian_port_destination_%": round(100 * g.dest_russian.astype(bool).mean(), 1),
            "notable_destination_%": round(100 * g.dest_notable.astype(bool).mean(), 1),
            "more_than_one_mmsi_%": round(100 * (g.n_mmsi > 1).mean(), 1),
            "spoof_jump_any_%": round(100 * (g.spoof > 0).mean(), 1),
            "intraday_gap_any_%": round(100 * (g.gaps > 0).mean(), 1),
            "top_flags": g.mmsi_flag.value_counts().head(5).to_dict(),
        }
    NUM["contrast_tankers_by_status_at_first_sample_day"] = rows

    metrics = [("russian_port_destination_%", "Destination:\nRussian port"),
               ("flag_of_convenience_%", "ITF flag of convenience\n(from MMSI)"),
               ("notable_destination_%", "Destination:\n'FOR ORDERS' and similar"),
               ("build_year_known_%", "Build year known\n(data-quality check)")]
    fig, axes = plt.subplots(1, len(metrics), figsize=(12, 3.6), sharey=True)
    cols = [C1, C2, C3]
    short = ["already designated", "designated later", "not designated"]
    for ax, (m, title) in zip(axes, metrics):
        vals = [rows[s][m] for s in order]
        ax.barh(range(3), vals, color=cols, height=0.65, edgecolor=SURF, linewidth=1)
        for i, val in enumerate(vals):
            ax.text(val + 1, i, f"{val:.0f}%", va="center", fontsize=9)
        ax.set_xlim(0, 115)
        ax.set_title(title, fontsize=9.5)
        ax.set_xticks([0, 50, 100])
    axes[0].set_yticks(range(3), [f"{s}\n(n={rows[o]['ships']})" for s, o in zip(short, order)])
    axes[0].invert_yaxis()
    fig.suptitle("Tankers seen in Danish AIS, by sanctions status on the day seen", x=0.01, ha="left",
                 fontweight="bold")
    foot(fig, "DMA historical AIS (sampled days) linked on IMO to UK/EU/OFAC lists. Status uses list dates only. "
              "Flag-of-convenience list: ITF (assumption).")
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(REPORTS / "04_contrast_by_status.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 5. data quality / leakage risks
def quality(l, master, days):
    eu = pd.read_parquet(INTERIM / "eu_vessels.parquet")
    uk = pd.read_parquet(INTERIM / "uk_vessels.parquet")
    links = pd.read_parquet(INTERIM / "mmsi_imo.parquet")
    NUM["quality"] = {
        "uk_ships": len(uk), "uk_ships_missing_valid_imo": int(uk.imo.isna().sum()),
        "eu_rows": len(eu), "eu_duplicate_imo_rows": int(eu.imo.duplicated().sum()),
        "imos_with_multiple_mmsi_in_sample": int((links.groupby("imo").mmsi.nunique() > 1).sum()),
        "mmsis_with_multiple_imo_in_sample": int((links.groupby("mmsi").imo.nunique() > 1).sum()),
        "ais_static_tanker_rows_without_imo_%": None,
        "master_build_year_known_designated_%": round(100 * master[master.imo.isin(l.imo)].build_year.notna().mean(), 1),
        "master_build_year_known_ais_only_%": round(100 * master[master.sources.eq("DMA_AIS")].build_year.notna().mean(), 1),
    }


def main():
    l = pd.read_parquet(INTERIM / "labels.parquet")
    master = pd.read_parquet(INTERIM / "vessel_master.parquet")
    days = pd.read_parquet(INTERIM / "ais_days.parquet")
    n_days = days.day.nunique()
    rng = (str(pd.to_datetime(days.day).min().date()), str(pd.to_datetime(days.day).max().date()))
    timing(l)
    cross_list(l)
    follow_the_leader_baseline(l)
    t = ais_status(l, days, master)
    coverage(l, t, n_days, rng)
    contrast(t)
    quality(l, master, days)
    (REPORTS / "explore_numbers.json").write_text(json.dumps(NUM, indent=2, default=str))
    write_manifest(REPORTS / "explore.manifest.json", inputs=[], outputs={"charts": 4},
                   notes="Inputs: data/interim/{labels,vessel_master,ais_days,mid_flags}.parquet")
    print(json.dumps(NUM, indent=1, default=str))


if __name__ == "__main__":
    main()
