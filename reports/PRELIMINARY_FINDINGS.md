# Preliminary findings: data access and first analysis

Written 2026-10-16, before any model. All lists were retrieved 2026-10-16. Every number below is in `reports/explore_numbers.json`, which `src/sfp/explore.py` produces. Download URLs, retrieval times and checksums are in `data/raw/manifest.jsonl`.

**AIS scope of this run:** 7 sampled days of Danish Maritime Authority AIS: 2026-01-07, 02-04, 04-01, 04-15, 04-29, 05-13 and 05-27. Eleven days are downloaded, but 4 of them (01-21, 02-18, 03-04, 03-18) had not been reduced when this was written. Rerun `sfp.ais_reduce`, `sfp.link` and `sfp.explore` to include them.

## What we have

| Source | What we got | Usable as |
| --- | --- | --- |
| UK Sanctions List (CSV, report date 16-Oct-2026) | 683 ships (645 Russia regime, 37 DPRK, 1 Libya), each with a designation date | Primary labels |
| EU designated vessels (DMA import CSV, 24-07-2026) | 733 rows, 671 Russia (Art. 3s) IMOs, each with a date of application | Labels and a cross-list feature |
| OFAC SDN advanced XML (issued 2026-10-15) | 1,559 vessels, 442 on the Russia program, with entry dates, flags, former flags and build year | Labels and attributes. Russia vessel designations stop in Q1 2025 |
| GUR shadow-fleet catalogue (scraped 2026-06-24) | 1,404 vessels, 1,244 ports | Port coordinates and static attributes only (see leakage) |
| OpenSanctions maritime (2026-10-16) | 20,841 vessels incl. Tokyo, Black Sea and Abuja MoU detentions | Cross-check only (no dates) |
| ITU MID table (Wikipedia copy) | 292 MMSI prefixes mapped to flags | Flag from MMSI |
| DMA AIS | 11 daily files (~650 MB each). 7 reduced to tanker positions at 5-minute resolution plus daily static data | Corridor behaviour |
| Global Fishing Watch | **Not yet.** Needs `GFW_API_TOKEN`. Fetcher written in `src/sfp/gfw.py` but untested | Worldwide behaviour |

## Finding 1: the UK mostly follows the EU, so "listed elsewhere first" is the baseline to beat

- 23 of the 27 ships in the 2026-06-16 UK test batch were already EU-listed on **2026-04-24**. That is a week before our 2026-05-01 training cut-off.
- Rank every ship not yet UK-listed by how recently the EU or US listed it, as of 2026-06-01. That puts **16 of 27** June-batch ships in the top 25 and **23 of 27** in the top 50, from a pool of 300.
- The October batch (8 ships across 2026-10-01 and 10-02) is different. Only 4 of the 8 were listed elsewhere first, and that rule gets 1 in the top 25 and 2 in the top 50. Five of the 8 are LNG carriers.
- Across all UK ship designations, 365 followed an EU or US listing (median lag 192 days), 244 came first and 34 are UK-only.

**Implication:** this rule has to go into the baseline table in `docs/EVALUATION.md`, because a judge will ask about it. A model that cannot beat it on the June batch adds nothing. The October batch is where behaviour data has to earn its place. *(Not yet added: the docs are read-only for this session.)*

Charts: `01_designation_timing.png`, `02_uk_batches_cross_list.png`.

## Finding 2: Danish-corridor AIS coverage is the biggest bottleneck

- Over the 7 sampled days we saw 907 distinct tankers, about 225 a day.
- Of the test-batch ships, only **3 of 27** (June) and **0 of 8** (October) appear in the sample before designation.
- Coverage is not saturating. Each extra day adds about 100 to 150 new tankers and about 10 that are ever designated. Denser sampling would help, but a full Jan to May pull is about 100 GB, roughly 8 hours at the DMA server's speed.
- **Global Fishing Watch worldwide events are the realistic fix.** Getting a token is the top next step.

Chart: `03_coverage_uk_batches.png`.

## Finding 3: some corridor signals separate designated from undesignated tankers, but the textbook ones don't

Tankers are grouped by their sanctions status on the day they were seen:

| | already designated (n=77) | designated later (n=6) | not designated (n=824) |
| --- | --- | --- | --- |
| Destination names a Russian port | 14% | 0% | 2% |
| Destination "FOR ORDERS" and similar | 39% | 50% | 15% |
| ITF flag of convenience | 30% | 33% | 51% |
| Top flags | Sierra Leone, Cameroon, Russia, Oman | Palau, Guinea | Malta, Liberia, Marshall Islands |

- The **ITF flag-of-convenience list points the wrong way**: mainstream open registries dominate it. The flags that matter are newer registries such as Sierra Leone, Cameroon and Gabon. A flag feature should come from flags common among ships designated **before T**, never from a hand list tuned on the labels.
- The "designated later" group has only 6 ships, so it supports no conclusions yet.

Chart: `04_contrast_by_status.png`.

## Finding 4: leakage and bias risks found in the data itself

1. **Build year is a label proxy.** It is known for 100% of designated tankers but only 2% of undesignated ones, because it comes from the sanctions lists. Any model given `build_year` or its missingness learns "is on a list". It needs one source for all ships: GFW identity, or drop the feature.
2. **GUR has no per-entry dates.** It is a single scrape (2026-06-24), and its port visits are undated. Use only time-invariant fields and port coordinates. GUR membership is legitimate only for snapshots after 2026-06-24: it holds 3 of the 8 October-batch ships and 8 of the 12 ships designated 2026-10-08.
3. **OpenSanctions maritime CSV has no dates.** Use it for cross-checks only.
4. **The ITU site blocks scripted access**, so the MID table is a Wikipedia copy and must be verified by hand.
5. **Batch dates:** the October "batch" spans 2026-10-01 and 10-02. `uk_batch` groups dates up to 2 days apart. There is also a 2026-10-08 batch of 12 ships that the evaluation doc doesn't mention, a candidate third test set.

## Next steps

1. Get a GFW API token, put it in `.env`, then run `python -m sfp.gfw --limit 20` and check it.
2. Reduce the remaining 4 AIS days, then decide on denser sampling for the months before each test batch.
3. Add the follow-the-leader baseline and the 2026-10-08 batch to `docs/EVALUATION.md`, and fill the Retrieved column in `docs/DATASETS.md` (values in `data/raw/manifest.jsonl`).
4. Stage 3: monthly snapshots and features computed only from data before T.
