#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外資連續兩天都進前10名的個股分析
+ AI 交叉確認（自動抓取任意股票月營收 + 新聞）
"""
import os
import json
import re
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from groq import Groq

TPE_TZ = timezone(timedelta(hours=8))
NOW_TPE = datetime.now(TPE_TZ)
OUT_LATEST = Path("data/latest.json")
OUT_HISTORY_DIR = Path("data/history")
OUT_EXPORT_DIR = Path("exports")
OUT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
OUT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})


# ════════════════════════════════════════════════════════
# 工具函式
# ════════════════════════════════════════════════════════

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
    if x is None: return 0.0
    if isinstance(x, (int, float)): return float(x)
    s = str(x).strip().replace(',', '')
    if s in {'', '-'}: return 0.0
    try: return float(s)
    except: return 0.0


# ════════════════════════════════════════════════════════
# 外資資料
# ════════════════════════════════════════════════════════

def get_twse_foreign_data(date):
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {'date': date, 'selectType': 'ALL', 'response': 'json'}
    try:
        response = http_get(url, params=params)
        data = response.json()
        if 'data' not in data or len(data['data']) == 0:
            return None
        df = pd.DataFrame(data['data'], columns=data['fields'])
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
        print(f"⚠️ TWSE {date} 查詢失敗: {e}")
        return None

def get_tpex_foreign_data(date):
    year = int(date[:4]) - 1911
    date_tw = f"{year}/{date[4:6]}/{date[6:8]}"
    url = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    params = {'l': 'zh-tw', 'd': date_tw, 'se': 'AL', 'response': 'json'}
    try:
        response = http_get(url, params=params)
        data = response.json()
        if 'aaData' not in data or len(data['aaData']) == 0:
            return None
        df = pd.DataFrame(data['aaData'])
        df = df[[0, 1, 7, 8, 9]].copy()
        df.columns = ['stock_id', 'stock_name', 'buy_shares', 'sell_shares', 'net_shares']
        for col in ['buy_shares', 'sell_shares', 'net_shares']:
            df[col] = df[col].map(to_number)
        df['date'] = date
        df['market'] = 'TPEx'
        return df
    except Exception as e:
        print(f"⚠️ TPEx {date} 查詢失敗: {e}")
        return None

def get_daily_top10(date):
    all_data = []
    df_twse = get_twse_foreign_data(date)
    if df_twse is not None: all_data.append(df_twse)
    time.sleep(0.3)
    df_tpex = get_tpex_foreign_data(date)
    if df_tpex is not None: all_data.append(df_tpex)
    if not all_data: return None
    combined = pd.concat(all_data, ignore_index=True)
    daily_result = combined.groupby(['stock_id', 'stock_name'], as_index=False).agg(
        buy_shares=('buy_shares', 'sum'),
        sell_shares=('sell_shares', 'sum'),
        net_shares=('net_shares', 'sum')
    )
    daily_top10 = daily_result.sort_values(
        'net_shares', ascending=False).head(10).reset_index(drop=True)
    daily_top10['買入_張'] = (daily_top10['buy_shares'] / 1000).round(0).astype(int)
    daily_top10['賣出_張'] = (daily_top10['sell_shares'] / 1000).round(0).astype(int)
    daily_top10['淨買超_張'] = (daily_top10['net_shares'] / 1000).round(0).astype(int)
    return daily_top10

def find_recent_trading_dates(days=2, lookback=20):
    trading_dates = []
    check_date = NOW_TPE
    print("🔍 尋找最近的交易日...")
    for _ in range(lookback):
        date_str = check_date.strftime('%Y%m%d')
        df_twse = get_twse_foreign_data(date_str)
        if df_twse is not None and len(df_twse) > 0:
            trading_dates.append(date_str)
            print(f"   ✓ {date_str[:4]}-{date_str[4:6]}-{date_str[6:]}")
            if len(trading_dates) >= days:
                break
        check_date -= timedelta(days=1)
        time.sleep(0.2)
    return trading_dates

def get_consecutive_top10(days=2):
    print("=" * 70)
    print("🚀 外資連續買超前10名交集分析")
    print("=" * 70)
    print(f"📅 {NOW_TPE.strftime('%Y-%m-%d %H:%M')} (Asia/Taipei)\n")

    trading_dates = find_recent_trading_dates(days=days, lookback=30)
    if len(trading_dates) < days:
        print(f"❌ 只找到 {len(trading_dates)} 個交易日，需要 {days} 個")
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
            print(f"   ✓ 前10名: {', '.join(daily_top10['stock_name'].head(5).tolist())}...")
        else:
            print(f"   ✗ 無法取得資料")
            return None
        time.sleep(0.3)

    print(f"\n🔍 尋找連續 {days} 天都在前10名的個股...")
    common_stocks = set(daily_top10_list[0]['stock_id'])
    for i in range(1, days):
        common_stocks &= set(daily_top10_list[i]['stock_id'])
        print(f"   第 1-{i+1} 天交集: {len(common_stocks)} 檔")

    if not common_stocks:
        print(f"❌ 沒有個股連續 {days} 天都在前10名")
        return pd.DataFrame(), daily_top10_list

    print(f"\n✅ 找到 {len(common_stocks)} 檔\n")
    result_list = []
    for stock_id in common_stocks:
        stock_name = daily_top10_list[0].loc[
            daily_top10_list[0]['stock_id'] == stock_id, 'stock_name'].values[0]
        stock_info = {'stock_id': stock_id, 'stock_name': stock_name}
        total_net_buy = 0
        for i, daily_data in enumerate(daily_top10_list, 1):
            stock_row = daily_data[daily_data['stock_id'] == stock_id]
            if len(stock_row) > 0:
                rank = int((daily_data['淨買超_張'] >= stock_row.iloc[0]['淨買超_張']).sum())
                net_buy = int(stock_row.iloc[0]['淨買超_張'])
                stock_info[f'day{i}_rank'] = rank
                stock_info[f'day{i}_net_buy'] = net_buy
                stock_info[f'day{i}_date'] = daily_data.iloc[0]['rank_date']
                total_net_buy += net_buy
        stock_info['total_net_buy'] = int(total_net_buy)
        stock_info['avg_net_buy'] = float(total_net_buy / days)
        result_list.append(stock_info)

    result = pd.DataFrame(result_list).sort_values(
        'total_net_buy', ascending=False).reset_index(drop=True)
    return result, daily_top10_list


# ════════════════════════════════════════════════════════
# AI 交叉確認（全部走自動搜尋）
# ════════════════════════════════════════════════════════

# ETF 代號前綴（00 開頭通常是 ETF，MOPS 查不到月營收）
def is_etf(ticker: str) -> bool:
    return ticker.startswith("00") or ticker.startswith("0050") or ticker.startswith("006")

def fetch_mops_revenue(ticker: str) -> str:
    """從 MOPS 抓任意上市公司月營收"""
    if is_etf(ticker):
        return "ETF 無月營收資料（追蹤指數，不適用 MOPS）"
    now = datetime.now()
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    try:
        resp = requests.post(
            "https://mopsov.twse.com.tw/mops/web/t05st10_ifrs",
            data={"encodeURIComponent": 1, "step": 1, "firstin": 1,
                  "co_id": ticker, "year": year - 1911, "month": str(month)},
            timeout=12, headers={"User-Agent": "Mozilla/5.0"}
        )
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 100 or "查無資料" in text:
            return "MOPS 查無資料（上櫃公司或尚未公布）"

        results = [f"期間：{year}-{month:02d}"]
        nums = []
        for n in re.findall(r'[\d,]{5,}', text):
            try:
                val = int(n.replace(',', ''))
                if 1_000_000 < val < 10_000_000_000:
                    nums.append(val)
            except Exception:
                pass
        if nums:
            results.append(f"當月營收：{nums[0]:,} 千元（{nums[0]/1e6:.1f} 億）")
        pcts = re.findall(r'[-+]?\d+\.?\d*\s*%', text)
        if pcts:
            results.append(f"成長率：{pcts[0]}")
        elif len(nums) >= 3 and nums[2] > 0:
            yoy = (nums[0] - nums[2]) / nums[2] * 100
            results.append(f"YoY（估算）：{yoy:+.1f}%")
        kws = ["庫存調整", "客戶調整", "GB200", "AI伺服器", "液冷", "匯率", "NVL72"]
        found = [k for k in kws if k in text]
        if found:
            results.append(f"備註關鍵字：{'、'.join(found)}")
        results.append(f"原始節錄：{text[:400]}")
        return "\n".join(results)
    except Exception as e:
        return f"MOPS 連線失敗：{e}"


def search_news(ticker: str, name: str) -> str:
    """Google News RSS 搜尋近期新聞"""
    results = []
    for q in [f"{name} 財報", f"{ticker} {name} 營收"]:
        try:
            url = (f"https://news.google.com/rss/search?"
                   f"q={requests.utils.quote(q)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
            resp = requests.get(url, timeout=8,
                                headers={"User-Agent": "Mozilla/5.0"})
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', resp.text)
            for t in titles[1:5]:
                if any(k in t for k in [ticker, name, name[:2]]) and t not in results:
                    results.append(t)
        except Exception:
            pass
        time.sleep(0.5)
    return "\n".join(results[:5]) if results else "無近期相關新聞"


def call_groq(client, prompt: str, retries: int = 3) -> str:
    """呼叫 Groq，自動重試，確保回傳可解析的 JSON 字串"""
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model="qwen/qwen3-32b",
                messages=[
                    {"role": "system",
                     "content": "你是台灣股票分析師。只輸出純 JSON，繁體中文，不要有任何其他文字、說明、或 markdown。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            raw = resp.choices[0].message.content.strip()
            # 去掉 think 標籤、markdown 包裹
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw).strip()
            # 找 JSON 物件
            start, end = raw.find("{"), raw.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError(f"找不到 JSON，原始輸出：{raw[:100]}")
            return raw[start:end]
        except Exception as e:
            print(f"    ⚠️  第 {attempt+1} 次嘗試失敗：{e}")
            if attempt < retries - 1:
                time.sleep(5)
    return ""


def ai_analyze_one(ticker: str, name: str, net_buy: int) -> dict:
    """對單一股票自動搜尋財報 + 新聞，然後 AI 判斷"""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return {
            "ticker": ticker, "name": name,
            "verdict": "謹慎觀察", "confidence": "低",
            "reasons": ["未設定 GROQ_API_KEY"],
            "warning": None, "next_check": "設定 API Key",
            "data_quality": "不足",
        }

    from groq import Groq
    client = Groq(api_key=groq_key)

    etf = is_etf(ticker)
    if etf:
        print(f"    📊 ETF，跳過 MOPS，直接搜尋新聞...")
        earnings = "此為 ETF，追蹤指數，無月營收，以資金流向和折溢價判斷。"
    else:
        print(f"    🌐 抓取 MOPS 月營收...")
        earnings = fetch_mops_revenue(ticker)

    print(f"    📰 搜尋近期新聞...")
    news = search_news(ticker, name)
    time.sleep(1)

    if etf:
        context = f"""這是 ETF（{ticker} {name}），不適用一般財報分析。
外資連續兩天大量買超（合計 {net_buy:,} 張），代表機構法人在佈局。
請根據新聞判斷市場對此 ETF 追蹤標的的看法。"""
    else:
        context = f"一般股票，請根據月營收和新聞判斷基本面。"

    prompt = f"""外資連續兩天買超：{ticker} {name}（{'ETF' if etf else '股票'}）
合計買超：{net_buy:,} 張

{context}

【月營收 / 基本面】
{earnings[:500]}

【近期新聞】
{news}

只輸出純 JSON，不要有任何其他文字：
{{
  "ticker": "{ticker}",
  "name": "{name}",
  "verdict": "建議買進 或 謹慎觀察 或 不建議",
  "confidence": "高 或 中 或 低",
  "reasons": ["理由1（15字內）", "理由2（15字內）"],
  "warning": "最大風險（20字內），沒有填null",
  "next_check": "下次確認時間點（10字內）",
  "data_quality": "充足 或 有限 或 不足"
}}

判斷原則：
ETF → 外資大量買超通常是正面訊號，但需觀察追蹤標的走勢
股票 → 外資買超 + 財報成長 + 新聞正面 → 建議買進
資料不足時 confidence 設「低」，verdict 設「謹慎觀察」"""

    raw_json = call_groq(client, prompt)

    if not raw_json:
        return {
            "ticker": ticker, "name": name,
            "verdict": "謹慎觀察", "confidence": "低",
            "reasons": ["AI 回傳解析失敗，請手動查閱"],
            "warning": "Groq 回傳格式異常",
            "next_check": "手動確認",
            "data_quality": "不足",
            "net_buy_lots": net_buy,
        }

    try:
        result = json.loads(raw_json)
    except Exception as e:
        return {
            "ticker": ticker, "name": name,
            "verdict": "謹慎觀察", "confidence": "低",
            "reasons": ["JSON 解析失敗"],
            "warning": str(e)[:40],
            "next_check": "手動確認",
            "data_quality": "不足",
            "net_buy_lots": net_buy,
        }

    result["net_buy_lots"] = net_buy
    result["is_etf"] = etf
    return result


# ════════════════════════════════════════════════════════
# 輸出 JSON
# ════════════════════════════════════════════════════════

def write_json_payload(result_df, daily_top10_list, ai_analyses=None):
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
        "stocks": stocks,
        "ai_analysis": ai_analyses or [],
        "ai_analysis_time": NOW_TPE.strftime("%Y-%m-%d %H:%M") if ai_analyses else "",
    }

    OUT_LATEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_LATEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 寫入 {OUT_LATEST}")

    last_trade = trading_dates[0].replace('-', '')
    out_history = OUT_HISTORY_DIR / f"{last_trade}.json"
    out_history.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 寫入 {out_history}")


# ════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    days = int(os.getenv("DAYS", "2"))
    result_data = get_consecutive_top10(days=days)

    if result_data is not None:
        result, daily_top10_list = result_data

        print("=" * 70)
        print(f"🎉 連續 {days} 天都在外資買超前10名的個股 (交集)")
        print("=" * 70)

        if result is not None and len(result) > 0:
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
                           if int(row['第2天排名']) > int(row['第1天排名']) else "→"))
                ), axis=1
            )
            pd.set_option('display.unicode.east_asian_width', True)
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', 180)
            print("\n" + display.to_string())

            timestamp = NOW_TPE.strftime('%Y%m%d_%H%M')
            csv_path = OUT_EXPORT_DIR / f'外資連續前10名交集_{timestamp}.csv'
            result.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"\n💾 CSV: {csv_path}")
            print(f"✅ 連續進榜: {len(result)} 檔")
            print(f"📊 總買超: {int(display['合計買超(張)'].sum()):,} 張")

            common_ids = set(result['stock_id'])
            for i, daily_data in enumerate(daily_top10_list, 1):
                date = daily_data.iloc[0]['rank_date']
                print(f"\n【第 {i} 天】{date}")
                print("-" * 70)
                for rank, (_, row) in enumerate(daily_data.iterrows(), 1):
                    is_common = "⭐" if row['stock_id'] in common_ids else "  "
                    print(f"   {is_common} {rank:2d}. {row['stock_name']:8s} "
                          f"({row['stock_id']}) - 買超 {row['淨買超_張']:>8,} 張")
        else:
            print("❌ 沒有個股連續兩天都在前10名")

        # AI 交叉確認
        ai_analyses = run_ai_cross_check(
            result if result is not None else pd.DataFrame()
        )
        write_json_payload(
            result if result is not None else pd.DataFrame(),
            daily_top10_list,
            ai_analyses,
        )
    else:
        print("❌ 分析失敗")

    print("\n✨ 查詢完成!")
