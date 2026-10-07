import glob

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pdi.services.loaders import SeedError, load_seed


class Command(BaseCommand):
    help = "Load researched seed files (data/seed/*.json). All facts arrive as PENDING review."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="*")

    def handle(self, paths, **opts):
        paths = paths or sorted(glob.glob(str(settings.DATA_DIR / "seed" / "*.json")))
        if not paths:
            raise CommandError("No seed files found")
        unresolved = []
        # Two passes so relationships across files resolve regardless of order (loading is idempotent).
        for pass_no in (1, 2):
            unresolved = []
            for path in paths:
                try:
                    stats = load_seed(path)
                except SeedError as exc:
                    raise CommandError(f"{path}: {exc}")
                unresolved += stats.pop("unresolved_relationships", [])
                if pass_no == 2:
                    self.stdout.write(f"{path}: {stats}")
        for item in unresolved:
            self.stdout.write(self.style.WARNING(f"Relationship target not found: {item}"))
        self.stdout.write(self.style.SUCCESS("Seed load complete"))
