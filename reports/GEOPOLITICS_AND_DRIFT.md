# Geopolitics, regime change and keeping the models honest

Design note, 2026-10-17. **Not implemented.** It covers how geopolitical news and turmoil could feed the risk tool, and how to deal with the fact that the model only sees history.

## The problem

The model learns from historical designations. That history is shaped by a small number of political decisions:
- the Russia programmes after 2022;
- Iran under US pressure;
- smaller DPRK, Syria, Venezuela and Libya programmes.

Three things follow:

1. **New regimes are invisible.** If the EU or UK opened a programme against a different country tomorrow, nothing in the training data would point at the ships serving it.
2. **Lifted regimes go stale.** When a programme is eased or lifted, the model keeps treating its ports and trade as risky. Syria's sanctions were largely lifted in 2025; Venezuela's US licences have come and gone. Our current feature list of "sanctioned-trade port countries" (Russia, Iran, Venezuela, Syria, North Korea) is hard-coded, so it is already partly out of date for Syria.
3. **The world itself shifts.** The data shows this today. IMF PortWatch records Strait of Hormuz tanker transits falling from about 45 a day in February 2026 to under 5 a day from March 2026 (all vessel types fell about 95%). A model trained on 2025 Gulf behaviour is scoring a different Gulf in October 2026. Nothing in our data says why.

The aim is a tool that stays correct as policy changes, and does not quietly encode yesterday's politics as today's risk.

## Principle 1: separate behaviour from jurisdiction

Split one score into two parts, each with its own data and refresh cycle:

**Risk = P(ship engages in sanctions-evasion behaviour) × P(that activity is targeted by an active regime)**

- **Behaviour score (regime-agnostic).** Signals that indicate evasion under any regime:
  - AIS switched off inside coverage, spoofed positions;
  - ship-to-ship transfers away from ports;
  - rapid flag, name and MMSI changes, and flags with weak oversight;
  - old tonnage with opaque or changing ownership, missing registry records.

  This part generalises to new regimes because evasion techniques are shared, and it is what we train on history.
- **Jurisdictional exposure (regime-specific, rules-based, versioned).** Which countries, ports, cargoes and counterparties are under an *active* regime on date T, for each authority (UK, EU, US and others). It is not learned. It comes from a **regime registry**: a dated table of programmes, their scope (countries, ports, cargo types, price caps, port bans) and their start and end dates.

The feature "port calls in sanctioned-trade countries" then becomes "port calls in countries under an active UK/EU/US regime **as of T**", computed from the registry. When Syria's regime ends, Syrian calls stop counting from that date. When a new regime starts, its ports count from its start date, even with no designation history yet.

## Principle 2: a dated regime registry, maintained like the lists

- **Source:** official texts (EU Official Journal, UK statutory instruments and FCDO notices, OFAC programme pages and Federal Register). An LLM can draft entries, but a human signs off every change.
- **Each entry:** authority, programme, scope (countries, ports, cargo, entity types), effective date, end date, and a link to the legal text.
- **Time-safe by construction:** features use the registry as it stood at T, so backtests replay what was knowable.
- **Delistings:** keep dated snapshots of every list (OpenSanctions keeps history, and we can archive our own daily downloads). The label stays "designated within 90 days", whatever happened later. A ship delisted afterwards was still designated.

## Principle 3: news and turmoil as dated, regime-level and entity-level signals

News should not decide risk on its own. It should move the **timing** and the **exposure** layers, and flag specific vessels for review.

1. **Regime pressure (timing).**
   - **Sources:** GDELT (free, multilingual, global news events with 15-minute updates and archives back many years), official press releases, and parliamentary and Council agendas.
   - **Signals:** counts and tone of articles about sanctions packages per authority and target, plus known calendar events. EU packages are negotiated in public and leaked weeks ahead; G7 summits and invasion anniversaries tend to come with batches.
   - **Use:** feeds a separate **batch-timing model** ("how likely is a UK or EU vessel batch in the next 30/60/90 days?"). Designations come in batches, so *when* is a political question and *who* is a behavioural one. Keeping them apart stops the ranking model from learning calendar artefacts.
2. **Entity mentions (who).**
   - **Sources:** investigative and NGO reporting (for example KSE Institute, Lloyd's List, Windward and Kpler analyses, Ukrainian GUR updates) often names vessels months before designation.
   - **Method:** extract IMO numbers and names from articles with an LLM, keeping the publication date. That gives "named in shadow-fleet reporting before T" as a dated feature, plus a review queue.
   - **Bias guard:** coverage is skewed toward English-language Western outlets and toward ships already under scrutiny. Use these mentions as a review trigger and a separate model input whose contribution is shown explicitly, never hidden inside the score.
3. **Turmoil and disruption (context).**
   - **Sources:** chokepoint traffic (IMF PortWatch), conflict and security incidents (ACLED, UKMTO and JMIC advisories), JWC listed areas (war-risk zones), and GNSS-jamming maps.
   - **Use:**
     - **Normalisation:** a gap or position jump in a region with heavy jamming, or during a closure, is weaker evidence than the same event elsewhere. Features become "relative to vessels in the same area and week".
     - **Insurer view:** war-risk exposure is a separate risk card line.
     - **Drift alarm:** when regional traffic collapses (as at Hormuz since March 2026), behaviour features there are flagged as out of distribution, and the card says so.

## Principle 4: handling new regimes with no history (cold start)

- **Scenario mode.** An analyst declares a hypothetical or newly announced regime: "EU targets ports in country X from date D". The exposure layer recomputes immediately: which ships call at X, meet ships that call at X, or are owned or managed there. The ranking for that regime is then behaviour score × exposure, with no retraining needed.
- **Analogy transfer.** Start a new regime's model from the behaviour model trained on existing regimes, and add regime-specific weight only as designations accumulate.
- **Human in the loop.** Early batches under a new regime are used to check the transfer before any automated alerting.

## Principle 5: keeping the models current and unbiased

1. **Rolling retraining with time-split validation.** Retrain monthly on all complete-label snapshots. Validate every model on the latest batches it has not seen, before promotion (champion / challenger). Report hits in the top K per authority and per region, not only overall.
2. **Recency weighting.** Weight recent training snapshots more, so 2022-era patterns (for example Russian-flagged tankers) don't dominate after the fleet re-flagged.
3. **Drift monitoring.** Track the following per region:
   - feature drift (population stability index, a standard measure of distribution shift);
   - base-rate drift (designations per month);
   - calibration drift (predicted vs actual designation rate).

   Alert when any moves beyond a threshold. Hormuz in 2026 would have triggered this.
4. **Bias and fairness checks.** Flag and region features can turn into proxies for politics.
   - **Breakdowns:** report performance and false-positive rates by flag, region and owner nationality.
   - **Reasons:** cap how much of a ship's score may come from jurisdiction-only signals, and show the behavioural evidence first.
   - **Ownership:** never use nationality of crew or owners as a feature.
5. **Label hygiene.** "Never designated" does not mean "clean". Use positive-unlabelled methods, and track how many high-scoring ships are designated later. That is the real-world precision.
6. **Explain the regime on the card.** Every elevated score should say which active regime makes it relevant (for example "exposure: UK Russia regulations, active since 2019; EU Reg. 833/2014"). When a regime ends, the card changes the same day.

## What this would take

| Piece | Data | Effort |
| --- | --- | --- |
| Regime registry (dated scope per programme) | Official texts, LLM-drafted, human-approved | Days to set up, then hours per regime change |
| Daily list archiving and delisting dates | Our own scheduled downloads, OpenSanctions history | Small |
| Batch-timing model | Designation history, GDELT, policy calendar | Medium |
| Vessel mentions in reporting | News and NGO articles, LLM extraction with dates | Medium; licence checks per source |
| Disruption normalisation | PortWatch (already downloaded), JWC areas, jamming data | Medium |
| Drift and fairness monitoring | Model outputs | Small to medium |
