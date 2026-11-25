from django.contrib import admin

from .models import Mover


@admin.register(Mover)
class MoverAdmin(admin.ModelAdmin):
    list_display = ("name", "dba_name", "usdot_number", "city", "status", "claimed", "utc_permit_number", "hhg_confirmed_at")
    list_filter = ("status", "claimed", "fmcsa_allowed_to_operate", "fmcsa_out_of_service")
    search_fields = ("name", "dba_name", "usdot_number", "mc_number", "utc_permit_number", "city")
    readonly_fields = ("fmcsa_allowed_to_operate", "fmcsa_out_of_service", "hhg_confirmed_at", "last_seen_in_census", "created_at", "updated_at")
