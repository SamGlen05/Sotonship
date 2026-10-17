"""Stage 4: train on snapshots before TRAIN_CUTOFF, backtest on later snapshots.

Rankers (simplest first):
  random        : random order (floor)
  flag_rule     : flag_risk only (the 'flag of convenience' rule a sceptic proposes;
                  AIS carries no build year, so the age half is unavailable)
  rule_score    : hand-weighted 0-100 score (RULE_WEIGHTS; set before seeing test data)
  logreg        : standardised logistic regression
  lightgbm      : gradient boosting, explained with SHAP

Outputs (data/processed/):
  backtest.json            metrics per model per test snapshot (+ UK test batches)
  model_lgbm.txt, model_meta.json
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from sfp import config
from sfp import features as _dma
from sfp import global_features as _glob

FEATURES, MONOTONE = _dma.FEATURES, _dma.MONOTONE
SET, SUFFIX, FEATURE_FILE = "dma", "", "features.parquet"
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, PROCESSED

# ASSUMPTION: hand-set rule weights (each signal scaled to 0-1 first). Set from
# domain priors, not tuned on any test batch.
RULE_WEIGHTS = {
    "dest_russian_frac": 25,      # announced voyages to Russian export ports
    "flag_risk": 20,              # flag already common among sanctioned tankers
    "sts_with_sanctioned": 10,    # met an already-sanctioned tanker at sea
    "near_sanctioned": 10,        # lingered next to already-sanctioned tankers
    "west_laden_frac": 10,        # left the Baltic loaded
    "gaps_core_per_day": 8,       # went silent while inside receiver coverage
    "n_flags_12m": 7,             # re-flagging seen in AIS
    "dest_notable_frac": 5,       # 'FOR ORDERS'-style destinations
    "spoof_per_day": 5,           # implausible position jumps
}
RULE_WEIGHTS_GLOBAL = {
    "ports_sanctioned_trade": 25,     # port calls in Russia, Iran, Venezuela, Syria, North Korea
    "share_port_days_sanctioned": 10, # share of port time spent there
    "loiter_with_sanctioned": 15,     # loitered next to an already-sanctioned tanker
    "flag_risk": 15,                  # flag already common among sanctioned tankers
    "n_gaps_intentional": 10,         # AIS switched off (GFW: likely intentional)
    "loiter_hotspot_hours": 10,       # loitering in reported transfer areas
    "n_flags_12m": 10,                # re-flagging
    "dma_dest_russian_frac": 5,       # Danish AIS: announced a Russian port
}
_RULE_DMA = None


def use_set(name: str):
    """Switch every function in this module to the 'dma' or 'global' feature set."""
    global FEATURES, MONOTONE, RULE_WEIGHTS, SET, SUFFIX, FEATURE_FILE, _RULE_DMA
    _RULE_DMA = _RULE_DMA or RULE_WEIGHTS
    if name == "global":
        FEATURES, MONOTONE, RULE_WEIGHTS = _glob.FEATURES, _glob.MONOTONE, RULE_WEIGHTS_GLOBAL
        SET, SUFFIX, FEATURE_FILE = "global", "_global", "features_global.parquet"
    else:
        FEATURES, MONOTONE, RULE_WEIGHTS = _dma.FEATURES, _dma.MONOTONE, _RULE_DMA
        SET, SUFFIX, FEATURE_FILE = "dma", "", "features.parquet"


LGB_PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=20,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                  n_estimators=400, verbose=-1, random_state=0)
KS = (25, 50, 100)


def rule_score(df: pd.DataFrame, ref: pd.DataFrame) -> pd.Series:
    """0-100. Each signal is clipped at its 99th percentile in the TRAINING data."""
    s = 0
    for f, w in RULE_WEIGHTS.items():
        hi = ref[f].quantile(0.99) or 1.0
        v = df[f].fillna(0)
        x = (v.clip(lower=0) / hi).clip(upper=1)
        if f in ("n_flags_12m", "n_names_12m", "n_mmsi_12m"):  # 1 = no change
            x = ((v - 1).clip(lower=0) / max(hi - 1, 1)).clip(upper=1)
        s = s + w * x
    return 100 * s / sum(RULE_WEIGHTS.values())


GRID = [dict(num_leaves=nl, min_child_samples=mc, monotone=mo)
        for nl in (7, 15) for mc in (20, 60) for mo in (True, False)]
LR_C = (0.03, 0.3, 3.0)


def lr_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Logistic regression inputs: fill gaps, compress heavy tails."""
    X = df[FEATURES].astype(float).fillna(0).copy()
    for c in X:
        if c not in ("imo_number", "built_year", "flag_risk", "flag_is_russia", "registry_verified") \
                and not c.endswith("_frac") and not c.startswith("share_"):
            X[c] = np.log1p(X[c].clip(lower=0))
    X["imo_number"] = (X["imo_number"] - 9_000_000) / 1e6
    return X


def make_gbm(params: dict, y: pd.Series) -> lgb.LGBMClassifier:
    p = {**LGB_PARAMS, "num_leaves": params["num_leaves"], "min_child_samples": params["min_child_samples"]}
    if params.get("monotone"):
        p["monotone_constraints"] = [MONOTONE.get(f, 0) for f in FEATURES]
        p["monotone_constraints_method"] = "advanced"
    pos = y.sum()
    return lgb.LGBMClassifier(**p, scale_pos_weight=max((len(y) - pos) / max(pos, 1), 1) ** 0.5)


def select(train: pd.DataFrame) -> dict:
    """Choose settings on a time-based validation split INSIDE the training period:
    validate on the last 3 training snapshots whose labels are complete before the
    cut-off; fit on snapshots at least one label horizon (90 days) earlier."""
    cutoff = pd.Timestamp(config.TRAIN_CUTOFF)
    hz = pd.Timedelta(days=config.LABEL_HORIZON_DAYS)
    Ts = sorted(t for t in train["T"].unique() if t + hz <= cutoff)
    val_T = Ts[-3:]
    inner = train[train["T"] <= (val_T[0] - hz)] if val_T else train.iloc[:0]
    val = train[train["T"].isin(val_T)]
    log = {"val_snapshots": [str(t.date()) for t in val_T], "inner_rows": len(inner),
           "inner_positives": int(inner.label.sum()), "val_positives": int(val.label.sum()), "candidates": []}
    default = {"gbm": dict(num_leaves=15, min_child_samples=20, monotone=True), "lr_C": 0.3}
    if inner.label.sum() < 10 or val.label.sum() < 5:
        log["chosen"] = default
        log["note"] = "too few positives for validation; defaults used"
        return log

    def ap(scores):
        v = val.assign(s=scores)
        return float(np.mean([average_precision_score(g.label, g.s) for _, g in v.groupby("T") if g.label.any()]))

    best = None
    for params in GRID:
        m = make_gbm(params, inner.label).fit(inner[FEATURES], inner.label)
        a = ap(m.predict_proba(val[FEATURES])[:, 1])
        log["candidates"].append({**params, "val_pr_auc": round(a, 4)})
        if best is None or a > best[0]:
            best = (a, params)
    best_lr = None
    for C in LR_C:
        lr = make_pipeline(StandardScaler(), LogisticRegression(C=C, class_weight="balanced", max_iter=3000))
        lr.fit(lr_matrix(inner), inner.label)
        a = ap(lr.predict_proba(lr_matrix(val))[:, 1])
        log["candidates"].append({"logreg_C": C, "val_pr_auc": round(a, 4)})
        if best_lr is None or a > best_lr[0]:
            best_lr = (a, C)
    log["chosen"] = {"gbm": best[1], "lr_C": best_lr[1]}
    return log


def fit(train: pd.DataFrame, chosen: dict):
    y = train["label"]
    lr = make_pipeline(StandardScaler(), LogisticRegression(C=chosen["lr_C"], class_weight="balanced", max_iter=3000))
    lr.fit(lr_matrix(train), y)
    gbm = make_gbm(chosen["gbm"], y).fit(train[FEATURES], y)
    return lr, gbm


def score_all(df: pd.DataFrame, train: pd.DataFrame, lr, gbm) -> pd.DataFrame:
    out = df[["imo", "T", "label"]].copy()
    rng = np.random.default_rng(0)
    out["random"] = rng.random(len(df))
    out["flag_rule"] = df["flag_risk"].values
    out["rule_score"] = rule_score(df, train).values
    out["logreg"] = lr.predict_proba(lr_matrix(df))[:, 1]
    out["lightgbm"] = gbm.predict_proba(df[FEATURES])[:, 1]
    return out


MODELS = ["random", "flag_rule", "rule_score", "logreg", "lightgbm"]


def metrics(snap: pd.DataFrame, positives: set | None = None) -> dict:
    """Ranking metrics for one snapshot. positives defaults to the snapshot labels."""
    pos = positives if positives is not None else set(snap.imo[snap.label == 1])
    res = {"population": len(snap), "positives_in_population": int(snap.imo.isin(pos).sum())}
    for m in MODELS:
        r = snap.sort_values(m, ascending=False)
        y = r.imo.isin(pos).values
        res[m] = {f"hits@{k}": int(y[:k].sum()) for k in KS}
        res[m]["pr_auc"] = round(float(average_precision_score(y, r[m])), 4) if y.any() else None
    return res


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["dma", "global"], default="dma")
    use_set(ap.parse_args().set)
    df = pd.read_parquet(PROCESSED / FEATURE_FILE)
    train = df[df.split == "train"]
    test = df[df.split == "test"]
    sel = select(train)
    lr, gbm = fit(train, sel["chosen"])
    scored = score_all(df, train, lr, gbm)
    scored.to_parquet(PROCESSED / f"scores_all_snapshots{SUFFIX}.parquet", index=False)

    lab = pd.read_parquet(INTERIM / "labels.parquet")
    out = {"train": {"snapshots": sorted(str(t.date()) for t in train["T"].unique()),
                     "rows": len(train), "positives": int(train.label.sum())},
           "test_snapshots": {}, "uk_test_batches": {}}
    for T, snap in scored[scored["T"].isin(test["T"].unique())].groupby("T"):
        out["test_snapshots"][str(T.date())] = metrics(snap)
    # headline: UK batches, at the last snapshot before designation
    for batch, T in (("2026-06-16", "2026-06-01"), ("2026-10-01", "2026-09-01")):
        snap = scored[scored["T"] == pd.Timestamp(T)]
        ships = set(lab.imo[lab.uk_batch == pd.Timestamp(batch)])
        if len(snap):
            m = metrics(snap, ships)
            m["batch_size"] = len(ships)
            out["uk_test_batches"][f"{batch} (snapshot {T})"] = m
    (PROCESSED / f"backtest{SUFFIX}.json").write_text(json.dumps(out, indent=2))

    gbm.booster_.save_model(str(PROCESSED / f"model_lgbm{SUFFIX}.txt"))
    imp = dict(zip(FEATURES, gbm.booster_.feature_importance("gain").round(1).tolist()))
    coef = dict(zip(FEATURES, lr[-1].coef_[0].round(3).tolist()))
    (PROCESSED / f"model_meta{SUFFIX}.json").write_text(json.dumps(
        {"features": FEATURES, "rule_weights": RULE_WEIGHTS, "lgb_params": LGB_PARAMS, "selection": sel,
         "lgbm_gain": imp, "logreg_coef": coef, "train_cutoff": config.TRAIN_CUTOFF, "feature_set": SET}, indent=2))
    write_manifest(PROCESSED / f"backtest{SUFFIX}.manifest.json", inputs=[f"data/processed/{FEATURE_FILE}"],
                   outputs={"train_rows": len(train), "test_rows": len(test)},
                   notes="trained only on snapshots before TRAIN_CUTOFF")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
