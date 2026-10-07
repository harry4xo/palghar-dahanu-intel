from django.core.management.base import BaseCommand

from pdi.services.monitor import ensure_default_queries, run_all


class Command(BaseCommand):
    help = "Check watch feeds for new Palghar/Dahanu documents and add keyword matches to the inbox."

    def handle(self, **opts):
        created = ensure_default_queries()
        if created:
            self.stdout.write(f"Added {created} default watch queries")
        for name, added in run_all().items():
            self.stdout.write(f"  {name}: {added} new")
        self.stdout.write(self.style.SUCCESS("Monitoring run complete"))
