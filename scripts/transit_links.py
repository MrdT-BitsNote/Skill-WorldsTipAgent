#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交通查询引导 —— 站名/电报码解析 + 官方渠道文字提示（零外链、品牌中性）。

设计纪律（v0.1.17 平台合规改判）：
- **不生成任何可点击外链、不做站外引流**：旧版曾输出第三方 OTA/票务平台的预填充深链，
  因平台判定「站外引流 / 竞品导流 / 票务代订嫌疑」已整体移除。
- **品牌中性**：文案只泛指「12306 官方渠道」「航司官方渠道/官方售票平台」，不点名具体商业平台。
- 仅做数据解析：城市名 → 车站名与电报码（复用 station_codes.json），供编排层以文字路书呈现。
- 零第三方依赖，仅用标准库。

用法：
  python transit_links.py 北京 上海 --date 2026-10-20
  python transit_links.py 成都 重庆 --date 2026-11-01 --json
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REF_DIR = Path(__file__).resolve().parent.parent / "references"
STATION_CODES_FILE = REF_DIR / "station_codes.json"

_STATION_CODES: dict[str, str] | None = None


def _load_stations() -> dict[str, str]:
    global _STATION_CODES
    if _STATION_CODES is None:
        with open(STATION_CODES_FILE, encoding="utf-8") as f:
            _STATION_CODES = json.load(f)
    return _STATION_CODES


def resolve_station(city: str) -> tuple[str, str] | None:
    """城市名 → (站名, 电报码)。优先匹配主站，其次含城市名的站。"""
    codes = _load_stations()
    if city in codes:
        return (city, codes[city])
    for s in ("东", "南", "西", "北"):
        name = city + s
        if name in codes:
            return (name, codes[name])
    for name, code in codes.items():
        if name.startswith(city) and len(name) <= len(city) + 2:
            return (name, code)
    return None


def generate(from_city: str, to_city: str, travel_date: str | None = None,
             include_flight: bool = True) -> dict:
    """解析站名/电报码并给出官方渠道文字查询提示（无任何外链）。"""
    if not travel_date:
        travel_date = (date.today() + timedelta(days=1)).isoformat()

    from_st = resolve_station(from_city)
    to_st = resolve_station(to_city)

    def _status(st):
        if st:
            return {"station": st[0], "code": st[1], "status": "ok"}
        return {"station": None, "code": None, "status": "station_not_found"}

    result = {
        "from": from_city,
        "to": to_city,
        "date": travel_date,
        "generated_at": date.today().isoformat(),
        "rail": {
            **_status(from_st),
            "to_station": to_st[0] if to_st else None,
            "to_code": to_st[1] if to_st else None,
            "hint": (f"铁路出行：请到 12306 官方渠道（App / 官网 www.12306.cn）"
                     f"按到发站查询当日车次、余票与票价"
                     + (f"（建议到发站：{from_st[0]} → {to_st[0] if to_st else to_city}）" if from_st else "")
                     + "。本技能不代订、不缓存实时票价。")
                     if (from_st and to_st) else
                     f"铁路出行：请到 12306 官方渠道按城市『{from_city}』『{to_city}』查对应车站名后查询余票票价。",
            "from_status": _status(from_st)["status"],
            "to_status": _status(to_st)["status"],
        },
        "flight": {
            "hint": (f"民航出行：请到各航空公司官方渠道或官方售票平台查询"
                     f"{from_city}—{to_city} 当日航班、时刻与票价，以官方实时结果为准。")
        } if include_flight else None,
        "disclaimer": "票价/余票/时刻以官方渠道实时结果为准；本技能仅做规划与信息引导，不代订、不外链导流、不缓存票价。",
    }
    return result


def render_html(links: dict) -> str:
    """生成可嵌入小册子的「官方渠道查询提示」卡片（纯文字，无任何超链接）。"""
    parts = ['<div class="card" style="border:1px solid var(--accent);border-radius:12px;padding:14px 16px;margin:10px 0">']
    parts.append('<h3 style="margin:0 0 8px">出行查询指引 <span class="feat-badge">以官方实时为准</span></h3>')
    parts.append(f'<p style="font-size:13px;color:var(--sub);margin:0 0 10px">'
                 f'{links["from"]} → {links["to"]} · {links["date"]}</p>')

    rail = links.get("rail", {})
    if rail.get("from_status") == "ok" and rail.get("hint"):
        parts.append(f'<p style="margin:4px 0;font-size:13px">🚄 <b>铁路</b>：{rail["hint"]}</p>')
    if links.get("flight"):
        parts.append(f'<p style="margin:4px 0;font-size:13px">✈ <b>民航</b>：{links["flight"]["hint"]}</p>')

    parts.append(f'<p style="font-size:11.5px;color:var(--sub);margin:8px 0 0">'
                 f'{links["disclaimer"]}</p>')
    parts.append('</div>')
    return "\n".join(parts)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="交通查询引导（站名解析 + 官方渠道文字提示，零外链）")
    ap.add_argument("from_city", help="出发城市")
    ap.add_argument("to_city", help="到达城市")
    ap.add_argument("--date", default=None, help="出行日期 YYYY-MM-DD（默认明天）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--html", action="store_true", help="输出可嵌入 HTML 卡片")
    ap.add_argument("--no-flight", action="store_true", help="不含民航提示")
    args = ap.parse_args()

    links = generate(args.from_city, args.to_city, args.date, include_flight=not args.no_flight)

    if args.json:
        print(json.dumps(links, ensure_ascii=False, indent=2))
    elif args.html:
        print(render_html(links))
    else:
        print(f"{'=' * 60}")
        print(f"  {links['from']} → {links['to']}  {links['date']}")
        print(f"{'=' * 60}")
        print(f"\n  {links['rail']['hint']}")
        if links.get("flight"):
            print(f"\n  {links['flight']['hint']}")
        print(f"\n  {links['disclaimer']}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
