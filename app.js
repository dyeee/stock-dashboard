async function loadData() {
  const url = `./data/latest.json?v=${Date.now()}`;
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

  // ── 基本欄位 ──
  const dates = Array.isArray(data.trading_dates) ? data.trading_dates : [];
  const hasDay2 = Boolean(data?.stocks?.[0]?.per_day?.day2);

  // ── Meta ──
  const metaEl = document.getElementById('meta');
  if (metaEl) {
    const utcStr = data.generated_at_utc;
    let localStr = '';
    if (utcStr) {
      const utcDate = new Date(utcStr + 'Z');
      localStr = utcDate.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' });
    }
    metaEl.textContent =
      `模式：兩日交集 ｜ 交易日：${dates.join(', ')} ｜ 產生(UTC+8)：${localStr}`;
  }

  const statsEl = document.getElementById('stats');
  if (statsEl)
    statsEl.textContent = `交集檔數：${data.count_intersection ?? (data.stocks?.length || 0)}`;

  const stocks = Array.isArray(data.stocks) ? data.stocks : [];

  if (!stocks.length) {
    if (window.myChart) { window.myChart.destroy(); window.myChart = null; }
    const tableEl = document.getElementById('table');
    if (tableEl) tableEl.innerHTML = `<div class="muted">目前沒有連續兩天都進前十名的個股。</div>`;
    renderAIAnalysis(data);
    return;
  }

  // ── 排序 ──
  const sorted = [...stocks].sort((a, b) => {
    const ar = a?.per_day?.day1?.rank ?? 9999;
    const br = b?.per_day?.day1?.rank ?? 9999;
    if (ar !== br) return ar - br;
    return (b.total_net_buy ?? 0) - (a.total_net_buy ?? 0);
  });

  // ── 圖表 ──
  const d1Label = dates[0] || '第1天';
  const d2Label = dates[1] || '第2天';
  const labels = sorted.map(s => `${s.stock_name.trim()}(${s.stock_id})`);
  const d1Vals = sorted.map(s => s?.per_day?.day1?.net_buy_lots ?? 0);
  const d2Vals = sorted.map(s => s?.per_day?.day2?.net_buy_lots ?? 0);
  const datasets = [{ label: `${d1Label} 淨買超(張)`, data: d1Vals }];
  if (hasDay2) datasets.push({ label: `${d2Label} 淨買超(張)`, data: d2Vals });

  const ctx = document.getElementById('chart');
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

  // ── 明細表 ──
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
        </tr>`;
    }).join('');

    tableEl.innerHTML = `
      <style>
        #table table { width:100%; border-collapse:collapse; font-size:14px; }
        #table th, #table td { padding:8px 10px; border-bottom:1px solid #1f2937; }
        #table th { text-align:left; color:#a5b4fc; font-weight:600; }
        #table .num { text-align:right; font-variant-numeric:tabular-nums; }
        #table code { background:#0f172a; padding:2px 6px; border-radius:6px; }
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
      </div>`;
  }

  // ── AI 交叉確認卡片 ──
  renderAIAnalysis(data);
  // 快取資料給三大法人頁籤用
  _instiData = data;
}

// ════════════════════════════════════════════════════════
// AI 交叉確認卡片渲染
// ════════════════════════════════════════════════════════

function renderAIAnalysis(data) {
  const analyses = data.ai_analysis || [];
  const time = data.ai_analysis_time || '';

  // 找或建立卡片
  let card = document.getElementById('ai-analysis-card');
  if (!card) {
    card = document.createElement('div');
    card.id = 'ai-analysis-card';
    card.className = 'card';
    document.querySelector('.wrap').appendChild(card);
  }

  if (!analyses.length) {
    card.innerHTML = `
      <div style="color:#a5b4fc;font-size:14px;font-weight:700;margin-bottom:8px">
        🤖 AI 交叉確認
      </div>
      <div style="color:#6b7280;font-size:13px">
        今日無外資交集個股，或 GROQ_API_KEY 尚未設定。
      </div>`;
    return;
  }

  const verdictColor = v =>
    v === '建議買進' ? '#34d399' : v === '不建議' ? '#f87171' : '#fbbf24';
  const verdictIcon  = v =>
    v === '建議買進' ? '✅' : v === '不建議' ? '❌' : '⚠️';
  const confColor    = c =>
    c === '高' ? '#34d399' : c === '低' ? '#f87171' : '#fbbf24';
  const qualityColor = q =>
    q === '充足' ? '#34d399' : q === '不足' ? '#f87171' : '#fbbf24';

  const rows = analyses.map(a => {
    const reasons = (a.reasons || []).map(r =>
      `<li style="margin-bottom:3px">${r}</li>`).join('');
    const warning = a.warning
      ? `<div style="margin-top:6px;font-size:12px;color:#f87171">⚠ ${a.warning}</div>` : '';
    const nextCheck = a.next_check
      ? `<div style="font-size:11px;color:#6b7280;margin-top:4px">📅 ${a.next_check}</div>` : '';
    const srcBadge = `<span style="font-size:10px;background:#1f2937;padding:1px 6px;
      border-radius:4px;color:#6b7280;margin-left:6px">${
      a.is_etf ? '📦 ETF' : '🌐 即時搜尋'}</span>`;
    const qualityBadge = `<span style="font-size:10px;color:${qualityColor(a.data_quality)};
      margin-left:8px">資料：${a.data_quality}</span>`;

    return `
      <div style="padding:14px 0;border-bottom:1px solid #1f2937">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <span style="font-size:16px">${verdictIcon(a.verdict)}</span>
          <span style="font-weight:700;color:#e5e7eb;font-size:15px">
            ${a.ticker} ${a.name}</span>
          ${srcBadge}
          <span style="font-size:12px;color:#a5b4fc;margin-left:4px">
            外資買超 ${(a.net_buy_lots||0).toLocaleString()} 張</span>
        </div>
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px;flex-wrap:wrap">
          <span style="font-weight:700;font-size:15px;color:${verdictColor(a.verdict)}">
            ${a.verdict}</span>
          <span style="font-size:12px;color:${confColor(a.confidence)}">
            信心度：${a.confidence}</span>
          ${qualityBadge}
        </div>
        <ul style="padding-left:18px;margin:0;font-size:13px;
          color:#9ca3af;line-height:1.8">${reasons}</ul>
        ${warning}
        ${nextCheck}
      </div>`;
  }).join('');

  card.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <div style="font-size:15px;font-weight:700;color:#eef2ff">🤖 AI 交叉確認</div>
      <div style="font-size:11px;color:#6b7280">${time}</div>
    </div>
    <div style="font-size:12px;color:#6b7280;margin-bottom:14px">
      用月營收 + 新聞交叉確認外資買超訊號是否可信
      （本地資料庫優先，其他股票自動抓取 MOPS + Google News）
    </div>
    ${rows}
    <div style="font-size:11px;color:#4b5563;margin-top:12px;
      padding-top:10px;border-top:1px solid #1f2937">
      ⚠️ 此分析僅供參考，不構成投資建議。投資前請自行評估風險。
    </div>`;
}


// ════════════════════════════════════════════════════════
// 三大法人頁籤渲染
// ════════════════════════════════════════════════════════

let _instiData = null;  // 快取，避免重複渲染

function renderInsti() {
  if (!_instiData) return;  // 資料還沒載入
  const data = _instiData;
  const stocks = data.three_insti || [];
  const date = data.three_insti_date || '';

  const dateEl = document.getElementById('insti-date');
  if (dateEl) dateEl.textContent = date ? `資料日期：${date}` : '—';

  if (!stocks.length) {
    document.getElementById('insti-count').textContent = '0';
    document.getElementById('insti-total').textContent = '0';
    document.getElementById('insti-max').textContent = '0';
    const tbl = document.getElementById('insti-table');
    if (tbl) tbl.innerHTML = '<div class="muted" style="padding:12px">今日無三大法人同時買超個股</div>';
    return;
  }

  // 統計
  const total = stocks.reduce((s, r) => s + r.total_net, 0);
  const max   = Math.max(...stocks.map(r => r.total_net));
  document.getElementById('insti-count').textContent = stocks.length;
  document.getElementById('insti-total').textContent = total.toLocaleString();
  document.getElementById('insti-max').textContent   = max.toLocaleString();

  // 長條圖
  const ctx = document.getElementById('insti-chart');
  if (ctx) {
    if (window.instiChart) window.instiChart.destroy();
    window.instiChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: stocks.map(s => `${s.stock_name}(${s.stock_id})`),
        datasets: [
          { label: '外資(張)',  data: stocks.map(s => s.foreign_net), backgroundColor: 'rgba(99,102,241,.75)' },
          { label: '投信(張)',  data: stocks.map(s => s.trust_net),   backgroundColor: 'rgba(52,211,153,.75)' },
          { label: '自營商(張)',data: stocks.map(s => s.dealer_net),  backgroundColor: 'rgba(251,191,36,.75)'  },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#e5e7eb' } } },
        scales: {
          x: { stacked: true, ticks: { color: '#c7d2fe', font: { size: 11 } } },
          y: { stacked: true, ticks: { color: '#c7d2fe' } }
        }
      }
    });
  }

  // 明細表
  const tbl = document.getElementById('insti-table');
  if (tbl) {
    const rows = stocks.map((s, i) => {
      const fColor = s.foreign_net > 0 ? '#6ee7b7' : '#f87171';
      const tColor = s.trust_net   > 0 ? '#6ee7b7' : '#f87171';
      const dColor = s.dealer_net  > 0 ? '#6ee7b7' : '#f87171';
      return `<tr>
        <td>${i + 1}</td>
        <td><code>${s.stock_id}</code></td>
        <td>${s.stock_name}</td>
        <td class="num" style="color:${fColor}">${s.foreign_net.toLocaleString()}</td>
        <td class="num" style="color:${tColor}">${s.trust_net.toLocaleString()}</td>
        <td class="num" style="color:${dColor}">${s.dealer_net.toLocaleString()}</td>
        <td class="num" style="color:#fbbf24;font-weight:600">${s.total_net.toLocaleString()}</td>
      </tr>`;
    }).join('');

    tbl.innerHTML = `
      <style>
        #insti-table table { width:100%; border-collapse:collapse; font-size:13px; }
        #insti-table th, #insti-table td { padding:8px 10px; border-bottom:1px solid #1f2937; }
        #insti-table th { text-align:left; color:#a5b4fc; font-weight:600; }
        #insti-table .num { text-align:right; font-variant-numeric:tabular-nums; }
        #insti-table code { background:#0f172a; padding:2px 5px; border-radius:4px; }
      </style>
      <div style="overflow:auto">
        <table>
          <thead><tr>
            <th>#</th><th>代號</th><th>名稱</th>
            <th>外資(張)</th><th>投信(張)</th><th>自營商(張)</th>
            <th>合計(張)</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }
}


loadData();
