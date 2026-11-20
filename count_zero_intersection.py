#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
統計 data/history/*.json 裡 "count_intersection": 0 出現的次數

在 repo 根目錄 (stock-dashboard/) 執行:
  python count_zero_intersection.py
  python count_zero_intersection.py "data/history/*.json"
"""
import argparse
import glob
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?", default="data/history/*.json")
    args = ap.parse_args()

    files = sorted(glob.glob(args.pattern))
    if not files:
        print(f"找不到檔案: {args.pattern}")
        print(f"目前所在資料夾: {os.getcwd()}")
        print("請先 cd 到 stock-dashboard 根目錄再執行")
        sys.exit(1)

    rows = []      # (檔名, 交易日, count)
    no_field = []  # 沒有 count_intersection 的檔案 (舊格式或壞檔)

    for f in files:
        name = os.path.basename(f)
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
        except (json.JSONDecodeError, OSError):
            no_field.append(name)
            continue
        if not isinstance(data, dict) or "count_intersection" not in data:
            no_field.append(name)
            continue
        dates = data.get("trading_dates") or []
        rows.append((name, " / ".join(dates), data["count_intersection"]))

    zero = [r for r in rows if r[2] == 0]

    print(f"掃描檔案數: {len(files)}")
    print(f"略過(無 count_intersection 欄位): {len(no_field)}")
    print(f"有效天數: {len(rows)}")
    print(f"count_intersection = 0 的次數: {len(zero)}")
    if rows:
        print(f"佔比: {len(zero) / len(rows):.1%}")

    if zero:
        print("\n零交集的日期:")
        for name, dates, _ in zero:
            print(f"  {name}  ({dates})")

    if no_field:
        print("\n被略過的檔案:", ", ".join(no_field))


if __name__ == "__main__":
    main()
