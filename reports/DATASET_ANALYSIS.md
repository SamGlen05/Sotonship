# Dataset analysis and MVP dataset choice

Written 2026-10-17. Each dataset was profiled on its own: what it contains, how far it reaches in time, which date fields it carries, and what would leak or bias a model. All were retrieved 2026-10-16 to 2026-10-17. URLs, retrieval times and checksums are in `data/raw/manifest.jsonl`.

The question every dataset was tested against: **can it say what was knowable about a ship on date T, for every ship, not only sanctioned ones?**

## 1. UK Sanctions List (FCDO CSV, report date 16-Oct-2026)

- 683 ships: 645 under the Russia regime, 37 DPRK and 1 Libya. Every ship has a valid IMO except one, plus a designation date and a statement of reasons.
- Designation dates run from 2024-07-31 to 2026-10-08 and come in batches: 20 batches of 2 to 135 ships.
- Ship type is missing for 247 of the 645 Russia ships, build year for 201 and flag for 144.
- OpenSanctions' copy of the list has the same 683 ships, so no delisted ships appear to be missing.
- **Role:** labels (dates are clean). It only describes sanctioned ships, so it can't supply features for the rest.

## 2. EU designated vessels (DMA import CSV, list of 24-07-2026)

- 733 rows: 671 Russia (Art. 3s) IMOs and 60 DPRK, each with a date of application. Four IMOs appear twice with different dates; we keep the first date.
- The batches line up with the EU sanctions packages. The 2026-04-24 batch held 23 of the 27 ships the UK designated on 2026-06-16.
- **Role:** labels and cross-list signal. Like the UK list, it only covers sanctioned ships.

## 3. US OFAC SDN (advanced XML, issued 2026-10-15)

- 1,559 vessels with entry dates, flag, former flags and build year. 442 are under Russia programmes.
- Russia-programme vessel designations stop on 2025-01-10. Since March 2025 OFAC's vessel designations have been almost all Iran-related (311 under IRAN-EO13902).
- **Role:** labels. It adds little recent Russia signal.

## 4. GUR War&Sanctions catalogue (source.coop parquet, scraped 2026-06-24)

- 1,404 vessels, 1,244 ports and 19,678 port visits. It is a single snapshot with **no listing dates**, and the port visits are undated.
- The OpenSanctions copy (`ua_war_sanctions`) has a first-seen date for each vessel, but none earlier than 2025-10-16.
- **Leakage risk:** high. Membership can only be dated from 2025-10-16, which is after most training snapshots.
- **Role:** dated context on the vessel card only. Port coordinates for Russian terminals.

## 5. OpenSanctions maritime CSV and per-dataset exports (2026-10-16)

- The maritime CSV has 20,841 vessels and no dates, so it is used for cross-checks only.
- The per-dataset entity exports do carry dates, as an official date plus `first_seen`:
  - **Canada:** 731 vessels, each with a listing date.
  - **Switzerland:** 638 vessels with listing dates. The IMO is recovered from referent IDs.
  - **Australia:** 357 vessels with start dates.
  - **Tokyo MoU detentions:** 5,577 vessels, 7,932 detentions from 2019 to 2026.
  - **Black Sea MoU detentions:** 1,248 vessels, 1,749 detentions.
  - **Abuja MoU detentions:** 211 vessels, 213 detentions.
  - **Paris MoU bans:** 147 vessels.
- Detentions are public about a month after they happen, so known-at = detention date + 30 days. The lag is an assumption, set in `config.py`.
- **Role:** strong dated cross-list features and dated vessel-card context. Licence is CC BY-NC 4.0: non-commercial use only.

## 6. Danish Maritime Authority historical AIS (daily CSV)

- About 650 MB zipped and 2.7 GB unzipped per day, roughly 15 million messages. The archive runs back to 2006.
- We take one day per week (Wednesdays), from 2024-08-07 to 2026-09-30, about 113 days. Each day is reduced to all Class A positions at 5-minute resolution (about 1,800 vessels, 400k rows, 7 MB) plus per-vessel daily static data.
- 99% of tanker records carry an IMO, and no MMSI showed two IMOs within one day.
- About 225 tankers are seen per day, and each new sampled day adds 100 to 150 tankers not seen before.
- **Coverage bias:** only ships that pass the Danish straits appear. Only 3 of the 27 June-batch UK ships were seen in the first 7 sampled days.
- **Strengths:** every row is timestamped, and it covers sanctioned and unsanctioned ships alike, so it is time-safe by construction. It is also the only source with positions, which a map needs.

## 7. Support tables

- **MID table:** 292 MMSI prefixes mapped to flags, from a Wikipedia copy of the ITU table (itu.int blocks scripts). Flags can only be inferred for ships seen in AIS.
- **NGA World Port Index:** 3,807 ports, used to drop ship-to-ship meeting candidates at berths.
- **Natural Earth 10 m land:** basemap only.

## Choice for the MVP: Danish AIS as the single feature dataset

| Need | UK/EU/US lists | GUR | OpenSanctions | **DMA AIS** |
| --- | --- | --- | --- | --- |
| Covers unsanctioned ships (negatives) | no | partly | partly (detained) | **yes** |
| Every fact dated, so time-safe | yes | no | yes | **yes** |
| Location for the map | no | no | no | **yes** |
| Behaviour (destinations, gaps, meetings, re-flagging) | no | undated | no | **yes** |
| Free for commercial use | yes | unclear | no | **yes** (DMA open data) |

The model is trained on AIS behaviour only. Sanctions-list dates enter only as:
- the **label**: first UK, EU or US sanction within 90 days after T;
- the rule that **already-sanctioned ships leave the population**;
- two network signals that count only sanctions dated **before T**: the flag's share of sanctioned tankers, and meetings with sanctioned tankers.

The other lists appear on the vessel card as today's list status, each with its date, and are not model inputs.

**Known cost of this choice:** cross-list status is the strongest predictor we found. 23 of the 27 June-batch ships were already EU-listed. Leaving it out keeps the MVP honest about what behaviour alone can do. Adding it back is the first planned upgrade.

---

## Added on 2026-10-17: global coverage sources

### 8. Global Fishing Watch API (non-commercial licence, token required)

- **Presence.** 4Wings AIS presence per vessel per month in 11 sea areas: Baltic, North Sea and Channel, Norwegian and Barents Seas, Iberian Atlantic, Western and Eastern Mediterranean, Black Sea, Red Sea, Gulf of Aden, Persian Gulf and Gulf of Oman, Arabian Sea. July 2024 to October 2026, one position per vessel per hour.
  - 24,897 vessel IDs with an IMO number, giving 17,545 candidate tankers after excluding registry-typed tugs, cargo ships, dredgers and similar. About 12,500 are present in any given 6-month window.
  - GFW has **no "tanker" vessel type**: tankers sit under "other". Registry records type 4,496 of the candidates as tankers. **71% of later-sanctioned ships present have no registry ship type**, so untyped vessels are kept and marked unverified.
- **Identity history** per IMO: every name, flag and MMSI period with dates. For example, one tanker went Liberia → Gabon → Barbados → Gambia → Cameroon → Russia between 2024 and 2026.
- **Worldwide events** for those tankers, January 2024 to October 2026:
  - port visits, with anchorage country;
  - AIS gaps flagged as likely intentional;
  - loitering.

  Tanker-to-tanker encounters are **not** in the public encounters dataset.
- **Coverage gain.** Seen in the data before designation, by source:

  | Batch | Danish AIS (113 weekly days) | Global Fishing Watch |
  | --- | --- | --- |
  | UK June 2026 | 18 of 27 | 27 of 27 |
  | UK October 1, 2026 | 0 of 8 | 5 of 8 |
  | UK October 8, 2026 | 7 of 12 | 11 of 12 |
  | Every first sanction, 2025-01 to 2026-10 | 259 of 929 | 712 of 929 |

  Training positives rise from 2–4 per monthly snapshot (Danish AIS) to 80–180.
- **Leakage handling.**
  - **Population:** tankers are found by where they sailed, never from a sanctions list. A list-based population would be selected by its own future label.
  - **Dated inputs:** presence by month, events by end time, and identity periods by start date all carry dates.
  - **Registry fields:** registry type, build year and tonnage are an undated current snapshot, so they are display-only, not model inputs.
- **Verdict: the most valuable dataset.** It has global reach, dated behaviour and identity history. It's the backbone of the global model.

### 9. OpenSanctions per-dataset exports, with dates

- **Lists:** Canada (731 vessels), Switzerland (638) and Australia (357), with listing dates.
- **Detentions:** Tokyo MoU (7,932), Black Sea MoU (1,749) and Abuja MoU (213), with detention dates.
- **Bans:** Paris MoU bans (148).
- **GUR catalogue:** dated only from 2025-10-16.
- **Verdict: useful as dated context and as an optional feature group.** Other authorities rarely list a ship *before* the UK, EU and US, so the gain is small. The ablation measures it.

### 10. IMF PortWatch daily chokepoint transits

- 79,548 daily rows for 28 chokepoints, 2019 to 2026-10-11, counted by vessel type. Aggregate only, with no vessel identities.
- **Strait of Hormuz:** tanker transits fell from about 45 a day (February 2026) to under 5 a day from March 2026, and all traffic fell about 95%. GFW presence inside the Gulf fell only about 20%, so ships are still there but not transiting.
- **Verdict: no use for scoring individual ships, high value as context.** It's a drift alarm, regional risk context for insurers, and the feed for the geopolitics design in `GEOPOLITICS_AND_DRIFT.md`.

### 11. NGA World Port Index

- 3,807 ports, used to drop ship-to-ship meeting candidates at berths.
- **Verdict: support data.**

### Not downloaded, with reasons

| Source | Why not (yet) |
| --- | --- |
| aisstream.io, Digitraffic | Live only, no history; you asked for historical data first |
| Paris MoU detention PDFs | OpenSanctions carries Tokyo, Black Sea and Abuja detentions with dates; Paris MoU needs PDF parsing. Moderate value, later |
| FCDO sanctions notices | Reasons text for designations: useful for explaining labels, not for prediction |
| Equasis | No bulk access; manual lookups only |
| EEZ boundaries, JWC listed areas | Useful for war-risk views and gap normalisation; next iteration |
