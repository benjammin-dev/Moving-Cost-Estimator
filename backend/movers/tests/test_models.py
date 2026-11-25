from django.db import IntegrityError
from django.test import TestCase

from movers.models import Mover


class MoverModelTests(TestCase):
    def make(self, **kwargs):
        defaults = {"name": "Acme Moving LLC", "usdot_number": 1234567}
        return Mover.objects.create(**{**defaults, **kwargs})

    def test_new_profiles_start_unclaimed_and_unverified(self):
        mover = self.make()
        self.assertFalse(mover.claimed)
        self.assertEqual(mover.status, Mover.Status.UNVERIFIED)
        self.assertIsNone(mover.utc_permit_number)
        self.assertIsNone(mover.google_place_id)

    def test_only_verified_movers_with_a_permit_are_bookable(self):
        self.assertFalse(self.make(usdot_number=1).is_bookable())
        self.assertFalse(self.make(usdot_number=2, utc_permit_number="HG000001").is_bookable())
        self.assertFalse(self.make(usdot_number=3, status=Mover.Status.VERIFIED).is_bookable())
        self.assertFalse(self.make(usdot_number=4, status=Mover.Status.INACTIVE, utc_permit_number="HG000004").is_bookable())
        self.assertTrue(self.make(usdot_number=5, status=Mover.Status.VERIFIED, utc_permit_number="HG000005").is_bookable())

    def test_usdot_number_is_unique(self):
        self.make()
        with self.assertRaises(IntegrityError):
            self.make()

    def test_many_movers_can_have_no_permit_or_place_id(self):
        self.make(usdot_number=1)
        self.make(usdot_number=2)  # two NULLs don't clash with unique=True
        self.assertEqual(Mover.objects.count(), 2)

    def test_str_prefers_dba_name(self):
        self.assertEqual(str(self.make(dba_name="Acme Movers")), "Acme Movers (USDOT 1234567)")
