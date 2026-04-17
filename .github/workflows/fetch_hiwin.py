#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_hiwin.py
每日抓取 上銀科技 (2049.TW) vs 大銀微系統 (4576.TW) 的漲幅資料
輸出至 data/hiwin.json，供前端 hiwin.js 讀取

用法：
  python fetch_hiwin.py

GitHub Actions 每日自動執行，結果 commit 回 repo。
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── 設定 ────────────────────────────────────────────────────
SYMBOLS = {
    "hiwin": "2049.TW",   # 上銀科技
    "dayin": "4576.TW",   # 大銀微系統
}

OUT_PATH = Path("data/hiwin.json")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

TPE_TZ = timezone(timedelta(hours=8))
NOW_TPE = datetime.now(TPE_TZ)

HISTORY_DAYS = 35   # 抓幾天歷史（用於折線圖）

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
})

# ── 抓資料 ───────────────────────────────────────────────────
def fetch_yahoo(symbol: str, range_: str = "35d", interval: str = "1d") -> dict:
    """從 Yahoo Finance Chart API 抓歷史資料"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": range_}
    for attempt in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            result = data["chart"]["result"][0]
            return result
        except Exception as e:
            print(f"  ⚠️  {symbol} 第 {attempt+1} 次失敗：{e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"無法取得 {symbol} 資料")

def calc_pct(closes: list, n_days: int) -> float | None:
    """計算最近 n_days 天的漲幅百分比"""
    valid = [c for c in closes if c is not None]
    if len(valid) < 2:
        return None
    if n_days == 0:
        # 今日漲幅需要 meta.chartPreviousClose
        return None
    base = valid[max(0, len(valid) - 1 - n_days)]
    last = valid[-1]
    if base == 0:
        return None
    return round((last - base) / base * 100, 4)

def build_stock_info(symbol: str, label: str) -> dict:
    """產生單一股票的分析資訊"""
    print(f"  📥 抓取 {label} ({symbol})...")
    result = fetch_yahoo(symbol)

    meta   = result["meta"]
    closes = result["indicators"]["quote"][0]["close"]
    timestamps = result.get("timestamp", [])

    price       = meta.get("regularMarketPrice")
    prev_close  = meta.get("chartPreviousClose") or meta.get("previousClose")

    # 今日漲幅（用 meta 的即時價 vs 前收）
    pct_1d = None
    if price and prev_close and prev_close != 0:
        pct_1d = round((price - prev_close) / prev_close * 100, 4)

    pct_1w = calc_pct(closes, 5)
    pct_1m = calc_pct(closes, 22)

    # 歷史百分比（以第一筆為基準，供折線圖用）
    valid_closes = [c for c in closes if c is not None]
    base_price = valid_closes[0] if valid_closes else None
    history_pcts = []
    history_dates = []

    for i, (ts, c) in enumerate(zip(timestamps, closes)):
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d")
        history_dates.append(date_str)
        if c is None or base_price is None or base_price == 0:
            history_pcts.append(None)
        else:
            history_pcts.append(round((c - base_price) / base_price * 100, 4))

    return {
        "symbol":        symbol,
        "label":         label,
        "price":         price,
        "prev_close":    prev_close,
        "pct_1d":        pct_1d,
        "pct_1w":        pct_1w,
        "pct_1m":        pct_1m,
        "history_pcts":  history_pcts,
        "history_dates": history_dates,
    }

# ── 主程式 ───────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("🔍 上銀 vs 大銀微 漲幅資料抓取")
    print(f"📅 執行時間：{NOW_TPE.strftime('%Y-%m-%d %H:%M')} (Asia/Taipei)")
    print("=" * 60)

    hiwin_info = build_stock_info(SYMBOLS["hiwin"], "上銀科技")
    time.sleep(0.5)
    dayin_info = build_stock_info(SYMBOLS["dayin"], "大銀微系統")

    # 訊號計算
    diff_1d = None
    if hiwin_info["pct_1d"] is not None and dayin_info["pct_1d"] is not None:
        diff_1d = round(dayin_info["pct_1d"] - hiwin_info["pct_1d"], 4)

    signal = "hold"
    if diff_1d is not None:
        if diff_1d > 0.1:
            signal = "buy"    # 大銀微領漲 → 上銀補漲機率高 → 買進
        elif diff_1d < -0.1:
            signal = "sell"   # 上銀已超漲 → 賣出

    payload = {
        "generated_at":     NOW_TPE.strftime("%Y-%m-%d %H:%M"),
        "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "signal":           signal,
        "diff_1d":          diff_1d,
        "hiwin":            hiwin_info,
        "dayin":            dayin_info,
    }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已寫入 {OUT_PATH}")
    print(f"   訊號：{signal}  |  今日差距：{diff_1d}")
    print(f"   上銀今日：{hiwin_info['pct_1d']}%  |  大銀微今日：{dayin_info['pct_1d']}%")

if __name__ == "__main__":
    main()
