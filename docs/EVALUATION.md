# Evaluation protocol

The headline claim of the project comes from this protocol. Do not change it without writing down what changed and why in the decision log at the bottom.

## The question

For a tanker not yet sanctioned on snapshot date T, how likely is it to be designated within the next 90 days?

## Framing

- Monthly snapshot dates.
- For each snapshot T, include every tanker not yet designated (under the regime being predicted) on T.
- Features: Stage 3 signals computed only from data before T.
- Label: 1 if the ship was designated in the 90 days after T, otherwise 0.

## Splits (time-based only)

- **Training:** snapshots before 2026-05-01.
- **Test batch A:** UK designations on 2026-06-16 (27 ships).
- **Test batch B:** UK designations on 2026-10-01 (8 ships).
- **Extra tests:** EU and US designation batches after 2026-05-01, if labels allow.
- Never shuffle across time. Never tune on a test batch.

## Models, simplest first

1. Rule-based score (Stage 3)
2. Logistic regression
3. Gradient boosting (LightGBM or XGBoost) with SHAP values

## Baselines to beat

| Baseline | What it does | Expected result |
| --- | --- | --- |
| Sanctions-list lookup | Flags ships already on a list | Flags nothing before designation, by definition |
| Age and flag rule | Old tanker plus a flag of convenience | The simple rule a sceptical judge will suggest |
| Random ranking | Random order | The floor |

## Metrics

Positives are rare (hundreds of designated ships among thousands of tankers), so report ranking metrics:

- **Hits in top K:** of ships designated in a test batch, how many were in the top K (report K = 25, 50, 100) at the last snapshot before designation
- **Precision-recall AUC**
- **Lead time:** days between a ship first entering the top K and its designation
- **Coverage:** share of test-batch ships with any behaviour data before designation

## Results template

Fill in once per model and baseline, and copy the final table into the README.

| Model | Test batch | Ships in batch | Ships with data | Hits in top 25 | Hits in top 50 | Hits in top 100 | PR-AUC | Median lead time (days) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

## Leakage checklist

Run `/leakage-check`, and confirm each item before any number is shared:

- [ ] No feature uses data timestamped on or after its snapshot date
- [ ] No feature uses behaviour after the ship's own designation
- [ ] "Meetings with designated ships" counts only partners designated before T
- [ ] No list membership (GUR, OpenSanctions or any other) without a date before T
- [ ] Thresholds and weights were set on training data only
- [ ] The test batches were not used for model selection

## Honesty rules

- Report the result we get, including a weak one. A small honest number beats a large doubtful one.
- State coverage alongside every hit count.
- Some high-scoring ships that were never designated may still be shadow-fleet vessels. Say so, without naming any as such.

## Decision log

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-10-16 | Training cut-off 2026-05-01; test on UK batches of 2026-06-16 and 2026-10-01 | Two recent, clearly dated batches after the cut-off |
