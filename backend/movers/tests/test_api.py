"""Tests for the staff-only movers API and /api/user/me/. The FMCSA download
is replaced with sample records."""

from unittest.mock import patch

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from movers.fmcsa import FMCSAError
from movers.models import ImportRun, Mover
from movers.tests.test_fmcsa import record

DOWNLOAD = "movers.services.iter_authority_api"


def make_mover(dot, **fields):
    defaults = {"name": f"CARRIER {dot} LLC", "city": "SEATTLE", "state": "WA", "mc_number": str(dot + 1000)}
    return Mover.objects.create(usdot_number=dot, **{**defaults, **fields})


class StaffApiTestCase(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="pw-12345678", is_staff=True)
        self.regular = User.objects.create_user("regular", password="pw-12345678")
        self.client.force_authenticate(self.staff)


class CurrentUserTests(StaffApiTestCase):
    def test_reports_staff_status(self):
        self.assertEqual(self.client.get("/api/user/me/").data, {"username": "staff", "is_staff": True})
        self.client.force_authenticate(self.regular)
        self.assertEqual(self.client.get("/api/user/me/").data, {"username": "regular", "is_staff": False})

    def test_needs_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/user/me/").status_code, status.HTTP_401_UNAUTHORIZED)


class PermissionTests(StaffApiTestCase):
    def test_every_endpoint_is_staff_only(self):
        mover = make_mover(1)
        requests = [
            ("get", "/api/movers/", None),
            ("get", "/api/movers/summary/", None),
            ("get", f"/api/movers/{mover.id}/", None),
            ("patch", f"/api/movers/{mover.id}/", {"status": "inactive"}),
            ("get", "/api/movers/imports/", None),
            ("post", "/api/movers/imports/", {"dry_run": True}),
        ]
        for user, expected in [(self.regular, status.HTTP_403_FORBIDDEN), (None, status.HTTP_401_UNAUTHORIZED)]:
            self.client.force_authenticate(user)
            for method, url, data in requests:
                with self.subTest(user=user, method=method, url=url):
                    response = getattr(self.client, method)(url, data, format="json")
                    self.assertEqual(response.status_code, expected)
        mover.refresh_from_db()
        self.assertEqual(mover.status, Mover.Status.UNVERIFIED)
        self.assertFalse(ImportRun.objects.exists())


class MoverListTests(StaffApiTestCase):
    def setUp(self):
        super().setUp()
        self.acme = make_mover(8257, name="HANSEN BROS TRANSFER", dba_name="HANSEN MOVERS", mc_number="59073")
        self.tacoma = make_mover(100, name="TACOMA MOVING CO", city="TACOMA", status=Mover.Status.VERIFIED, utc_permit_number="HG000100", claimed=True)
        self.lapsed = make_mover(200, name="OLD VAN LINES", status=Mover.Status.INACTIVE, fmcsa_authority_active=False)

    def names(self, query=""):
        response = self.client.get(f"/api/movers/{query}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return [m["name"] for m in response.data["results"]]

    def test_lists_movers_alphabetically_with_bookable_flag(self):
        response = self.client.get("/api/movers/")
        self.assertEqual(response.data["count"], 3)
        self.assertEqual([m["name"] for m in response.data["results"]], ["HANSEN BROS TRANSFER", "OLD VAN LINES", "TACOMA MOVING CO"])
        tacoma = response.data["results"][2]
        self.assertTrue(tacoma["is_bookable"])
        self.assertEqual(tacoma["utc_permit_number"], "HG000100")

    def test_search_by_name_dba_city_usdot_or_mc(self):
        self.assertEqual(self.names("?search=hansen"), ["HANSEN BROS TRANSFER"])
        self.assertEqual(self.names("?search=movers"), ["HANSEN BROS TRANSFER"])  # DBA
        self.assertEqual(self.names("?search=tacoma"), ["TACOMA MOVING CO"])
        self.assertEqual(self.names("?search=8257"), ["HANSEN BROS TRANSFER"])
        self.assertEqual(self.names("?search=MC059073"), ["HANSEN BROS TRANSFER"])
        self.assertEqual(self.names("?search=99999999999999999999"), [])  # too long for a number; no crash

    def test_filters(self):
        self.assertEqual(self.names("?status=verified"), ["TACOMA MOVING CO"])
        self.assertEqual(self.names("?claimed=true"), ["TACOMA MOVING CO"])
        self.assertEqual(len(self.names("?claimed=false")), 2)
        self.assertEqual(self.names("?authority=lapsed"), ["OLD VAN LINES"])
        self.assertEqual(self.names("?status=nonsense"), self.names())  # unknown values are ignored

    def test_paginates_25_at_a_time(self):
        for dot in range(1000, 1030):
            make_mover(dot)
        first = self.client.get("/api/movers/").data
        self.assertEqual((first["count"], len(first["results"])), (33, 25))
        self.assertEqual(len(self.client.get("/api/movers/?page=2").data["results"]), 8)


class MoverDetailTests(StaffApiTestCase):
    def setUp(self):
        super().setUp()
        self.mover = make_mover(8257)
        self.url = f"/api/movers/{self.mover.id}/"

    def test_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.data["usdot_number"], 8257)
        self.assertFalse(response.data["is_bookable"])

    def test_verify_with_a_permit(self):
        response = self.client.patch(self.url, {"utc_permit_number": " hg068043 ", "status": "verified"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["utc_permit_number"], "HG068043")
        self.assertTrue(response.data["is_bookable"])

    def test_cannot_verify_without_a_permit(self):
        response = self.client.patch(self.url, {"status": "verified"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("UTC permit number", str(response.data["status"]))
        response = self.client.patch(self.url, {"utc_permit_number": "", "status": "verified"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clearing_the_permit_of_a_verified_mover_is_refused(self):
        self.client.patch(self.url, {"utc_permit_number": "HG1", "status": "verified"}, format="json")
        response = self.client.patch(self.url, {"utc_permit_number": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_permit_format_and_uniqueness(self):
        bad = self.client.patch(self.url, {"utc_permit_number": "HG 06<script>"}, format="json")
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        make_mover(9, utc_permit_number="HG000009")
        taken = self.client.patch(self.url, {"utc_permit_number": "hg000009"}, format="json")
        self.assertEqual(taken.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already has this UTC permit number", str(taken.data["utc_permit_number"]))
        # Saving a mover's own permit again is fine.
        self.client.patch(self.url, {"utc_permit_number": "HG000010"}, format="json")
        again = self.client.patch(self.url, {"utc_permit_number": "hg000010"}, format="json")
        self.assertEqual(again.status_code, status.HTTP_200_OK)

    def test_other_fields_cannot_be_changed(self):
        self.client.patch(self.url, {"name": "Changed", "usdot_number": 1, "claimed": True, "status": "inactive"}, format="json")
        self.mover.refresh_from_db()
        self.assertEqual((self.mover.name, self.mover.usdot_number, self.mover.claimed), ("CARRIER 8257 LLC", 8257, False))
        self.assertEqual(self.mover.status, Mover.Status.INACTIVE)

    def test_put_is_not_allowed(self):
        response = self.client.put(self.url, {"status": "inactive"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SummaryTests(StaffApiTestCase):
    def test_counts_and_latest_import(self):
        make_mover(1)
        make_mover(2, status=Mover.Status.VERIFIED, utc_permit_number="HG2", claimed=True)
        make_mover(3, status=Mover.Status.INACTIVE)
        Mover.objects.filter(usdot_number=2).update(utc_status="Active")
        ImportRun.objects.create(state="WA", source="old", succeeded=True)
        latest = ImportRun.objects.create(state="WA", source="new", succeeded=True, stats={"created": 2})
        utc_run = ImportRun.objects.create(kind="utc", state="WA", source="utc", succeeded=True)
        data = self.client.get("/api/movers/summary/").data
        self.assertEqual(data["counts"], {"total": 3, "unverified": 1, "verified": 1, "inactive": 1, "claimed": 1, "bookable": 1, "utc_active": 1})
        self.assertEqual(data["latest_imports"]["fmcsa"]["id"], latest.id)
        self.assertEqual(data["latest_imports"]["utc"]["id"], utc_run.id)

    def test_no_imports_yet(self):
        self.assertEqual(self.client.get("/api/movers/summary/").data["latest_imports"], {"fmcsa": None, "utc": None})


class ImportRunTests(StaffApiTestCase):
    rows = [record(dot="00000001", docket="MC000001"), record(dot="00000002", docket="MC000002", common="I")]

    def test_run_an_import_from_the_page(self):
        with patch(DOWNLOAD, return_value=iter(self.rows)):
            response = self.client.post("/api/movers/imports/", {"kind": "fmcsa", "dry_run": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["kind"], "fmcsa")
        self.assertIsNotNone(response.data["finished_at"])  # tests run imports inline
        self.assertTrue(response.data["succeeded"])
        self.assertEqual(response.data["triggered_by"], "staff")
        self.assertEqual(response.data["stats"]["created"], 1)
        self.assertEqual(response.data["stats"]["inactive_skipped"], 1)
        self.assertEqual(Mover.objects.count(), 1)

    def test_dry_run_from_the_page_saves_no_movers(self):
        with patch(DOWNLOAD, return_value=iter(self.rows)):
            response = self.client.post("/api/movers/imports/", {"dry_run": True}, format="json")
        self.assertTrue(response.data["dry_run"])
        self.assertEqual(response.data["stats"]["created"], 1)
        self.assertFalse(Mover.objects.exists())
        self.assertEqual(ImportRun.objects.count(), 1)

    def test_download_failure_is_recorded_and_reported(self):
        def failing(state):
            raise FMCSAError("FMCSA download failed: HTTP 503")
            yield  # pragma: no cover

        with patch(DOWNLOAD, side_effect=failing):
            response = self.client.post("/api/movers/imports/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertFalse(response.data["succeeded"])
        self.assertIn("HTTP 503", response.data["error"])
        run = ImportRun.objects.get()
        self.assertFalse(run.succeeded)
        self.assertIn("HTTP 503", run.error)
        self.assertIsNotNone(run.finished_at)

    def test_conflict_messages_are_kept_on_the_run(self):
        make_mover(999, mc_number="1")
        with patch(DOWNLOAD, return_value=iter(self.rows)):
            response = self.client.post("/api/movers/imports/", {}, format="json")
        self.assertEqual(response.data["stats"]["conflicts"], 1)
        self.assertIn("MC 1 is already on USDOT 999", response.data["messages"][0])

    def test_command_line_runs_are_recorded_too(self):
        from io import StringIO

        from django.core.management import call_command
        with patch(DOWNLOAD, return_value=iter(self.rows)):
            call_command("import_fmcsa_movers", stdout=StringIO(), stderr=StringIO())
        run = ImportRun.objects.get()
        self.assertIsNone(run.triggered_by)
        self.assertTrue(run.succeeded)
        listed = self.client.get("/api/movers/imports/").data
        self.assertEqual([r["id"] for r in listed], [run.id])
        self.assertIsNone(listed[0]["triggered_by"])


class ImportControlTests(StaffApiTestCase):
    def test_refuses_a_second_run_of_the_same_kind_while_one_is_going(self):
        ImportRun.objects.create(kind="utc", state="WA", source="utc")  # unfinished
        response = self.client.post("/api/movers/imports/", {"kind": "utc"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(ImportRun.objects.count(), 1)

    def test_a_stale_unfinished_run_does_not_block(self):
        from datetime import timedelta

        from django.utils import timezone
        stale = ImportRun.objects.create(kind="fmcsa", state="WA", source="x")
        ImportRun.objects.filter(pk=stale.pk).update(started_at=timezone.now() - timedelta(hours=3))
        with patch(DOWNLOAD, return_value=iter([])):
            response = self.client.post("/api/movers/imports/", {"kind": "fmcsa"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_unknown_kind(self):
        response = self.client.post("/api/movers/imports/", {"kind": "google"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AddMoverTests(StaffApiTestCase):
    def test_staff_can_add_a_mover_without_a_usdot_number(self):
        response = self.client.post("/api/movers/", {
            "name": "  Aaron   Glide Moving ", "city": "Seattle", "phone": "425-745-9047", "mc_number": "MC-00123",
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mover = Mover.objects.get()
        self.assertEqual((mover.name, mover.state, mover.mc_number), ("Aaron Glide Moving", "WA", "123"))
        self.assertIsNone(mover.usdot_number)
        self.assertEqual((mover.source, mover.status, mover.claimed), ("staff", "unverified", False))
        self.assertEqual(response.data["source"], "staff")

    def test_validation(self):
        make_mover(8257, mc_number="59073")
        for data, field in [
            ({"name": "  "}, "name"),
            ({"name": "Dup", "usdot_number": 8257}, "usdot_number"),
            ({"name": "Dup", "mc_number": "MC059073"}, "mc_number"),
            ({"name": "Bad", "mc_number": "ABC"}, "mc_number"),
            ({"name": "Bad", "state": "Washington"}, "state"),
        ]:
            with self.subTest(data=data):
                response = self.client.post("/api/movers/", data, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)

    def test_cannot_set_status_or_permit_when_adding(self):
        self.client.post("/api/movers/", {"name": "Sneaky", "status": "verified", "utc_permit_number": "HG1", "source": "utc"}, format="json")
        mover = Mover.objects.get()
        self.assertEqual((mover.status, mover.utc_permit_number, mover.source), ("unverified", None, "staff"))

    def test_regular_users_cannot_add(self):
        self.client.force_authenticate(self.regular)
        self.assertEqual(self.client.post("/api/movers/", {"name": "X"}, format="json").status_code, status.HTTP_403_FORBIDDEN)


class UtcFilterTests(StaffApiTestCase):
    def test_filter_by_utc_status_and_source(self):
        make_mover(1, name="PERMITTED", utc_status="Active", source="utc")
        make_mover(2, name="UNREGULATED", utc_status="Unregulated", source="utc")
        make_mover(3, name="NOT ON LIST", source="fmcsa")
        names = lambda q: [m["name"] for m in self.client.get(f"/api/movers/?{q}").data["results"]]
        self.assertEqual(names("utc=active"), ["PERMITTED"])
        self.assertEqual(names("utc=not_permitted"), ["UNREGULATED"])
        self.assertEqual(names("utc=none"), ["NOT ON LIST"])
        self.assertEqual(names("source=fmcsa"), ["NOT ON LIST"])

    def test_search_by_permit_number(self):
        make_mover(1, name="GENTLE GIANT", utc_permit_number="HG060620")
        self.assertEqual([m["name"] for m in self.client.get("/api/movers/?search=hg060620").data["results"]], ["GENTLE GIANT"])
