#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""房车 / 自驾后勤自检引擎（v0.1.13）。

与 moto_check 同构：把房车出行的硬约束与后勤节奏拆成几张灯位卡（红/黄/绿/灰），
汇总成 rv_card()，再由 rv_html() 渲染进小册子，与门禁卡共用视觉语言。

设计纪律（沿用摩旅两条踩坑规则 + 可信度内核）：
1. 「后勤事项」≠「行程不成立」。限高、补给、排污、营地绝大多数是【提前规划可解】的黄灯，
   只有【驾照/牌照与车型不匹配】【拖挂无 C6】这类违法上路才判红灯。
2. 「未查证」不判红也不判绿。缺车高/水箱/电池/排污计划 → 灰灯或黄灯 + 写明需自行核实，
   绝不默认没问题、绝不用零数据断言蓝牌。
3. 数据驱动：所有阈值/区间/文案取自 references/rv_logistics.json，本文件不硬编码具体数字，
   避免数据与代码两份真相漂移。volatile 块（价格/营位/补给）渲染时挂「易变·出行前核验」角标。
4. 不编造具体排污站/营地名称、坐标、精确价格——只给区间、节奏、规则与「出行前电话确认」指引。

不做的事：不推荐用户「该选哪种车型」。车型由用户声明，本模块只按声明提供对应后勤。
"""
from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refloader

RED, YELLOW, GREEN, GREY = "red", "yellow", "green", "grey"
_CN = {RED: "红", YELLOW: "黄", GREEN: "绿", GREY: "灰"}
_STYLE = {
    RED: ("#FCEBEB", "#A32D2D", "#791F1F", "⛔"),
    YELLOW: ("#FAEEDA", "#BA7517", "#633806", "⚠"),
    GREEN: ("#EAF3DE", "#639922", "#27500A", "✅"),
    GREY: ("#F1EFE8", "#888780", "#444441", "◐"),
}

_DB: dict | None = None


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if s is not None else "")


def data() -> dict:
    global _DB
    if _DB is None:
        _DB = refloader.load("rv_logistics.json")
    return _DB


def _rng(v, sep="-"):
    """把 [a,b] 或标量渲染成字符串。"""
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return f"{v[0]}{sep}{v[1]}"
    if isinstance(v, (list, tuple)) and len(v) == 1:
        return str(v[0])
    return str(v) if v is not None else ""


# ── 单项检查 ────────────────────────────────────────────────

def check_license(vehicle_type: str | None, length_m: float | None = None,
                  gross_mass_kg: float | None = None, license_class: str | None = None,
                  is_tow: bool | None = None) -> dict:
    """驾照与牌照：唯一可能判红灯的项（违法上路）。无尺寸/驾照数据 → 灰灯，绝不断言蓝牌。"""
    lp = data().get("license_plate", {})
    blue = lp.get("blue_plate", {})
    tow = lp.get("tow_trailer", {})
    max_len = blue.get("max_length_m", 6.0)
    max_mass = blue.get("max_mass_kg", 4500)
    tow_ok = set(tow.get("ok_classes", ["C6", "A2", "A1", "A3", "A"]))

    if all(x is None for x in (vehicle_type, length_m, gross_mass_kg, license_class, is_tow)):
        return {"light": GREY, "title": "驾照与牌照",
                "detail": "未提供车型/车长/总质量/驾照，无法判定准驾是否匹配。",
                "action": f"确认：车长<{max_len}m 且总质量<{max_mass}kg 为蓝牌（C1/C2 可驾）；"
                          f"≥{max_len}m 或≥{max_mass}kg 为黄牌（需 B/A）；牵引旅居挂车需 C6。",
                "items": [], "volatile": False}

    lc = (license_class or "").upper()
    has_dims = (length_m is not None) or (gross_mass_kg is not None)

    # 拖挂：需 C6（或 A 类），与车长无关，先判
    if is_tow and lc and lc not in tow_ok:
        return {"light": RED, "title": "驾照与牌照（拖挂）",
                "detail": f"牵引旅居挂车需 C6 准驾（或 A2）。当前驾照：{lc}。"
                          f"{tow.get('规则', '挂车不得载人；组合总质量≤4500kg 的汽车列车需 C6。')}",
                "action": "硬阻断项：先增驾 C6（持 C1/C2 满 1 年、近两记分周期未记满 12 分）再上路。",
                "items": [{"k": "依据", "v": "《道交法实施条例》第56条；公安部162/172号令"}],
                "volatile": False}

    if has_dims:
        need_yellow = (length_m is not None and length_m >= max_len) or \
                      (gross_mass_kg is not None and gross_mass_kg >= max_mass)
        if need_yellow:
            if lc and lc[0] in ("A", "B"):
                return {"light": GREEN, "title": "驾照与牌照（黄牌）",
                        "detail": f"车长{length_m if length_m is not None else '?'}m/总质量"
                                  f"{gross_mass_kg if gross_mass_kg is not None else '?'}kg 属黄牌，持 {lc} 准驾匹配。",
                        "action": "逐城核对黄牌车限行时段与通行证要求（volatile，出发前查当地交管）。",
                        "items": [{"k": "阈值", "v": f"GA 802-2019：车长<{max_len}m 且总质量<{max_mass}kg 为蓝牌"}],
                        "volatile": True}
            if lc:
                return {"light": RED, "title": "驾照与牌照（黄牌）",
                        "detail": f"车长≥{max_len}m 或总质量≥{max_mass}kg 属黄牌车，需 B1/B2 或 A 类驾照。当前：{lc}。",
                        "action": "硬阻断项：持对应准驾车型再上路；黄牌车多城核心城区早晚高峰限行、需办通行证（逐城核验）。",
                        "items": [{"k": "阈值", "v": f"GA 802-2019：车长<{max_len}m 且总质量<{max_mass}kg 为蓝牌"}],
                        "volatile": False}
            return {"light": GREY, "title": "驾照与牌照（黄牌）",
                    "detail": f"车长≥{max_len}m 或总质量≥{max_mass}kg 属黄牌车，需 B1/B2 或 A 类驾照；未提供驾照。",
                    "action": "确认持 B/A 类准驾；并逐城核对黄牌车限行与通行证（volatile）。",
                    "items": [], "volatile": True}
        # 蓝牌区间
        if lc in ("C1", "C2") or (lc and lc[0] in ("A", "B")):
            return {"light": GREEN, "title": "驾照与牌照（蓝牌）",
                    "detail": f"车长<{max_len}m 且总质量<{max_mass}kg 属蓝牌，{lc} 可驾，按小客车通行权管理。",
                    "action": f"{blue.get('通行权', '按小客车管理，不含货车式限行')}；"
                              f"{lp.get('scrappage', '小微型非营运自行式房车已取消强制报废年限')}",
                    "items": [], "volatile": False}
        if lc:  # 拖挂已具备 C6 但主车尺寸未知，或有其它驾照
            return {"light": YELLOW, "title": "驾照与牌照",
                    "detail": f"未提供车长/总质量，无法判定蓝牌还是黄牌。当前驾照：{lc}。",
                    "action": f"核对行驶证：车长<{max_len}m 且总质量<{max_mass}kg→蓝牌（C1/C2 可驾）；否则黄牌需 B/A。",
                    "items": [], "volatile": False}
        return {"light": GREY, "title": "驾照与牌照",
                "detail": "属蓝牌尺寸区间但未提供驾照，无法确认准驾匹配。",
                "action": f"确认持 C1/C2 及以上（蓝牌 <{max_len}m 且 <{max_mass}kg）。",
                "items": [], "volatile": False}

    # 无尺寸数据
    if is_tow and lc in tow_ok:
        return {"light": YELLOW, "title": "驾照与牌照（拖挂）",
                "detail": f"拖挂准驾 {lc} 已具备；但未提供车长/总质量，无法判定主车蓝/黄牌。",
                "action": "核对主车行驶证尺寸；挂车不得载人。", "items": [], "volatile": False}
    return {"light": GREY, "title": "驾照与牌照",
            "detail": "未提供车长/总质量，无法判定蓝牌（C1/C2）还是黄牌（B/A）。",
            "action": f"核对行驶证：车长<{max_len}m 且总质量<{max_mass}kg→蓝牌 C1/C2；否则黄牌需 B/A；拖挂需 C6。",
            "items": [], "volatile": False}


def check_height(vehicle_type: str | None, vehicle_height_m: float | None = None,
                 route_low_clearance: bool | None = None) -> dict:
    """限高：可规避 → 黄灯，绝不判红（除非明确要闯已知限高）。阈值取自数据库。"""
    hl = data().get("height_limits", {})
    rc = hl.get("road_clearance_m", {})
    vt = data().get("vehicle_types", {})
    garage = rc.get("城市地库_老旧小区", [2.0, 2.2])
    garage_hi = garage[1] if isinstance(garage, list) and len(garage) >= 2 else 2.2
    urban = rc.get("城市主次干道常见", 2.8)
    scenic = rc.get("景区_乡村道路常见", [2.5, 3.0])
    scenic_lo = scenic[0] if isinstance(scenic, list) and scenic else 2.5

    if vehicle_type not in vt or vehicle_type == "_note":
        return {"light": GREY, "title": "限高通行",
                "detail": "未声明车型，无法判断限高风险。",
                "action": "声明车型并实测整车高度（含空调外机/天线/天窗）。", "items": [], "volatile": False}
    if vehicle_type == "sedan":
        return {"light": GREEN, "title": "限高通行",
                "detail": vt.get("sedan", {}).get("height", "轿车车高通常 <1.5m，无限高困扰"),
                "action": "常规通行即可，可进地库。", "items": [], "volatile": False}
    if vehicle_height_m is None:
        rh = hl.get("rv_typical_height_m", {})
        return {"light": YELLOW, "title": "限高通行",
                "detail": f"未提供实测车高。房车车高参考：自行式{_rng(rh.get('自行式普遍', [2.8, 3.3]))}m、"
                          f"C型{_rng(rh.get('C型_含额头', [2.8, 3.0]))}m；城市地库限高仅{_rng(garage)}m、"
                          f"城市干道常见{urban}m、景区乡村{_rng(scenic)}m。",
                "action": "出发前实测车高到厘米；C型/拖挂默认进不了任何地库，导航用货车/自定义车高模式规避已知限高杆。",
                "items": [{"k": "常见限高", "v": f"地库{_rng(garage)}m · 城市干道{urban}m · 景区乡村{_rng(scenic)}m · "
                                                 f"高速/一二级净高{rc.get('高速_一级_二级', 5.0)}m"}],
                "volatile": False}
    blocked_by = []
    if vehicle_height_m >= garage_hi:
        blocked_by.append(f"地下车库(限高{_rng(garage)}m)")
    if vehicle_height_m >= scenic_lo:
        blocked_by.append(f"景区/乡村道路({_rng(scenic)}m)")
    if vehicle_height_m >= urban:
        blocked_by.append(f"城市干道常见限高{urban}m")
    light = YELLOW if (blocked_by or route_low_clearance) else GREEN
    return {"light": light, "title": "限高通行",
            "detail": f"实测车高 {vehicle_height_m}m。" + (
                f"将无法通过：{'、'.join(blocked_by)}。" if blocked_by else "未见明显限高冲突。"),
            "action": hl.get("tunnel_mountain", "规避上述限高路段与一切地下车库；隧道适用净高标准，超限车不得入隧道。"),
            "items": ([{"k": "需规避", "v": "、".join(blocked_by)}] if blocked_by else []),
            "volatile": False}


def check_resupply(water_tank_l: float | None = None, people: int | None = None,
                   days: int | None = None, battery_kwh: float | None = None,
                   use_ac: bool | None = None) -> dict:
    """补给半径：把水/电数字变成补给节奏与决策点。缺参数 → 灰灯；无法证明够用 → 黄灯，绝不默认绿。"""
    w = data().get("water", {}); p = data().get("power", {})
    per_day = w.get("per_person_day_l", 85)
    daily_kwh = p.get("daily_kwh", {})
    base_pair = daily_kwh.get("基础_冰箱照明水泵充电", [2, 3])
    base_hi = base_pair[1] if isinstance(base_pair, list) and len(base_pair) >= 2 else 3

    if water_tank_l is None and battery_kwh is None:
        return {"light": GREY, "title": "补给半径（水/电）",
                "detail": "未提供净水箱容量与电池容量，无法估算补给节奏。",
                "action": f"提供净水箱(L)与生活电池(度)；缺省经验：净水箱{_rng(w.get('tank_l', [50, 200]))}L、"
                          f"约{per_day}L/人/天、{w.get('cadence', '每2-3天补水')}；"
                          f"电池基础{_rng(base_pair)}度/天、开空调{_rng(daily_kwh.get('含空调或电磁炉', [8, 15]))}度/天，"
                          f"{p.get('offgrid', '离网开空调撑不过一夜')}。",
                "items": [], "volatile": True}

    items = []
    water_ok = power_ok = None
    if water_tank_l is not None:
        if people:
            wpd = per_day * people
            water_days = round(water_tank_l / wpd, 1) if wpd else None
            if water_days is not None:
                items.append({"k": "净水", "v": f"{water_tank_l}L ÷ {people}人×{per_day}L/人/天 ≈ 撑 {water_days} 天"})
                if days:
                    water_ok = water_days >= days
                    if not water_ok:
                        items.append({"k": "途中补水", "v": f"行程 {days} 天 > 水续航 {water_days} 天，须中途补水"
                                                            f"（{'、'.join(w.get('refill_points', {}).get('免费_低成本', [])[:3])}）"})
        else:
            items.append({"k": "净水", "v": f"{water_tank_l}L（未给人数，按{per_day}L/人/天估：1人≈{round(water_tank_l / per_day, 1)}天）"})
    if battery_kwh is not None:
        if use_ac:
            items.append({"k": "用电", "v": f"{battery_kwh}度 + 开空调（{_rng(daily_kwh.get('含空调或电磁炉', [8, 15]))}度/天）"
                                            f"→ {p.get('offgrid', '离网基本撑不过一夜')}，须每日接市电/行车充电"})
            power_ok = False
        else:
            base_days = round(battery_kwh / base_hi, 1)
            items.append({"k": "用电", "v": f"{battery_kwh}度 不开空调（基础{_rng(base_pair)}度/天）≈ 撑 {base_days} 天；"
                                            f"{(p.get('recharge', {}) or {}).get('太阳能', '太阳能400W晴天约+2.5度/天')}"})
            if days:
                power_ok = base_days >= days
                if not power_ok:
                    items.append({"k": "途中充电", "v": f"行程 {days} 天 > 电续航 {base_days} 天，须接市电/行车充电/太阳能补能"})

    # 只有水、电都【证明够整趟】才绿；有数据但证明不了 → 黄（须规划补给）
    light = GREEN if (water_ok is True and power_ok is True) else YELLOW
    action = ("按补给节奏把『下一个补水/充电点』排成硬节点；" +
              w.get("interface", "接口多为 G1/2 英寸，备软管+转接头") + "；" +
              (p.get("recharge", {}) or {}).get("市电", "营地市电充满常需 8-12h") + "。")
    return {"light": light, "title": "补给半径（水/电）",
            "detail": "水/电续航决定补给节奏——补给点稀疏是房车路线的硬约束。",
            "action": action, "items": items, "volatile": True}


def check_waste(vehicle_type: str | None, has_black_tank: bool | None = None,
                dump_plan: bool | None = None) -> dict:
    """黑水/灰水：排污设施稀缺是确定性事实。房车默认黄灯，已确认排污→绿灯；
    明确无黑水箱→灰灯轻量指引；非房车→灰灯不适用。"""
    wa = data().get("waste", {})
    black = wa.get("black", {}); infra = wa.get("infrastructure", {})
    if has_black_tank is False:
        return {"light": GREY, "title": "黑水/灰水处理",
                "detail": "无车载黑水箱（床车/改装）。",
                "action": "便携马桶仍须到公厕或指定点倾倒，严禁野外/路边/水源地直排。",
                "items": [], "volatile": False}
    if vehicle_type != "rv" and has_black_tank is None:
        return {"light": GREY, "title": "黑水/灰水处理",
                "detail": "非房车或未涉及车载排污，本项不适用。",
                "action": "如为床车/改装带便携马桶，仍须到公厕或指定点倾倒，严禁野外直排。",
                "items": [], "volatile": False}
    if dump_plan:
        return {"light": GREEN, "title": "黑水/灰水处理",
                "detail": f"已规划合规排污点。{black.get('cadence', '黑水箱满约80%即排')}；"
                          f"灰水须分流达标（GB 8978）后排放。",
                "action": f"到营地排污桩/服务区指定井口倾倒（口径{_rng(black.get('port_mm', [38, 50]), ' 或 ')}mm，提前确认管路匹配）；"
                          f"{black.get('rules', '黑水加降解剂、禁倒纸巾湿巾；严禁野外/路边/水源地直排')}。",
                "items": [{"k": "排污口径", "v": f"{_rng(black.get('port_mm', [38, 50]), ' 或 ')}mm，出发前确认"}],
                "volatile": True}
    return {"light": YELLOW, "title": "黑水/灰水处理",
            "detail": infra.get("detail", "排污基础设施在中国整体极稀缺：有效合规营位严重不足，"
                                "很多挂名『营地』只有硬化地面+水龙头、无排污口。"),
            "action": "把【能合规排污的正规营地/排污点】作为路线硬节点，不能假设沿途随时可排；"
                      "出发前电话确认排污可用；黑水严禁野外直排，灰水雨污/灰黑分流达标后排放。",
            "items": [{"k": "黑水箱", "v": f"{_rng(black.get('tank_l', [15, 80]))}L，{black.get('cadence', '满80%即排')}"},
                      {"k": "灰水箱", "v": f"{_rng(wa.get('grey', {}).get('tank_l', [30, 150]))}L，分流达标排放"},
                      {"k": "现状", "v": infra.get("结论", "排污点稀缺") + "（volatile，逐地核验）"}],
            "volatile": True}


def check_campground(vehicle_type: str | None, days: int | None = None,
                     peak_season: bool | None = None, booked: bool | None = None) -> dict:
    """营地与过夜：非房车走轻量过夜指引；房车未订→黄灯，旺季强调爆满，已订→绿灯。"""
    cg = data().get("campground", {})
    vt = data().get("vehicle_types", {})
    of = data().get("official_facilities", {})
    stop = of.get("stopover_discipline", "")
    # 非房车（轿车/SUV/MPV）：不套房车营地谱系，只给通用过夜停车指引
    if vehicle_type in ("sedan", "suv", "mpv"):
        note = (vt.get(vehicle_type, {}) or {}).get(
            "overnight", "野营合法性收紧，优先正规营地/经营性停车场，停车过夜遵守当地规定")
        return {"light": GREY, "title": "过夜与停车",
                "detail": f"{(vt.get(vehicle_type, {}) or {}).get('label', '')}非房车，不涉及营地补给。{note}",
                "action": "过夜优先正规停车场/营地；多地已收紧路边过夜与露营，出行前查当地最新规定。",
                "items": [], "volatile": True}
    if booked:
        return {"light": GREEN, "title": "营地与过夜",
                "detail": "已预订/确认营位。",
                "action": f"电话复核营位、水电、排污、过夜政策；{cg.get('booking', '拖挂占1.5-2车位，确认是否接受拖挂与排污')}。"
                          + (f" {stop}" if stop else ""),
                "items": [], "volatile": True}
    types = cg.get("types", [])
    type_line = " > ".join(
        f"{t.get('type')}(¥{_rng(t.get('cost_yuan_night', [0, 0]))})" for t in types) or \
        "房车营地(全补给) > 自驾车/景区营地(水电) > 乡村驿站(停车+公厕+补水) > 高速服务区(临时过夜)"
    detail = "未确认营地/过夜安排。"
    if peak_season:
        detail += cg.get("booking", "五一/十一等法定假期营地持续爆满，部分热门营地不接受预订、先到先得")
    elif days and days >= 3:
        detail += f"行程 {days} 天，需以营地/服务区为过夜补给锚点。"
    return {"light": YELLOW, "title": "营地与过夜",
            "detail": detail,
            "action": f"营地类型（供给递减）：{type_line}。旺季提前订、逐营电话确认排污与过夜政策。"
                      + (f" {stop}" if stop else ""),
            "items": [{"k": "标准", "v": " · ".join(cg.get("standards", [])) or "GB/T 31710 · TY/T 4001 · LB/T 078"},
                      {"k": "供给", "v": cg.get("supply", "全国营地3100+(宽口径)/约1287(标准化)，营地:车严重失衡")},
                      {"k": "证据优先", "v": (of.get("philosophy", {}) or {}).get(
                          "证据即可信度单位", "存『来源+公告日期』而非『能停』结论；有设施≠能过夜，出发前电话确认")}],
            "volatile": True}


# ── 汇总 ────────────────────────────────────────────────────

def rv_card(*, vehicle_type: str | None = None, length_m: float | None = None,
            gross_mass_kg: float | None = None, license_class: str | None = None,
            is_tow: bool | None = None, vehicle_height_m: float | None = None,
            route_low_clearance: bool | None = None, water_tank_l: float | None = None,
            people: int | None = None, days: int | None = None,
            battery_kwh: float | None = None, use_ac: bool | None = None,
            has_black_tank: bool | None = None, dump_plan: bool | None = None,
            peak_season: bool | None = None, booked: bool | None = None) -> dict:
    """汇总房车后勤自检，返回门禁卡结构（与 gate_card / moto_card 同构）。"""
    cards = [
        check_license(vehicle_type, length_m, gross_mass_kg, license_class, is_tow),
        check_height(vehicle_type, vehicle_height_m, route_low_clearance),
        check_resupply(water_tank_l, people, days, battery_kwh, use_ac),
        check_waste(vehicle_type, has_black_tank, dump_plan),
        check_campground(vehicle_type, days, peak_season, booked),
    ]
    counts = {l: sum(1 for c in cards if c["light"] == l) for l in (RED, YELLOW, GREEN, GREY)}
    blocked = counts[RED] > 0
    verdict = "blocked" if blocked else ("caution" if (counts[YELLOW] or counts[GREY]) else "clear")
    return {
        "cards": cards,
        "red": counts[RED], "yellow": counts[YELLOW],
        "green": counts[GREEN], "grey": counts[GREY],
        "blocked": blocked, "verdict": verdict,
        "vehicle_type": vehicle_type,
        "vehicle_logistics": (data().get("vehicle_types", {}) or {}).get(vehicle_type or ""),
    }


def rv_html(g: dict, dest: str = "") -> str:
    """房车后勤自检卡 HTML：与 gate_card / moto_card 视觉语言一致，直接嵌入小册子。"""
    if not g or not g.get("cards"):
        return ""
    lamps = ""
    for c in g["cards"]:
        bg, stroke, fg, ico = _STYLE[c["light"]]
        lamps += (f'<div style="flex:1;min-width:150px;background:{bg};border:1px solid {stroke};'
                  f'border-radius:12px;padding:12px 14px">'
                  f'<div style="font-size:12px;color:{fg};opacity:.85">{ico} {_CN[c["light"]]}灯</div>'
                  f'<div style="font-size:14px;font-weight:500;color:{fg};margin:3px 0 5px">'
                  f'{_esc(c["title"])}</div>'
                  f'<div style="font-size:12px;line-height:1.55;color:{fg}">'
                  f'{_esc(c["detail"][:68])}</div></div>')

    rows = ""
    for c in g["cards"]:
        bg, stroke, fg, ico = _STYLE[c["light"]]
        vol = ('<span class="feat-badge" style="margin-left:4px">易变·出行前核验</span>'
               if c.get("volatile") else "")
        extra = ""
        items = c.get("items") or []
        if items:
            extra = ('<ul class="kv" style="margin:4px 0 0">' + "".join(
                f'<li style="font-size:12.5px;line-height:1.6"><b>{_esc(it.get("k"))}</b>：'
                f'{_esc(it.get("v"))}</li>' for it in items if isinstance(it, dict)) + "</ul>")
        rows += (f'<li style="margin:0 0 10px"><b>{_esc(c["title"])}</b> '
                 f'<span class="feat-badge" style="background:{stroke}22;color:{fg};'
                 f'border:1px solid {stroke}">{ico} {_CN[c["light"]]}灯</span>{vol}'
                 f'<div style="font-size:13px;line-height:1.6;color:var(--sub);margin-top:3px">'
                 f'{_esc(c["detail"])}</div>'
                 f'<div style="font-size:13px;line-height:1.6;margin-top:3px">'
                 f'<b>要做什么：</b>{_esc(c["action"])}</div>{extra}</li>')

    vl = g.get("vehicle_logistics") or {}
    vt_html = ""
    if vl:
        cells = "".join(
            f'<div style="flex:1;min-width:140px;background:#F7F7F9;border-radius:10px;padding:9px 11px">'
            f'<div style="font-size:11.5px;color:var(--sub)">{_esc(k)}</div>'
            f'<div style="font-size:12.5px;line-height:1.5;margin-top:2px">{_esc(v)}</div></div>'
            for k, v in (("停车", vl.get("parking")), ("限高", vl.get("height")),
                         ("地库", vl.get("地库")), ("补给", vl.get("resupply")),
                         ("过夜", vl.get("overnight"))) if v)
        vt_html = (f'<div class="card"><h3>{_esc(vl.get("label", ""))}后勤速查'
                   f'<span class="feat-badge">按你声明的车型</span></h3>'
                   f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">{cells}</div></div>')

    verdict_html = {
        "blocked": ('<div class="card" style="border:1px solid #A32D2D;background:#FCEBEB">'
                    '<h3>⛔ 这趟房车行当前不成立</h3>'
                    '<p style="margin:0;font-size:13px;line-height:1.65;color:#501313">'
                    '存在红灯项：驾照/牌照与车型不匹配属违法上路，会让整趟行程归零。请先清掉红灯项再出发。</p></div>'),
        "caution": ('<div class="card" style="border:1px solid #BA7517;background:#FAEEDA">'
                    '<h3>⚠ 可以走，但后勤事项需先落实</h3>'
                    '<p style="margin:0;font-size:13px;line-height:1.65;color:#412402">'
                    '没有硬阻断。房车的难点不在「能不能开」，而在「停哪、补水充电、黑水灰水往哪排」——'
                    '排污设施稀缺，务必把正规营地/排污点作为路线硬节点，黄灯项出发前逐项电话确认，灰灯项不要默认没问题。</p></div>'),
        "clear": ('<div class="card" style="border:1px solid #639922;background:#EAF3DE">'
                  '<h3>✅ 后勤自检通过</h3>'
                  '<p style="margin:0;font-size:13px;line-height:1.65;color:#173404">'
                  '驾照牌照、限高、补给、排污、营地五项均已落实。价格/营位/路况为易变信息，出发前 1-3 天再核一次。</p></div>'),
    }[g["verdict"]]

    sub = "停哪、补水充电、黑水灰水往哪排——先解决后勤，再谈风景"
    if dest:
        sub = f"{_esc(dest)} ｜ " + sub
    return (f'<div class="sec-open" id="rv"><div class="sec-no">🚐</div><div>'
            f'<h2>房车 / 自驾后勤自检</h2>'
            f'<p class="sec-sub">{sub}</p></div></div>'
            f'<div class="card"><h3>后勤五项自检'
            f'<span class="feat-badge">'
            f'{"硬阻断" if g["blocked"] else ("待落实" if g["verdict"] == "caution" else "通过")}'
            f'</span></h3>'
            f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:6px">{lamps}</div></div>'
            + vt_html +
            f'<div class="card"><h3>逐项明细与行动项</h3><ul class="kv">{rows}</ul></div>'
            + verdict_html + route_emergency_html(g.get("total_km")))


def route_emergency_html(total_km: float | None = None) -> str:
    """路线优化原则 + 经典线路 caution + 应急要点（取自 rv_logistics，只给稳定事实与区间）。"""
    d = data()
    rt = d.get("route", {}); em = d.get("emergency", {})
    if not rt and not em:
        return ""
    dk = rt.get("daily_km") or [200, 350]
    if not isinstance(dk, (list, tuple)) or len(dk) < 2:
        dk = [dk[0] if isinstance(dk, (list, tuple)) and dk else 200,
              dk[-1] if isinstance(dk, (list, tuple)) and dk else 350]
    km_line = f"（本趟全程约 {total_km}km）" if total_km else ""
    of = d.get("official_facilities", {})
    stop = of.get("stopover_discipline", "")
    stop_li = (f'<li style="font-size:12.5px;line-height:1.6"><b>终点停靠·证据优先</b>：{_esc(stop)}</li>'
               if stop else "")
    head = (f'<div class="card"><h3>路线优化原则<span class="feat-badge">营地为节点</span></h3>'
            f'<ul class="kv" style="margin:6px 0 0">'
            f'<li style="font-size:12.5px;line-height:1.6"><b>节点法</b>：{_esc(rt.get("node_principle", ""))}</li>'
            f'<li style="font-size:12.5px;line-height:1.6"><b>日行里程</b>：约 {dk[0]}-{dk[1]}km/天'
            f'（房车舒适与安全经验值）{_esc(km_line)}</li>'
            f'<li style="font-size:12.5px;line-height:1.6"><b>限高优先</b>：{_esc(rt.get("height_first", ""))}</li>'
            f'<li style="font-size:12.5px;line-height:1.6"><b>高原</b>：{_esc(rt.get("plateau", ""))}</li>'
            + stop_li +
            f'</ul>')
    routes = rt.get("classic_routes") or []
    if routes:
        lis = "".join(
            f'<li style="margin:0 0 8px"><b>{_esc(r.get("name"))}</b>'
            + (f'（{_esc(r.get("path"))} · 建议{_esc(r.get("days"))}天）' if r.get("path") else "")
            + f'<div style="font-size:12.5px;line-height:1.55;color:var(--sub);margin-top:2px">'
              f'{_esc(r.get("caution"))}</div></li>'
            for r in routes)
        head += f'<h3 style="margin-top:12px">经典房车线路与注意</h3><ul class="kv" style="margin:4px 0 0">{lis}</ul>'
    head += "</div>"
    emer = ""
    if em:
        emer = (f'<div class="card"><h3>应急要点<span class="feat-badge">易变·出行前核验</span></h3>'
                f'<ul class="kv" style="margin:6px 0 0">'
                f'<li style="font-size:12.5px;line-height:1.6"><b>拖车救援</b>：{_esc(em.get("tow", ""))}</li>'
                f'<li style="font-size:12.5px;line-height:1.6"><b>高原装备</b>：{_esc(em.get("plateau_kit", ""))}</li>'
                f'<li style="font-size:12.5px;line-height:1.6"><b>极寒防护</b>：{_esc(em.get("cold", ""))}</li>'
                f'<li style="font-size:12.5px;line-height:1.6"><b>补给断档</b>：{_esc(em.get("supply_gap", ""))}</li>'
                f'</ul></div>')
    return head + emer


if __name__ == "__main__":
    import json
    print("── 案例1：C型房车，C1照，未确认排污/营地 ──")
    g = rv_card(vehicle_type="rv", length_m=5.9, gross_mass_kg=4200, license_class="C1",
                vehicle_height_m=3.0, water_tank_l=120, people=3, days=5,
                battery_kwh=5, use_ac=True)
    print(json.dumps({k: v for k, v in g.items() if k not in ("cards", "vehicle_logistics")}, ensure_ascii=False))
    for c in g["cards"]:
        print(f"  {_CN[c['light']]}灯 {c['title']}: {c['detail'][:46]}")
    print("\n── 案例2：拖挂无C6（应红灯阻断）──")
    g2 = rv_card(vehicle_type="rv", is_tow=True, license_class="C1")
    print("verdict:", g2["verdict"], "| red:", g2["red"])
    print("\n── 案例3：零数据房车（应灰灯，不断言蓝牌）──")
    g3 = rv_card(vehicle_type="rv")
    for c in g3["cards"]:
        print(f"  {_CN[c['light']]}灯 {c['title']}")
