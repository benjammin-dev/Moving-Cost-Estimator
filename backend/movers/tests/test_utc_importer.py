"""Tests for the UTC import rules (movers/utc_importer.py)."""

from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from movers.importer import import_movers
from movers.models import Mover
from movers.tests.test_fmcsa import record
from movers.utc import CompanyDetail, ListedCompany, UTCError
from movers.utc_importer import import_utc_movers

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=dt_timezone.utc)
LATER = datetime(2026, 12, 25, 12, 0, tzinfo=dt_timezone.utc)


def listed(cid, status="Active", usdot=None, name=None):
    return ListedCompany(company_id=cid, name=name or f"Company {cid} LLC", dba_name="", usdot_number=usdot, status=status)


def detail(cid, permit="", usdot=None, city="Seattle", status="Active"):
    return CompanyDetail(company_id=cid, name=f"Company {cid} LLC", status=status, phone="206-555-0100",
                         street="1 Main St", city=city, state="WA", zip_code="98101",
                         usdot_number=usdot, permit_number=permit, permit_type="Permanent" if permit else "")


class FakeDetails:
    def __init__(self, details=None):
        self.details = details or {}
        self.read = []

    def __call__(self, cid):
        self.read.append(cid)
        result = self.details.get(cid) or detail(cid)
        if isinstance(result, Exception):
            raise result
        return result


def run(companies, details=None, **kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("sleep", lambda s: None)
    fake = details if isinstance(details, FakeDetails) else FakeDetails(details)
    return import_utc_movers(companies, fake, **kwargs), fake


def get(cid):
    return Mover.objects.get(utc_company_id=cid)


class CreateTests(TestCase):
    def test_active_permit_holder_is_verified_and_bookable(self):
        stats, _ = run([listed(1, usdot=111)], {1: detail(1, permit="HG060620", usdot=111)})
        mover = get(1)
        self.assertEqual((mover.status, mover.utc_permit_number, mover.usdot_number), ("verified", "HG060620", 111))
        self.assertTrue(mover.is_bookable())
        self.assertEqual((mover.source, mover.utc_status, mover.claimed), ("utc", "Active", False))
        self.assertEqual((mover.city, mover.phone), ("Seattle", "206-555-0100"))
        self.assertEqual((stats.created, stats.verified, stats.details_read), (1, 1, 1))

    def test_pending_is_unverified_and_unregulated_is_inactive(self):
        run([listed(1, "Pending"), listed(2, "Unregulated")])
        self.assertEqual(get(1).status, "unverified")
        self.assertEqual(get(2).status, "inactive")
        self.assertIsNone(get(2).usdot_number)
        self.assertEqual(get(2).city, "Seattle")  # details still read

    def test_active_without_a_readable_permit_stays_unverified(self):
        run([listed(1)], {1: detail(1, permit="")})
        self.assertEqual(get(1).status, "unverified")
        self.assertFalse(get(1).is_bookable())

    def test_inactive_companies_are_skipped_unless_asked_for(self):
        stats, fake = run([listed(1, "Inactive"), listed(2)])
        self.assertEqual(stats.inactive_skipped, 1)
        self.assertEqual(fake.read, [2])
        self.assertFalse(Mover.objects.filter(utc_company_id=1).exists())
        run([listed(1, "Inactive")], include_inactive=True)
        self.assertEqual(get(1).status, "inactive")

    def test_a_company_listed_twice_becomes_one_profile(self):
        run([listed(1, usdot=222), listed(1, usdot=111)], {1: detail(1, permit="HG1", usdot=None)})
        self.assertEqual(Mover.objects.count(), 1)
        self.assertEqual(get(1).usdot_number, 111)  # lowest listed USDOT when the page has none

    def test_a_failed_company_page_leaves_it_out_for_now(self):
        stats, _ = run([listed(1), listed(2)], {1: UTCError("UTC company 1 page failed: HTTP 500")})
        self.assertEqual((stats.errors, stats.created), (1, 1))
        self.assertFalse(Mover.objects.filter(utc_company_id=1).exists())

    def test_pauses_between_company_pages(self):
        waits = []
        run([listed(1), listed(2), listed(3)], sleep=waits.append, sleep_seconds=1.0)
        self.assertEqual(waits, [1.0, 1.0])

    def test_dry_run_saves_nothing_reads_no_pages_and_counts_likely_verifications(self):
        stats, fake = run([listed(1), listed(2, "Unregulated")], dry_run=True)
        self.assertFalse(Mover.objects.exists())
        self.assertEqual(fake.read, [])
        self.assertEqual((stats.created, stats.verified), (2, 1))

    def test_limit(self):
        stats, _ = run([listed(1), listed(2), listed(3)], limit=2)
        self.assertEqual((stats.companies, Mover.objects.count()), (2, 2))


class UpdateTests(TestCase):
    def test_rerun_skips_company_pages_already_read(self):
        run([listed(1)], {1: detail(1, permit="HG1")})
        stats, fake = run([listed(1)], now=LATER)
        self.assertEqual(fake.read, [])
        self.assertEqual((stats.updated, Mover.objects.count()), (1, 1))
        self.assertEqual(get(1).utc_synced_at, LATER)

    def test_rereads_an_active_company_still_missing_its_permit(self):
        run([listed(1)], {1: detail(1, permit="")})
        stats, fake = run([listed(1)], {1: detail(1, permit="HG9")}, now=LATER)
        self.assertEqual(fake.read, [1])
        self.assertEqual((get(1).status, get(1).utc_permit_number), ("verified", "HG9"))
        self.assertEqual(stats.verified, 1)

    def test_permit_lapses_then_returns(self):
        run([listed(1)], {1: detail(1, permit="HG1")})
        run([listed(1, "Unregulated")], now=LATER)
        self.assertEqual(get(1).status, "inactive")
        self.assertFalse(get(1).is_bookable())
        run([listed(1)], now=LATER)
        self.assertEqual(get(1).status, "verified")

    def test_matches_an_fmcsa_profile_by_usdot_and_verifies_it(self):
        import_movers([record(dot="00000111", docket="MC000111")], now=NOW)
        run([listed(1, usdot=111)], {1: detail(1, permit="HG111", usdot=111, city="Tacoma")})
        mover = Mover.objects.get(usdot_number=111)
        self.assertEqual(Mover.objects.count(), 1)
        self.assertEqual((mover.utc_company_id, mover.status, mover.utc_permit_number), (1, "verified", "HG111"))
        self.assertEqual(mover.source, "fmcsa")
        self.assertEqual(mover.city, "SEATTLE")  # FMCSA details aren't overwritten

    def test_fmcsa_profile_without_an_in_state_permit_is_not_verified_or_hidden(self):
        import_movers([record(dot="00000111", docket="MC000111")], now=NOW)
        Mover.objects.filter(usdot_number=111).update(status="verified", utc_permit_number="HG5")
        logs = []
        run([listed(1, "Unregulated", usdot=111)], log=logs.append)
        mover = Mover.objects.get(usdot_number=111)
        self.assertEqual((mover.status, mover.utc_status), ("unverified", "Unregulated"))
        self.assertTrue(any("Set back to unverified" in line for line in logs))

    def test_claimed_profiles_only_get_utc_fields_and_mismatches_are_logged(self):
        run([listed(1)], {1: detail(1, permit="HG1")})
        Mover.objects.filter(utc_company_id=1).update(claimed=True, name="Mover's Own Name", phone="425-000-0000")
        logs = []
        run([listed(1, "Unregulated", name="UTC NAME")], now=LATER, log=logs.append)
        mover = get(1)
        self.assertEqual((mover.name, mover.phone, mover.status, mover.utc_permit_number), ("Mover's Own Name", "425-000-0000", "verified", "HG1"))
        self.assertEqual(mover.utc_status, "Unregulated")
        self.assertTrue(any("claimed" in line for line in logs))

    def test_permit_already_on_another_profile_is_not_copied(self):
        Mover.objects.create(name="Other", source="staff", utc_permit_number="HG1")
        stats, _ = run([listed(1)], {1: detail(1, permit="HG1")})
        self.assertEqual(stats.conflicts, 1)
        self.assertEqual((get(1).status, get(1).utc_permit_number), ("unverified", None))

    def test_usdot_matching_two_profiles_is_skipped(self):
        Mover.objects.create(name="A", source="fmcsa", usdot_number=111)
        Mover.objects.create(name="B", source="fmcsa", usdot_number=222)
        logs = []
        stats, _ = run([listed(1, usdot=111), listed(1, usdot=222)], log=logs.append)
        self.assertEqual(stats.conflicts, 1)
        self.assertFalse(Mover.objects.filter(utc_company_id=1).exists())
        self.assertIn("more than one profile", logs[0])


class GoneFromListTests(TestCase):
    def setUp(self):
        import_movers([record(dot="00000111", docket="MC000111")], now=NOW)
        run([listed(1, usdot=111), listed(2)], {1: detail(1, permit="HG111", usdot=111), 2: detail(2, permit="HG2")})

    def test_utc_profiles_go_inactive_and_others_go_back_to_unverified(self):
        stats, _ = run([], now=LATER)
        self.assertEqual(get(2).status, "inactive")
        fmcsa_mover = Mover.objects.get(usdot_number=111)
        self.assertEqual((fmcsa_mover.status, fmcsa_mover.utc_status), ("unverified", ""))
        self.assertEqual(stats.deactivated, 1)

    def test_a_limited_run_changes_nothing_for_missing_companies(self):
        run([listed(2)], limit=1, now=LATER)
        self.assertEqual(Mover.objects.get(usdot_number=111).status, "verified")


class FmcsaRespectsUtcTests(TestCase):
    """The FMCSA import must not undo what the UTC says."""

    def test_fmcsa_never_deactivates_a_mover_with_an_active_utc_permit(self):
        import_movers([record(dot="00000111", docket="MC000111")], now=NOW)
        run([listed(1, usdot=111)], {1: detail(1, permit="HG111", usdot=111)})
        logs = []
        import_movers([record(dot="00000111", docket="MC000111", common="I")], now=LATER, log=logs.append)
        self.assertEqual(Mover.objects.get(usdot_number=111).status, "verified")
        import_movers([], now=LATER)  # gone from FMCSA data entirely
        self.assertEqual(Mover.objects.get(usdot_number=111).status, "verified")
        self.assertTrue(any("UTC lists an active permit" in line for line in logs))

    def test_fmcsa_never_reactivates_a_mover_the_utc_lists_as_not_permitted(self):
        run([listed(1, "Unregulated", usdot=111)])
        self.assertEqual(get(1).status, "inactive")
        import_movers([record(dot="00000111", docket="MC000111")], now=LATER)
        self.assertEqual(get(1).status, "inactive")
