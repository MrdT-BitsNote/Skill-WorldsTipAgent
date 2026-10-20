#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短途灵感: 用户「想不到去哪」时, 结合临近周末/节假日给大方向参考。

用法:
  python suggest_trip.py
  python suggest_trip.py --date 2026-10-10 --top 3
  python suggest_trip.py --region 华东 --season 秋 --top 4 --json

逻辑:
  1. 取「今天」(或 --date), 算出最近的一个周末窗口 + 最近的一个法定假期窗口。
  2. 由窗口月份推断季节(春3-5/夏6-8/秋9-11/冬12-2)。
  3. 从 short_trips.json 中筛选匹配当季(及相邻季)的短途, 按种子随机挑 top N, 兼顾区域/主题多样。
  4. 输出结构化 JSON, 供 render_suggestion.py 渲染成华丽 HTML(可一键 PDF)。

说明: 法定假期为「参考日期」, 以国务院当年放假安排为准; 距离为相对概念, 实际以出发地计算。
"""
import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

TRIPS = Path(__file__).resolve().parent.parent / "references" / "short_trips.json"

# 法定假期(参考): (名称, 起始, 结束) —— 以国务院当年放假安排为准
HOLIDAYS = [
    ("元旦", date(2026, 1, 1), date(2026, 1, 3)),
    ("春节", date(2026, 2, 17), date(2026, 2, 23)),
    ("清明", date(2026, 4, 4), date(2026, 4, 6)),
    ("劳动节", date(2026, 5, 1), date(2026, 5, 5)),
    ("端午", date(2026, 6, 19), date(2026, 6, 21)),
    ("中秋", date(2026, 9, 25), date(2026, 9, 27)),
    ("国庆", date(2026, 10, 1), date(2026, 10, 8)),
    ("元旦", date(2027, 1, 1), date(2027, 1, 3)),
    ("春节", date(2027, 2, 6), date(2027, 2, 12)),
    ("清明", date(2027, 4, 5), date(2027, 4, 7)),
    ("劳动节", date(2027, 5, 1), date(2027, 5, 5)),
    ("端午", date(2027, 6, 9), date(2027, 6, 11)),
    ("中秋", date(2027, 9, 15), date(2027, 9, 17)),
    ("国庆", date(2027, 10, 1), date(2027, 10, 8)),
]

SEASON_OF_MONTH = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
                   6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}
ADJ = {"春": ["春", "秋"], "夏": ["夏", "春"], "秋": ["秋", "春"], "冬": ["冬", "秋"]}


def weekend_window(today: date) -> tuple[date, date, str]:
    """返回(周六, 周日, 标签)。若今天已在周末, 取本周; 否则取下个周末。"""
    wd = today.weekday()  # 0=Mon
    if wd == 5:           # 周六
        sat, sun = today, today + timedelta(days=1)
    elif wd == 6:         # 周日
        sat, sun = today - timedelta(days=1), today
    else:
        days = 5 - wd     # 到本周六
        sat, sun = today + timedelta(days=days), today + timedelta(days=days + 1)
    label = "本周末" if (today <= sun and today >= sat) else (
        "下周末" if (sat - today).days <= 7 else "临近周末")
    return sat, sun, label


def next_holiday(today: date) -> tuple[str, date, date] | None:
    for name, s, e in HOLIDAYS:
        if e >= today:
            return name, s, e
    return None


def build(today: date, region: str = "", season: str = "", top: int = 3, seed: int | None = None) -> dict:
    data = json.load(open(TRIPS, encoding="utf-8"))
    trips = data["trips"]

    sat, sun, wk_label = weekend_window(today)
    hol = next_holiday(today)
    win_month = sat.month
    cur_season = SEASON_OF_MONTH[win_month]
    target_seasons = ADJ.get(season or cur_season, [cur_season])

    # 窗口标签
    if hol and hol[1] <= sat <= hol[2]:
        occ_label = f"{hol[0]}假期({hol[1]:%m.%d}-{hol[2]:%m.%d})"
        occ_kind = "holiday"
        window_days = (hol[2] - hol[1]).days + 1
    elif hol and (hol[1] - today).days <= 21:
        occ_label = f"{wk_label} {sat:%m.%d}-{sun:%m.%d}（临近{hol[0]}）"
        occ_kind = "pre_holiday"
        window_days = 2
    else:
        occ_label = f"{wk_label} {sat:%m.%d}-{sun:%m.%d}"
        occ_kind = "weekend"
        window_days = 2

    # 筛选: 当季严格优先, 不足再放宽到相邻季; 区域可选
    strict_season = season or cur_season
    strict = [t for t in trips if strict_season in t["seasons"]]
    if len(strict) < top:
        loose = [t for t in trips
                 if any(s in target_seasons for s in t["seasons"]) and t not in strict]
        strict = strict + loose
    matched = strict
    if region:
        matched = [t for t in matched if t["region"] == region] or matched
    if not matched:
        matched = trips  # 兜底

    # 窗口天数适配: 窗口内可完成的条目优先(超窗条目保留作备选)
    rng = random.Random(seed if seed is not None else int(today.strftime("%Y%m%d")))
    fit = [t for t in matched if t["days"] <= window_days]
    rest = [t for t in matched if t["days"] > window_days]
    rng.shuffle(fit)
    rng.shuffle(rest)
    pool = fit + rest
    picks = []
    seen_regions = set()
    for t in pool:
        if len(picks) >= top:
            break
        if t["region"] in seen_regions and len(picks) < len(pool):
            continue
        seen_regions.add(t["region"])
        picks.append(t)
    # 若区域去重后不足 top, 补满
    if len(picks) < top:
        for t in pool:
            if t not in picks:
                picks.append(t)
            if len(picks) >= top:
                break

    picks_out = [{
        "title": t["title"], "region": t["region"], "days": t["days"],
        "style": t["style"], "themes": t["themes"], "why": t["why"],
        "highlights": t["highlights"],
    } for t in picks]

    return {
        "generated": today.strftime("%Y-%m-%d"),
        "occasion": {"label": occ_label, "kind": occ_kind,
                     "weekend": f"{sat:%Y-%m-%d}~{sun:%Y-%m-%d}"},
        "season": cur_season,
        "picks": picks_out,
        "disclaimer": "法定假期为参考日期，以国务院当年放假安排为准；距离为相对概念，实际以你的出发地计算。本建议为灵感参考，非预订。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="短途灵感建议(周末/节假日)")
    ap.add_argument("--date", help="今天日期 YYYY-MM-DD, 默认系统今天")
    ap.add_argument("--region", help="限定区域, 如 华东/西南")
    ap.add_argument("--season", help="限定季节 春/夏/秋/冬(默认按窗口推断)")
    ap.add_argument("--top", type=int, default=3, help="推荐条数")
    ap.add_argument("--seed", type=int, help="随机种子(可复现)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    today = date.today()
    if args.date:
        try:
            today = date.fromisoformat(args.date)
        except ValueError:
            print("日期格式错误, 用今天", file=sys.stderr)

    r = build(today, args.region, args.season, args.top, args.seed)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print(f"═══ 短途灵感 · {r['generated']} ═══")
    print(f"窗口: {r['occasion']['label']}（{r['season']}）\n")
    for i, p in enumerate(r["picks"], 1):
        print(f"{i}. {p['title']} ｜ {p['region']} ｜ {p['days']}天 ｜ {p['style']}")
        print(f"   为什么现在去: {p['why']}")
        print(f"   亮点: {'、'.join(p['highlights'])}\n")
    print(f"⚠️ {r['disclaimer']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
