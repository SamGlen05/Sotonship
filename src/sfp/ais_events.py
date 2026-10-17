"""Stage 1: per-day behaviour events from reduced AIS (data/interim/ais_v2).

Outputs, one file per AIS day (computed once, cached):
  data/interim/ais_v2/shipday/<day>.parquet  one row per tanker MMSI-day
  data/interim/ais_v2/sts/<day>.parquet      candidate ship-to-ship meetings (tanker pairs)

Tankers = AIS ship type 'Tanker' that day. Every threshold comes from config.py.
"""
import duckdb

from sfp import config
from sfp.paths import INTERIM, RAW

AIS = INTERIM / "ais_v2"
HAV = """(2 * 6371.0 * asin(sqrt(pow(sin(radians({la2} - {la1}) / 2), 2)
          + cos(radians({la1})) * cos(radians({la2})) * pow(sin(radians({lo2} - {lo1}) / 2), 2)))) / 1.852"""


def day_events(day: str) -> None:
    out_s, out_t = AIS / "shipday" / f"{day}.parquet", AIS / "sts" / f"{day}.parquet"
    out_n = AIS / "near" / f"{day}.parquet"
    if out_s.exists() and out_t.exists() and out_n.exists():
        return
    for o in (out_s, out_t, out_n):
        o.parent.mkdir(exist_ok=True)
    la0, la1, lo0, lo1 = config.CORE_COVERAGE_BOX
    rx = "|".join(config.RUSSIAN_PORT_DEST_PATTERNS)
    notable = "|".join(config.NOTABLE_DESTINATIONS)
    tank = ",".join(f"'{t}'" for t in config.TANKER_SHIP_TYPES)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"""
      CREATE TEMP TABLE st AS SELECT * FROM '{AIS}/static/{day}.parquet'
      WHERE mobile = 'Class A' AND ship_type IN ({tank});
      CREATE TEMP TABLE p AS
      SELECT p.mmsi, p.ts, p.lat, p.lon, p.sog, p.nav_status, p.draught,
             lag(p.ts) OVER w AS pts, lag(p.lat) OVER w AS plat, lag(p.lon) OVER w AS plon
      FROM '{AIS}/pos/{day}.parquet' p JOIN st USING (mmsi)
      WINDOW w AS (PARTITION BY p.mmsi ORDER BY p.ts);
    """)
    dist = HAV.format(la1="plat", la2="lat", lo1="plon", lo2="lon")
    in_core = lambda a, o: f"({a} BETWEEN {la0} AND {la1} AND {o} BETWEEN {lo0} AND {lo1})"  # noqa: E731
    con.execute(f"""
      COPY (
        WITH x AS (
          SELECT *, epoch(ts - pts) / 3600.0 AS dt_h, {dist} AS d_nm FROM p
        ), a AS (
          SELECT mmsi, count(*) AS n_fixes,
                 epoch(max(ts) - min(ts)) / 3600.0 AS hours_span,
                 max(dt_h) AS max_gap_h,
                 count(*) FILTER (WHERE dt_h >= {config.AIS_INTRADAY_GAP_HOURS}
                     AND {in_core('lat', 'lon')} AND {in_core('plat', 'plon')}
                     AND d_nm / dt_h < {config.GAP_MAX_IMPLIED_KN}) AS n_gaps_core,
                 count(*) FILTER (WHERE sog < {config.LOITER_SPEED_KN}
                     AND nav_status NOT IN ('Moored', 'At anchor')) * {config.AIS_RESAMPLE_MINUTES} / 60.0 AS slow_hours_underway,
                 count(*) FILTER (WHERE nav_status = 'At anchor') * {config.AIS_RESAMPLE_MINUTES} / 60.0 AS anchor_hours,
                 count(*) FILTER (WHERE dt_h > 0 AND d_nm / dt_h > {config.SPOOF_SPEED_KN}) AS n_spoof_jumps,
                 count(*) FILTER (WHERE plon < {config.BALTIC_SIDE_LON} AND lon >= {config.BALTIC_SIDE_LON}) AS n_east_cross,
                 count(*) FILTER (WHERE plon >= {config.BALTIC_SIDE_LON} AND lon < {config.BALTIC_SIDE_LON}) AS n_west_cross,
                 arg_max(lat, ts) AS last_lat, arg_max(lon, ts) AS last_lon, arg_max(sog, ts) AS last_sog,
                 max(ts) AS last_ts, avg(lon) AS mean_lon
          FROM x GROUP BY mmsi
        )
        SELECT st.mmsi, DATE '{day}' AS day, st.imo_ais AS imo, st.name, st.callsign, st.ship_type,
               st.length, st.width, st.draught_min, st.draught_max, st.destinations, st.n_names,
               regexp_matches(coalesce(regexp_replace(st.destinations, '[^A-Z0-9| ]', ' ', 'g'), ''), '{rx}') AS dest_russian,
               regexp_matches(coalesce(st.destinations, ''), '{notable}') AS dest_notable,
               st.destinations IS NULL AS dest_missing,
               st.draught_max IS NULL AS draught_missing,
               a.* EXCLUDE (mmsi)
        FROM st LEFT JOIN a USING (mmsi)
      ) TO '{out_s}' (FORMAT parquet)
    """)
    con.execute(f"""
      CREATE TEMP TABLE ports AS
      SELECT "Main Port Name" AS port, Latitude AS plat, Longitude AS plon
      FROM read_csv('{RAW}/nga_wpi/UpdatedPub150.csv', header=true)
      WHERE Latitude BETWEEN 50 AND 62 AND Longitude BETWEEN 0 AND 25
    """)
    d2 = HAV.format(la1="a.lat", la2="b.lat", lo1="a.lon", lo2="b.lon")
    dport = HAV.format(la1="m.lat", la2="ports.plat", lo1="m.lon", lo2="ports.plon")
    con.execute(f"""
      COPY (
        WITH q AS (
          SELECT mmsi, lat, lon, sog, time_bucket(INTERVAL '{config.AIS_RESAMPLE_MINUTES} minutes', ts) AS b
          FROM p WHERE sog < {config.STS_SPEED_KN} AND coalesce(nav_status, '') <> 'Moored'
        ), pairs AS (
          SELECT a.mmsi AS mmsi_a, b.mmsi AS mmsi_b, a.b, a.lat, a.lon
          FROM q a JOIN q b ON a.b = b.b AND a.mmsi < b.mmsi
               AND abs(a.lat - b.lat) < 0.02 AND abs(a.lon - b.lon) < 0.04
          WHERE {d2} < {config.STS_DISTANCE_NM}
        )
        , m AS (
          SELECT DATE '{day}' AS day, mmsi_a, mmsi_b, count(*) * {config.AIS_RESAMPLE_MINUTES} / 60.0 AS hours,
                 avg(lat) AS lat, avg(lon) AS lon
          FROM pairs GROUP BY 1, 2, 3
          HAVING count(*) * {config.AIS_RESAMPLE_MINUTES} / 60.0 >= {config.STS_MIN_HOURS}
        )
        SELECT m.* FROM m
        WHERE NOT EXISTS (SELECT 1 FROM ports WHERE {dport} * 1.852 < {config.PORT_EXCLUSION_KM})
      ) TO '{out_t}' (FORMAT parquet)
    """)
    # looser co-location: lingering near another tanker (anchorages, drifting areas)
    con.execute(f"""
      COPY (
        WITH q AS (
          SELECT mmsi, lat, lon, time_bucket(INTERVAL '{config.AIS_RESAMPLE_MINUTES} minutes', ts) AS b
          FROM p WHERE sog < {config.NEAR_SPEED_KN} AND coalesce(nav_status, '') <> 'Moored'
        ), pairs AS (
          SELECT a.mmsi AS mmsi_a, b.mmsi AS mmsi_b, a.lat, a.lon
          FROM q a JOIN q b ON a.b = b.b AND a.mmsi < b.mmsi
               AND abs(a.lat - b.lat) < 0.05 AND abs(a.lon - b.lon) < 0.09
          WHERE {d2} < {config.NEAR_DISTANCE_NM}
        ), m AS (
          SELECT DATE '{day}' AS day, mmsi_a, mmsi_b, count(*) * {config.AIS_RESAMPLE_MINUTES} / 60.0 AS hours,
                 avg(lat) AS lat, avg(lon) AS lon
          FROM pairs GROUP BY 1, 2, 3
          HAVING count(*) * {config.AIS_RESAMPLE_MINUTES} / 60.0 >= {config.NEAR_MIN_HOURS}
        )
        SELECT m.* FROM m
        WHERE NOT EXISTS (SELECT 1 FROM ports WHERE {dport} * 1.852 < {config.PORT_EXCLUSION_KM})
      ) TO '{out_n}' (FORMAT parquet)
    """)
    con.close()


def main():
    days = sorted(p.stem for p in (AIS / "pos").glob("*.parquet"))
    for d in days:
        day_events(d)
    print("shipday days:", len(list((AIS / "shipday").glob("*.parquet"))))


if __name__ == "__main__":
    main()
