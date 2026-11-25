"""Turns FMCSA census rows into Mover profiles, confirming each carrier
through QCMobile first. Used by `manage.py import_fmcsa_movers`.

Rules:
- A carrier is imported only if QCMobile finds it, it's allowed to operate,
  it isn't out of service, and its cargo includes household goods.
- New profiles start unclaimed and unverified.
- Claimed profiles belong to the mover: only the federal (FMCSA) fields are
  refreshed, never the name, contact details, UTC permit or claim.
- A carrier that stops qualifying is set to inactive, not deleted:
    * not allowed to operate / out of service: always (claimed or not)
    * no household goods, not found, or gone from the census: only while
      unclaimed. A claimed profile is left for a person to review.
- A carrier whose lookup errors is left exactly as it was.
- Movers that were never confirmed by an import (e.g. self-listed) are
  never deactivated for being missing from the census.
"""

import time
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .fmcsa import FMCSAError, census_mc_number, is_candidate
from .models import Mover


@dataclass
class ImportStats:
    candidates: int = 0
    confirmed: int = 0
    created: int = 0
    updated: int = 0
    rejected: int = 0
    deactivated: int = 0
    errors: int = 0


def _clean(value, max_length):
    return " ".join(str(value or "").split())[:max_length]


def census_profile_fields(row):
    """Identity fields for a Mover, from one census row."""
    return {
        "name": _clean(row.get("legal_name"), 200) or f"USDOT {row.get('dot_number')}",
        "dba_name": _clean(row.get("dba_name"), 200),
        "mc_number": _clean(census_mc_number(row), 20),
        "street": _clean(row.get("phy_street"), 200),
        "city": _clean(row.get("phy_city"), 100),
        "state": _clean(row.get("phy_state"), 2).upper(),
        "zip_code": _clean(row.get("phy_zip"), 10),
        "phone": _clean(row.get("phone"), 20),
    }


def import_movers(rows, client, *, state="WA", dry_run=False, limit=None, sleep_seconds=0.25,
                  sleep=time.sleep, now=None, log=lambda msg: None, debug=lambda msg: None):
    """Import movers from census `rows` (any iterable of dicts). `client`
    needs a `check(dot_number)` method returning a CarrierCheck."""
    now = now or timezone.now()
    stats = ImportStats()
    in_census = set()
    first = True

    for row in rows:
        if not is_candidate(row, state):
            continue
        try:
            dot = int(str(row.get("dot_number", "")).strip())
        except ValueError:
            continue
        if dot in in_census:
            continue
        if limit is not None and stats.candidates >= limit:
            break
        stats.candidates += 1
        in_census.add(dot)

        if not first and sleep_seconds:
            sleep(sleep_seconds)
        first = False

        try:
            check = client.check(dot)
        except FMCSAError as err:
            stats.errors += 1
            log(f"USDOT {dot}: {err}. Left unchanged.")
            continue

        existing = Mover.objects.filter(usdot_number=dot).first()

        if not check.qualifies:
            stats.rejected += 1
            debug(f"USDOT {dot}: rejected ({check.reason}).")
            if existing:
                _record_rejection(existing, check, stats, dry_run, now, log)
            continue

        stats.confirmed += 1
        if existing:
            stats.updated += 1
            debug(f"USDOT {dot}: confirmed, updating.")
            if not dry_run:
                _update_confirmed(existing, row, now)
        else:
            stats.created += 1
            debug(f"USDOT {dot}: confirmed, creating.")
            if not dry_run:
                Mover.objects.create(
                    usdot_number=dot,
                    **census_profile_fields(row),
                    fmcsa_allowed_to_operate=True,
                    fmcsa_out_of_service=False,
                    hhg_confirmed_at=now,
                    last_seen_in_census=now,
                )

    # Only a complete run can say a carrier has left the census.
    if limit is None:
        gone = (
            Mover.objects.filter(state=state, claimed=False, hhg_confirmed_at__isnull=False)
            .exclude(status=Mover.Status.INACTIVE)
            .exclude(usdot_number__in=in_census)
        )
        for mover in gone:
            stats.deactivated += 1
            log(f"USDOT {mover.usdot_number}: no longer in the census as an active household goods carrier. Set to inactive.")
            if not dry_run:
                mover.status = Mover.Status.INACTIVE
                mover.save(update_fields=["status", "updated_at"])

    return stats


@transaction.atomic
def _update_confirmed(mover, row, now):
    mover.fmcsa_allowed_to_operate = True
    mover.fmcsa_out_of_service = False
    mover.hhg_confirmed_at = now
    mover.last_seen_in_census = now
    if not mover.claimed:
        for field, value in census_profile_fields(row).items():
            setattr(mover, field, value)
    if mover.status == Mover.Status.INACTIVE:
        mover.status = Mover.Status.UNVERIFIED  # qualifies again; needs re-verifying
    mover.save()


def _record_rejection(mover, check, stats, dry_run, now, log):
    federal_block = check.found and (not check.allowed_to_operate or check.out_of_service)
    deactivate = mover.status != Mover.Status.INACTIVE and (federal_block or not mover.claimed)
    if deactivate:
        stats.deactivated += 1
        log(f"USDOT {mover.usdot_number}: {check.reason}. Set to inactive.")
    elif mover.claimed and mover.status != Mover.Status.INACTIVE:
        log(f"USDOT {mover.usdot_number}: {check.reason}, but the profile is claimed. Left active for review.")
    if dry_run:
        return
    if check.found:
        mover.fmcsa_allowed_to_operate = check.allowed_to_operate
        mover.fmcsa_out_of_service = check.out_of_service
    mover.last_seen_in_census = now
    if deactivate:
        mover.status = Mover.Status.INACTIVE
    mover.save()
