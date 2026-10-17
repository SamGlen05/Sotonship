"""Small per-stage manifest: inputs (with retrieval dates from data/raw/manifest.jsonl),
output row counts and run time."""
import json
from datetime import datetime, timezone
from pathlib import Path

from sfp.paths import RAW


def raw_retrievals() -> dict[str, dict]:
    out = {}
    m = RAW / "manifest.jsonl"
    if m.exists():
        for line in m.read_text().splitlines():
            e = json.loads(line)
            out[e["file"]] = e
    return out


def write_manifest(path: Path, inputs: list[str], outputs: dict, notes: str = "") -> None:
    ret = raw_retrievals()
    doc = {
        "ran_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": [{"file": f, "url": ret.get(f, {}).get("url"),
                    "retrieved_utc": ret.get(f, {}).get("retrieved_utc")} for f in inputs],
        "outputs": outputs,
        "notes": notes,
    }
    path.write_text(json.dumps(doc, indent=2, default=str))
