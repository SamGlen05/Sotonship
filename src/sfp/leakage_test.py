"""Automated leakage test for Stage 3 features.

For several snapshot dates T, rebuild the features from inputs PHYSICALLY truncated
to data before T (AIS rows, STS meetings, sanctions dated before T) and assert they
equal the pipeline's features. If any feature used information from on/after T,
the two would differ. Labels are excluded (they look forward by design).
Exit code 1 on any mismatch.
"""
import sys

import numpy as np
import pandas as pd

from sfp import config
from sfp.features import FEATURES, load_pairs, load_shipdays, sanction_dates, snapshot, snapshot_dates


def main():
    sd, first_sanc = load_shipdays(), sanction_dates()
    pairs = load_pairs(sd)
    Ts = snapshot_dates()
    picks = [Ts[0], Ts[len(Ts) // 2], pd.Timestamp(config.TRAIN_CUTOFF), Ts[-1]]
    ok = True
    for T in picks:
        full = snapshot(T, sd, pairs, first_sanc, pd.Timestamp("2026-10-16"))
        # truncated inputs: nothing on/after T; future sanctions replaced by "not sanctioned"
        fs_trunc = first_sanc.where(first_sanc < T)
        trunc = snapshot(T, sd[sd.day < T], {k: v[v.day < T] for k, v in pairs.items()}, fs_trunc, pd.Timestamp("2026-10-16"))
        if full.empty and trunc.empty:
            continue
        a = full.set_index("imo")[FEATURES].sort_index()
        b = trunc.set_index("imo")[FEATURES].sort_index()
        same_pop = a.index.equals(b.index)
        diff = [] if not same_pop else [f for f in FEATURES
                                         if not np.allclose(a[f].astype(float), b[f].astype(float), equal_nan=True)]
        status = "PASS" if same_pop and not diff else "FAIL"
        ok &= status == "PASS"
        print(f"T={T.date()} rows={len(a)} population_equal={same_pop} mismatched_features={diff} -> {status}")
    print("LEAKAGE TEST", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
