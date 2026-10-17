# Audience views

The same score is shown differently to each audience, because each is making a different decision. Build the bank vessel card first, then the insurer screen.

## Views

| Audience | Their decision | What they see | Format |
| --- | --- | --- | --- |
| Bank trade-finance compliance (primary) | Can we finance this cargo or vessel? | Vessel card: list status today, risk band, top three dated signals, recommended action | Screening page plus a one-page memo for the audit file |
| Bank ship-finance or credit | Which ships we finance could be sanctioned? | Portfolio watchlist ranked by risk, alerts when a score jumps | Dashboard |
| Marine insurer or P&I club | Should we write or renew cover, and do the customer's attestations hold up? | Voyage history map, transfers and dark periods, renewal checklist | Underwriting screen |
| Reinsurer or war underwriter | How much high-risk exposure sits in one area? | High-risk ships by area | Map and table |
| Port or coastal authority | Which ships should we question first? | Ranked list of ships near our waters | Live map and list |
| Judges and VCs | Does it work, and who pays? | Backtest headline, one live vessel card, one failure case | Three slides and the demo |

## Vessel card: content in order

1. Ship name, IMO number, current flag, build year (each with its source)
2. List status today: UK, EU, US, each with the date checked
3. Risk band (low, medium, high) and score, with the model version and data cut-off date
4. Top three signals, each with its date, place and source, for example "AIS gap of 9 days, 2026-08-14, near a known transfer area (Danish Maritime Authority AIS, retrieved 2026-10-17)"
5. Recommended action: proceed, extra checks, or decline, plus what extra checks to request (itemised costs, voyage history)
6. Coverage note: what data exists for this ship and what does not
7. Footer: "Risk indicators for human review. Not a finding that this vessel is evading sanctions."

## Failure cases to show

- **No AIS history in the corridor:** show "Not enough data to assess" with the coverage note. Never show a low score.
- **Data source unavailable:** show the cached data's date and say it is not live.
- **Ship already designated:** show the designation and its date; the prediction is not needed.

## Wording rules

- Say "risk indicators", never "shadow fleet" as a verdict on a named ship.
- Every number and date shows its source.
- Neutral on the conflict: describe sanctions compliance, not politics.
- Label anything synthetic as synthetic.
