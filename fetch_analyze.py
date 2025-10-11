import json, time, requests
import pandas as pd
from pathlib import Path

# 範例：公開 API（請換成你的）
API_URL = "https://api.publicapis.org/entries"  # DEMO 用
OUT = Path("data/latest.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

def fetch():
    r = requests.get(API_URL, timeout=30)
    r.raise_for_status()
    return r.json()

def analyze(raw):
    # 這裡做你需要的統計/清洗/特徵工程；以下只是示範
    entries = raw.get("entries", [])
    df = pd.DataFrame(entries)
    # 例：按 Category 分組計數（示範分析）
    summary = (
        df.groupby("Category")
          .size()
          .reset_index(name="count")
          .sort_values("count", ascending=False)
          .head(10)
          .to_dict(orient="records")
    )
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "source": API_URL,
        "top_categories": summary,
        "total": int(df.shape[0]),
    }

def main():
    raw = fetch()
    result = analyze(raw)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
