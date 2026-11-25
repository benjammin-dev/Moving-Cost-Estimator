from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from movers.fmcsa import FMCSAError, QCMobileClient, iter_census_api, iter_census_file
from movers.importer import import_movers


class Command(BaseCommand):
    help = (
        "Import household goods movers from FMCSA's Company Census File as "
        "unclaimed, unverified Mover profiles, confirming each carrier through "
        "the QCMobile API. Needs FMCSA_WEBKEY in backend/.env. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--state", default="WA", help="Two-letter state code (default: WA).")
        parser.add_argument("--census-file", metavar="PATH",
                            help="Read a downloaded Company Census File CSV instead of querying the DOT portal.")
        parser.add_argument("--limit", type=int, metavar="N",
                            help="Check at most N carriers. A limited run never deactivates missing carriers.")
        parser.add_argument("--sleep", type=float, default=0.25, metavar="SECONDS",
                            help="Pause between carriers, to go easy on QCMobile (default: 0.25).")
        parser.add_argument("--dry-run", action="store_true", help="Check everything but save nothing.")

    def handle(self, *args, **options):
        webkey = getattr(settings, "FMCSA_WEBKEY", "")
        if not webkey:
            raise CommandError("FMCSA_WEBKEY is not set. Add FMCSA_WEBKEY=your-key to backend/.env.")
        state = options["state"].strip().upper()
        if not (len(state) == 2 and state.isalpha()):
            raise CommandError(f"--state must be a two-letter state code, not {options['state']!r}.")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")
        if options["sleep"] < 0:
            raise CommandError("--sleep can't be negative.")

        # Belt and braces: nothing printed may contain the key.
        def safe(text):
            return text.replace(webkey, "***")

        def log(message):
            self.stderr.write(safe(message))

        def debug(message):
            if options["verbosity"] >= 2:
                self.stdout.write(safe(message))

        path = options["census_file"]
        if path:
            if not Path(path).is_file():
                raise CommandError(f"Census file not found: {path}")
            rows = iter_census_file(path, state)
            self.stdout.write(f"Reading {path} for active household goods carriers in {state}...")
        else:
            rows = iter_census_api(state)
            self.stdout.write(f"Downloading active household goods carriers in {state} from the Company Census File...")

        try:
            stats = import_movers(
                rows, QCMobileClient(webkey), state=state, dry_run=options["dry_run"],
                limit=options["limit"], sleep_seconds=options["sleep"], log=log, debug=debug,
            )
        except FMCSAError as err:
            raise CommandError(safe(str(err))) from None

        prefix = "Dry run, nothing saved. " if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Checked {stats.candidates} carriers: {stats.confirmed} confirmed "
            f"({stats.created} new, {stats.updated} updated), {stats.rejected} rejected, "
            f"{stats.deactivated} set inactive, {stats.errors} errors."
        ))
        if stats.errors:
            self.stdout.write(self.style.WARNING(
                f"{stats.errors} lookups failed and were left unchanged. Re-run to retry them."
            ))
