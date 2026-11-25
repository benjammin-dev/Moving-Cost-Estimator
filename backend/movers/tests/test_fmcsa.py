"""Tests for the FMCSA census and QCMobile clients. No real network calls:
HTTP is faked, and QCMobile responses come from tests/fixtures/."""

import json
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from movers import fmcsa
from movers.fmcsa import (
    CarrierCheck,
    FMCSAError,
    QCMobileClient,
    census_mc_number,
    get_json,
    iter_census_api,
    iter_census_file,
    parse_carrier,
    parse_household_goods,
)

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "test-webkey-not-real-123"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def http_error(code, headers=None):
    return urllib.error.HTTPError("https://example.test", code, "error", headers or {}, None)


def ok_response(body):
    response = MagicMock()
    response.read.return_value = json.dumps(body).encode()
    response.__enter__.return_value = response
    return response


class GetJsonTests(SimpleTestCase):
    def test_returns_parsed_json(self):
        opener = MagicMock(return_value=ok_response({"a": 1}))
        self.assertEqual(get_json("https://x.test/a", {"q": "1"}, opener=opener), {"a": 1})
        self.assertEqual(opener.call_args.args[0].full_url, "https://x.test/a?q=1")

    def test_404_returns_none(self):
        opener = MagicMock(side_effect=http_error(404))
        self.assertIsNone(get_json("https://x.test", opener=opener, sleep=lambda s: None))

    def test_retries_rate_limits_and_server_errors(self):
        opener = MagicMock(side_effect=[http_error(429), http_error(503), ok_response([1])])
        waits = []
        self.assertEqual(get_json("https://x.test", opener=opener, sleep=waits.append, backoff=1), [1])
        self.assertEqual(waits, [1, 2])

    def test_honours_retry_after(self):
        opener = MagicMock(side_effect=[http_error(429, {"Retry-After": "7"}), ok_response({})])
        waits = []
        get_json("https://x.test", opener=opener, sleep=waits.append)
        self.assertEqual(waits, [7.0])

    def test_gives_up_after_retries(self):
        opener = MagicMock(side_effect=http_error(500))
        with self.assertRaisesMessage(FMCSAError, "HTTP 500"):
            get_json("https://x.test", opener=opener, retries=2, sleep=lambda s: None)
        self.assertEqual(opener.call_count, 3)

    def test_does_not_retry_client_errors(self):
        opener = MagicMock(side_effect=http_error(401))
        with self.assertRaises(FMCSAError):
            get_json("https://x.test", opener=opener, sleep=lambda s: None)
        self.assertEqual(opener.call_count, 1)

    def test_errors_never_include_the_url_or_key(self):
        cases = [http_error(401), urllib.error.URLError("boom"), TimeoutError()]
        for error in cases:
            opener = MagicMock(side_effect=error)
            with self.assertRaises(FMCSAError) as ctx:
                get_json("https://x.test/carriers/1", {"webKey": SECRET}, opener=opener, retries=0)
            self.assertNotIn(SECRET, str(ctx.exception))
            self.assertNotIn("x.test", str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)

    def test_invalid_json_is_an_error(self):
        response = MagicMock()
        response.read.return_value = b"<html>not json</html>"
        response.__enter__.return_value = response
        with self.assertRaisesMessage(FMCSAError, "not valid JSON"):
            get_json("https://x.test", opener=MagicMock(return_value=response))


class CensusApiTests(SimpleTestCase):
    def test_filters_on_the_portal_and_pages_through_results(self):
        pages = [[{"dot_number": "1"}, {"dot_number": "2"}], [{"dot_number": "3"}]]
        calls = []

        def fetch(url, params):
            calls.append(params)
            return pages[len(calls) - 1]

        rows = list(iter_census_api("WA", page_size=2, fetch=fetch))
        self.assertEqual([r["dot_number"] for r in rows], ["1", "2", "3"])
        self.assertEqual([c["$offset"] for c in calls], [0, 2])
        self.assertEqual(calls[0]["$where"], "phy_state='WA' AND crgo_household='X' AND status_code='A'")
        self.assertEqual(calls[0]["$order"], "dot_number")
        # Private columns aren't downloaded.
        for column in ("email_address", "company_officer_1", "cell_phone"):
            self.assertNotIn(column, calls[0]["$select"])

    def test_stops_on_an_empty_page(self):
        calls = []

        def fetch(url, params):
            calls.append(params)
            return [{"dot_number": "1"}, {"dot_number": "2"}] if len(calls) == 1 else []

        self.assertEqual(len(list(iter_census_api("WA", page_size=2, fetch=fetch))), 2)
        self.assertEqual(len(calls), 2)

    def test_rejects_anything_but_a_state_code(self):
        with self.assertRaises(ValueError):
            list(iter_census_api("WA' OR 1=1 --", fetch=lambda u, p: []))

    def test_download_errors_are_reported(self):
        def fetch(url, params):
            raise FMCSAError("HTTP 503")

        with self.assertRaisesMessage(FMCSAError, "Census download failed: HTTP 503"):
            list(iter_census_api("WA", fetch=fetch))


class CensusFileTests(SimpleTestCase):
    def test_reads_a_downloaded_csv_and_applies_the_same_filters(self):
        csv_text = (
            "DOT_NUMBER,LEGAL_NAME,PHY_STATE,CRGO_HOUSEHOLD,STATUS_CODE\n"
            "1,WA MOVER,WA,X,A\n"
            "2,OREGON MOVER,OR,X,A\n"
            "3,WA FREIGHT,WA,,A\n"
            "4,WA INACTIVE,WA,X,I\n"
            "5,lowercase ok,wa,x,a\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(csv_text)
        self.addCleanup(Path(f.name).unlink)
        rows = list(iter_census_file(f.name, "WA"))
        self.assertEqual([r["dot_number"] for r in rows], ["1", "5"])
        self.assertEqual(rows[0]["legal_name"], "WA MOVER")


class CensusMcNumberTests(SimpleTestCase):
    def test_finds_the_mc_docket_in_any_slot(self):
        self.assertEqual(census_mc_number({"docket1prefix": "MC", "docket1": "123456"}), "123456")
        self.assertEqual(census_mc_number({"docket1prefix": "FF", "docket1": "9", "docket2prefix": "MC", "docket2": "77"}), "77")
        self.assertEqual(census_mc_number({"docket1prefix": "FF", "docket1": "9"}), "")
        self.assertEqual(census_mc_number({}), "")


class QCMobileParsingTests(SimpleTestCase):
    def test_carrier_allowed_to_operate(self):
        self.assertEqual(parse_carrier(fixture("qcmobile_carrier_allowed.json")), (True, True, False))

    def test_carrier_not_allowed_to_operate(self):
        self.assertEqual(parse_carrier(fixture("qcmobile_carrier_not_allowed.json")), (True, False, False))

    def test_carrier_out_of_service(self):
        self.assertEqual(parse_carrier(fixture("qcmobile_carrier_out_of_service.json")), (True, True, True))

    def test_unrecognised_carrier_responses_never_qualify(self):
        for data in (None, {}, [], {"content": None}, {"content": []}, {"content": {"carrier": None}}, "oops"):
            found, allowed, _ = parse_carrier(data)
            self.assertFalse(found and allowed, data)

    def test_household_goods_in_cargo(self):
        self.assertTrue(parse_household_goods(fixture("qcmobile_cargo_household_goods.json")))
        self.assertFalse(parse_household_goods(fixture("qcmobile_cargo_general_freight.json")))

    def test_unrecognised_cargo_responses_never_qualify(self):
        for data in (None, {}, {"content": None}, {"content": {}}, {"content": ["Household Goods"]}, "oops"):
            self.assertFalse(parse_household_goods(data), data)


class QCMobileClientTests(SimpleTestCase):
    def make_client(self, responses):
        calls = []

        def fetch(url, params):
            calls.append((url, params))
            return responses[url.rsplit("/", 1)[-1]]

        return QCMobileClient(SECRET, fetch=fetch, base_url="https://qc.test"), calls

    def test_confirms_an_allowed_household_goods_carrier(self):
        client, calls = self.make_client({
            "1234567": fixture("qcmobile_carrier_allowed.json"),
            "cargo-carried": fixture("qcmobile_cargo_household_goods.json"),
        })
        check = client.check(1234567)
        self.assertTrue(check.qualifies)
        self.assertEqual([url for url, _ in calls], [
            "https://qc.test/carriers/1234567",
            "https://qc.test/carriers/1234567/cargo-carried",
        ])
        self.assertTrue(all(params == {"webKey": SECRET} for _, params in calls))

    def test_skips_the_cargo_lookup_for_carriers_not_allowed_to_operate(self):
        client, calls = self.make_client({"1234567": fixture("qcmobile_carrier_not_allowed.json")})
        check = client.check(1234567)
        self.assertFalse(check.qualifies)
        self.assertEqual(check.reason, "not allowed to operate")
        self.assertEqual(len(calls), 1)

    def test_not_found(self):
        client, _ = self.make_client({"1234567": None})
        check = client.check(1234567)
        self.assertEqual(check, CarrierCheck(found=False))
        self.assertEqual(check.reason, "not found in QCMobile")

    def test_general_freight_carrier_is_rejected(self):
        client, _ = self.make_client({
            "1234567": fixture("qcmobile_carrier_allowed.json"),
            "cargo-carried": fixture("qcmobile_cargo_general_freight.json"),
        })
        self.assertEqual(client.check(1234567).reason, "household goods not listed in cargo carried")

    def test_errors_say_which_lookup_failed_without_the_key(self):
        def fetch(url, params):
            raise FMCSAError("HTTP 401")

        client = QCMobileClient(SECRET, fetch=fetch)
        with self.assertRaises(FMCSAError) as ctx:
            client.check(1234567)
        self.assertEqual(str(ctx.exception), "QCMobile carrier lookup failed: HTTP 401")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_requires_a_key(self):
        with self.assertRaises(ValueError):
            QCMobileClient("")


class RealUrlTests(SimpleTestCase):
    """Guards against typos in the live URLs (nothing is fetched)."""

    def test_urls(self):
        self.assertEqual(fmcsa.CENSUS_API_URL, "https://data.transportation.gov/resource/az4n-8mr2.json")
        self.assertEqual(fmcsa.QCMOBILE_BASE_URL, "https://mobile.fmcsa.dot.gov/qc/services")
