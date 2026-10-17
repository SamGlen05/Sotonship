# Vessel report UI — first iteration

Scope: **vessel report page only**. Homepage, analysis page, scoring pipeline and data contract remain unchanged.

## Changes
- Left: vessel identity, existing estimated 90-day likelihood and risk band, top three reasons from existing explanations/model contributors, plus recommended review action.
- Right: analyst assistant with guided questions, conversation history, and compose field.
- Supporting evidence: expandable section with movement map, audience-specific economic exposure, sanctions list status, complete model drivers, dated evidence, coverage and vessel history.
- Shortcuts: local-device watchlist and print/Save to PDF via the browser print dialog.
- Responsive two-column layout on large screens; stacked layout for iPad portrait and mobile.

## What this does not do
- Does not recalculate or modify predictions.
- Does not change app/data or ingest licensed datasets.
- Does not introduce a new cloud AI endpoint, server key or model. The existing Claude API integration works only in supported environments. Other browsers show a transparent offline explanation.
- Does not sync watchlist with the backend. Saves only to the current browser/device.

## Demo deployment
The public gh-pages branch contains a copy of the original dashboard plus **fictional sample vessel data**.
The analyst assistant on that page responds with **scripted, rule-based text** grounded in the fictional data and is explicitly labelled "Guided demo · no AI". It is not live or trained inference. The global SFP_PREVIEW flag enables that mode.

## Review checklist
1. Check a high-, medium- and low-risk scenario plus an unscored case.
2. Expand Supporting evidence; ensure map, financial estimates, history and list status appear.
3. Change audience and oil-price assumptions; score/evidence and chat should still operate.
4. Test search, back navigation and vessel changes (chat should reset per vessel).
5. Ask a suggested question and a custom question. Demo replies are scripted; live Claude is used only where available.
6. Test watchlist persistence after browser reload and test print dialog.
7. Verify iPad portrait/landscape and desktop widths.

## Next iteration ideas
- Agree exact wording for the risk score: model probability vs relative ranking.
- Improve evidence citation display, source timestamps and confidence cues.
- Connect watchlist to a real backend if collaborative tracking is required.
- Provide real AI chat through an authenticated server endpoint, with no secrets in static HTML.
- Add vessel history drawer and review/approval workflows.
