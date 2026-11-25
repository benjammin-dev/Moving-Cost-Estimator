from django.db import models


class Mover(models.Model):
    """A moving company. Profiles are created unclaimed by the FMCSA import
    (`manage.py import_fmcsa_movers`) or by a mover listing itself, and stay
    unverified, and can't be booked, until a UTC permit number is provided
    and checked."""

    class Status(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        VERIFIED = "verified", "Verified"
        # No longer qualifies (e.g. FMCSA says it isn't allowed to operate).
        # Kept rather than deleted, since it may have been claimed.
        INACTIVE = "inactive", "Inactive"

    # Identity. For claimed profiles these belong to the mover; the FMCSA
    # import only fills them in while a profile is unclaimed.
    name = models.CharField(max_length=200, help_text="Legal name")
    dba_name = models.CharField("DBA name", max_length=200, blank=True)
    usdot_number = models.PositiveIntegerField("USDOT number", unique=True)
    mc_number = models.CharField("MC number", max_length=20, blank=True)
    street = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=20, blank=True, help_text="Business phone")

    utc_permit_number = models.CharField(
        "UTC permit number", max_length=20, null=True, blank=True, unique=True
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNVERIFIED)
    claimed = models.BooleanField(default=False)
    # Only the Google place ID may be stored. Ratings and other Google data
    # are fetched live, never saved.
    google_place_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    # Federal (FMCSA) data, refreshed by every import, claimed or not.
    fmcsa_allowed_to_operate = models.BooleanField(null=True, blank=True)
    fmcsa_out_of_service = models.BooleanField(null=True, blank=True)
    hhg_confirmed_at = models.DateTimeField(
        "household goods confirmed at", null=True, blank=True,
        help_text="Last time QCMobile confirmed this carrier hauls household goods",
    )
    last_seen_in_census = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.dba_name or self.name} (USDOT {self.usdot_number})"

    def is_bookable(self):
        """Customers can only book a verified mover with a UTC permit number."""
        return self.status == self.Status.VERIFIED and bool(self.utc_permit_number)
