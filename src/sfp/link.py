"""Stage 1: link everything on IMO.

Outputs (data/interim/):
  mid_flags.parquet      MID (first 3 MMSI digits) -> flag country
  mmsi_imo.parquet       time-bounded MMSI->IMO links seen in AIS static data
  vessel_master.parquet  one row per IMO, static attributes with their source
  ais_days.parquet       one row per IMO per AIS day in the Danish corridor: presence,
                         destinations, simple intra-day behaviour (Stage 1 events, coarse)

Leakage notes:
  * GUR is a single scrape (2026-06-24) with no per-entry dates. We take only
    time-invariant attributes (build year, vessel type, size). Its sanction flags,
    'shadow_fleet' flag, current flag and port visits are NOT used as features.
  * OpenSanctions maritime CSV has no dates; used for cross-checks only.
"""
import re

import duckdb
import numpy as np
import pandas as pd

from sfp import config
from sfp.labels import clean_imo
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, RAW


def mid_table() -> pd.DataFrame:
    t = pd.read_html(RAW / "itu_mid" / "wikipedia_maritime_identification_digits.html")[0]
    rows = [(m, c) for c, codes in zip(t["Country"], t["Codes"].astype(str))
            for m in re.findall(r"\b\d{3}\b", codes)]
    df = pd.DataFrame(rows, columns=["mid", "flag_formal"]).drop_duplicates("mid")
    df["flag_from_mmsi"] = df["flag_formal"].map(short_flag)
    return df


_FLAG_FIX = {"Gabonese Republic": "Gabon", "Togolese Republic": "Togo",
             "Russian Federation": "Russia", "Islamic Republic of Iran": "Iran"}


def short_flag(name: str) -> str:
    """'Bahamas (Commonwealth of the)' -> 'Bahamas'; strip accents."""
    import unicodedata
    n = re.sub(r"\s*\(.*?\)", "", str(name)).strip()
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    return _FLAG_FIX.get(n, n)


def mmsi_imo_links() -> pd.DataFrame:
    """MMSI is a time-bounded attribute of an IMO, never a key."""
    return duckdb.sql(f"""
        SELECT imo_ais AS imo, mmsi, min(day) AS first_day, max(day) AS last_day,
               count(*) AS n_days, mode(name) AS name, mode(ship_type) AS ship_type
        FROM read_parquet('{INTERIM}/ais_v2/static/*.parquet')
        WHERE imo_ais IS NOT NULL
        GROUP BY 1, 2
    """).df().assign(imo=lambda d: d["imo"].map(clean_imo)).dropna(subset=["imo"])


def vessel_master(links: pd.DataFrame, mids: pd.DataFrame) -> pd.DataFrame:
    uk = pd.read_parquet(INTERIM / "uk_vessels.parquet")
    eu = pd.read_parquet(INTERIM / "eu_vessels.parquet")
    of = pd.read_parquet(INTERIM / "ofac_vessels.parquet")
    gur = duckdb.sql(f"""SELECT imo, name, vessel_type, build_year, dwt, gross_tonnage
                         FROM '{RAW}/gur/vessels.parquet'""").df()
    gur["imo"] = gur["imo"].map(clean_imo)

    ais = (links.sort_values("last_day").groupby("imo")
           .agg(name_ais=("name", "last"), ship_type_ais=("ship_type", "last"),
                mmsi_list=("mmsi", lambda s: "|".join(sorted(set(s)))),
                n_mmsi=("mmsi", "nunique"), ais_last_mmsi=("mmsi", "last")))
    ais["flag_from_mmsi"] = ais["ais_last_mmsi"].str[:3].map(mids.set_index("mid")["flag_from_mmsi"])

    m = pd.DataFrame(index=pd.Index(sorted(set(uk.imo.dropna()) | set(eu.imo.dropna())
                                           | set(of.imo.dropna()) | set(gur.imo.dropna())
                                           | set(ais.index)), name="imo"))
    m = m.join(uk.dropna(subset=["imo"]).drop_duplicates("imo").set_index("imo")
               [["name", "ship_type", "build_year", "flag", "previous_flags"]].add_prefix("uk_"))
    m = m.join(of.dropna(subset=["imo"]).drop_duplicates("imo").set_index("imo")
               [["name", "vessel_type", "build_year", "flag", "former_flags"]].add_prefix("ofac_"))
    m = m.join(gur.dropna(subset=["imo"]).drop_duplicates("imo").set_index("imo")
               [["name", "vessel_type", "build_year", "dwt"]].add_prefix("gur_"))
    m = m.join(eu.dropna(subset=["imo"]).drop_duplicates("imo").set_index("imo")[["name"]].add_prefix("eu_"))
    m = m.join(ais)

    m["name_current"] = m["name_ais"].fillna(m["uk_name"]).fillna(m["ofac_name"]).fillna(m["gur_name"]).fillna(m["eu_name"])
    m["build_year"] = m["ofac_build_year"].fillna(m["uk_build_year"]).fillna(m["gur_build_year"])
    m["build_year_source"] = np.select(
        [m["ofac_build_year"].notna(), m["uk_build_year"].notna(), m["gur_build_year"].notna()],
        ["OFAC", "UK", "GUR"], default=None)
    m["ship_type"] = m["uk_ship_type"].fillna(m["ofac_vessel_type"]).fillna(m["gur_vessel_type"]).fillna(m["ship_type_ais"])
    m["is_tanker"] = m["ship_type"].fillna("").str.contains("tanker", case=False) | m["ship_type_ais"].eq("Tanker")
    m["sources"] = (m[["uk_name", "ofac_name", "gur_name", "eu_name", "name_ais"]].notna()
                    .apply(lambda r: "|".join(k for k, v in zip(["UK", "OFAC", "GUR", "EU", "DMA_AIS"], r) if v), axis=1))
    return m.reset_index()


def ais_days(links: pd.DataFrame) -> pd.DataFrame:
    """Per IMO per day in the Danish corridor. Coarse, single-day behaviour only."""
    con = duckdb.connect()
    con.register("links", links[["imo", "mmsi", "first_day", "last_day"]])
    rx = "|".join(config.RUSSIAN_PORT_DEST_PATTERNS)
    notable = "|".join(re.escape(d) for d in config.NOTABLE_DESTINATIONS)
    return con.execute(f"""
        WITH s AS (
          SELECT s.*, l.imo FROM read_parquet('{INTERIM}/ais_v2/static/*.parquet') s
          JOIN links l ON s.mmsi = l.mmsi AND s.day BETWEEN l.first_day AND l.last_day
        ),
        p AS (
          SELECT mmsi, CAST(ts AS DATE) AS day, ts, lat, lon, sog,
                 lag(ts) OVER w AS prev_ts, lag(lat) OVER w AS plat, lag(lon) OVER w AS plon
          FROM read_parquet('{INTERIM}/ais_v2/pos/*.parquet')
          WINDOW w AS (PARTITION BY mmsi, CAST(ts AS DATE) ORDER BY ts)
        ),
        pa AS (
          SELECT mmsi, day, count(*) AS n_fixes,
                 max(epoch(ts - prev_ts)) / 3600.0 AS max_gap_h,
                 count(*) FILTER (WHERE epoch(ts - prev_ts) >= {config.AIS_INTRADAY_GAP_HOURS} * 3600) AS n_gaps_intraday,
                 count(*) FILTER (WHERE sog < {config.LOITER_SPEED_KN}) * {config.AIS_RESAMPLE_MINUTES} / 60.0 AS slow_hours,
                 count(*) FILTER (WHERE epoch(ts - prev_ts) > 0 AND
                     (6371.0 * 2 * asin(sqrt(pow(sin(radians(lat - plat) / 2), 2) + cos(radians(plat)) * cos(radians(lat)) * pow(sin(radians(lon - plon) / 2), 2)))) / 1.852
                     / (epoch(ts - prev_ts) / 3600.0) > {config.SPOOF_SPEED_KN}) AS n_spoof_jumps,
                 avg(lon) AS mean_lon, min(lon) AS min_lon, max(lon) AS max_lon
          FROM p GROUP BY 1, 2
        )
        SELECT s.imo, s.day, s.mmsi, s.name, s.ship_type, s.destinations,
               s.draught_min, s.draught_max, s.n_msgs, s.n_names, s.n_imo_values,
               regexp_matches(coalesce(regexp_replace(s.destinations, '[^A-Z0-9| ]', ' ', 'g'), ''), '{rx}') AS dest_russian,
               regexp_matches(coalesce(s.destinations, ''), '{notable}') AS dest_notable,
               pa.n_fixes, pa.max_gap_h, pa.n_gaps_intraday, pa.slow_hours, pa.n_spoof_jumps,
               pa.mean_lon, pa.min_lon < {config.BALTIC_SIDE_LON} AND pa.max_lon > {config.BALTIC_SIDE_LON} AS crossed_straits
        FROM s LEFT JOIN pa ON s.mmsi = pa.mmsi AND s.day = pa.day
    """).df()


def main():
    mids = mid_table()
    links = mmsi_imo_links()
    master = vessel_master(links, mids)
    days = ais_days(links)
    outs = {"mid_flags": mids, "mmsi_imo": links, "vessel_master": master, "ais_days": days}
    for k, v in outs.items():
        v.to_parquet(INTERIM / f"{k}.parquet", index=False)
        print(k, v.shape)
    write_manifest(INTERIM / "link.manifest.json",
                   inputs=["itu_mid/wikipedia_maritime_identification_digits.html", "gur/vessels.parquet"],
                   outputs={k: len(v) for k, v in outs.items()},
                   notes="AIS inputs listed in ais.manifest.json; label inputs in labels.manifest.json")


if __name__ == "__main__":
    main()
