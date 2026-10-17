"""Stage 1: reduce DMA daily AIS zips to two small Parquet tables per day.

  data/interim/ais_v2/static/<day>.parquet  one row per MMSI-day (Class A and B):
      IMO, name, callsign, ship type(s), destinations, draught range, message counts
  data/interim/ais_v2/pos/<day>.parquet     ALL Class A positions (not only tankers:
      shadow tankers sometimes broadcast a wrong/undefined ship type, and STS
      counterparts need not be typed tankers), first fix per MMSI per
      AIS_RESAMPLE_MINUTES bucket. Tanker selection happens downstream.

The raw zip is never modified; the CSV is extracted to a scratch dir and deleted.
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import duckdb

from sfp import config
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, RAW

AIS_DIR = INTERIM / "ais_v2"
STATIC_DIR = AIS_DIR / "static"
POS_DIR = AIS_DIR / "pos"
STATS = AIS_DIR / "reduce_stats.jsonl"


def reduce_day(zip_path: Path, scratch: Path) -> dict:
    day = zip_path.stem.replace("aisdk-", "")
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    POS_DIR.mkdir(parents=True, exist_ok=True)
    out_s, out_p = STATIC_DIR / f"{day}.parquet", POS_DIR / f"{day}.parquet"
    if out_s.exists() and out_p.exists():
        return {"day": day, "skipped": True}
    lock = AIS_DIR / f".{day}.lock"
    try:  # one reducer per day, even if two loops overlap
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
    except FileExistsError:
        return {"day": day, "skipped": True}
    final_s, final_p = out_s, out_p
    out_s, out_p = out_s.with_suffix(".tmp"), out_p.with_suffix(".tmp")

    tmp = Path(tempfile.mkdtemp(dir=scratch))
    try:
        subprocess.run(["unzip", "-q", "-o", str(zip_path), "-d", str(tmp)], check=True)
        csv = next(tmp.glob("*.csv"))
        con = duckdb.connect()
        con.execute(f"SET memory_limit='6GB'; SET threads=4; SET temp_directory='{tmp}'; SET enable_progress_bar=false;")
        con.execute(f"""
            CREATE VIEW r AS
            SELECT strptime("# Timestamp", '%d/%m/%Y %H:%M:%S') AS ts,
                   "Type of mobile" AS mobile, CAST(MMSI AS VARCHAR) AS mmsi,
                   TRY_CAST(Latitude AS DOUBLE) AS lat, TRY_CAST(Longitude AS DOUBLE) AS lon, "Navigational status" AS nav_status,
                   TRY_CAST(SOG AS DOUBLE) AS sog, TRY_CAST(COG AS DOUBLE) AS cog,
                   NULLIF(IMO, 'Unknown') AS imo_raw, NULLIF(Callsign, 'Unknown') AS callsign,
                   NULLIF(Name, '') AS name, "Ship type" AS ship_type, "Cargo type" AS cargo_type,
                   TRY_CAST(Length AS DOUBLE) AS length, TRY_CAST(Width AS DOUBLE) AS width,
                   TRY_CAST(Draught AS DOUBLE) AS draught,
                   NULLIF(Destination, 'Unknown') AS destination
            FROM read_csv('{csv}', header=true, all_varchar=true, ignore_errors=true)
        """)
        con.execute(f"""
            COPY (
              SELECT mmsi, DATE '{day}' AS day,
                     mode(imo_raw) FILTER (WHERE regexp_matches(imo_raw, '^[0-9]{{7}}$')) AS imo_ais,
                     count(DISTINCT imo_raw) AS n_imo_values,
                     mode(name) AS name, count(DISTINCT name) AS n_names,
                     mode(callsign) AS callsign,
                     mode(ship_type) FILTER (WHERE ship_type NOT IN ('Undefined')) AS ship_type,
                     string_agg(DISTINCT ship_type, '|') AS ship_types,
                     mode(cargo_type) AS cargo_type,
                     max(length) AS length, max(width) AS width,
                     min(draught) AS draught_min, max(draught) AS draught_max,
                     string_agg(DISTINCT upper(trim(destination)), '|') AS destinations,
                     any_value(mobile) AS mobile,
                     count(*) AS n_msgs,
                     count(*) FILTER (WHERE lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
                                       AND NOT (lat = 0 AND lon = 0)) AS n_pos,
                     min(ts) AS first_ts, max(ts) AS last_ts
              FROM r WHERE mobile IN ('Class A', 'Class B')
              GROUP BY mmsi
            ) TO '{out_s}' (FORMAT parquet)
        """)
        con.execute(f"""
            COPY (
              WITH pos AS (
                SELECT mmsi, ts, lat, lon, sog, cog, nav_status, draught,
                       time_bucket(INTERVAL '{config.AIS_RESAMPLE_MINUTES} minutes', ts) AS b
                FROM r
                WHERE mobile = 'Class A' AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
                  AND NOT (lat = 0 AND lon = 0)
              )
              -- first fix per (mmsi, bucket); GROUP BY + arg_min avoids a DuckDB 1.5
              -- optimizer crash seen with QUALIFY row_number() on this query
              SELECT mmsi, min(ts) AS ts, arg_min(lat, ts) AS lat, arg_min(lon, ts) AS lon,
                     arg_min(sog, ts) AS sog, arg_min(cog, ts) AS cog,
                     arg_min(nav_status, ts) AS nav_status, arg_min(draught, ts) AS draught
              FROM pos GROUP BY mmsi, b
              ORDER BY mmsi, ts
            ) TO '{out_p}' (FORMAT parquet)
        """)
        n_s = con.execute(f"SELECT count(*) FROM read_parquet('{out_s}')").fetchone()[0]
        n_p, n_m = con.execute(f"SELECT count(*), count(DISTINCT mmsi) FROM read_parquet('{out_p}')").fetchone()
        con.close()
        os.replace(out_s, final_s)
        os.replace(out_p, final_p)
        st = {"day": day, "static_rows": n_s, "pos_rows": n_p, "pos_mmsi": n_m}
        import json
        with open(STATS, "a") as f:
            f.write(json.dumps(st) + "\n")
        return st
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        lock.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", required=True, help="dir for temporary CSV extraction")
    a = ap.parse_args()
    zips = sorted((RAW / "dma_ais").glob("aisdk-*.zip"))
    Path(a.scratch).mkdir(parents=True, exist_ok=True)
    for z in zips:
        try:
            s = reduce_day(z, Path(a.scratch))
        except Exception as e:  # one bad day must not block the others
            print(f"FAILED {z.name}: {e.__class__.__name__}: {str(e)[:200]}", flush=True)
            continue
        if not s.get("skipped"):
            print(s, flush=True)
    done = sorted(p.stem for p in POS_DIR.glob("*.parquet"))
    write_manifest(AIS_DIR / "ais.manifest.json",
                   inputs=[f"dma_ais/aisdk-{d}.zip" for d in done],
                   outputs={"days_reduced": len(done), "per_day_stats": "ais_v2/reduce_stats.jsonl"},
                   notes=f"v2: all Class A positions; resample={config.AIS_RESAMPLE_MINUTES}min")


if __name__ == "__main__":
    main()
