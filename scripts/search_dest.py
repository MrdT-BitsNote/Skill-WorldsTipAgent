#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线检索国内目的地库。

用法:
  python search_dest.py <关键词>              # 按名称/简介/拼音模糊搜索
  python search_dest.py --region 西南          # 按区域列出
  python search_dest.py --theme 草原            # 按主题词搜索(景点类型)
  python search_dest.py --days-max 3          # 筛选建议天数<= N 的目的地
  python search_dest.py --stats# 区域统计

无第三方依赖, 直接读 references/destinations.json。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import refloader

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"

# 常见主题词 -> 简介中可能出现的关键词
THEME_HINTS = {
    "草原": ["草原", "牧场", "骑马", "蒙古", "锡林", "呼伦贝尔"],
    "沙漠": ["沙漠", "沙丘", "响沙", "胡杨", "戈壁"],
    "雪山": ["雪山", "冰川", "贡嘎", "珠峰", "羌塘", "梅里", "稻城"],
    "海岛": ["海岛", "沙滩", "海岸", "环岛", "海鲜", "渔村"],
    "古城": ["古城", "古镇", "明清", "老城", "城墙", "牌坊"],
    "美食": ["美食", "小吃", "火锅", "面", "菜", "夜市", "街区"],
    "亲子": ["乐园", "主题", "亲子", "动物园", "海洋"],
    "徒步": ["徒步", "登山", "峡谷", "雪山", "线路"],
    "摄影": ["摄影", "日出", "日落", "云海", "光影", "打卡"],
    "避暑": ["避暑", "凉爽", "22度", "夏都"],
    "温泉": ["温泉", "温泉县"],
    "边境": ["边境", "口岸", "国门"],
}


def load() -> list[dict]:
    return refloader.load("destinations.json")["destinations"]


def match_theme(d: dict, theme: str) -> bool:
    keys = THEME_HINTS.get(theme, [theme])
    blob = f"{d['name']}{d['summary']}{d['region']}{''.join(d.get('aliases') or [])}"
    return any(k in blob for k in keys)


def parse_days(val) -> int | None:
    """'2-3天' -> 3 (取上限), '4天' -> 4, None -> None"""
    if not val:
        return None
    m = re.search(r"(\d+)(?:\s*-\s*(\d+))?", str(val))
    if not m:
        return None
    return int(m.group(2) or m.group(1))


def fmt(d: dict) -> str:
    days = f" · 建议 {d['days']}" if d.get("days") else ""
    url = d.get("url") or ""
    return f"{d['name']}（{d['region']}）\n    {d['summary']}{days}" + (f"\n    {url}" if url else "")


def main() -> int:
    ap = argparse.ArgumentParser(description="国内目的地库检索")
    ap.add_argument("keyword", nargs="?", help="名称/简介关键词")
    ap.add_argument("--region", help="按区域筛选, 支持部分匹配, 如 西南 / 华北")
    ap.add_argument("--theme", help="主题筛选: " + " / ".join(THEME_HINTS.keys()))
    ap.add_argument("--days-max", dest="days_max", type=int, help="建议天数 <= N")
    ap.add_argument("--stats", action="store_true", help="打印区域统计")
    ap.add_argument("--limit", type=int, default=15, help="最多返回条数")
    args = ap.parse_args()

    rows = load()

    if args.stats:
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["region"]] = counts.get(r["region"], 0) + 1
        print(f"共 {len(rows)} 个目的地\n")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {k:<10} {v:>3}个")
        return 0

    if args.region:
        rows = [r for r in rows if args.region in r["region"]]
    if args.theme:
        rows = [r for r in rows if match_theme(r, args.theme)]
    if args.days_max is not None:
        rows = [r for r in rows if (n := parse_days(r.get("days"))) and n <= args.days_max]

    if args.keyword:
        kw = args.keyword.lower()
        rows = [
            r for r in rows
            if kw in r["name"].lower()
            or kw in r["summary"].lower()
            or kw in r["slug"].lower()
            or kw in r["pinyin"].lower()
            or any(kw in a.lower() for a in (r.get("aliases") or []))
        ]

    if not rows:
        print("无匹配结果。可用 --stats 查看区域, 或去掉筛选条件重试。")
        return 1

    shown = rows[: args.limit]
    print(f"匹配 {len(rows)} 个目的地, 显示 {len(shown)} 个:\n")
    for r in shown:
        print(fmt(r))
        print()
    if len(rows) > len(shown):
        print(f"...另有 {len(rows) - len(shown)} 个, 用 --limit 调整")
    return 0


if __name__ == "__main__":
    sys.exit(main())
