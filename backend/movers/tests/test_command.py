"""Tests for `manage.py import_fmcsa_movers`. The download is replaced with
sample records, so nothing touches the network."""

from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from movers.fmcsa import FMCSAError
from movers.models import Mover
from movers.tests.test_fmcsa import record

COMMAND = "movers.management.commands.import_fmcsa_movers"


class ImportCommandTests(TestCase):
    def call(self, *args, rows=()):
        out, err = StringIO(), StringIO()
        with patch(f"{COMMAND}.iter_authority_api", return_value=iter(rows)) as download:
            call_command("import_fmcsa_movers", *args, stdout=out, stderr=err)
        self.download = download
        return out.getvalue(), err.getvalue()

    def test_imports_without_any_api_key_and_prints_a_summary(self):
        out, _ = self.call(rows=[
            record(dot="00000001", docket="MC000001"),
            record(dot="00000002", docket="MC000002", common="I"),
            record(dot="00000003", docket="FF000003"),
        ])
        self.download.assert_called_once_with("WA")
        self.assertEqual(list(Mover.objects.values_list("usdot_number", flat=True)), [1])
        self.assertIn("3 records, 2 motor carriers: 1 new, 0 updated, 1 skipped (no active authority), "
                      "0 set inactive, 0 MC conflicts. 1 freight forwarders skipped.", out)

    def test_dry_run_saves_nothing(self):
        out, _ = self.call("--dry-run", rows=[record()])
        self.assertFalse(Mover.objects.exists())
        self.assertIn("Dry run, nothing saved.", out)

    def test_conflicts_are_reported(self):
        Mover.objects.create(name="Existing", usdot_number=999, mc_number="12345")
        out, err = self.call(rows=[record()])
        self.assertIn("MC 12345 is already on USDOT 999", err)
        self.assertIn("1 carriers were skipped", out)

    def test_download_failure_is_a_clear_error(self):
        def failing(state):
            raise FMCSAError("FMCSA download failed: HTTP 503")
            yield  # pragma: no cover

        with patch(f"{COMMAND}.iter_authority_api", side_effect=failing):
            with self.assertRaisesMessage(CommandError, "FMCSA download failed: HTTP 503"):
                call_command("import_fmcsa_movers", stdout=StringIO(), stderr=StringIO())

    def test_reads_a_csv_export(self):
        with NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("DOCKET_NUMBER,DOT_NUMBER,LEGAL_NAME,BUS_STATE_CODE,HHG_CHK,COMMON_STAT,CONTRACT_STAT\n"
                    "MC000007,00000007,FILE MOVER,WA,Y,A,N\n"
                    "MC000008,00000008,OREGON MOVER,OR,Y,A,N\n")
        self.addCleanup(Path(f.name).unlink)
        with patch(f"{COMMAND}.iter_authority_api") as download:
            call_command("import_fmcsa_movers", "--file", f.name, stdout=StringIO(), stderr=StringIO())
        download.assert_not_called()
        self.assertEqual(list(Mover.objects.values_list("usdot_number", flat=True)), [7])

    def test_rejects_bad_options(self):
        for args, message in [
            (["--file", "/no/such/file.csv"], "File not found"),
            (["--state", "Washington"], "two-letter state code"),
            (["--limit", "0"], "--limit must be at least 1"),
        ]:
            with self.subTest(args=args), self.assertRaisesMessage(CommandError, message):
                call_command("import_fmcsa_movers", *args, stdout=StringIO(), stderr=StringIO())
