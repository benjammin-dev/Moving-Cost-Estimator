from django.db import models


class Mover(models.Model):
    """A moving company. Profiles are created unclaimed by the FMCSA import
    (`manage.py import_fmcsa_movers`) or by a mover listing itself, and stay
    unverified, and can't be booked, until a UTC permit number is provided
    and checked."""

    class Source(models.TextChoices):
        FMCSA = "fmcsa", "FMCSA import"
        UTC = "utc", "UTC import"
        STAFF = "staff", "Added by staff"

    class Status(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        VERIFIED = "verified", "Verified"
        # No longer qualifies (e.g. its federal authority went inactive).
        # Kept rather than deleted, since it may have been claimed.
        INACTIVE = "inactive", "Inactive"

    # Identity. For claimed profiles these belong to the mover; the FMCSA
    # import only fills them in while a profile is unclaimed.
    name = models.CharField(max_length=200, help_text="Legal name")
    dba_name = models.CharField("DBA name", max_length=200, blank=True)
    # Optional: many local movers have no USDOT number.
    usdot_number = models.PositiveIntegerField("USDOT number", unique=True, null=True, blank=True)
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
    source = models.CharField(max_length=10, choices=Source.choices, help_text="Where the profile came from")
    claimed = models.BooleanField(default=False)
    # Only the Google place ID may be stored. Ratings and other Google data
    # are fetched live, never saved.
    google_place_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    # Federal (FMCSA) data, refreshed by every import, claimed or not.
    fmcsa_authority_active = models.BooleanField(
        "FMCSA authority active", null=True, blank=True,
        help_text="Active common or contract household goods authority in FMCSA's data",
    )
    fmcsa_synced_at = models.DateTimeField(
        "FMCSA synced at", null=True, blank=True,
        help_text="Last time the FMCSA import found this carrier",
    )

    # Washington UTC data, refreshed by every UTC import.
    utc_company_id = models.PositiveIntegerField(
        "UTC company ID", null=True, blank=True, unique=True,
        help_text="The number in the company's utc.wa.gov/company/... page address",
    )
    utc_status = models.CharField(
        "UTC status", max_length=20, blank=True,
        help_text="As the UTC lists it: Active, Pending, Unregulated, Inactive. Blank if not on the UTC list.",
    )
    utc_synced_at = models.DateTimeField("UTC synced at", null=True, blank=True)
    utc_detail_synced_at = models.DateTimeField("UTC company page read at", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        number = f"USDOT {self.usdot_number}" if self.usdot_number else f"UTC {self.utc_company_id or '-'}"
        return f"{self.dba_name or self.name} ({number})"

    @property
    def utc_permit_active(self):
        return self.utc_status == "Active"

    def is_bookable(self):
        """Customers can only book a verified mover with a UTC permit number."""
        return self.status == self.Status.VERIFIED and bool(self.utc_permit_number)


class ImportRun(models.Model):
    """One run of an import (FMCSA or UTC), from the command line or the
    Movers page, so the app can show what happened last. A run with no
    finished_at is still going."""

    class Kind(models.TextChoices):
        FMCSA = "fmcsa", "FMCSA"
        UTC = "utc", "Washington UTC"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FMCSA)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=2)
    source = models.CharField(max_length=255, help_text="What was read: the FMCSA dataset, a CSV file, or the UTC lookup")
    dry_run = models.BooleanField(default=False)
    # Empty when run from the command line.
    triggered_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="mover_imports"
    )
    succeeded = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)
    # Messages worth reviewing (conflicts, deactivations), capped.
    messages = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        what = "Dry run" if self.dry_run else "Import"
        return f"{self.get_kind_display()} {what.lower()} {self.state} at {self.started_at:%Y-%m-%d %H:%M}"
