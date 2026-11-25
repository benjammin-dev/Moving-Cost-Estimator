"""Reads the Washington Utilities and Transportation Commission's public
"regulated companies" lookup (https://www.utc.wa.gov/companies): household
goods carriers, their UTC status and, from each company's detail page, the
household goods permit number, address and phone.

There's no API, so this reads the HTML pages. Columns and sections are found
by their headings, not their position, so small layout changes don't
silently shift values. Requests are paced (one a second by default); the
page isn't disallowed by the site's robots.txt. Contact names and email
addresses are never kept.
"""

import re
import time
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

from .http import FetchError, fetch

UTC_BASE_URL = "https://www.utc.wa.gov"
COMPANIES_URL = f"{UTC_BASE_URL}/companies"
HOUSEHOLD_GOODS_FILTER = "568"  # "Household Goods Carriers" in the lookup's industry filter
HOUSEHOLD_GOODS_CODE = "207"  # the industry code on detail pages
MAX_LIST_PAGES = 200

# Same class as http.FetchError; the UTC name is kept for readability.
UTCError = FetchError


def company_url(company_id):
    return f"{UTC_BASE_URL}/company/{int(company_id)}"


# ---------------------------------------------------------------------------
# HTML tables
# ---------------------------------------------------------------------------

@dataclass
class Table:
    heading: str
    rows: list = field(default_factory=list)  # each row: list of (text, [hrefs])


class _TableParser(HTMLParser):
    """Collects every <table> with the nearest heading before it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._heading = ""
        self._in_heading = False
        self._heading_text = []
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self._in_heading, self._heading_text = True, []
        elif tag == "table":
            self._table = Table(heading=self._heading)
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = ([], [])
        elif tag == "a" and self._cell is not None:
            href = dict(attrs).get("href")
            if href:
                self._cell[1].append(href)
        elif tag == "br" and self._cell is not None:
            self._cell[0].append(" ")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4") and self._in_heading:
            self._in_heading = False
            self._heading = _squash("".join(self._heading_text))
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append((_squash("".join(self._cell[0])), self._cell[1]))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if self._in_heading:
            self._heading_text.append(data)
        if self._cell is not None:
            self._cell[0].append(data)


def _squash(text):
    return " ".join(unescape(text).split())


def parse_tables(html):
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    return parser.tables


def _records(table):
    """Rows as dicts keyed by the header row's column names."""
    if not table.rows:
        return []
    header = [text.lower() for text, _ in table.rows[0]]
    return [
        {name: cell for name, cell in zip(header, row)}
        for row in table.rows[1:]
        if len(row) == len(header)
    ]


def _status(text):
    """"[Active] See company detail to verify status" -> "Active"."""
    match = re.search(r"\[\s*([A-Za-z ]+?)\s*\]", text or "")
    return (match.group(1) if match else (text or "").split(" ")[0]).strip().title()


def _usdot(text):
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits and int(digits) > 0 else None


# ---------------------------------------------------------------------------
# List pages
# ---------------------------------------------------------------------------

@dataclass
class ListedCompany:
    company_id: int
    name: str
    dba_name: str
    usdot_number: int | None
    status: str  # "Active", "Pending", "Unregulated", "Inactive", ...


def parse_list_page(html):
    """Companies on one page of the lookup's results table."""
    companies = []
    for table in parse_tables(html):
        for record in _records(table):
            if "name" not in record or "status" not in record:
                continue
            hrefs = [h for _, links in record.values() for h in links]
            company_id = next((int(m.group(1)) for h in hrefs if (m := re.search(r"/company/(\d+)", h))), None)
            if company_id is None:
                continue
            dba = record.get("dba", ("", []))[0]
            companies.append(ListedCompany(
                company_id=company_id,
                name=record["name"][0],
                dba_name=re.sub(r"^DBA:\s*", "", dba, flags=re.I),
                usdot_number=_usdot(record.get("usdot", ("", []))[0]),
                status=_status(record["status"][0]),
            ))
    return companies


def iter_listed_companies(*, fetch_html=None, sleep=time.sleep, sleep_seconds=1.0):
    """Every household goods carrier in the lookup, all statuses, page by page."""
    fetch_html = fetch_html or get_html
    for page in range(MAX_LIST_PAGES):
        if page and sleep_seconds:
            sleep(sleep_seconds)
        try:
            html = fetch_html(COMPANIES_URL, {
                "exposed_select_industry": HOUSEHOLD_GOODS_FILTER,
                "regulatory_status": "All",
                "page": page,
            })
        except UTCError as err:
            raise UTCError(f"UTC list download failed: {err}") from None
        companies = parse_list_page(html)
        if not companies:
            return
        yield from companies
    raise UTCError(f"UTC list has more than {MAX_LIST_PAGES} pages; stopping in case the page layout changed.")


# ---------------------------------------------------------------------------
# Detail pages
# ---------------------------------------------------------------------------

@dataclass
class CompanyDetail:
    company_id: int | None
    name: str = ""
    dba_name: str = ""
    status: str = ""
    phone: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    usdot_number: int | None = None  # from the household goods permit row
    permit_number: str = ""  # e.g. "HG060620"; only an active household goods permit
    permit_type: str = ""  # "Permanent" or "Temporary"


def split_address(address):
    """"21086 24th Ave S, Suite 125, Seatac, WA 98148" ->
    ("21086 24th Ave S, Suite 125", "Seatac", "WA", "98148")."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) >= 3:
        match = re.fullmatch(r"([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)?", parts[-1])
        if match:
            return ", ".join(parts[:-2]), parts[-2], match.group(1).upper(), match.group(2) or ""
    return ", ".join(parts), "", "", ""


def parse_detail_page(html):
    tables = {t.heading.lower(): t for t in parse_tables(html)}
    detail = CompanyDetail(company_id=None)

    basic = _records(tables.get("basic information", Table("")))
    if basic:
        row = basic[0]
        detail.company_id = _usdot(row.get("utc id", ("", []))[0])
        detail.name = row.get("company name", ("", []))[0]
        detail.dba_name = row.get("dba(s)", ("", []))[0]
        detail.status = _status(row.get("status", ("", []))[0])

    contacts = _records(tables.get("company contacts", Table("")))
    primary = next((c for c in contacts if c.get("contact type", ("", []))[0].lower() == "primary"), contacts[0] if contacts else None)
    if primary:
        detail.phone = primary.get("phone", ("", []))[0]

    addresses = {}
    for row in tables.get("company address", Table("")).rows[1:]:
        if len(row) >= 2:
            addresses[row[0][0].lower()] = row[1][0]
    address = addresses.get("physical address") or addresses.get("mailing address") or ""
    detail.street, detail.city, detail.state, detail.zip_code = split_address(address)

    for permit in _records(tables.get("permits / industry", Table(""))):
        if permit.get("code", ("", []))[0] != HOUSEHOLD_GOODS_CODE:
            continue
        detail.usdot_number = _usdot(permit.get("usdot", ("", []))[0])
        number = permit.get("active permit(s)", ("", []))[0].split(" ")[0].upper()
        if _status(permit.get("status", ("", []))[0]) == "Active" and re.fullmatch(r"[A-Z]{2}\d{3,8}", number):
            detail.permit_number = number
            detail.permit_type = permit.get("perm or temp", ("", []))[0]
        break
    return detail


def get_detail(company_id, *, fetch_html=None):
    fetch_html = fetch_html or get_html
    try:
        return parse_detail_page(fetch_html(company_url(company_id), None))
    except UTCError as err:
        raise UTCError(f"UTC company {company_id} page failed: {err}") from None


def get_html(url, params=None, **kwargs):
    return fetch(url, params, accept="text/html", **kwargs).decode("utf-8", errors="replace")
