#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城际交通比选: 高铁 / 普铁 / 客车 / 轮船 / 自驾 / 飞机 六方式估算与推荐。

用法:
  python plan_transit.py --from 北京 --to 上海
  python plan_transit.py --from 岳阳 --to 张家界 --json

设计原则 (小册子版, 侧重短途近程):
  - ≤30km 市内圈: 同城/市内出行, 只推公交/地铁/出租/网约车(短驳骑行/步行), 不推城际高铁/飞机/普铁。
  - 30-150km 近程圈: 近郊/周边县市, 当天来回为主; 优先自驾/班车, 高铁仅当「通高铁且≥50km」才值得, 不默认推高铁飞机。
  - ≤300km 短途圈: 1-3 天行程, 高铁 1.5h 圈首选。
  - 客车覆盖县域/乡镇/景区「最后一公里」; 轮船适用跨海岛与观光水域。
  - 自驾自由度最高, 成本=油费+过路费+停车。
  - 机票仅 1200km+ 或无地面直达时纳入比选。
  - 坐标缺失(通常是同城/市内地点)时, 不默认推荐高铁/飞机, 而是提示先向用户确认「市内 or 跨城」。

注意: 所有票价/时长均为「基于距离的估算」, 非实时数据。
实时余票、票价、折扣请查 12306 App/官网、当地客运站/港口官方公众号。
"""
import argparse
import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
RULES = Path(__file__).resolve().parent.parent / "references" / "transit_rules.json"


def load_dest() -> list[dict]:
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)["destinations"]


# 主要枢纽城市坐标兜底: destinations.json 个别条目缺经纬度时仍可比选
HUB_COORDS = {
    "北京": (39.9075, 116.3972), "上海": (31.2304, 121.4737), "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579), "成都": (30.5728, 104.0668), "杭州": (30.2741, 120.1551),
    "西安": (34.3416, 108.9398), "武汉": (30.5928, 114.3055), "重庆": (29.5630, 106.5516),
    "昆明": (24.8801, 102.8329), "南京": (32.0603, 118.7969), "天津": (39.3434, 117.3616),
    "长沙": (28.2282, 112.9388), "郑州": (34.7466, 113.6254), "哈尔滨": (45.8038, 126.5350),
    "沈阳": (41.8057, 123.4315), "济南": (36.6512, 117.1201), "青岛": (36.0671, 120.3826),
    "厦门": (24.4798, 118.0894), "福州": (26.0745, 119.2965), "海口": (20.0440, 110.1999),
    "贵阳": (26.6470, 106.6302), "兰州": (36.0611, 103.8343), "西宁": (36.6171, 101.7782),
    "乌鲁木齐": (43.8256, 87.6168), "拉萨": (29.6520, 91.1721), "呼和浩特": (40.8426, 111.7492),
    "南宁": (22.8170, 108.3665), "桂林": (25.2736, 110.2990), "三亚": (18.2528, 109.5119),
    "石家庄": (38.0428, 114.5149), "太原": (37.8706, 112.5489), "合肥": (31.8206, 117.2272),
    "南昌": (28.6829, 115.8579), "长春": (43.8171, 125.3235), "大连": (38.9140, 121.6147),
    "宁波": (29.8683, 121.5440), "温州": (28.0000, 120.7000), "珠海": (22.2710, 113.5760),
    "丽江": (26.8721, 100.2299), "大理": (25.6065, 100.2676), "拉萨": (29.6520, 91.1721),
    # 短途近程常用城市补充(湖南/华中/长三角/珠三角/环京周边等)
    "岳阳": (29.3563, 113.1290), "常德": (29.0405, 111.6987), "益阳": (28.5530, 112.3550),
    "湘潭": (27.8297, 112.9394), "株洲": (27.8274, 113.1340), "怀化": (27.5501, 110.0338),
    "吉首": (28.2624, 109.7390), "凤凰": (27.9482, 109.5995), "永州": (26.4345, 111.6132),
    "邵阳": (27.2386, 111.2734), "衡阳": (26.8935, 112.5719), "郴州": (25.7937, 113.0320),
    "娄底": (27.7006, 111.9944), "韶山": (27.9150, 112.5266), "宜昌": (30.6920, 111.2860),
    "襄阳": (32.0090, 112.1220), "十堰": (32.6476, 110.7877), "恩施": (30.2720, 109.4880),
    "咸宁": (29.8413, 114.3220), "九江": (29.7050, 116.0000), "景德镇": (29.2687, 117.1784),
    "上饶": (28.4553, 117.9430), "宜春": (27.8043, 114.4160), "萍乡": (27.6229, 113.8545),
    "嘉兴": (30.7539, 120.7558), "绍兴": (30.0300, 120.5800), "湖州": (30.8671, 120.0933),
    "无锡": (31.4912, 120.3119), "苏州": (31.2990, 120.5853), "常州": (31.8107, 119.9741),
    "镇江": (32.1884, 119.4250), "扬州": (32.3947, 119.4127), "泰州": (32.4553, 119.9230),
    "南通": (31.9802, 120.8943), "芜湖": (31.3345, 118.4326), "黄山": (29.7147, 118.3376),
    "佛山": (23.0218, 113.1219), "东莞": (23.0207, 113.7518), "惠州": (23.1115, 114.4161),
    "潮州": (23.6567, 116.6226), "汕头": (23.3540, 116.6820), "清远": (23.6820, 113.0560),
    "肇庆": (23.0470, 112.4654), "中山": (22.5150, 113.3926), "江门": (22.5789, 113.0815),
    "阳江": (21.8580, 111.9821), "茂名": (21.6627, 110.9254), "承德": (40.9762, 117.9634),
    "保定": (38.8740, 115.4650), "张家口": (40.8242, 114.8875), "秦皇岛": (39.9354, 119.5980),
    "包头": (40.6572, 109.8403), "鄂尔多斯": (39.6086, 109.7811), "赤峰": (42.2577, 118.8895),
    "洛阳": (34.6197, 112.4542), "开封": (34.7972, 114.3074), "徐州": (34.2044, 117.2857),
    "绵阳": (31.4680, 104.6796), "乐山": (29.5522, 103.7660), "雅安": (30.0104, 103.0013),
    "都江堰": (31.0049, 103.6657), "西昌": (27.9078, 102.2588), "遵义务川": (28.0000, 108.0000),
    "遵义": (27.7255, 106.9270), "安顺": (26.2333, 105.9460), "凯里": (26.5836, 107.9850),
    # 极限运动与自然美景基地补充
    "万宁": (18.7952, 110.3894), "陵水": (18.5051, 109.9280), "琼海": (19.2581, 110.4747),
    "崇礼": (40.9742, 115.2782), "阿勒泰": (47.8484, 88.1405), "松花湖": (43.6684, 126.6746),
    "安吉": (30.6381, 119.6822), "罗定": (22.7696, 111.5700), "荆门": (31.0354, 112.1993),
    "丹巴": (30.8787, 101.9921), "康定": (30.0488, 101.9625), "新都桥": (30.0428, 101.5180),
    "理塘": (29.9963, 100.2680), "林芝": (29.6501, 94.3624), "然乌": (29.4900, 96.6600),
    "独山子": (44.3281, 84.8826), "库车": (41.7172, 82.9666), "那拉提": (43.2813, 84.0455),
    "六库": (25.8500, 98.8543), "贡山": (27.7400, 98.6600), "丙中洛": (28.1070, 98.6050),
    "武功山": (27.4630, 114.2660), "阳朔": (24.7790, 110.4890), "琼库什台": (43.0700, 82.4200),
    "乌兰布统": (42.4000, 117.4200), "喀拉峻": (43.0200, 82.2800),
    # 客运水路港口补充(供水路白名单比选, 坐标兜底)
    "台州": (28.6560, 121.4280), "安庆": (30.5080, 117.0470), "徐闻": (20.3370, 110.1680),
    "湛江": (21.2700, 110.3590), "漳州": (24.5130, 117.6530), "澳门": (22.1980, 113.5440),
    "蓬莱": (37.8070, 120.7550), "香港": (22.3190, 114.1690),
}


def find(name: str, dests: list[dict]) -> dict | None:
    hits = [d for d in dests if d.get("name") == name]
    if not hits:
        hits = [d for d in dests if name in d.get("name", "") or d.get("name", "") in name]
    return hits[0] if hits else None


def coords_of(name: str, dests: list[dict]) -> tuple | None:
    """优先 destinations.json, 缺坐标时回退枢纽表。"""
    d = find(name, dests)
    if d and isinstance(d.get("lat"), (int, float)) and isinstance(d.get("lon"), (int, float)):
        return d["lat"], d["lon"]
    return HUB_COORDS.get(name)


def haversine(a: tuple, b: tuple) -> float:
    la1, lo1 = a
    la2, lo2 = b
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    h = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1, math.sqrt(h)))


# 真实存在的客运水路港口白名单 (保守口径, 仅这些城市间才展示轮船, 防内陆伪航线幻觉)
WATERWAY_NETS = {
    "长江干线": {"重庆", "宜昌", "武汉", "岳阳", "荆州", "九江", "安庆", "芜湖", "南京", "上海"},
    "琼州海峡": {"海口", "徐闻", "湛江", "北海"},
    "渤海湾": {"大连", "烟台", "威海", "天津", "秦皇岛", "蓬莱"},
    "漓江": {"桂林", "阳朔"},
    "粤港澳轮渡": {"深圳", "珠海", "广州", "香港", "澳门"},
    "舟山群岛": {"宁波", "舟山", "上海", "台州"},
    "厦门湾区": {"厦门", "漳州", "泉州"},
}


def _same_waterway(a: str, b: str) -> bool:
    """两端是否同属一条真实客运水路网络；任一端不在白名单则视为无水路。"""
    for ports in WATERWAY_NETS.values():
        if a in ports and b in ports:
            return True
    return False


def build(frm: str, to: str, force_water: bool = False) -> dict:
    rules = json.load(open(RULES, encoding="utf-8"))
    dests = load_dest()
    ca, cb = coords_of(frm, dests), coords_of(to, dests)
    dist = haversine(ca, cb) if (ca and cb) else None

    g = rules["高铁"]; p = rules["普铁"]; fl = rules["飞机"]
    rec = rules["机票参考条件"]

    result: dict = {"from": frm, "to": to, "distance_km": round(dist) if dist else None}
    if not dist:
        # 坐标缺失通常是「同城/市内地点」（景点、街区、门店等不在城际目的地库中）。
        # 绝不能默认推荐高铁/飞机——那会把「市内逛个公园」误判成「跨省出行」。
        # 正确做法：先向用户确认是「市内交通」还是「跨城交通」，再决定判断逻辑。
        result["note"] = ("未能从目的地库获取两地坐标，无法估算距离。"
                          "这通常是同城/市内地点（景点、街区、门店不在城际目的地库中），"
                          "也可能是地名需消歧。")
        result["recommend"] = "需确认交通方式"
        result["reason"] = ("距离未知，不能默认推荐高铁/飞机。请先向用户确认："
                            "① 若为同城/市内出行——推荐公交/地铁/出租车/网约车，"
                            "而非城际铁路或航班；② 若确为跨城出行——再补两地后按城际六方式比选。")
        result["disclaimer"] = rules["核实声明"]
        return result

    # ── 同城/市内短途分支：市内出行不走城际高铁/飞机/普铁 ──
    # 判据：距离 ≤ 市内阈值（默认 30km）→ 视为同城/市内，只出市内交通方式。
    # 这修正了「近郊/市内短途被误判成跨省并推荐高铁飞机」的逻辑错误。
    city_rules = rules.get("市内交通")
    if city_rules and dist <= city_rules.get("city_distance_km", 30):
        result["scope"] = "市内"
        result["recommend"] = "市内交通"
        result["reason"] = (f"两地直线距离仅约 {round(dist)} km，属同城/市内出行，"
                            f"不应推荐城际高铁/飞机/普铁。按市内交通推荐："
                            f"地铁/公交/出租车/网约车，短驳可骑行、超短可步行。")
        result["options"] = [
            {"name": name, "fit": "市内出行", "how": desc}
            for name, desc in city_rules.get("modes", {}).items()
        ]
        result["disclaimer"] = rules["核实声明"]
        return result

    # 高铁
    g_hours = dist / g["speed_kmh"] + 1.0
    g_price = dist * g["price_per_km"]
    result["高铁"] = {
        "hours": round(g_hours, 1),
        "price_est": round(g_price),
        "note": g["note"],
    }
    # 普铁
    p_hours = dist / p["speed_kmh"] + 1.0
    result["普铁"] = {
        "hours": round(p_hours, 1),
        "price_hard_seat_est": round(dist * p["hard_seat_per_km"]),
        "price_hard_sleeper_est": round(dist * p["hard_sleeper_per_km"]),
        "note": p["note"],
    }
    # 飞机
    flight_hours = dist / 780.0
    ground = 3.0
    fl_total = flight_hours + ground
    full = dist * fl["full_price_per_km"]
    disc = {d: round(full * d) for d in fl["common_discounts"]}
    result["飞机"] = {
        "hours_flight": round(flight_hours, 1),
        "hours_total_est": round(fl_total, 1),
        "price_full_est": round(full),
        "price_discount_est": disc,
        "note": fl["note"],
    }

    # 客车 (短途近程主力: 县域/乡镇/景区班线)
    b = rules.get("客车")
    if b:
        bus_hours = dist / b["speed_kmh"] + 0.5
        result["客车"] = {
            "hours": round(bus_hours, 1),
            "price_est": round(dist * b["price_per_km"]),
            "note": b["note"],
        }
    # 轮船 (仅真实存在的客运水路: 跨海岛/长江干线/观光水域/海湾轮渡)
    # 内陆城市间无大江联运 → 默认不列轮船, 杜绝「重庆坐船到杭州」类伪航线幻觉
    s = rules.get("轮船")
    if s and (force_water or _same_waterway(frm, to)):
        ship_note = s["note"]
        if force_water and not _same_waterway(frm, to):
            ship_note += "（你指定了水路，但该城市对无已知客运航线，请务必核实是否真实开行）"
        ship_hours = dist / s["speed_kmh"] + 0.5
        result["轮船"] = {
            "hours": round(ship_hours, 1),
            "price_est": round(dist * s["price_per_km"]),
            "note": ship_note,
        }
    # 自驾 (短途近程最灵活)
    dr = rules.get("自驾")
    if dr:
        drive_hours = dist / dr["speed_kmh"]
        fuel = dist * dr["fuel_per_km"] * 7.5
        toll = dist * dr["toll_per_km"] if dist >= 30 else 0
        result["自驾"] = {
            "hours": round(drive_hours, 1),
            "cost_est": round(fuel + toll),
            "note": dr["note"],
        }

    # 推荐逻辑
    min_disc_price = min(disc.values())
    min_disc_factor = min(disc, key=disc.get)
    if dist <= 150:
        # 近程圈(30-150km)：近郊/周边县市，当天来回为主。
        # 不应按「高铁 vs 机票」的城际默认对比来推荐——近郊坐高铁是否划算，
        # 取决于「是否真的通高铁」与「距离是否够远」，必须先向用户确认出行方式。
        recommend = "近郊出行（优先自驾/班车）"
        reason = (f"两地约 {round(dist)} km，属近郊/周边短途，"
                  f"不建议默认推荐高铁或飞机。近郊出行优先自驾（最灵活，约 {result['自驾']['hours']}h）"
                  f"或客运班车（最便宜）；若确已通高铁且单程 ≥50km、班次合适，"
                  f"再考虑高铁往返（约 {result['高铁']['hours']}h / ¥{result['高铁']['price_est']}/人），"
                  f"并核对末班车时间。请先向用户确认出行方式后再定。")
    elif (min_disc_price <= g_price * 1.05) and (fl_total <= g_hours * 1.3):
        recommend = "机票参考"
        reason = (f"机票折扣估算低至 ¥{min_disc_price}（约 {min_disc_factor*10:.0f} 折），"
                  f"不超过高铁估算 ¥{round(g_price)} 的 1.05 倍，且总耗时（{round(fl_total,1)}h）"
                  f"未超过高铁（{round(g_hours,1)}h）的 1.3 倍；可优先考虑机票，但请以实时票价为准。")
    else:
        recommend = "高铁(默认)"
        reason = (f"高铁估算 ¥{round(g_price)} / {round(g_hours,1)}h，"
                  f"机票即便最低折扣估算 ¥{min_disc_price} 也更贵或耗时更长，按惯例优先高铁。")
    if dist >= 1200:
        reason += (f" 距离 {round(dist)}km 较远，若不赶时间，普铁夜班硬卧"
                   f"（约 ¥{result['普铁']['price_hard_sleeper_est']}）可省一晚住宿，适合预算优先。")

    result["recommend"] = recommend
    result["reason"] = reason
    result["disclaimer"] = rules["核实声明"]

    # ── 多方案组合 (方案 A/B/C, 按 快 / 省 / 灵活 三视角) ──
    gh, pr = result.get("高铁", {}), result.get("普铁", {})
    flt, bs, sh, dr = result.get("飞机", {}), result.get("客车", {}), result.get("轮船", {}), result.get("自驾", {})
    options = []
    if dist <= 150:
        # 近程圈: 当天来回, 组合时间与末班约束
        if dr:
            options.append({"name": "方案A · 自驾直达", "fit": "最灵活",
                            "how": f"约 {dr['hours']}h / ¥{dr['cost_est']}油费过路费, 时间完全自主, 适合带装备(徒步/骑行)与多人出行"})
        if gh:
            options.append({"name": "方案B · 高铁往返（若通高铁）", "fit": "通高铁才值得",
                            "how": f"约 {gh['hours']}h / ¥{gh['price_est']}/人，仅当两端确已通高铁且单程≥50km 才值得坐；先确认是否通高铁，再核对末班车时间——当天来回必须留返程余量, 查不到合适返程就改住一晚或改自驾/班车"})
        if bs:
            options.append({"name": "方案C · 客运班车", "fit": "最便宜",
                            "how": f"约 {bs['hours']}h / ¥{bs['price_est']}, 适合不通高铁的县域/景区; 班次少务必提前查当地客运站公众号, 错过末班只能包车"})
    elif dist <= 800:
        if gh:
            options.append({"name": "方案A · 高铁直达", "fit": "首选",
                            "how": f"约 {gh['hours']}h / ¥{gh['price_est']}/人, 市中心到市中心, 准点率高; 若无直达车次需中转, 中转时间留 ≥40min"})
        if dr:
            options.append({"name": "方案B · 自驾", "fit": "多点位",
                            "how": f"约 {dr['hours']}h / ¥{dr['cost_est']}, 适合沿途多景点或目的地公共交通不便(如草原/山区/多景区串联)"})
        if pr:
            options.append({"name": "方案C · 普铁", "fit": "预算优先",
                            "how": f"约 {pr['hours']}h / 硬座 ¥{pr['price_hard_seat_est']}, 时间充裕时比高铁省 50%+; 夜班硬卧 ¥{pr['price_hard_sleeper_est']} 可省一晚住宿"})
    else:
        if gh:
            options.append({"name": "方案A · 高铁", "fit": "基准",
                            "how": f"约 {gh['hours']}h / ¥{gh['price_est']}/人"})
        if flt:
            lo_d = min(flt.get("price_discount_est", {}).values(), default=flt.get("price_full_est", 0))
            options.append({"name": "方案B · 飞机(折扣)", "fit": "长距离",
                            "how": f"含接驳约 {flt['hours_total_est']}h / 折扣估 ¥{lo_d} 起, 提前 2-4 周购票折扣最优, 大风大雾易延误需留余量"})
        if pr:
            options.append({"name": "方案C · 普铁夜班", "fit": "最省",
                            "how": f"夜班硬卧 ¥{pr['price_hard_sleeper_est']}, 睡一觉到站省一晚住宿, 适合不赶时间的慢旅行"})
    if sh:
        options.append({"name": "方案+ · 轮船/渡轮", "fit": "水域专线",
                        "how": f"约 {sh['hours']}h / ¥{sh['price_est']}, 跨海岛/长江干线适用; 大风大雾停航常见, 出行前查港口公众号公告"})
    result["options"] = options

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="城际交通比选(高铁/普铁/飞机)")
    ap.add_argument("--from", dest="frm", required=True, help="出发地")
    ap.add_argument("--to", required=True, help="目的地")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    ap.add_argument("--water", action="store_true", help="强制包含轮船/渡轮方案(即便非已知水路, 需自行核实航线)")
    args = ap.parse_args()

    r = build(args.frm, args.to, force_water=args.water)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print(f"═══ {args.frm} → {args.to} 交通比选 ═══")
    if r.get("distance_km"):
        print(f"估算距离: {r['distance_km']} km")
        d = r["distance_km"]
        if d <= 150:
            print("  📍 近程圈(≤150km): 当天来回为主, 客运班车/自驾最常用")
        elif d <= 300:
            print("  📍 短途圈(≤300km): 1-3 天行程, 高铁 1.5h 圈首选")
    g = r.get("高铁", {}); p = r.get("普铁", {}); fl = r.get("飞机", {})
    bus = r.get("客车", {}); ship = r.get("轮船", {}); drive = r.get("自驾", {})
    if g:
        print(f"  高铁: 约 {g['hours']}h | 估算 ¥{g['price_est']}")
    if p:
        print(f"  普铁: 约 {p['hours']}h | 硬座 ¥{p['price_hard_seat_est']} / 硬卧 ¥{p['price_hard_sleeper_est']}")
    if bus:
        print(f"  客车: 约 {bus['hours']}h | 估算 ¥{bus['price_est']}")
    if ship:
        print(f"  轮船: 约 {ship['hours']}h | 估算 ¥{ship['price_est']}")
    if drive:
        print(f"  自驾: 约 {drive['hours']}h | 油费+过路费估算 ¥{drive['cost_est']}")
    if fl:
        dsc = fl['price_discount_est']
        lo, hi = min(dsc.values()), max(dsc.values())
        lo_f = min(dsc, key=dsc.get) * 10
        hi_f = max(dsc, key=dsc.get) * 10
        print(f"  飞机: 飞行 {fl['hours_flight']}h+接驳≈{fl['hours_total_est']}h | 全价估 ¥{fl['price_full_est']} "
              f"折扣估 ¥{lo}-¥{hi}（约 {lo_f:.0f}-{hi_f:.0f} 折）")
    print(f"\n  推荐: {r['recommend']}")
    print(f"  理由: {r['reason']}")
    for opt in r.get("options", []):
        print(f"\n  {opt['name']} [{opt['fit']}]\n    {opt['how']}")
    print(f"\n  ⚠️ {r['disclaimer']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
