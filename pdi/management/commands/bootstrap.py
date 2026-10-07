from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from pdi.models import Location
from pdi.services.monitor import ensure_default_queries


class Command(BaseCommand):
    help = "Set up a fresh database: locations, coordinates, seed research, MahaRERA data, watch queries."

    def add_arguments(self, parser):
        parser.add_argument("--no-geocode", action="store_true")

    def handle(self, no_geocode=False, **opts):
        call_command("migrate", verbosity=0)
        call_command("load_locations")
        if not no_geocode and Location.objects.filter(latitude__isnull=True).exists():
            try:
                call_command("geocode_locations")
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Geocoding skipped: {exc}"))
        if list((settings.DATA_DIR / "seed").glob("*.json")):
            call_command("load_seed")
        rera = Path(settings.DATA_DIR / "rera" / "projects.jsonl")
        if rera.exists():
            call_command("import_rera", str(rera))
        ensure_default_queries()
        call_command("recompute")
        self.stdout.write(self.style.SUCCESS("Bootstrap complete"))
