# Pipeline specification

Five stages. Each stage writes its outputs plus a manifest (sources, retrieval dates, row counts, run time). A later stage reads only the outputs of earlier stages, never raw files directly, except Stage 1.

## Stage 1: Ingest and link

**Goal:** three tables keyed on IMO number, each row carrying its source and retrieval date.

### Vessel master table (one row per IMO)

| Column | Meaning |
| --- | --- |
| imo | IMO number (key) |
| name_current | Latest known name |
| ship_type | Tanker type where known |
| build_year | From OFAC or Global Fishing Watch where available |
| flag_current | Latest known flag |
| mmsi_history | Every MMSI the ship used, with start and end dates |
| name_history | Every name, with start and end dates |
| flag_history | Every flag, with start and end dates (from MMSI prefix, OFAC former flags and GFW identity) |
| sources | Which datasets contributed |

### Label table (one row per IMO)

| Column | Meaning |
| --- | --- |
| imo | IMO number |
| uk_designated_on | First UK designation date, or empty |
| eu_listed_on | First EU listing date, or empty |
| us_designated_on | First OFAC designation date, or empty |
| first_designated_on | Earliest of the three |
| uk_batch | The UK designation batch date, for grouping test sets |

Ships never designated stay in the table with empty dates. They are unlabelled, not confirmed clean.

### Event table (one row per behaviour event)

| Column | Meaning |
| --- | --- |
| imo | IMO number |
| event_type | One of the types below |
| start_time, end_time | Event window (UTC) |
| lat, lon | Representative position |
| counterpart_imo | For ship-to-ship meetings, the other ship |
| port_id | For port calls |
| source | AIS feed or Global Fishing Watch |
| confidence | High, medium or low (low when receiver coverage is poor) |

### Event definitions

Every threshold below is a **starting assumption**. Keep them in one config file, tune them in Stage 2, and record final values in `docs/EVALUATION.md`.

| Event type | Definition (starting assumption) |
| --- | --- |
| ais_gap | No position for at least 12 hours while the ship was inside receiver coverage before and after the gap |
| loitering | Speed under 1 knot for at least 12 hours, outside any port area |
| sts_meeting | Two tankers within about 0.5 nautical miles of each other, both under 2 knots, for at least 2 hours |
| port_call | A stop inside a port area; flag it when the port is a Russian export terminal |
| identity_change | A new name, flag or MMSI in static messages |
| spoof_jump | Consecutive positions implying a speed above 50 knots |
| destination_text | Notable destination strings, such as "FOR ORDERS" |

**Processing notes:** sample positions to one every five minutes per ship before extracting events. Map MMSI to IMO using static messages and Global Fishing Watch identity, respecting the time each MMSI was in use.

## Stage 2: Explore

Answer these in order and save the three or four clearest charts to `reports/`:

1. **Coverage:** how many designated ships appear in the behaviour data before their designation date? If very few, widen the corridor or rely more on Global Fishing Watch.
2. **Timing:** when did designations happen? Batches define the test sets.
3. **Contrast:** designated versus never-designated tankers on age, flag, gaps, meetings and Russian port calls.
4. **Lead time:** how many weeks before designation do the signals appear?
5. **Leakage:** which signals appear only after designation? Exclude them.
6. **Data quality:** missing static data, reused MMSIs, gaps caused by poor receiver coverage rather than by the ship.

## Stage 3: Risk signals

**Rule:** for snapshot date T, compute every signal over a look-back window ending the day before T (default 180 days), using only data timestamped before T.

### Feature table (one row per IMO per snapshot date)

| Family | Example features |
| --- | --- |
| Going dark | Count and total hours of AIS gaps; gaps near known transfer areas |
| Ship-to-ship meetings | Count of meetings; count with ships already designated before T |
| Trade pattern | Calls at Russian export terminals; long voyages to Asia |
| Identity churn | Flag changes in 12 months; name changes; flag on the Paris MoU grey or black list |
| Age and condition | Build year; detentions and deficiencies before T |
| Anomalies | Spoofing jumps; "FOR ORDERS" destinations; loitering hours |
| Network (if rights allow) | Shared ports or companies with ships designated before T |

### Rule-based score

Before any ML, combine the signals with hand-set weights into a 0 to 100 score. Document each weight and why. It is the explainable baseline and the fallback if the model disappoints.

## Stage 4: Predict and validate

Fully specified in `docs/EVALUATION.md`.

## Stage 5: Present

Fully specified in `docs/AUDIENCES.md`. Every view reads only from `data/processed/` and shows the source and date of each piece of evidence.

## Where the LLM is used

- Turning sanctions notices and Paris MoU PDFs into tables
- Turning each ship's top SHAP signals into a short narrative that cites only the dated evidence it was given

The LLM never invents facts, scores or dates. If evidence is missing, the narrative says so.
