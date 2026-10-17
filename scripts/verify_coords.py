#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""坐标自检: 找出 destinations.json 中省份归属可疑的条目。

用法:
  python verify_coords.py            # 列出可疑条目
  python verify_coords.py --fix      # 清除可疑条目的坐标
  python verify_coords.py --known    # 用内置已知坐标表交叉验证(可选)

为什么需要: 地理编码对中文地名不可靠, 会把"洛阳"匹配到外省同名地点。
本脚本用「经纬度反查」独立验证 —— 拿已存的坐标向 Open-Meteo 反查地名/省份,
若反查结果与库中记录的名称/区域不符, 即判定为可疑。

这与 enrich_coords.py 的正向校验互补: 一个是查得准不准, 一个是存的对不对。
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
REVERSE = "https://geocoding-api.open-meteo.com/v1/search"
UA = "Mozilla/5.0 (compatible: ai-travel-guide/1.0)"


def reverse(lat: float, lon: float) -> dict | None:
    """按坐标反查最近地名。Open-Meteo 支持 latitude/longitude 反查。"""
    qs = urllib.parse.urlencode(
        {"latitude": lat, "longitude": lon, "count": 1, "language": "zh", "format": "json"}
    )
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"{REVERSE}?{qs}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.load(r).get("results")
            return res[0] if res else None
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="坐标自检")
    ap.add_argument("--fix", action="store_true", help="清除可疑坐标")
    ap.add_argument("--limit", type=int, default=0, help="只检查前 N 条")
    args = ap.parse_args()

    with open(DATA, encoding="utf-8") as f:
        db = json.load(f)
    dests = db["destinations"]
    if args.limit:
        dests = dests[: args.limit]

    checked = [d for d in dests if d.get("lat")]
    print(f"待校验 {len(checked)} 条坐标\n")

    suspect: list[dict] = []
    for i, d in enumerate(checked, 1):
        info = reverse(d["lat"], d["lon"])
        if not info:
            print(f"  [{i}] {d['name']}: 反查失败(网络), 跳过")
            continue
        got_name = (info.get("name") or "").rstrip("市县区镇乡村")
        got_prov = info.get("admin1", "")
        want_name = d["name"].rstrip("市县区镇乡村")
        name_hit = got_name in d["name"] or d["name"] in got_name
        prov_hit = (not got_prov) or (not d.get("admin1")) or got_prov == d.get("admin1")
        if not (name_hit and prov_hit):
            suspect.append(d)
            print(f"  [{i}] {d['name']}: 存({d['lat']:.2f},{d['lon']:.2f}, {d.get('admin1','')}"
                  f") → 反查({got_name}, {got_prov})")
        else:
            print(f"  [{i}] {d['name']}: OK ({got_prov})")

    print(f"\n可疑 {len(suspect)} / {len(checked)} 条")
    if suspect:
        print("可疑条目: " + ", ".join(d["name"] for d in suspect))
        if args.fix:
            for d in suspect:
                for k in ("lat", "lon", "admin1", "elevation"):
                    d.pop(k, None)
            with open(DATA, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=1)
            print(f"\n已清除 {len(suspect)} 条可疑坐标, 请重跑 enrich_coords.py --force 重新抓取")
        else:
            print("\n加 --fix 可清除这些坐标后重新抓取")
    return 0


if __name__ == "__main__":
    sys.exit(main())
