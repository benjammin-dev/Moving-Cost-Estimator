"""Tests for the import rules (movers/importer.py)."""

from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from movers.importer import import_movers
from movers.models import Mover
from movers.tests.test_fmcsa import record

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=dt_timezone.utc)
LATER = datetime(2026, 12, 25, 12, 0, tzinfo=dt_timezone.utc)


def carrier(dot, active=True, **overrides):
    fields = {"legal_name": f"CARRIER {dot} LLC", **overrides}
    return record(dot=f"{dot:08d}", docket=f"MC{dot:06d}", common="A" if active else "I", **fields)


def run(rows, **kwargs):
    kwargs.setdefault("now", NOW)
    return import_movers(rows, **kwargs)


class ImportTests(TestCase):
    def test_active_carrier_becomes_an_unclaimed_unverified_profile(self):
        stats = run([carrier(111, dba_name="FAST  MOVERS")])
        mover = Mover.objects.get(usdot_number=111)
        self.assertEqual((stats.records, stats.carriers, stats.created), (1, 1, 1))
        self.assertEqual(mover.name, "CARRIER 111 LLC")
        self.assertEqual(mover.dba_name, "FAST MOVERS")  # whitespace tidied
        self.assertEqual(mover.mc_number, "111")
        self.assertEqual((mover.street, mover.city, mover.state, mover.zip_code), ("100 MAIN ST", "SEATTLE", "WA", "98101-1234"))
        self.assertEqual(mover.phone, "2065550100")
        self.assertFalse(mover.claimed)
        self.assertEqual(mover.status, Mover.Status.UNVERIFIED)
        self.assertIsNone(mover.utc_permit_number)
        self.assertIsNone(mover.google_place_id)
        self.assertTrue(mover.fmcsa_authority_active)
        self.assertEqual(mover.fmcsa_synced_at, NOW)
        self.assertFalse(mover.is_bookable())

    def test_carriers_without_active_authority_are_not_imported(self):
        stats = run([carrier(1, active=False), carrier(2)])
        self.assertEqual(stats.inactive_skipped, 1)
        self.assertEqual(list(Mover.objects.values_list("usdot_number", flat=True)), [2])

    def test_freight_forwarders_are_not_imported(self):
        stats = run([record(dot="00000005", docket="FF000005")])
        self.assertEqual(stats.forwarders_skipped, 1)
        self.assertFalse(Mover.objects.exists())

    def test_multiple_dockets_make_one_profile(self):
        run([carrier(7), record(dot="00000007", docket="MC000999", common="A")])
        self.assertEqual(Mover.objects.count(), 1)
        self.assertEqual(Mover.objects.get().mc_number, "7")

    def test_rerunning_updates_instead_of_duplicating(self):
        run([carrier(111)])
        stats = run([carrier(111, bus_telno="2065550199")], now=LATER)
        self.assertEqual(Mover.objects.count(), 1)
        self.assertEqual((stats.created, stats.updated), (0, 1))
        mover = Mover.objects.get()
        self.assertEqual(mover.phone, "2065550199")
        self.assertEqual(mover.fmcsa_synced_at, LATER)

    def test_claimed_profiles_keep_the_movers_own_details(self):
        run([carrier(111)])
        Mover.objects.filter(usdot_number=111).update(
            claimed=True, name="Acme Moving", phone="4255550000",
            utc_permit_number="HG000111", status=Mover.Status.VERIFIED,
        )
        run([carrier(111, legal_name="SOMETHING ELSE", bus_telno="2065550199")], now=LATER)
        mover = Mover.objects.get()
        self.assertEqual((mover.name, mover.phone, mover.utc_permit_number), ("Acme Moving", "4255550000", "HG000111"))
        self.assertEqual(mover.status, Mover.Status.VERIFIED)
        self.assertEqual(mover.fmcsa_synced_at, LATER)  # federal fields still refresh

    def test_mc_number_on_another_profile_is_skipped_not_merged(self):
        Mover.objects.create(name="Existing", usdot_number=999, mc_number="111")
        logs = []
        stats = run([carrier(111)], log=logs.append)
        self.assertEqual(stats.conflicts, 1)
        self.assertFalse(Mover.objects.filter(usdot_number=111).exists())
        self.assertIn("USDOT 999", logs[0])

    def test_dry_run_writes_nothing(self):
        run([carrier(1)])
        stats = run([carrier(1, active=False), carrier(2)], dry_run=True, now=LATER)
        self.assertEqual((stats.created, stats.deactivated), (1, 1))
        self.assertEqual(Mover.objects.count(), 1)
        mover = Mover.objects.get()
        self.assertEqual(mover.status, Mover.Status.UNVERIFIED)
        self.assertEqual(mover.fmcsa_synced_at, NOW)

    def test_limit_caps_the_number_of_carriers(self):
        stats = run([carrier(1), carrier(2), carrier(3)], limit=2)
        self.assertEqual(stats.carriers, 2)
        self.assertEqual(sorted(Mover.objects.values_list("usdot_number", flat=True)), [1, 2])


class DeactivationTests(TestCase):
    def setUp(self):
        run([carrier(1), carrier(2)])

    def status(self, dot):
        return Mover.objects.get(usdot_number=dot).status

    def claim(self, dot):
        Mover.objects.filter(usdot_number=dot).update(claimed=True, status=Mover.Status.VERIFIED, utc_permit_number=f"HG00000{dot}")

    def test_inactive_authority_deactivates_unclaimed_profiles(self):
        stats = run([carrier(1, active=False), carrier(2)], now=LATER)
        self.assertEqual(stats.deactivated, 1)
        self.assertEqual(self.status(1), Mover.Status.INACTIVE)
        self.assertFalse(Mover.objects.get(usdot_number=1).fmcsa_authority_active)
        self.assertEqual(self.status(2), Mover.Status.UNVERIFIED)

    def test_inactive_authority_on_a_claimed_profile_is_logged_for_review(self):
        self.claim(1)
        logs = []
        stats = run([carrier(1, active=False), carrier(2)], now=LATER, log=logs.append)
        self.assertEqual(stats.deactivated, 0)
        mover = Mover.objects.get(usdot_number=1)
        self.assertEqual(mover.status, Mover.Status.VERIFIED)
        self.assertFalse(mover.fmcsa_authority_active)
        self.assertTrue(any("claimed" in line and "USDOT 1" in line for line in logs))

    def test_carriers_gone_from_the_data_are_deactivated_on_a_full_run(self):
        stats = run([carrier(1)], now=LATER)
        self.assertEqual(stats.deactivated, 1)
        self.assertEqual(self.status(1), Mover.Status.UNVERIFIED)
        self.assertEqual(self.status(2), Mover.Status.INACTIVE)

    def test_a_limited_run_never_deactivates_missing_carriers(self):
        stats = run([carrier(1)], limit=1, now=LATER)
        self.assertEqual(stats.deactivated, 0)
        self.assertEqual(self.status(2), Mover.Status.UNVERIFIED)

    def test_missing_claimed_and_self_listed_movers_are_left_alone(self):
        self.claim(1)
        Mover.objects.create(name="Self Listed Movers", usdot_number=999, state="WA")
        stats = run([], now=LATER)
        self.assertEqual(stats.deactivated, 1)  # only unclaimed carrier 2
        self.assertEqual(self.status(1), Mover.Status.VERIFIED)
        self.assertEqual(self.status(999), Mover.Status.UNVERIFIED)

    def test_reactivated_authority_needs_re_verifying(self):
        run([carrier(1, active=False), carrier(2)], now=LATER)
        self.assertEqual(self.status(1), Mover.Status.INACTIVE)
        run([carrier(1), carrier(2)], now=LATER)
        self.assertEqual(self.status(1), Mover.Status.UNVERIFIED)
        self.assertTrue(Mover.objects.get(usdot_number=1).fmcsa_authority_active)
