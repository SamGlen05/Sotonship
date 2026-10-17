# How to predict sanction risk accurately, worldwide

Written 2026-10-17 after downloading and testing every dataset. It answers which data is most predictive, how the model should work, and how to scale to the whole world and to deep vessel histories. Numbers come from `data/processed/ablation.json`, `backtest_global.json` and `app/data/gfw_analysis.js`. For geopolitics and regime change, see `GEOPOLITICS_AND_DRIFT.md`.

## 1. What decides accuracy, in order

1. **Coverage: you cannot rank a ship you never see.**

   | Seen before designation | Danish AIS (113 weekly days) | Global Fishing Watch (11 sea areas) |
   | --- | --- | --- |
   | UK batch 2026-06-16 | 18 of 27 | **27 of 27** |
   | UK batch 2026-10-01 | 0 of 8 | **5 of 8** |
   | UK batch 2026-10-08 | 7 of 12 | **11 of 12** |
   | Every first sanction 2025-01 to 2026-10 | 259 of 929 (28%) | **712 of 929 (77%)** |

   Moving from one coastal receiver network to global AIS-derived data took training positives from 2–4 to 80–180 per monthly snapshot. No modelling trick comes close to that.

2. **How the population is chosen.** Tankers must be found by where they sailed, never from a sanctions list. A list-derived population is selected by its own future label. Our first Global Fishing Watch fetch was list-based, and I stopped it for that reason.

3. **Leak-proof dates on every fact.** The registry snapshot looked very predictive: 71% of later-sanctioned ships have no registry ship type. But it is undated, so it was excluded. Two automated leakage tests rebuild every feature from data truncated before each snapshot date and must pass before any metric is reported.

4. **Signals, and only then the model.** LightGBM beats logistic regression and the rule score in every test month, but the bigger gains came from data and population choices.

## 2. Which datasets are most predictive (measured)

The ablation adds dataset groups one at a time. Choices are made on a validation split inside the training period. The test months, after 2026-05-01, are shown for information only.

| Added | Validation lift over random | Test lift | Test hits in top 100 |
| --- | --- | --- | --- |
| GFW presence by sea area + IMO-number age | 7.5× | 8.6× | 11 / 120 |
| **+ GFW identity history (flag, name, MMSI changes)** | **11.1×** | **21.8×** | **24 / 120** |
| + GFW port visits by country | 11.2× | 18.5× | 20 / 120 |
| + GFW AIS gaps (intentional only) | 10.2× | 16.0× | 20 / 120 |
| + GFW loitering, incl. next to sanctioned tankers | 11.7× | 16.6× | 19 / 120 |
| + Chokepoint passages, incl. with AIS off (GFW port calls + gaps) | 11.6× | 16.0× | 20 / 120 |
| + Danish AIS behaviour | 11.4× | 17.5× | 21 / 120 |
| + Other authorities' lists and port-state detentions | 12.1× | 18.7× | 21 / 120 |

**Ranking of datasets by value:**

1. **Global Fishing Watch presence and identity history.** Where a tanker trades, how old it is (IMO number) and how often it re-flags, renames or changes MMSI carry most of the signal. Flag hopping is common: 2,271 tankers used two flags in 12 months, 365 used three and 90 used four or more.
2. **Sanctions lists (UK, EU, OFAC) with dates.** Indispensable as labels. They also drive the strongest single input: the flag's share of already-sanctioned tankers, computed only from earlier designations.
3. **Global Fishing Watch port visits and loitering.** They add little on top of identity *as currently engineered*, but they carry the evidence an analyst needs, such as dated port calls and loitering next to named sanctioned tankers. Better features from them are the main modelling opportunity (section 3).
4. **Global Fishing Watch AIS gaps.** Sparse (4,874 events in total, all flagged intentional) and fully redundant with each other.
5. **Danish AIS.** Rich detail, but only 28% reach (259 of 929 later-sanctioned ships seen). Valuable for depth in the Baltic approaches; it adds almost nothing to ranking once Global Fishing Watch is in.
6. **OpenSanctions dated lists and detentions.** Other authorities rarely list a ship first. Useful context on the vessel card.
7. **IMF PortWatch.** Not vessel-level, so no ranking value. High value as a drift alarm: Hormuz transits fell about 95% from March 2026.

**Recommended core stack for the next version:**
- **Global Fishing Watch** (presence, identity, events) as the behaviour backbone;
- **dated sanctions lists** for labels and network features;
- **a commercial fleet registry** (S&P Sea-web or similar) for ownership, management, insurer and class with dates;
- **satellite radar** "dark vessel" detections.

Everything else is context.

## 3. How to model it more accurately

1. **Two questions, two models.**
   - **"First designation anywhere in the next 90 days."** This is the current model and the right one for a bank screening a new counterparty.
   - **"Will another authority follow?"** This is for ships already listed somewhere. The UK designated 23 of its 27 June-batch ships after the EU had. Among UK designations that followed an EU or US listing, the median lag was 192 days. A follow-on model using "listed by EU/US on date X" would rank these very well, and it's a legitimate, dated signal. Banks under UK jurisdiction need exactly this view.
2. **Better behaviour features from data we already hold.**
   - **Near-shore transfers.** Laconian Gulf and Kalamata show no loitering because GFW only counts loitering 20+ nautical miles from shore. Detect slow near-shore pairs from presence and port events, and add hotspot polygons from published reporting.
   - **Voyage sequences.** For example: Russian or Iranian loading port → long transfer loiter → India, China or UAE discharge. Features would cover the sequence and its timing, not just counts.
   - **Co-loitering graph.** Who loiters with whom, over time, using only sanctions dated before T. Graph features: distance to a sanctioned ship, shared partners.
   - **Draught changes at sea.** Loading without a port call. This needs positions, so it comes with satellite AIS.
   - **Gaps compared with the local norm,** because jamming and coverage vary by region.
3. **Learning setup.**
   - **Training:** positive-unlabelled training, since "never sanctioned" is not "clean"; time-decay weighting; monthly retraining with champion/challenger.
   - **Evaluation:** per authority and per region.
   - **Probabilities:** calibrated per region.
4. **Ownership and management.** The strongest signal in published research, and the one gap we can't fill for free. Ownership changes, single-ship companies and opaque jurisdictions need a licensed registry with dated records. The GFW registry has an operator field for some ships, but it is undated, so it's display-only for now.
5. **Keep the explanations first-class.** Every elevated score already lists dated, sourced reasons, and any elevated score without one is flagged for manual review. Keep that as a hard rule as features grow.

## 4. Covering the world

- **The design is region-agnostic:** sea areas are a list of boxes in `gfw_region.py`.
- **Add these areas next:**
  - Malaysia (Eastern Outer Port Limits and the Singapore Strait transfer hub);
  - the Yellow Sea and Shandong discharge ports;
  - India's west coast (Sikka, Vadinar);
  - West Africa (off Lomé);
  - the Russian Pacific (Kozmino);
  - Venezuela and the Caribbean;
  - the Gulf of Guinea.
- **Cost:** each area adds about 10 presence reports plus identity and event calls for its new tankers. That's minutes to an hour of API time.
- **For production, beyond Global Fishing Watch:**
  - **satellite AIS** (raw positions everywhere);
  - **satellite radar** for ships with AIS off;
  - **a fleet registry**, so ships never seen are still scored;
  - **live feeds** (aisstream.io, Digitraffic) recorded continuously to build our own history.
- **Licences:** Global Fishing Watch and OpenSanctions are non-commercial. A product needs commercial agreements, or licensed equivalents.

## 5. In-depth vessel analysis

The vessel page is now a dossier:
- every identity period (name, flag, MMSI, with dates);
- port calls from 2024 to 2026;
- AIS gaps of a day or more;
- port-state detentions;
- list status with dates;
- dated evidence behind each reason;
- a question box that answers only from that evidence.

**Next steps for the dossier:**
- a voyage timeline map (port calls and loitering in order);
- profiles of counterpart ships (who it loitered with, and their status);
- an ownership and management chain, once a registry is licensed;
- a one-page memo export for the bank's audit file.

## 6. What the current model achieves (honest)

- **Training:** 16 monthly snapshots before 2026-05-01, 202,813 tanker-months, of which 1,446 were sanctioned within 90 days.
- **Test months:** May to October 2026, about 12,800 tankers and 20–51 new designations each. LightGBM reaches PR-AUC 0.030–0.065, against 0.002–0.004 for random order. It beats the hand-weighted rule score in every month: clearly from August, narrowly in June and July. It catches **5–11 of the 20–51 new designations in its top 100** each month.
- **Track record by band** (May–July 2026, labels complete, model trained before May):

  | Band | Sanctioned within 90 days |
  | --- | --- |
  | High (top 1%) | **7.6%** (29 of 383 tanker-months), 24× the 0.31% average |
  | Medium (next 4%) | 3.3% (51 of 1,537) |
  | Low | 0.11% |

  **The top 5% held 80 of the 120 new designations (67%).**
- **The months from August onward have incomplete labels.** Designations up to 2026-10-16 are known, so those months understate true hits.
- **Weaknesses:**
  - ships outside the 11 sea areas are invisible;
  - ownership is missing;
  - near-shore transfers are missed;
  - Gulf behaviour shifted sharply after March 2026 (PortWatch), so Gulf scores deserve extra caution.
