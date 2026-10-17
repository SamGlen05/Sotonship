# Data register

Every dataset the project uses, with its role, access route and licence. Fill in **Retrieved** with the date each file was downloaded, and update the row whenever it is downloaded again. The README's data section is built from this file.

Priority: **Must** = needed for the weekend build. **Should** = adds accuracy. **Nice** = context or demo only.

Join key everywhere: **IMO number**.

## Labels: which ships were sanctioned, and when

| Dataset | Role | Fields we need | Source | Access and licence | Priority | Retrieved |
| --- | --- | --- | --- | --- | --- | --- |
| UK Sanctions List | Primary label | Unique ID, ship name, IMO number, date designated, regime | https://www.gov.uk/government/publications/the-uk-sanctions-list (format guide: https://www.gov.uk/guidance/format-guide-for-the-uk-sanctions-list) | Free CSV/XML. The only UK source since the OFSI Consolidated List closed on 28 January 2026 | Must | |
| EU Annex XLII vessel list | Secondary label | IMO number, date listed | https://www.dma.dk/growth-and-framework-conditions/maritime-sanctions/general-information/eu-vessel-designations | Free, published by the Danish Maritime Authority. Check the listing date per vessel | Must | |
| OFAC SDN list (vessels) | Secondary label and features | IMO, vessel type, flag, **former flags**, build year, program | https://sanctionssearch.ofac.treas.gov/ (download link on that page) | Free download | Must | |
| GUR War&Sanctions shadow-fleet catalogue | Context and features | Vessel records, ports visited, companies | https://data.source.coop/cholmes/gur-shadow-fleet/README.md (original: https://war-sanctions.gur.gov.ua/en/transport/shadow-fleet) | Parquet mirror. No open licence asserted. **Do not use the named-captains table (personal data).** Treat entries without dates as leakage risks | Should | |
| OpenSanctions | Cross-check of all lists | Merged vessel entities | https://www.opensanctions.org/ | Free for non-commercial use only (CC BY-NC) | Nice | |
| FCDO sanctions notices | Designation batches and stated reasons | Batch date, ships added, reasons text | https://www.gov.uk/guidance/russia-list-of-designations-and-sanctions-notices | Free PDFs. An LLM can extract reasons into a table | Should | |

## Behaviour: where ships went and what they did

| Dataset | Role | Fields we need | Source | Access and licence | Priority | Retrieved |
| --- | --- | --- | --- | --- | --- | --- |
| Danish Maritime Authority historical AIS | Raw positions in the corridor | MMSI, IMO (static messages), timestamp, position, speed, course, ship type, destination, name | https://www.dma.dk/safety-at-sea/navigational-information/ais-data | Free CSV downloads. Large files: start with one month | Must | |
| Global Fishing Watch API | Worldwide events and identity history | AIS gaps, encounters, loitering, port visits; vessel identity, flag and ownership history | https://api-doc.globalfishingwatch.org/ | Free API key. **Non-commercial use only**; attribution required | Must | |
| Digitraffic (Finland) | Gulf of Finland AIS and port calls, near Russian export ports | Positions, vessel metadata, port calls | https://digitraffic.fi/en/marine-traffic | Open data, free; follow its licence terms and send a `Digitraffic-User` header. Live only: history exists only if we record it | Should | |
| aisstream.io | Live global AIS for the demo | Positions and static data by bounding box | https://aisstream.io/documentation | Free key, beta, sometimes unstable. Live only | Should | |
| IMF PortWatch | Chokepoint and port traffic context | Daily transits by vessel type | https://portwatch.imf.org/ | Free; published weekly with a lag | Nice | |

## Identity and quality

| Dataset | Role | Fields we need | Source | Access and licence | Priority | Retrieved |
| --- | --- | --- | --- | --- | --- | --- |
| ITU maritime identification digits (MID) | Flag from the first three digits of an MMSI | MID, country | Find the official ITU MID table | Public | Must | |
| Paris MoU detention lists | Port inspection detentions and deficiencies | IMO, date, port, flag at the time, deficiencies | https://parismou.org/ (monthly PDF lists) | Free PDFs; an LLM can parse them into rows | Should | |
| Paris MoU white, grey and black flag lists | Flag-state performance | Flag, list colour, year | https://parismou.org/ | Free, yearly (1 July) | Should | |
| Equasis | Owner, manager, P&I insurer, flag history | Per ship, by hand | https://www.equasis.org/ | Free account. **No bulk or automated downloads.** Manual lookups for demo ships only | Nice | |
| KSE Institute oil-spill insurance report | P&I coverage context | Report figures | https://sanctions.kse.ua/?p=12305 | Public report | Nice | |

## Geography and context

| Dataset | Role | Fields we need | Source | Access and licence | Priority | Retrieved |
| --- | --- | --- | --- | --- | --- | --- |
| Port locations | Russian export terminals and frequent transfer areas | Port name, coordinates, country | GUR ports table, or a public port index | Check each source's terms | Must | |
| Maritime boundaries (EEZ) | Which country's waters an event happened in | Boundary polygons | Find an open EEZ dataset | Check the licence | Nice | |
| JWC listed areas | Official war-risk zones | Area boundaries, circular date | https://lmalloyds.com/ (JWLA circulars) | Public | Nice | |

## Known gaps

- **Ownership and management changes** are strong signals but cannot be collected legally at scale for free. Use identity churn (flag, name, MMSI changes) instead.
- **Coverage bias:** corridor AIS only sees ships that pass through the corridor. Report this in every result.
- **Label noise:** ships never designated are not confirmed innocent. Some high-scoring "false positives" may be correct.
