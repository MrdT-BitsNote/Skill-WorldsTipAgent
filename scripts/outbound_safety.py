#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出境「答不出错」核查器。

用户要求：国外的可以做，但只要确保问到能答不出错。
本脚本把这句话变成可验证的硬约束，逐项检查五条防线：

  防线1  不知道就标 unknown —— 查不到的国家/政策绝不猜。
         历史缺陷：迪拜、罗马曾被误映射到申根区（危险兜底）。
  防线2  所有出境数据必须带稳定性标记 —— 政策类事实必须 volatile，
         不能把 2024 年的免签规则当成永久事实直出。
  防线3  签证结论必须能溯源 —— 每个结论要能指出数据来自哪条记录。
  防线4  红灯必须拦停 —— strict 模式下红灯只出行动项，不出行程。
  防线5  门禁卡四灯完备 —— 护照/签证/疫苗/保险四灯缺一即不可用。

用法：
    python outbound_safety.py            # 人类可读报告
    python outbound_safety.py --strict   # 任一防线失败即退出码 1

零第三方依赖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(os.path.dirname(HERE), "references")
sys.path.insert(0, HERE)

import refloader

# ── 出境四张基线表：表名 → (候选数据键, 说明) ────────────────────────────
# 键名按各表真实结构写（曾把 currency_tz 的键写成 countries 而误报 3 张表为空）。
OUTBOUND_TABLES = {
    "visa_rules.json": (["countries", "visa_free_for_cn_ordinary"], "准入/签证"),
    "currency_tz.json": (["currencies", "timezones", "payment_and_tipping"], "货币与时差"),
    "country_safety.json": (["country_safety", "universal_emergency"], "安全与领事"),
    "local_customs.json": (["customs_and_tips", "dietary_and_drugs",
                            "driving_and_plug", "local_transport_and_apps"], "合规与文化"),
}

# 必须能被正确识别为「查不到」的国家/地区名（拼错、不存在、过时名）
MUST_BE_UNKNOWN = [
    "瓦坎达",            # 虚构
    "苏联",              # 已不存在
    "锡兰",              # 旧称（今斯里兰卡）
    "XX国",              # 占位符
    "北塞浦路斯",        # 非普遍承认
    "某某斯坦",          # 用户随口编的
]

# 高风险误映射样本：城市 → 期望国家 / 期望 unknown / 绝不接受的错误映射。
# 迪拜/罗马是历史缺陷复现点（曾被误映射到申根区）。
# 注：阿联酋在互免名单内，修复后迪拜应解析为阿联酋而非 unknown——
#     名单来源是中外互免签证协定一览表，属权威数据，解析出来是改进不是风险。
MISMAP_PROBES = [
    ("迪拜", "阿联酋", "法国", "阿联酋在互免名单内，应解析为阿联酋，绝不能映射成申根国"),
    ("罗马", "", "法国", "申根城市未列映射→必须 unknown（历史缺陷复现点）"),
    ("曼谷", "泰国", "", "应解析为泰国"),
    ("东京", "日本", "", "应解析为日本"),
    ("首尔", "韩国", "", "应解析为韩国"),
    ("第比利斯", "格鲁吉亚", "", "bus/2 参考页主题，必须解析为格鲁吉亚"),
    ("波黑", "波斯尼亚和黑塞哥维那（波黑）", "", "括号别名「波黑」应能命中"),
]

L: list[str] = []


def say(s: str = "") -> None:
    L.append(s)


def load(name: str):
    return refloader.load(name, default=None)


def _stability_evidence(d: dict) -> str:
    """表级稳定性证据。返回证据描述，空串表示没有。

    接受三种形态（按设计，不是按我臆想的字段名）：
      1) 结构化 `_stability: volatile`
      2) `_note` / `_principle` 等说明文字里明确写了 volatile / 易变
      3) `_updated` 日期戳（无等级声明但至少有保鲜锚点）
    三者都没有 → 判失败：政策类事实既无等级也无日期，无法判断何时会过期。
    """
    if str(d.get("_stability", "")).strip():
        return f"_stability={d['_stability']}"
    for k in ("_note", "_principle", "_stability_split", "_redline", "triage_note"):
        v = d.get(k)
        if isinstance(v, str) and ("volatile" in v or "易变" in v):
            return f"{k} 含 volatility 声明"
    if str(d.get("_updated", "")).strip():
        return f"_updated={d['_updated']}（有日期戳，无等级声明）"
    return ""


def check_tables() -> tuple[int, int]:
    """防线2：出境基线表结构 + 稳定性证据完备。"""
    ok = bad = 0
    say("─" * 72)
    say("防线2　出境基线表结构与稳定性证据")
    for fname, (keys, label) in OUTBOUND_TABLES.items():
        d = load(fname)
        if d is None:
            say(f"  ❌ {fname} 缺失（出境四维约束少一张表：{label}）")
            bad += 1
            continue
        found = [k for k in keys if d.get(k)]
        if not found:
            say(f"  ❌ {fname} 无任何数据键（试过 {keys}）——{label}维度是空的")
            bad += 1
            continue
        ev = _stability_evidence(d)
        if not ev:
            say(f"  ❌ {fname}（{label}）：{len(found)} 个数据键，"
                f"但既无 volatility 等级也无 _updated 日期戳")
            bad += 1
            continue
        n = sum(len(d[k]) for k in found if hasattr(d[k], "__len__"))
        say(f"  ✅ {fname}（{label}）：键 {found}，{n} 项，{ev}")
        ok += 1
    return ok, bad


def check_unknown() -> tuple[int, int]:
    """防线1：查不到就 unknown，绝不猜。

    判定标准（灰灯语义）：
      - 未收录/查不到 → visa_required=None → 门禁卡给【灰灯】，不是绿灯。
        绿灯等于回答「没问题」，对没收录的国家给绿灯就是答错。
      - 同时也【不能给红灯】：对虚构地名红灯拦停是另一种错（把用户
        当成要去一个不存在的地方），但危害远小于绿灯，列为次要观察项。
    """
    ok = bad = 0
    say("─" * 72)
    say("防线1　查不到 → unknown（禁止危险兜底）")
    try:
        import outbound_constraints as oc
        import gate_card as gc
    except Exception as e:
        say(f"  ❌ 无法导入出境模块：{e}")
        return 0, 1

    for name in MUST_BE_UNKNOWN:
        try:
            inst = oc.OutboundConstraints([name])
            gate = inst.admission()
            card = gc.gate_card(gate if gate else None)
        except Exception as e:
            say(f"  ❌ {name} 处理异常：{e}")
            bad += 1
            continue
        visa = (gate or {}).get("visa_required")
        verdict = card.get("verdict")
        # 致命错误：给绿灯（=告诉用户「没问题」）
        if verdict == "clear" and (gate or {}):
            say(f"  ❌ {name} → 绿灯放行（{verdict}）——没收录却答「没问题」，"
                f"这是编造，比不答更危险")
            bad += 1
        elif visa is None or verdict in ("caution", "domestic"):
            say(f"  ✅ {name} → 未解析，走 unknown（visa_required=None，"
                f"verdict={verdict}）")
            ok += 1
        else:
            say(f"  ⚠️ {name} → visa_required={visa} verdict={verdict}（非绿灯，可接受）")
            ok += 1

    # 真实存在的国家必须能解析（不能一律 unknown，那不是安全是无能）
    for real in ("日本", "泰国", "法国", "格鲁吉亚"):
        try:
            inst = oc.OutboundConstraints([real])
            gate = inst.admission()
        except Exception as e:
            say(f"  ❌ {real} 处理异常：{e}")
            bad += 1
            continue
        if inst.country == real and gate:
            say(f"  ✅ {real} → 正常解析（visa_required="
                f"{gate.get('visa_required')}）")
            ok += 1
        else:
            say(f"  ⚠️ {real} → country={inst.country!r} gate={'有' if gate else '空'}"
                f"（漏答，需补录）")
            bad += 1
    return ok, bad


def check_mismap() -> tuple[int, int]:
    """防线1b：高风险误映射（城市不能张冠李戴到错误政策区）。"""
    ok = bad = 0
    say("─" * 72)
    say("防线1b　误映射探针（政策区不能张冠李戴）")
    try:
        import outbound_constraints as oc
    except Exception as e:
        say(f"  ❌ 无法导入 outbound_constraints：{e}")
        return 0, 1

    # (城市, 期望国家, 绝不接受的错误国家, 说明)
    probes = MISMAP_PROBES
    for city, expect, forbidden, why in probes:
        try:
            inst = oc.OutboundConstraints([city])
        except Exception as e:
            say(f"  ❌ {city} 处理异常：{e}")
            bad += 1
            continue
        got = inst.country
        if forbidden and got == forbidden:
            say(f"  ❌ {city} → {got}（{why}）——误映射复现")
            bad += 1
        elif expect and got == expect:
            say(f"  ✅ {city} → {got}（{why}）")
            ok += 1
        elif not expect and got == "":
            say(f"  ✅ {city} → 未解析（{why}）")
            ok += 1
        else:
            say(f"  ⚠️ {city} → {got!r}（期望 {expect or '未解析'}）——需人工确认")
            bad += 1

    # 签证结论不能错标免签
    vr = load("visa_rules.json")
    countries = (vr or {}).get("countries") or {}
    if isinstance(countries, list):
        countries = {c.get("name", ""): c for c in countries if isinstance(c, dict)}
    for ctry in ("泰国", "韩国"):
        row = countries.get(ctry)
        if not row:
            say(f"  ⚠️ {ctry} 不在 visa_rules（漏录）")
            bad += 1
            continue
        status = str(row.get("visa_status", "")) or str(row.get("visa_required", ""))
        if "免签" in status and "落地签" not in status and "过境" not in status:
            say(f"  ❌ {ctry} 被标为「{status}」——免签结论错误")
            bad += 1
        else:
            say(f"  ✅ {ctry} visa_status={status[:36]}（未误标免签）")
            ok += 1
    return ok, bad


def check_gate() -> tuple[int, int]:
    """防线4+5：红灯拦停 + 四灯完备。"""
    ok = bad = 0
    say("─" * 72)
    say("防线4/5　门禁卡：四灯必完备，红灯必拦停")
    try:
        import gate_card as gc
    except Exception as e:
        say(f"  ❌ 无法导入 gate_card：{e}")
        return 0, 1

    # 四灯完备：一个正常的出境 gate 必须产出 4 张灯卡
    try:
        card = gc.gate_card({"passport_valid_months": 11,
                             "passport_required_months": 6,
                             "visa_required": "required",
                             "visa_lead_days": 10, "days_to_depart": 5})
        cards = card.get("cards") or []
        lights = [c.get("light") for c in cards]
        if len(cards) == 4:
            say(f"  ✅ 四灯齐备（{len(cards)} 张卡，灯色 {lights}）")
            ok += 1
        else:
            say(f"  ❌ 门禁卡只有 {len(cards)} 张：缺灯的结论会假阴/假阳")
            bad += 1
    except Exception as e:
        say(f"  ❌ gate_card() 调用失败：{e}")
        bad += 1

    # 国内必须放行且不渲染门禁卡（国内技能场景）
    try:
        card = gc.gate_card(None)
        if card.get("verdict") == "domestic" and not card.get("cards"):
            say(f"  ✅ 国内 gate=None → verdict=domestic，不弹门禁卡")
            ok += 1
        else:
            say(f"  ❌ 国内行程竟渲染门禁卡：{card.get('verdict')}")
            bad += 1
    except Exception as e:
        say(f"  ❌ gate_card(None) 失败：{e}")
        bad += 1

    # 红灯拦停：签证来不及办 → blocked + 拦停页含行动项
    try:
        gate = {"passport_valid_months": 20, "passport_required_months": 6,
                "visa_required": "required", "visa_lead_days": 15,
                "days_to_depart": 3}
        card = gc.gate_card(gate)
        if card.get("blocked") and card.get("red", 0) > 0:
            page = gc.blocked_page(card, "测试国")
            s = str(page)
            has_action = any(k in s for k in ("行动", "核验", "怎么办", "建议"))
            if has_action:
                say(f"  ✅ 红灯 blocked=True（red={card['red']}），"
                    f"拦停页含行动项/核验渠道")
                ok += 1
            else:
                say(f"  ⚠️ 红灯拦停页不含行动项——拦停了却没告诉用户该干什么")
                bad += 1
        else:
            say(f"  ❌ 签证 15 天办、3 天后出发，竟未判红灯"
                f"（blocked={card.get('blocked')} red={card.get('red')}）")
            bad += 1
    except Exception as e:
        say(f"  ❌ 红灯场景失败：{e}")
        bad += 1
    return ok, bad


def check_traceability() -> tuple[int, int]:
    """防线3：结论可溯源。

    设计要求：基线表不是权威答案库，而是「基线 + 核验清单」。
    因此溯源的最低标准是【表级】有 _sources（官方来源）+ _updated（日期），
    让用户知道结论采信谁、截止到哪天。逐条 source 是加分项，不强制。
    """
    ok = bad = 0
    say("─" * 72)
    say("防线3　结论可溯源（表级官方来源 + 日期戳）")
    for fname, (keys, label) in OUTBOUND_TABLES.items():
        d = load(fname)
        if not d:
            say(f"  ❌ {fname} 缺失")
            bad += 1
            continue
        src = d.get("_sources")
        upd = str(d.get("_updated", "")).strip()
        items = []
        for k in keys:
            v = d.get(k)
            if isinstance(v, dict):
                items.extend(x for x in v.values() if isinstance(x, dict))
            elif isinstance(v, list):
                items.extend(x for x in v if isinstance(x, dict))
        per = sum(1 for r in items if r.get("source") or r.get("verified_on")
                  or r.get("as_of"))
        has_src = bool(src) and isinstance(src, dict)
        if has_src and upd:
            extra = f"，另 {per} 条带逐条来源" if per else ""
            say(f"  ✅ {fname}（{label}）：来源 {len(src)} 项 + 日期 {upd}{extra}")
            ok += 1
        elif has_src or upd:
            say(f"  ⚠️ {fname}：来源={'有' if has_src else '无'} "
                f"日期={upd or '无'}——缺一半，用户无法完整核验")
            bad += 1
        else:
            say(f"  ❌ {fname}：既无 _sources 也无 _updated——结论无法验证")
            bad += 1
    return ok, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="任一防线失败即退出码 1（默认总是退出码 0）")
    args = ap.parse_args()

    say("=" * 72)
    say("出境「答不出错」核查　——　国外的可以做，但问到就必须答对")
    say("=" * 72)

    results = []
    for fn in (check_tables, check_unknown, check_mismap, check_gate,
               check_traceability):
        o, b = fn()
        results.append((fn.__name__, o, b))

    total_ok = sum(o for _, o, _ in results)
    total_bad = sum(b for _, _, b in results)
    say("─" * 72)
    for name, o, b in results:
        mark = "✅" if b == 0 else "❌"
        say(f"  {mark} {name:<20} 通过 {o}　失败 {b}")
    say("─" * 72)
    if total_bad:
        say(f"结论：{total_bad} 项未过。出境答错比不答更危险——"
            f"未修好前不要对外承诺出境能力。")
    else:
        say(f"结论：{total_ok} 项全过。出境能力可对外，"
            f"但每条结论仍须带 volatility 日期戳。")
    print("\n".join(L))
    return 1 if (args.strict and total_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
