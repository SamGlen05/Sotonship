# Shadow Fleet Risk Predictor

## What we are building

A SotonShip 2026 FinTech track entry. Hacking runs Friday 16 October 2026, 20:00 to Sunday 18 October 2026, 13:00. Submissions lock at 13:00 Sunday with no extensions.

The tool helps sanctions-compliance teams at banks and marine insurers spot oil tankers that are likely to be sanctioned next. It reads public sanctions lists and AIS ship-tracking data, scores each tanker, and shows a dated risk card with the evidence behind the score.

Track-format statement: *We help bank and insurer sanctions analysts decide whether to finance or insure a tanker by predicting which ships are likely to be sanctioned next, using AI trained on public sanctions lists and AIS ship-tracking data.*

The headline result we must produce: train only on data before 2026-05-01, then report how many of the ships the UK designated on 2026-06-16 (27 ships) and 2026-10-01 (8 ships) the model ranked in its top K before designation. Every other piece of work serves this number or the demo.

## Users

- **Primary:** a sanctions analyst in a bank's trade-finance or commodity-finance team, clearing a vessel before the bank finances a cargo.
- **Secondary:** marine insurer or P&I underwriter; port or coastal authority; the judges and VC audience on Sunday.
- What each one sees is specified in `docs/AUDIENCES.md`.

## Weekend scope

- **Corridor:** the Danish straits, using Danish Maritime Authority historical AIS.
- **Labels:** UK Sanctions List (primary), EU Annex XLII vessel list and OFAC SDN vessels (secondary).
- **Worldwide history:** Global Fishing Watch events (AIS gaps, encounters, loitering, port visits).
- **Models:** a transparent rule-based score, logistic regression, then gradient boosting with SHAP.
- **Views:** bank vessel card and insurer screen. Others only if time allows.
- **Out of scope:** ownership networks, bulk Equasis data, production deployment, live trading of any kind.

## Pipeline

Five stages, specified in `docs/PIPELINE.md`:

1. Ingest and link: vessel master table, label table, event table, all keyed on IMO number
2. Explore: coverage, timing, lead time, leakage and data-quality checks
3. Risk signals: features over a look-back window before each snapshot date, plus the rule-based score
4. Predict and validate: time-split backtest, baselines, ranking metrics (see `docs/EVALUATION.md`)
5. Present: audience views (see `docs/AUDIENCES.md`)

## Data

The full register, with URLs, licences and retrieval dates, is `docs/DATASETS.md`. Update it whenever a dataset is added or re-downloaded.

The seven sources we need first: UK Sanctions List, EU Annex XLII vessel list, OFAC SDN vessels, Danish Maritime Authority AIS, Global Fishing Watch API, the ITU table of maritime identification digits (MMSI prefix to flag), and port locations for Russian export terminals.

**Join everything on IMO number.** It never changes for a ship. MMSI changes when a ship reflags, so treat MMSI as a time-bounded attribute of an IMO, never as a key.

## Hard rules

These are not negotiable. If a request conflicts with one, stop and say so.

1. **No temporal leakage.** A feature for snapshot date T uses only data timestamped before T. Never use behaviour after a ship's designation, and never use a list entry dated after T. Run `/leakage-check` before reporting any metric.
2. **Provenance for every number.** Every dataset is logged in `docs/DATASETS.md` with URL, retrieval date and licence. Every figure in the UI, README or pitch traces to a source and a date. Never present cached data as live, and never present synthetic data as real. Label synthetic data as synthetic wherever it appears.
3. **Raw data is read-only.** Files in `data/raw/` are written once by download steps and never edited. Derived data goes to `data/interim/` and `data/processed/`.
4. **Secrets stay in `.env`.** Never commit, print or log API keys. `.env.example` lists the variable names only.
5. **No personal data.** Drop the named-captains table from the GUR catalogue. Store no individuals beyond the official names on sanctions lists.
6. **Careful language.** Outputs are risk indicators for human review. Never describe a named ship as "shadow fleet" as a verdict. Stay neutral on the conflict.
7. **Licences.** Global Fishing Watch and OpenSanctions are non-commercial only. That is acceptable for the hackathon; the README must say so and note that production needs commercial licences.
8. **Track rules.** No real customer data. Build nothing that creates fake documents, deepfakes or scam material. The README must list AI-generated parts, anything that existed before the event, and who helped.
9. **Thresholds are assumptions.** Every heuristic threshold (AIS gap hours, meeting distance, loitering speed, spoofing speed) lives in one config file with a comment saying it is an assumption. Never hard-code one in feature logic.

## Working conventions

- Python 3.11 or later. DuckDB and Parquet for AIS; pandas is fine for small tables. LightGBM or XGBoost with SHAP for the model; scikit-learn logistic regression as the explainable baseline.
- Notebooks are for exploration only. Logic that a later stage reuses lives in `src/`.
- Develop on one month of AIS first. Scale up only once a stage works end to end.
- Every stage writes a small manifest next to its output: sources used, retrieval dates, row counts and the time it ran.
- Prefer simple and explainable over clever. A judge must follow every step in the demo.
- When a choice affects the headline result (a threshold, a split date, a filter), write it down in `docs/EVALUATION.md`.

## Directory layout

- `data/raw/`: downloads exactly as received (read-only, not committed)
- `data/interim/`: cleaned and linked tables (not committed)
- `data/processed/`: feature tables, scores and backtest results
- `src/`: pipeline stages
- `notebooks/`: exploration
- `app/`: the audience views
- `docs/`: specifications and the data register
- `reports/`: charts and tables for the README and pitch

## Definition of done by Sunday 13:00

- [ ] Backtest result for the June and October UK batches, against all baselines
- [ ] Rule-based score and one gradient-boosting model with SHAP explanations
- [ ] Bank vessel card working on a real IMO, with dated evidence and a failure case ("no AIS history in this area")
- [ ] README complete: data sources with dates and licences, AI-generated parts, pre-existing work, helpers, limitations
- [ ] Demo video (1 to 3 minutes) uploaded to YouTube
- [ ] Summary of about 150 words
- [ ] `/provenance-check` passes

## Claude Code setup

- `/leakage-check`: audits features and the backtest for temporal leakage. Run before reporting any metric.
- `/provenance-check`: audits that every dataset, number and date traces to a logged source. Run before submission.
- `data-auditor` subagent: an independent, read-only reviewer. Use it before a result goes into the README or pitch.
- `.claude/settings.json` blocks reading `.env` and editing `data/raw/`. Personal overrides go in `.claude/settings.local.json` (not committed).

## Reference docs

- `docs/DATASETS.md`: every source, its role, access and licence
- `docs/PIPELINE.md`: stage contracts, table columns, event definitions
- `docs/EVALUATION.md`: backtest protocol, metrics, baselines, leakage checklist
- `docs/AUDIENCES.md`: what each audience sees and the wording rules
