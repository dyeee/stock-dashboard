"""
外資出場追蹤系統 v3
正確對應資料格式：
  stock_id, stock_name,
  day1_rank, day1_net_buy, day1_date,   ← 較新的一天（名單確認日）
  day2_rank, day2_net_buy, day2_date,   ← 前一天（首次進場日）
  total_net_buy, avg_net_buy

追蹤邏輯：
  進場日 = day2_date
  從 day1_date 之後，用 FinMind 抓往後 10 個交易日籌碼
"""

import os
import re
import glob
import time
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import datetime, timedelta
from FinMind.data import DataLoader

dl = DataLoader()
# 若有帳號：
# dl.login(user_id="你的帳號", password="你的密碼")

# ── 中文字型 ───────────────────────────────────────────
def set_chinese_font():
    candidates = ["PingFang TC", "Microsoft JhengHei", "Noto Sans CJK TC",
                  "Arial Unicode MS", "WenQuanYi Micro Hei"]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            matplotlib.rcParams["font.family"] = font
            break
    matplotlib.rcParams["axes.unicode_minus"] = False

set_chinese_font()

COLUMNS = [
    "stock_id", "stock_name",
    "day1_rank", "day1_net_buy", "day1_date",
    "day2_rank", "day2_net_buy", "day2_date",
    "total_net_buy", "avg_net_buy"
]


# ══════════════════════════════════════════════════════
# STEP 1：讀取所有 CSV，取得進場事件
# ══════════════════════════════════════════════════════
def load_entry_list(exports_dir: str) -> pd.DataFrame:
    pattern = os.path.join(exports_dir, "外資連續前10名交集_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"找不到 CSV：{exports_dir}")

    # 同一天多個時間戳 → 只取最新
    seen_dates = {}
    for f in files:
        m = re.search(r"(\d{8})_(\d{4})\.csv", f)
        if not m:
            continue
        date_str, time_str = m.group(1), m.group(2)
        if date_str not in seen_dates or time_str > seen_dates[date_str][1]:
            seen_dates[date_str] = (f, time_str)

    all_dfs = []
    for date_str, (fpath, _) in sorted(seen_dates.items()):
        try:
            df = pd.read_csv(
                fpath, header=None, names=COLUMNS,
                dtype={"stock_id": str}, encoding="utf-8-sig"
            )
            df["stock_id"]   = df["stock_id"].str.strip()
            df["stock_name"] = df["stock_name"].str.strip()
            # 移除表頭行（stock_id 欄位內容等於 "stock_id" 的列）
            df = df[df["stock_id"] != "stock_id"]
            df["file_date"]  = date_str  # 檔名日期備用
            all_dfs.append(df)
        except Exception as e:
            print(f"⚠️  {os.path.basename(fpath)} 讀取失敗：{e}")

    if not all_dfs:
        raise ValueError("所有 CSV 讀取失敗")

    combined = pd.concat(all_dfs, ignore_index=True)

    # 日期欄轉型
    combined["day1_date"] = pd.to_datetime(combined["day1_date"].str.strip(), errors="coerce")
    combined["day2_date"] = pd.to_datetime(combined["day2_date"].str.strip(), errors="coerce")

    # 數值欄轉型
    for col in ["day1_rank", "day1_net_buy", "day2_rank", "day2_net_buy",
                "total_net_buy", "avg_net_buy"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")

    # ── 進場事件定義 ──────────────────────────────────
    # 每個 (stock_id, day2_date) 組合 = 一個進場事件
    # 去除重複（同股同進場日只保留一筆）
    entries = (
        combined
        .drop_duplicates(subset=["stock_id", "day2_date"])
        .sort_values(["day2_date", "stock_id"])
        .reset_index(drop=True)
    )

    print(f"✅ 讀取完成：{len(seen_dates)} 個交易日快照")
    print(f"   進場事件：{len(entries)} 筆")
    print(f"   涵蓋股票：{entries['stock_id'].nunique()} 檔")
    print(f"   時間範圍：{entries['day2_date'].min().date()} "
          f"~ {entries['day1_date'].max().date()}\n")

    return entries


# ══════════════════════════════════════════════════════
# STEP 2：用 FinMind 抓個股往後 N 個交易日的外資買賣超
# ══════════════════════════════════════════════════════
_chip_cache = {}  # 全域快取，同股不重複抓

def fetch_chip_after(
    stock_id: str,
    start_date: pd.Timestamp,   # day1_date（名單確認日）
    days_forward: int = 10,
) -> pd.DataFrame:
    """
    從 start_date 的隔天開始，抓 days_forward 個交易日的外資買賣超
    回傳欄位：date, foreign_net, trading_day
    """
    fetch_start = (start_date + timedelta(days=1)).strftime("%Y-%m-%d")
    fetch_end   = (start_date + timedelta(days=days_forward * 2 + 10)).strftime("%Y-%m-%d")
    cache_key   = (stock_id, fetch_start)

    if cache_key in _chip_cache:
        raw = _chip_cache[cache_key]
    else:
        try:
            raw = dl.taiwan_stock_institutional_investors(
                stock_id=stock_id,
                start_date=fetch_start,
                end_date=fetch_end,
            )
            _chip_cache[cache_key] = raw
            time.sleep(0.35)
        except Exception as e:
            print(f"⚠️  FinMind [{stock_id}] 失敗：{e}")
            return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    # 只取外資
    foreign = raw[raw["name"] == "Foreign_Investor"].copy()
    if foreign.empty:
        return pd.DataFrame()

    foreign["date"]        = pd.to_datetime(foreign["date"])
    foreign["foreign_net"] = foreign["buy"] - foreign["sell"]
    foreign = foreign.sort_values("date").reset_index(drop=True)

    # 取前 days_forward 個交易日
    result = foreign[["date", "foreign_net"]].head(days_forward).copy()
    result["trading_day"] = range(1, len(result) + 1)
    return result


# ══════════════════════════════════════════════════════
# STEP 3：出場訊號偵測
# ══════════════════════════════════════════════════════
def detect_exit(nets: list) -> dict:
    """
    nets：進場後每日外資淨買超列表（股數，正=買超，負=賣超）

    回傳：
      exit_first_sell  第幾個交易日首次出現賣超（-1=未出現）
      exit_consec_2    第幾個交易日出現連續2天賣超（-1=未出現）
      exit_cumul_neg   第幾個交易日累積轉負（-1=未出現）
      still_buying_end 最後一天是否仍買超 (True/False)
      days_positive    買超天數
      days_negative    賣超天數
      avg_net          平均每日淨買超
      total_net        10天累積淨買超
    """
    n = len(nets)

    # A. 首次賣超
    exit_a = next((i + 1 for i, v in enumerate(nets) if v < 0), -1)

    # B. 連續 2 天賣超（回傳連續第1天的交易日編號）
    exit_b, streak = -1, 0
    for i, v in enumerate(nets):
        if v < 0:
            streak += 1
            if streak >= 2:
                exit_b = i  # i 是連續第2天的 0-based index → 連續第1天 = i
                break
        else:
            streak = 0

    # C. 累積轉負
    exit_c, cumsum = -1, 0
    for i, v in enumerate(nets):
        cumsum += v
        if cumsum < 0:
            exit_c = i + 1
            break

    return {
        "exit_first_sell":  exit_a,
        "exit_consec_2":    exit_b,
        "exit_cumul_neg":   exit_c,
        "still_buying_end": bool(nets[-1] > 0) if n > 0 else None,
        "days_positive":    int(sum(1 for v in nets if v > 0)),
        "days_negative":    int(sum(1 for v in nets if v < 0)),
        "avg_net":          float(np.mean(nets)),
        "total_net":        float(np.sum(nets)),
        "daily_nets":       ",".join(str(int(v)) for v in nets),
    }


# ══════════════════════════════════════════════════════
# STEP 4：主追蹤流程
# ══════════════════════════════════════════════════════
def run_tracking(entries: pd.DataFrame, days_forward: int = 10) -> pd.DataFrame:
    results = []
    total = len(entries)
    print(f"開始追蹤 {total} 個進場事件（往後 {days_forward} 個交易日）...\n")

    for i, row in entries.iterrows():
        sid        = row["stock_id"]
        name       = row["stock_name"]
        entry_date = row["day2_date"]   # 首次進場日
        confirm_date = row["day1_date"] # 名單確認日（從這天之後開始追蹤）
        entry_net  = row["day1_net_buy"]

        # 跳過日期無效的列（例如表頭殘留）
        if pd.isnull(entry_date) or pd.isnull(confirm_date):
            print(f"[{i+1:>3}/{total}] {sid} 日期無效，跳過")
            continue

        print(f"[{i+1:>3}/{total}] {sid} {name:<10} "
              f"進場:{entry_date.date()} 確認:{confirm_date.date()}", end="  ")

        chip_df = fetch_chip_after(sid, confirm_date, days_forward)

        if chip_df.empty or len(chip_df) < 2:
            print("→ 資料不足，跳過")
            continue

        nets = chip_df["foreign_net"].tolist()
        signals = detect_exit(nets)

        print(f"→ 買{signals['days_positive']}天/賣{signals['days_negative']}天  "
              f"累計:{signals['total_net']:+.0f}  "
              f"首賣:第{signals['exit_first_sell']}天")

        results.append({
            "entry_date":    entry_date.date(),
            "confirm_date":  confirm_date.date(),
            "stock_id":      sid,
            "stock_name":    name,
            "entry_net":     entry_net,
            "day1_rank":     row["day1_rank"],
            "day2_rank":     row["day2_rank"],
            **signals,
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv("exit_tracking_result.csv", index=False, encoding="utf-8-sig")
    print(f"\n✅ 結果儲存：exit_tracking_result.csv（{len(result_df)} 筆）")
    return result_df


# ══════════════════════════════════════════════════════
# STEP 5：統計 + 圖表
# ══════════════════════════════════════════════════════
def analyze_and_plot(df: pd.DataFrame, days_forward: int = 10):
    os.makedirs("output_charts", exist_ok=True)

    # ── 數值清洗：排除異常極值 ────────────────────────
    df = df[df["avg_net"].abs() < 1e9].copy()
    n = len(df)

    print("\n" + "=" * 60)
    print(f"📊 外資進場後 {days_forward} 交易日分析  （有效樣本：{n} 筆）")
    print("=" * 60)

    # ── 文字統計 ──────────────────────────────────────
    print(f"\n【整體行為】")
    print(f"  平均買超天數：{df['days_positive'].mean():.1f} 天")
    print(f"  平均賣超天數：{df['days_negative'].mean():.1f} 天")
    pct_still = df['still_buying_end'].mean() * 100
    print(f"  {days_forward}天後仍買超比例：{pct_still:.1f}%")

    print(f"\n【出場訊號】")
    for col, label in [
        ("exit_first_sell", "首次出現賣超"),
        ("exit_consec_2",   "連續2天賣超"),
        ("exit_cumul_neg",  "累積轉負"),
    ]:
        sub = df[df[col] > 0][col]
        pct = len(sub) / n * 100
        if len(sub):
            print(f"  {label}：{pct:.0f}% 在{days_forward}天內發生  "
                  f"平均第 {sub.mean():.1f} 天  中位數第 {sub.median():.1f} 天")
        else:
            print(f"  {label}：{days_forward}天內未發生")

    # ── 圖1：每天仍在買超的比例（核心圖）────────────
    daily_data = []
    for nets_str in df["daily_nets"]:
        try:
            vals = [float(v) for v in nets_str.split(",")]
            daily_data.append(vals)
        except:
            pass

    max_len = max(len(v) for v in daily_data)
    daily_arr = np.array([v + [np.nan] * (max_len - len(v)) for v in daily_data])
    still_buying_pct = np.nanmean(daily_arr > 0, axis=0) * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f"外資連續買超進場後 {days_forward} 日籌碼追蹤", fontsize=14, fontweight="bold")

    # 左：半衰期柱狀圖
    ax = axes[0]
    days_x = range(1, len(still_buying_pct) + 1)
    colors = ["#22C55E" if v >= 50 else "#F59E0B" if v >= 30 else "#EF4444"
              for v in still_buying_pct]
    ax.bar(days_x, still_buying_pct, color=colors, edgecolor="white")
    ax.axhline(50, color="#555", linestyle="--", lw=1.5, label="50% 基準")

    # 標出跌破 50% 的那天
    cross = next((i + 1 for i, v in enumerate(still_buying_pct) if v < 50), None)
    if cross:
        ax.axvline(cross, color="#DC2626", linestyle=":", lw=2,
                   label=f"第{cross}天跌破50%")

    ax.set_title("進場後第 N 天仍在買超的比例")
    ax.set_xlabel("進場後交易日")
    ax.set_ylabel("仍在買超比例 (%)")
    ax.set_xticks(days_x)
    ax.set_ylim(0, 105)
    ax.legend()
    ax.grid(axis="y", alpha=0.25)

    # 右：平均每日淨買超趨勢
    ax2 = axes[1]
    avg_daily = np.nanmean(daily_arr, axis=0) / 1000  # 千股
    bar_colors = ["#22C55E" if v > 0 else "#EF4444" for v in avg_daily]
    ax2.bar(days_x, avg_daily, color=bar_colors, edgecolor="white")
    ax2.axhline(0, color="#333", lw=1)

    zero_cross = next((i + 1 for i, v in enumerate(avg_daily) if v < 0), None)
    if zero_cross:
        ax2.axvline(zero_cross - 0.5, color="#F59E0B", linestyle="--", lw=2,
                    label=f"第{zero_cross}天平均轉空")
        ax2.legend()

    ax2.set_title("每日平均外資淨買超趨勢（千股）")
    ax2.set_xlabel("進場後交易日")
    ax2.set_ylabel("平均淨買超（千股）")
    ax2.set_xticks(days_x)
    ax2.grid(axis="y", alpha=0.25)

    plt.tight_layout()
    plt.savefig("output_charts/1_main.png", dpi=150, bbox_inches="tight")
    print("\n✅ 圖1：output_charts/1_main.png")
    plt.close()

    # ── 圖2：首次賣超天數 CDF ─────────────────────────
    sub = df[df["exit_first_sell"] > 0]["exit_first_sell"]
    if len(sub) >= 3:
        fig, ax = plt.subplots(figsize=(9, 5))
        sorted_d = np.sort(sub)
        cdf = np.arange(1, len(sorted_d) + 1) / n * 100
        ax.step(sorted_d, cdf, color="#3B82F6", lw=2.5, where="post")
        ax.fill_between(sorted_d, cdf, step="post", alpha=0.12, color="#3B82F6")
        for d in range(1, days_forward + 1):
            p = (sub <= d).sum() / n * 100
            if p > 0:
                ax.plot(d, p, "o", color="#1D4ED8", ms=5)
                ax.annotate(f"D{d}: {p:.0f}%", xy=(d, p),
                            xytext=(d + 0.15, p + 1.5), fontsize=8, color="#1D4ED8")
        ax.set_title("進場後首次出現賣超的累積比例（CDF）")
        ax.set_xlabel("進場後交易天數")
        ax.set_ylabel(f"佔全部進場事件比例 %（n={n}）")
        ax.set_xlim(0.5, days_forward + 0.5)
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.25)
        plt.tight_layout()
        plt.savefig("output_charts/2_exit_cdf.png", dpi=150, bbox_inches="tight")
        print("✅ 圖2：output_charts/2_exit_cdf.png")
        plt.close()

    print("\n🎉 完成！")


# ══════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir",  default="./exports", help="exports 資料夾路徑")
    parser.add_argument("--days", type=int, default=10, help="追蹤天數（預設10）")
    args = parser.parse_args()

    entries   = load_entry_list(args.dir)
    result_df = run_tracking(entries, days_forward=args.days)

    if not result_df.empty:
        analyze_and_plot(result_df, days_forward=args.days)
