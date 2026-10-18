#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摩旅可行性校验引擎 —— v0.1.1 摩旅模式核心

## 为什么单独做一个引擎（而不是塞进 gate_card）

出境的门禁问的是「能不能成行」——护照/签证/疫苗/保险。
摩托的门禁问的是另一件事：

    这辆车、这个人、这条路，合法吗？跑得下来吗？会不会半路被扣车？

两者都是"没解决就走不成"，但检查项完全不重叠，混在一起会让两边都变糊。
所以复用 gate_card 的**判定语义与渲染管道**（红/黄/绿/灰四灯 + 置顶拦停），
但自成一套检查器。

## 五项灯位（摩托特有）

  license   准驾车型与证件  —— D/E/F 照、行驶证、交强险。缺一项就是"无证驾驶"
  helmet    头盔与防护      —— 法定强制，不是可选项
  highway   高速准入        —— 逐省规定不同，闯了就是罚款+扣分
  ban       禁摩城区        —— 扣车级风险，一次中招整趟报废
  range     续航与加油半径  —— 最被低估、也最容易把人扔在路上的一项

## 最核心的设计纪律

**查不到就灰灯，绝不默认绿灯。**

摩托政策的特殊性在于：它是**逐省甚至逐城**的，而且变化频繁。
「北京禁摩、云南能上高速」这种省级差异，任何经验性描述都会害人。
因此：

  - 省份未收录 → grey + 「未收录，出发前必须自行核实」，不给"应该没事"
  - 用户没说排量 → grey，不按平均值猜
  - 政策条目带 stability 三档，volatile 项挂核验角标

一个灰灯的成本是用户多打一个电话；
一个假绿灯的成本是用户被扣车、被罚款，甚至出事故。
这笔账必须是这么算的。

用法：
    from moto_check import moto_card, moto_html
    card = moto_card(from_city="上海", to_city="黄山",
                     daily_km=280, displacement_cc=250,
                     has_license=True, license_class="E",
                     has_plate=True, has_insurance=True, has_helmet=True)
    print(moto_html(card))
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refloader

REF = Path(__file__).resolve().parent.parent / "references"
MOTO_RULES = REF / "moto_rules.json"
GEO_ADMIN = REF / "geo_admin.json"

RED, YELLOW, GREEN, GREY = "red", "yellow", "green", "grey"
_CN = {RED: "红", YELLOW: "黄", GREEN: "绿", GREY: "灰"}
_STYLE = {
    RED: ("#FCEBEB", "#A32D2D", "#791F1F", "⛔"),
    YELLOW: ("#FAEEDA", "#BA7517", "#633806", "⚠"),
    GREEN: ("#EAF3DE", "#639922", "#27500A", "✅"),
    GREY: ("#F1EFE8", "#888780", "#444441", "◐"),
}

# 安全续航系数：理论续航 × 此系数 = 你敢放心跑的里程。
# 0.7 的理由：山路油耗上浮、逆风、找加油站绕路、以及"不敢跑到最后一滴"的心理余量。
# 摩旅死在路上最常见的死法不是没油，是"以为还能跑"。
RANGE_SAFETY = 0.7


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load(path: Path) -> dict:
    """容错加载。文件缺失/损坏 → 返回空 dict，由上层走 grey，绝不抛异常中断行程。"""
    return refloader.load(path)


_RULES: dict | None = None
_GEO: dict | None = None


def rules() -> dict:
    global _RULES
    if _RULES is None:
        _RULES = _load(MOTO_RULES)
    return _RULES


# ── 行政区划：城市 → 省份 ────────────────────────────────────────────────
_PROV_INDEX: dict | None = None


def _prov_index() -> dict:
    """构建「地名 → 省份」索引。

    三层都索引：省级、地级市、县级。
    为什么必须含县级：摩旅目的地大量是县级市/县（康定市、丙中洛、独山子、贡山），
    只索引地级市会让「康定」查不到省份 → 途经省识别不全 → 高速准入漏判。

    同名冲突处理：县级「朝阳」（北京朝阳区 / 长春朝阳区）这类同名不同省的短名，
    一律标为歧义并返回空串 —— 与 geo_admin 的原则一致：不得静默取首个。
    """
    global _PROV_INDEX
    if _PROV_INDEX is not None:
        return _PROV_INDEX

    idx: dict[str, str] = {}
    ambiguous: set[str] = set()
    geo = _GEO if _GEO is not None else _load(GEO_ADMIN)

    def add(name: str | None, prov: str) -> None:
        if not name or not prov:
            return
        if name in idx:
            if idx[name] != prov:
                ambiguous.add(name)      # 同名不同省 → 歧义，不猜
            return
        if name in ambiguous:
            return
        idx[name] = prov

    # 顺序即优先级：省级 > 地级市 > 县级（用户更常说的是市名）
    for rec in (geo.get("province") or []):
        for k in (rec.get("keys") or []):
            add(k, rec.get("name") or "")
    for rec in (geo.get("city") or []):
        prov = rec.get("province") or ""
        for k in (rec.get("keys") or []):
            add(k, prov)
        add(rec.get("name"), prov)
    for rec in (geo.get("county") or []):
        prov = rec.get("province") or ""
        for k in (rec.get("keys") or []):
            add(k, prov)
        add(rec.get("name"), prov)

    for k in ambiguous:
        idx.pop(k, None)
    _PROV_INDEX = idx
    return idx


def _norm_prov(name: str) -> str:
    """省份名归一：'河北省'/'河北' → '河北'；'广西壮族自治区' → '广西'。"""
    if not name:
        return ""
    for suf in ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区",
                "自治区", "省", "市"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def province_of(city: str) -> str:
    """查城市所属省份（归一后的短名）。查不到返回空串——不猜。"""
    if not city:
        return ""
    idx = _prov_index()
    if city in idx:
        return _norm_prov(idx[city])
    # 去掉"市/区/县"后缀再试
    for suf in ("市", "地区", "自治州", "区", "县"):
        if city.endswith(suf) and city[: -len(suf)] in idx:
            return _norm_prov(idx[city[: -len(suf)]])
    # 前缀包含匹配（"黄山风景区" → "黄山"）
    for k, v in idx.items():
        if len(k) >= 2 and k in city:
            return _norm_prov(v)
    return ""


def _highway_record(prov: str) -> dict:
    """取某省的高速准入记录。支持 '河北'/'河北省' 两种键写法。"""
    table = rules().get("highway_access") or {}
    if prov in table:
        return table[prov] or {}
    for k, v in table.items():
        if _norm_prov(k) == prov:
            return v or {}
    return {}


# ── 五项检查器 ────────────────────────────────────────────────────────────
def check_license(has_license, license_class, has_plate, has_insurance) -> dict:
    """准驾车型与证件链。

    摩托车最容易被忽视的一环：很多人有 C1 汽车驾照就以为能骑摩托——
    实际上准驾车型不符按「无证驾驶」处理，可拘留。这条必须硬呈现。
    """
    chain = rules().get("license_chain") or {}
    got = []

    if has_license is None:
        return {"light": GREY, "title": "准驾车型与证件",
                "detail": "未提供驾照信息。摩托车准驾车型不符按无证驾驶处理，"
                          "这不是可以事后再说的项，因此本次不作通过判定。",
                "action": "确认你持有 D / E / F 准驾车型的摩托车驾驶证（C1 不能骑摩托），"
                          "并随身携带。",
                "items": got}

    if not has_license:
        return {"light": RED, "title": "准驾车型与证件",
                "detail": "未持有摩托车驾驶证。无证驾驶摩托车可处拘留并扣留车辆，"
                          "且发生事故时保险不予赔付。",
                "action": "这是硬阻断项：先考取 D / E / F 准驾车型驾驶证再上路。"
                          "持 C1 汽车驾照骑摩托同样按无证驾驶处理。",
                "items": got}

    lc = (license_class or "").strip().upper()
    lc_info = chain.get(lc) or {}
    got.append(f"驾驶证：{lc or '已持有（未注明准驾车型）'}"
               + (f"（{lc_info.get('desc')}）" if lc_info.get("desc") else ""))

    if has_plate is False:
        return {"light": RED, "title": "准驾车型与证件",
                "detail": "车辆无行驶证/未上牌。无牌上路可扣车，且多数加油站拒绝为无牌车加油。",
                "action": "硬阻断项：先完成上牌并取得行驶证。",
                "items": got}
    if has_plate:
        got.append("行驶证：已确认")

    if has_insurance is False:
        return {"light": RED, "title": "准驾车型与证件",
                "detail": "未投交强险。交强险是法定强制险，未投保不得上路，"
                          "且无法通过年检。",
                "action": "硬阻断项：先投保交强险（摩托车费率按排量分档）再出行。",
                "items": got}
    if has_insurance:
        got.append("交强险：已确认")

    missing = [k for k, v in (("行驶证", has_plate), ("交强险", has_insurance)) if v is None]
    if missing:
        return {"light": GREY, "title": "准驾车型与证件",
                "detail": f"未提供「{'、'.join(missing)}」的确认信息，本次无法判定。"
                          "这两项是路检必查项，不确认等于带着未知风险出门。",
                "action": f"出发前确认并随车携带：{'、'.join(missing)}，"
                          "以及身份证与驾驶证原件。",
                "items": got}

    # 准驾车型提示：D 优于 E 优于 F，F 只能骑轻便摩托
    if lc == "F":
        return {"light": YELLOW, "title": "准驾车型与证件",
                "detail": "持 F 照（轻便摩托车）——只能驾驶排量 ≤50cc、时速 ≤50km/h 的轻便摩托，"
                          "不可驾驶普通二轮摩托长途骑行。",
                "action": "若是长途摩旅，确认你的实际准驾车型为 E（普通二轮）或 D（三轮+二轮）。",
                "items": got}
    if lc and lc not in ("D", "E", "F"):
        # 关键：持汽车驾照（C1/C2/B2/A2…）骑摩托属于「准驾车型不符」，
        # 按无证驾驶处理 —— 可拘留 + 扣车 + 保险拒赔。这是红灯，不是提醒。
        # 把它降级成黄灯是危险的：用户会以为"有驾照就没大问题"。
        return {"light": RED, "title": "准驾车型与证件",
                "detail": f"准驾车型为「{lc}」，不是摩托车准驾车型。"
                          "持汽车等其它准驾车型驾驶摩托车，按「准驾车型不符」处理，"
                          "法律后果等同于无证驾驶：可处拘留、扣车，且事故时保险不予赔付。",
                "action": "硬阻断项：必须持有 D（三轮摩托+二轮）或 E（普通二轮）准驾车型"
                          "才能骑摩托长途。请先增驾。",
                "items": got}

    return {"light": GREEN, "title": "准驾车型与证件",
            "detail": "驾驶证、行驶证、交强险三项齐备。",
            "action": "随车携带原件；跨省骑行建议同时留存电子件与复印件，"
                      "证件防水袋收好。",
            "items": got}


def check_helmet(has_helmet) -> dict:
    """头盔：法定强制，且是致死率最高的防护项。"""
    if has_helmet is None:
        return {"light": GREY, "title": "头盔与防护装备",
                "detail": "未确认头盔情况。",
                "action": "确认佩戴符合标准的摩托车乘员头盔（非电动自行车头盔），"
                          "并配齐骑行手套、护膝、防风外层。",
                "items": []}
    if not has_helmet:
        return {"light": RED, "title": "头盔与防护装备",
                "detail": "未佩戴头盔。驾驶与乘坐摩托车均应按规定佩戴头盔，"
                          "这是法定要求，也是唯一能在摔车时把死亡率降下来的一半装备。",
                "action": "硬阻断项：备好合规头盔再上路。",
                "items": []}
    return {"light": GREEN, "title": "头盔与防护装备",
            "detail": "已配备头盔。",
            "action": "选全盔或 3/4 盔配面罩；长途再补骑行手套、护膝护肘、"
                      "防风防水外层（垭口体感比谷地低 10-15°C）。",
            "items": ["头盔：已确认"]}


_EV_LABEL = {
    "statute": "",                        # 有明文法条，最可靠，不加角标
    "practice": "（执法口径）",
    "third_party": "（第三方来源·需核实）",
}


def check_highway(provinces: list[str], prefer_highway: bool = False) -> dict:
    """途经省份的高速准入。

    这是摩托政策里最碎片化的一项：**没有全国统一规定**，
    有些省明确禁止、有些省允许、有些省按排量或路段附加条件。
    任何"一般来说可以"的表述在这里都是不负责任的。

    ## 灯色的关键判断（踩过坑）

    第一版把「某省禁止摩托上高速」直接判成红灯，导致「成都→康定」这种
    纯国道线路被判"这趟不成立"——**把"不能上高速"错当成了"不能去"**。

    摩托和汽车的根本差别在这里：汽车没高速基本就废了，摩托永远可以走国道。
    所以「该省禁摩上高速」的正确语义是【怎么去、多花多久】，不是【能不能去】。
    只有当你明确说"我要走高速"时，它才是硬阻断。
    """
    if not provinces:
        return {"light": GREY, "title": "高速准入（途经省份）",
                "detail": "未能识别途经省份，无法判定高速准入。"
                          "摩托车能否上高速由各省自行规定，不存在全国统一答案。",
                "action": "请提供明确的出发地、目的地与途经点，或自行按省份逐一核实。",
                "items": []}

    rows = []
    for p in provinces:
        rec = _highway_record(p)
        st = (rec.get("status") or "").lower()
        note = rec.get("note") or ""
        ev = rec.get("evidence") or ""
        stab = rec.get("stability") or "unknown"
        if st == "allowed":
            rows.append({"province": p, "status": "可上高速", "light": GREEN,
                         "note": (note or "该省允许摩托车上高速") + _EV_LABEL.get(ev, ""),
                         "evidence": ev, "stability": stab})
        elif st == "banned":
            rows.append({"province": p, "status": "禁止上高速", "light": RED,
                         "note": (note or "该省禁止摩托车上高速") + _EV_LABEL.get(ev, ""),
                         "evidence": ev, "stability": stab})
        elif st == "conditional":
            rows.append({"province": p, "status": "有条件通行", "light": YELLOW,
                         "note": (note or "需满足特定条件") + _EV_LABEL.get(ev, ""),
                         "evidence": ev, "stability": stab})
        else:
            rows.append({"province": p, "status": "未收录", "light": GREY,
                         "note": "本技能未收录该省规定，出行前必须自行核实——"
                                 "摩托车高速政策各省不同且会调整，此处不给推测结论。",
                         "evidence": "unknown", "stability": "unknown"})

    banned = [r for r in rows if r["light"] == RED]
    unk = [r for r in rows if r["light"] == GREY]
    cond = [r for r in rows if r["light"] == YELLOW]

    if banned and prefer_highway:
        return {"light": RED, "title": "高速准入（途经省份）",
                "detail": f"你计划走高速，但 {'、'.join(r['province'] for r in banned)} "
                          "明确禁止摩托车上高速。这条路线不成立。",
                "action": "硬阻断项：改走国道/省道，或调整路线绕开这些省份。",
                "items": rows}

    if banned:
        slow = "国道通常比高速慢 40-80%，请按此重算每天的里程与落脚点"
        return {"light": YELLOW, "title": "高速准入（途经省份）",
                "detail": f"{'、'.join(r['province'] for r in banned)} 禁止摩托车上高速。"
                          f"注意这不影响你去——走国道/省道即可——但{slow}。",
                "action": "导航不要用「驾车」模式（会把你导上高速），改用「摩托车」模式；"
                          "按国道速度重排每日里程，别按高速的时间估到达。",
                "items": rows}

    if cond or unk:
        parts = []
        if cond:
            parts.append(f"{'、'.join(r['province'] for r in cond)} 有条件通行（见明细）")
        if unk:
            parts.append(f"{'、'.join(r['province'] for r in unk)} 未收录规定，需自行核实")
        return {"light": YELLOW, "title": "高速准入（途经省份）",
                "detail": "；".join(parts) + "。",
                "action": "按明细逐省落实条件；未收录的省份请查该省交警官方渠道，"
                          "不要按邻近省份的习惯推断。",
                "items": rows}

    return {"light": GREEN, "title": "高速准入（途经省份）",
            "detail": f"途经 {'、'.join(p for p in provinces)}，均按已收录规定允许摩托车通行。",
            "action": "上高速前确认本车排量符合当地要求（部分省要求 ≥125cc、"
                      "设计时速 ≥70km/h），并注意部分路段仍有专项禁行。",
            "items": rows}


def check_ban(cities: list[str]) -> dict:
    """禁摩 / 限摩城区。

    ## 灯色判断（同样踩过坑）

    第一版把"命中禁摩名单"直接判红灯。但绝大多数禁摩是【区域内限行】，
    把车停在区域外换乘、或绕行通过，都是可行方案——这不是"走不成"，
    是"要多做一步功课"。所以命中 = 黄灯 + 绕行方案。

    真正不能给结论的是【未查证到权威来源】的城市（本库中标 stability=unknown）：
    既不能报红灯吓人，也不能报绿灯放行，只能给灰灯让用户自己去问。
    拿一个没根据的结论去吓用户，和拿假绿灯放行一样是错的。
    """
    if not cities:
        return {"light": GREY, "title": "禁摩 / 限摩城区",
                "detail": "未提供途经城市，无法判定是否穿越禁摩区。",
                "action": "提供途经城市后重算；或按各地交警公告自行核对禁摩边界。",
                "items": []}

    ban_list = rules().get("city_ban") or []
    if not ban_list:
        return {"light": GREY, "title": "禁摩 / 限摩城区",
                "detail": "禁摩城市名单未加载，本次无法判定。",
                "action": "出发前按途经城市逐一核实交警公告。",
                "items": []}

    hits, unknown_hits, clear_hits = [], [], []
    for c in cities:
        cn = c.rstrip("市区县")
        for rec in ban_list:
            rc = (rec.get("city") or "").rstrip("市区县")
            if not rc or not (rc == cn or (len(rc) >= 2 and rc in c)):
                continue
            scope = (rec.get("scope") or "").strip()
            stab = (rec.get("stability") or "unknown")
            if stab == "unknown" or not scope or "未查证" in scope:
                unknown_hits.append(rec)
            elif scope.startswith(("无", "目前无", "目前未")):
                clear_hits.append(rec)
            else:
                hits.append(rec)
            break

    def _row(h: dict) -> dict:
        return {"city": h.get("city"), "scope": h.get("scope") or "",
                "time": h.get("time") or "",
                "displacement_limit": h.get("displacement_limit"),
                "note": h.get("note") or "", "source": h.get("source") or "",
                "stability": h.get("stability") or "unknown"}

    if hits:
        names = "、".join(f"{h.get('city')}" for h in hits)
        detail = (f"途经 {names} 设有摩托车禁行/限行区域。"
                  "注意这不等于你去不了——多数禁摩是【区域内限行】，"
                  "绕行或把车停在区域外换乘即可——但绝不能抱着「骑进去再说」的心态，"
                  "罚款扣分是轻的，部分城市直接扣车。")
        if unknown_hits:
            detail += (f" 另外 {'、'.join(h.get('city') for h in unknown_hits)} "
                       "的禁摩政策本技能未查证到权威来源，需你自行核实。")
        return {"light": YELLOW, "title": "禁摩 / 限摩城区", "detail": detail,
                "action": "① 查清禁行区域边界与限行时段；② 规划绕行路线，"
                          "或把车停在禁摩区外的正规停车场再换乘公共交通进入；"
                          "③ 导航开启「摩托车」模式并勾选避开禁摩区。",
                "items": [_row(h) for h in hits + unknown_hits]}

    if unknown_hits:
        return {"light": GREY, "title": "禁摩 / 限摩城区",
                "detail": f"途经 {'、'.join(h.get('city') for h in unknown_hits)} 的禁摩政策，"
                          "本技能未查证到权威来源。本次不给结论——"
                          "报红灯是没有依据的恐吓，报绿灯是不负责任的放行。",
                "action": "出发前自行核实：查当地交警官方渠道，"
                          "或直接致电当地 12345 热线问「摩托车能否进入某某区域」。",
                "items": [_row(h) for h in unknown_hits]}

    if clear_hits:
        names = "、".join(h.get("city") for h in clear_hits)
        return {"light": GREEN, "title": "禁摩 / 限摩城区",
                "detail": f"途经 {names} 已核实为不设全域禁摩（详见明细）。",
                "action": "注意：不限摩不等于任何路段都能走，"
                          "快速路、高架、隧道与部分景区道路仍可能单独禁行，按现场标志走。",
                "items": [_row(h) for h in clear_hits]}

    return {"light": GREEN, "title": "禁摩 / 限摩城区",
            "detail": f"途经 {'、'.join(cities)} 未命中已知禁摩城市名单。",
            "action": "注意：未命中只表示不在本库已知名单内，不表示绝对不禁摩。"
                      "部分城市对特定路段/时段有临时管制，出发前仍建议查一次当地交警公告。",
            "items": []}


def check_range(daily_km, total_km, displacement_cc, tank_l=None, range_km=None,
                prefer_highway: bool = False) -> dict:
    """续航与加油半径 —— 摩旅最硬的约束，也是汽车思维最容易漏掉的一项。

    汽车一箱油 600-800km，服务区密布，从来不用想"下一个加油站在哪"。
    摩托不是：125cc 续航 300km 上下，山区实际更低，而国道加油站间距可达 100km+。
    所以这一项不是"顺便提一句"，是必须算出来的。
    """
    fm = rules().get("fuel_model") or {}

    if range_km is None and displacement_cc is None:
        return {"light": GREY, "title": "续航与加油半径",
                "detail": "未提供排量或实际续航。摩托续航因车型、载重、路况差异极大，"
                          "按平均值估算会给出误导性的结论，因此本次不估算。",
                "action": "告诉我你的排量（如 250cc）或实际续航里程，"
                          "我可以算出这段路需要几次加油、哪一段最长无补给。",
                "items": []}

    # 解析续航：优先用户实测值，否则按排量查基线
    src = ""
    if range_km:
        theory = float(range_km)
        src = "你提供的实际续航"
    else:
        key = None
        for k in fm.get("displacement_bands", {}):
            try:
                lo, hi = [float(x) for x in str(k).replace("cc", "").split("-")]
            except Exception:
                continue
            if lo <= float(displacement_cc) <= hi:
                key = k
                break
        band = fm.get("displacement_bands", {}).get(key) if key else None
        if not band:
            return {"light": GREY, "title": "续航与加油半径",
                    "detail": f"未收录 {displacement_cc}cc 的续航基线，无法估算。",
                    "action": "直接告诉我你的实际续航里程（满油能跑多少公里）即可。",
                    "items": []}
        theory = float(band.get("range_km_mid") or band.get("range_km") or 0)
        if not theory:
            return {"light": GREY, "title": "续航与加油半径",
                    "detail": f"{displacement_cc}cc 的续航基线数据不可用。",
                    "action": "告诉我实际续航里程即可。",
                    "items": []}
        src = f"{displacement_cc}cc 基线"

    safe = theory * RANGE_SAFETY
    d_km = float(daily_km) if daily_km else None
    t_km = float(total_km) if total_km else None

    # ── 加油动作序列 ────────────────────────────────────────────────
    # 学自备用地图服务摩托车出行智能体的「高速前 2km 挑服务区」：
    # 原版只给"满油续航 X km / 预计加油 N 次"这类数字，用户拿到还是不知道
    # 什么时候该干什么。这里把数字翻译成**可执行的决策点**——什么时候、
    # 在多少公里处、做什么动作、为什么。
    actions: list[dict] = [{
        "at": "出发前", "do": "加满油",
        "why": ("高速服务区间距 40-60km，摩托在高速上不能掉头找站；"
                "部分禁摩省一旦被劝返就得临时改国道，满油是唯一退路"
                if prefer_highway else
                "国道首段往往最长，出发前满油是后面所有决策的基线"),
    }]
    refuels: list[dict] = []
    if t_km:
        # 贪心设站：剩余里程超过安全续航才设一站（尊重安全系数，不用满油续航贪心）
        pos, remaining = 0.0, t_km
        while remaining > safe:
            pos += safe
            remaining -= safe
            refuels.append({"at_km": round(pos), "left_km": round(theory - safe),
                            "after_km": round(remaining)})
        for r in refuels:
            tail = ""
            if r["after_km"] <= safe * 0.5:
                tail = (f"；此站之后仅剩 {r['after_km']}km 即抵达，"
                        f"若全程满油出发且未绕路，此站为保险站，可视实际油量跳过")
            r["note"] = (f"从上一站满油出发跑到此处约耗 {round(safe)}km 行程当量，"
                         f"加满后约还能跑 {r['left_km']}km{tail}")
            actions.append({
                "at": f"全程约 {r['at_km']}km 处", "do": "加油",
                "why": r["note"],
            })
        actions.append({
            "at": "抵达前最后一站", "do": "不要等亮灯",
            "why": f"全程 {round(t_km)}km 需加油 {len(refuels)} 次，"
                   f"把「油量低于 1/2 见站即加」当硬规则执行",
        })

    plan = {
        "theory_range_km": round(theory),
        "safe_range_km": round(safe),
        "safety_factor": RANGE_SAFETY,
        "source": src,
        "tank_l": tank_l,
        "fuel_actions": actions,
        "refuel_points": refuels,
    }
    if t_km:
        plan["total_km"] = round(t_km)
        plan["expected_refuels"] = len(refuels)
        # 最长无补给段：除末段外每段都按安全续航切分，故最长段 ≤ 安全续航
        plan["longest_gap_km"] = round(min(safe, t_km))
    if d_km:
        plan["daily_km"] = round(d_km)

    if d_km and d_km > theory:
        return {"light": RED, "title": "续航与加油半径",
                "detail": f"单日 {round(d_km)}km 超过满油续航 {round(theory)}km。"
                          "必须中途加油，而中途是否有站、站间距多远决定了这趟能不能跑完。",
                "action": "把单日里程压到安全续航以内，或提前确认途中的加油站分布并标注备选点。",
                "items": plan}
    if d_km and d_km > safe:
        first_stop = round(safe)
        return {"light": YELLOW, "title": "续航与加油半径",
                "detail": f"单日 {round(d_km)}km 超过安全续航 {round(safe)}km"
                          f"（满油 {round(theory)}km × {RANGE_SAFETY} 安全系数）。"
                          f"最晚必须在出发后约 {first_stop}km 处补油。",
                "action": f"现在就做两件事：① 出发前加满；"
                          f"② 在地图上标出前 {first_stop}km 内的第一个加油站，"
                          f"把它当强制停靠点而不是顺路选项。",
                "items": plan}
    if d_km:
        return {"light": GREEN, "title": "续航与加油半径",
                "detail": f"单日 {round(d_km)}km 在安全续航 {round(safe)}km 以内。",
                "action": "仍按「油量低于 1/2 见站即加」执行——山区与长段无村镇路段"
                          "的实际油耗会高于平路。",
                "items": plan}
    return {"light": GREY, "title": "续航与加油半径",
            "detail": f"满油续航约 {round(theory)}km（安全续航 {round(safe)}km），"
                      "但未提供行程里程，无法判断是否需要中途补油。",
            "action": "提供单日或全程里程后重算。",
            "items": plan}


# ── 线路推荐 ──────────────────────────────────────────────────────────────
_ROUTES: dict | None = None


def routes() -> dict:
    global _ROUTES
    if _ROUTES is None:
        _ROUTES = _load(REF / "moto_routes.json")
    return _ROUTES


def all_routes() -> list[dict]:
    """把 near/long/loop 三组摊平成一维，并补上分组标记。"""
    out = []
    db = routes()
    for g in ("near", "long", "loop"):
        blk = db.get(g) or {}
        for r in (blk.get("routes") or []):
            item = dict(r)
            item["group"] = g
            item["group_label"] = blk.get("label", "")
            out.append(item)
    return out


def _days_of(r: dict) -> tuple:
    """把 '1-2' / '10-15' 解析成 (lo, hi)。解析不出就给宽区间，不误杀。"""
    s = str(r.get("days") or "").replace("天", "").strip()
    if "-" in s:
        try:
            a, b = s.split("-")[:2]
            return float(a), float(b)
        except Exception:
            return 0.0, 999.0
    try:
        v = float(s)
        return v, v
    except Exception:
        return 0.0, 999.0


_SHADE_RANK = {"高": 3, "中": 2, "低": 1}


def _season_covers_summer(season: str) -> bool:
    """判断季节串是否覆盖 6/7/8 月中的任一个月。

    「5-6月、9-10月」这种写法覆盖 6 月，属夏季窗口——暴晒建议必须触发。
    用月份解析而非字符串包含：'5-9' 这类简写会漏，'10月-次年4月' 不该误命中。
    """
    s = season or ""
    months: set[int] = set()
    for m in re.finditer(r"(\d{1,2})\s*月", s):
        months.add(int(m.group(1)))
    for m in re.finditer(r"(\d{1,2})\s*[-~—]\s*(\d{1,2})\s*月", s):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b:
            months.update(range(a, b + 1))
    return bool(months & {6, 7, 8})


def shade_advice(shade: str, season: str = "") -> str:
    """按线路绿荫等级给暴晒防护建议。

    学自备用地图服务摩托车出行智能体的「绿荫优先」：暴晒是摩托党大敌，
    但智能体只回答问题不拦截——这里在选线阶段就把防护要求一次说清。
    """
    s = (shade or "").strip()
    if s == "高":
        base = "线路林荫覆盖好，但长袖仍建议穿着：林荫段光线暗、出荫点紫外线骤增。"
    elif s == "中":
        base = ("林荫间断分布，正午务必择荫休息；防晒按 SPF50+ 准备，"
                "颈后与手背是最容易漏涂的部位。")
    elif s == "低":
        base = ("高原/戈壁/开阔段基本无遮蔽，防晒是硬要求：SPF50+ 每 2 小时补涂、"
                "长袖骑行服、面巾+墨镜四件套，每 1-1.5 小时强制停车补水。")
    else:
        return ""
    if _season_covers_summer(season):
        base += "所选时段覆盖夏季，建议把骑行时段压到 7:00-11:00 / 15:00-18:00。"
    return base


def suggest_routes(days=None, level_max=None, region=None, group=None, limit=3,
                   shade_min: str | None = None, shade_first: bool = False) -> list[dict]:
    """按天数 / 难度 / 地区筛线路，支持绿荫优先。

    shade_min：最低绿荫等级（高/中/低），如 "中" 表示不要全无遮蔽的线路；
    shade_first：绿荫优先排序——把 shade 等级放在难度之前，暴晒规避优先于压弯体验。

    没有匹配项时返回空列表 —— 不硬凑一条来填版面。
    「宁可说没有合适的现成线路」，也不要拿一条不匹配的线路糊弄用户。
    """
    out = []
    for r in all_routes():
        if group and r["group"] != group:
            continue
        if level_max is not None and int(r.get("level", 5)) > int(level_max):
            continue
        if shade_min:
            if _SHADE_RANK.get(r.get("shade", ""), 0) < _SHADE_RANK.get(shade_min, 0):
                continue
        if region and region not in ((r.get("region") or "") + (r.get("path") or "")):
            continue
        if days:
            lo, hi = _days_of(r)
            if not (lo <= float(days) <= hi):
                continue
        out.append(r)
    if shade_first:
        out.sort(key=lambda x: (-_SHADE_RANK.get(x.get("shade", ""), 0),
                                int(x.get("level", 5)), -int(x.get("km", 0))))
    else:
        out.sort(key=lambda x: (int(x.get("level", 5)), -int(x.get("km", 0))))
    return out[:limit]


CHECKERS = {
    "license": check_license,
    "helmet": check_helmet,
    "highway": check_highway,
    "ban": check_ban,
    "range": check_range,
}


def moto_card(*, from_city=None, to_city=None, via_cities=None,
              daily_km=None, total_km=None, displacement_cc=None,
              tank_l=None, range_km=None, prefer_highway=False,
              has_license=None, license_class=None,
              has_plate=None, has_insurance=None, has_helmet=None) -> dict:
    """汇总五项摩旅检查，返回门禁卡结构（与 gate_card 同构，便于共用渲染管道）。"""
    route_cities = [c for c in ([from_city, to_city] + list(via_cities or [])) if c]
    provinces = []
    for c in route_cities:
        p = province_of(c)
        if p and p not in provinces:
            provinces.append(p)

    cards = [
        check_license(has_license, license_class, has_plate, has_insurance),
        check_helmet(has_helmet),
        check_highway(provinces, prefer_highway=prefer_highway),
        check_ban(route_cities),
        check_range(daily_km, total_km, displacement_cc, tank_l, range_km,
                    prefer_highway=prefer_highway),
    ]
    counts = {l: sum(1 for c in cards if c["light"] == l) for l in (RED, YELLOW, GREEN, GREY)}
    blocked = counts[RED] > 0
    verdict = "blocked" if blocked else ("caution" if (counts[YELLOW] or counts[GREY]) else "clear")
    return {
        "cards": cards,
        "red": counts[RED], "yellow": counts[YELLOW],
        "green": counts[GREEN], "grey": counts[GREY],
        "blocked": blocked, "verdict": verdict,
        "provinces": provinces,
        "route_cities": route_cities,
    }


def moto_html(g: dict, dest: str = "") -> str:
    """摩旅门禁卡 HTML：与 gate_card 的视觉语言一致，直接嵌入小册子。"""
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
        extra = ""
        items = c.get("items") or []
        if c["title"].startswith("高速准入") and items:
            chips = ""
            for it in items:
                _, s2, f2, i2 = _STYLE.get(it.get("light", GREY), _STYLE[GREY])
                chips += (f'<span class="feat-badge" style="background:{s2}22;color:{f2};'
                          f'border:1px solid {s2};margin:2px 4px 2px 0;display:inline-block">'
                          f'{_esc(it.get("province"))} · {_esc(it.get("status"))}</span>')
            extra += f'<div style="margin:6px 0 2px">{chips}</div>'
            notes = [it for it in items if it.get("note")]
            if notes:
                extra += ('<ul class="kv" style="margin:4px 0 0">' + "".join(
                    f'<li style="font-size:12.5px;line-height:1.6">{_esc(n.get("province"))}：'
                    f'{_esc(n.get("note"))}</li>' for n in notes) + "</ul>")
        if c["title"].startswith("禁摩") and items:
            extra += ('<ul class="kv" style="margin:4px 0 0">' + "".join(
                f'<li style="font-size:12.5px;line-height:1.6"><b>{_esc(h.get("city"))}</b>：'
                f'{_esc(h.get("scope") or "")}'
                + (f' · {_esc(h.get("time"))}' if h.get("time") else "")
                + (f' · {_esc(h.get("note"))}' if h.get("note") else "") + "</li>"
                for h in items) + "</ul>")
        if c["title"].startswith("续航") and isinstance(c.get("items"), dict) and c["items"]:
            p = c["items"]
            kv = []
            if p.get("theory_range_km"):
                kv.append(f"满油续航 ≈ {p['theory_range_km']}km")
            if p.get("safe_range_km"):
                kv.append(f"安全续航 ≈ {p['safe_range_km']}km（×{p.get('safety_factor')}）")
            if p.get("daily_km"):
                kv.append(f"单日 {p['daily_km']}km")
            if p.get("total_km"):
                kv.append(f"全程 {p['total_km']}km · 预计加油 {p.get('expected_refuels', 0)} 次"
                          f" · 最长无补给段 {p.get('longest_gap_km', 0)}km")
            if kv:
                extra += (f'<div style="font-size:12.5px;line-height:1.7;margin-top:5px">'
                          f'{" · ".join(kv)}</div>')
            # 加油动作序列：把数字变成可执行决策点
            acts = p.get("fuel_actions") or []
            if acts:
                extra += ('<div style="font-size:12.5px;font-weight:600;margin:8px 0 2px">'
                          '加油决策点（按顺序执行）</div><ul class="kv" style="margin:2px 0 0">'
                          + "".join(
                              f'<li style="font-size:12.5px;line-height:1.6">'
                              f'<b>{_esc(a.get("at"))}</b> → {_esc(a.get("do"))}'
                              f'：{_esc(a.get("why"))}</li>' for a in acts) + "</ul>")

        rows += (f'<li style="margin:0 0 10px"><b>{_esc(c["title"])}</b> '
                 f'<span class="feat-badge" style="background:{stroke}22;color:{fg};'
                 f'border:1px solid {stroke}">{ico} {_CN[c["light"]]}灯</span>'
                 f'<div style="font-size:13px;line-height:1.6;color:var(--sub);margin-top:3px">'
                 f'{_esc(c["detail"])}</div>'
                 f'<div style="font-size:13px;line-height:1.6;margin-top:3px">'
                 f'<b>要做什么：</b>{_esc(c["action"])}</div>{extra}</li>')

    verdict_html = {
        "blocked": ('<div class="card" style="border:1px solid #A32D2D;background:#FCEBEB">'
                    '<h3>⛔ 这趟摩旅当前不成立</h3>'
                    '<p style="margin:0;font-size:13px;line-height:1.65;color:#501313">'
                    '存在红灯项。摩托不同于汽车：证件不齐是违法上路，闯禁摩区是直接扣车，'
                    '两者都会让整趟行程归零。请先清掉红灯项再出发。</p></div>'),
        "caution": ('<div class="card" style="border:1px solid #BA7517;background:#FAEEDA">'
                    '<h3>⚠ 可以走，但有事项需先落实</h3>'
                    '<p style="margin:0;font-size:13px;line-height:1.65;color:#412402">'
                    '没有硬阻断。黄灯项需在出发前确认，灰灯项请不要默认它没问题——'
                    '摩托政策是逐省逐城的，一个电话比一次扣车便宜得多。</p></div>'),
        "clear": ('<div class="card" style="border:1px solid #639922;background:#EAF3DE">'
                  '<h3>✅ 五项自检通过</h3>'
                  '<p style="margin:0;font-size:13px;line-height:1.65;color:#173404">'
                  '证件、防护、高速准入、禁摩、续航五项均无问题。'
                  '政策类信息请在出发前 1-3 天再核一次。</p></div>'),
    }[g["verdict"]]

    return (f'<div class="sec-open" id="moto"><div class="sec-no">🏍</div><div>'
            f'<h2>摩旅可行性自检</h2>'
            f'<p class="sec-sub">这辆车、这个人、这条路——合法且跑得下来吗</p></div></div>'
            f'<div class="card"><h3>摩托五项门禁'
            f'<span class="feat-badge">'
            f'{"硬阻断" if g["blocked"] else ("待落实" if g["verdict"] == "caution" else "通过")}'
            f'</span></h3>'
            f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:6px">{lamps}</div></div>'
            f'<div class="card"><h3>逐项明细与行动项</h3><ul class="kv">{rows}</ul></div>'
            + verdict_html)


if __name__ == "__main__":
    import sys
    print("── 案例1：证件不全 + 单日超续航 ──")
    g = moto_card(from_city="上海", to_city="黄山", daily_km=350,
                  displacement_cc=250, has_license=True, license_class="C1",
                  has_plate=True, has_insurance=True, has_helmet=True)
    print(json.dumps({k: v for k, v in g.items() if k != "cards"}, ensure_ascii=False))
    print("途经省:", g["provinces"])
    for c in g["cards"]:
        print(f"  {_CN[c['light']]}灯 {c['title']}: {c['detail'][:50]}")
    print()
    print("── 案例2：全部齐备 ──")
    g2 = moto_card(from_city="成都", to_city="康定", daily_km=280, total_km=560,
                   displacement_cc=500, has_license=True, license_class="E",
                   has_plate=True, has_insurance=True, has_helmet=True)
    print(json.dumps({k: v for k, v in g2.items() if k != "cards"}, ensure_ascii=False))
    print("途经省:", g2["provinces"])
    for c in g2["cards"]:
        print(f"  {_CN[c['light']]}灯 {c['title']}: {c['detail'][:50]}")
    print()
    print("── 案例3：信息缺失（不得默认绿灯）──")
    g3 = moto_card(from_city="北京", to_city="天津")
    print(json.dumps({k: v for k, v in g3.items() if k != "cards"}, ensure_ascii=False))
    print("灰灯数:", g3["grey"], "| verdict:", g3["verdict"])
    print()
    print("── 案例4：未查证城市（不得报红灯，也不得报绿灯）──")
    g4 = moto_card(from_city="珠海", to_city="中山", displacement_cc=250,
                   has_license=True, license_class="E",
                   has_plate=True, has_insurance=True, has_helmet=True)
    ban4 = [c for c in g4["cards"] if c["title"].startswith("禁摩")][0]
    print("禁摩灯色:", _CN[ban4["light"]], "|", ban4["detail"][:60])
    print("verdict:", g4["verdict"], "| red:", g4["red"], "grey:", g4["grey"])
    print()
    print("── 案例5：明确要走高速 + 途经禁止省 → 硬阻断 ──")
    g5 = moto_card(from_city="成都", to_city="康定", prefer_highway=True,
                   displacement_cc=250, has_license=True, license_class="E",
                   has_plate=True, has_insurance=True, has_helmet=True)
    hw5 = [c for c in g5["cards"] if c["title"].startswith("高速")][0]
    print("高速灯色:", _CN[hw5["light"]], "|", hw5["detail"][:60])
    print("blocked:", g5["blocked"])
    print()
    print("── 案例6：线路推荐 ──")
    for r in suggest_routes(days=2, limit=3):
        print(f"   · {r['name']} ({r['group_label']} · {r['km']}km · level {r['level']})")
    print("HTML 长度:", len(moto_html(g2, "康定")))
    sys.exit(0)
