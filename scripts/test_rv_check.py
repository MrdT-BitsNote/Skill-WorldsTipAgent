#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rv_check 回归测试：锁死房车后勤判定纪律，不触网、纯本地数据。

锁死的核心纪律（踩过坑/易回退的）：
1. 只有【驾照牌照与车型不匹配】【拖挂无C6】判红灯（违法上路）；限高/补给/排污/营地一律黄灯或灰灯，
   绝不把「后勤待办」误判成「行程不成立」。
2. 「未查证」不判红也不判绿：缺车高/水箱/电池/排污计划 → 灰灯或黄灯 + 需自行核实，绝不默认没问题。
3. 非房车不硬套房车后勤（排污项对轿车/SUV 走灰灯「不适用」）。
4. 数据只给区间/节奏/规则，不编造具体排污站/营地名称与坐标。
运行：python test_rv_check.py
"""
import sys

import rv_check as rc

PASS = FAIL = 0


def ck(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  ✗ FAIL:", msg)


def card_of(g, title_prefix):
    for c in g["cards"]:
        if c["title"].startswith(title_prefix):
            return c
    return None


def test_data_loaded():
    d = rc.data()
    ck(bool(d) and "height_limits" in d and "waste" in d, "rv_logistics.json 应加载出核心块")
    ck(len(d["route"]["classic_routes"]) >= 5, "经典线路应 >=5 条")
    ck(set(d["vehicle_types"]) >= {"sedan", "suv", "mpv", "rv"}, "四种车型后勤齐备")


def test_license_red_only_for_illegal():
    # 拖挂无 C6 → 红灯阻断
    g = rc.rv_card(vehicle_type="rv", is_tow=True, license_class="C1")
    ck(g["red"] == 1 and g["verdict"] == "blocked", "拖挂无C6应红灯阻断")
    # 拖挂持 C6 → 不红
    g2 = rc.rv_card(vehicle_type="rv", is_tow=True, license_class="C6")
    ck(card_of(g2, "驾照")["light"] != rc.RED, "拖挂持C6不应红灯")
    # 黄牌(车长6.5m) + C1 → 红灯
    g3 = rc.rv_card(vehicle_type="rv", length_m=6.5, license_class="C1")
    ck(card_of(g3, "驾照")["light"] == rc.RED, "黄牌车持C1应红灯")
    # 黄牌 + B2 → 绿
    g4 = rc.rv_card(vehicle_type="rv", length_m=6.5, license_class="B2")
    ck(card_of(g4, "驾照")["light"] == rc.GREEN, "黄牌车持B2应绿灯")
    # 蓝牌 + C1 → 绿
    g5 = rc.rv_card(vehicle_type="rv", length_m=5.9, gross_mass_kg=4200, license_class="C1")
    ck(card_of(g5, "驾照")["light"] == rc.GREEN, "蓝牌车持C1应绿灯")


def test_license_grey_when_unknown():
    g = rc.rv_card()  # 什么都不给
    ck(card_of(g, "驾照")["light"] == rc.GREY, "无车型/驾照信息应灰灯，不猜")


def test_height_never_red():
    # 房车 3.0m → 黄灯（可规避），绝不红
    g = rc.rv_card(vehicle_type="rv", vehicle_height_m=3.0)
    c = card_of(g, "限高")
    ck(c["light"] == rc.YELLOW, "限高应黄灯不是红灯（可规避）")
    ck("地下车库" in (c["items"][0]["v"] if c["items"] else "") or "地" in c["detail"], "3.0m 应点出地库/干道限高")
    # 轿车 → 绿灯
    g2 = rc.rv_card(vehicle_type="sedan")
    ck(card_of(g2, "限高")["light"] == rc.GREEN, "轿车限高应绿灯")
    # 房车未给车高 → 黄灯提醒实测
    g3 = rc.rv_card(vehicle_type="rv")
    ck(card_of(g3, "限高")["light"] == rc.YELLOW, "房车未给车高应黄灯提醒实测")


def test_resupply_cadence():
    # 水撑不过行程天数 → 黄灯 + 补水提示
    g = rc.rv_card(vehicle_type="rv", water_tank_l=70, people=3, days=6)
    c = card_of(g, "补给")
    ck(c["light"] == rc.YELLOW, "水续航<行程天数应黄灯")
    ck(any("补水" in it.get("v", "") for it in c["items"]), "应给出途中补水提示")
    # 开空调 → 黄灯（离网撑不过一夜）
    g2 = rc.rv_card(vehicle_type="rv", battery_kwh=5, use_ac=True)
    ck(card_of(g2, "补给")["light"] == rc.YELLOW, "开空调用电应黄灯")
    # 水充足(240L/2人≈1.4天>=1天行程) + 不开空调 → 绿
    g3 = rc.rv_card(vehicle_type="rv", water_tank_l=240, people=2, days=1, battery_kwh=8, use_ac=False)
    ck(card_of(g3, "补给")["light"] == rc.GREEN, "补给充足应绿灯")
    # 无水电参数 → 灰灯
    g4 = rc.rv_card(vehicle_type="rv")
    ck(card_of(g4, "补给")["light"] == rc.GREY, "无水箱/电池参数应灰灯不猜")


def test_waste():
    # 房车未确认排污 → 黄灯（稀缺提醒）
    g = rc.rv_card(vehicle_type="rv")
    ck(card_of(g, "黑水")["light"] == rc.YELLOW, "房车排污未确认应黄灯")
    # 已确认排污计划 → 绿灯
    g2 = rc.rv_card(vehicle_type="rv", dump_plan=True)
    ck(card_of(g2, "黑水")["light"] == rc.GREEN, "已确认排污计划应绿灯")
    # 非房车 → 灰灯不适用
    g3 = rc.rv_card(vehicle_type="suv")
    ck(card_of(g3, "黑水")["light"] == rc.GREY, "非房车排污应灰灯不适用")


def test_campground():
    g = rc.rv_card(vehicle_type="rv", booked=True)
    ck(card_of(g, "营地")["light"] == rc.GREEN, "已订营地应绿灯")
    g2 = rc.rv_card(vehicle_type="rv", peak_season=True)
    ck(card_of(g2, "营地")["light"] == rc.YELLOW, "旺季未订应黄灯")


def test_card_aggregation():
    # 升顶收顶低车高(2.1m<2.2) + 蓝牌C1 + 补给充足 + 已确认排污 + 已订营地 → clear
    g = rc.rv_card(vehicle_type="rv", length_m=5.9, license_class="C1", vehicle_height_m=2.1,
                   water_tank_l=240, people=2, days=1, battery_kwh=8, use_ac=False,
                   dump_plan=True, booked=True)
    ck(g["verdict"] == "clear" and g["red"] == 0, "全部落实应 clear 无红灯")
    ck(g["vehicle_logistics"].get("label") == "房车", "应带出车型后勤速查")
    # 高车高 C型(3.0m) 永远有限高黄灯 → 不会 clear（诚实：高车不可能「全清」）
    g2 = rc.rv_card(vehicle_type="rv", length_m=5.9, license_class="C1", vehicle_height_m=3.0,
                    water_tank_l=240, people=2, days=1, battery_kwh=8, use_ac=False,
                    dump_plan=True, booked=True)
    ck(g2["verdict"] == "caution" and g2["red"] == 0, "3.0m 房车应恒为 caution（限高黄灯）非 clear")


def test_html_render_and_escape():
    g = rc.rv_card(vehicle_type="rv", length_m=5.9, license_class="C1", vehicle_height_m=3.0)
    h = rc.rv_html(g, "测试")
    ck(h.startswith('<div class="sec-open" id="rv">'), "应渲染房车板块外壳")
    ck("房车 / 自驾后勤自检" in h, "应含板块标题")
    ck("后勤速查" in h, "应含车型后勤速查卡")
    ck(rc.rv_html({}, "") == "", "空卡应返回空串")
    ck(rc.rv_html({"cards": []}, "") == "", "无 cards 应返回空串")
    # 转义
    ck(rc._esc("<script>") == "&lt;script&gt;", "HTML 应转义")


def test_no_fabrication_guard():
    d = rc.data()
    blob = str(d)
    # 不应出现精确经纬度坐标（本库刻意不存坐标）
    import re
    ck(not re.search(r"\b1[0-3]\d\.\d{4,}", blob), "后勤库不应含精确经度坐标")
    ck(d["waste"]["infrastructure"]["结论"], "应保留『排污稀缺』这一确定性结论")


# ── v0.1.13 审查修复：锁死被修掉的 bug，防回退 ──────────────────

def test_license_no_assert_from_empty():
    """生产真实路径：rv 画像恒传 vehicle_type='rv' 但无车长/质量/驾照 → 必须灰灯，绝不断言蓝牌。"""
    g = rc.rv_card(vehicle_type="rv")
    c = card_of(g, "驾照")
    ck(c["light"] == rc.GREY, "零尺寸/驾照数据应灰灯，不得断言蓝牌")
    ck("蓝牌" not in c["detail"] or "无法判定" in c["detail"], "不得在无数据时下蓝牌结论")


def test_resupply_power_vs_days():
    """电量也必须与行程天数比较（旧 bug：只比水，电不足仍报绿）。"""
    g = rc.rv_card(vehicle_type="rv", battery_kwh=2, days=15, use_ac=False, people=2, water_tank_l=1000)
    c = card_of(g, "补给")
    ck(c["light"] == rc.YELLOW, "电撑不过行程天数应黄灯，不得报绿")
    ck(any("充电" in it.get("v", "") or "市电" in it.get("v", "") for it in c["items"]), "应给出途中充电提示")


def test_resupply_never_default_green():
    """有水但无法证明够整趟（缺天数）→ 黄灯，不默认绿。"""
    g = rc.rv_card(vehicle_type="rv", water_tank_l=200)
    ck(card_of(g, "补给")["light"] == rc.YELLOW, "无法证明补给充足时应黄灯，绝不默认绿")


def test_waste_black_tank_false():
    """显式『无黑水箱』→ 灰灯轻量指引，不输出完整房车黑水规程（旧 bug：忽略 has_black_tank 值）。"""
    g = rc.rv_card(vehicle_type="rv", has_black_tank=False)
    c = card_of(g, "黑水")
    ck(c["light"] == rc.GREY, "无黑水箱应灰灯")
    ck("便携马桶" in c["action"] or "公厕" in c["action"], "无黑水箱应给轻量指引")


def test_campground_vehicle_gate():
    """非房车（轿车/SUV/MPV）不得拿到房车营地谱系与拖挂占位文案（旧 bug：无车型闸）。"""
    for vt in ("sedan", "suv", "mpv"):
        g = rc.rv_card(vehicle_type=vt, days=3)
        c = card_of(g, "过夜") or card_of(g, "营地")
        ck(c["light"] == rc.GREY, f"{vt} 过夜/营地应灰灯轻量，不套房车营地")
        blob = c["detail"] + c["action"]
        ck("拖挂占" not in blob and "房车营地(¥" not in blob, f"{vt} 不应出现房车营地/拖挂文案")


def test_route_emergency_guard():
    """daily_km 只有 1 元素也不得 IndexError（旧 bug：dk[0]/dk[1] 无长度守卫）。"""
    orig = rc.data()["route"].get("daily_km")
    try:
        rc.data()["route"]["daily_km"] = [300]
        h = rc.route_emergency_html(1234)
        ck("300" in h and "全程约 1234km" in h, "单元素 daily_km 应降级不崩，且渲染 total_km")
        rc.data()["route"]["daily_km"] = []
        h2 = rc.route_emergency_html(None)
        ck(isinstance(h2, str) and "日行里程" in h2, "空 daily_km 也应降级不崩")
    finally:
        rc.data()["route"]["daily_km"] = orig


def test_data_driven_not_hardcoded():
    """渲染数字须来自 rv_logistics.json（旧 bug：JSON 被加载却没被读取，数字硬编码在 .py）。"""
    d = rc.data()
    per_day = d["water"]["per_person_day_l"]
    g = rc.rv_card(vehicle_type="rv", water_tank_l=per_day * 2, people=1, days=1)
    c = card_of(g, "补给")
    ck(str(per_day) in "".join(it.get("v", "") for it in c["items"]),
       "补给节奏应引用 JSON 的 per_person_day_l，而非硬编码")
    max_len = d["license_plate"]["blue_plate"]["max_length_m"]
    g2 = rc.rv_card(vehicle_type="rv", length_m=max_len + 0.5, license_class="C1")
    ck(card_of(g2, "驾照")["light"] == rc.RED, "黄牌阈值应取自 JSON max_length_m")


def test_volatile_badge():
    """volatile 块（补给/营地/排污）渲染须挂『易变·出行前核验』角标（spec 5a）。"""
    g = rc.rv_card(vehicle_type="rv", water_tank_l=120, people=2, days=3)
    ck(card_of(g, "补给").get("volatile") is True, "补给卡应标 volatile")
    ck(card_of(g, "营地").get("volatile") is True, "营地卡应标 volatile")
    h = rc.rv_html(g, "")
    ck("易变·出行前核验" in h, "渲染应出现易变角标")


def test_official_facilities_evidence_first():
    """官方设施·证据优先（房车 session 结论）：数据模型 + 停靠纪律须落地。"""
    d = rc.data()
    of = d.get("official_facilities")
    ck(isinstance(of, dict) and of, "rv_logistics 应含 official_facilities 块")
    ph = of.get("philosophy", {})
    ck("证据即可信度单位" in ph and "只收官方正规设施" in ph, "应含『证据即可信度单位』『只收官方正规设施』纪律")
    ck("有设施不等于能过夜" in ph, "应含『有设施≠能过夜』纪律")
    # schema 必须以来源+日期为可信度单位
    schema = of.get("facility_schema", {})
    ck("source" in schema and "source_date" in schema and "claim" in schema,
       "facility_schema 须含 source/source_date/claim")
    # 种子事实须带来源与稳定性，且不含精确坐标
    facts = of.get("seed_aggregate_facts", {}).get("facts", [])
    ck(len(facts) >= 4, "应含 >=4 条种子锚点事实")
    ck(all(f.get("source") and f.get("stability") for f in facts), "每条种子事实须带 source+stability")
    ck(all("lat" not in f and "lon" not in f for f in facts), "种子事实不得含精确坐标（不编造点位）")
    # 停靠纪律须进 check_campground 的 action（房车）
    g = rc.rv_card(vehicle_type="rv", days=3)
    camp = card_of(g, "营地")
    ck("电话确认" in camp["action"] or "有设施" in camp["action"] or "官方正规设施" in camp["action"],
       "房车营地卡 action 应含证据优先停靠纪律")
    ck(any(it.get("k") == "证据优先" for it in camp["items"]), "营地卡应带『证据优先』条目")
    # 路线面板应含终点停靠·证据优先
    h = rc.route_emergency_html(None)
    ck("终点停靠·证据优先" in h, "路线面板应含终点停靠·证据优先")


def main():
    for fn in (test_data_loaded, test_license_red_only_for_illegal, test_license_grey_when_unknown,
               test_height_never_red, test_resupply_cadence, test_waste, test_campground,
               test_card_aggregation, test_html_render_and_escape, test_no_fabrication_guard,
               test_license_no_assert_from_empty, test_resupply_power_vs_days,
               test_resupply_never_default_green, test_waste_black_tank_false,
               test_campground_vehicle_gate, test_route_emergency_guard,
               test_data_driven_not_hardcoded, test_volatile_badge,
               test_official_facilities_evidence_first):
        fn()
    print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
    print("rv_check OK" if FAIL == 0 else "FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
