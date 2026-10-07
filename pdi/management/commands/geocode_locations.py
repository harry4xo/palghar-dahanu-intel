import json
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from pdi.models import Location, Project

# Rough bounding box of Palghar district; results outside it are rejected.
BBOX = (19.25, 72.55, 20.30, 73.60)  # lat_min, lon_min, lat_max, lon_max
PLACE_TYPES = ["city", "town", "suburb", "village", "hamlet", "locality", "neighbourhood"]


class Command(BaseCommand):
    help = "Fill missing Location coordinates from OpenStreetMap Nominatim (1 request/second)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Re-geocode places that already have coordinates")
        parser.add_argument("--write-json", action="store_true", help="Also write coordinates back to data/locations.json")

    def handle(self, force=False, write_json=False, **opts):
        session = requests.Session()
        session.headers["User-Agent"] = settings.CRAWLER_CONTACT
        qs = Location.objects.all() if force else Location.objects.filter(latitude__isnull=True)
        done = 0
        for loc in qs:
            latin = [n for n in loc.all_names() if n.isascii()]
            queries = []
            for name in latin:
                queries += [f"{name}, Palghar district, Maharashtra, India", f"{name}, Maharashtra, India"]
            for q in queries:
                resp = session.get("https://nominatim.openstreetmap.org/search",
                                   params={"q": q, "format": "json", "limit": 8, "countrycodes": "in"}, timeout=30)
                time.sleep(1.1)
                # Only settlements: administrative boundaries (e.g. a district polygon) give misleading centroids.
                hits = [h for h in resp.json()
                        if h.get("class") == "place" and h.get("type") in PLACE_TYPES
                        and BBOX[0] <= float(h["lat"]) <= BBOX[2] and BBOX[1] <= float(h["lon"]) <= BBOX[3]]
                hits.sort(key=lambda h: PLACE_TYPES.index(h["type"]))
                if hits:
                    loc.latitude, loc.longitude = round(float(hits[0]["lat"]), 5), round(float(hits[0]["lon"]), 5)
                    loc.coord_source = "OpenStreetMap Nominatim (place centroid)"
                    loc.save()
                    done += 1
                    self.stdout.write(f"  {loc}: {loc.latitude}, {loc.longitude}")
                    break
            else:
                self.stdout.write(self.style.WARNING(f"  {loc}: no result inside Palghar district"))

        # Projects placed only by village/taluka inherit the centroid.
        for p in Project.objects.filter(location__isnull=False).exclude(coord_precision="EXACT"):
            if p.location.latitude is not None:
                p.latitude, p.longitude = p.location.latitude, p.location.longitude
                p.coord_precision = p.coord_precision or "VILLAGE"
                p.save(update_fields=["latitude", "longitude", "coord_precision"])

        if write_json:
            path = settings.DATA_DIR / "locations.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            coords = {(l.taluka, l.name): l for l in Location.objects.all()}
            for row in data["locations"]:
                loc = coords.get((row["taluka"], row["name"]))
                if loc and loc.latitude is not None:
                    row["latitude"], row["longitude"], row["coord_source"] = loc.latitude, loc.longitude, loc.coord_source
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Geocoded {done} places"))
