async function loadData() {
  const res = await fetch('./data/latest.json', { cache: 'no-store' });
  const data = await res.json();

  // Meta info
  const meta = document.getElementById('meta');
  meta.textContent = `來源：${data.source} ｜ 產生時間(UTC)：${data.generated_at}`;

  // Text stats
  const stats = document.getElementById('stats');
  stats.textContent = `總數量：${data.total}`;

  // Chart
  const ctx = document.getElementById('chart');
  const labels = data.top_categories.map(d => d.Category);
  const values = data.top_categories.map(d => d.count);

  if (window.myChart) window.myChart.destroy();
  window.myChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: 'Count', data: values }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { ticks: { color: '#c7d2fe' }}, y: { ticks: { color: '#c7d2fe' }} },
      plugins: { legend: { labels: { color: '#e5e7eb' }} }
    }
  });
}
loadData();
