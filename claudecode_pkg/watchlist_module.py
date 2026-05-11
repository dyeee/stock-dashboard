#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watchlist_module.py — 追蹤名單模組
可獨立使用或整合進 fetch_analyze.py

使用方式（獨立執行）:
  python watchlist_module.py              # 更新所有追蹤股票收盤價
  python watchlist_module.py --add 2303 聯電 84.0 2026-05-05  # 手動加入
  python watchlist_module.py --remove 2303 2026-04-23          # 手動移除
  python watchlist_module.py --list                             # 列出清單
"""
import os, json, math, time, argparse
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

TPE_TZ   = timezone(timedelta(hours=8))
NOW_TPE  = datetime.now(TPE_TZ)
TRACK_DAYS = 10

import requests
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

# ════════════════════════════════════════════════════════
# 進榜股票追蹤（10天漲跌幅監控）
# ════════════════════════════════════════════════════════

OUT_WATCHLIST = Path("data/watchlist.json")
TRACK_DAYS = 10  # 追蹤天數


def get_close_price(ticker: str) -> float | None:
    """抓當日收盤價，優先用 yfinance，fallback 用 TWSE"""
    # ── 方法一：yfinance（GH Actions 環境最穩）──
    try:
        import yfinance as yf
        suffix = ".TWO" if ticker.startswith("00") and len(ticker) == 5 else ".TW"
        t = yf.Ticker(ticker + suffix)
        hist = t.history(period="5d")
        if not hist.empty:
            raw = float(hist["Close"].iloc[-1])
            if not math.isnan(raw) and raw > 0:
                price = round(raw, 2)
                print(f"    [yfinance] {ticker}: {price}")
                return price
    except Exception as e:
        print(f"    [yfinance] {ticker} 失敗：{e}")

    # ── 方法二：TWSE STOCK_DAY（當月資料）──
    try:
        yyyymm = NOW_TPE.strftime("%Y%m") + "01"
        r = SESSION.get(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
            params={"stockNo": ticker, "date": yyyymm, "response": "json"},
            timeout=10,
            headers={"Referer": "https://www.twse.com.tw/"}
        )
        d = r.json()
        rows = d.get("data", [])
        if rows:
            price_str = rows[-1][6].replace(",", "")
            price = float(price_str)
            if not math.isnan(price) and price > 0:
                print(f"    [TWSE] {ticker}: {price}")
                return price
    except Exception as e:
        print(f"    [TWSE] {ticker} 失敗：{e}")

    # ── 方法三：TPEx（上櫃股票）──
    try:
        roc_date = f"{NOW_TPE.year - 1911}/{NOW_TPE.strftime('%m/%d')}"
        r = SESSION.get(
            "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php",
            params={"l": "zh-tw", "d": roc_date, "se": "AL", "s": "0,asc",
                    "o": "json", "q": ticker},
            timeout=10
        )
        d = r.json()
        rows = d.get("aaData", [])
        if rows:
            price = float(rows[0][2].replace(",", ""))
            print(f"    [TPEx] {ticker}: {price}")
            return price
    except Exception as e:
        print(f"    [TPEx] {ticker} 失敗：{e}")

    print(f"    ⚠️ {ticker} 所有方法均失敗")
    return None


def load_watchlist() -> list:
    """載入追蹤清單"""
    if OUT_WATCHLIST.exists():
        try:
            return json.loads(OUT_WATCHLIST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_watchlist(items: list):
    OUT_WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    OUT_WATCHLIST.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_watchlist(result_df) -> list:
    """
    1. 載入現有追蹤清單
    2. 加入今日進榜的新股票（若已在清單就跳過）
    3. 更新每筆的當日收盤價和漲跌幅
    4. 清除超過 TRACK_DAYS 天的紀錄
    5. 存檔並回傳
    """
    today_str = NOW_TPE.strftime("%Y-%m-%d")
    watchlist = load_watchlist()

    # 今日進榜的股票
    new_stocks = []
    if result_df is not None and len(result_df) > 0:
        for _, row in result_df.iterrows():
            new_stocks.append({
                "stock_id":   str(row["stock_id"]),
                "stock_name": str(row["stock_name"]).strip(),
            })

    # 加入新進榜股票（用 stock_id + entry_date 作唯一鍵，同股票不同進榜日都保留）
    existing_keys = {(w["stock_id"], w["entry_date"]) for w in watchlist}
    for s in new_stocks:
        key = (s["stock_id"], today_str)
        if key not in existing_keys:
            print(f"  📌 新增追蹤：{s['stock_id']} {s['stock_name']} ({today_str})")
            watchlist.append({
                "stock_id":     s["stock_id"],
                "stock_name":   s["stock_name"],
                "entry_date":   today_str,
                "entry_price":  None,
                "prices":       {},
                "pct_changes":  {},
            })

    # 更新收盤價
    print(f"\n  📈 更新追蹤清單收盤價（共 {len(watchlist)} 檔）...")
    for item in watchlist:
        ticker = item["stock_id"]
        if today_str in item.get("prices", {}):
            continue  # 今天已更新過
        price = get_close_price(ticker)
        if price:
            item.setdefault("prices", {})[today_str] = price
            if item.get("entry_price") is None:
                item["entry_price"] = price
            # 計算漲跌幅
            entry = item["entry_price"]
            if entry and entry > 0:
                pct = round((price - entry) / entry * 100, 2)
                if not math.isnan(pct):
                    item.setdefault("pct_changes", {})[today_str] = pct
            pct_val = item.get("pct_changes", {}).get(today_str)
            if isinstance(pct_val, float):
                print(f"    {ticker} {item['stock_name']}: {price} 元 ({pct_val:+.2f}%)")
            else:
                print(f"    {ticker}: {price} 元")
        time.sleep(0.5)

    # 清除超過 TRACK_DAYS 天的紀錄
    from datetime import datetime as dt
    cutoff = NOW_TPE.date() - timedelta(days=TRACK_DAYS)
    kept = []
    for item in watchlist:
        entry = item.get("entry_date", "")
        try:
            if dt.strptime(entry, "%Y-%m-%d").date() >= cutoff:
                kept.append(item)
            else:
                print(f"  🗑️ 清除過期追蹤：{item['stock_id']} {item['stock_name']} (進榜 {entry})")
        except Exception:
            kept.append(item)
    watchlist = kept

    save_watchlist(watchlist)
    print(f"  ✅ 追蹤清單已更新，共 {len(watchlist)} 檔")
    return watchlist

# ── CLI 介面 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="追蹤名單管理工具")
    sub = parser.add_subparsers(dest="cmd")

    # 更新收盤價
    sub.add_parser("update", help="更新所有追蹤股票收盤價（預設）")

    # 手動加入
    p_add = sub.add_parser("add", help="手動加入追蹤")
    p_add.add_argument("stock_id",   help="股票代號 e.g. 2303")
    p_add.add_argument("stock_name", help="股票名稱 e.g. 聯電")
    p_add.add_argument("price",      type=float, help="進榜收盤價 e.g. 84.0")
    p_add.add_argument("entry_date", nargs="?",
                       default=NOW_TPE.strftime("%Y-%m-%d"),
                       help="進榜日期 YYYY-MM-DD（預設今天）")

    # 手動移除
    p_rm = sub.add_parser("remove", help="移除追蹤")
    p_rm.add_argument("stock_id",  help="股票代號")
    p_rm.add_argument("entry_date", nargs="?", default=None,
                      help="進榜日期（不填則移除所有同代號的）")

    # 列出
    sub.add_parser("list", help="列出目前追蹤清單")

    args = parser.parse_args()

    if args.cmd == "add":
        wl = load_watchlist()
        key = (args.stock_id, args.entry_date)
        existing = {(w["stock_id"], w["entry_date"]) for w in wl}
        if key in existing:
            print(f"⚠️  {args.stock_id} {args.entry_date} 已存在")
        else:
            wl.append({
                "stock_id":    args.stock_id,
                "stock_name":  args.stock_name,
                "entry_date":  args.entry_date,
                "entry_price": args.price,
                "prices":      {args.entry_date: args.price},
                "pct_changes": {args.entry_date: 0.0},
            })
            save_watchlist(wl)
            print(f"✅ 已加入：{args.stock_id} {args.stock_name} @ {args.price} ({args.entry_date})")

    elif args.cmd == "remove":
        wl = load_watchlist()
        before = len(wl)
        if args.entry_date:
            wl = [w for w in wl if not (w["stock_id"] == args.stock_id
                                         and w["entry_date"] == args.entry_date)]
        else:
            wl = [w for w in wl if w["stock_id"] != args.stock_id]
        save_watchlist(wl)
        print(f"✅ 移除 {before - len(wl)} 筆")

    elif args.cmd == "list":
        wl = load_watchlist()
        if not wl:
            print("（追蹤清單是空的）")
        for w in wl:
            pcts = w.get("pct_changes", {})
            dates = sorted(pcts.keys())
            latest = f"{pcts[dates[-1]]:+.2f}%" if dates else "—"
            print(f"  {w['stock_id']:6s} {w['stock_name']:10s} "
                  f"進榜 {w['entry_date']} @ {w['entry_price']}  最新漲跌 {latest}")

    else:
        # 預設：更新收盤價
        import pandas as pd
        result = update_watchlist(pd.DataFrame())
        print(f"\n✅ 更新完成，共 {len(result)} 筆")
