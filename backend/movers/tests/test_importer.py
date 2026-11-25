"""Tests for the import rules (movers/importer.py), with a fake QCMobile client."""

from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from movers.fmcsa import CarrierCheck, FMCSAError
from movers.importer import import_movers
from movers.models import Mover

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=dt_timezone.utc)
LATER = datetime(2026, 12, 25, 12, 0, tzinfo=dt_timezone.utc)

QUALIFIES = CarrierCheck(found=True, allowed_to_operate=True, out_of_service=False, household_goods=True)
NOT_HHG = CarrierCheck(found=True, allowed_to_operate=True, out_of_service=False, household_goods=False)
NOT_ALLOWED = CarrierCheck(found=True, allowed_to_operate=False)
OUT_OF_SERVICE = CarrierCheck(found=True, allowed_to_operate=True, out_of_service=True)
NOT_FOUND = CarrierCheck(found=False)


def row(dot, **overrides):
    base = {
        "dot_number": str(dot),
        "legal_name": f"CARRIER {dot} LLC",
        "dba_name": "",
        "phy_street": "100 MAIN ST",
        "phy_city": "SEATTLE",
        "phy_state": "WA",
        "phy_zip": "98101",
        "phone": "2065550100",
        "status_code": "A",
        "crgo_household": "X",
        "docket1prefix": "MC",
        "docket1": f"{dot}9",
    }
    return {**base, **overrides}


class FakeClient:
    def __init__(self, results=None, default=QUALIFIES):
        self.results = results or {}
        self.default = default
        self.checked = []

    def check(self, dot):
        self.checked.append(dot)
        result = self.results.get(dot, self.default)
        if isinstance(result, Exception):
            raise result
        return result


def run(rows, client=None, **kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("sleep", lambda s: None)
    return import_movers(rows, client or FakeClient(), **kwargs)


class ImportTests(TestCase):
    def test_confirmed_carrier_becomes_an_unclaimed_unverified_profile(self):
        stats = run([row(111, dba_name="FAST  MOVERS")])
        mover = Mover.objects.get(usdot_number=111)
        self.assertEqual((stats.candidates, stats.confirmed, stats.created), (1, 1, 1))
        self.assertEqual(mover.name, "CARRIER 111 LLC")
        self.assertEqual(mover.dba_name, "FAST MOVERS")  # whitespace tidied
        self.assertEqual(mover.mc_number, "1119")
        self.assertEqual((mover.street, mover.city, mover.state, mover.zip_code), ("100 MAIN ST", "SEATTLE", "WA", "98101"))
        self.assertEqual(mover.phone, "2065550100")
        self.assertFalse(mover.claimed)
        self.assertEqual(mover.status, Mover.Status.UNVERIFIED)
        self.assertIsNone(mover.utc_permit_number)
        self.assertIsNone(mover.google_place_id)
        self.assertTrue(mover.fmcsa_allowed_to_operate)
        self.assertFalse(mover.fmcsa_out_of_service)
        self.assertEqual(mover.hhg_confirmed_at, NOW)
        self.assertFalse(mover.is_bookable())

    def test_skips_rows_that_are_not_candidates_without_calling_qcmobile(self):
        client = FakeClient()
        stats = run([
            row(1, phy_state="OR"),
            row(2, crgo_household=""),
            row(3, status_code="I"),
            row(4, dot_number="not-a-number"),
            row(5),
            row(5),  # duplicate row
        ], client)
        self.assertEqual(client.checked, [5])
        self.assertEqual(stats.candidates, 1)

    def test_rejected_carriers_are_not_imported(self):
        client = FakeClient({1: NOT_HHG, 2: NOT_ALLOWED, 3: OUT_OF_SERVICE, 4: NOT_FOUND})
        stats = run([row(1), row(2), row(3), row(4)], client)
        self.assertEqual(stats.rejected, 4)
        self.assertEqual(stats.created, 0)
        self.assertFalse(Mover.objects.exists())

    def test_rerunning_updates_instead_of_duplicating(self):
        run([row(111)])
        stats = run([row(111, phone="2065550199")], now=LATER)
        self.assertEqual(Mover.objects.count(), 1)
        self.assertEqual((stats.created, stats.updated), (0, 1))
        mover = Mover.objects.get()
        self.assertEqual(mover.phone, "2065550199")
        self.assertEqual(mover.hhg_confirmed_at, LATER)

    def test_claimed_profiles_keep_the_movers_own_details(self):
        run([row(111)])
        Mover.objects.filter(usdot_number=111).update(
            claimed=True, name="Acme Moving", phone="4255550000",
            utc_permit_number="HG000111", status=Mover.Status.VERIFIED,
        )
        run([row(111, legal_name="SOMETHING ELSE", phone="2065550199")], now=LATER)
        mover = Mover.objects.get()
        self.assertEqual((mover.name, mover.phone, mover.utc_permit_number), ("Acme Moving", "4255550000", "HG000111"))
        self.assertEqual(mover.status, Mover.Status.VERIFIED)
        self.assertTrue(mover.claimed)
        self.assertEqual(mover.hhg_confirmed_at, LATER)  # federal fields still refresh

    def test_one_failed_lookup_does_not_stop_the_run(self):
        logs = []
        client = FakeClient({2: FMCSAError("QCMobile carrier lookup failed: HTTP 500")})
        stats = run([row(1), row(2), row(3)], client, log=logs.append)
        self.assertEqual((stats.created, stats.errors), (2, 1))
        self.assertEqual(sorted(Mover.objects.values_list("usdot_number", flat=True)), [1, 3])
        self.assertIn("USDOT 2", logs[0])

    def test_a_failed_lookup_leaves_an_existing_profile_unchanged(self):
        run([row(1)])
        run([row(1)], FakeClient({1: FMCSAError("HTTP 500")}), now=LATER)
        mover = Mover.objects.get()
        self.assertEqual(mover.status, Mover.Status.UNVERIFIED)
        self.assertEqual(mover.hhg_confirmed_at, NOW)

    def test_dry_run_writes_nothing(self):
        run([row(1)])
        stats = run([row(1), row(2)], FakeClient({1: NOT_ALLOWED}), dry_run=True, now=LATER)
        self.assertEqual((stats.created, stats.rejected, stats.deactivated), (1, 1, 1))
        self.assertEqual(Mover.objects.count(), 1)
        self.assertEqual(Mover.objects.get().status, Mover.Status.UNVERIFIED)

    def test_limit_caps_the_number_of_carriers_checked(self):
        client = FakeClient()
        stats = run([row(1), row(2), row(3)], client, limit=2)
        self.assertEqual(client.checked, [1, 2])
        self.assertEqual(stats.candidates, 2)

    def test_pauses_between_carriers(self):
        waits = []
        run([row(1), row(2), row(3)], sleep=waits.append, sleep_seconds=0.25)
        self.assertEqual(waits, [0.25, 0.25])


class DeactivationTests(TestCase):
    def setUp(self):
        run([row(1), row(2)])

    def status(self, dot):
        return Mover.objects.get(usdot_number=dot).status

    def claim(self, dot):
        Mover.objects.filter(usdot_number=dot).update(claimed=True, status=Mover.Status.VERIFIED, utc_permit_number=f"HG00000{dot}")

    def test_not_allowed_to_operate_deactivates_even_claimed_profiles(self):
        self.claim(1)
        stats = run([row(1), row(2)], FakeClient({1: NOT_ALLOWED, 2: OUT_OF_SERVICE}), now=LATER)
        self.assertEqual(stats.deactivated, 2)
        self.assertEqual(self.status(1), Mover.Status.INACTIVE)
        self.assertEqual(self.status(2), Mover.Status.INACTIVE)
        mover = Mover.objects.get(usdot_number=1)
        self.assertFalse(mover.fmcsa_allowed_to_operate)
        self.assertFalse(mover.is_bookable())

    def test_no_household_goods_deactivates_only_unclaimed_profiles(self):
        self.claim(1)
        logs = []
        stats = run([row(1), row(2)], FakeClient(default=NOT_HHG), now=LATER, log=logs.append)
        self.assertEqual(stats.deactivated, 1)
        self.assertEqual(self.status(1), Mover.Status.VERIFIED)
        self.assertEqual(self.status(2), Mover.Status.INACTIVE)
        self.assertTrue(any("claimed" in line and "USDOT 1" in line for line in logs))

    def test_carriers_gone_from_the_census_are_deactivated_on_a_full_run(self):
        stats = run([row(1)], now=LATER)
        self.assertEqual(stats.deactivated, 1)
        self.assertEqual(self.status(1), Mover.Status.UNVERIFIED)
        self.assertEqual(self.status(2), Mover.Status.INACTIVE)

    def test_a_limited_run_never_deactivates_missing_carriers(self):
        stats = run([row(1)], limit=1, now=LATER)
        self.assertEqual(stats.deactivated, 0)
        self.assertEqual(self.status(2), Mover.Status.UNVERIFIED)

    def test_missing_claimed_and_self_listed_movers_are_left_alone(self):
        self.claim(1)
        Mover.objects.create(name="Self Listed Movers", usdot_number=999, state="WA")
        stats = run([], now=LATER)
        self.assertEqual(stats.deactivated, 1)  # only unclaimed carrier 2
        self.assertEqual(self.status(1), Mover.Status.VERIFIED)
        self.assertEqual(self.status(999), Mover.Status.UNVERIFIED)

    def test_inactive_mover_that_qualifies_again_needs_re_verifying(self):
        run([row(1), row(2)], FakeClient({1: NOT_ALLOWED}), now=LATER)
        self.assertEqual(self.status(1), Mover.Status.INACTIVE)
        stats = run([row(1), row(2)], now=LATER)
        self.assertEqual(stats.updated, 2)
        self.assertEqual(self.status(1), Mover.Status.UNVERIFIED)
