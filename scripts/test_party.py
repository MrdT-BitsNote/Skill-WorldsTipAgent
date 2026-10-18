#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""陪伴结构（Party Type）回归测试 —— 锁死 6 类判定、边界裁定、分摊口径、团体分房、四轴正交。

对齐 CONTEXT.md 与 references/party_playbooks.json。纯离线、无网络。
用法: python test_party.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from build_itinerary import (  # noqa: E402
    resolve_party_type, party_block, load_party, stay_plan, budget_for,
    STYLE_PROFILES,
)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {name}")


# ── 1. 六类判定 + 边界裁定（CONTEXT.md 规则）──
CASES = [
    # (people, composition, hints, expect)
    (1, "", [], "solo"),
    (1, "一个人", [], "solo"),
    (2, "情侣", [], "couple"),
    (2, "蜜月出行", [], "couple"),
    (2, "闺蜜同行", [], "friends-small"),      # 2 朋友非情侣
    (4, "两对情侣", [], "friends-small"),       # ≥2 组关系→非 couple
    (3, "异性同事自驾", [], "friends-small"),
    (5, "一群朋友", [], "friends-large"),      # ≥5 无组织
    (6, "球友结伴", [], "friends-large"),
    (3, "一家三口带娃", [], "family"),
    (4, "带父母出游", [], "family"),           # 跨代亲属→family，非计数
    (30, "公司团建", [], "group"),
    (20, "亲子研学团", [], "group"),           # 有组织方优先于 family 词
    (12, "夕阳红旅行团", [], "group"),
]
for ppl, comp, hints, exp in CASES:
    got = resolve_party_type(ppl, comp, hints)
    check(f"resolve({ppl},{comp!r})={got} 期望 {exp}", got == exp)

# ── 2. 优先级：group > family（研学团含"亲子"仍 group）；family > couple ──
check("跨代亲属优先于朋友计数", resolve_party_type(5, "五个家庭带娃", []) == "family")
check("组织方优先于家庭词", resolve_party_type(8, "家庭日团建", []) == "group")

# ── 3. override 显式指定生效 ──
check("override 团建 2 人判 group", resolve_party_type(2, "", [], override="group") == "group")
check("override 覆盖自动推断", resolve_party_type(6, "一群朋友", [], override="family") == "family")

# ── 4. 每类 party_block 分摊口径非空 + 六键齐全 ──
db = load_party()
for pt in ["solo", "couple", "friends-small", "friends-large", "family", "group"]:
    blk = party_block(db, pt, 2, inferred=True)
    check(f"{pt} label 非空", bool(blk.get("label")))
    check(f"{pt} budget_mode 非空", bool(blk.get("budget_mode")))
    check(f"{pt} safety_focus 列表", isinstance(blk.get("safety_focus"), list))
    check(f"{pt} inferred 标记", blk.get("inferred") is True)

# ── 5. 分摊口径语义正确 ──
check("solo 独自承担", party_block(db, "solo", 1, True)["budget_mode"] == "独自承担")
check("friends-large AA 分摊", "AA" in party_block(db, "friends-large", 6, True)["budget_mode"])
check("group 含组织者/包价口径", ("组织者" in party_block(db, "group", 30, True)["budget_mode"])
      or ("包价" in party_block(db, "group", 30, True)["budget_mode"]))

# ── 6. stay_plan 团体分支：组织者统订标准双床间，房间数≈⌈n/2⌉ ──
prof = STYLE_PROFILES["leisure"]
g_stay = stay_plan(30, prof, "公司团建")
check("团体 30 人按⌈n/2⌉=15 间", g_stay.rooms == 15)
check("团体分房文案含'组织者'", "组织者" in g_stay.room_types[0] or "组织者" in g_stay.rationale)
# 非团体不受影响（回归保护）：情侣仍 1 间大床
check("情侣分房不受团体分支影响", stay_plan(2, prof, "情侣").rooms == 1)
check("三口之家仍 1 间家庭房", stay_plan(3, prof, "一家三口").rooms == 1)

# ── 7. 预算双档：整团 group_total 与人均 per_person_total 都在，且随 party 标注口径 ──
b_group = budget_for(prof, 3, 30, "舒适", "舒适", stay=g_stay)
check("团体预算含 group_total", b_group.get("group_total", 0) > 0)
check("团体预算含 per_person_total", b_group.get("per_person_total", 0) > 0)
check("住宿按间不按人：30人15间≠30间", g_stay.rooms == 15 and g_stay.rooms != 30)

# ── 8. 四轴正交：family party 不强制 audience=family（丁克=party family 但可 general audience）──
#    resolve_party_type 只吃 composition/people/hint，与 infer_audience 互不写入
from build_itinerary import infer_audience  # noqa: E402


class _Args:
    def __init__(self, comp, hint, style=""):
        self.composition = comp; self.hint = hint; self.style = style


check("party 与 audience 独立：带娃→party family 且 audience family",
      resolve_party_type(3, "带娃", []) == "family" and infer_audience(_Args("带娃", [])) == "family")
check("party 与 audience 独立：纯朋友→friends-small 但 audience general",
      resolve_party_type(2, "朋友同行", []) == "friends-small" and infer_audience(_Args("朋友同行", [])) == "general")

print(f"\n{'='*56}")
if FAIL == 0:
    print(f"test_party: ALL PASSED ({PASS} 断言)")
else:
    print(f"test_party: 通过 {PASS} / 失败 {FAIL}")
    sys.exit(1)
