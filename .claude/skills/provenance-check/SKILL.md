---
name: provenance-check
description: Check that every dataset, number and date in the README, app views and pitch traces to a logged source with a retrieval date and licence. Use before submission, before recording the demo, and after adding a dataset.
allowed-tools: Read, Grep, Glob
---

# Provenance check

Judges and users must be able to trace every figure to a source and a date. Run this audit and report gaps. Do not invent sources or dates to fill a gap; mark it and ask.

## Inputs to read

- `docs/DATASETS.md` (the data register)
- `README.md`
- Everything in `app/` that renders text, numbers or dates
- Pitch material and charts in `reports/`
- Stage manifests next to outputs in `data/interim/` and `data/processed/`
- `.env.example`

## Checks

1. **Register complete.** Every source actually read by the pipeline (per the manifests) has a row in `docs/DATASETS.md` with URL, licence and a filled **Retrieved** date. List any source used but not registered, and any row with a blank date.
2. **README data table.** Matches the register: same sources, URLs, dates and licences.
3. **Licence notes.** The README states that Global Fishing Watch and OpenSanctions are non-commercial only and that production needs commercial licences. Equasis is used only for manual lookups.
4. **Every figure sourced.** Each number in the README, app and pitch (fines, fleet counts, hit counts, coverage, dates) has a source link or points to a results table produced by the pipeline. List any unsourced figure with its location.
5. **Cached versus live.** Any view that uses cached data shows the cache date and does not say "live".
6. **Synthetic data.** Anything synthetic is labelled synthetic wherever it appears. Nothing synthetic appears in the headline result.
7. **Results consistency.** Numbers in the README results table match the latest backtest output and its manifest.
8. **Personal data.** No GUR captains table, and no individuals beyond official names on sanctions lists, in any committed file or view.
9. **Wording.** No named ship is called "shadow fleet" as a verdict. The vessel card footer reads: "Risk indicators for human review. Not a finding that this vessel is evading sanctions."
10. **Secrets.** `.env.example` holds names only. No key appears in any tracked file, notebook output or log.
11. **Track disclosures.** The README lists AI-generated parts, what existed before the event, and who helped.

## Output

A short report listing each check as **pass** or **fail** with the location of each problem, then a final verdict: **ready** only if every check passes.
