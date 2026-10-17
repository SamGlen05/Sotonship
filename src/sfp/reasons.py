"""Plain-language reasons for a ship's score.

Every reason = the ship's own observed value (with dates) + a comparison computed
from the same snapshot's AIS population (as of T) + links to dated evidence.
Only signals that RAISE the score (positive SHAP contribution) become reasons;
context features (how often we saw the ship) never do.
"""
import numpy as np
import pandas as pd

from sfp import config
from sfp.features import CONTEXT

def est_build_year(imo) -> int | None:
    try:
        n = int(imo)
    except (TypeError, ValueError):
        return None
    xs, ys = zip(*config.IMO_BUILD_YEAR)
    if n < xs[0]:
        return None
    return int(round(np.interp(n, [x + 50_000 for x in xs], ys)))


def size_class_name(length):
    if length is None or not np.isfinite(length):
        return None
    return next(name for mx, name, *_ in config.SIZE_CLASSES if length <= mx)


class Context:
    """Population comparisons as of snapshot T (AIS window + sanctions dated before T)."""

    def __init__(self, win: pd.DataFrame, first_sanc: pd.Series, T: pd.Timestamp):
        last = win.sort_values("day").groupby("imo").tail(1).copy()
        last["sanc"] = last.imo.isin(first_sanc[first_sanc < T].index)
        last["size"] = last["length"].map(size_class_name)
        last["year"] = last["imo"].map(est_build_year)
        self.T = T
        self.n_sanc, self.n_other = int(last.sanc.sum()), int((~last.sanc).sum())
        self.size_share = last.groupby("sanc")["size"].value_counts(normalize=True)
        self.year_median = last.groupby("sanc")["year"].median()
        fl = last.groupby("flag")["sanc"].agg(["sum", "count"])
        self.flag = fl
        self.share_other = lambda col: float(win[~win.imo.isin(last.imo[last.sanc])].groupby("imo")[col].mean().gt(0).mean())

    def pct(self, x):
        return f"{100 * x:.0f}%"


def _ev(evidence, types, n=3):
    return [e for e in evidence if e["type"] in types][:n]


def build(row, contrib: dict, w: pd.DataFrame, evidence: list, ctx: Context) -> list[dict]:
    """row: the ship's feature row; w: its AIS ship-days in the window (sorted by day)."""
    out = []
    row = {k: (0.0 if (v is None or (isinstance(v, float) and not np.isfinite(v))) and k not in ("flag_last", "imo") else v)
           for k, v in row.items()}
    n = int(row["days_seen"])
    dates = lambda mask: ", ".join(str(d.date()) for d in w.loc[mask, "day"][-3:])  # noqa: E731
    for f, c in sorted(contrib.items(), key=lambda kv: -kv[1]):
        if c <= 0 or f in CONTEXT:
            continue
        v = row.get(f)
        v = 0.0 if v is None or (isinstance(v, float) and not np.isfinite(v)) else v
        r = None
        if f == "imo_number":
            y = est_build_year(row["imo"])
            if y:
                ys, yo = ctx.year_median.get(True), ctx.year_median.get(False)
                r = ("Older tonnage", f"IMO {row['imo']} suggests a build year around {y}. Already-sanctioned tankers seen in "
                     f"these waters have a median estimated build year of {ys:.0f}, against {yo:.0f} for the others.", [])
        elif f in ("length", "draught_max"):
            sc = size_class_name(row["length"])
            if sc:
                a = ctx.size_share.get((True, sc), 0.0)
                b = ctx.size_share.get((False, sc), 0.0)
                r = (f"{sc} size", f"{row['length']:.0f} m long, {row['width']:.0f} m beam. {ctx.pct(a)} of the "
                     f"{ctx.n_sanc} already-sanctioned tankers seen in these waters are this size class, against "
                     f"{ctx.pct(b)} of the other {ctx.n_other}.", [])
        elif f in ("flag_risk", "flag_is_russia"):
            fl = row["flag_last"]
            s, k = (ctx.flag.loc[fl] if fl in ctx.flag.index else (0, 0))
            r = (f"Flag: {fl}", f"Flag {fl} (from its MMSI). {int(s)} of {int(k)} tankers seen under this flag in the "
                 f"last 180 days were already sanctioned before {ctx.T.date()}.", [])
        elif f in ("n_names_12m", "n_flags_12m") and v > 1:
            col = {"n_mmsi_12m": "mmsi", "n_names_12m": "name", "n_flags_12m": "flag"}[f]
            what = {"n_mmsi_12m": "MMSI numbers", "n_names_12m": "names", "n_flags_12m": "flags"}[f]
            r = ("Identity changes", f"Used {int(v)} different {what} in the last 12 months.", [])
        elif f == "dest_russian_frac" and v > 0:
            m = w.dest_russian.astype(bool)
            r = ("Russian port destination", f"Announced a Russian port as destination on {int(m.sum())} of {n} days seen "
                 f"({dates(m)}). {ctx.pct(ctx.share_other('dest_russian'))} of unsanctioned tankers did so at all.",
                 _ev(evidence, {"Russian port destination"}))
        elif f == "dest_notable_frac" and v > 0:
            m = w.dest_notable.astype(bool)
            r = ("Vague destination", f"Broadcast 'FOR ORDERS'-style destinations on {int(m.sum())} of {n} days seen ({dates(m)}).",
                 _ev(evidence, {"Vague destination"}))
        elif f == "dest_missing_frac" and v > 0:
            r = ("Blank destination", f"Left the AIS destination blank on {int(round(v * n))} of {n} days seen.", [])
        elif f == "west_laden_frac" and v > 0:
            r = ("Left the Baltic loaded", f"{v:.0%} of its westbound passages through the Danish straits were at 80% or more "
                 f"of its maximum observed draught, consistent with cargo loaded at a Baltic port.", [])
        elif f == "east_laden_frac" and v > 0:
            r = ("Entered the Baltic loaded", f"{v:.0%} of its eastbound passages were laden.", [])
        elif f == "baltic_side_frac" and v > 0:
            r = ("Baltic trading pattern", f"On the Baltic side of the straits on {v:.0%} of days seen.", [])
        elif f == "cross_per_day" and v > 0:
            r = ("Frequent straits passages", f"{v:.1f} passages through the Danish straits per day seen.", [])
        elif f == "gaps_core_per_day" and v > 0:
            m = w.n_gaps_core.fillna(0) > 0
            r = ("AIS gaps inside coverage", f"Went silent for 2 h or more while inside receiver coverage on {int(m.sum())} "
                 f"day(s) ({dates(m)}).", _ev(evidence, {"AIS gap in coverage"}))
        elif f == "spoof_per_day" and v > 0:
            m = w.n_spoof_jumps.fillna(0) > 0
            r = ("Implausible position jumps", f"Positions implied speeds above {config.SPOOF_SPEED_KN} kn on {dates(m)}.",
                 _ev(evidence, {"Position jump"}))
        elif f == "slow_underway_h_per_day" and v > 0:
            r = ("Drifting at sea", f"About {v:.1f} h per day seen moving under {config.LOITER_SPEED_KN} kn while not moored.", [])
        elif f == "anchor_h_per_day" and v > 0:
            r = ("Long periods at anchor", f"About {v:.1f} h per day seen at anchor.", [])
        elif f in ("sts_count", "sts_with_sanctioned") and row["sts_count"] > 0:
            k = int(row["sts_with_sanctioned"])
            r = ("Ship-to-ship meetings", f"{int(row['sts_count'])} meeting(s) with another tanker within "
                 f"{config.STS_DISTANCE_NM} nm for {config.STS_MIN_HOURS} h or more, outside ports"
                 + (f"; {k} with tankers already sanctioned at the time." if k else "."),
                 _ev(evidence, {"Ship-to-ship meeting"}))
        elif f == "near_sanctioned" and v > 0:
            r = ("Near sanctioned tankers", f"Lingered within {config.NEAR_DISTANCE_NM} nm of {int(v)} tanker(s) that were "
                 f"already sanctioned, for an hour or more.", _ev(evidence, {"Near sanctioned tanker"}))
        if r and not any(x["title"] == r[0] for x in out):
            out.append({"feature": f, "title": r[0], "text": r[1], "evidence": r[2], "contrib": round(float(c), 3)})
    return out
