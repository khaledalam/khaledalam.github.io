#!/usr/bin/env python3
"""Build data.json for /inflation-rate/ from open data.

Sources (both free and open):
  - IMF World Economic Outlook, DataMapper API: CPI inflation (PCPIPCH), real GDP
    growth (NGDP_RPCH) and unemployment (LUR), 1980 onward, with projections.
  - World Bank, FP.CPI.TOTL.ZG: annual CPI inflation from 1960, plus country regions.

The IMF series is used wherever it has a value, because it is the one the forecasts
come from. World Bank values fill the years the IMF does not cover (mostly
1960-1979), and are never used for the current year or later.

Run from anywhere:  python3 inflation-rate/build_data.py
Standard library only.
"""

import datetime as dt
import json
import pathlib
import time
import urllib.error
import urllib.request

OUT = pathlib.Path(__file__).with_name("data.json")
IMF = "https://www.imf.org/external/datamapper/api/v1"
WB = "https://api.worldbank.org/v2"
ISO_CODES = "https://cdn.jsdelivr.net/npm/i18n-iso-countries@7/codes.json"

TODAY = dt.date.today()
PROJ_FROM = TODAY.year  # this year onward is an estimate or projection
Y0 = 1960

# IMF and World Bank disagree on a couple of codes.
IMF_TO_WB = {"UVK": "XKX", "WBG": "PSE"}

NAME_FIX = {
    "BHS": "Bahamas", "CHN": "China", "COD": "DR Congo", "COG": "Republic of the Congo",
    "FSM": "Micronesia", "GMB": "Gambia", "KOR": "South Korea", "PRK": "North Korea",
    "TUR": "Türkiye", "TWN": "Taiwan", "SSD": "South Sudan", "UVK": "Kosovo",
    "WBG": "Palestine", "VIR": "US Virgin Islands", "RUS": "Russia", "IRN": "Iran",
    "SYR": "Syria", "LAO": "Laos", "VNM": "Vietnam", "KGZ": "Kyrgyzstan",
    "SVK": "Slovakia", "CZE": "Czechia", "MKD": "North Macedonia", "BRN": "Brunei",
    "CPV": "Cabo Verde", "STP": "São Tomé and Príncipe", "CIV": "Côte d'Ivoire",
    "YEM": "Yemen", "EGY": "Egypt", "VEN": "Venezuela", "KNA": "St. Kitts and Nevis",
    "LCA": "St. Lucia", "VCT": "St. Vincent and the Grenadines",
}

NORTH_AFRICA = {"DZA", "EGY", "LBY", "MAR", "TUN"}
AFRICA_FROM_MENA = NORTH_AFRICA | {"DJI"}
CENTRAL_ASIA = {"KAZ", "KGZ", "TJK", "TKM", "UZB"}
OCEANIA = {"AUS", "NZL", "FJI", "PNG", "WSM", "TON", "VUT", "SLB", "KIR", "FSM", "MHL",
           "PLW", "NRU", "TUV", "ASM", "GUM", "MNP", "PYF", "NCL"}

# Regional aggregates from the IMF, used for "compared with its region".
REGIONS = {"WEOWORLD": "World", "NAQ": "North Africa", "SSQ": "Sub-Saharan Africa",
           "AFQ": "Africa", "MEQ": "Middle East", "CAQ": "Central Asia and the Caucasus",
           "APQ": "Asia and Pacific", "EUQ": "Europe", "WHQ": "Western Hemisphere",
           "AZQ": "Australia and New Zealand", "PIQ": "Pacific Islands"}


def get(url):
    # The IMF API returns 403 for some custom User-Agents (urllib's default is accepted)
    # and sometimes resets back-to-back connections, so retry with a pause.
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))


def continent(code, wb_region):
    if code == "TWN":
        return "Asia"
    if code in OCEANIA:
        return "Australia"
    if code in CENTRAL_ASIA:
        return "Asia"
    if code == "MLT":
        return "Europe"
    if wb_region.startswith("Sub-Saharan"):
        return "Africa"
    if wb_region.startswith("Middle East"):
        return "Africa" if code in AFRICA_FROM_MENA else "Asia"
    if wb_region.startswith("Europe"):
        return "Europe"
    if wb_region.startswith(("Latin America", "North America")):
        return "America"
    if wb_region.startswith(("East Asia", "South Asia")):
        return "Asia"
    return None


def region_aggregate(code, cont, wb_region):
    if cont == "Africa":
        if code in NORTH_AFRICA:
            return "NAQ"
        return "SSQ" if wb_region.startswith("Sub-Saharan") else "AFQ"
    if cont == "Asia":
        if code in CENTRAL_ASIA:
            return "CAQ"
        return "MEQ" if wb_region.startswith("Middle East") else "APQ"
    if cont == "Europe":
        return "EUQ"
    if cont == "America":
        return "WHQ"
    if cont == "Australia":
        return "AZQ" if code in ("AUS", "NZL") else "PIQ"
    return None


def rnd(v):
    return None if v is None else round(float(v), 1)


def series(values, y0, y1):
    """Dict {year: value} -> list over [y0, y1], trimmed of trailing nulls."""
    out = [rnd(values.get(str(y))) for y in range(y0, y1 + 1)]
    while out and out[-1] is None:
        out.pop()
    return out


def main():
    print("fetching IMF ...")
    imf_cpi = get(f"{IMF}/PCPIPCH")["values"]["PCPIPCH"]
    imf_gdp = get(f"{IMF}/NGDP_RPCH")["values"]["NGDP_RPCH"]
    imf_lur = get(f"{IMF}/LUR")["values"]["LUR"]
    imf_names = {k: (v.get("label") or "").strip() for k, v in get(f"{IMF}/countries")["countries"].items()}
    weo = get(f"{IMF}/indicators")["indicators"]["PCPIPCH"].get("source", "World Economic Outlook")

    print("fetching World Bank ...")
    wb_meta, wb_rows = get(f"{WB}/country/all/indicator/FP.CPI.TOTL.ZG?format=json&per_page=20000")
    _, wb_countries = get(f"{WB}/country?format=json&per_page=400")
    wb_info = {c["id"]: c for c in wb_countries if c["region"]["value"].strip() != "Aggregates"}
    wb_cpi = {}
    for r in wb_rows:
        if r["value"] is not None and r["countryiso3code"] in wb_info:
            wb_cpi.setdefault(r["countryiso3code"], {})[int(r["date"])] = r["value"]

    print("fetching ISO numeric codes ...")
    numeric = {a3: num for _a2, a3, num, *_ in get(ISO_CODES)}

    y1 = max(int(y) for v in imf_cpi.values() for y in v)
    codes = {c for c in imf_cpi if c in imf_names} | set(wb_cpi)

    countries = {}
    for code in sorted(codes):
        if code in IMF_TO_WB.values():
            continue  # handled under its IMF code
        wb_code = IMF_TO_WB.get(code, code)
        info = wb_info.get(wb_code)
        wb_region = info["region"]["value"].strip() if info else ""
        cont = continent(code, wb_region)
        if not cont:
            continue
        imf = imf_cpi.get(code, {})
        wb = wb_cpi.get(wb_code, {})
        cpi, wb_years = [], []
        for y in range(Y0, y1 + 1):
            v = imf.get(str(y))
            if v is None and y < PROJ_FROM and y in wb:
                v = wb[y]
                wb_years.append(y)
            cpi.append(rnd(v))
        while cpi and cpi[-1] is None:
            cpi.pop()
        if not any(v is not None for v in cpi):
            continue
        # wb years as compact [start, end] ranges
        ranges = []
        for y in wb_years:
            if ranges and ranges[-1][1] == y - 1:
                ranges[-1][1] = y
            else:
                ranges.append([y, y])
        name = NAME_FIX.get(code) or imf_names.get(code) or (info["name"] if info else code)
        entry = {"n": name, "c": cont, "r": region_aggregate(code, cont, wb_region), "cpi": cpi}
        if ranges:
            entry["wb"] = ranges
        gdp = series(imf_gdp.get(code, {}), 1980, y1)
        lur = series(imf_lur.get(code, {}), 1980, y1)
        if any(v is not None for v in gdp):
            entry["gdp"] = gdp
        if any(v is not None for v in lur):
            entry["lur"] = lur
        num = numeric.get(wb_code) or numeric.get(code)
        if num:
            entry["iso"] = num
        if info and info["incomeLevel"]["value"]:
            entry["inc"] = info["incomeLevel"]["value"]
        countries[code] = entry

    regions = {k: {"n": n, "cpi": series(imf_cpi.get(k, {}), 1980, y1)} for k, n in REGIONS.items()}

    data = {
        "meta": {
            "built": TODAY.isoformat(),
            "y0": Y0, "imfY0": 1980, "y1": y1, "proj": PROJ_FROM,
            "imf": weo, "wb": wb_meta.get("lastupdated"),
        },
        "regions": regions,
        "countries": countries,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(countries)} countries)")


if __name__ == "__main__":
    main()
