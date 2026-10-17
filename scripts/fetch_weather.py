#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询目的地实时天气与预报。

数据源（v0.1.0 统一接入 live_api）：
  - 和风 (QWeather)：优先，环境变量 QWEATHER_KEY 配置后启用（更准确的中文天气 + 国内覆盖）
  - Open-Meteo：免 key 兜底（无 QWEATHER_KEY 时自动使用）

用法:
  python fetch_weather.py 成都                # 读预置坐标, 默认和风优先/Open-Meteo 兜底
  python fetch_weather.py 成都 --days 7        # 7天预报
  python fetch_weather.py 成都 拉萨 --days 5    # 多地对比
  python fetch_weather.py --lat 30.57 --lon 104.07   # 手动坐标(库里没收录时)
  python fetch_weather.py 成都 --json          # 输出渲染可直接消费的 JSON(含 source 字段)

说明: 坐标已由 enrich_coords.py 预置进 destinations.json, 本脚本离线读取。
"""
import argparse
import json
import sys
from pathlib import Path

# 真实天气统一入口（和风优先 / Open-Meteo 兜底）
from live_api import weather_unified  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"


def find_dest(name: str) -> dict | None:
    with open(DATA, encoding="utf-8") as f:
        dests = json.load(f)["destinations"]
    hits = [d for d in dests if d["name"] == name]
    if not hits:
        hits = [d for d in dests if name in d["name"] or d["name"] in name]
    return hits[0] if hits else None


def render(name: str, days: list, source: str, dest: dict | None = None) -> str:
    lines = [f"【{name}】  数据源: {source}"]
    if dest and dest.get("admin1"):
        lines.append(f"  位置: {dest['admin1']} ({dest['lat']:.3f}, {dest['lon']:.3f})")
    lines.append("  预报:")
    for d in days:
        lo, hi = d.get("t_min"), d.get("t_max")
        wmo = d.get("wmo_text", "")
        pop = d.get("precip_prob")
        rain = f" 降水概率{pop}%" if pop is not None else ""
        lines.append(f"    {d.get('date','')} {wmo}{rain} {lo}~{hi}°C")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="查询目的地天气（和风优先 / Open-Meteo 兜底）")
    ap.add_argument("cities", nargs="*", help="目的地名(须在库内)")
    ap.add_argument("--lat", type=float, help="手动指定纬度")
    ap.add_argument("--lon", type=float, help="手动指定经度")
    ap.add_argument("--days", type=int, default=7, help="预报天数 1-16")
    ap.add_argument("--json", action="store_true", help="输出渲染可直接消费的 JSON（含 source 字段）")
    args = ap.parse_args()

    days = max(1, min(16, args.days))
    targets: list = []

    if args.lat is not None and args.lon is not None:
        targets.append(("自定义位置", args.lat, args.lon, None))
    else:
        if not args.cities:
            ap.print_help()
            return 1
        for c in args.cities:
            d = find_dest(c)
            if not d:
                print(f"跳过「{c}」: 不在目的地库中(该库为旅游目的地, 非任意城市)", file=sys.stderr)
                continue
            if d.get("lat") is None:
                print(
                    f"跳过「{c}」: 库中无坐标(地理编码未能可靠定位该地名)。\n"
                    f"  说明: 为避免查到错误地点的天气, 不可靠的坐标一律不入库。\n"
                    f"  变通: 用 --lat/--lon 手动指定, 或查询同区域已收录的城市。",
                    file=sys.stderr,
                )
                continue
            targets.append((d["name"], d["lat"], d["lon"], d))

    if not targets:
        return 1

    payload: dict = {"results": []}
    for name, lat, lon, dest in targets:
        day_list, source = weather_unified(lat, lon, days)
        if not day_list:
            print(f"{name}: 天气查询失败（网络和风/Open-Meteo 均不可用）", file=sys.stderr)
            continue
        payload["results"].append({
            "city": name,
            "source": source,
            "days": day_list,
        })
        if not args.json:
            print(render(name, day_list, source, dest))
            print()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
