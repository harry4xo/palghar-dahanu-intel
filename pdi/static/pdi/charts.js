(function () {
  const css = getComputedStyle(document.documentElement);
  const color = (key) => css.getPropertyValue("--c-" + String(key).toLowerCase()).trim() || "#888";
  const text = css.getPropertyValue("--muted").trim();
  const grid = css.getPropertyValue("--border").trim();
  Chart.defaults.color = text;
  Chart.defaults.borderColor = grid;
  Chart.defaults.font.family = "system-ui, sans-serif";

  const tl = JSON.parse(document.getElementById("timeline-data").textContent);
  const tlEl = document.getElementById("timelineChart");
  if (tlEl) {
    new Chart(tlEl, {
      type: "bar",
      data: {
        labels: tl.years,
        datasets: tl.series.map((s) => ({ label: s.label, data: s.data, backgroundColor: color(s.key), borderRadius: 2 })),
      },
      options: {
        maintainAspectRatio: false,
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } } },
      },
    });
  }

  const sector = JSON.parse(document.getElementById("sector-data").textContent);
  const sEl = document.getElementById("sectorChart");
  if (sEl) {
    new Chart(sEl, {
      type: "bar",
      data: {
        labels: sector.map((s) => s.label),
        datasets: [{ label: "Projects", data: sector.map((s) => s.n), backgroundColor: sector.map((s) => color(s.key)), borderRadius: 2 }],
      },
      options: {
        indexAxis: "y",
        maintainAspectRatio: false,
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { grid: { display: false } } },
        plugins: { legend: { display: false } },
      },
    });
  }
})();
