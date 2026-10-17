# Shadow Fleet Risk Predictor

> SotonShip 2026, FinTech track. Repository created after hacking opened on Friday 16 October 2026, 20:00.

**One line:** We help bank and insurer sanctions analysts decide whether to finance or insure a tanker by predicting which ships are likely to be sanctioned next, using AI trained on public sanctions lists and AIS ship-tracking data.

## The user and the problem

_To complete: who the user is, what they do today, and the evidence that the problem is real and costly. Every figure needs a source link and date._

## What it does

_To complete: the vessel card, the backtest, and what each audience sees._

## Headline result

_To complete from `docs/EVALUATION.md`: the results table for the UK designation batches of 16 June and 1 October 2026, against all baselines, with coverage stated._

## How it works

1. Ingest and link sanctions lists and AIS data on IMO number
2. Explore coverage, timing and leakage
3. Compute risk signals before each snapshot date
4. Predict with a rule-based score, logistic regression and gradient boosting; validate on later designation batches
5. Present a dated risk card for each audience

## Data sources

_Copy from `docs/DATASETS.md`: every source used, with URL, retrieval date and licence. State which data is synthetic, if any._

| Dataset | URL | Retrieved | Licence |
| --- | --- | --- | --- |
| | | | |

Global Fishing Watch and OpenSanctions data are licensed for non-commercial use only. A production version would need commercial licences or data feeds.

## Limitations

- Corridor AIS only sees ships that pass through the corridor.
- Ownership and management changes are not included.
- Ships never designated are not confirmed innocent, so some "false positives" may be correct.
- Outputs are risk indicators for human review, not findings about any vessel.

## Responsible use

_To complete: human review, no personal data, neutral language, failure cases shown in the demo._

## AI-generated parts

_To complete: which files or sections were written with AI assistance (for example Claude Code), and how they were checked._

## What existed before the event

_To complete: libraries, templates and pre-trained models used. No earlier project code is reused, per track rules._

## Who helped

_To complete._

## How to run

_To complete once the pipeline exists._
