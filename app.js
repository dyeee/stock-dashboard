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

  const dates  = Array.isArray(data.trading_dates) ? data.trading_dates : [];
  const hasDay2 = Boolean(data?.stocks?.[0]?.per_day?.day2);

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
    _instiData = data;
    return;
  }

  const sorted = [...stocks].sort((a, b) => {
    const ar = a?.per_day?.day1?.rank ?? 9999;
    const br = b?.per_day?.day1?.rank ?? 9999;
    if (ar !== br) return ar - br;
    return (b.total_net_buy ?? 0) - (a.total_net_buy ?? 0);
  });

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
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#e5e7eb' } } },
      scales: {
        x: { ticks: { color: '#c7d2fe' } },
        y: { ticks: { color: '#c7d2fe' } }
      }
    }
  });

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
          <td>${idx + 1}</td><td><code>${s.stock_id}</code></td>
          <td>${s.stock_name.trim()}</td>
          <td>${hasDay2 ? d2.date : '-'}</td>
          <td class="num">${hasDay2 ? rank2 : '-'}</td>
          <td class="num">${hasDay2 ? buy2.toLocaleString() : '-'}</td>
          <td>${d1.date || d1Label}</td>
          <td class="num">${rank1}</td>
          <td class="num">${buy1.toLocaleString()}</td>
          <td class="num">${total.toLocaleString()}</td>
          <td>${rankDelta}</td><td class="num">${buyDelta}</td>
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
          <thead><tr>
            <th>#</th><th>代號</th><th>名稱</th>
            <th>第2天日期</th><th>第2天名次</th><th>第2天買超(張)</th>
            <th>第1天日期</th><th>第1天名次</th><th>第1天買超(張)</th>
            <th>合計買超(張)</th><th>排名變化</th><th>買超變化</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  renderAIAnalysis(data);
  _instiData = data;
}

// ════════════════════════════════════════════════════════
// AI 交叉確認卡片
// ════════════════════════════════════════════════════════

function renderAIAnalysis(data) {
  const analyses = data.ai_analysis || [];
  const time = data.ai_analysis_time || '';

  let card = document.getElementById('ai-analysis-card');
  if (!card) {
    card = document.createElement('div');
    card.id = 'ai-analysis-card';
    card.className = 'card';
    document.querySelector('#page-main .wrap').appendChild(card);
  }

  if (!analyses.length) {
    card.innerHTML = `
      <div style="color:#a5b4fc;font-size:14px;font-weight:700;margin-bottom:8px">🤖 AI 交叉確認</div>
      <div style="color:#6b7280;font-size:13px">今日無外資交集個股，或 GROQ_API_KEY 尚未設定。</div>`;
    return;
  }

  const verdictColor = v => v==='建議買進'?'#34d399':v==='不建議'?'#f87171':'#fbbf24';
  const verdictIcon  = v => v==='建議買進'?'✅':v==='不建議'?'❌':'⚠️';
  const confColor    = c => c==='高'?'#34d399':c==='低'?'#f87171':'#fbbf24';
  const qualityColor = q => q==='充足'?'#34d399':q==='不足'?'#f87171':'#fbbf24';

  const rows = analyses.map(a => {
    const reasons = (a.reasons||[]).map(r=>`<li style="margin-bottom:3px">${r}</li>`).join('');
    const warning  = a.warning ? `<div style="margin-top:6px;font-size:12px;color:#f87171">⚠ ${a.warning}</div>`:'';
    const nextCheck= a.next_check ? `<div style="font-size:11px;color:#6b7280;margin-top:4px">📅 ${a.next_check}</div>`:'';
    const srcBadge = `<span style="font-size:10px;background:#1f2937;padding:1px 6px;border-radius:4px;color:#6b7280;margin-left:6px">${a.is_etf?'📦 ETF':'🌐 即時搜尋'}</span>`;
    const qualBadge= `<span style="font-size:10px;color:${qualityColor(a.data_quality)};margin-left:8px">資料：${a.data_quality}</span>`;
    return `
      <div style="padding:14px 0;border-bottom:1px solid #1f2937">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <span style="font-size:16px">${verdictIcon(a.verdict)}</span>
          <span style="font-weight:700;color:#e5e7eb;font-size:15px">${a.ticker} ${a.name}</span>
          ${srcBadge}
          <span style="font-size:12px;color:#a5b4fc;margin-left:4px">外資買超 ${(a.net_buy_lots||0).toLocaleString()} 張</span>
        </div>
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px;flex-wrap:wrap">
          <span style="font-weight:700;font-size:15px;color:${verdictColor(a.verdict)}">${a.verdict}</span>
          <span style="font-size:12px;color:${confColor(a.confidence)}">信心度：${a.confidence}</span>
          ${qualBadge}
        </div>
        <ul style="padding-left:18px;margin:0;font-size:13px;color:#9ca3af;line-height:1.8">${reasons}</ul>
        ${warning}${nextCheck}
      </div>`;
  }).join('');

  card.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <div style="font-size:15px;font-weight:700;color:#eef2ff">🤖 AI 交叉確認</div>
      <div style="font-size:11px;color:#6b7280">${time}</div>
    </div>
    <div style="font-size:12px;color:#6b7280;margin-bottom:14px">用月營收 + 新聞交叉確認外資買超訊號是否可信</div>
    ${rows}
    <div style="font-size:11px;color:#4b5563;margin-top:12px;padding-top:10px;border-top:1px solid #1f2937">
      ⚠️ 此分析僅供參考，不構成投資建議。
    </div>`;
}

// ════════════════════════════════════════════════════════
// 法人買賣超頁籤
// ════════════════════════════════════════════════════════

let _instiData = null;

function renderInsti() {
  if (!_instiData) return;
  const sig    = _instiData.insti_signal || {};
  const mkt    = _instiData.market_insti || {};
  const date   = _instiData.insti_signal_date || sig.date || '';
  const buy    = sig.buy  || [];
  const sell   = sig.sell || [];

  const dateEl = document.getElementById('insti-date');
  if (dateEl) dateEl.textContent = date ? `資料日期：${date}` : '—';

  // ── 大盤法人金額 ──
  const fNet = mkt.foreign_net_bn;
  const tNet = mkt.trust_net_bn;
  const fNetEl = document.getElementById('mkt-foreign-net');
  const tNetEl = document.getElementById('mkt-trust-net');
  const fBuyEl = document.getElementById('mkt-foreign-buy');
  const fSellEl= document.getElementById('mkt-foreign-sell');
  const tBuyEl = document.getElementById('mkt-trust-buy');
  const tSellEl= document.getElementById('mkt-trust-sell');

  const unit   = mkt.unit || '張';
  const isAmt  = unit === '億元';
  const fmtNet = n => {
    if (n === undefined || n === null) return '—';
    const sign = n >= 0 ? '+' : '';
    return isAmt
      ? sign + n.toLocaleString() + ' 億'
      : sign + Math.round(n).toLocaleString() + ' 張';
  };
  const fmtAbs = n => {
    if (n === undefined || n === null) return '—';
    return isAmt
      ? Math.abs(n).toLocaleString() + ' 億'
      : Math.abs(Math.round(n)).toLocaleString() + ' 張';
  };

  if (fNetEl && mkt.foreign_net !== undefined) {
    fNetEl.textContent = fmtNet(mkt.foreign_net);
    fNetEl.style.color = mkt.foreign_net >= 0 ? '#f87171' : '#6ee7b7';
  }
  if (tNetEl && mkt.trust_net !== undefined) {
    tNetEl.textContent = fmtNet(mkt.trust_net);
    tNetEl.style.color = mkt.trust_net   >= 0 ? '#f87171' : '#6ee7b7';
  }
  if (fBuyEl)  fBuyEl.textContent  = fmtAbs(mkt.foreign_buy);
  if (fSellEl) fSellEl.textContent = fmtAbs(mkt.foreign_sell);
  if (tBuyEl)  tBuyEl.textContent  = fmtAbs(mkt.trust_buy);
  if (tSellEl) tSellEl.textContent = fmtAbs(mkt.trust_sell);

  // 更新標題說明單位
  const unitLabel = document.getElementById('mkt-unit-label');
  if (unitLabel) unitLabel.textContent = `（${unit}）`;

  // ── 買超表 ──
  renderInstiTable('insti-buy-table', buy, true);

  // ── 買超長條圖 ──
  renderInstiChart('insti-buy-chart', buy, true);

  // ── 賣超表 ──
  renderInstiTable('insti-sell-table', sell, false);

  // ── 賣超長條圖 ──
  renderInstiChart('insti-sell-chart', sell, false);
}

function renderInstiTable(elId, stocks, isBuy) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!stocks.length) {
    el.innerHTML = `<div class="muted" style="padding:12px">今日無資料</div>`;
    return;
  }
  const fCol = s => s.foreign_net > 0 ? '#f87171' : '#6ee7b7';
  const tCol = s => s.trust_net   > 0 ? '#f87171' : '#6ee7b7';
  const rows = stocks.map((s, i) => `
    <tr>
      <td>${i+1}</td>
      <td><code>${s.stock_id}</code></td>
      <td>${s.stock_name}</td>
      <td class="num" style="color:${fCol(s)}">${s.foreign_net.toLocaleString()}</td>
      <td class="num" style="color:${tCol(s)}">${s.trust_net.toLocaleString()}</td>
      <td class="num" style="color:${isBuy?'#f87171':'#6ee7b7'};font-weight:600">${s.ft_net.toLocaleString()}</td>
    </tr>`).join('');
  el.innerHTML = `
    <style>
      .it table { width:100%; border-collapse:collapse; font-size:13px; }
      .it th,.it td { padding:7px 10px; border-bottom:1px solid #1f2937; }
      .it th { text-align:left; color:#a5b4fc; font-weight:600; }
      .it .num { text-align:right; font-variant-numeric:tabular-nums; }
      .it code { background:#0f172a; padding:2px 5px; border-radius:4px; }
    </style>
    <div class="it" style="overflow:auto">
      <table>
        <thead><tr>
          <th>#</th><th>代號</th><th>名稱</th>
          <th>外資(張)</th><th>投信(張)</th><th>合計(張)</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderInstiChart(elId, stocks, isBuy) {
  const ctx = document.getElementById(elId);
  if (!ctx || !stocks.length) return;
  const key = elId + '_chart_obj';
  if (window[key]) window[key].destroy();
  window[key] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: stocks.map(s => `${s.stock_name}(${s.stock_id})`),
      datasets: [
        { label: '外資(張)', data: stocks.map(s => s.foreign_net),
          backgroundColor: isBuy ? 'rgba(220,38,38,.8)'   : 'rgba(34,197,94,.8)' },
        { label: '投信(張)', data: stocks.map(s => s.trust_net),
          backgroundColor: isBuy ? 'rgba(252,165,165,.7)'  : 'rgba(134,239,172,.7)'  },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#e5e7eb' } } },
      scales: {
        x: { stacked: true, ticks: { color: '#c7d2fe', font: { size: 10 } } },
        y: { stacked: true, ticks: { color: '#c7d2fe' } }
      }
    }
  });
}

loadData();

// ════════════════════════════════════════════════════════
// 追蹤清單頁籤
// ════════════════════════════════════════════════════════

function renderWatch() {
  const data = _instiData;
  if (!data) return;

  const watchlist = data.watchlist || [];
  const genAt = data.generated_at_utc || '';
  const upEl = document.getElementById('watch-update');
  if (upEl && genAt) {
    const d = new Date(genAt + 'Z');
    upEl.textContent = '更新：' + d.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' });
  }

  const threshold = parseFloat(document.getElementById('threshold-slider')?.value || 5);

  // ── 警示區 ──
  const alertEl = document.getElementById('watch-alerts');
  const alerts = [];
  watchlist.forEach(item => {
    const pcts = item.pct_changes || {};
    const dates = Object.keys(pcts).sort();
    if (!dates.length) return;
    const latest_date = dates[dates.length - 1];
    const pct = pcts[latest_date];
    if (typeof pct !== 'number') return;

    if (Math.abs(pct) >= threshold) {
      const isUp = pct > 0;
      alerts.push({ item, pct, latest_date, isUp });
    }
  });

  if (alertEl) {
    if (alerts.length) {
      alertEl.innerHTML = alerts.map(({ item, pct, latest_date, isUp }) => `
        <div class="card" style="border-left:4px solid ${isUp ? '#f87171' : '#34d399'};padding:14px 16px;">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <span style="font-size:20px">${isUp ? '🚀' : '📉'}</span>
            <span style="font-weight:700;font-size:15px;color:#e5e7eb;">
              ${item.stock_id} ${item.stock_name}</span>
            <span style="font-size:22px;font-weight:800;color:${isUp ? '#f87171' : '#34d399'};">
              ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span>
          </div>
          <div style="font-size:12px;color:#6b7280;margin-top:6px;">
            進榜日：${item.entry_date}　進榜價：${item.entry_price ?? '—'} 元　
            ${latest_date} 收盤：${item.prices?.[latest_date] ?? '—'} 元
          </div>
        </div>`).join('');
    } else {
      alertEl.innerHTML = `
        <div class="card" style="color:#6b7280;font-size:13px;text-align:center;padding:20px;">
          目前沒有股票漲跌幅超過 ${threshold}%
        </div>`;
    }
  }

  // ── 追蹤明細表 ──
  const tblEl = document.getElementById('watch-table');
  if (!tblEl) return;

  if (!watchlist.length) {
    tblEl.innerHTML = '<div class="muted" style="padding:12px">尚無追蹤資料，等待明日進榜股票</div>';
    return;
  }

  // 取所有出現的日期（最多10天）
  const allDates = [...new Set(
    watchlist.flatMap(w => Object.keys(w.pct_changes || {}))
  )].sort().slice(-10);

  const headerCols = allDates.map(d => `<th>${d.slice(5)}</th>`).join('');

  const rows = watchlist.map(item => {
    const pcts = item.pct_changes || {};
    const dateCols = allDates.map(d => {
      const pct = pcts[d];
      if (pct === undefined || pct === null) return '<td class="num" style="color:#374151">—</td>';
      const abs = Math.abs(pct);
      const color = abs >= threshold ? (pct > 0 ? '#f87171' : '#34d399') :
                    pct > 0 ? '#fca5a5' : pct < 0 ? '#6ee7b7' : '#6b7280';
      const bold = abs >= threshold ? 'font-weight:700;' : '';
      return `<td class="num" style="color:${color};${bold}">${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%</td>`;
    }).join('');

    // 最新漲跌幅
    const sortedDates = Object.keys(pcts).sort();
    const latestPct = sortedDates.length ? pcts[sortedDates[sortedDates.length - 1]] : null;
    const latestColor = latestPct === null ? '#6b7280' : latestPct > 0 ? '#f87171' : '#34d399';

    return `<tr>
      <td><code>${item.stock_id}</code></td>
      <td>${item.stock_name}</td>
      <td style="font-size:11px;color:#6b7280;">${item.entry_date}</td>
      <td class="num">${item.entry_price ?? '—'}</td>
      ${dateCols}
      <td class="num" style="color:${latestColor};font-weight:700;">
        ${latestPct !== null ? (latestPct >= 0 ? '+' : '') + latestPct.toFixed(2) + '%' : '—'}
      </td>
    </tr>`;
  }).join('');

  tblEl.innerHTML = `
    <style>
      #watch-table table { width:100%; border-collapse:collapse; font-size:12px; }
      #watch-table th, #watch-table td { padding:7px 8px; border-bottom:1px solid #1f2937; white-space:nowrap; }
      #watch-table th { color:#a5b4fc; font-weight:600; text-align:left; }
      #watch-table .num { text-align:right; }
      #watch-table code { background:#0f172a; padding:1px 4px; border-radius:4px; }
    </style>
    <div style="overflow:auto;">
      <table>
        <thead><tr>
          <th>代號</th><th>名稱</th><th>進榜日</th><th>進榜價</th>
          ${headerCols}
          <th>最新漲跌</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
