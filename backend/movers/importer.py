"""Turns FMCSA household goods authority records into Mover profiles. Used
by `manage.py import_fmcsa_movers`.

Rules:
- Records are combined per USDOT number (see fmcsa.combine_records). Only
  motor carriers (MC dockets) count; freight forwarders are skipped.
- A carrier is imported only if its federal authority is active. New
  profiles start unclaimed and unverified.
- Re-runs update profiles, never duplicate them. Claimed profiles belong to
  the mover: only the federal fields are refreshed, never the name, contact
  details, UTC permit, status or claim.
- If a carrier's authority goes inactive, or it disappears from the data on
  a full run, an unclaimed profile is set to inactive (never deleted). A
  claimed profile is left alone and logged for review: federal authority
  covers interstate moves and isn't the same thing as a UTC permit.
- A carrier whose MC number is already on another USDOT's profile is
  skipped and logged rather than merged.
- Movers the import never found (e.g. self-listed) are never touched.
- The Washington UTC has the final say for in-state moves: a mover the UTC
  lists as Active is never deactivated here, and one the UTC lists as not
  permitted (e.g. Unregulated) is never reactivated here.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .fmcsa import combine_records
from .models import Mover


@dataclass
class ImportStats:
    records: int = 0
    carriers: int = 0
    created: int = 0
    updated: int = 0
    inactive_skipped: int = 0  # no active authority and no existing profile
    forwarders_skipped: int = 0
    conflicts: int = 0
    deactivated: int = 0


def _clean(value, max_length):
    return " ".join(str(value or "").split())[:max_length]


def profile_fields(carrier):
    """Identity fields for a Mover, from a combined carrier."""
    row = carrier.record
    return {
        "name": _clean(row.get("legal_name"), 200) or f"USDOT {carrier.dot_number}",
        "dba_name": _clean(row.get("dba_name"), 200),
        "mc_number": carrier.mc_number,
        "street": _clean(row.get("bus_street_po"), 200),
        "city": _clean(row.get("bus_city"), 100),
        "state": _clean(row.get("bus_state_code"), 2).upper(),
        "zip_code": _clean(row.get("bus_zip_code"), 10),
        "phone": _clean(row.get("bus_telno"), 20),
    }


def import_movers(rows, *, state="WA", dry_run=False, limit=None, now=None,
                  log=lambda msg: None, debug=lambda msg: None):
    """Import movers from FMCSA authority `rows` (any iterable of dicts)."""
    now = now or timezone.now()
    combined = combine_records(rows, state)
    stats = ImportStats(records=combined.records, forwarders_skipped=combined.forwarders_skipped)
    carriers = combined.carriers if limit is None else combined.carriers[:limit]
    stats.carriers = len(carriers)

    for carrier in carriers:
        dot = carrier.dot_number
        existing = Mover.objects.filter(usdot_number=dot).first()

        if not carrier.authority_active:
            if existing:
                _record_inactive_authority(existing, stats, dry_run, now, log)
            else:
                stats.inactive_skipped += 1
                debug(f"USDOT {dot}: no active authority, skipped.")
            continue

        clash = Mover.objects.filter(mc_number=carrier.mc_number).exclude(usdot_number=dot).first()
        if clash:
            stats.conflicts += 1
            log(f"USDOT {dot}: MC {carrier.mc_number} is already on USDOT {clash.usdot_number}'s profile. Skipped for review.")
            continue

        if existing:
            stats.updated += 1
            debug(f"USDOT {dot}: updating.")
            if not dry_run:
                _update(existing, carrier, now)
        else:
            stats.created += 1
            debug(f"USDOT {dot}: creating.")
            if not dry_run:
                Mover.objects.create(
                    usdot_number=dot, **profile_fields(carrier), source=Mover.Source.FMCSA,
                    fmcsa_authority_active=True, fmcsa_synced_at=now,
                )

    # Only a complete run can say a carrier has left the data.
    if limit is None:
        found = {c.dot_number for c in combined.carriers}
        gone = (
            Mover.objects.filter(state=state.upper(), claimed=False, fmcsa_synced_at__isnull=False)
            .exclude(status=Mover.Status.INACTIVE)
            .exclude(usdot_number__in=found)
            .exclude(utc_status="Active")
        )
        for mover in gone:
            stats.deactivated += 1
            log(f"USDOT {mover.usdot_number}: no longer in FMCSA's household goods data. Set to inactive.")
            if not dry_run:
                mover.status = Mover.Status.INACTIVE
                mover.save(update_fields=["status", "updated_at"])

    return stats


@transaction.atomic
def _update(mover, carrier, now):
    mover.fmcsa_authority_active = True
    mover.fmcsa_synced_at = now
    if not mover.claimed:
        for field, value in profile_fields(carrier).items():
            setattr(mover, field, value)
        if mover.status == Mover.Status.INACTIVE and not utc_blocks(mover):
            mover.status = Mover.Status.UNVERIFIED  # active again; needs re-verifying
    mover.save()


def utc_blocks(mover):
    """The UTC knows this mover and doesn't list it as permitted."""
    return bool(mover.utc_status) and mover.utc_status not in ("Active", "Pending")


def _record_inactive_authority(mover, stats, dry_run, now, log):
    deactivate = not mover.claimed and mover.status != Mover.Status.INACTIVE and not mover.utc_permit_active
    if mover.utc_permit_active and not mover.claimed:
        log(f"USDOT {mover.usdot_number}: federal authority is no longer active, but the UTC lists an active permit. Kept.")
    if deactivate:
        stats.deactivated += 1
        log(f"USDOT {mover.usdot_number}: federal authority is no longer active. Set to inactive.")
    elif mover.claimed:
        log(f"USDOT {mover.usdot_number}: federal authority is no longer active, but the profile is claimed. Left as is for review.")
    if dry_run:
        return
    mover.fmcsa_authority_active = False
    mover.fmcsa_synced_at = now
    if deactivate:
        mover.status = Mover.Status.INACTIVE
    mover.save()
