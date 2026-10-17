"""Which datasets carry the signal? Cumulative ablation over dataset groups.

Each variant trains the same LightGBM on a growing set of feature groups. Decisions are
made on the VALIDATION split inside the training period (validate on the last 3 training
snapshots with complete labels, fit on snapshots at least one label horizon earlier).
Test months (after the 2026-05-01 cut-off, labels complete by 2026-10-16) are reported
for information only and never used to choose.

Writes data/processed/ablation.json and reports/07_dataset_ablation.png
"""
import json

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402

from sfp import config  # noqa: E402
from sfp import global_features as gf  # noqa: E402
from sfp.manifest import write_manifest  # noqa: E402
from sfp.model import LGB_PARAMS  # noqa: E402
from sfp.paths import PROCESSED, REPORTS  # noqa: E402

GROUPS = [
    ("Presence by sea area + IMO age (GFW)", gf.CONTEXT + list(gf.REGION_GROUPS) + ["imo_number"]),
    ("+ Identity history: flags, names, MMSIs (GFW)", ["n_flags_12m", "n_names_12m", "n_mmsi_12m",
                                                        "days_since_identity_change", "flag_risk"]),
    ("+ Port visits by country (GFW)", ["n_port_visits", "ports_sanctioned_trade", "ports_reroute_markets",
                                        "share_port_days_sanctioned"]),
    ("+ AIS gaps (GFW)", ["n_gaps", "n_gaps_intentional", "gap_hours", "gap_hours_max"]),
    ("+ Loitering incl. next to sanctioned tankers (GFW)", ["n_loiter", "loiter_hours", "loiter_hotspot_hours",
                                                            "loiter_with_sanctioned"]),
    ("+ Chokepoint passages incl. with AIS off (GFW port calls + gaps)", ["chokepoint_passages", "dark_passages",
                                                                         "hormuz_passages", "dark_hormuz_passages"]),
    ("+ Danish AIS behaviour (DMA)", [f for f in gf.FEATURES if f.startswith("dma_")]),
    ("+ Other authorities' lists and port-state detentions (OpenSanctions)", gf.OTHER_LISTS),
]


def fit(train, feats):
    pos = train.label.sum()
    m = lgb.LGBMClassifier(**{**LGB_PARAMS, "num_leaves": 15, "min_child_samples": 60},
                           scale_pos_weight=max((len(train) - pos) / max(pos, 1), 1) ** 0.5)
    return m.fit(train[feats], train.label)


def evaluate(m, df, feats):
    out = []
    for T, g in df.groupby("T"):
        if not g.label.any():
            continue
        p = m.predict_proba(g[feats])[:, 1]
        order = np.argsort(-p)
        y = g.label.values[order]
        out.append({"T": str(T.date()), "positives": int(g.label.sum()), "ap": float(average_precision_score(g.label, p)),
                    "base": float(g.label.mean()), "hits50": int(y[:50].sum()), "hits100": int(y[:100].sum())})
    return {"per_snapshot": out, "ap_mean": float(np.mean([o["ap"] for o in out])),
            "lift_mean": float(np.mean([o["ap"] / o["base"] for o in out])),
            "hits100_total": int(sum(o["hits100"] for o in out)), "positives_total": int(sum(o["positives"] for o in out))}


def main():
    df = pd.read_parquet(PROCESSED / "features_global.parquet")
    cutoff, hz = pd.Timestamp(config.TRAIN_CUTOFF), pd.Timedelta(days=config.LABEL_HORIZON_DAYS)
    train = df[df.split == "train"]
    Ts = sorted(t for t in train["T"].unique() if t + hz <= cutoff)
    val_T = Ts[-3:]
    inner = train[train["T"] <= val_T[0] - hz]
    val = train[train["T"].isin(val_T)]
    test = df[(df.split == "test") & df.label_complete]
    res, feats = [], []
    for name, g in GROUPS:
        feats = feats + [f for f in g if f in df]
        mv = fit(inner, feats)
        mt = fit(train, feats)
        r = {"variant": name, "n_features": len(feats), "validation": evaluate(mv, val, feats), "test": evaluate(mt, test, feats)}
        res.append(r)
        print(f"{name:72s} val AP {r['validation']['ap_mean']:.4f} (lift {r['validation']['lift_mean']:.1f}x)  "
              f"test AP {r['test']['ap_mean']:.4f} (lift {r['test']['lift_mean']:.1f}x) hits@100 {r['test']['hits100_total']}/{r['test']['positives_total']}",
              flush=True)
    meta = {"val_snapshots": [str(t.date()) for t in val_T], "inner_train_until": str((val_T[0] - hz).date()),
            "test_snapshots": sorted(str(t.date()) for t in test["T"].unique()), "variants": res}
    (PROCESSED / "ablation.json").write_text(json.dumps(meta, indent=2))

    fig, ax = plt.subplots(figsize=(10, 4.6))
    y = np.arange(len(res))
    ax.barh(y - 0.18, [r["validation"]["lift_mean"] for r in res], 0.34, color="#2a78d6", label="validation (inside training period)")
    ax.barh(y + 0.18, [r["test"]["lift_mean"] for r in res], 0.34, color="#eb6834", label="test (after 2026-05-01)")
    ax.set_yticks(y, [r["variant"] for r in res], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("PR-AUC as a multiple of random ranking (higher is better)")
    ax.set_title("What each dataset adds: cumulative ablation", loc="left", fontweight="bold")
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    ax.grid(axis="x", color="#e1e0d9")
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.01, "Global Fishing Watch API, DMA AIS, OpenSanctions (non-commercial); labels UK/EU/OFAC, retrieved 2026-10-16.",
             fontsize=7, color="#898781")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(REPORTS / "07_dataset_ablation.png", dpi=150, facecolor="#fcfcfb")
    write_manifest(PROCESSED / "ablation.manifest.json", inputs=["data/processed/features_global.parquet"],
                   outputs={"variants": len(res)}, notes="decisions on validation split only")


if __name__ == "__main__":
    main()
