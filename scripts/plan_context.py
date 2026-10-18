#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""季节感知 + 自驾动力类型规划: 让建议贴合「实际出行时间 + 具体车辆」。

用法:
  python plan_context.py --to 大理 --date 2026-07-15
  python plan_context.py --to 丽江 --date 2026-10-01 --car ev
  python plan_context.py --to 张家界 --date 2026-08-10 --car fuel --drive 380
  python plan_context.py --to 三亚 --date 2026-01-20 --json

## 为什么需要这个
「带雨伞、穿外套」是废话式推荐。真正有用的是:
  - 7月中旬去大理: 雨季, 每天可能阵雨, 骑行几乎不可行, 稻田是绿的不是金的
  - 10月初去丽江: 雨季刚过, 是全年最舒服的窗口, 但紫外线仍强
  - 8月去张家界: 旺季+高温, 门票要提前抢, 山上比山下低 5-6 度
  - 1月去黄山: 寒潮, 索道可能因大风停运, 必须查
  - 电车 vs 油车: 完全不同 —— 电车不能上高海拔烂路、爬坡耗电翻倍、
    山区充电桩少; 油车要算加油站间距

本脚本输出**可操作**的结论, 不是泛泛的提醒。
"""
import argparse
import json
import sys
from datetime import date, datetime

# ── 季节画像: 按月份给不同地区的气候与专属建议 ──
# key = (月份, 区域归类); 区域归类见 region_of()
SEASON = {
    # 南方/西南
    "south": {
        1: ("深冬", "温和少雨, 12-18°C", ["穿薄羽绒或厚外套", "湿冷, 备除湿或暖风机", "元旦春节人多, 住宿提前 3 周"]),
        2: ("早春", "乍暖还寒, 10-18°C", ["外套+内搭, 洋葱式穿法", "仍需保暖", "春节高峰, 避开初一到初五"]),
        3: ("暮春", "舒适, 15-25°C", ["薄长袖+薄外套", "开始多雨, 备伞", "油菜花/桃花季(部分目的地)"]),
        4: ("暮春", "舒适, 18-27°C", ["薄长袖", "阵雨增多", "清明人多"]),
        5: ("初夏", "25-32°C, 进入雨季前", ["短袖+薄外套(室内空调)", "紫外线开始强", "五一高峰"]),
        6: ("入梅", "雨季开始, 22-30°C, 湿度高", ["雨具必带", "鞋子选防水或可替换", "山区注意落石/滑坡"]),
        7: ("盛夏雨季", "28-35°C, 雷雨频繁", ["防晒+雨具双备", "午后雷雨, 户外活动放上午", "地质灾害风险高, 徒步/骑行慎选"]),
        8: ("盛夏雨季", "28-36°C, 高温高湿", ["防暑: 冰袖/盐丸/电解质水", "午后暴雨, 骑行/徒步建议改室内", "台风季, 出发前查台风路径"]),
        9: ("初秋", "雨季尾声, 26-32°C, 天气转稳", ["仍需雨具但可减量", "体感最舒适月份之一", "国庆高峰, 提前订房"]),
        10: ("深秋", "20-28°C, 干燥晴朗", ["薄外套", "紫外线仍强(秋老虎)", "国庆高峰, 机票住宿最贵"]),
        11: ("初冬", "12-22°C, 干爽", ["夹克+毛衣", "昼夜温差大", "红叶季(部分山地)"]),
        12: ("深冬", "8-18°C, 少雨", ["厚外套/薄羽绒", "部分高海拔景点可能结冰", "元旦前预订"]),
    },
    # 北方
    "north": {
        1: ("严冬", "-15~0°C, 干燥寒冷", ["羽绒服+保暖内衣", "防滑鞋(结冰)", "室内外温差大, 备润唇膏"]),
        2: ("严冬", "-12~2°C", ["羽绒服", "围巾手套", "春节高峰"]),
        3: ("早春", "-2~12°C, 干燥多风", ["夹克+卫衣", "风大, 戴帽子防风", "沙尘季(北方)"]),
        4: ("暮春", "8-22°C, 舒适", ["薄外套+长袖", "风大, 骑车注意侧风", "花粉季"]),
        5: ("初夏", "16-28°C", ["短袖+薄外套", "紫外线强", "五一高峰"]),
        6: ("初夏", "20-31°C", ["短袖", "午后雷阵雨", "蚊虫开始多"]),
        7: ("盛夏", "24-35°C, 雨季", ["防晒必做", "雨具", "华北暴雨洪涝期, 山区慎行"]),
        8: ("盛夏", "23-34°C", ["防暑装备", "午后雷雨", "雨量最大月份, 徒步/骑行常受影响"]),
        9: ("初秋", "16-28°C, 最佳", ["薄外套", "天气最舒适", "国庆高峰"]),
        10: ("深秋", "8-20°C", ["夹克/薄羽绒", "干燥", "红叶季(香山/坝上等)"]),
        11: ("初冬", "0-12°C", ["厚外套", "初霜, 北方路面可能结冰", "日出晚, 注意时间"]),
        12: ("严冬", "-10~2°C", ["羽绒服", "防滑鞋", "元旦前预订"]),
    },
    # 高海拔/西部（西藏、川西、云贵）
    "plateau": {
        1: ("严冬", "夜间可至-15°C, 白天强日照", ["羽绒服+抓绒内胆", "高原紫外线极强, 防晒SPF50+", "夜间保暖优先"]),
        2: ("严冬", "风大, 干燥", ["防风层", "护唇膏", "部分垭口可能封路"]),
        3: ("早春", "昼夜温差极大", ["洋葱式穿法", "早晚冰雹/雪", "高海拔道路结冰"]),
        4: ("暮春", "10-24°C, 最舒适", ["薄羽绒+长袖", "紫外线强", "杜鹃花期(林芝)"]),
        5: ("初夏", "8-26°C, 最佳", ["薄外套+短袖组合", "紫外线极强", "雨季未到, 徒步最佳窗口"]),
        6: ("入雨季", "10-24°C, 午后雷雨", ["雨具", "山路注意落石", "云雾多, 能见度差"]),
        7: ("雨季", "11-23°C, 降雨最多", ["防水外套+雨具", "滑坡泥石流高发", "自驾注意路况, 徒步慎选"]),
        8: ("雨季", "11-24°C", ["同上", "部分垭口可能塌方", "部分景区临时关闭"]),
        9: ("初秋", "9-22°C, 最佳", ["薄羽绒", "紫外线仍强", "雨季结束, 能见度高"]),
        10: ("深秋", "3-18°C, 昼夜温差大", ["厚外套+内胆", "早霜", "国庆人多但气候好"]),
        11: ("初冬", "-2-14°C", ["羽绒服+抓绒", "干燥, 风大", "部分高海拔口可能封"]),
        12: ("严冬", "-8-12°C", ["羽绒服", "强日照+极低温并存", "避免高海拔夜间出行"]),
    },
    # 西南: 城区海拔 1500-2400m，气候温和但昼夜温差大、雨季分明
    "southwest": {
        1: ("凉冬", "8-20°C, 干爽晴朗", ["薄羽绒或厚外套+毛衣", "昼夜温差大, 洋葱式穿法", "紫外线强(海拔高)"]),
        2: ("凉冬", "10-22°C, 阳光好", ["外套+内搭", "干燥, 防晒不能省", "春节高峰"]),
        3: ("暮春", "14-25°C, 舒适", ["薄外套+长袖", "开始有阵雨", "紫外线开始强"]),
        4: ("暮春", "16-27°C, 最舒适", ["薄长袖+薄外套", "防晒", "清明人多"]),
        5: ("初夏", "18-28°C, 雨季未到", ["短袖+薄外套", "紫外线强", "五一高峰"]),
        6: ("入雨季", "18-27°C, 开始下雨", ["雨具", "山路注意落石", "云雾多"]),
        7: ("雨季", "17-25°C, 降雨最多", ["雨具+防水外套", "午后雷雨多, 户外放上午", "骑行/徒步常受影响"]),
        8: ("雨季", "17-25°C, 雨量最大", ["同上", "地质灾害风险高", "部分景区临时关闭"]),
        9: ("初秋", "17-26°C, 雨季结束", ["薄外套", "能见度高, 天气最舒服", "国庆高峰"]),
        10: ("深秋", "14-24°C, 干爽", ["外套+毛衣", "秋老虎, 紫外线仍强", "稻田金黄期(大理等地)"]),
        11: ("初冬", "8-20°C", ["夹克+毛衣", "干燥", "红叶/银杏期"]),
        12: ("凉冬", "6-18°C", ["薄羽绒", "昼夜温差大", "元旦前预订"]),
    },
    # 海南/华南沿海
    "tropical": {
        1: ("凉季", "18-25°C, 最舒服", ["薄长袖+薄外套", "避寒首选季, 房价旺季", "春节高峰"]),
        2: ("凉季", "19-26°C", ["薄外套", "天气好", "春节高峰"]),
        3: ("暮春", "22-30°C, 回南天", ["短袖", "潮湿, 备除湿", "回南天墙面潮湿"]),
        4: ("暮春", "25-32°C", ["短袖", "紫外线强", "五一高峰"]),
        5: ("初夏", "27-33°C, 酷热", ["防晒必做", "午后雷雨", "台风季开始"]),
        6: ("湿热", "28-34°C", ["速干衣", "防霉", "雷雨频繁"]),
        7: ("盛夏", "28-35°C, 台风季", ["防晒", "台风预警查航班/轮渡", "遇台风海上项目全停"]),
        8: ("盛夏", "28-35°C, 台风高发", ["同上", "台风季最需警惕", "遇台风立即改室内"]),
        9: ("初秋", "27-33°C, 台风尾", ["防晒+雨具", "仍需防台风", "国庆高峰"]),
        10: ("深秋", "25-31°C", ["短袖+薄外套", "天气转好", "国庆高峰"]),
        11: ("凉季", "22-28°C, 最佳", ["薄长袖", "避寒旺季", "房价上涨"]),
        12: ("凉季", "20-26°C, 最佳", ["薄外套", "冬泳季", "元旦前预订"]),
    },
}

# 区域归类
REGION_KIND = {
    "华北": "north", "东北": "north",
    "华东": "south", "华中": "south", "华南": "tropical",
    "西南": "plateau", "西北": "plateau",
    "港澳台": "tropical", "海外": "tropical", "主题乐园": "south",
}
# 真正的高寒高海拔目的地(海拔 2500m 以上, 需按高原工况)
# 注意: 玉龙雪山/苍山/九寨沟等是"景区高海拔但城区温和",
# 与拉萨/香格里拉这类"整城高海拔"不同, 故不列入。
TRUE_PLATEAU = {
    "拉萨", "香格里拉", "色达", "稻城亚丁", "四姑娘山", "若尔盖", "理塘",
    "芒康", "新都桥", "塔公", "丹巴", "甘孜", "阿坝", "凉山西昌", "毕棚沟",
    "日喀则", "林芝", "阿里", "昌都", "林周", "羊湖", "纳木错",
}

# 城区温和、但核心玩法在「高海拔景区」的目的地(电车爬坡耗电/限行风险显著)。
# 用户在城区落脚、上山玩, 电车工况应按高海拔处理, 否则告警与能耗都偏乐观。
HIGH_ALT_SCENIC = {
    "玉龙雪山", "苍山", "梅里雪山", "飞来寺", "虎跳峡", "峨眉山", "黄山", "泰山",
    "华山", "武当山", "武夷山", "庐山", "梵净山", "青城山", "龙脊梯田", "贡嘎",
    "牛背山", "达古冰川", "西岭雪山", "长白山", "恒山", "嵩山", "衡山", "九华山",
    "普达措", "老君山", "玉龙", "梅里",
}


def region_kind(city: str, region: str) -> str:
    # 整城位于高原 → 按高原工况
    if city in TRUE_PLATEAU:
        return "plateau"
    # 西南其余地区(大理/丽江城区等)海拔 1500-2400, 气候温和,
    # 按 southern 夏季多雨处理更准确, 单独建一档
    if region == "西南":
        return "southwest"
    return REGION_KIND.get(region, "south")


# ── 自驾动力类型 ──
CAR_SPECS = {
    "ev": {
        "name": "纯电车",
        "energy_label": "电费",
        "consume": 0.18,          # kWh/km（含山路与空调，取中国工况常见值）
        "unit_price": 1.25,      # 元/kWh（家充/服务区均价）
        "reserve_pct": 20,       # 保留电量
        "highland_penalty": 1.9, # 高海拔爬坡耗电倍数
        "weaknesses": [
            "低电量状态下动力受限, 爬坡可能「哑车」",
            "高海拔+低温会显著掉电(冬季可能 -30%)",
            "山区充电桩少, 节假日高速充电排队严重",
            "部分高海拔/烂路景区道路新能源车限行或劝退",
            "涉水路段(溪流/涉水路面)严禁, 保险不赔",
        ],
        "route_rules": [
            "山区路段提前规划补能点, 充电桩间距 > 60km 一律先充再走",
            "不要指望景区停车场有桩, 到达前先查App 附近充电站",
            "爬坡前把电耗到 70% 以下, 出弯道时预留 20% 缓冲",
            "冬季低温自动预热会耗电, 上高速前先预热再走",
        ],
    },
    "phev": {
        "name": "插混/增程",
        "energy_label": "电费+油费",
        "consume": 0.10,
        "unit_price": 1.25,
        "reserve_pct": 15,
        "highland_penalty": 1.6,
        "weaknesses": [
            "亏电状态下油耗会飙到 8-10L/100km(比油车还高)",
            "高原亏电风险大, 爬坡时发动机介入是常态",
            "冬季纯电续航缩水明显",
        ],
        "route_rules": [
            "当油车用最省心: 保持 SOC>50% 再进山",
            "满油+满电出发, 山里找桩比找加油站难得多",
            "不要指望亏电状态爬长坡, 提前保底",
        ],
    },
    "fuel": {
        "name": "燃油车",
        "energy_label": "油费",
        "consume": 0.085,         # L/km（约8.5L/100km）
        "unit_price": 7.9,        # 元/L（92号均价）
        "reserve_pct": 0,
        "highland_penalty": 1.25, # 爬坡油耗增加
        "weaknesses": [
            "高海拔爬坡动力衰减(涡轮迟滞), 超车要提前",
            "山区加油站间距大, 部分乡镇无92号只有95号",
            "长途连续驾驶疲劳, 每2 小时必须休息",
            "部分景区环保要求(老旧车可能限入)",
        ],
        "route_rules": [
            "山区油箱剩余半箱就补, 不要等亮灯",
            "上坡用低挡位发动机控速, 不要高挡位硬顶(省油且护变速箱)",
            "提前查沿途加油站位置(地图服务/备用地图服务「加油站」图层)",
            "每 2 小时或 200km 休息 15 分钟, 山区夜间不赶路",
        ],
    },
    "hybrid": {
        "name": "油电混动",
        "energy_label": "油费为主",
        "consume": 0.055,
        "unit_price": 7.9,
        "reserve_pct": 0,
        "highland_penalty": 1.2,
        "weaknesses": [
            "高原低氧下动力电机效率下降, 综合油耗上升",
            "冬季热效率低, 短途更费油",
        ],
        "route_rules": [
            "混动在平原最省, 山路优势减小, 按油车的一半油量预留即可",
            "避免长时间怠速(景区排队/堵车), 关窗开空调更省",
        ],
    },
}


def build(cities: list[str], regions: dict, trip_date: str | None,
          car: str, drive_km: float, plate: str) -> dict:
    out: dict = {"date": trip_date, "car": car, "drive_km": drive_km,
                 "cities": {}, "warnings": []}

    if not trip_date:
        out["date"] = None
        out["season"] = None
        out["warnings"].append("未提供出行日期 —— 装备与建议无法贴合实际时令, "
                              "请补充日期后重新生成, 否则推荐是泛化的。")
    else:
        try:
            d = datetime.strptime(trip_date, "%Y-%m-%d").date()
            m = d.month
        except ValueError:
            out["warnings"].append(f"日期格式错误: {trip_date}, 应为 YYYY-MM-DD")
            d, m = None, date.today().month
        if d:
            for c in cities:
                kind = region_kind(c, regions.get(c, ""))
                label, climate, tips = SEASON[kind][m]
                out["cities"][c] = {
                    "kind": kind, "month": m, "season": label,
                    "climate": climate, "tips": tips,
                }

    # 节假日提示
    if trip_date:
        try:
            d = datetime.strptime(trip_date, "%Y-%m-%d").date()
            md = (d.month, d.day)
            if md in ((1, 1), (5, 1), (10, 1), (10, 2), (10, 3)):
                out["warnings"].append(f"{d.month}月{d.day}日 前后为法定假期高峰，"
                                       "住宿与机票价格上浮 50-200%，热门景点需提前 3-7 天抢票。")
            # 暑期高峰
            if 7 <= d.month <= 8 and d.day >= 10:
                out["warnings"].append("处于暑期高峰，景区人流最大，"
                                       "建议避开 11:00-15:00 高峰时段，住宿提前 2 周订。")
        except ValueError:
            pass

    # 自驾部分
    if car in CAR_SPECS and drive_km > 0:
        spec = CAR_SPECS[car]
        highland = (any(out["cities"].get(c, {}).get("kind") == "plateau" for c in cities)
                    or any(c in HIGH_ALT_SCENIC for c in cities))
        penalty = spec["highland_penalty"] if highland else 1.0
        if car in ("ev", "phev"):
            energy = drive_km * spec["consume"] * penalty
            cost = energy * spec["unit_price"]
            energy_txt = f"约 {energy:.0f} kWh"
            if highland:
                cost *= 1.0
                energy_txt += "(已按高海拔系数上浮)"
        else:
            energy = drive_km * spec["consume"] * penalty
            cost = energy * spec["unit_price"]
            energy_txt = f"约 {energy:.0f} L"
        out["drive"] = {
            "car_name": spec["name"],
            "energy": energy_txt,
            "cost": round(cost),
            "per_km": round(cost / drive_km, 2),
            "highland_adjusted": highland,
            "weaknesses": spec["weaknesses"],
            "route_rules": spec["route_rules"],
        }
        if highland and car in ("ev",):
            out["warnings"].append(
                f"目的地含高海拔区域，纯电车需特别注意：爬坡耗电约为平地的 "
                f"{spec['highland_penalty']} 倍，且山区充电桩密度低，"
                f"建议每次行驶控制在 {int(60)} km 内就补能，或改用插混/燃油。")
        if not car and drive_km > 600:
            out["warnings"].append("未指定动力类型。电车与油车的补能逻辑完全不同，"
                                  "请补充 --car ev/fuel/phev/hybrid 以获得准确建议。")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="季节感知与自驾动力规划")
    ap.add_argument("--to", nargs="+", required=True, help="目的地")
    ap.add_argument("--date", help="出行日期 YYYY-MM-DD")
    ap.add_argument("--car", default="", choices=["", "ev", "phev", "fuel", "hybrid"])
    ap.add_argument("--drive", type=float, default=0, help="总驾驶里程 km")
    ap.add_argument("--region", nargs="*", default=[], help="格式: 城市=区域")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    regions = {}
    for kv in args.region:
        if "=" in kv:
            k, v = kv.split("=", 1)
            regions[k] = v
    if not regions:
        try:
            DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
            for d in json.load(open(DATA, encoding="utf-8"))["destinations"]:
                regions[d["name"]] = d.get("region", "")
        except Exception:
            pass

    r = build(args.to, regions, args.date, args.car, args.drive, args.car)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print("═══ 出行上下文 ═══\n")
    if r.get("date"):
        print(f"出行日期: {r['date']}")
        for c, v in r["cities"].items():
            print(f"\n── {c} · {v['season']}（{v['climate']}）")
            for t in v["tips"]:
                print(f"   · {t}")
    else:
        print(r["warnings"][0] if r["warnings"] else "未提供日期")

    if "drive" in r:
        d = r["drive"]
        print(f"\n═══ 自驾 · {d['car_name']} ═══")
        print(f"总里程 {args.drive} km │ 预估能耗 {d['energy']} │ "
              f"费用约 ¥{d['cost']}（¥{d['per_km']}/km）")
        if d["highland_adjusted"]:
            print("⚡ 已按高海拔工况上浮")
        print("\n需要注意的短板:")
        for w in d["weaknesses"]:
            print(f"   ! {w}")
        print("\n路线与补能策略:")
        for rr in d["route_rules"]:
            print(f"   → {rr}")

    extra = [w for w in r["warnings"] if "日期" not in w]
    if extra:
        print("\n═══ 重要提醒 ═══")
        for w in extra:
            print(f"   ⚠️  {w}")
    return 0


if __name__ == "__main__":
    from pathlib import Path
    sys.exit(main())
