#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""户外行程天气可行性预检: 在推荐骑行/徒步/摩旅/自驾行程之前必须先跑这个。

用法:
  python check_weather.py --to 大理 --style cycling --days 3
  python check_weather.py --to 大理 丽江 --style moto --start 2026-10-10
  python check_weather.py --to 稻城亚丁 --style hiking --start 2026-10-10
  python check_weather.py --to 大理 --style cycling --route-file plan.json  # 用行程里的城市

## 为什么必须有这一步
户外行程对天气的敏感度远高于城市观光:
- 骑行: 雨天路滑、能见度低、洱海/湖边风大, 事故风险显著上升
- 徒步: 山地降雨易引发落石/滑坡/雷击, 低温度会失温
- 摩旅: 大风与降雨会严重影响操控, 夜间骑行风险成倍上升
- 自驾: 雨雪雾天高速管制、封路风险

**天气不达标就不应该推荐该行程**, 应改为:
  1. 改期(推荐, 找出未来 7-10 天的可行窗口)
  2. 换目的地(推荐同区域备选)
  3. 降级为室内/市区方案(亲子、恶劣天气时的兜底)

判定基于 Open-Meteo 官方 WMO 天气代码 + 温度阈值, 不做主观判断。
输出 verdict: ok / caution / not_recommended
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import refloader

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
API = "https://api.open-meteo.com/v1/forecast"
UA = "Mozilla/5.0 (compatible: ai-travel-guide/1.0)"

# WMO 天气代码 -> (中文描述, 类型)
# 类型: clear / cloud / rain / heavyrain / snow / storm / fog
WMO = {
    0: ("晴", "clear"), 1: ("大致晴朗", "clear"), 2: ("局部多云", "cloud"),
    3: ("阴", "cloud"),
    45: ("雾", "fog"), 48: ("雾凇", "fog"),
    51: ("毛毛雨", "rain"), 53: ("毛毛雨", "rain"), 55: ("强毛毛雨", "rain"),
    61: ("小雨", "rain"), 63: ("中雨", "rain"), 65: ("大雨", "heavyrain"),
    66: ("冻雨", "heavyrain"), 67: ("强冻雨", "heavyrain"),
    71: ("小雪", "snow"), 73: ("中雪", "snow"), 75: ("大雪", "snow"),
    77: ("雪粒", "snow"),
    80: ("阵雨", "rain"), 81: ("阵雨", "rain"), 82: ("强阵雨", "heavyrain"),
    85: ("阵雪", "snow"),
    86: ("强阵雪", "snow"),
    95: ("雷阵雨", "storm"), 96: ("雷阵雨伴冰雹", "storm"), 99: ("强雷暴伴冰雹", "storm"),
}

BAD_TYPES = {"heavyrain", "snow", "storm"}
RISKY_TYPES = {"rain", "fog"}


def load() -> list[dict]:
    return refloader.load("destinations.json")["destinations"]


def find(name: str, dests: list[dict]) -> dict | None:
    hits = [d for d in dests if d["name"] == name]
    if not hits:
        hits = [d for d in dests if name in d["name"] or d["name"] in name]
    return hits[0] if hits else None


def forecast(lat: float, lon: float, days: int) -> dict:
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Shanghai",
        "forecast_days": days,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


# 各画像的判定阈值
THRESHOLDS = {
    "cycling":    {"max_precip_mm": 5,  "max_pop": 60, "min_temp": 5, "max_wind": 35,
                   "note": "骑行: 降水与阵风影响操控与刹车"},
    "hiking":     {"max_precip_mm": 3,  "max_pop": 50, "min_temp": 3, "max_wind": 30,
                   "note": "徒步: 强降雨易引发落石滑坡雷击, 低温会失温"},
    "moto":       {"max_precip_mm": 3,  "max_pop": 50, "min_temp": 5, "max_wind": 30,
                   "note": "摩旅: 大风与降雨严重影响操控, 夜间骑行风险翻倍"},
    "roadtrip":   {"max_precip_mm": 12, "max_pop": 70, "min_temp": 0, "max_wind": 45,
                   "note": "自驾: 雨雪雾天高速管制、封路风险"},
    # 非户外画像仅作提示
    "commando":   {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "特种兵: 户外比重高, 雨天需调整为室内优先"},
    "family":     {"max_precip_mm": 25, "max_pop": 85, "min_temp": -2, "max_wind": 50,
                   "note": "亲子: 恶劣天气优先安排室内博物馆/亲子乐园"},
    # 扩展方式(国内全场景)
    "rv":         {"max_precip_mm": 15, "max_pop": 75, "min_temp": 0, "max_wind": 45,
                   "note": "房车: 重心高、侧风敏感, 雨雪天减速, 避开积水与软基营地"},
    "camping":    {"max_precip_mm": 8,  "max_pop": 70, "min_temp": 2, "max_wind": 35,
                   "note": "露营: 大风易掀帐、低温需保暖, 雷雨远离孤立树木与山脊"},
    "ski":        {"max_precip_mm": 10, "max_pop": 70, "min_temp": -10, "max_wind": 40,
                   "note": "滑雪: 低温大风索道停运, 注意雪盲与冻伤, 听从雪场管制"},
    "island":     {"max_precip_mm": 10, "max_pop": 70, "min_temp": 10, "max_wind": 35,
                   "note": "海岛: 看出海风浪与涌, 台风季禁出海, 潜水需平静水域"},
    "silver":     {"max_precip_mm": 25, "max_pop": 85, "min_temp": 5, "max_wind": 40,
                   "note": "银发: 低温与湿滑易跌倒, 优先室内, 避开陡坡与长台阶"},
    "ancient":    {"max_precip_mm": 20, "max_pop": 80, "min_temp": 3, "max_wind": 45,
                   "note": "古镇慢游: 雨天花巷别有韵味, 注意青石板与桥面湿滑"},
    "photo":      {"max_precip_mm": 15, "max_pop": 75, "min_temp": 0, "max_wind": 40,
                   "note": "摄影: 雨雪天有独特光影, 注意器材防雨与低温掉电"},
    "study":      {"max_precip_mm": 20, "max_pop": 80, "min_temp": 3, "max_wind": 45,
                   "note": "研学: 户外课时看天, 备室内备选与讲解视频"},
    "budget":     {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "穷游: 户外比重大, 雨天优先室内展馆与夜市"},
    "rail":       {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "高铁周边: 室内外皆宜, 雨天转室内展馆与商圈"},
    # 非户外方式(仅作提示, 可走 indoor_rewrite 兜底)
    "leisure":    {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "休闲: 户外比重低, 雨天转室内或就近慢逛"},
    "resort":     {"max_precip_mm": 25, "max_pop": 85, "min_temp": 0, "max_wind": 50,
                   "note": "度假: 以度假村活动为主, 恶劣天气室内设施兜底"},
    "honeymoon":  {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "蜜月: 雨天改室内SPA/私厨, 保留仪式感"},
    "couple":     {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "情侣: 雨天转室内展览/咖啡馆, 保留二人时段"},
    "friends":    {"max_precip_mm": 20, "max_pop": 80, "min_temp": 0, "max_wind": 50,
                   "note": "朋友: 雨天转室内聚餐/桌游, 晚上仍是主场"},
    # v0.0.3: 极限玩法 + 自然美景专线(阈值最严)
    "extreme":    {"max_precip_mm": 2,  "max_pop": 40, "min_temp": 5, "max_wind": 25,
                   "note": "极限运动: 天气窗口即生命线——冲浪/跳伞/滑索对风与降水的容忍度极低, 预检不达标直接改期, 不存在「硬上」"},
    "nature":     {"max_precip_mm": 4,  "max_pop": 50, "min_temp": 3, "max_wind": 32,
                   "note": "自然美景专线: 晨雾与光线依赖天气; 摩旅/自驾段看风与能见度, 徒步段看降水(塌方/落石)"},
}


def assess(city: str, style: str, days: int, data: dict) -> dict:
    """对单个城市的预报做适宜度判定。"""
    th = THRESHOLDS.get(style, THRESHOLDS["roadtrip"])
    daily = data.get("daily", {})
    times = daily.get("time", [])

    issues: list[dict] = []
    good_days: list[str] = []
    detail: list[dict] = []

    for i, day in enumerate(times):
        code = daily["weather_code"][i]
        desc, kind = WMO.get(code, (f"代码{code}", "cloud"))
        tmax = daily["temperature_2m_max"][i]
        tmin = daily["temperature_2m_min"][i]
        rain = daily.get("precipitation_sum", [0] * len(times))[i] or 0
        pop = (daily.get("precipitation_probability_max") or [None] * len(times))[i]
        wind = (daily.get("wind_speed_10m_max") or [None] * len(times))[i]

        flags = []
        if kind in BAD_TYPES:
            flags.append(("danger", f"{desc}"))
        elif kind in RISKY_TYPES:
            flags.append(("risk", f"{desc}"))
        if rain > th["max_precip_mm"]:
            flags.append(("danger" if rain > th["max_precip_mm"] * 2 else "risk",
                          f"降水 {rain}mm"))
        if pop is not None and pop > th["max_pop"]:
            flags.append(("risk", f"降水概率 {pop}%"))
        if tmin < th["min_temp"]:
            flags.append(("danger", f"最低温 {tmin}°C 偏低"))
        if wind is not None and wind > th["max_wind"]:
            flags.append(("danger" if wind > th["max_wind"] * 1.3 else "risk",
                          f"最大风速 {wind}km/h"))

        detail.append({
            "date": day, "desc": desc, "kind": kind,
            "tmin": tmin, "tmax": tmax, "rain": rain, "pop": pop, "wind": wind,
            "flags": flags,
        })
        if not flags:
            good_days.append(day)
        for level, msg in flags:
            issues.append({"date": day, "level": level, "msg": msg})

    # 综合判定
    danger_n = sum(1 for x in issues if x["level"] == "danger")
    risk_n = sum(1 for x in issues if x["level"] == "risk")
    ratio_danger = danger_n / max(len(times), 1)

    if not good_days or ratio_danger >= 0.5:
        verdict = "not_recommended"
    elif risk_n or ratio_danger > 0:
        verdict = "caution"
    else:
        verdict = "ok"

    # 亲子/休闲/度假: 户外权重低, 恶劣天气可转室内替代, 故不直接判死刑。
    # 这些画像即使天气差, 行程仍可成立 —— 只需把户外时段换成室内。
    indoor_friendly = style in (
        "family", "leisure", "resort", "couple", "honeymoon",
        "silver", "ancient", "study", "rail", "budget", "photo",
    )
    if verdict == "not_recommended" and indoor_friendly:
        verdict = "indoor_rewrite"

    return {
        "city": city, "verdict": verdict,
        "good_days": good_days, "issues": issues,
        "detail": detail, "threshold_note": th["note"],
        "threshold": th,
        "indoor_friendly": indoor_friendly,
        "source": "Open-Meteo",
    }


VERDICT_CN = {
    "ok": "适宜",
    "caution": "需谨慎",
    "not_recommended": "不建议",
    "indoor_rewrite": "需改为室内方案",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="户外行程天气可行性预检")
    ap.add_argument("--to", nargs="+", required=True, help="目的地(可多个, 沿线都查)")
    ap.add_argument("--style", required=True,
                    help="cycling/hiking/moto/roadtrip/commando/family/rv/camping/ski/island/silver/ancient/photo/study/budget/rail")
    ap.add_argument("--start", help="出发日期 YYYY-MM-DD(当前接口只支持 16 天内)")
    ap.add_argument("--days", type=int, default=3, help="检查天数, 默认 3")
    ap.add_argument("--route-file", help="从 plan.json 读取目的地列表")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.style not in THRESHOLDS:
        print(f"错误: --style 须为 {'/'.join(THRESHOLDS)}", file=sys.stderr)
        return 1

    cities = list(args.to)
    if args.route_file:
        plan = json.load(open(args.route_file, encoding="utf-8"))
        cities = plan.get("destinations", cities)

    dests = load()
    results = []
    for c in cities:
        d = find(c, dests)
        if not d:
            print(f"跳过「{c}」: 不在目的地库中", file=sys.stderr)
            continue
        if d.get("lat") is None:
            print(f"跳过「{c}」: 库中无坐标, 无法查询天气(该地名地理编码不可靠, 留空是正确行为)",
                  file=sys.stderr)
            print(f"  变通: 可用 fetch_weather.py 手动指定 --lat/--lon 查询", file=sys.stderr)
            continue
        try:
            data = forecast(d["lat"], d["lon"], max(3, min(16, args.days)))
        except Exception as e:
            print(f"跳过「{c}」: 天气查询失败 {e}", file=sys.stderr)
            continue
        r = assess(c, args.style, args.days, data)
        r["admin1"] = d.get("admin1", "")
        r["lat"], r["lon"] = d["lat"], d["lon"]
        results.append(r)
        time.sleep(0.4)

    if not results:
        print("无有效结果。", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"style": args.style, "results": results},
                         ensure_ascii=False, indent=2))
        return 0

    th = results[0]["threshold"]
    print(f"═══ 户外天气可行性预检 · {args.style} ═══")
    print(f"阈值: 降水≤{th['max_precip_mm']}mm 概率≤{th['max_pop']}% "
          f"最低温≥{th['min_temp']}°C 风速≤{th['max_wind']}km/h")
    print(f"说明: {th['note']}\n")

    overall = "ok"
    for r in results:
        v = r["verdict"]
        print(f"── {r['city']}（{r.get('admin1','')}）→ 【{VERDICT_CN[v]}】")
        for x in r["detail"]:
            mark = "✅" if not x["flags"] else (
                "⛔" if any(lv == "danger" for lv, _ in x["flags"]) else "⚠️")
            extra = "  ".join(f"[{m}]" for _, m in x["flags"])
            print(f"   {mark} {x['date']}  {x['desc']}  {x['tmin']}~{x['tmax']}°C"
                  f"  降水{x['rain']}mm/{x['pop']}%  风{x['wind']}km/h  {extra}")
        if r["good_days"]:
            print(f"   可用日: {', '.join(r['good_days'])}")
        else:
            print("   可用日: 无 —— 该天气下不走户外线路")
        print()
        rank = {"ok": 0, "caution": 1, "indoor_rewrite": 2, "not_recommended": 3}
        if rank[v] > rank[overall]:
            overall = v

    print("═" * 62)
    if overall == "not_recommended":
        print("⛔ 结论: 当前天气不适宜该户外行程。**不要直接推荐原方案**。")
        print()
        print("给用户的替代方案（按优先级）:")
        print("  1. 改期—— 上方「可用日」为空说明近期都不可行, 建议改到天气转好后")
        print("     的时间窗口, 或换季节（查得更远可用 --days 10~16）")
        print("  2. 换目的地 —— 推荐同区域备选, 重新跑本预检确认")
        print("  3. 降级方案 —— 改为室内/市区:")
        print("     · 博物馆/美术馆/科技馆/自然博物馆")
        print("     · 古镇与历史街区室内段（雨天别撑伞, 挤人力少）")
        print("     · 温泉/商场/室内亲子乐园/手作工坊")
        print()
        print("若用户坚持出行, 必须明确告知风险与安全边界:")
        print("  · 降雨山路不徒步（落石/滑坡/雷击）; 骑行减速、避开积水路段")
        print("  · 雷电天气不在海边/湖边/山脊/树下停留, 立即进室内")
        print("  · 低温+雨= 失温风险, 备防水保暖层与热水")
        print("  · 摩旅/骑行遇大雨积水不要硬通过, 宁可等待或掉头")
    elif overall == "indoor_rewrite":
        print("⚠️ 结论: 户外段天气不佳, 但行程可成立 —— 需把户外时段改为室内。")
        print()
        print("改写方式（不改变总天数与住宿）:")
        print("  · 把古城/古镇/公园等户外段 → 博物馆、美术馆、老字号店铺、文创园")
        print("  · 亲子: 科技馆/自然博物馆/室内亲子乐园/手作DIY/游泳馆")
        print("  · 把最好的天气日留给必须户外的项目（如需看日出的观景点）")
        print("  · 备雨具与防水袋, 鞋子选防水或可替换的")
        print("  · 报告里必须明确标注「本行程含室内替代方案」")
    elif overall == "caution":
        print("⚠️ 结论: 可出行但有风险日。必须在报告中标注风险日并给出应对。")
        print("  应对: 备雨具/防水袋、减少当日里程、避开强风时段、")
        print("        徒步遇雷雨立即下撤、不要在海边/湖边/山脊逗留。")
    else:
        print("✅ 结论: 天气适宜, 可按计划推进。仍需备基础防护(防晒/雨具/水壶)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
