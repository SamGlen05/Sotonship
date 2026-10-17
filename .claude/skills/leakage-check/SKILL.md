---
name: leakage-check
description: Audit the feature and backtest pipeline for temporal leakage before any metric is reported. Use before sharing a hit count, PR-AUC or lead time, and whenever features, thresholds, splits or labels change.
allowed-tools: Read, Grep, Glob
---

# Leakage check

The headline result is only credible if no feature for snapshot date T could have known anything from on or after T. Run this audit and report the outcome before any metric is shared. Do not change code during the audit; list what needs fixing.

## Inputs to read

- `docs/EVALUATION.md` (splits, label horizon, leakage checklist, decision log)
- `docs/PIPELINE.md` (event definitions, look-back window)
- The feature-building and backtest code in `src/`
- The threshold config file
- The latest stage manifests next to outputs in `data/processed/`

## Checks, in order

1. **Snapshot cut-off.** Every feature for snapshot T filters on a timestamp strictly before T. Look for filters using `<=`, missing date filters, or windows that end on T instead of the day before.
2. **Own designation.** No feature uses behaviour after the ship's own first designation date under any regime.
3. **Partner designation.** "Meetings with designated ships" and any network feature count a partner only if that partner was designated before T, not as of today.
4. **Undated list membership.** No feature uses membership of GUR, OpenSanctions or any other list unless the entry has a date before T. Undated membership is excluded.
5. **Identity fields.** Current name, flag or MMSI is not used for past snapshots. Only history entries that started before T.
6. **Thresholds and weights.** Every threshold and rule-based weight was set using training snapshots only (before 2026-05-01). Check the decision log for when each was set.
7. **Model selection.** Test batches (UK 2026-06-16 and 2026-10-01) were not used to choose features, hyperparameters, K or thresholds.
8. **Label horizon.** The label for T looks forward exactly 90 days, and training snapshots whose 90-day window crosses 2026-05-01 are handled as the protocol states.
9. **Population.** Each snapshot includes only tankers not yet designated on T, under the regime being predicted.
10. **Data retrieved later.** Any source downloaded during the hackathon (for example a current vessel registry) is not treated as if it were known at T unless its records carry dates.

## Output

A short report with:

- Each check marked **pass**, **fail** or **cannot verify**, with the file and line or the manifest that shows it
- For each fail, what leaks and the smallest fix
- A final verdict: **clear to report** only if every check passes; otherwise **do not report metrics yet**

Then tick the leakage checklist in `docs/EVALUATION.md` only for the checks that passed, and add a decision-log entry if anything was changed.
