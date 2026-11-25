from django.contrib import admin

from .models import ImportRun, Mover


@admin.register(Mover)
class MoverAdmin(admin.ModelAdmin):
    list_display = ("name", "dba_name", "usdot_number", "city", "status", "claimed", "utc_permit_number", "fmcsa_authority_active")
    list_filter = ("status", "claimed", "fmcsa_authority_active")
    search_fields = ("name", "dba_name", "usdot_number", "mc_number", "utc_permit_number", "city")
    readonly_fields = ("fmcsa_authority_active", "fmcsa_synced_at", "created_at", "updated_at")


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "state", "dry_run", "succeeded", "triggered_by", "source")
    list_filter = ("succeeded", "dry_run")
    readonly_fields = [f.name for f in ImportRun._meta.fields]
