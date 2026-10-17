# Finding the dark fleet at Hormuz, next steps, and similar tools

Written 2026-10-17. Data: Global Fishing Watch radar detections and events, IMF PortWatch, all retrieved 2026-10-16/17.

## 1. What the data shows at Hormuz

- **AIS transits collapsed.** IMF PortWatch counts tanker transits through the Strait of Hormuz from AIS. They fell from about 45 a day (Oct 2025 – Feb 2026) to 1–5 a day from March 2026, about 3% of the earlier level by September.
- **Radar still sees the traffic.** Global Fishing Watch's Sentinel-1 radar detections in the strait fell to about half in March–June 2026, but by **July–September 2026 they were back above pre-March levels (about 122% of the October–February average)**.
- **Most of what radar sees is dark.** Of those detections, **60–65% have no matching AIS signal**, against about 10% in the Danish straits. In the Gulf of Oman the dark share is 53–82%, and at the Kerch Strait it is about 98%.
- **Port calls confirm tankers kept crossing.** Consecutive port calls inside and outside the Persian Gulf imply **140–430 Hormuz passages a month by candidate tankers from April to September 2026**, while AIS transit counts stayed near zero.
- **GFW's gap events rarely catch them.** Only 2 of those passages overlap an AIS-gap event, against 161 in the Red Sea. That points to AIS degraded by jamming or spoofing rather than clean switch-offs (gap detection needs good reception on both sides).

**Conclusion:** ships still use the strait; many are not broadcasting usable AIS while they do. A model fed only by AIS behaviour treats them as quiet. That is the blind spot to close.

## 2. Can we find them without proprietary data? Mostly yes, with limits

| Method | Data (free) | What it gives | Limits |
| --- | --- | --- | --- |
| Radar vessel detections | GFW SAR presence (Sentinel-1), already integrated | Location and date of every hull above ~15–20 m; matched or dark | No identity; revisit every few days; small boats included |
| Own radar processing | Sentinel-1 imagery, Copernicus Data Space | Detections plus estimated length and heading, so tanker-sized targets can be kept | Needs a detection model (open models exist); compute cost |
| Optical imagery | Sentinel-2 (10 m, every 5 days, often cloud-free over the Gulf) | Confirms a hull is a tanker; shows two hulls side by side (ship-to-ship transfer) | Daylight only; 10 m resolution cannot read names |
| Night lights | NOAA VIIRS boat detections | Lit vessels at night | Built for fishing fleets; coarse |
| Port-call sequences | GFW port visits, integrated | Passages inferred from calls on both sides, with dates and ports | Only ships that make AIS port calls |
| AIS gaps and spoofing | GFW gaps; position jumps | Who switched off, and where | Sparse where reception is jammed |

**How to put a name on a dark radar target, using only free data:**
1. **Candidates:** for each dark radar detection, list tankers whose last AIS position before going silent, or first after reappearing, is within reach at plausible speed. This is space-time gating, like ships "off" before Hormuz and "on" after it.
2. **Size check:** keep candidates whose length matches the radar length estimate (own Sentinel-1 processing).
3. **Visual check:** use Sentinel-2 to tell a tanker from a cargo ship, and to see transfers.
4. **Trajectory chaining:** chain detections across passes to recover dark tracks.
5. **Attribution with confidence:** an attribution like "probably IMO X, 70%" becomes evidence on the vessel card, never a verdict.

Expect partial success. Attribution is reliable when few candidates fit and weak in busy anchorages such as Fujairah. Published open work (for example DarkVesselNet, and GFW's dark-vessel research) follows the same multi-sensor approach. Starboard notes that a radar detection is a lead to verify, not proof.

**What proprietary data would add:**
- **Very high-resolution imagery:** Planet (3 m daily) and Maxar, enough to read deck layouts.
- **Tasked commercial radar:** ICEYE, Capella.
- **Radio-frequency geolocation:** HawkEye 360, Unseenlabs, which locate ships by their navigation-radar emissions even with AIS off, and fingerprint individual ships.
- **Satellite AIS with spoofing analytics:** Spire, Kpler, Windward.

These are the realistic route to identity-level coverage at Hormuz.

## 3. Next steps, in priority order

1. **Turn the passage signal into evidence for every Gulf tanker.** Done in this build: passages with dates and ports appear on the vessel card and in the model.
2. **Per-vessel radar attribution.** Pull GFW radar detections at full resolution for Hormuz and the Gulf of Oman. Match them to tankers whose AIS went silent nearby (step 1 above), and add "probably seen dark at Hormuz on date" as evidence with a confidence.
3. **Own Sentinel-1 processing** for the strait and the main transfer anchorages (Fujairah/Khor Fakkan, Sohar, Laconian Gulf, Kalamata, Kerch), with length estimates to keep tanker-sized targets only.
4. **Sentinel-2 confirmation** of ship-to-ship transfers at the hotspots, as image chips on the vessel card for analysts.
5. **Spoofing detection.** Flag positions that are physically implausible, or inconsistent with radar at the same time. In the Gulf, jamming makes this a regional baseline problem.
6. **Ownership and management data** (licensed registry): the largest remaining gap for the model.
7. **Wider coverage:** add the Asian transfer hubs, India, China, West Africa and Venezuela as further sea areas.
8. **Production and commercial licences:** Global Fishing Watch and OpenSanctions are non-commercial. Budget for satellite AIS, a registry and, if Hormuz matters to a customer, radio-frequency geolocation.

## 4. Similar tools

The market is established. Our angle is transparency and cost.

| Tool | What it does (vendor claims, not independently verified) |
| --- | --- |
| **Windward** (Risk & Compliance) | Screens vessels and counterparties against LSEG World-Check lists. Says it runs 15+ proprietary AI models for ship-to-ship transfers, GNSS manipulation and ownership-based shadow-fleet links. |
| **Kpler** (incl. MarineTraffic) | Behaviour- and network-based shadow-fleet exposure ("risk tree", including a "grey fleet" tier). Reports that 23.5% of a flagged cohort was later sanctioned. |
| **Pole Star** (PurpleTRAC, Maritime Transparency Index) | Sanctions screening and vessel monitoring, as software or an API. The Index scores 40,000+ vessels from 0 ("hard dark") to 5 ("transparent") on vessel, position and voyage factors. |
| **Starboard Maritime Intelligence** | Dark-vessel detection from multiple satellite sensors, for maritime domain awareness. |
| **S&P Global, Lloyd's List Intelligence** | Large vessel and ownership databases with compliance screening. These are the registry-grade data we lack. Product details were not confirmed in this research. |
| **Global Fishing Watch** (non-profit) | The open data and radar detections we build on. Not a compliance product. |

From general knowledge, not verified here: Spire Maritime, Vortexa and TankerTrackers.com also track tankers and sanctioned trades.

Third-party listings put commercial platforms at roughly $20,000–$80,000 a year. That figure is unverified.

**How this tool differs:**
- **Every elevated score lists its reasons with dated, sourced evidence.**
- **Published backtest:** performance on later sanction batches, not a self-reported hit rate.
- **No look-ahead:** two automated leakage tests guarantee no future data is used.
- **Coverage stated next to every number.**
- **Open data:** built from public data, so it is cheap to run and can be audited.

**What we lack against the leaders:** ownership networks, satellite AIS density, radio-frequency and very high-resolution imagery, and commercial data licences.

## Sources

- IMF PortWatch daily chokepoints (ArcGIS feature service), retrieved 2026-10-17
- Global Fishing Watch API v3: SAR presence, events, identity (non-commercial licence), retrieved 2026-10-17
- Windward Risk & Compliance: https://windward.ai/?p=36099
- Kpler, "How to build a risk tree to assess shadow fleet exposure", 2026-04-01: https://www.kpler.com/blog/how-to-build-a-risk-tree-to-assess-shadow-fleet-exposure-in-your-network
- Pole Star PurpleTRAC: https://polestarglobal.com/software-solutions/purpletrac
- Pole Star Maritime Transparency Index: https://www.ajot.com/news/pole-star-global-launches-maritime-transparency-index
- Starboard dark vessel detection: https://starboard.nz/case-study-dark-vessel-detection-for-mda
- Global Fishing Watch dark vessels research: https://globalfishingwatch.org/research-project-dark-vessels/
- DarkVesselNet (arXiv 2606.00445): https://arxiv.org/pdf/2606.00445
