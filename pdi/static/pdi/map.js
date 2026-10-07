(function () {
  const el = document.getElementById("map");
  const css = getComputedStyle(document.documentElement);
  const color = (key) => css.getPropertyValue("--c-" + String(key).toLowerCase()).trim() || "#888";
  const map = L.map(el).setView([19.85, 72.85], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const crore = (v) => (v == null ? "—" : "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 }) + " cr");

  fetch(el.dataset.src)
    .then((r) => r.json())
    .then((data) => {
      // Many projects share a village centroid: spread exact duplicates slightly so all stay clickable.
      const seen = {};
      const layer = L.geoJSON(data, {
        pointToLayer: (f, latlng) => {
          const k = latlng.lat.toFixed(4) + "," + latlng.lng.toFixed(4);
          const n = (seen[k] = (seen[k] || 0) + 1) - 1;
          if (n > 0) {
            const angle = n * 2.4, r = 0.012 * Math.sqrt(n);
            latlng = L.latLng(latlng.lat + r * Math.sin(angle), latlng.lng + r * Math.cos(angle));
          }
          const approx = f.properties.precision && !f.properties.precision.startsWith("Exact");
          return L.circleMarker(latlng, {
            radius: 7, weight: 2, color: color(f.properties.category),
            fillColor: color(f.properties.category), fillOpacity: approx ? 0.15 : 0.85,
          });
        },
        onEachFeature: (f, l) => {
          const p = f.properties;
          l.bindPopup(
            `<strong><a href="${esc(p.url)}">${esc(p.name)}</a></strong><br>` +
              `${esc(p.category_label)} · ${esc(p.micro_market || "")}<br>` +
              `Stage: ${esc(p.stage)}${p.provisional ? " (provisional)" : ""}<br>` +
              `Investment: ${crore(p.investment)}${p.basis ? " (" + esc(p.basis.toLowerCase()) + ")" : ""}<br>` +
              `<span style="opacity:.7">${esc(p.precision || "")}</span>`
          );
        },
      }).addTo(map);
      document.getElementById("map-count").textContent = `${data.features.length} project${data.features.length === 1 ? "" : "s"} with a location`;
      if (data.features.length) map.fitBounds(layer.getBounds().pad(0.15), { maxZoom: 12 });
    })
    .catch(() => { document.getElementById("map-count").textContent = "Could not load projects."; });
})();
