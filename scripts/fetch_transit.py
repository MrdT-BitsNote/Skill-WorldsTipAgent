#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询城际交通(铁路)信息: 站名→车站码, 车次→起讫站与历时。

用法:
  python fetch_transit.py 车站码                      # 查 G71 在哪
  python fetch_transit.py --stations 成都 重庆# 站名→车站码
  python fetch_transit.py --liststations             # 列出车站码表规模

## 关于票价的重要说明
**本脚本不提供票价。** 实测(2026-10):
- 12306 官方 leftTicket 接口会 302 重定向到错误页, 需 Cookie/session 初始化,
  无登录态直接请求必然失败。
- 携程 H5 车次接口(GetBookingByStationV3)虽返回 Ack:Success, 但 TrainInfoList
  恒为空数组, 已失效。
- 携程机票接口返回 code 11010 Operation Forbidden。

因此票价必须由用户自行查12306 App/官网, 或改用官方渠道。
本脚本只提供**不需登录即可获取的车次与车站基础信息**。
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

STATION_JS = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
TRAIN_SEARCH = "https://search.12306.cn/search/v1/train/search"

CACHE = Path(__file__).resolve().parent.parent / "references" / "station_codes.json"


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def load_stations() -> dict[str, str]:
    """站名 → 电报码, 缓存到本地避免重复下载。"""
    if CACHE.exists():
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)

    js = fetch(STATION_JS)
    table: dict[str, str] = {}
    for m in re.finditer(r"@([^|]*)\|([^|]*)\|([A-Z]+)\|", js):
        table[m.group(2)] = m.group(3)
    if not table:
        raise RuntimeError("车站码表解析失败, 站点结构可能已变更")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=0)
    return table


def search_trains(code: str, date: str) -> list[dict]:
    """按车次号搜。注意两点:
    1. 该接口只认车次号, 不支持 OD(出发地-目的地)查询。
    2. 返回的是**模糊匹配**结果集 —— 搜 G71 会包含 G710/G711 等。
       故下面按车次号精确过滤, 且严格模式下若查不到精确匹配会明确告知。
    """
    q = urllib.parse.urlencode({"keyword": code, "date": date})
    req = urllib.request.Request(f"{TRAIN_SEARCH}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r).get("data", [])


def filter_exact(rows: list[dict], code: str) -> list[dict]:
    """只保留车次号精确等于 code 的记录。"""
    key = code.upper()
    return [r for r in rows if str(r.get("station_train_code", "")).upper() == key]


def main() -> int:
    ap = argparse.ArgumentParser(description="城际铁路信息查询(不含票价)")
    ap.add_argument("codes", nargs="*", help="车次号, 如 G71")
    ap.add_argument("--stations", nargs="*", help="站名, 查其电报码")
    ap.add_argument("--date", default=None, help="出发日期 YYYYMMDD")
    ap.add_argument("--liststations", action="store_true", help="显示车站码表规模")
    args = ap.parse_args()

    try:
        table = load_stations()
    except Exception as e:
        print(f"车站码表获取失败: {e}", file=sys.stderr)
        return 1

    if args.liststations:
        print(f"车站码表已加载: {len(table)} 个车站")
        print("示例:", ", ".join(f"{k}={v}" for k, v in list(table.items())[:8]))
        return 0

    if args.stations:
        print("站名 → 电报码:")
        for s in args.stations:
            code = table.get(s)
            print(f"  {s:<12} {code if code else '未收录'}")
        print()

    for code in args.codes:
        date = args.date or __import__("datetime").date().strftime("%Y%m%d")
        try:
            raw = search_trains(code, date)
        except Exception as e:
            print(f"{code}: 查询失败 {e}", file=sys.stderr)
            continue
        rows = filter_exact(raw, code)
        if not rows:
            if raw:
                print(f"{code} ({date}): 无精确匹配(仅模糊结果 {len(raw)} 条, 可能该车次当日不开行)")
            else:
                print(f"{code} ({date}): 无数据(可能当日不开行, 或车次号有误)")
            continue
        print(f"{code} ({date}) {len(rows)} 趟:")
        for r in rows[:10]:
            print(f"  {r.get('from_station')} → {r.get('to_station')}")
        if len(rows) > 10:
            print(f"  ...另有 {len(rows) - 10} 趟")
        print()

    if not args.codes and not args.stations and not args.liststations:
        ap.print_help()
        print("\n提示: 本工具不提供票价。", file=sys.stderr)
        print("  查票价请用 12306 App/官网, 或在购票平台确认。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
