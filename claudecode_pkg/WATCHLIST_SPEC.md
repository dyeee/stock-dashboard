# 追蹤名單功能規格
給 Claude Code 使用的完整說明

## 專案背景
stock-dashboard 是一個 GitHub Pages 靜態網站
每天 22:10 由 GitHub Actions 執行 fetch_analyze.py
結果寫入 data/latest.json 和 data/watchlist.json

## 追蹤名單功能說明

### 目的
外資連兩日買超進榜的股票，自動追蹤10天，
記錄進榜價與每日收盤價，計算漲跌幅。

### 相關檔案
- fetch_analyze.py     # 主程式（GitHub Actions 執行）
- data/watchlist.json  # 持久化追蹤清單（跨日保存）
- data/latest.json     # 每日輸出（包含 watchlist 欄位）
- app.js               # 前端（renderWatch 函式）

### watchlist.json 結構
```json
[
  {
    "stock_id": "2884",
    "stock_name": "玉山金",
    "entry_date": "2026-04-28",   // 首次進榜日
    "entry_price": 32.55,          // 進榜當日收盤價
    "prices": {
      "2026-04-28": 32.55,
      "2026-05-05": 31.4
    },
    "pct_changes": {
      "2026-04-28": 0.0,
      "2026-05-05": -3.53          // 相對進榜價的漲跌幅
    }
  }
]
```

### 核心邏輯（fetch_analyze.py）

#### 唯一鍵：stock_id + entry_date
同一股票不同進榜日都保留（例如聯電 4/23 和 5/5 各一筆）

#### update_watchlist(result_df) 函式流程：
1. 載入 data/watchlist.json
2. 把今日進榜股票加入（若 stock_id + entry_date 已存在就跳過）
3. 用 get_close_price(ticker) 抓今日收盤價
4. 計算 pct = (today_price - entry_price) / entry_price * 100
5. 過濾 NaN（重要！避免 JSON 寫入 NaN 導致前端崩潰）
6. 清除進榜超過 10 天的紀錄
7. 存回 data/watchlist.json
8. 回傳 watchlist list

#### get_close_price(ticker) 優先順序：
1. yfinance（主要，.TW 後綴）
2. TWSE STOCK_DAY API（fallback）
3. TPEx API（上櫃股票 fallback）
ETF 代號（00開頭5位）用 .TW 不用 .TWO

#### 寫入 latest.json 時：
payload["watchlist"] = watchlist（從 update_watchlist 回傳）

#### 週末/假日處理：
result_data is None 時（無交易日），仍需：
- 讀取 watchlist.json
- 更新收盤價
- 寫回 watchlist.json
- 更新 latest.json 的 watchlist 欄位

### 前端顯示（app.js renderWatch）

#### 警示區
超過閾值（滑桿 3-10%）的股票放大顯示
漲超過 → 🚀 紅色
跌超過 → 📉 綠色（台股習慣）

#### 追蹤明細表（六欄）
代號 | 名稱 | 進榜日 | 進榜價 | 今日價 | 最新漲跌

漲跌顏色：漲=紅色(#f87171) 跌=綠色(#6ee7b7) 台股習慣

#### 資料來源
_instiData = data/latest.json 的內容
data.watchlist = 追蹤清單陣列

### 已知問題與修正
1. yfinance 對 5位數ETF（00878）用 .TW 不要用 .TWO
2. 收盤價可能是 NaN → 寫入前必須 math.isnan() 過濾
3. 週末不執行 → else branch 也要更新追蹤清單

### 手動新增追蹤
直接編輯 data/watchlist.json，格式同上
prices 和 pct_changes 只填進榜當日即可
下次 Actions 跑時會自動補齊後續收盤價

### 目前追蹤的股票範例（2026-05-05）
2887 台新新光金 進榜 4/28 @ 23.8
2884 玉山金     進榜 4/28 @ 32.55
2303 聯電       進榜 4/23 @ 73.6（已超10天會被清）
2303 聯電       進榜 5/5  @ 84.0
3481 群創       進榜 5/5  @ 26.3
2883 凱基金     進榜 5/5  @ 21.75
