from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from movers.fmcsa import FMCSAError, check_state, iter_authority_api, iter_authority_file
from movers.importer import import_movers


class Command(BaseCommand):
    help = (
        "Import household goods movers with active federal authority from FMCSA's "
        "public 'Carrier - All With History' data as unclaimed, unverified Mover "
        "profiles. No API key needed. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--state", default="WA", help="Two-letter state code (default: WA).")
        parser.add_argument("--file", metavar="PATH",
                            help="Read a CSV export of the dataset instead of downloading it.")
        parser.add_argument("--limit", type=int, metavar="N",
                            help="Process at most N carriers. A limited run never deactivates missing carriers.")
        parser.add_argument("--dry-run", action="store_true", help="Show what would change, but save nothing.")

    def handle(self, *args, **options):
        try:
            state = check_state(options["state"].strip())
        except ValueError:
            raise CommandError(f"--state must be a two-letter state code, not {options['state']!r}.") from None
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")

        def debug(message):
            if options["verbosity"] >= 2:
                self.stdout.write(message)

        path = options["file"]
        if path:
            if not Path(path).is_file():
                raise CommandError(f"File not found: {path}")
            self.stdout.write(f"Reading household goods carriers in {state} from {path}...")
            rows = iter_authority_file(path)
        else:
            self.stdout.write(f"Downloading household goods carriers in {state} from FMCSA...")
            rows = iter_authority_api(state)

        try:
            stats = import_movers(
                rows, state=state, dry_run=options["dry_run"], limit=options["limit"],
                log=self.stderr.write, debug=debug,
            )
        except FMCSAError as err:
            raise CommandError(str(err)) from None

        prefix = "Dry run, nothing saved. " if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}{stats.records} records, {stats.carriers} motor carriers: "
            f"{stats.created} new, {stats.updated} updated, "
            f"{stats.inactive_skipped} skipped (no active authority), "
            f"{stats.deactivated} set inactive, {stats.conflicts} MC conflicts. "
            f"{stats.forwarders_skipped} freight forwarders skipped."
        ))
        if stats.conflicts:
            self.stdout.write(self.style.WARNING(
                f"{stats.conflicts} carriers were skipped because their MC number is on another profile. See the messages above."
            ))
