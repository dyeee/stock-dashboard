#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 11 19:24:57 2025

@author: stellakao

外資連續兩天都進前10名的個股分析（交集版本，含 JSON/CSV 輸出，適用 GitHub Actions）
"""
import os
import json
import math
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

# --- 路徑與時間 ---
TPE_TZ = timezone(timedelta(hours=8))
NOW_TPE = datetime.now(TPE_TZ)
OUT_LATEST = Path("data/latest.json")
OUT_HISTORY_DIR = Path("data/history")
OUT_EXPORT_DIR = Path("exports")
OUT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
OUT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# --- HTTP Session（逾時/重試/UA）---
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

def http_get(url, params=None, retries=3, timeout=30):
    last_err = None
    for i in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            time.sleep(1.2 * (i + 1))
    raise last_err

def to_number(x):
    """將 '1,234' / '-' / None 安全轉為 float。"""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(',', '')
    if s in {'', '-'}:
        return 0.0
    try:
        return float(s)
    except:
        return 0.0

# ---------------------------------------------------------
# 抓資料：TWSE / TPEx
# ---------------------------------------------------------
def get_twse_foreign_data(date):
    """
    從證交所官網抓取外資買賣超資料 (完全免費!)
    參數:
        date: 日期字串,格式 'YYYYMMDD'
    """
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {'date': date, 'selectType': 'ALL', 'response': 'json'}
    try:
        response = http_get(url, params=params)
        data = response.json()
        if 'data' not in data or len(data['data']) == 0:
            return None
        df = pd.DataFrame(data['data'], columns=data['fields'])
        # 只保留外資資料
        df = df[['證券代號', '證券名稱',
                 '外陸資買進股數(不含外資自營商)',
                 '外陸資賣出股數(不含外資自營商)',
                 '外陸資買賣超股數(不含外資自營商)']].copy()
        df.columns = ['stock_id', 'stock_name', 'buy_shares', 'sell_shares', 'net_shares']
        for col in ['buy_shares', 'sell_shares', 'net_shares']:
            df[col] = df[col].map(to_number)
        df['date'] = date
        df['market'] = 'TWSE'
        return df
    except Exception as e:
        print(f"⚠️ 日期 {date} TWSE 查詢失敗: {e}")
        return None

def get_tpex_foreign_data(date):
    """
    從櫃買中心抓取外資買賣超資料 (上櫃股票)
    參數:
        date: 日期字串,格式 'YYYYMMDD'
    """
    # 轉換為民國年格式
    year = int(date[:4]) - 1911
    month = date[4:6]
    day = date[6:8]
    date_tw = f"{year}/{month}/{day}"

    url = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    params = {'l': 'zh-tw', 'd': date_tw, 'se': 'AL', 'response': 'json'}
    try:
        response = http_get(url, params=params)
        data = response.json()
        if 'aaData' not in data or len(data['aaData']) == 0:
            return None
        df = pd.DataFrame(data['aaData'])
        # 欄位：0代號,1名稱,7外資買,8外資賣,9外資買賣超
        df = df[[0, 1, 7, 8, 9]].copy()
        df.columns = ['stock_id', 'stock_name', 'buy_shares', 'sell_shares', 'net_shares']
        for col in ['buy_shares', 'sell_shares', 'net_shares']:
            df[col] = df[col].map(to_number)
        df['date'] = date
        df['market'] = 'TPEx'
        return df
    except Exception as e:
        print(f"⚠️ 櫃買日期 {date} 查詢失敗: {e}")
        return None

# ---------------------------------------------------------
# 單日 Top10 與最近交易日尋找
# ---------------------------------------------------------
def get_daily_top10(date):
    """
    取得單日外資買超前10名
    參數:
        date: 日期字串,格式 'YYYYMMDD'
    """
    all_data = []
    df_twse = get_twse_foreign_data(date)
    if df_twse is not None:
        all_data.append(df_twse)
    time.sleep(0.3)
    df_tpex = get_tpex_foreign_data(date)
    if df_tpex is not None:
        all_data.append(df_tpex)

    if not all_data:
        return None

    combined = pd.concat(all_data, ignore_index=True)
    daily_result = combined.groupby(['stock_id', 'stock_name'], as_index=False).agg(
        buy_shares=('buy_shares', 'sum'),
        sell_shares=('sell_shares', 'sum'),
        net_shares=('net_shares', 'sum')
    )

    daily_top10 = daily_result.sort_values('net_shares', ascending=False).head(10).reset_index(drop=True)
    # 股→張
    daily_top10['買入_張'] = (daily_top10['buy_shares'] / 1000).round(0).astype(int)
    daily_top10['賣出_張'] = (daily_top10['sell_shares'] / 1000).round(0).astype(int)
    daily_top10['淨買超_張'] = (daily_top10['net_shares'] / 1000).round(0).astype(int)
    return daily_top10

def find_recent_trading_dates(days=2, lookback=20):
    """往回找最近的可用交易日（以 TWSE 有資料為準）"""
    trading_dates = []
    check_date = NOW_TPE
    print("🔍 尋找最近的交易日...")
    for _ in range(lookback):
        date_str = check_date.strftime('%Y%m%d')
        df_twse = get_twse_foreign_data(date_str)
        if df_twse is not None and len(df_twse) > 0:
            trading_dates.append(date_str)
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            print(f"   ✓ 找到交易日: {formatted_date}")
            if len(trading_dates) >= days:
                break
        check_date -= timedelta(days=1)
        time.sleep(0.2)
    return trading_dates

# ---------------------------------------------------------
# 主分析：連續 N 天交集
# ---------------------------------------------------------
def get_consecutive_top10(days=2):
    """
    找出連續N天都在前10名的個股(交集)
    """
    print("=" * 70)
    print("🚀 外資連續買超前10名交集分析")
    print("=" * 70)
    print(f"📅 今天: {NOW_TPE.strftime('%Y-%m-%d %H:%M')} (Asia/Taipei)\n")

    trading_dates = find_recent_trading_dates(days=days, lookback=30)

    if len(trading_dates) < days:
        print(f"\n❌ 只找到 {len(trading_dates)} 個交易日,需要 {days} 個")
        return None

    print(f"\n📊 分析最近 {days} 個交易日...\n")
    daily_top10_list = []

    for i, date in enumerate(trading_dates[:days], 1):
        formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        print(f"⏳ 取得第 {i} 天前10名: {formatted_date}")
        daily_top10 = get_daily_top10(date)
        if daily_top10 is not None:
            daily_top10['rank_date'] = formatted_date
            daily_top10_list.append(daily_top10)
            # 顯示前五名名稱
            print(f"   ✓ 前10名: {', '.join(daily_top10['stock_name'].head(5).tolist())}...")
        else:
            print(f"   ✗ 無法取得資料")
            return None
        time.sleep(0.3)

    if len(daily_top10_list) < days:
        print(f"\n❌ 資料不完整")
        return None

    # 交集
    print(f"\n🔍 尋找連續 {days} 天都在前10名的個股...")
    common_stocks = set(daily_top10_list[0]['stock_id'])
    for i in range(1, days):
        day_stocks = set(daily_top10_list[i]['stock_id'])
        common_stocks &= day_stocks
        print(f"   第 1-{i+1} 天交集: {len(common_stocks)} 檔")

    if not common_stocks:
        print(f"\n❌ 沒有個股連續 {days} 天都在前10名")
        # 仍回傳空結果與每日榜單，方便前端顯示
        return pd.DataFrame(), daily_top10_list

    print(f"\n✅ 找到 {len(common_stocks)} 檔連續 {days} 天都在前10名的個股\n")

    result_list = []
    for stock_id in common_stocks:
        stock_name = daily_top10_list[0].loc[
            daily_top10_list[0]['stock_id'] == stock_id, 'stock_name'
        ].values[0]

        stock_info = {'stock_id': stock_id, 'stock_name': stock_name}
        total_net_buy = 0

        for i, daily_data in enumerate(daily_top10_list, 1):
            stock_row = daily_data[daily_data['stock_id'] == stock_id]
            if len(stock_row) > 0:
                # 名次（依當日淨買超張數排序）
                rank = int((daily_data['淨買超_張'] >= stock_row.iloc[0]['淨買超_張']).sum())
                net_buy = int(stock_row.iloc[0]['淨買超_張'])

                stock_info[f'day{i}_rank'] = rank
                stock_info[f'day{i}_net_buy'] = net_buy
                stock_info[f'day{i}_date'] = daily_data.iloc[0]['rank_date']
                total_net_buy += net_buy

        stock_info['total_net_buy'] = int(total_net_buy)
        stock_info['avg_net_buy'] = float(total_net_buy / days)
        result_list.append(stock_info)

    result = pd.DataFrame(result_list).sort_values('total_net_buy', ascending=False).reset_index(drop=True)
    return result, daily_top10_list

# ---------------------------------------------------------
# 輸出 JSON（給前端使用）
# ---------------------------------------------------------
def write_json_payload(result_df, daily_top10_list):
    # trading_dates（由近到遠）
    trading_dates = [d.iloc[0]['rank_date'] for d in daily_top10_list]

    stocks = []
    for _, r in result_df.iterrows():
        item = {
            "stock_id": r["stock_id"],
            "stock_name": r["stock_name"],
            "total_net_buy": int(r["total_net_buy"]),
            "avg_net_buy": float(r["avg_net_buy"]),
            "per_day": {}
        }
        # day1/day2...
        i = 1
        while f"day{i}_date" in r:
            item["per_day"][f"day{i}"] = {
                "date": r[f"day{i}_date"],
                "rank": int(r[f"day{i}_rank"]),
                "net_buy_lots": int(r[f"day{i}_net_buy"])
            }
            i += 1
        stocks.append(item)

    payload = {
        "mode": "intersection_top10_per_day",
        "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Taipei",
        "params": {"days": len(daily_top10_list), "top_n": 10},
        "trading_dates": trading_dates,
        "count_intersection": int(len(result_df)),
        "stocks": stocks
    }

    OUT_LATEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_LATEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 寫入 {OUT_LATEST}")

    # 以最近一個交易日命名歷史檔
    last_trade = trading_dates[0].replace('-', '')
    out_history = OUT_HISTORY_DIR / f"{last_trade}.json"
    out_history.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 寫入 {out_history}")

# ---------------------------------------------------------
# 主程式
# ---------------------------------------------------------
if __name__ == "__main__":
    # 連續天數可由環境變數控制（預設 2）
    days = int(os.getenv("DAYS", "2"))

    result_data = get_consecutive_top10(days=days)

    if result_data is not None:
        result, daily_top10_list = result_data

        print("=" * 70)
        print(f"🎉 連續 {days} 天都在外資買超前10名的個股 (交集)")
        print("=" * 70)

        if result is not None and len(result) > 0:
            # 整理終端機顯示
            display = pd.DataFrame()
            display['代號'] = result['stock_id']
            display['股票名稱'] = result['stock_name']
            display['第1天日期'] = result['day1_date']
            display['第1天排名'] = result['day1_rank'].astype(int)
            display['第1天買超(張)'] = result['day1_net_buy'].astype(int)
            display['第2天日期'] = result.get('day2_date', pd.NA)
            display['第2天排名'] = result.get('day2_rank', pd.NA)
            display['第2天買超(張)'] = result.get('day2_net_buy', pd.NA)
            display['合計買超(張)'] = result['total_net_buy'].astype(int)

            display['排名變化'] = display.apply(
                lambda row: (
                    "→" if pd.isna(row['第2天排名']) else
                    (f"↑{abs(int(row['第2天排名']) - int(row['第1天排名']))}"
                     if int(row['第2天排名']) < int(row['第1天排名'])
                     else (f"↓{int(row['第2天排名']) - int(row['第1天排名'])}"
                           if int(row['第2天排名']) > int(row['第1天排名'])
                           else "→"))
                ), axis=1
            )

            pd.set_option('display.unicode.east_asian_width', True)
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', 180)

            print("\n" + display.to_string())

            # CSV 匯出（檔名中文保持 UTF-8-sig，Windows 可開）
            timestamp = NOW_TPE.strftime('%Y%m%d_%H%M')
            csv_path = OUT_EXPORT_DIR / f'外資連續前10名交集_{timestamp}.csv'
            result.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"\n💾 結果已儲存: {csv_path}")

            # 統計資訊
            print("\n" + "=" * 70)
            print("📈 統計資訊")
            print("=" * 70)
            print(f"✅ 連續進榜: {len(result)} 檔")
            print(f"📊 總買超: {int(display['合計買超(張)'].sum()):,} 張")
            print(f"📊 平均買超: {display['合計買超(張)'].mean():,.0f} 張/檔")

            # 顯示每日完整前10名（供參考）
            print("\n" + "=" * 70)
            print("📋 各日完整前10名 (⭐為交集個股)")
            print("=" * 70)
            common_ids = set(result['stock_id'])
            for i, daily_data in enumerate(daily_top10_list, 1):
                date = daily_data.iloc[0]['rank_date']
                print(f"\n【第 {i} 天】{date}")
                print("-" * 70)
                for rank, (_, row) in enumerate(daily_data.iterrows(), 1):
                    is_common = "⭐" if row['stock_id'] in common_ids else "  "
                    print(f"   {is_common} {rank:2d}. {row['stock_name']:8s} ({row['stock_id']}) "
                          f"- 買超 {row['淨買超_張']:>8,} 張")

        else:
            print("\n❌ 沒有個股連續兩天都在前10名")

        # 無論是否有交集，都寫 JSON（方便前端顯示）
        write_json_payload(result if result is not None else pd.DataFrame(), daily_top10_list)

    else:
        print("\n❌ 分析失敗")
        # 失敗時：避免讓 GitHub Actions 因無輸出而中止，可視需求決定是否 exit 1
        # import sys; sys.exit(1)

    print("\n✨ 查詢完成!")
