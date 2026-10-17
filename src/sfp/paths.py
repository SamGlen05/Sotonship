"""Project paths. Raw data is write-once; derived data goes to interim/processed."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

for _p in (RAW, INTERIM, PROCESSED, REPORTS):
    _p.mkdir(parents=True, exist_ok=True)
