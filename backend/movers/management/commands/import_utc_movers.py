from django.core.management.base import BaseCommand, CommandError

from movers.services import run_import
from movers.utc import UTCError


class Command(BaseCommand):
    help = (
        "Import household goods movers from the Washington UTC's public regulated "
        "companies lookup. Active permit holders are verified with their permit "
        "number; Pending ones are unverified; Unregulated ones are inactive. "
        "Reads utc.wa.gov politely (one request a second). Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, metavar="N",
                            help="Process at most N companies. A limited run never deactivates missing companies.")
        parser.add_argument("--include-inactive", action="store_true",
                            help="Also import companies the UTC lists as Inactive (mostly old, cancelled permits).")
        parser.add_argument("--sleep", type=float, metavar="SECONDS",
                            help="Pause between requests to utc.wa.gov (default: 1).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Read the UTC list and show what would change, but save nothing. Skips company pages, so it's quick.")

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")
        if options["sleep"] is not None and options["sleep"] < 0:
            raise CommandError("--sleep can't be negative.")

        def debug(message):
            if options["verbosity"] >= 2:
                self.stdout.write(message)

        self.stdout.write("Reading household goods carriers from the Washington UTC...")
        try:
            _, stats = run_import(
                "utc", dry_run=options["dry_run"], limit=options["limit"],
                include_inactive=options["include_inactive"], sleep_seconds=options["sleep"],
                log=self.stderr.write, debug=debug,
            )
        except UTCError as err:
            raise CommandError(str(err)) from None

        prefix = "Dry run, nothing saved. " if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}{stats.listed} listings, {stats.companies} companies: {stats.created} new, "
            f"{stats.updated} updated, {stats.verified} verified with a UTC permit, "
            f"{stats.deactivated} set inactive, {stats.inactive_skipped} inactive skipped, "
            f"{stats.duplicates_skipped} duplicate listings skipped, "
            f"{stats.details_read} company pages read, {stats.conflicts} conflicts, {stats.errors} errors."
        ))
        if stats.errors:
            self.stdout.write(self.style.WARNING(f"{stats.errors} company pages couldn't be read. Re-run to retry them."))
