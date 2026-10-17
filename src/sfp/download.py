"""Stage 1 download helpers. Each file is written once to data/raw/ with a
sidecar manifest entry (URL, retrieval time UTC, size, sha256)."""
import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from sfp.paths import RAW

MANIFEST = RAW / "manifest.jsonl"
UA = {"User-Agent": "shadow-fleet-predictor/0.1 (SotonShip 2026 hackathon; research use)"}


def fetch(url: str, dest: Path, overwrite: bool = False) -> Path:
    """Download url to dest once. Never overwrites unless asked (raw is read-only)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not overwrite:
        print(f"skip (exists) {dest.relative_to(RAW)}", flush=True)
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(8):  # resume partial downloads with HTTP Range
        have = tmp.stat().st_size if tmp.exists() else 0
        hdr = dict(UA, **({"Range": f"bytes={have}-"} if have else {}))
        try:
            with requests.get(url, headers=hdr, stream=True, timeout=120) as r:
                if r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                mode = "ab" if (have and r.status_code == 206) else "wb"
                with open(tmp, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            print(f"retry {attempt + 1} {dest.name}: {e.__class__.__name__}", flush=True)
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"gave up on {url}")
    h = hashlib.sha256()
    with open(tmp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    tmp.rename(dest)
    entry = {
        "file": str(dest.relative_to(RAW)),
        "url": url,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": dest.stat().st_size,
        "sha256": h.hexdigest(),
    }
    with open(MANIFEST, "a") as m:
        m.write(json.dumps(entry) + "\n")
    print(f"ok {entry['file']} {entry['bytes']/1e6:.1f} MB", flush=True)
    return dest


def dma_ais_keys() -> dict[str, str]:
    """Map YYYY-MM-DD -> object key. Older days live under a year prefix
    (e.g. 2025/aisdk-2025-01-01.zip); recent days sit at the bucket root."""
    import re
    import urllib.parse
    base = "http://aisdata.ais.dk.s3.eu-central-1.amazonaws.com/?list-type=2"
    keys, tok = {}, None
    while True:
        r = requests.get(base + (f"&continuation-token={urllib.parse.quote(tok)}" if tok else ""), timeout=60)
        for k in re.findall(r"<Key>([^<]+)</Key>", r.text):
            m = re.search(r"aisdk-(\d{4}-\d{2}-\d{2})\.zip$", k)
            if m:
                keys[m.group(1)] = k
        m = re.search(r"<NextContinuationToken>([^<]+)<", r.text)
        if not m:
            return keys
        tok = m.group(1)


def sample_days() -> list[str]:
    import pandas as pd
    from sfp import config
    return [d.strftime("%Y-%m-%d") for d in
            pd.date_range(config.AIS_SAMPLE_START, config.AIS_SAMPLE_END, freq=config.AIS_SAMPLE_FREQ)]


def dma_ais_days(days: list[str], workers: int = 3) -> None:
    keys = dma_ais_keys()

    def one(d):
        try:
            if d not in keys:
                raise FileNotFoundError(f"no DMA file for {d}")
            fetch(f"http://aisdata.ais.dk/{keys[d]}", RAW / "dma_ais" / f"aisdk-{d}.zip")
        except Exception as e:  # keep going on one bad day
            print(f"FAIL {d}: {e}", file=sys.stderr, flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, days))


OS_DATASETS = ["ua_war_sanctions", "ca_dfatd_sema_sanctions", "ch_seco_sanctions", "au_dfat_sanctions",
               "nz_russia_sanctions", "tokyo_mou_detention", "black_sea_mou_detention", "abuja_mou_detention",
               "paris_mou_banned"]
SMALL_SOURCES = {
    "uk/UK-Sanctions-List.csv": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv",
    "uk/UK-Sanctions-List.xml": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
    "eu/ImportversionListOfEUDesignatedVessels240726.csv":
        "https://www.dma.dk/Media/639204766104358805/ImportversionListOfEUDesignatedVessels240726.csv",
    "ofac/SDN_ADVANCED.XML": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML",
    "ofac/SDN.CSV": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
    "opensanctions/maritime.csv": "https://data.opensanctions.org/datasets/latest/maritime/maritime.csv",
    "itu_mid/wikipedia_maritime_identification_digits.html": "https://en.wikipedia.org/wiki/Maritime_identification_digits",
    "nga_wpi/UpdatedPub150.csv": "https://msi.nga.mil/api/publications/download?type=view&key=16920959/SFH00000/UpdatedPub150.csv",
    "naturalearth/ne_10m_land.geojson":
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson",
    **{f"gur/{c.split('/')[-1]}": f"https://data.source.coop/cholmes/gur-shadow-fleet/{c}"
       for c in ["vessels/vessels.parquet", "ports/ports.parquet", "visits/visits.parquet",
                 "companies/companies.parquet", "RIGHTS.md", "README.md"]},  # masters (personal data) never fetched
    **{f"opensanctions/{d}/entities.ftm.json": f"https://data.opensanctions.org/datasets/latest/{d}/entities.ftm.json"
       for d in OS_DATASETS},
}


PORTWATCH = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/"
             "Daily_Chokepoints_Data/FeatureServer/0/query")


def portwatch() -> None:
    """IMF PortWatch daily chokepoint transits (aggregate, no vessel ids), all pages."""
    out = RAW / "imf_portwatch" / "daily_chokepoints.json"
    if out.exists():
        print("skip (exists) imf_portwatch/daily_chokepoints.json")
        return
    rows, off = [], 0
    while True:
        r = requests.get(PORTWATCH, params={"where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json",
                                            "resultOffset": off, "resultRecordCount": 1000, "orderByFields": "ObjectId"},
                         headers=UA, timeout=120)
        r.raise_for_status()
        j = r.json()
        feats = j.get("features", [])
        rows += [f["attributes"] for f in feats]
        if not feats or not j.get("exceededTransferLimit"):
            break
        off += len(feats)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows))
    with open(MANIFEST, "a") as m:
        m.write(json.dumps({"file": str(out.relative_to(RAW)), "url": PORTWATCH, "rows": len(rows),
                            "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
    print(f"ok imf_portwatch {len(rows)} rows")


def small_sources() -> None:
    """Sanctions lists, OpenSanctions, GUR, reference tables. Files already present are kept
    (raw data is written once); delete a file deliberately to refresh it."""
    for rel, url in SMALL_SOURCES.items():
        try:
            fetch(url, RAW / rel)
        except Exception as e:
            print(f"FAIL {rel}: {e}", file=sys.stderr, flush=True)
    portwatch()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ais-days", nargs="+", help="YYYY-MM-DD dates of DMA AIS daily files")
    ap.add_argument("--ais-plan", action="store_true", help="download config.AIS_SAMPLE_* days")
    ap.add_argument("--small", action="store_true", help="sanctions lists, OpenSanctions, GUR, reference tables")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if a.small:
        small_sources()
    if a.ais_days:
        dma_ais_days(a.ais_days, a.workers)
    if a.ais_plan:
        # test-period days first (newest first), then training history
        days = sorted(sample_days(), reverse=True)
        dma_ais_days(days, a.workers)
