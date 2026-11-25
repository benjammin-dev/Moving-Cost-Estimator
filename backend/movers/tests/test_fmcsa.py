"""Tests for reading and combining FMCSA authority records. No network:
HTTP is faked."""

import json
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from movers import fmcsa
from movers.fmcsa import (
    FMCSAError,
    combine_records,
    get_json,
    is_active,
    iter_authority_api,
    iter_authority_file,
    mc_number,
    parse_dot,
)


def record(dot="00012345", docket="MC012345", common="A", contract="N", **overrides):
    """A record shaped like the real dataset (6eyk-hxee)."""
    base = {
        "docket_number": docket, "dot_number": dot,
        "legal_name": "ACME MOVING & STORAGE INC", "dba_name": "ACME MOVERS",
        "bus_street_po": "100 MAIN ST", "bus_city": "SEATTLE", "bus_state_code": "WA",
        "bus_zip_code": "98101-1234", "bus_telno": "2065550100",
        "common_stat": common, "contract_stat": contract, "hhg_chk": "Y",
    }
    return {**base, **overrides}


def http_error(code, headers=None):
    return urllib.error.HTTPError("https://example.test", code, "error", headers or {}, None)


def ok_response(body):
    response = MagicMock()
    response.read.return_value = json.dumps(body).encode()
    response.__enter__.return_value = response
    return response


class GetJsonTests(SimpleTestCase):
    def test_returns_parsed_json(self):
        opener = MagicMock(return_value=ok_response([{"a": 1}]))
        self.assertEqual(get_json("https://x.test/a", {"q": "1"}, opener=opener), [{"a": 1}])
        self.assertEqual(opener.call_args.args[0].full_url, "https://x.test/a?q=1")

    def test_retries_rate_limits_and_server_errors(self):
        opener = MagicMock(side_effect=[http_error(429), http_error(503), ok_response([])])
        waits = []
        self.assertEqual(get_json("https://x.test", opener=opener, sleep=waits.append, backoff=1), [])
        self.assertEqual(waits, [1, 2])

    def test_honours_retry_after(self):
        opener = MagicMock(side_effect=[http_error(429, {"Retry-After": "7"}), ok_response([])])
        waits = []
        get_json("https://x.test", opener=opener, sleep=waits.append)
        self.assertEqual(waits, [7.0])

    def test_gives_up_after_retries(self):
        opener = MagicMock(side_effect=http_error(500))
        with self.assertRaisesMessage(FMCSAError, "HTTP 500"):
            get_json("https://x.test", opener=opener, retries=2, sleep=lambda s: None)
        self.assertEqual(opener.call_count, 3)

    def test_does_not_retry_client_errors(self):
        opener = MagicMock(side_effect=http_error(400))
        with self.assertRaises(FMCSAError):
            get_json("https://x.test", opener=opener, sleep=lambda s: None)
        self.assertEqual(opener.call_count, 1)

    def test_connection_errors(self):
        for error in (urllib.error.URLError("boom"), TimeoutError()):
            with self.assertRaisesMessage(FMCSAError, "connection failed"):
                get_json("https://x.test", opener=MagicMock(side_effect=error), retries=0)

    def test_invalid_json_is_an_error(self):
        response = MagicMock()
        response.read.return_value = b"<html>not json</html>"
        response.__enter__.return_value = response
        with self.assertRaisesMessage(FMCSAError, "not valid JSON"):
            get_json("https://x.test", opener=MagicMock(return_value=response))


class AuthorityApiTests(SimpleTestCase):
    def test_filters_on_the_portal_and_pages_through_results(self):
        pages = [[record(docket="MC1"), record(docket="MC2")], [record(docket="MC3")]]
        calls = []

        def fetch(url, params):
            calls.append((url, params))
            return pages[len(calls) - 1]

        rows = list(iter_authority_api("wa", page_size=2, fetch=fetch))
        self.assertEqual([r["docket_number"] for r in rows], ["MC1", "MC2", "MC3"])
        url, params = calls[0]
        self.assertEqual(url, "https://data.transportation.gov/resource/6eyk-hxee.json")
        self.assertEqual(params["$where"], "bus_state_code='WA' AND hhg_chk='Y'")
        self.assertEqual(params["$order"], "docket_number")
        self.assertEqual([p["$offset"] for _, p in calls], [0, 2])
        self.assertNotIn("webKey", params)

    def test_stops_on_an_empty_page(self):
        calls = []

        def fetch(url, params):
            calls.append(params)
            return [record(), record()] if len(calls) == 1 else []

        self.assertEqual(len(list(iter_authority_api("WA", page_size=2, fetch=fetch))), 2)
        self.assertEqual(len(calls), 2)

    def test_rejects_anything_but_a_state_code(self):
        with self.assertRaises(ValueError):
            list(iter_authority_api("WA' OR 1=1 --", fetch=lambda u, p: []))

    def test_download_errors_are_reported(self):
        def fetch(url, params):
            raise FMCSAError("HTTP 503")

        with self.assertRaisesMessage(FMCSAError, "FMCSA download failed: HTTP 503"):
            list(iter_authority_api("WA", fetch=fetch))


class AuthorityFileTests(SimpleTestCase):
    def test_reads_a_csv_export_with_uppercase_headers(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("DOCKET_NUMBER,DOT_NUMBER,LEGAL_NAME,BUS_STATE_CODE,HHG_CHK,COMMON_STAT,CONTRACT_STAT\n"
                    "MC059073,00008257, HANSEN BROS ,WA,Y,A,A\n")
        self.addCleanup(Path(f.name).unlink)
        [row] = list(iter_authority_file(f.name))
        self.assertEqual(row["docket_number"], "MC059073")
        self.assertEqual(row["legal_name"], "HANSEN BROS")
        self.assertTrue(is_active(row))


class FieldParsingTests(SimpleTestCase):
    def test_parse_dot(self):
        self.assertEqual(parse_dot("00008257"), 8257)
        self.assertEqual(parse_dot(" 42 "), 42)
        for bad in (None, "", "abc", "0", "-5"):
            self.assertIsNone(parse_dot(bad), bad)

    def test_mc_number(self):
        self.assertEqual(mc_number("MC059073"), "59073")
        self.assertEqual(mc_number("mc-123"), "123")
        for not_mc in ("FF012345", "MX1", "", None, "MC", "MCABC"):
            self.assertEqual(mc_number(not_mc), "", not_mc)

    def test_is_active(self):
        self.assertTrue(is_active({"common_stat": "A", "contract_stat": "N"}))
        self.assertTrue(is_active({"common_stat": "I", "contract_stat": "A"}))
        self.assertFalse(is_active({"common_stat": "I", "contract_stat": "N"}))
        self.assertFalse(is_active({}))


class CombineRecordsTests(SimpleTestCase):
    def test_one_carrier_per_usdot_number(self):
        combined = combine_records([
            record(dot="00000001", docket="MC000100"),
            record(dot="00000001", docket="MC000200"),
            record(dot="00000002", docket="MC000300"),
        ], "WA")
        self.assertEqual(combined.records, 3)
        self.assertEqual([c.dot_number for c in combined.carriers], [1, 2])
        self.assertEqual(combined.carriers[0].mc_number, "100")  # lowest MC wins

    def test_active_record_wins_over_inactive_ones(self):
        [carrier] = combine_records([
            record(docket="MC000100", common="I", legal_name="OLD NAME"),
            record(docket="MC000200", common="A", legal_name="CURRENT NAME"),
        ], "WA").carriers
        self.assertTrue(carrier.authority_active)
        self.assertEqual(carrier.mc_number, "200")
        self.assertEqual(carrier.record["legal_name"], "CURRENT NAME")

    def test_carrier_with_only_inactive_records(self):
        [carrier] = combine_records([record(common="I", contract="I"), record(docket="MC9", common="N", contract="N")], "WA").carriers
        self.assertFalse(carrier.authority_active)

    def test_freight_forwarders_are_skipped(self):
        combined = combine_records([
            record(dot="00000001", docket="FF000100"),
            record(dot="00000002", docket="FF000200"),
            record(dot="00000002", docket="MC000300", common="I"),  # MC docket, inactive
        ], "WA")
        self.assertEqual(combined.forwarders_skipped, 1)
        [carrier] = combined.carriers
        self.assertEqual((carrier.dot_number, carrier.mc_number, carrier.authority_active), (2, "300", False))

    def test_ignores_other_states_non_household_goods_and_missing_usdot(self):
        combined = combine_records([
            record(dot="1", bus_state_code="OR"),
            record(dot="2", hhg_chk="N"),
            record(dot=""),
            record(dot="3"),
        ], "WA")
        self.assertEqual([c.dot_number for c in combined.carriers], [3])
        self.assertEqual(combined.records, 2)  # the WA household goods ones


class UrlTests(SimpleTestCase):
    def test_dataset_url(self):
        self.assertEqual(fmcsa.AUTHORITY_API_URL, "https://data.transportation.gov/resource/6eyk-hxee.json")
