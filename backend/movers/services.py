"""Runs the FMCSA and UTC imports and records each as an ImportRun. Shared
by the management commands and the import buttons on the Movers page.

The page starts imports in a background thread, because the first UTC import
reads several hundred company pages at one a second. The page polls the
ImportRun until it has a finished_at.
"""

import threading
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import utc
from .fmcsa import iter_authority_api, iter_authority_file
from .importer import import_movers
from .models import ImportRun
from .utc_importer import import_utc_movers

FMCSA_SOURCE = "FMCSA Carrier - All With History (6eyk-hxee)"
UTC_SOURCE = "Washington UTC regulated companies (household goods carriers)"
MAX_MESSAGES = 200
# A run unfinished after this long is assumed dead (e.g. the server restarted).
STALE_AFTER = timedelta(hours=2)


class ImportAlreadyRunning(Exception):
    pass


def create_run(kind, *, state="WA", dry_run=False, file_path=None, triggered_by=None):
    if kind == ImportRun.Kind.UTC:
        source = UTC_SOURCE
    else:
        source = Path(file_path).name if file_path else FMCSA_SOURCE
    return ImportRun.objects.create(kind=kind, state=state, source=source, dry_run=dry_run, triggered_by=triggered_by)


def execute(run, *, limit=None, file_path=None, include_inactive=False, sleep_seconds=None,
            log=lambda msg: None, debug=lambda msg: None):
    """Run the import for an existing ImportRun and record the outcome. If the
    import fails, the run is saved with the error and the exception re-raised."""

    def capture(message):
        if len(run.messages) < MAX_MESSAGES:
            run.messages.append(message)
        log(message)

    try:
        if run.kind == ImportRun.Kind.UTC:
            pause = settings.UTC_IMPORT_SLEEP_SECONDS if sleep_seconds is None else sleep_seconds
            stats = import_utc_movers(
                utc.iter_listed_companies(sleep_seconds=pause), utc.get_detail,
                include_inactive=include_inactive, dry_run=run.dry_run, limit=limit,
                sleep_seconds=pause, log=capture, debug=debug,
            )
        else:
            rows = iter_authority_file(file_path) if file_path else iter_authority_api(run.state)
            stats = import_movers(rows, state=run.state, dry_run=run.dry_run, limit=limit, log=capture, debug=debug)
    except Exception as err:
        run.error = str(err) or type(err).__name__
        run.finished_at = timezone.now()
        run.save()
        raise

    run.succeeded = True
    run.stats = asdict(stats)
    run.finished_at = timezone.now()
    run.save()
    return stats


def run_import(kind=ImportRun.Kind.FMCSA, *, state="WA", dry_run=False, limit=None, file_path=None,
               include_inactive=False, sleep_seconds=None, triggered_by=None,
               log=lambda msg: None, debug=lambda msg: None):
    """Run an import now (used by the commands). Returns (run, stats)."""
    run = create_run(kind, state=state, dry_run=dry_run, file_path=file_path, triggered_by=triggered_by)
    stats = execute(run, limit=limit, file_path=file_path, include_inactive=include_inactive,
                    sleep_seconds=sleep_seconds, log=log, debug=debug)
    return run, stats


def running(kind):
    """The unfinished run of this kind, if one is still plausibly going."""
    return (
        ImportRun.objects.filter(kind=kind, finished_at__isnull=True, started_at__gte=timezone.now() - STALE_AFTER)
        .order_by("-started_at").first()
    )


def start_import(kind, *, dry_run=False, triggered_by=None):
    """Start an import for the Movers page. Returns the ImportRun right away;
    the import runs in a background thread unless MOVER_IMPORTS_IN_BACKGROUND
    is off (as in tests), in which case it has finished when this returns."""
    if running(kind):
        raise ImportAlreadyRunning(kind)
    run = create_run(kind, dry_run=dry_run, triggered_by=triggered_by)

    if not settings.MOVER_IMPORTS_IN_BACKGROUND:
        try:
            execute(run)
        except Exception:
            pass  # recorded on the run
        return run

    def work():
        try:
            execute(run)
        except Exception:
            pass  # recorded on the run
        finally:
            connection.close()

    threading.Thread(target=work, name=f"mover-import-{run.pk}", daemon=True).start()
    return run
