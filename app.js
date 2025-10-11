async function loadData() {
  const url = `./data/latest.json?v=${Date.now()}`; // 避免快取
  let data;

  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    console.error('載入 latest.json 失敗：', err);
    const metaEl = document.getElementById('meta');
    const statsEl = document.getElementById('stats');
    if (metaEl) metaEl.textContent = '載入資料失敗';
    if (statsEl) statsEl.textContent = String(err);
    return;
  }

  // 基本欄位
  const dates = Array.isArray(data.trading_dates) ? data.trading_dates : [];
  const hasDay1 = Boolean(data?.stocks?.[0]?.per_day?.day1);
  const hasDay2 = Boolean(data?.stocks?.[0]?.per_day?.day2);

  // Meta 顯示
  const metaEl = document.getElementById('meta');
  const statsEl = document.getElementById('stats');
  if (metaEl) {
  const utcStr = data.generated_at_utc;
  let localStr = '';
  if (utcStr) {
    const utcDate = new Date(utcStr + 'Z'); // 加 Z 告訴 JS 是 UTC
    localStr = utcDate.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' });
  }
  metaEl.textContent =
    `模式：兩日交集 ｜ 交易日：${dates.join(', ')} ｜ 產生(UTC+8)：${localStr}`;}

  if (statsEl) statsEl.textContent = `交集檔數：${data.count_intersection ?? (data.stocks?.length || 0)}`;

  const stocks = Array.isArray(data.stocks) ? data.stocks : [];

  // 沒有交集就清畫面
  if (!stocks.length) {
    if (window.myChart) { window.myChart.destroy(); window.myChart = null; }
    const tableEl = document.getElementById('table');
    if (tableEl) tableEl.innerHTML = `<div class="muted">目前沒有連續兩天都進前十名的個股。</div>`;
    return;
  }

  // 依最近一天(day1)排名排序，沒有排名就退而求其次比總買超
  const sorted = [...stocks].sort((a, b) => {
    const ar = a?.per_day?.day1?.rank ?? 9999;
    const br = b?.per_day?.day1?.rank ?? 9999;
    if (ar !== br) return ar - br;
    return (b.total_net_buy ?? 0) - (a.total_net_buy ?? 0);
  });

  // 準備圖表資料（注意 per_day 的 key 是 day1/day2，欄位是 net_buy_lots）
  const d1Label = dates[0] || '第1天';
  const d2Label = dates[1] || '第2天';
  const labels = sorted.map(s => `${s.stock_name.trim()}(${s.stock_id})`);
  const d1Vals = sorted.map(s => s?.per_day?.day1?.net_buy_lots ?? 0);
  const d2Vals = sorted.map(s => s?.per_day?.day2?.net_buy_lots ?? 0);

  // 繪圖
  const ctx = document.getElementById('chart');
  const datasets = [{ label: `${d1Label} 淨買超(張)`, data: d1Vals }];
  if (hasDay2) datasets.push({ label: `${d2Label} 淨買超(張)`, data: d2Vals });

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

  // 表格
  const tableEl = document.getElementById('table');
  if (tableEl) {
    const rows = sorted.map((s, idx) => {
      const d1 = s?.per_day?.day1 || {};
      const d2 = s?.per_day?.day2 || {};
      const rank1 = d1.rank ?? '-';
      const rank2 = hasDay2 ? (d2.rank ?? '-') : '-';
      const buy1  = d1.net_buy_lots ?? 0;
      const buy2  = hasDay2 ? (d2.net_buy_lots ?? 0) : 0;
      const total = s.total_net_buy ?? (buy1 + buy2);

      let rankDelta = '→';
      if (hasDay2 && Number.isFinite(rank1) && Number.isFinite(rank2)) {
        if (rank1 < rank2) rankDelta = `↑${rank2 - rank1}`;
        else if (rank1 > rank2) rankDelta = `↓${rank1 - rank2}`;
      }
      const diff = hasDay2 ? (buy1 - buy2) : 0;
      const buyDelta = hasDay2
        ? (diff === 0 ? '持平' : (diff > 0 ? `+${diff.toLocaleString()}` : `${diff.toLocaleString()}`))
        : '—';

      return `
        <tr>
          <td>${idx + 1}</td>
          <td><code>${s.stock_id}</code></td>
          <td>${s.stock_name.trim()}</td>
          <td>${hasDay2 ? d2.date : '-'}</td>
          <td class="num">${hasDay2 ? rank2 : '-'}</td>
          <td class="num">${hasDay2 ? buy2.toLocaleString() : '-'}</td>
          <td>${d1.date || d1Label}</td>
          <td class="num">${rank1}</td>
          <td class="num">${buy1.toLocaleString()}</td>
          <td class="num">${total.toLocaleString()}</td>
          <td>${rankDelta}</td>
          <td class="num">${buyDelta}</td>
        </tr>
      `;
    }).join('');

    tableEl.innerHTML = `
      <style>
        #table table { width: 100%; border-collapse: collapse; font-size: 14px; }
        #table th, #table td { padding: 8px 10px; border-bottom: 1px solid #1f2937; }
        #table th { text-align: left; color: #a5b4fc; font-weight: 600; }
        #table .num { text-align: right; font-variant-numeric: tabular-nums; }
        #table code { background: #0f172a; padding: 2px 6px; border-radius: 6px; }
      </style>
      <div style="overflow:auto;">
        <table>
          <thead>
            <tr>
              <th>#</th><th>代號</th><th>名稱</th>
              <th>第2天日期</th><th>第2天名次</th><th>第2天買超(張)</th>
              <th>第1天日期</th><th>第1天名次</th><th>第1天買超(張)</th>
              <th>合計買超(張)</th><th>排名變化</th><th>買超變化</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }
}

loadData();
