#!/usr/bin/env bash
# Tanker sanctions-risk tool: one entry point for setup, downloads, build and the dashboard.
#
#   ./run.sh setup        create .venv and install requirements
#   ./run.sh download     sanctions lists, OpenSanctions, GUR, reference tables, Danish AIS
#                         (weekly sample, ~70 GB, hours) and Global Fishing Watch (needs
#                         GFW_API_TOKEN in .env). Resumable: rerun to continue.
#   ./run.sh build        every stage: labels, AIS, features, leakage tests, models,
#                         scores and dashboard data (add --skip-global for Danish AIS only)
#   ./run.sh serve        open the dashboard at http://localhost:8000
#   ./run.sh all          setup + download + build + serve
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
export PYTHONPATH=src

setup()    { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && echo "setup done"; }
download() {
  $PY -m sfp.download --small
  $PY -m sfp.download --ais-plan --workers 3
  if [ -f .env ] && grep -q '^GFW_API_TOKEN=.' .env; then
    $PY -m sfp.gfw_region all
  else
    echo "Skipping Global Fishing Watch: put GFW_API_TOKEN=... in .env (free, non-commercial)."
  fi
}
build()    { $PY -m sfp.pipeline --scratch data/interim/_unzip "$@"; }
serve()    { echo "Dashboard: http://localhost:8000  (Ctrl+C to stop)"; cd app && ../$PY -m http.server 8000; }

case "${1:-help}" in
  setup) setup ;;
  download) download ;;
  build) shift; build "$@" ;;
  serve) serve ;;
  all) setup; download; build; serve ;;
  *) sed -n '2,10p' "$0" ;;
esac
