"""Clients for FMCSA's free public data: the Company Census File and the
QCMobile API. Standard library only, no extra dependencies.

The QCMobile webKey goes in a query string, so URLs are never put in error
messages or logs.
"""

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Company Census File on the DOT open data portal (dataset az4n-8mr2).
CENSUS_API_URL = "https://data.transportation.gov/resource/az4n-8mr2.json"
QCMOBILE_BASE_URL = "https://mobile.fmcsa.dot.gov/qc/services"
USER_AGENT = "moving-cost-estimator-mover-import"

# Census columns the importer uses. Selecting only these keeps the download
# small and leaves out data we don't store (officer names, emails, cells).
CENSUS_FIELDS = [
    "dot_number", "legal_name", "dba_name",
    "phy_street", "phy_city", "phy_state", "phy_zip", "phone",
    "status_code", "crgo_household", "carrier_operation",
    "docket1prefix", "docket1", "docket2prefix", "docket2", "docket3prefix", "docket3",
]

RETRY_STATUSES = {429, 500, 502, 503, 504}


class FMCSAError(Exception):
    """A request to an FMCSA service failed. The message never includes the URL."""


def get_json(url, params=None, *, retries=3, backoff=1.0, timeout=30,
             opener=urllib.request.urlopen, sleep=time.sleep):
    """GET a JSON URL. Returns the parsed body, or None on 404. Retries
    rate-limit and server errors with a growing wait between attempts."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    request = urllib.request.Request(full_url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if err.code not in RETRY_STATUSES or attempt == retries:
                raise FMCSAError(f"HTTP {err.code}") from None
            sleep(_retry_after(err) or backoff * 2 ** attempt)
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == retries:
                reason = getattr(err, "reason", err)
                kind = type(reason).__name__ if isinstance(reason, BaseException) else "network error"
                raise FMCSAError(f"connection failed ({kind})") from None
            sleep(backoff * 2 ** attempt)
        except ValueError:
            raise FMCSAError("response was not valid JSON") from None


def _retry_after(err):
    try:
        return max(0.0, float(err.headers.get("Retry-After")))
    except (TypeError, ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Company Census File
# ---------------------------------------------------------------------------

def is_candidate(row, state):
    """Active carrier based in `state` that lists household goods as cargo."""
    return (
        (row.get("phy_state") or "").strip().upper() == state
        and (row.get("crgo_household") or "").strip().upper() == "X"
        and (row.get("status_code") or "").strip().upper() == "A"
    )


def iter_census_api(state, *, page_size=1000, fetch=get_json):
    """Census rows for active household goods carriers in `state`, filtered
    by the portal so only matching rows are downloaded."""
    if not (len(state) == 2 and state.isalpha()):
        raise ValueError(f"Not a state code: {state!r}")
    where = f"phy_state='{state.upper()}' AND crgo_household='X' AND status_code='A'"
    offset = 0
    while True:
        try:
            page = fetch(CENSUS_API_URL, {
                "$select": ",".join(CENSUS_FIELDS),
                "$where": where,
                "$order": "dot_number",
                "$limit": page_size,
                "$offset": offset,
            })
        except FMCSAError as err:
            raise FMCSAError(f"Census download failed: {err}") from None
        if not page:
            return
        yield from page
        if len(page) < page_size:
            return
        offset += page_size


def iter_census_file(path, state):
    """Census rows from a downloaded CSV, filtered to the same carriers as
    iter_census_api. Column names are matched case-insensitively."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if is_candidate(row, state):
                yield row


def census_mc_number(row):
    """The MC docket number from a census row, if it has one."""
    for n in (1, 2, 3):
        if (row.get(f"docket{n}prefix") or "").strip().upper() == "MC" and (row.get(f"docket{n}") or "").strip():
            return row[f"docket{n}"].strip()
    return ""


# ---------------------------------------------------------------------------
# QCMobile API
# ---------------------------------------------------------------------------

@dataclass
class CarrierCheck:
    found: bool
    allowed_to_operate: bool = False
    out_of_service: bool = False
    household_goods: bool = False

    @property
    def qualifies(self):
        return self.found and self.allowed_to_operate and not self.out_of_service and self.household_goods

    @property
    def reason(self):
        if not self.found:
            return "not found in QCMobile"
        if not self.allowed_to_operate:
            return "not allowed to operate"
        if self.out_of_service:
            return "out of service"
        if not self.household_goods:
            return "household goods not listed in cargo carried"
        return "qualifies"


# --- PLACEHOLDER RESPONSE FORMAT --------------------------------------------
# FMCSA doesn't document the response bodies for these endpoints. The two
# parsers below are a best guess and MUST be checked against real responses
# (saved in movers/tests/fixtures/) before this is merged. Both fail safe:
# anything unrecognised means "doesn't qualify", never a false confirmation.

def parse_carrier(data):
    """Returns (found, allowed_to_operate, out_of_service)."""
    content = (data or {}).get("content") if isinstance(data, dict) else None
    carrier = content.get("carrier") if isinstance(content, dict) else None
    if not isinstance(carrier, dict):
        return False, False, False
    allowed = _is_yes(carrier.get("allowedToOperate", carrier.get("allowToOperate")))
    out_of_service = _is_yes(carrier.get("outOfService")) or bool(carrier.get("oosDate") or carrier.get("outOfServiceDate"))
    return True, allowed, out_of_service


def parse_household_goods(data):
    """True if the cargo-carried response lists household goods."""
    content = (data or {}).get("content") if isinstance(data, dict) else None
    if not isinstance(content, list):
        return False
    return any(
        "household goods" in str(item.get("cargoClassDesc", "")).lower()
        for item in content if isinstance(item, dict)
    )

# --- END PLACEHOLDER ---------------------------------------------------------


def _is_yes(value):
    return str(value).strip().upper() in {"Y", "YES", "TRUE"}


class QCMobileClient:
    def __init__(self, webkey, *, fetch=get_json, base_url=QCMOBILE_BASE_URL):
        if not webkey:
            raise ValueError("A QCMobile webKey is required.")
        self._webkey = webkey
        self._fetch = fetch
        self._base_url = base_url

    def _get(self, path):
        try:
            return self._fetch(f"{self._base_url}/{path}", {"webKey": self._webkey})
        except FMCSAError as err:
            label = "cargo-carried" if path.endswith("cargo-carried") else "carrier"
            raise FMCSAError(f"QCMobile {label} lookup failed: {err}") from None

    def check(self, dot_number):
        """Look the carrier up, then check its cargo only if it's allowed to
        operate (saves a request for carriers that would be rejected anyway)."""
        found, allowed, oos = parse_carrier(self._get(f"carriers/{int(dot_number)}"))
        if not (found and allowed and not oos):
            return CarrierCheck(found=found, allowed_to_operate=allowed, out_of_service=oos)
        hhg = parse_household_goods(self._get(f"carriers/{int(dot_number)}/cargo-carried"))
        return CarrierCheck(found=True, allowed_to_operate=True, out_of_service=False, household_goods=hhg)
