def analyze_intersection(days=2, top_n=10, order_by="last_rank"):
    """
    取得最近 N 個交易日各日 Top-N（依當日 net_shares 取前十），
    回傳「連續 N 天皆入榜」的交集名單與分日指標。

    order_by:
      - "last_rank"  : 以最近一天( trading_dates[0] )的名次排序（預設）
      - "avg_rank"   : 以平均名次排序
      - "sum_net"    : 以兩天 net_shares 總和排序（僅排序用，不做加總名單）
    """
    trading_dates = find_recent_trading_dates(days, lookback=30)
    if len(trading_dates) < days:
        raise RuntimeError(f"只找到 {len(trading_dates)} 個交易日，需求 {days}。")
    # trading_dates[0] 是最近的一天

    day_tops = {}  # { yyyymmdd: DataFrame(columns=[stock_id, stock_name, net_shares, buy_shares, sell_shares, rank]) }
    union_candidates = set()

    for yyyymmdd in trading_dates:
        # 下載兩個市場，合併
        daily_parts = []
        twse = get_twse_foreign_data(yyyymmdd)
        if twse is not None: daily_parts.append(twse)
        time.sleep(0.2)
        tpex = get_tpex_foreign_data(yyyymmdd)
        if tpex is not None: daily_parts.append(tpex)

        if not daily_parts:
            print(f"[WARN] {yyyymmdd} 無資料，略過")
            continue

        daily = pd.concat(daily_parts, ignore_index=True)

        # 當日依 net_shares 排序取前 N
        top = (daily.sort_values("net_shares", ascending=False)
                     .head(top_n)
                     .reset_index(drop=True))

        # 產生 rank（1 起算）
        top["rank"] = top.index + 1
        day_tops[yyyymmdd] = top[[
            "stock_id", "stock_name",
            "buy_shares", "sell_shares", "net_shares", "rank"
        ]].copy()

        union_candidates |= set(top["stock_id"].tolist())

    if len(day_tops) < days:
        raise RuntimeError("有交易日抓不到 Top 名單，請稍後重試。")

    # 交集：必須出現在每一天的 Top-N 名單中
    intersection_ids = set.intersection(
        *[set(df["stock_id"].tolist()) for df in day_tops.values()]
    )

    if not intersection_ids:
        print("[INFO] 連續兩天前十的交集為空。")
        inter_rows = []
    else:
        # 針對交集股票，彙整每日資料
        records = []
        for sid in intersection_ids:
            per_day = {}
            names = set()
            sum_net = 0.0
            ranks = []

            for yyyymmdd in trading_dates:
                df = day_tops[yyyymmdd]
                row = df[df["stock_id"] == sid].iloc[0]
                names.add(str(row["stock_name"]))
                per_day[yyyymmdd] = {
                    "rank": int(row["rank"]),
                    "buy_shares": int(row["buy_shares"]),
                    "sell_shares": int(row["sell_shares"]),
                    "net_shares": int(row["net_shares"]),
                    "buy_lots": int(round(row["buy_shares"]/1000)),
                    "sell_lots": int(round(row["sell_shares"]/1000)),
                    "net_lots": int(round(row["net_shares"]/1000)),
                }
                sum_net += float(row["net_shares"])
                ranks.append(int(row["rank"]))

            # 名稱以最近一天為主
            last_day = trading_dates[0]
            last_row = day_tops[last_day][day_tops[last_day]["stock_id"] == sid].iloc[0]
            stock_name = str(last_row["stock_name"])

            records.append({
                "stock_id": sid,
                "stock_name": stock_name,
                "per_day": per_day,                # 各日指標
                "sum_net_shares": int(sum_net),    # 僅供排序/參考
                "avg_rank": sum(ranks)/len(ranks),
                "last_rank": int(per_day[last_day]["rank"])
            })

        # 依排序策略排序
        if order_by == "avg_rank":
            records.sort(key=lambda x: (x["avg_rank"], -x["sum_net_shares"]))
        elif order_by == "sum_net":
            records.sort(key=lambda x: (-x["sum_net_shares"], x["avg_rank"]))
        else:  # "last_rank"
            records.sort(key=lambda x: (x["last_rank"], -x["sum_net_shares"]))

        inter_rows = records

    # 組合輸出 payload
    payload = {
        "mode": "intersection_topN_per_day",
        "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Taipei",
        "source": {
            "twse": "https://www.twse.com.tw/rwd/zh/fund/T86",
            "tpex": "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
        },
        "params": {"days": days, "top_n": top_n, "order_by": order_by},
        "trading_dates": trading_dates,  # 由近到遠
        "count_intersection": len(inter_rows),
        "stocks": inter_rows
    }
    return payload


def main():
    days   = int(os.getenv("DAYS", "2"))
    top_n  = int(os.getenv("TOP_N", "10"))
    order  = os.getenv("ORDER_BY", "last_rank")  # last_rank / avg_rank / sum_net

    payload = analyze_intersection(days=days, top_n=top_n, order_by=order)

    # latest.json
    OUT_LATEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_LATEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 寫入 {OUT_LATEST}")

    # 以最近一個交易日命名歷史檔
    last_trade = payload["trading_dates"][0]
    OUT_HISTORY = OUT_HISTORY_DIR / f"{last_trade}.json"
    OUT_HISTORY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 寫入 {OUT_HISTORY}")

    # 匯出 CSV（交集名單）
    rows = payload["stocks"]
    csv_cols = ["stock_id", "stock_name"]
    # 平鋪 per_day 欄位：每日 net_lots / rank
    for y in payload["trading_dates"]:
        csv_cols += [f"{y}_rank", f"{y}_net_lots"]

    recs = []
    for r in rows:
        item = {"stock_id": r["stock_id"], "stock_name": r["stock_name"]}
        for y in payload["trading_dates"]:
            pdict = r["per_day"][y]
            item[f"{y}_rank"] = pdict["rank"]
            item[f"{y}_net_lots"] = pdict["net_lots"]
        recs.append(item)

    out_csv = OUT_EXPORT_DIR / f"foreign_net_top{top_n}_intersection_{NOW_TPE.strftime('%Y%m%d')}.csv"
    OUT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(recs, columns=csv_cols).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[OK] 匯出 {out_csv}")
