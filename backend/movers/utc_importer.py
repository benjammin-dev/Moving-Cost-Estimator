"""Turns the Washington UTC's list of household goods carriers into Mover
profiles. Used by `manage.py import_utc_movers` and the Movers page.

Rules:
- Companies the UTC lists as Active, Pending or Unregulated are imported
  (Inactive ones too with include_inactive). A company is matched to an
  existing profile by its UTC company ID, then by USDOT number.
- The company's detail page is read for its address, phone and household
  goods permit, but only when that's still needed: new companies, companies
  never read before, and active ones with no permit number yet. That keeps
  re-runs to the ~30 list pages.
- Profiles the UTC import creates: Active with an active household goods
  permit (e.g. HG060620) -> verified with that permit number, so bookable;
  Pending -> unverified; Unregulated / Inactive -> inactive.
- Profiles from other sources (FMCSA, staff) get verified the same way when
  the UTC lists an active permit. If the UTC doesn't, they're never verified
  (a verified one goes back to unverified), but they aren't set inactive:
  an interstate carrier can still be valid without an in-state permit.
- Claimed profiles belong to the mover: only the UTC fields are refreshed,
  and anything that doesn't match (e.g. the UTC no longer lists the permit as
  active) is logged for review instead of changed.
- For profiles from other sources (FMCSA, staff), the UTC only fills in
  details that are blank; it doesn't overwrite them.
- On a full run, a linked profile that's no longer on the UTC list at all
  loses its UTC status; if the UTC import created it, it's set to inactive
  (unclaimed only).
- A dry run doesn't read detail pages, so it assumes every Active company
  has a permit when counting how many would be verified.
- A failed detail page leaves that company unchanged for this run.
"""

import time
from dataclasses import dataclass

from django.utils import timezone

from .models import Mover
from .utc import UTCError

IMPORTED_STATUSES = {"Active", "Pending", "Unregulated"}
VERIFIED_STATUS = "Active"
UNVERIFIED_STATUSES = {"Pending"}
IDENTITY_FIELDS = ("name", "dba_name", "street", "city", "state", "zip_code", "phone")


@dataclass
class UTCStats:
    listed: int = 0  # rows read from the UTC list
    companies: int = 0  # distinct companies considered
    created: int = 0
    updated: int = 0
    verified: int = 0  # profiles verified with a UTC permit by this run
    deactivated: int = 0
    inactive_skipped: int = 0  # UTC Inactive companies not imported
    details_read: int = 0
    conflicts: int = 0
    errors: int = 0


def _group(listed):
    """One entry per UTC company: (first listing, every USDOT it's listed with)."""
    companies = {}
    for company in listed:
        entry = companies.setdefault(company.company_id, [company, set()])
        if company.usdot_number:
            entry[1].add(company.usdot_number)
    return companies


def _clean(value, max_length):
    return " ".join(str(value or "").split())[:max_length]


def import_utc_movers(listed, get_detail, *, include_inactive=False, dry_run=False, limit=None,
                      sleep_seconds=1.0, sleep=time.sleep, now=None,
                      log=lambda msg: None, debug=lambda msg: None):
    """`listed` is an iterable of utc.ListedCompany; `get_detail(company_id)`
    returns a utc.CompanyDetail."""
    now = now or timezone.now()
    stats = UTCStats()
    listed = list(listed)
    stats.listed = len(listed)
    companies = _group(listed)
    wanted = IMPORTED_STATUSES | ({"Inactive"} if include_inactive else set())
    on_list = set(companies)
    processed = 0
    first_request = True

    for company_id in sorted(companies, key=lambda cid: (companies[cid][0].name.lower(), cid)):
        company, usdots = companies[company_id]
        mover, clash = _match(company_id, usdots)
        if clash:
            stats.conflicts += 1
            log(f"UTC {company_id} ({company.name}): {clash} Skipped for review.")
            continue
        if company.status not in wanted:
            if mover is None:
                stats.inactive_skipped += 1
                continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        stats.companies += 1

        detail = None
        if company.status in wanted and _needs_detail(mover, company) and not dry_run:
            if not first_request and sleep_seconds:
                sleep(sleep_seconds)
            first_request = False
            try:
                detail = get_detail(company_id)
                stats.details_read += 1
            except UTCError as err:
                stats.errors += 1
                log(f"UTC {company_id} ({company.name}): {err}. Left unchanged.")
                continue

        usdot = (detail.usdot_number if detail and detail.usdot_number else None) or (min(usdots) if usdots else None)
        if usdot and Mover.objects.filter(usdot_number=usdot).exclude(pk=getattr(mover, "pk", None)).exists():
            usdot = None  # already on another profile; don't move it
        permit = detail.permit_number if detail else ""
        if permit and Mover.objects.filter(utc_permit_number=permit).exclude(pk=getattr(mover, "pk", None)).exists():
            stats.conflicts += 1
            log(f"UTC {company_id} ({company.name}): permit {permit} is already on another profile. Permit not set.")
            permit = ""

        if mover is None:
            stats.created += 1
            status = _status_for(company.status, permit or (dry_run and company.status == VERIFIED_STATUS))
            if status == Mover.Status.VERIFIED:
                stats.verified += 1
            debug(f"UTC {company_id} ({company.name}): creating as {status}.")
            if not dry_run:
                Mover.objects.create(
                    source=Mover.Source.UTC,
                    usdot_number=usdot,
                    status=status,
                    utc_permit_number=permit or None,
                    utc_company_id=company_id,
                    utc_status=company.status,
                    utc_synced_at=now,
                    utc_detail_synced_at=now if detail else None,
                    **_identity(company, detail),
                )
            continue

        stats.updated += 1
        changes = _update(mover, company, detail, usdot, permit, now, log, assume_permit=dry_run)
        if changes.get("verified"):
            stats.verified += 1
        if changes.get("deactivated"):
            stats.deactivated += 1
        debug(f"UTC {company_id} ({company.name}): updating.")
        if not dry_run:
            mover.save()

    # A full run can say a company has left the UTC list entirely.
    if limit is None:
        gone = Mover.objects.filter(utc_company_id__isnull=False).exclude(utc_company_id__in=on_list).exclude(utc_status="")
        for mover in gone:
            mover.utc_status = ""
            if mover.claimed:
                log(f"UTC {mover.utc_company_id} ({mover.name}): no longer on the UTC list, but the profile is claimed. Left as is for review.")
            elif mover.source == Mover.Source.UTC and mover.status != Mover.Status.INACTIVE:
                stats.deactivated += 1
                mover.status = Mover.Status.INACTIVE
                log(f"UTC {mover.utc_company_id} ({mover.name}): no longer on the UTC list. Set to inactive.")
            elif mover.status == Mover.Status.VERIFIED:
                mover.status = Mover.Status.UNVERIFIED
                log(f"UTC {mover.utc_company_id} ({mover.name}): no longer on the UTC list. Set back to unverified.")
            if not dry_run:
                mover.save(update_fields=["status", "utc_status", "updated_at"])

    return stats


def _match(company_id, usdots):
    """(mover or None, clash message or None)."""
    mover = Mover.objects.filter(utc_company_id=company_id).first()
    if mover:
        return mover, None
    by_usdot = list(Mover.objects.filter(usdot_number__in=usdots)) if usdots else []
    if len(by_usdot) > 1:
        numbers = ", ".join(str(m.usdot_number) for m in by_usdot)
        return None, f"its USDOT numbers match more than one profile ({numbers})."
    if by_usdot and by_usdot[0].utc_company_id:
        return None, f"USDOT {by_usdot[0].usdot_number} is already linked to UTC {by_usdot[0].utc_company_id}."
    return (by_usdot[0] if by_usdot else None), None


def _needs_detail(mover, company):
    if mover is None or mover.utc_detail_synced_at is None:
        return True
    return company.status == VERIFIED_STATUS and not mover.utc_permit_number


def _status_for(utc_status, permit):
    if utc_status == VERIFIED_STATUS:
        return Mover.Status.VERIFIED if permit else Mover.Status.UNVERIFIED
    if utc_status in UNVERIFIED_STATUSES:
        return Mover.Status.UNVERIFIED
    return Mover.Status.INACTIVE


def _identity(company, detail):
    fields = {
        "name": _clean(detail.name if detail and detail.name else company.name, 200),
        "dba_name": _clean(detail.dba_name if detail and detail.dba_name else company.dba_name, 200),
        "street": "", "city": "", "state": "", "zip_code": "", "phone": "",
    }
    if detail:
        fields.update({
            "street": _clean(detail.street, 200),
            "city": _clean(detail.city, 100),
            "state": _clean(detail.state, 2).upper(),
            "zip_code": _clean(detail.zip_code, 10),
            "phone": _clean(detail.phone, 20),
        })
    return fields


def _update(mover, company, detail, usdot, permit, now, log, assume_permit=False):
    """Apply the UTC listing to an existing profile (in memory; caller saves)."""
    changes = {}
    mover.utc_company_id = mover.utc_company_id or company.company_id
    mover.utc_status = company.status
    mover.utc_synced_at = now
    if detail:
        mover.utc_detail_synced_at = now
    if usdot and not mover.usdot_number:
        mover.usdot_number = usdot

    if mover.claimed:
        if company.status != VERIFIED_STATUS and mover.status == Mover.Status.VERIFIED:
            log(f"UTC {company.company_id} ({mover.name}): the UTC lists it as {company.status}, but the profile is claimed and verified. Left as is for review.")
        if permit and mover.utc_permit_number and permit != mover.utc_permit_number:
            log(f"UTC {company.company_id} ({mover.name}): the UTC permit is {permit}, the profile says {mover.utc_permit_number}. Left as is for review.")
        return changes

    identity = _identity(company, detail)
    for field_name in IDENTITY_FIELDS:
        value = identity[field_name]
        if value and (mover.source == Mover.Source.UTC or not getattr(mover, field_name)):
            setattr(mover, field_name, value)

    if permit:
        mover.utc_permit_number = permit
    has_permit = bool(mover.utc_permit_number) or (assume_permit and company.status == VERIFIED_STATUS)
    status = _status_for(company.status, has_permit)
    if mover.source != Mover.Source.UTC and status != Mover.Status.VERIFIED:
        # Not permitted in-state: never verified, but not hidden either.
        if mover.status == Mover.Status.VERIFIED:
            log(f"UTC {company.company_id} ({mover.name}): the UTC lists it as {company.status}. Set back to unverified.")
            mover.status = Mover.Status.UNVERIFIED
        return changes

    if status == Mover.Status.VERIFIED and mover.status != Mover.Status.VERIFIED:
        changes["verified"] = True
    if status == Mover.Status.INACTIVE and mover.status != Mover.Status.INACTIVE:
        changes["deactivated"] = True
        log(f"UTC {company.company_id} ({mover.name}): the UTC lists it as {company.status}. Set to inactive.")
    mover.status = status
    return changes
