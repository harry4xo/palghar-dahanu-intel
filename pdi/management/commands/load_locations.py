from django.conf import settings
from django.core.management.base import BaseCommand

from pdi.services.loaders import load_locations


class Command(BaseCommand):
    help = "Load the taluka / village / micro-market reference table (data/locations.json)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(settings.DATA_DIR / "locations.json"))

    def handle(self, path, **opts):
        created, updated = load_locations(path)
        self.stdout.write(self.style.SUCCESS(f"Locations: {created} created, {updated} updated"))
