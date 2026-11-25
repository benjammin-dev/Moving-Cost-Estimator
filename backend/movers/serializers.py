import re

from rest_framework import serializers

from .models import ImportRun, Mover

PERMIT_PATTERN = re.compile(r"^[A-Z0-9-]{3,20}$")


class MoverSerializer(serializers.ModelSerializer):
    is_bookable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Mover
        fields = [
            "id", "name", "dba_name", "usdot_number", "mc_number",
            "street", "city", "state", "zip_code", "phone",
            "utc_permit_number", "status", "claimed", "google_place_id",
            "fmcsa_authority_active", "fmcsa_synced_at",
            "is_bookable", "created_at", "updated_at",
        ]
        read_only_fields = fields


class MoverUpdateSerializer(serializers.ModelSerializer):
    """Staff can only set the UTC permit number and the status. Everything
    else comes from FMCSA or from the mover."""

    class Meta:
        model = Mover
        fields = ["utc_permit_number", "status"]
        # Uniqueness is checked in validate_utc_permit_number, after the
        # value is cleaned up; the default check would compare the raw text.
        extra_kwargs = {"utc_permit_number": {"validators": []}}

    def validate_utc_permit_number(self, value):
        value = (value or "").strip().upper()
        if not value:
            return None
        if not PERMIT_PATTERN.match(value):
            raise serializers.ValidationError("Use letters, numbers and dashes only.")
        taken = Mover.objects.filter(utc_permit_number=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Another mover already has this UTC permit number.")
        return value

    def validate(self, attrs):
        permit = attrs.get("utc_permit_number", getattr(self.instance, "utc_permit_number", None))
        status = attrs.get("status", getattr(self.instance, "status", None))
        if status == Mover.Status.VERIFIED and not permit:
            raise serializers.ValidationError(
                {"status": "Add the mover's UTC permit number before verifying it."}
            )
        return attrs


class ImportRunSerializer(serializers.ModelSerializer):
    triggered_by = serializers.SerializerMethodField()

    class Meta:
        model = ImportRun
        fields = [
            "id", "started_at", "finished_at", "state", "source", "dry_run",
            "triggered_by", "succeeded", "error", "stats", "messages",
        ]

    def get_triggered_by(self, run):
        return run.triggered_by.username if run.triggered_by else None
