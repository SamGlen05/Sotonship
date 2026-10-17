"""Automated leakage test for the global (GFW + Danish AIS) features.

For several snapshot dates T, rebuild features from inputs physically truncated to
before T (presence months, events ended, identity periods begun, Danish AIS rows,
sanctions) and assert they equal the pipeline's features. Exit code 1 on mismatch.
Static attributes (IMO number, registry build year/tonnage/type) are time-invariant
facts and are not truncated.
"""
import sys

import numpy as np
import pandas as pd

from sfp import config
from sfp import features as dma
from sfp import global_features as gf


def main():
    pres, ident, reg, ev, cand = gf.load()
    regstat = gf.registry_static(reg)
    first_sanc = dma.sanction_dates()
    sd = dma.load_shipdays()
    pairs = dma.load_pairs(sd)
    os_ev = pd.read_parquet(gf.INTERIM / "os_events.parquet").dropna(subset=["imo", "known_at"])
    Ts = gf.snapshot_dates()
    picks = sorted({Ts[0], Ts[len(Ts) // 2], pd.Timestamp(config.TRAIN_CUTOFF), Ts[-1]})
    end = pd.Timestamp("2026-10-16")
    ok = True
    for T in picks:
        d_full = dma.snapshot(T, sd, pairs, first_sanc, end)
        full = gf.snapshot(T, pres, ident, ev, cand, regstat, first_sanc, end, d_full, os_ev)
        fs_t = first_sanc.where(first_sanc < T)
        it = ident[ident["from"] < T].assign(to=lambda x: x["to"].clip(upper=T))
        d_tr = dma.snapshot(T, sd[sd.day < T], {k: v[v.day < T] for k, v in pairs.items()}, fs_t, end)
        trunc = gf.snapshot(T, pres[pres.month_start < T], it, ev[ev.end < T], cand, regstat, fs_t, end, d_tr,
                            os_ev[os_ev.known_at < T])
        if full.empty and trunc.empty:
            continue
        cols = gf.FEATURES + gf.OTHER_LISTS
        a = full.set_index("imo")[cols].sort_index()
        b = trunc.set_index("imo")[cols].sort_index()
        same = a.index.equals(b.index)
        diff = [] if not same else [f for f in cols
                                     if not np.allclose(a[f].astype(float), b[f].astype(float), equal_nan=True)]
        st = "PASS" if same and not diff else "FAIL"
        ok &= st == "PASS"
        print(f"T={T.date()} rows={len(a)} population_equal={same} mismatched={diff} -> {st}")
    print("GLOBAL LEAKAGE TEST", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
