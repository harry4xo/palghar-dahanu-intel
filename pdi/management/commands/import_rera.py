from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pdi.services.rera_import import import_file


class Command(BaseCommand):
    help = "Import MahaRERA crawler output (JSONL) and create change events."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(settings.DATA_DIR / "rera" / "projects.jsonl"))

    def handle(self, path, **opts):
        try:
            imported, events = import_file(path)
        except FileNotFoundError:
            raise CommandError(f"{path} not found — run the crawler first (python -m scrapers.maharera.cli ...)")
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} registrations, {events} new events"))
