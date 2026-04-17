/**
 * hiwin.js
 * 上銀科技 (2049) vs 大銀微系統 (4576) 漲幅監控
 * 資料來源：data/hiwin.json（由 GitHub Actions 每日更新）
 * 對應頁面：index.html 的 #page-hiwin 分頁
 */

const HIWIN_DATA_URL = './data/hiwin.json';

// ── 工具函式 ──────────────────────────────────────────────
function fmtPct(v) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function pctColor(v) {
  if (v > 0) return '#6ee7b7';   // 漲：綠
  if (v < 0) return '#fca5a5';   // 跌：紅
  return '#a5b4fc';               // 平：紫
}

// ── 渲染函式 ──────────────────────────────────────────────
function renderHiwin(data) {
  const { generated_at, hiwin, dayin } = data;

  // 更新時間
  const el = id => document.getElementById(id);
  el('hiwin-update').textContent = '資料時間：' + (generated_at || '—');

  // 股價列
  el('hiwin-price').textContent  = hiwin.price  ? 'NT$' + Number(hiwin.price).toLocaleString()  : '—';
  el('dayin-price').textContent  = dayin.price  ? 'NT$' + Number(dayin.price).toLocaleString()  : '—';
  el('hiwin-prev').textContent   = fmtPct(hiwin.pct_1d);
  el('dayin-prev').textContent   = fmtPct(dayin.pct_1d);
  el('hiwin-prev').style.color   = pctColor(hiwin.pct_1d);
  el('dayin-prev').style.color   = pctColor(dayin.pct_1d);

  // 訊號計算（以「當日漲幅」為主要訊號）
  const periods = [
    { key: '1d', label: '今日',  hw: hiwin.pct_1d, dy: dayin.pct_1d },
    { key: '1w', label: '一週',  hw: hiwin.pct_1w, dy: dayin.pct_1w },
    { key: '1m', label: '一個月', hw: hiwin.pct_1m, dy: dayin.pct_1m },
  ];

  // 訊號 banner（以今日為準）
  const diff1d = (dayin.pct_1d || 0) - (hiwin.pct_1d || 0);
  const banner = el('hiwin-signal');
  if (Math.abs(diff1d) < 0.1) {
    banner.textContent = '— 觀望　差距 < 0.1%，訊號不明確';
    banner.style.background = '#1f2937';
    banner.style.color = '#a5b4fc';
  } else if (diff1d > 0) {
    banner.textContent = `▲ 買進訊號　大銀微 ${fmtPct(dayin.pct_1d)} 領漲，上銀 ${fmtPct(hiwin.pct_1d)} 尚未跟上（差距 ${fmtPct(diff1d)}）`;
    banner.style.background = '#064e3b';
    banner.style.color = '#6ee7b7';
  } else {
    banner.textContent = `▼ 賣出訊號　上銀 ${fmtPct(hiwin.pct_1d)} 已超漲（大銀微 ${fmtPct(dayin.pct_1d)}，差距 ${fmtPct(-diff1d)}）`;
    banner.style.background = '#450a0a';
    banner.style.color = '#fca5a5';
  }

  // 各期漲幅比較表
  let tableHtml = `
    <table style="width:100%;border-collapse:collapse;font-size:13px;color:#eef2ff;">
      <thead>
        <tr style="color:#a5b4fc;font-size:11px;text-transform:uppercase;border-bottom:1px solid #1f2937;">
          <th style="padding:6px 4px;text-align:left;">週期</th>
          <th style="padding:6px 4px;text-align:right;">上銀 2049</th>
          <th style="padding:6px 4px;text-align:right;">大銀微 4576</th>
          <th style="padding:6px 4px;text-align:right;">差距</th>
          <th style="padding:6px 4px;text-align:center;">訊號</th>
        </tr>
      </thead>
      <tbody>`;

  for (const p of periods) {
    const diff = (p.dy || 0) - (p.hw || 0);
    const sig = Math.abs(diff) < 0.1 ? '—'
              : diff > 0 ? '▲ 買進'
              : '▼ 賣出';
    const sigColor = Math.abs(diff) < 0.1 ? '#a5b4fc'
                   : diff > 0 ? '#6ee7b7' : '#fca5a5';
    tableHtml += `
        <tr style="border-bottom:1px solid #1f2937;">
          <td style="padding:8px 4px;">${p.label}</td>
          <td style="padding:8px 4px;text-align:right;color:${pctColor(p.hw)}">${fmtPct(p.hw)}</td>
          <td style="padding:8px 4px;text-align:right;color:${pctColor(p.dy)}">${fmtPct(p.dy)}</td>
          <td style="padding:8px 4px;text-align:right;color:${pctColor(diff)}">${fmtPct(diff)}</td>
          <td style="padding:8px 4px;text-align:center;font-weight:700;color:${sigColor}">${sig}</td>
        </tr>`;
  }
  tableHtml += '</tbody></table>';
  el('hiwin-compare-table').innerHTML = tableHtml;

  // 折線圖
  renderHiwinChart(data);
}

function renderHiwinChart(data) {
  const { hiwin, dayin } = data;
  const canvas = document.getElementById('hiwinChart');
  if (!canvas) return;

  // 若已有舊圖表則銷毀
  if (window._hiwinChart) {
    window._hiwinChart.destroy();
  }

  const hwPcts = (hiwin.history_pcts || []).map(v => v === null ? null : +v.toFixed(2));
  const dyPcts = (dayin.history_pcts || []).map(v => v === null ? null : +v.toFixed(2));
  const labels = (hiwin.history_dates || []).map((d, i, arr) => {
    if (i === 0) return d.slice(5);        // 第一筆顯示日期
    if (i === arr.length - 1) return '今';
    if (i % 5 === 0) return d.slice(5);
    return '';
  });

  window._hiwinChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '上銀 2049',
          data: hwPcts,
          borderColor: '#60a5fa',
          backgroundColor: 'rgba(96,165,250,0.08)',
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2,
          fill: true,
          spanGaps: true,
        },
        {
          label: '大銀微 4576',
          data: dyPcts,
          borderColor: '#34d399',
          backgroundColor: 'rgba(52,211,153,0.08)',
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2,
          fill: true,
          spanGaps: true,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#a5b4fc', boxWidth: 12, font: { size: 12 } }
        },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}：${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y?.toFixed(2)}%`
          }
        }
      },
      scales: {
        x: {
          ticks: { color: '#6b7280', font: { size: 11 }, maxRotation: 0 },
          grid: { color: 'rgba(255,255,255,0.04)' }
        },
        y: {
          ticks: {
            color: '#6b7280',
            font: { size: 11 },
            callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%'
          },
          grid: { color: 'rgba(255,255,255,0.06)' }
        }
      }
    }
  });
}

// ── 主入口 ────────────────────────────────────────────────
async function initHiwin() {
  const errEl = document.getElementById('hiwin-error');
  const loadEl = document.getElementById('hiwin-loading');
  const contentEl = document.getElementById('hiwin-content');

  try {
    const res = await fetch(HIWIN_DATA_URL + '?t=' + Date.now());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    loadEl.style.display = 'none';
    contentEl.style.display = 'block';
    renderHiwin(data);
  } catch (e) {
    loadEl.style.display = 'none';
    errEl.style.display = 'block';
    errEl.textContent = '⚠️ 無法載入上銀資料（' + e.message + '）。請確認 data/hiwin.json 是否已由 GitHub Actions 產生。';
  }
}

// 等 DOM 就緒後執行
document.addEventListener('DOMContentLoaded', () => {
  // 若分頁預設隱藏，等切換時再初始化
  const tab = document.getElementById('page-hiwin');
  if (tab && tab.dataset.loaded !== 'true') {
    tab.dataset.loaded = 'true';
    initHiwin();
  }
});
