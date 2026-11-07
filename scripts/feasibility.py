#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可执行性体检引擎（零依赖）：阈值自检 + 目的地 P0 关卡覆盖检测 + 末班船时间一致性断言。

自 render_booklet.py 抽出为单独模块：v0.1.14 起默认渲染器为 render_compact.py，
它只需这一块能力（`--feasibility strict|advisory|none`），无需整个 Apple 风渲染器。
抽出保持原实现逐字等价，未改动任何判据阈值或结论口径。
"""
import json
import re
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "references"


def load_json(p) -> dict:
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def load_feas_rules() -> dict:
    d = load_json(REF / "feasibility_check.json")
    d.setdefault("max_spots_per_day", 6)
    d.setdefault("max_drive_hours", 8)
    d.setdefault("late_hour", 21)
    d.setdefault("altitude_min_days", 3)
    d.setdefault("altitude_threshold_m", 3000)
    d.setdefault("long_trip_days", 7)
    d.setdefault("transfer_max_spots", 3)
    d.setdefault("tips", {})
    return d


def _collect_places(plan) -> set:
    places = set()
    if plan.get("origin"):
        places.add(plan["origin"])
    for d in (plan.get("destinations") or []):
        if isinstance(d, str):
            places.add(d)
        elif isinstance(d, dict):
            places.add(d.get("name") or d.get("city") or "")
    for day in (plan.get("plan") or []):
        c = day.get("city")
        if c:
            places.add(c)
    places.discard("")
    return places


def _resolve_gate_rules(place: str, rules: dict):
    dests = rules.get("destinations") or {}
    seen = set()
    cur = place
    while cur and cur not in seen:
        seen.add(cur)
        node = dests.get(cur)
        if node and "gates" in node:
            return node["gates"]
        if node and "alias_of" in node:
            cur = node["alias_of"]
            continue
        return None
    return None


def _plan_text(plan) -> str:
    parts = []
    for day in (plan.get("plan") or []):
        parts.append(day.get("city") or "")
        for s in (day.get("slots") or []):
            parts.append((s.get("label") or "") + " " + (s.get("desc") or ""))
        if day.get("note"):
            parts.append(day["note"])
    for k in ("tips", "safety"):
        v = plan.get(k)
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v))
        elif isinstance(v, dict):
            parts.append(" ".join(str(x) for x in v.values()))
    t = plan.get("transit")
    if isinstance(t, dict):
        parts.append(" ".join(str(x) for x in t.values()))
    return "\n".join(parts)


def _slot_hour(raw):
    """从 'HH:MM' / 'HH点' / '14:30 抵达' 里取小时；取不到返回 None。

    v0.2.1 修：旧实现逐字符读到非数字为止，'2100'（HHMM 写法）会被拼成
    2100 → 输出「末段约 2100:00 仍安排在外」这种不存在的时刻。只认 0–23。
    """
    m = re.match(r"\s*(\d{1,2})\s*[:：点時时]", str(raw or ""))
    if not m:
        return None
    h = int(m.group(1))
    return h if 0 <= h <= 23 else None


# 末班船的不同说法（v0.2.1 修）
_FERRY_KW = ("末班船", "末班渡轮", "末班轮渡", "末班游船", "末班渡船")


def _time_near(text: str, keywords):
    """在关键词后 40 字内找第一个 HH:MM。

    v0.2.1 修：旧实现只找「末班」，于是「末班车 18:00 … 末班船 17:30」会把
    **末班车**的 18:00 当成末班船时间，再拿它跟权威值 17:30 比对，
    报出一条假的 P0「冲突」——误报会让人真的去信一个不存在的时间。
    现在只认「末班船」类词，且取每个关键词里最早出现的那处。
    """
    if isinstance(keywords, str):
        keywords = (keywords,)
    best = None
    for kw in keywords:
        idx = text.find(kw)
        if idx < 0:
            continue
        if best is None or idx < best:
            best = idx
    if best is None:
        return None
    seg = text[best: best + 40]
    m = re.search(r"(\d{1,2})[:：](\d{2})", seg)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def run_feasibility(plan: dict, rules: dict | None = None) -> dict:
    """零依赖可行性体检引擎：阈值自检 + 目的地 P0 关卡覆盖检测 + 末班船时间一致性断言。"""
    if rules is None:
        rules = load_feas_rules()
    threshold, p0, assert_issues = [], [], []
    days = plan.get("plan", []) or []
    tips = rules.get("tips", {})
    mpd = rules.get("max_spots_per_day", 6)
    late = rules.get("late_hour", 21)
    # ── 阈值自检（节奏/体力）──
    for day in days:
        dno = day.get("day", "?")
        try:
            spots = int(day.get("spots") or 0)
        except Exception:
            spots = 0
        if spots > mpd:
            threshold.append(f"D{dno} 排了 {spots} 个点位，超过单日建议上限 {mpd}——{tips.get('too_many_spots','')}")
        latest = 0
        for s in day.get("slots", []):
            h = _slot_hour(s.get("time", ""))
            if h is not None and h > latest:
                latest = h
        if latest and latest > late:
            threshold.append(f"D{dno} 末段约 {latest}:00 仍安排在外，注意末班车与夜间安全——{tips.get('late_night','')}")
    # ── 高海拔判据 ──
    # v0.2.1 修：旧实现读 plan["high_altitude"]，但 build_itinerary 与 render_compact
    # 全仓库从未设置该字段（grep 命中 0 次）→ altitude_min_days 是永远走不到的死代码。
    # 本地没有权威海拔库，绝不猜目的地海拔；改为显式契约：调用方给海拔才判，
    # 给 high_altitude=True 或 max_altitude_m>=altitude_threshold_m 才触发。
    _alt_m = plan.get("max_altitude_m")
    _high_alt = bool(plan.get("high_altitude"))
    if not _high_alt and isinstance(_alt_m, (int, float)):
        _high_alt = _alt_m >= rules.get("altitude_threshold_m", 3000)
    if _high_alt and len(days) < rules.get("altitude_min_days", 3):
        threshold.append(tips.get("altitude", ""))
    if len(days) >= rules.get("long_trip_days", 7) and not any((day.get("label") or "").find("休") >= 0 for day in days):
        threshold.append(tips.get("long_trip", ""))
    for day in days:
        if day.get("transfer"):
            try:
                sp = int(day.get("spots") or 0)
            except Exception:
                sp = 0
            if sp > rules.get("transfer_max_spots", 3):
                threshold.append(f"D{day.get('day')} 为跨城转场日仍排 {sp} 个点位——{tips.get('tight_transfer','')}")
    # ── 目的地 P0 关卡覆盖检测 ──
    places = _collect_places(plan)
    origin = plan.get("origin")
    visited_origin = any((d.get("city") or "") == origin for d in days)
    if origin and not visited_origin:
        places.discard(origin)  # 纯出发地不触发景点类关卡
    text = _plan_text(plan)
    # 任何在行程文本中出现的已知目的地/景点关键词，也纳入关卡检测（spots 不以城市维度出现时也能抓到）
    for key in (rules.get("destinations") or {}):
        if key == origin:
            continue  # 出发地不在文本扫描里触发
        if key in text:
            places.add(key)
    kw = rules.get("gate_keywords", {})
    for place in sorted(places):
        gr = _resolve_gate_rules(place, rules)
        if not gr:
            continue
        for gtype, g in gr.items():
            covered = any(k in text for k in kw.get(gtype, []))
            if not covered:
                p0.append({"level": g.get("level", "P2"), "place": place,
                           "gate": gtype, "text": g.get("text", "")})
            asr = g.get("assert")
            if asr and asr.get("type") == "last_ferry":
                stated = _time_near(text, _FERRY_KW)
                if stated and stated != asr["value"]:
                    assert_issues.append({
                        "level": "P0", "place": place,
                        "text": f"行程写「末班船 {stated}」与权威值「{asr['value']}」冲突——请复核真实末班时间，避免误船。"})
    return {"threshold": threshold, "p0": p0, "assert": assert_issues}
