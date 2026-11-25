"""Tests for reading the UTC lookup pages, using trimmed copies of real
utc.wa.gov pages saved in fixtures/. No network."""

from pathlib import Path

from django.test import SimpleTestCase

from movers import utc
from movers.utc import UTCError, get_detail, iter_listed_companies, parse_detail_page, parse_list_page, split_address

FIXTURES = Path(__file__).parent / "fixtures"


def page(name):
    return (FIXTURES / name).read_text()


class ListPageTests(SimpleTestCase):
    def test_reads_companies_and_their_status(self):
        companies = parse_list_page(page("utc_list_page.html"))
        self.assertEqual(len(companies), 6)
        by_name = {c.name: c for c in companies}
        perfect = by_name["A Perfect Mover LLC"]
        self.assertEqual((perfect.status, perfect.usdot_number), ("Active", 3264337))
        self.assertEqual(perfect.dba_name, "A Perfect Mover")  # "DBA: " removed
        self.assertIsInstance(perfect.company_id, int)
        self.assertEqual(by_name["12 Man Movers"].status, "Unregulated")
        self.assertIsNone(by_name["12 Man Movers"].usdot_number)
        self.assertEqual(by_name["1 Heart Movers, LLC"].status, "Inactive")

    def test_an_empty_results_page_has_no_companies(self):
        self.assertEqual(parse_list_page(page("utc_list_empty.html")), [])

    def test_pages_until_an_empty_page(self):
        calls = []

        def fetch_html(url, params):
            calls.append(params)
            return page("utc_list_page.html") if len(calls) < 3 else page("utc_list_empty.html")

        waits = []
        companies = list(iter_listed_companies(fetch_html=fetch_html, sleep=waits.append, sleep_seconds=1.0))
        self.assertEqual(len(companies), 12)
        self.assertEqual([c["page"] for c in calls], [0, 1, 2])
        self.assertEqual(calls[0]["exposed_select_industry"], "568")
        self.assertEqual(calls[0]["regulatory_status"], "All")
        self.assertEqual(waits, [1.0, 1.0])  # polite pause between pages

    def test_stops_if_the_list_never_ends(self):
        with self.assertRaisesMessage(UTCError, "more than"):
            list(iter_listed_companies(fetch_html=lambda u, p: page("utc_list_page.html"), sleep=lambda s: None))

    def test_download_errors_are_reported(self):
        def fetch_html(url, params):
            raise UTCError("HTTP 503")

        with self.assertRaisesMessage(UTCError, "UTC list download failed: HTTP 503"):
            list(iter_listed_companies(fetch_html=fetch_html))


class DetailPageTests(SimpleTestCase):
    def test_active_company_with_a_household_goods_permit(self):
        detail = parse_detail_page(page("utc_detail_active.html"))
        self.assertEqual(detail.company_id, 41219)
        self.assertEqual(detail.name, "Gentle Giant Moving Company (West), LLC")
        self.assertEqual(detail.dba_name, "Gentle Giant Moving & Storage")
        self.assertEqual(detail.status, "Active")
        self.assertEqual((detail.permit_number, detail.permit_type), ("HG060620", "Permanent"))
        self.assertEqual(detail.usdot_number, 373544)
        # Physical address wins over the out-of-state mailing address.
        self.assertEqual((detail.street, detail.city, detail.state, detail.zip_code),
                         ("21086 24th Avenue South, Suite 125", "Seatac", "WA", "98148"))
        self.assertEqual(detail.phone, "800-442-6863")

    def test_uses_the_household_goods_permit_not_other_industries(self):
        detail = parse_detail_page(page("utc_detail_two_permits.html"))
        self.assertEqual(detail.permit_number, "HG068131")  # not the CC freight permit
        self.assertEqual(detail.usdot_number, 3074631)

    def test_unregulated_company_has_no_permit_but_keeps_contact_details(self):
        detail = parse_detail_page(page("utc_detail_unregulated.html"))
        self.assertEqual((detail.status, detail.permit_number, detail.usdot_number), ("Unregulated", "", None))
        self.assertEqual((detail.city, detail.zip_code, detail.phone), ("Seattle", "98122-3936", "(425) 745-9047"))

    def test_never_keeps_contact_names_or_emails(self):
        for name in ("utc_detail_active.html", "utc_detail_two_permits.html", "utc_detail_unregulated.html"):
            values = vars(parse_detail_page(page(name))).values()
            self.assertFalse(any("@" in str(v) for v in values), name)

    def test_an_unexpected_page_gives_an_empty_detail(self):
        detail = parse_detail_page("<html><body><p>Down for maintenance</p></body></html>")
        self.assertEqual((detail.company_id, detail.permit_number, detail.status), (None, "", ""))

    def test_get_detail_reports_failures(self):
        def fetch_html(url, params):
            self.assertEqual(url, "https://www.utc.wa.gov/company/41219")
            raise UTCError("HTTP 500")

        with self.assertRaisesMessage(UTCError, "UTC company 41219 page failed: HTTP 500"):
            get_detail(41219, fetch_html=fetch_html)


class AddressTests(SimpleTestCase):
    def test_split_address(self):
        self.assertEqual(split_address("1206 E Pike St, Seattle, WA 98122-3936"), ("1206 E Pike St", "Seattle", "WA", "98122-3936"))
        self.assertEqual(split_address("PO Box 1, Suite 2, Spokane, wa 99201"), ("PO Box 1, Suite 2", "Spokane", "WA", "99201"))
        self.assertEqual(split_address("Somewhere odd"), ("Somewhere odd", "", "", ""))
        self.assertEqual(split_address(""), ("", "", "", ""))

    def test_company_url(self):
        self.assertEqual(utc.company_url(41219), "https://www.utc.wa.gov/company/41219")
