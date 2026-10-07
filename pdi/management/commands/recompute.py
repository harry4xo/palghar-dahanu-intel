from django.core.management.base import BaseCommand

from pdi.services.status import recompute_all


class Command(BaseCommand):
    help = "Recompute every project's derived status, verification level and headline investment."

    def handle(self, **opts):
        self.stdout.write(self.style.SUCCESS(f"Recomputed {recompute_all()} projects"))
