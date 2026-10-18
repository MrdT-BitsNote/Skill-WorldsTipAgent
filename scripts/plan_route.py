#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行程起点规划: 从出发地到目的地的距离与方向判定。

用法:
  python plan_route.py 出发地 目的地 目的地2 ...# 多目的地
  python plan_route.py 出发地 目的地 --from-date 2026-10-10

回答的问题:
- 每个目的地离出发地多远(直线距离/方位)
- 多个目的地之间如何排序(按地理邻近度, 避免来回折返)

距离用 haversine 公式基于预置坐标计算, 不消耗任何 API 配额。
**不提供票价** —— 原因票价一律估算、以官方渠道实时为准。
"""
import argparse
import json
import math
import sys
from pathlib import Path

import refloader

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"

DIRECTIONS = {
    "北": 0, "东北": 45, "东": 90, "东南": 135,
    "南": 180, "西南": 225, "西": 270, "西北": 315,
}


def load() -> list[dict]:
    return refloader.load("destinations.json")["destinations"]


def find(name: str, dests: list[dict]) -> dict | None:
    hits = [d for d in dests if d["name"] == name]
    if not hits:
        hits = [d for d in dests if name in d["name"] or d["name"] in name]
    if not hits:
        return None
    d = hits[0]
    if d.get("lat") is None:
        return {"name": d["name"], "region": d.get("region", ""), "lat": None, "lon": None,
                "url": d.get("url", "")}
    return d


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """球面直线距离(km)。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """方位角转中文方位。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return min(DIRECTIONS.items(), key=lambda kv: abs(kv[1] - deg) if abs(kv[1] - deg) <= 180
               else 360 - abs(kv[1] - deg))[0]


def fmt_dist(km: float) -> str:
    if km < 1:
        return f"{km * 1000:.0f} m"
    if km < 100:
        return f"{km:.1f} km"
    return f"{km:.0f} km"


def main() -> int:
    ap = argparse.ArgumentParser(description="行程起点规划(距离与方位, 不含票价)")
    ap.add_argument("places", nargs="+", help="起点与目的地, 如: 北京 成都 重庆")
    ap.add_argument("--date", help="出发日期(仅作标注, 不影响计算)")
    args = ap.parse_args()

    if len(args.places) < 2:
        ap.print_help()
        return 1

    dests = load()
    found = []
    for p in args.places:
        d = find(p, dests)
        if d is None:
            print(f"跳过「{p}」: 不在目的地库中", file=sys.stderr)
            continue
        found.append(d)

    if len(found) < 2:
        print("至少需要两个有效地点(起点 + 目的地)", file=sys.stderr)
        return 1

    origin, targets = found[0], found[1:]
    if args.date:
        print(f"出发日期: {args.date}")
    print(f"\n起点: {origin['name']}" + (f"({origin.get('admin1','')})" if origin.get("admin1") else ""))

    missing = [t for t in targets if t.get("lat") is None]
    ready = [t for t in targets if t.get("lat") is not None]

    if missing:
        print("\n以下目的地无可靠坐标, 无法计算距离:")
        for m in missing:
            print(f"  - {m['name']}({m.get('region','')})")
        print("  可用 --lat/--lon 手动指定, 或按区域邻近的其他目的地替代。")

    if not ready:
        return 1

    if origin.get("lat") is None:
        print(f"\n起点「{origin['name']}」无坐标, 无法计算距离。")
        print("提示: 起点可为任意城市, 用天气脚本的坐标查询或手动指定。")
        return 1

    print("\n=== 距离与方位(直线, 仅供参考) ===")
    rows = []
    for t in ready:
        km = haversine(origin["lat"], origin["lon"], t["lat"], t["lon"])
        b = bearing(origin["lat"], origin["lon"], t["lat"], t["lon"])
        rows.append((km, b, t))
    rows.sort()
    for km, b, t in rows:
        scope = "市内/同城" if km < 50 else ("省内" if km < 300 else "跨省")
        print(f"  {t['name']:<10} {fmt_dist(km):>10}  {b}向  [{scope}]  {t.get('admin1','')}")

    if len(ready) > 1:
        print("\n=== 目的地之间相邻度(贪心排序, 减少折返) ===")
        cur = origin
        remaining = ready[:]
        seq = [origin]
        while remaining:
            nxt = min(
                remaining,
                key=lambda d: haversine(cur["lat"], cur["lon"], d["lat"], d["lon"]),
            )
            km = haversine(cur["lat"], cur["lon"], nxt["lat"], nxt["lon"])
            print(f"  {cur['name']} → {nxt['name']}: {fmt_dist(km)}")
            seq.append(nxt)
            remaining.remove(nxt)
            cur = nxt
        print("\n  建议顺序: " + " → ".join(x["name"] for x in seq))

        total = sum(
            haversine(seq[i]["lat"], seq[i]["lon"], seq[i + 1]["lat"], seq[i + 1]["lon"])
            for i in range(len(seq) - 1)
        )
        print(f"  总直线里程约 {fmt_dist(total)}(实际路程通常为其 1.3-1.5 倍)")
        if any(
            haversine(a["lat"], a["lon"], b["lat"], b["lon"]) > 1500
            for a, b in zip(seq, seq[1:])
        ):
            print("\n  注意: 存在超过 1500km 的跨段, 建议拆成多个行程, 或调整为就近目的地")

    print("\n提示: 本工具不含票价与班次。火车票请查 12306 App/官网。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
