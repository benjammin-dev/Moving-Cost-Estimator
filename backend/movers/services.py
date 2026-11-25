"""Runs the FMCSA import and records it as an ImportRun. Shared by
`manage.py import_fmcsa_movers` and the Run import button on the Movers page."""

from dataclasses import asdict
from pathlib import Path

from django.utils import timezone

from .fmcsa import iter_authority_api, iter_authority_file
from .importer import import_movers
from .models import ImportRun

FMCSA_SOURCE = "FMCSA Carrier - All With History (6eyk-hxee)"
MAX_MESSAGES = 200


def run_import(*, state="WA", dry_run=False, limit=None, file_path=None, triggered_by=None,
               log=lambda msg: None, debug=lambda msg: None):
    """Run the import and save an ImportRun. Returns (run, stats). If the
    import fails, the run is saved with the error and the exception re-raised."""
    run = ImportRun.objects.create(
        state=state,
        source=Path(file_path).name if file_path else FMCSA_SOURCE,
        dry_run=dry_run,
        triggered_by=triggered_by,
    )

    def capture(message):
        if len(run.messages) < MAX_MESSAGES:
            run.messages.append(message)
        log(message)

    try:
        rows = iter_authority_file(file_path) if file_path else iter_authority_api(state)
        stats = import_movers(rows, state=state, dry_run=dry_run, limit=limit, log=capture, debug=debug)
    except Exception as err:
        run.error = str(err) or type(err).__name__
        run.finished_at = timezone.now()
        run.save()
        raise

    run.succeeded = True
    run.stats = asdict(stats)
    run.finished_at = timezone.now()
    run.save()
    return run, stats
