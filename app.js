async function loadData() {
  const res = await fetch('./data/latest.json', { cache: 'no-store' });
  const data = await res.json();

  const [d0, d1] = data.trading_dates; // d0: 最近一天
  const labels = data.stocks.map(s => `${s.stock_name}(${s.stock_id})`);
  const v0 = data.stocks.map(s => s.per_day[d0].net_lots);
  const v1 = data.stocks.map(s => s.per_day[d1].net_lots);

  if (window.myChart) window.myChart.destroy();
  window.myChart = new Chart(document.getElementById('chart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: `${d0} 淨買超(張)`, data: v0 },
        { label: `${d1} 淨買超(張)`, data: v1 }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false }
  });

  document.getElementById('meta').textContent =
    `模式：兩日交集 ｜ 交易日：${data.trading_dates.join(', ')} ｜ 產生(UTC)：${data.generated_at_utc}`;
  document.getElementById('stats').textContent =
    `交集檔數：${data.count_intersection}`;
}
loadData();
