from django.core.management.base import BaseCommand

from pdi.services.archive import archive_missing


class Command(BaseCommand):
    help = "Download a local copy of every source that has not been archived yet."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)

    def handle(self, limit=None, **opts):
        ok, failed = archive_missing(limit)
        for url, err in failed:
            self.stdout.write(self.style.WARNING(f"  failed {url}: {err}"))
        self.stdout.write(self.style.SUCCESS(f"Archived {ok}, failed {len(failed)}"))
