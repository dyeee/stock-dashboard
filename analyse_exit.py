"""
外資出場追蹤系統 v2
流程：
  1. 讀取你的進場名單 CSV（外資連續前10名交集_*.csv）
  2. 對每個進場事件，用 FinMind 抓個股往後 10 個交易日的三大法人資料
  3. 判斷外資是否開始賣出（出場訊號）
  4. 統計 + 畫圖

安裝：pip install pandas numpy matplotlib finmind
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

# ── FinMind ────────────────────────────────────────────
from FinMind.data import DataLoader

dl = DataLoader()
# 若有帳號可登入提升 API 限制（免費每小時 600 次）
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
    "consec_days", "today_net", "today_date",
    "prev_rank", "prev_net", "prev_date",
    "total_net", "avg_net"
]


# ══════════════════════════════════════════════════════
# STEP 1：讀取進場名單，取得唯一進場事件
# ══════════════════════════════════════════════════════
def load_entry_list(exports_dir: str) -> pd.DataFrame:
    pattern = os.path.join(exports_dir, "外資連續前10名交集_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"找不到 CSV：{exports_dir}")

    seen_dates = {}  # date -> filepath（同天取最新）
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
            df = pd.read_csv(fpath, header=None, names=COLUMNS,
                             dtype={"stock_id": str}, encoding="utf-8-sig")
            df["stock_id"] = df["stock_id"].str.strip()
            df["stock_name"] = df["stock_name"].str.strip()
            df["file_date"] = pd.to_datetime(date_str, format="%Y%m%d")
            all_dfs.append(df)
        except Exception as e:
            print(f"⚠️  {os.path.basename(fpath)} 讀取失敗：{e}")

    combined = pd.concat(all_dfs, ignore_index=True)
    combined["consec_days"] = pd.to_numeric(combined["consec_days"], errors="coerce")
    combined["today_net"] = pd.to_numeric(combined["today_net"], errors="coerce")

    # ── 只取「新進場」：consec_days == 1 ──────────────
    # consec_days=1 代表這天是連續買超第1天，即進場日
    entries = combined[combined["consec_days"] == 1].copy()
    entries = entries.rename(columns={"file_date": "entry_date"})

    # 去除重複（同股同日只保留一筆）
    entries = entries.drop_duplicates(subset=["stock_id", "entry_date"])
    entries = entries.sort_values("entry_date").reset_index(drop=True)

    print(f"✅ 讀取完成：{len(seen_dates)} 個交易日，找到 {len(entries)} 個進場事件")
    print(f"   涵蓋股票：{entries['stock_id'].nunique()} 檔")
    print(f"   時間範圍：{entries['entry_date'].min().date()} ~ {entries['entry_date'].max().date()}\n")
    return entries


# ══════════════════════════════════════════════════════
# STEP 2：用 FinMind 抓個股往後 10 交易日的三大法人資料
# ══════════════════════════════════════════════════════
def fetch_chip_after_entry(
    stock_id: str,
    entry_date: pd.Timestamp,
    days_forward: int = 10,
    cache: dict = None,
) -> pd.DataFrame:
    """
    抓 entry_date 後 days_forward 個交易日的外資買賣超
    用 cache 避免重複 API 呼叫（同一檔股票只抓一次）
    """
    # 往後多抓一些日曆天，確保涵蓋足夠交易日（假日不算）
    start = (entry_date + timedelta(days=1)).strftime("%Y-%m-%d")
    end = (entry_date + timedelta(days=days_forward * 2 + 5)).strftime("%Y-%m-%d")
    cache_key = (stock_id, start, end)

    if cache is not None and cache_key in cache:
        df = cache[cache_key]
    else:
        try:
            df = dl.taiwan_stock_institutional_investors(
                stock_id=stock_id,
                start_date=start,
                end_date=end,
            )
            if cache is not None:
                cache[cache_key] = df
            time.sleep(0.3)  # 避免打爆 API
        except Exception as e:
            print(f"  ⚠️  {stock_id} FinMind 失敗：{e}")
            return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # 只取外資（Foreign_Investor）
    foreign = df[df["name"] == "Foreign_Investor"].copy()
    if foreign.empty:
        return pd.DataFrame()

    foreign["date"] = pd.to_datetime(foreign["date"])
    foreign = foreign.sort_values("date")

    # buy - sell = 當日外資買賣超（股）
    foreign["foreign_net"] = foreign["buy"] - foreign["sell"]

    # 只取進場後前 days_forward 個交易日
    result = foreign[["date", "foreign_net"]].head(days_forward).reset_index(drop=True)
    result["trading_day"] = result.index + 1  # 第幾個交易日
    return result


# ══════════════════════════════════════════════════════
# STEP 3：判斷出場訊號
# ══════════════════════════════════════════════════════
def detect_exit(chip_df: pd.DataFrame) -> dict:
    """
    輸入：進場後每日外資買賣超 DataFrame
    輸出：各種出場定義的天數

    出場定義：
      A. 第一天轉賣超（foreign_net < 0）
      B. 連續 2 天賣超
      C. 累積淨賣超轉負（從進場後累積買賣超變成負）
    """
    nets = chip_df["foreign_net"].values
    n = len(nets)

    # A：第一天賣超
    exit_a = next((i + 1 for i, v in enumerate(nets) if v < 0), -1)

    # B：連續 2 天賣超
    exit_b = -1
    streak = 0
    for i, v in enumerate(nets):
        if v < 0:
            streak += 1
            if streak >= 2:
                exit_b = i  # 連續第2天的位置（1-based = i+1，但我們回傳開始那天）
                break
        else:
            streak = 0

    # C：累積轉負
    exit_c = -1
    cumsum = 0
    for i, v in enumerate(nets):
        cumsum += v
        if cumsum < 0:
            exit_c = i + 1
            break

    # 在追蹤期內最後一天是否仍買超
    still_buying = nets[-1] > 0 if n > 0 else None

    return {
        "exit_first_sell": exit_a,      # 第一次賣超（交易日）
        "exit_consec_2": exit_b,        # 連續2天賣超開始
        "exit_cumul_neg": exit_c,       # 累積轉負
        "still_buying_end": still_buying,
        "avg_net_10d": float(np.mean(nets)),
        "total_net_10d": float(np.sum(nets)),
        "days_positive": int(np.sum(nets > 0)),  # 幾天買超
        "days_negative": int(np.sum(nets < 0)),  # 幾天賣超
    }


# ══════════════════════════════════════════════════════
# STEP 4：主流程 - 逐一處理進場事件
# ══════════════════════════════════════════════════════
def run_analysis(entries: pd.DataFrame, days_forward: int = 10) -> pd.DataFrame:
    results = []
    chip_cache = {}  # 避免同股重複抓
    total = len(entries)

    print(f"開始追蹤 {total} 個進場事件（每個往後追 {days_forward} 個交易日）...\n")

    for i, row in entries.iterrows():
        sid = row["stock_id"]
        name = row["stock_name"]
        entry_date = row["entry_date"]
        entry_net = row["today_net"]

        print(f"[{i+1}/{total}] {sid} {name}  進場：{entry_date.date()}", end="  ")

        chip_df = fetch_chip_after_entry(sid, entry_date, days_forward, chip_cache)

        if chip_df.empty:
            print("→ 無資料")
            continue

        signals = detect_exit(chip_df)
        print(f"→ 10天買/賣：{signals['days_positive']}天買/{signals['days_negative']}天賣  "
              f"累計淨：{signals['total_net_10d']:+.0f}")

        results.append({
            "entry_date": entry_date.date(),
            "stock_id": sid,
            "stock_name": name,
            "entry_net": entry_net,
            **signals,
            # 原始每日數據（方便後續細看）
            "daily_nets": ",".join(f"{v:.0f}" for v in chip_df["foreign_net"].values),
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv("exit_tracking_result.csv", index=False, encoding="utf-8-sig")
    print(f"\n✅ 明細儲存：exit_tracking_result.csv（共 {len(result_df)} 筆）")
    return result_df


# ══════════════════════════════════════════════════════
# STEP 5：統計分析 + 4 張圖
# ══════════════════════════════════════════════════════
def analyze_and_plot(df: pd.DataFrame, days_forward: int = 10):
    os.makedirs("output_charts", exist_ok=True)

    print("\n" + "=" * 60)
    print("📊 外資進場後 10 交易日籌碼行為分析")
    print("=" * 60)
    print(f"有效樣本：{len(df)} 筆\n")

    # 基本統計
    print(f"【進場後 {days_forward} 個交易日統計】")
    print(f"  平均買超天數：{df['days_positive'].mean():.1f} 天")
    print(f"  平均賣超天數：{df['days_negative'].mean():.1f} 天")
    print(f"  {days_forward}天結束仍買超比例：{df['still_buying_end'].mean()*100:.1f}%")
    print()

    for col, label in [
        ("exit_first_sell", "第1次轉賣超（交易日）"),
        ("exit_consec_2",   "連續2天賣超（交易日）"),
        ("exit_cumul_neg",  "累積轉負（交易日）"),
    ]:
        sub = df[df[col] > 0][col]
        pct = len(sub) / len(df) * 100
        if len(sub) > 0:
            print(f"【{label}】  {days_forward}天內發生：{pct:.1f}%")
            print(f"  平均第 {sub.mean():.1f} 天  中位數第 {sub.median():.1f} 天")
        else:
            print(f"【{label}】  {days_forward}天內未發生")
        print()

    # ── 圖1：10天內買超 vs 賣超天數分布 ───────────────
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(f"外資進場後 {days_forward} 個交易日籌碼行為", fontsize=14, fontweight="bold")

    ax = axes[0]
    ax.hist(df["days_positive"], bins=range(0, days_forward + 2),
            alpha=0.7, color="#22C55E", edgecolor="white", label="買超天數")
    ax.hist(df["days_negative"], bins=range(0, days_forward + 2),
            alpha=0.7, color="#EF4444", edgecolor="white", label="賣超天數")
    ax.axvline(df["days_positive"].mean(), color="#15803D", linestyle="--", lw=1.5,
               label=f"買超平均 {df['days_positive'].mean():.1f}天")
    ax.axvline(df["days_negative"].mean(), color="#B91C1C", linestyle="--", lw=1.5,
               label=f"賣超平均 {df['days_negative'].mean():.1f}天")
    ax.set_title("買超/賣超天數分布")
    ax.set_xlabel("天數")
    ax.set_ylabel("次數")
    ax.legend(fontsize=8)

    # ── 圖1右：每天仍在買超的比例（半衰期）────────────
    ax2 = axes[1]
    daily_data = []
    for nets_str in df["daily_nets"]:
        vals = [float(v) for v in nets_str.split(",")]
        daily_data.append(vals)

    # 補齊長度
    max_len = max(len(v) for v in daily_data)
    daily_arr = np.array([v + [np.nan]*(max_len-len(v)) for v in daily_data])

    still_buying_pct = np.nanmean(daily_arr > 0, axis=0) * 100
    days_x = range(1, len(still_buying_pct) + 1)

    ax2.bar(days_x, still_buying_pct,
            color=["#22C55E" if v > 50 else "#F59E0B" if v > 30 else "#EF4444"
                   for v in still_buying_pct])
    ax2.axhline(50, color="#555", linestyle="--", lw=1.2, label="50%")
    ax2.set_title(f"進場後第 N 天仍在買超的比例")
    ax2.set_xlabel("進場後第幾個交易日")
    ax2.set_ylabel("仍在買超比例 (%)")
    ax2.set_xticks(days_x)
    ax2.set_ylim(0, 105)
    ax2.legend()

    plt.tight_layout()
    plt.savefig("output_charts/1_chip_behavior.png", dpi=150, bbox_inches="tight")
    print("✅ 圖1：output_charts/1_chip_behavior.png")
    plt.close()

    # ── 圖2：第一次轉賣超的天數 CDF ───────────────────
    sub = df[df["exit_first_sell"] > 0]["exit_first_sell"]
    if len(sub) > 0:
        fig, ax = plt.subplots(figsize=(9, 5))
        sorted_days = np.sort(sub)
        cdf = np.arange(1, len(sorted_days) + 1) / len(df) * 100

        ax.step(sorted_days, cdf, color="#3B82F6", lw=2.5, where="post")
        ax.fill_between(sorted_days, cdf, step="post", alpha=0.1, color="#3B82F6")

        for d in range(1, days_forward + 1):
            p = (sub <= d).sum() / len(df) * 100
            if p > 0:
                ax.annotate(f"D{d}\n{p:.0f}%", xy=(d, p),
                            xytext=(d + 0.2, p + 2), fontsize=8, color="#1D4ED8")

        ax.set_title("進場後第幾天首次轉賣超（累積比例）")
        ax.set_xlabel("進場後交易天數")
        ax.set_ylabel(f"佔全部進場事件比例 (%)\n（分母含未賣超者）")
        ax.set_xlim(0.5, days_forward + 0.5)
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.25)

        plt.tight_layout()
        plt.savefig("output_charts/2_exit_cdf.png", dpi=150, bbox_inches="tight")
        print("✅ 圖2：output_charts/2_exit_cdf.png")
        plt.close()

    # ── 圖3：平均每日外資淨買超趨勢 ───────────────────
    fig, ax = plt.subplots(figsize=(10, 5))
    avg_daily = np.nanmean(daily_arr, axis=0)
    colors = ["#22C55E" if v > 0 else "#EF4444" for v in avg_daily]
    ax.bar(days_x, avg_daily / 1000, color=colors, edgecolor="white")  # 千股
    ax.axhline(0, color="#333", lw=1)
    ax.set_title(f"進場後各天平均外資淨買超（千股）")
    ax.set_xlabel("進場後第幾個交易日")
    ax.set_ylabel("平均淨買超（千股）")
    ax.set_xticks(days_x)
    ax.grid(axis="y", alpha=0.25)

    # 標正負分水嶺
    zero_cross = next((i+1 for i, v in enumerate(avg_daily) if v < 0), None)
    if zero_cross:
        ax.axvline(zero_cross - 0.5, color="#F59E0B", linestyle="--", lw=2,
                   label=f"平均第 {zero_cross} 天轉空")
        ax.legend()

    plt.tight_layout()
    plt.savefig("output_charts/3_avg_daily_net.png", dpi=150, bbox_inches="tight")
    print("✅ 圖3：output_charts/3_avg_daily_net.png")
    plt.close()

    print("\n🎉 分析完成！查看 output_charts/ 資料夾")


# ══════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="./exports", help="exports 資料夾路徑")
    parser.add_argument("--days", type=int, default=10, help="進場後追蹤天數（預設10）")
    args = parser.parse_args()

    # 1. 載入進場名單
    entries = load_entry_list(args.dir)

    # 2. 追蹤 + 出場分析
    result_df = run_analysis(entries, days_forward=args.days)

    # 3. 統計 + 畫圖
    if not result_df.empty:
        analyze_and_plot(result_df, days_forward=args.days)
