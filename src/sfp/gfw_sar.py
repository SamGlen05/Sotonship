"""Satellite radar (Sentinel-1 SAR) vessel detections from Global Fishing Watch, by area.

A SAR detection is a hull seen on a radar image. GFW matches each detection to AIS;
an UNMATCHED detection is a vessel that was not broadcasting AIS at that place and
time ("dark"). Detections cover all vessel types above roughly 15-20 m and depend on
how often Sentinel-1 passed over, so trends matter more than absolute counts.
Non-commercial licence. The API limits SAR queries to 366 days, so windows are split.

Writes data/raw/gfw/sar/*.json (raw, once) and data/interim/gfw_sar.parquet,
data/interim/gfw_sar_cells.parquet.
"""
import json
import time

import pandas as pd

from sfp.gfw import BASE, _log, _session
from sfp.gfw_region import _geo, report
from sfp.manifest import write_manifest
from sfp.paths import INTERIM, RAW

OUT = RAW / "gfw" / "sar"
AREAS = {  # lon_min, lat_min, lon_max, lat_max
    "Strait of Hormuz": (55.8, 25.6, 57.2, 27.0),
    "Gulf of Oman": (56.5, 22.5, 60.5, 25.6),
    "Persian Gulf (west of Hormuz)": (48.0, 24.0, 55.8, 30.0),
    "Bab el-Mandeb": (42.6, 11.8, 44.2, 13.2),
    "Red Sea (central)": (36.5, 16.0, 41.0, 22.0),
    "Kerch Strait": (36.2, 44.8, 37.2, 45.6),
    "Gulf of Finland (Primorsk / Ust-Luga)": (26.5, 59.4, 30.5, 60.8),
    "Danish straits": (10.0, 54.4, 13.0, 57.8),
    "Laconian Gulf (Greece)": (22.3, 36.3, 23.2, 36.9),
}
WINDOWS = [("2024-10-01", "2025-10-01"), ("2025-10-01", "2026-10-01")]
CELL_AREA = ("Hormuz and Gulf of Oman", (54.5, 23.0, 60.5, 27.5))
CELL_WINDOW = ("2026-04-01", "2026-10-01")


def _rows(d):
    return list((d.get("entries") or [{}])[0].values() or [[]])[0] or []


def fetch(s):
    for name, b in AREAS.items():
        for a, z in WINDOWS:
            for matched in ("true", "false"):
                path = OUT / f"{name.split(' (')[0].replace(' ', '_').lower()}_{a}_{matched}.json"
                if path.exists():
                    continue
                params = {"format": "JSON", "group-by": "FLAG", "temporal-resolution": "MONTHLY",
                          "spatial-aggregation": "true", "datasets[0]": "public-global-sar-presence:latest",
                          "date-range": f"{a},{z}", "filters[0]": f"matched='{matched}'"}
                d = report(s, params, _geo(b))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"area": name, "bbox": b, "matched": matched, "data": d}))
                _log(path, f"{BASE}/4wings/report sar {name} {a},{z} matched={matched}")
                print(f"sar {name} {a} matched={matched}: {len(_rows(d))} rows", flush=True)
                time.sleep(1)
    path = OUT / f"cells_{CELL_WINDOW[0]}.json"
    if not path.exists():
        params = {"format": "JSON", "group-by": "FLAG", "temporal-resolution": "ENTIRE", "spatial-resolution": "HIGH",
                  "datasets[0]": "public-global-sar-presence:latest", "date-range": ",".join(CELL_WINDOW),
                  "filters[0]": "matched='false'"}
        d = report(s, params, _geo(CELL_AREA[1]))
        path.write_text(json.dumps({"area": CELL_AREA[0], "bbox": CELL_AREA[1], "window": CELL_WINDOW, "data": d}))
        _log(path, f"{BASE}/4wings/report sar cells {CELL_AREA[0]} {CELL_WINDOW}")
        print(f"sar cells: {len(_rows(d))}", flush=True)


def tables():
    rows = []
    for p in OUT.glob("*_true.json"), OUT.glob("*_false.json"):
        for f in p:
            j = json.loads(f.read_text())
            for r in _rows(j["data"]):
                rows.append({"area": j["area"], "matched": j["matched"] == "true", "month": r["date"],
                             "detections": r.get("detections", 0)})
    df = pd.DataFrame(rows).groupby(["area", "month", "matched"], as_index=False)["detections"].sum()
    j = json.loads((OUT / f"cells_{CELL_WINDOW[0]}.json").read_text())
    cells = pd.DataFrame([{"lat": r["lat"], "lon": r["lon"], "detections": r["detections"]} for r in _rows(j["data"])])
    cells = cells.groupby(["lat", "lon"], as_index=False)["detections"].sum()
    df.to_parquet(INTERIM / "gfw_sar.parquet", index=False)
    cells.to_parquet(INTERIM / "gfw_sar_cells.parquet", index=False)
    write_manifest(INTERIM / "gfw_sar.manifest.json", inputs=["gfw/sar"],
                   outputs={"area_months": len(df), "cells": len(cells)}, notes="GFW SAR presence, non-commercial")
    return df, cells


def main():
    fetch(_session())
    df, cells = tables()
    dashboard()
    w = df.pivot_table(index=["area", "month"], columns="matched", values="detections", fill_value=0)
    print(w.groupby("area").tail(4).to_string())
    print("dark cells:", len(cells))


if __name__ == "__main__":
    main()


def dashboard():
    """app/data/sar.js: dark-vessel indicators per area, Hormuz AIS-vs-radar index, dark cells."""
    from sfp.paths import ROOT
    df = pd.read_parquet(INTERIM / "gfw_sar.parquet")
    cells = pd.read_parquet(INTERIM / "gfw_sar_cells.parquet")
    w = df.pivot_table(index=["area", "month"], columns="matched", values="detections", fill_value=0).reset_index()
    w.columns = ["area", "month", "dark", "matched"]
    w["total"] = w.dark + w.matched
    w["dark_share"] = (w.dark / w.total.where(w.total > 0)).round(3)
    areas = {a: g.sort_values("month")[["month", "dark", "matched", "dark_share"]].to_dict("records")
             for a, g in w.groupby("area")}
    pw = pd.DataFrame(json.loads((RAW / "imf_portwatch" / "daily_chokepoints.json").read_text()))
    pw["date"] = pd.to_datetime(pw["date"], unit="ms")
    hz = pw[pw.portname == "Strait of Hormuz"].assign(month=lambda x: x.date.dt.strftime("%Y-%m"))
    hzm = hz.groupby("month").agg(ais_tanker_transits=("n_tanker", "mean"), ais_all_transits=("n_total", "mean"))
    sar = w[w.area == "Strait of Hormuz"].set_index("month")[["total", "dark"]]
    j = hzm.join(sar, how="inner")
    base_m = [m for m in j.index if "2025-10" <= m <= "2026-02"]
    idx = (100 * j / j.loc[base_m].mean()).round(1)
    cells["lat5"], cells["lon5"] = (cells.lat / 0.05).round() * 0.05, (cells.lon / 0.05).round() * 0.05
    c5 = cells.groupby(["lat5", "lon5"], as_index=False)["detections"].sum()
    out = {"window_cells": CELL_WINDOW, "cell_area": CELL_AREA[0], "cell_bbox": CELL_AREA[1], "areas": areas,
           "area_boxes": AREAS, "hormuz_index": {"months": list(idx.index), "base": f"{base_m[0]} to {base_m[-1]}",
                                                 "series": {c: [None if pd.isna(v) else float(v) for v in idx[c]] for c in idx.columns},
                                                 "raw": {c: [None if pd.isna(v) else round(float(v), 1) for v in j[c]] for c in j.columns}},
           "cells": [[round(a, 2), round(b, 2), int(n)] for a, b, n in zip(c5.lat5, c5.lon5, c5.detections)]}
    (ROOT / "app" / "data" / "sar.js").write_text("window.SFP_SAR = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print("sar.js:", len(out["cells"]), "cells;", {k: len(v) for k, v in areas.items()})
