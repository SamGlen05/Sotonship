"""Stage 1: parse UK, EU and OFAC vessel designations into tidy tables keyed on IMO.

Outputs (data/interim/):
  uk_vessels.parquet    one row per UK Unique ID (ship), with designation date
  eu_vessels.parquet    one row per EU list row, with date of application
  ofac_vessels.parquet  one row per OFAC vessel profile, with 'Created' entry date
  labels.parquet        one row per IMO: first designation date per regime
"""
import re
from pathlib import Path

import pandas as pd
from lxml import etree

from sfp.manifest import write_manifest
from sfp.paths import INTERIM, RAW

IMO_RE = re.compile(r"(\d{7})")


def clean_imo(x) -> str | None:
    """Return a 7-digit IMO string, or None. Validates the IMO check digit."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    m = IMO_RE.search(str(x))
    if not m:
        return None
    d = m.group(1)
    check = sum(int(d[i]) * (7 - i) for i in range(6)) % 10
    return d if check == int(d[6]) else None


# ---------------------------------------------------------------- UK
def parse_uk(path: Path = RAW / "uk" / "UK-Sanctions-List.csv") -> pd.DataFrame:
    report_date = open(path, encoding="utf-8-sig").readline().split(":", 1)[1].strip()
    df = pd.read_csv(path, skiprows=1, dtype=str)
    df = df[df["Designation Type"] == "Ship"].copy()
    df["is_primary"] = df["Name type"].str.lower().eq("primary name")
    aliases = (
        df[~df["is_primary"]].groupby("Unique ID")["Name 6"]
        .agg(lambda s: "|".join(sorted(set(s.dropna())))).rename("aliases")
    )
    p = (df.sort_values("is_primary", ascending=False)
           .drop_duplicates("Unique ID").set_index("Unique ID"))
    out = pd.DataFrame({
        "uk_id": p.index,
        "imo": p["IMO number"].map(clean_imo).values,
        "name": p["Name 6"].values,
        "regime": p["Regime Name"].values,
        "designated_on": pd.to_datetime(p["Date Designated"], dayfirst=True).values,
        "last_updated": pd.to_datetime(p["Last Updated"], dayfirst=True).values,
        "flag": p["Current believed flag of ship"].values,
        "previous_flags": p["Previous flags"].values,
        "ship_type": p["Type of ship"].values,
        "build_year": pd.to_numeric(p["Year Built"], errors="coerce").values,
        "owner_operator": p["Current owner/operator (s)"].values,
        "statement_of_reasons": p["UK Statement of Reasons"].values,
    })
    out = out.merge(aliases, left_on="uk_id", right_index=True, how="left")
    out["source"] = f"UK Sanctions List (report date {report_date})"
    return out


# ---------------------------------------------------------------- EU
def parse_eu(path: Path = RAW / "eu" / "ImportversionListOfEUDesignatedVessels240726.csv") -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig")
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(subset=["IMO number"])
    out = pd.DataFrame({
        "imo": df["IMO number"].map(clean_imo),
        "imo_raw": df["IMO number"].str.strip(),
        "name": df["Vessel name"].str.strip(),
        "listed_on": pd.to_datetime(df["Date of application"].str.strip(), format="%d.%m.%Y"),
        "subject_to": df["Subject to"].str.strip(),
    })
    out["regime"] = out["subject_to"].map(
        lambda s: "Russia (833/2014 Art. 3s)" if "833/2014" in s else "DPRK (2017/1509)")
    out["source"] = "EU designated vessels, Danish Maritime Authority import version 24-07-2026"
    return out


# ---------------------------------------------------------------- OFAC
def parse_ofac(path: Path = RAW / "ofac" / "SDN_ADVANCED.XML") -> pd.DataFrame:
    tree = etree.parse(str(path))
    root = tree.getroot()
    ns = {"o": root.nsmap[None]}
    q = lambda el, xp: el.xpath(xp, namespaces=ns)  # noqa: E731

    issue = q(root, "o:DateOfIssue")[0]
    issue_date = "-".join(q(issue, f"string(o:{p})").zfill(2) for p in ("Year", "Month", "Day"))

    refs = {r.get("ID"): r.text for r in q(root, "//o:ReferenceValueSets//*[@ID]")}
    ftype = {r.get("ID"): r.text for r in q(root, "//o:FeatureTypeValues/o:FeatureType")}

    vessels = {}
    for prof in q(root, "//o:DistinctParty/o:Profile[@PartySubTypeID='1']"):
        pid = prof.get("ID")
        ident = q(prof, "o:Identity[@Primary='true']")[0]
        names = q(ident, ".//o:Alias[@Primary='true']//o:NamePartValue/text()")
        alias = q(ident, ".//o:Alias[@Primary='false']//o:NamePartValue/text()")
        rec = {"ofac_profile_id": pid, "identity_id": ident.get("ID"),
               "name": " ".join(names), "aliases": "|".join(alias)}
        feats: dict[str, list[str]] = {}
        for f in q(prof, "o:Feature"):
            label = ftype.get(f.get("FeatureTypeID"), f.get("FeatureTypeID"))
            for vd in q(f, ".//o:VersionDetail"):
                val = vd.text or refs.get(vd.get("DetailReferenceID"))
                if val:
                    feats.setdefault(label, []).append(val.strip())
        rec["vessel_type"] = "|".join(feats.get("VESSEL TYPE", []))
        rec["flag"] = "|".join(feats.get("Vessel Flag", []))
        rec["former_flags"] = "|".join(feats.get("Former Vessel Flag", []) + feats.get("Other Vessel Flag", []))
        rec["build_year"] = (feats.get("Vessel Year of Build") or [None])[0]
        rec["owner"] = "|".join(feats.get("Vessel Owner", []))
        rec["gross_tonnage"] = (feats.get("Vessel Gross Registered Tonnage") or feats.get("Vessel Tonnage") or [None])[0]
        vessels[ident.get("ID")] = rec

    for doc in q(root, "//o:IDRegDocuments/o:IDRegDocument"):
        rec = vessels.get(doc.get("IdentityID"))
        if rec is None:
            continue
        no = q(doc, "string(o:IDRegistrationNo)")
        if doc.get("IDRegDocTypeID") == "1626":
            rec.setdefault("imo_raw", no)
        elif doc.get("IDRegDocTypeID") == "91264":
            rec["mmsi"] = re.sub(r"\D", "", no)

    by_profile = {r["ofac_profile_id"]: r for r in vessels.values()}
    for se in q(root, "//o:SanctionsEntries/o:SanctionsEntry"):
        rec = by_profile.get(se.get("ProfileID"))
        if rec is None:
            continue
        d = q(se, "o:EntryEvent[@EntryEventTypeID='1']/o:Date")
        if d:
            d = d[0]
            rec["designated_on"] = "-".join(q(d, f"string(o:{p})").zfill(2) for p in ("Year", "Month", "Day"))
        rec["programs"] = "|".join(
            c.strip() for c in q(se, "o:SanctionsMeasure[@SanctionsTypeID='1']/o:Comment/text()"))

    out = pd.DataFrame(by_profile.values())
    out["imo"] = out["imo_raw"].map(clean_imo)
    out["designated_on"] = pd.to_datetime(out["designated_on"])
    out["build_year"] = pd.to_numeric(out["build_year"], errors="coerce")
    out["source"] = f"OFAC SDN advanced XML (date of issue {issue_date})"
    return out


# ---------------------------------------------------------------- combine
def uk_batches(dates: pd.Series, max_gap_days: int = 2) -> pd.Series:
    """Group designation dates no more than max_gap_days apart into one batch,
    labelled by its first date (e.g. 2026-10-01 + 2026-10-02 -> 2026-10-01)."""
    u = pd.Series(sorted(dates.dropna().unique()))
    start = u.where(u.diff().dt.days.fillna(999) > max_gap_days).ffill()
    return dates.map(dict(zip(u, start)))


def build_labels(uk, eu, ofac) -> pd.DataFrame:
    """One row per IMO. Ships never designated are not in here; they are
    unlabelled, not confirmed clean."""
    uk_r = uk[uk["regime"].str.contains("Russia")].dropna(subset=["imo"])
    eu_r = eu[eu["regime"].str.startswith("Russia")].dropna(subset=["imo"])
    of_r = ofac[ofac["programs"].str.contains("RUSSIA", na=False)].dropna(subset=["imo"])
    lab = pd.concat([
        uk_r.groupby("imo")["designated_on"].min().rename("uk_designated_on"),
        eu_r.groupby("imo")["listed_on"].min().rename("eu_listed_on"),
        of_r.groupby("imo")["designated_on"].min().rename("us_designated_on"),
        # any-regime dates (incl. Iran, DPRK, Libya etc.) as context
        uk.dropna(subset=["imo"]).groupby("imo")["designated_on"].min().rename("uk_any_on"),
        eu.dropna(subset=["imo"]).groupby("imo")["listed_on"].min().rename("eu_any_on"),
        ofac.dropna(subset=["imo"]).groupby("imo")["designated_on"].min().rename("us_any_on"),
    ], axis=1)
    lab["first_designated_on"] = lab[["uk_designated_on", "eu_listed_on", "us_designated_on"]].min(axis=1)
    lab["first_any_on"] = lab[["uk_any_on", "eu_any_on", "us_any_on"]].min(axis=1)
    lab["uk_batch"] = uk_batches(lab["uk_designated_on"])
    lab.index.name = "imo"
    return lab.reset_index()


def main():
    uk, eu, ofac = parse_uk(), parse_eu(), parse_ofac()
    labels = build_labels(uk, eu, ofac)
    outs = {"uk_vessels": uk, "eu_vessels": eu, "ofac_vessels": ofac, "labels": labels}
    for k, v in outs.items():
        v.to_parquet(INTERIM / f"{k}.parquet", index=False)
        print(k, v.shape)
    write_manifest(INTERIM / "labels.manifest.json",
                   inputs=["uk/UK-Sanctions-List.csv",
                           "eu/ImportversionListOfEUDesignatedVessels240726.csv",
                           "ofac/SDN_ADVANCED.XML"],
                   outputs={k: len(v) for k, v in outs.items()})


if __name__ == "__main__":
    main()
