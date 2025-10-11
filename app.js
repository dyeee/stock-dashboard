async function loadData() {
  const res = await fetch('./data/latest.json', { cache: 'no-store' });
  const data = await res.json();

  // 安全防呆
  const dates = Array.isArray(data.trading_dates) ? data.trading_dates : [];
  const hasDay1 = dates.length >= 1;
  const hasDay2 = dates.length >= 2;

  const d1Label = hasDay1 ? dates[0] : 'N/A'; // 最近一天
  const d2Label = hasDay2 ? dates[1] : null;  // 前一交易日
  const stocks = Array.isArray(data.stocks) ? data.stocks : [];

  // UI meta
  const metaEl = document.getElementById('meta');
  const statsEl = document.getElementById('stats');
  const tableEl = document.getElementById('table'); // 請在 HTML 放一個 <div id="table"></div>
  if (metaEl) metaEl.textContent =
    `模式：兩日交集 ｜ 交易日：${dates.join(', ')} ｜ 產生(UTC)：${data.generated_at_utc || ''}`;
  if (statsEl) statsEl.textContent = `交集檔數：${data.count_intersection ?? stocks.length}`;

  if (stocks.length === 0) {
    // 沒有交集就清圖、清表
    if (window.myChart) { window.myChart.destroy(); window.myChart = null; }
    if (tableEl) tableEl.innerHTML = `<div class="muted">目前沒有連續兩天都進前十名的個股。</div>`;
    return;
  }

  // 依最近一天的排名排序（若無排名就退而求其次比總買超）
  const sorted = [...stocks].sort((a, b) => {
    const ar = a?.per_day?.day1?.rank ?? 9999;
    const br = b?.per_day?.day1?.rank ?? 9999;
    if (ar !== br) return ar - br;
    return (b.total_net_buy ?? 0) - (a.total_net_buy ?? 0);
  });

  // 準備 Chart 資料
  const labels = sorted.map(s => `${s.stock_name}(${s.stock_id})`);
  const d1Vals = sorted.map(s => s?.per_day?.day1?.net_buy_lots ?? 0);
  const d2Vals = hasDay2 ? sorted.map(s => s?.per_day?.day2?.net_buy_lots ?? 0) : null;

  // 長條圖
  const ctx = document.getElementById('chart');
  const datasets = [
    { label: `${d1Label} 淨買超(張)`, data: d1Vals }
  ];
  if (hasDay2) {
    datasets.push({ label: `${d2Label} 淨買超(張)`, data: d2Vals });
  }

  if (window.myChart) window.myChart.destroy();
  window.myChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#e5e7eb' } } },
      scales: {
        x: { ticks: { color: '#c7d2fe' } },
        y: { ticks: { color: '#c7d2fe' } }
      }
    }
  });

  // 產出表格（代號/名稱/兩日排名與買超/變化/合計）
  if (tableEl) {
    const rows = sorted.map((s, idx) => {
      const d1 = s?.per_day?.day1 || {};
      const d2 = s?.per_day?.day2 || {};
      const rank1 = d1.rank ?? '-';
      const rank2 = hasDay2 ? (d2.rank ?? '-') : '-';
      const buy1 = d1.net_buy_lots ?? 0;
      const buy2 = hasDay2 ? (d2.net_buy_lots ?? 0) : 0;
      const total = s.total_net_buy ?? (buy1 + buy2);

      // 排名變化：第2天 → 第1天（數字越小名次越前）
      let rankDelta = '→';
      if (hasDay2 && typeof rank1 === 'number' && typeof rank2 === 'number') {
        if (rank1 < rank2) rankDelta = `↑${rank2 - rank1}`;
        else if (rank1 > rank2) rankDelta = `↓${rank1 - rank2}`;
      }

      // 買超變化：day2 → day1
      const diff = hasDay2 ? (buy1 - buy2) : 0;
      const buyDelta = hasDay2
        ? (diff === 0 ? '持平' : (diff > 0 ? `+${diff.toLocaleString()}` : `${diff.toLocaleString()}`))
        : '—';

      return `
        <tr>
          <td>${idx + 1}</td>
          <td><code>${s.stock_id}</code></td>
          <td>${s.stock_name}</td>
          <td>${d2Label ?? '-'}</td>
          <td class="num">${hasDay2 ? rank2 : '-'}</td>
          <td class="num">${hasDay2 ? buy2.toLocaleString() : '-'}</td>
          <td>${d1Label}</td>
          <td class="num">${rank1}</td>
          <td class="num">${buy1.toLocaleString()}</td>
          <td class="num">${total.toLocaleString()}</td>
          <td>${rankDelta}</td>
          <td class="num">${buyDelta}</td>
        </tr>
      `;
    }).join('');

    // 簡單樣式（可移到 CSS）
    tableEl.innerHTML = `
      <style>
        #table table { width: 100%; border-collapse: collapse; font-size: 14px; }
        #table th, #table td { padding: 8px 10px; border-bottom: 1px solid #1f2937; }
        #table th { text-align: left; color: #a5b4fc; font-weight: 600; }
        #table .num { text-align: right; font-variant-numeric: tabular-nums; }
        #table code { background: #0f172a; padding: 2px 6px; border-radius: 6px; }
      </style>
      <div class="card">
        <div class="row" style="margin-bottom:8px;"><div>連續兩日交集明細</div></div>
        <div style="overflow:auto;">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>代號</th>
                <th>名稱</th>
                <th>第2天日期</th>
                <th>第2天名次</th>
                <th>第2天買超(張)</th>
                <th>第1天日期</th>
                <th>第1天名次</th>
                <th>第1天買超(張)</th>
                <th>合計買超(張)</th>
                <th>排名變化</th>
                <th>買超變化</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;
  }
}

loadData();
