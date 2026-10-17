"""Every heuristic threshold lives here. ALL VALUES ARE ASSUMPTIONS (starting
points from docs/PIPELINE.md) and must be tuned on training data only. Record
final values in docs/EVALUATION.md."""

# --- AIS reduction -----------------------------------------------------------
# ASSUMPTION: one position per ship per 5 minutes is enough for gap/loiter/STS events.
AIS_RESAMPLE_MINUTES = 5
# ASSUMPTION: AIS "Ship type" values we treat as tankers.
TANKER_SHIP_TYPES = ("Tanker",)

# --- Event definitions (Stage 1/3) ------------------------------------------
# ASSUMPTION: no position for >= this many hours while in coverage = AIS gap.
AIS_GAP_HOURS = 12
# ASSUMPTION: in a single-day file we can only see short gaps; flag >= this many
# hours inside one day as an intra-day gap (much weaker signal).
AIS_INTRADAY_GAP_HOURS = 2
# ASSUMPTION: speed under this (knots) for LOITER_HOURS outside port = loitering.
LOITER_SPEED_KN = 1.0
LOITER_HOURS = 12
# ASSUMPTION: two tankers within this distance (nm), both under STS_SPEED_KN,
# for at least STS_MIN_HOURS = ship-to-ship meeting.
STS_DISTANCE_NM = 0.5
STS_SPEED_KN = 2.0
STS_MIN_HOURS = 2
# ASSUMPTION: consecutive positions implying more than this speed = spoof jump.
SPOOF_SPEED_KN = 50
# ASSUMPTION: destination strings that are uninformative / commonly used to hide voyage.
NOTABLE_DESTINATIONS = ("FOR ORDERS", "FOR ORDER", "ORDERS", "TBA", "TBN", "UNKNOWN", "SEA")

# --- Russian export terminals ------------------------------------------------
# ASSUMPTION: a ship within this radius (km) of a terminal and slow is "at" it.
PORT_RADIUS_KM = 15

# --- Labels / evaluation -----------------------------------------------------
TRAIN_CUTOFF = "2026-05-01"
TEST_BATCHES_UK = ("2026-06-16", "2026-10-01")
LABEL_HORIZON_DAYS = 90

# ASSUMPTION: AIS destination strings (upper-cased, punctuation stripped) that point
# to Russian oil/gas export terminals. Port names plus UN/LOCODEs. Hand-built list.
RUSSIAN_PORT_DEST_PATTERNS = (
    r"PRIMORSK", r"\bRU ?PRI\b", r"UST ?LUGA", r"USTLUGA", r"\bRU ?ULU\b",
    r"VYSOTSK", r"\bRU ?VYS\b", r"ST ?PETERSBURG", r"SANKT", r"\bRU ?LED\b",
    r"NOVOROSSIYSK", r"NOVOROS", r"\bRU ?NVS\b", r"TUAPSE", r"\bRU ?TUA\b",
    r"TAMAN", r"MURMANSK", r"\bRU ?MMK\b", r"KALININGRAD", r"\bRU ?KGD\b",
    r"\bRU\b", r"RUSSIA",
)
# ASSUMPTION: Danish AIS sees ships transiting to/from the Baltic; positions east of
# this longitude are taken as Baltic-side of the straits (rough, for direction only).
BALTIC_SIDE_LON = 12.8

# ASSUMPTION: flags of convenience, from the ITF FOC list as commonly published
# (https://www.itfglobal.org/en/sector/seafarers/flags-of-convenience). Names as they
# appear in the MID table. Verify against the current ITF page before relying on it.
FLAGS_OF_CONVENIENCE = (
    "Antigua and Barbuda", "Bahamas", "Barbados", "Belize", "Bermuda", "Bolivia",
    "Cambodia", "Cameroon", "Comoros", "Cook Islands", "Cyprus", "Equatorial Guinea",
    "Faroe Islands", "Georgia", "Gibraltar", "Honduras", "Jamaica", "Lebanon", "Liberia",
    "Malta", "Marshall Islands", "Mauritius", "Moldova", "Mongolia", "Myanmar", "Panama",
    "Sao Tome and Principe", "Saint Kitts and Nevis", "Saint Vincent and the Grenadines",
    "Sri Lanka", "Tonga", "Tuvalu", "Vanuatu", "North Korea",
)

# --- AIS sampling plan ---------------------------------------------------------
# ASSUMPTION: one DMA AIS day per week (Wednesdays), uniformly across train and test
# periods. Keep density uniform: denser sampling in some months would shift
# sightings-based features between training and test snapshots.
AIS_SAMPLE_START = "2024-08-07"   # a Wednesday; 180-day look-back gives snapshots from 2025-02
AIS_SAMPLE_END = "2026-09-30"
AIS_SAMPLE_FREQ = "W-WED"

# --- Known-at rules for dated facts ------------------------------------------
# ASSUMPTION: port-state detentions/bans become public within this many days of the
# detention date (Tokyo/Black Sea/Abuja MoU publish monthly lists).
PSC_PUBLICATION_LAG_DAYS = 30
# ASSUMPTION: official sanctions lists are public on their listing date (lag 0).
LIST_PUBLICATION_LAG_DAYS = 0

# ASSUMPTION: inner Danish AIS coverage box (lat_min, lat_max, lon_min, lon_max).
# A silence counts as an "in-coverage gap" only if the ship is inside this box before
# and after it and implies < GAP_MAX_IMPLIED_KN (it did not simply sail out of range).
CORE_COVERAGE_BOX = (54.4, 57.9, 8.0, 15.5)
GAP_MAX_IMPLIED_KN = 3.0
# ASSUMPTION: ship-to-ship meeting candidates within this distance of a World Port
# Index port are berth/harbour proximity, not at-sea transfers, and are dropped.
PORT_EXCLUSION_KM = 4.0

# --- Economic exposure (ILLUSTRATIVE ASSUMPTIONS, editable in the dashboard) -----
# Tanker size class from AIS length (m): (max_length, class, typical DWT, hull value USD).
# Hull values are rough second-hand values for 15-20-year-old tonnage; DWT typical for class.
SIZE_CLASSES = (
    (130, "Small tanker", 8_000, 6e6),
    (185, "MR / Handysize", 45_000, 16e6),
    (230, "LR1 / Panamax", 72_000, 22e6),
    (255, "Aframax / LR2", 110_000, 32e6),
    (285, "Suezmax", 158_000, 42e6),
    (999, "VLCC", 300_000, 55e6),
)
CARGO_LOAD_FACTOR = 0.95       # share of DWT carried as cargo
BARRELS_PER_TONNE = 7.33       # crude oil, standard conversion
OIL_PRICE_USD_BBL = 95.0       # ASSUMPTION: Brent futures traded ~$89-103/bbl in Aug-Sep 2026 (TASS); editable, not live
# Risk bands relative to the base rate of the training population.
BAND_HIGH_X = 5.0
BAND_MEDIUM_X = 2.0

# --- Behaviour features, round 2 (ASSUMPTIONS) ---------------------------------
# Lingering near another tanker: within NEAR_DISTANCE_NM, both under NEAR_SPEED_KN,
# not moored, outside ports, for at least NEAR_MIN_HOURS.
NEAR_DISTANCE_NM = 2.0
NEAR_SPEED_KN = 3.0
NEAR_MIN_HOURS = 1.0
# A crossing counts as laden when that day's draught >= LADEN_RATIO x the ship's
# maximum draught seen in the look-back window.
LADEN_RATIO = 0.8
# Identity churn (names, MMSIs, flags) is counted over this longer window.
IDENTITY_LOOKBACK_DAYS = 365

# IMO number -> approximate build year, for explanation text only (not a model input;
# the model uses the raw IMO number). Medians per 100k IMO block, from 6,983 ships with
# known build years in OpenSanctions/UK/OFAC records (Spearman 0.96), 2026-10-17.
IMO_BUILD_YEAR = ((9_000_000, 1992), (9_100_000, 1997), (9_200_000, 2002), (9_300_000, 2006),
                  (9_400_000, 2009), (9_500_000, 2010), (9_600_000, 2011), (9_700_000, 2015),
                  (9_800_000, 2015), (9_900_000, 2021))

# --- Global (Global Fishing Watch) features: ASSUMPTIONS ----------------------------
# Port-visit countries (GFW anchorage flag, ISO3) treated as sanctioned-trade origins.
SANCTIONED_TRADE_PORT_COUNTRIES = ("RUS", "IRN", "VEN", "SYR", "PRK")
# Major buyer markets for re-routed crude (context signal, not risk by itself).
REROUTE_MARKETS = ("IND", "CHN", "TUR", "ARE", "EGY", "MYS", "SGP")
# Reported ship-to-ship transfer areas in/near Europe and the Middle East
# (lon_min, lat_min, lon_max, lat_max). Hand-drawn boxes; assumption, not official zones.
STS_HOTSPOTS = {
    "Laconian Gulf (GR)": (22.3, 36.3, 23.2, 36.9),
    "Kalamata / Messinian Gulf (GR)": (21.7, 36.6, 22.2, 37.05),
    "Hurd's Bank (MT)": (14.3, 35.6, 14.9, 36.0),
    "Ceuta / Gibraltar approaches": (-5.6, 35.75, -5.0, 36.25),
    "Kerch Strait / Kavkaz": (36.4, 45.0, 37.0, 45.5),
    "Gulf of Finland outer anchorages": (26.5, 59.6, 28.5, 60.2),
    "Kola Bay / Murmansk approaches": (32.5, 68.9, 34.5, 69.6),
    "Fujairah / Khor Fakkan anchorage": (56.2, 24.8, 57.0, 25.6),
    "Sohar / Gulf of Oman": (56.5, 24.0, 57.5, 24.7),
    "Kharg / Bushehr approaches": (50.0, 28.8, 50.6, 29.4),
    "Port Said / Suez anchorages": (32.2, 29.7, 32.7, 31.4),
    "Hormuz eastern approach": (56.4, 25.8, 57.2, 26.6),
}
GFW_LOOKBACK_DAYS = 180
# ASSUMPTION: size class from registry gross tonnage when no AIS length is known
# (max GT, class name as in SIZE_CLASSES). Typical tanker GT per class.
SIZE_BY_GT = ((5_000, "Small tanker"), (30_000, "MR / Handysize"), (45_000, "LR1 / Panamax"),
              (66_000, "Aframax / LR2"), (90_000, "Suezmax"), (10**9, "VLCC"))

# ASSUMPTION: enclosed basins whose chokepoint passages we infer from consecutive port
# calls (one inside, one outside). A passage is "dark" when a GFW intentional AIS gap
# overlaps the time between the two port calls. (lon_min, lat_min, lon_max, lat_max)
BASINS = {
    "Persian Gulf": (47.0, 23.5, 56.3, 31.0),   # passage = Strait of Hormuz
    "Red Sea": (32.0, 12.6, 43.4, 30.0),        # passage = Bab el-Mandeb or Suez
    "Baltic": (12.8, 53.5, 31.0, 66.0),         # passage = Danish straits
    "Black Sea": (27.4, 40.8, 42.0, 47.5),      # passage = Bosporus
}

# --- Customer insight figures (sourced; checked 2026-10-17) ------------------------
# Hull values: 5-year-old benchmark per class (KOBC assessment 1 Oct 2026 via ShipUniverse;
# LR1 and small tankers interpolated), depreciated linearly to 45% at 20 years, which
# matches reported 2026 sales of 2006-built Suezmaxes (~$50.8M) and 20-year VLCCs.
VALUE_5YR_USD = {"Small tanker": 20e6, "MR / Handysize": 58e6, "LR1 / Panamax": 70e6,
                 "Aframax / LR2": 87e6, "Suezmax": 110e6, "VLCC": 178e6}
HULL_DEPRECIATION_PER_YEAR = 0.0367   # 1.0 at 5 years -> 0.45 at 20 years
HULL_VALUE_FLOOR = 0.25               # never below a quarter of the 5-year value
HULL_VALUE_RANGE = 0.30               # show +/- 30% (benchmarks vary widely in 2026)
# Statutory maximum civil penalties (per violation; ceilings, not expected fines)
OFAC_IEEPA_MAX_USD = 377_700          # greater of this or 2x the transaction (Fed. Reg. 2025-00786, Jan 2025)
OFSI_MAX_GBP = 1_000_000              # greater of this or 50% of the breach value (Policing and Crime Act 2017)
# International Group P&I, policy year 2026/27 (North Standard, Skuld, London P&I circulars)
IG_OIL_POLLUTION_LIMIT_USD = 1_000_000_000
IG_OVERSPILL_LIMIT_USD = 3_350_000_000
# Risk bands by rank among all scored tankers (top 1% high, next 4% medium)
BAND_HIGH_TOP_PCT = 1.0
BAND_MEDIUM_TOP_PCT = 5.0
