"""Tests for `manage.py import_fmcsa_movers`. The census download and the
QCMobile client are replaced with fakes, so nothing touches the network."""

from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from movers.fmcsa import CarrierCheck, FMCSAError
from movers.models import Mover

KEY = "test-webkey-not-real-456"
COMMAND = "movers.management.commands.import_fmcsa_movers"
QUALIFIES = CarrierCheck(found=True, allowed_to_operate=True, out_of_service=False, household_goods=True)


def census_row(dot):
    return {"dot_number": str(dot), "legal_name": f"CARRIER {dot}", "phy_state": "WA",
            "crgo_household": "X", "status_code": "A"}


class FakeClient:
    def __init__(self, webkey, failures=()):
        self.webkey = webkey
        self.failures = failures

    def check(self, dot):
        if dot in self.failures:
            raise FMCSAError(f"QCMobile carrier lookup failed: HTTP 500 for {self.webkey}")
        return QUALIFIES


@override_settings(FMCSA_WEBKEY=KEY)
class ImportCommandTests(TestCase):
    def call(self, *args, rows=(), failures=()):
        out, err = StringIO(), StringIO()
        with patch(f"{COMMAND}.iter_census_api", return_value=iter(rows)) as census, \
                patch(f"{COMMAND}.QCMobileClient", side_effect=lambda key: FakeClient(key, failures)):
            call_command("import_fmcsa_movers", "--sleep", "0", *args, stdout=out, stderr=err)
        self.census = census
        return out.getvalue(), err.getvalue()

    def test_imports_and_prints_a_summary(self):
        out, _ = self.call(rows=[census_row(1), census_row(2)])
        self.census.assert_called_once_with("WA")
        self.assertEqual(Mover.objects.count(), 2)
        self.assertIn("Checked 2 carriers: 2 confirmed (2 new, 0 updated), 0 rejected, 0 set inactive, 0 errors.", out)

    def test_dry_run_saves_nothing(self):
        out, _ = self.call("--dry-run", rows=[census_row(1)])
        self.assertFalse(Mover.objects.exists())
        self.assertIn("Dry run, nothing saved.", out)

    def test_errors_are_reported_without_the_key(self):
        out, err = self.call(rows=[census_row(1), census_row(2)], failures={2})
        self.assertEqual(Mover.objects.count(), 1)
        self.assertIn("USDOT 2", err)
        self.assertIn("1 errors", out)
        self.assertIn("Re-run to retry them", out)
        self.assertNotIn(KEY, out + err)

    def test_census_download_failure_is_a_clear_error(self):
        def failing(state):
            raise FMCSAError("Census download failed: HTTP 503")
            yield  # pragma: no cover

        with patch(f"{COMMAND}.iter_census_api", side_effect=failing), \
                patch(f"{COMMAND}.QCMobileClient", side_effect=lambda key: FakeClient(key)):
            with self.assertRaisesMessage(CommandError, "Census download failed: HTTP 503"):
                call_command("import_fmcsa_movers", "--sleep", "0", stdout=StringIO(), stderr=StringIO())

    def test_reads_a_downloaded_census_file(self):
        with NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("DOT_NUMBER,LEGAL_NAME,PHY_STATE,CRGO_HOUSEHOLD,STATUS_CODE\n7,FILE MOVER,WA,X,A\n8,OREGON,OR,X,A\n")
        self.addCleanup(Path(f.name).unlink)
        with patch(f"{COMMAND}.iter_census_api") as census, \
                patch(f"{COMMAND}.QCMobileClient", side_effect=lambda key: FakeClient(key)):
            call_command("import_fmcsa_movers", "--sleep", "0", "--census-file", f.name, stdout=StringIO(), stderr=StringIO())
        census.assert_not_called()
        self.assertEqual(list(Mover.objects.values_list("usdot_number", flat=True)), [7])

    def test_rejects_bad_options(self):
        for args, message in [
            (["--census-file", "/no/such/file.csv"], "Census file not found"),
            (["--state", "Washington"], "two-letter state code"),
            (["--limit", "0"], "--limit must be at least 1"),
            (["--sleep", "-1"], "--sleep can't be negative"),
        ]:
            with self.subTest(args=args), self.assertRaisesMessage(CommandError, message):
                call_command("import_fmcsa_movers", *args, stdout=StringIO(), stderr=StringIO())

    @override_settings(FMCSA_WEBKEY="")
    def test_missing_key_is_a_clear_error(self):
        with self.assertRaisesMessage(CommandError, "FMCSA_WEBKEY is not set"):
            call_command("import_fmcsa_movers", stdout=StringIO(), stderr=StringIO())
