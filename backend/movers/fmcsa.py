"""Reads FMCSA's "Carrier - All With History" dataset (6eyk-hxee on
data.transportation.gov): carriers with federal operating authority, with a
household goods flag. Public, no API key. Standard library only.

The dataset was last refreshed on 2026-05-14 and FMCSA says it "will no
longer be updated", so treat it as a snapshot. It only covers carriers with
federal (interstate) authority, so local-only movers aren't in it; they get
in by listing themselves.
"""

import csv
import json
import re
import time
import urllib.request
from dataclasses import dataclass

from .http import FetchError, fetch

AUTHORITY_API_URL = "https://data.transportation.gov/resource/6eyk-hxee.json"

# Columns the importer uses; selecting only these keeps the download small.
AUTHORITY_FIELDS = [
    "docket_number", "dot_number", "legal_name", "dba_name",
    "bus_street_po", "bus_city", "bus_state_code", "bus_zip_code", "bus_telno",
    "common_stat", "contract_stat", "hhg_chk",
]

# Same class as http.FetchError; the FMCSA name is kept for readability.
FMCSAError = FetchError


def get_json(url, params=None, *, opener=urllib.request.urlopen, sleep=time.sleep, **kwargs):
    """GET a JSON URL and return the parsed body (retries as in http.fetch)."""
    body = fetch(url, params, accept="application/json", opener=opener, sleep=sleep, **kwargs)
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise FMCSAError("response was not valid JSON") from None


# ---------------------------------------------------------------------------
# Reading records
# ---------------------------------------------------------------------------

def check_state(state):
    if not (isinstance(state, str) and len(state) == 2 and state.isalpha()):
        raise ValueError(f"Not a state code: {state!r}")
    return state.upper()


def iter_authority_api(state, *, page_size=5000, fetch=get_json):
    """Household goods authority records (active and inactive) for carriers
    based in `state`. Filtered by the portal, so only those rows download.
    Inactive records are needed to tell when a carrier's authority lapsed."""
    state = check_state(state)
    offset = 0
    while True:
        try:
            page = fetch(AUTHORITY_API_URL, {
                "$select": ",".join(AUTHORITY_FIELDS),
                "$where": f"bus_state_code='{state}' AND hhg_chk='Y'",
                "$order": "docket_number",
                "$limit": page_size,
                "$offset": offset,
            })
        except FMCSAError as err:
            raise FMCSAError(f"FMCSA download failed: {err}") from None
        if not page:
            return
        yield from page
        if len(page) < page_size:
            return
        offset += page_size


def iter_authority_file(path):
    """Records from a CSV export of the dataset. Column names are matched
    case-insensitively, so the portal's uppercase headers work."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        for raw in csv.DictReader(f):
            yield {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Interpreting records
# ---------------------------------------------------------------------------

def _upper(row, field):
    return (row.get(field) or "").strip().upper()


def is_household_goods_record(row, state):
    return _upper(row, "bus_state_code") == state and _upper(row, "hhg_chk") == "Y"


def is_active(row):
    """Only an active common or contract authority counts."""
    return _upper(row, "common_stat") == "A" or _upper(row, "contract_stat") == "A"


def parse_dot(value):
    """USDOT numbers come zero-padded ("00008257")."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def mc_number(docket):
    """"MC059073" -> "59073". Anything that isn't an MC docket (e.g. FF,
    a freight forwarder) -> ""."""
    match = re.fullmatch(r"MC-?0*(\d+)", (docket or "").strip().upper())
    return match.group(1) if match else ""


@dataclass
class Carrier:
    """One carrier, combined from all of its household goods records."""
    dot_number: int
    mc_number: str
    authority_active: bool
    record: dict  # the record its name, address and phone come from


@dataclass
class CombinedRecords:
    carriers: list
    records: int = 0
    forwarders_skipped: int = 0  # carriers with only FF (freight forwarder) dockets


def combine_records(rows, state):
    """Group household goods records in `state` by USDOT number. Only MC
    (motor carrier) dockets count; a carrier with nothing but freight
    forwarder dockets is skipped. A carrier's authority is active if any of
    its MC records is, and its details come from that record (lowest MC
    number first when there are several)."""
    state = check_state(state)
    combined = CombinedRecords(carriers=[])
    by_dot = {}
    for row in rows:
        if not is_household_goods_record(row, state):
            continue
        combined.records += 1
        dot = parse_dot(row.get("dot_number"))
        if dot is not None:
            by_dot.setdefault(dot, []).append(row)

    for dot in sorted(by_dot):
        mc_rows = [r for r in by_dot[dot] if mc_number(r.get("docket_number"))]
        if not mc_rows:
            combined.forwarders_skipped += 1
            continue
        active = [r for r in mc_rows if is_active(r)]
        chosen = min(active or mc_rows, key=lambda r: int(mc_number(r.get("docket_number"))))
        combined.carriers.append(Carrier(
            dot_number=dot,
            mc_number=mc_number(chosen.get("docket_number")),
            authority_active=bool(active),
            record=chosen,
        ))
    return combined
