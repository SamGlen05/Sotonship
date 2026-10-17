"""Run every build stage after the downloads, in order. Stops on the first failure
(including a failed leakage test).

    PYTHONPATH=src python -m sfp.pipeline --scratch data/interim/_unzip [--skip-global]
"""
import argparse
import subprocess
import sys

DMA = [["labels"], ["opensanctions"], ["ais_reduce", "--scratch", "{scratch}"], ["ais_events"], ["link"],
       ["features"], ["leakage_test"], ["model", "--set", "dma"], ["ais_analysis"]]
GLOBAL = [["gfw_tables"], ["gfw_sar"], ["global_features"], ["leakage_test_global"], ["model", "--set", "global"], ["ablation"],
          ["score_global"], ["gfw_analysis"]]
DMA_ONLY_SCORE = [["score"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default="data/interim/_unzip", help="dir for unzipped AIS CSVs (needs ~7 GB)")
    ap.add_argument("--skip-global", action="store_true", help="Danish AIS only (no Global Fishing Watch)")
    a = ap.parse_args()
    stages = DMA + (DMA_ONLY_SCORE if a.skip_global else GLOBAL)
    for st in stages:
        cmd = [sys.executable, "-m", f"sfp.{st[0]}"] + [x.format(scratch=a.scratch) for x in st[1:]]
        print("==", " ".join(st), flush=True)
        if subprocess.run(cmd).returncode:
            sys.exit(f"stage {st[0]} failed")
    print("PIPELINE OK. Open the dashboard with: ./run.sh serve")


if __name__ == "__main__":
    main()
