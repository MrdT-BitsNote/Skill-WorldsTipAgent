#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并版准入许可门禁回归（v0.1.49 · 发布阻断）。

口径裁决：保留 v0.1.47「未核验即灰灯」红线（绝不编造放行），
补回 v0.1.48 的「核验日期戳」与 visa_source 双留证。
installed v0.1.48 的 test_gate_visa.py 用「未核验→黄灯有条件放行」，
与本口径互斥，故不纳入本包；本文件为合并后唯一权威判据。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from gate_card import gate_card, _check_visa, GREEN, YELLOW, RED, GREY  # noqa: E402

PASS, FAIL = 0, 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")

print("=== 合并版准入许可门禁回归（灰灯红线 + 核验留证）===")

g = _check_visa({"visa_required": "none"})
check("A1 免签未核验 → 绝不绿灯", g["light"] != GREEN, f"实际={g['light']}")
check("A1b 免签未核验 → 灰灯待查", g["light"] == GREY, f"实际={g['light']}")

g2 = _check_visa({"visa_required": "none", "visa_verified": True,
                  "visa_source": "https://cs.mfa.gov.cn/", "visa_verified_on": "2026-11-05"})
check("A2 免签已核验 → 绿灯", g2["light"] == GREEN, f"实际={g2['light']}")
check("A2b 绿灯详情含核验日期", "2026-11-05" in g2["detail"], g2["detail"][:70])
check("A2c 绿灯详情含官方来源", "cs.mfa.gov.cn" in g2["detail"], g2["detail"][:70])

g3 = _check_visa({"visa_required": "required", "visa_lead_days": 7, "days_to_depart": 30})
check("A3 需签未核验 → 绝不绿灯", g3["light"] != GREEN, f"实际={g3['light']}")
check("A3b 需签未核验 → 灰灯待查", g3["light"] == GREY, f"实际={g3['light']}")

g4 = _check_visa({"visa_required": "required", "visa_lead_days": 7, "days_to_depart": 30,
                  "visa_verified": True, "visa_verified_on": "2026-11-05"})
check("A4 需签已核验 → 不误判绿灯", g4["light"] != GREEN, f"实际={g4['light']}")
check("A4b 需签已核验 → 黄灯（仍需办签）", g4["light"] == YELLOW, f"实际={g4['light']}")
check("A4c 黄灯详情含核验日期", "2026-11-05" in g4["detail"], g4["detail"][:70])

g5 = _check_visa({"visa_required": "required", "visa_lead_days": 7,
                  "days_to_depart": 2, "visa_verified": True})
check("A5 办理时间不足 → 红灯硬阻断", g5["light"] == RED, f"实际={g5['light']}")

g6 = _check_visa({})
check("A6 未提供准入许可信息 → 灰灯", g6["light"] == GREY, f"实际={g6['light']}")
g7 = _check_visa({"visa_required": "unknown"})
check("A7 政策未覆盖 → 灰灯不猜测", g7["light"] == GREY, f"实际={g7['light']}")

gc = gate_card({"passport_valid_months": 24, "visa_required": "none",
                "vaccine_required": "none", "insurance_required": False})
check("B1 免签未核验 → verdict 非 clear", gc["verdict"] != "clear", str(gc["verdict"]))
check("B2 免签未核验 → 门禁卡含灰灯", any(
    c.get("light") == GREY for c in gc.get("cards", [])), str(gc.get("cards", []))[:100])
gc2 = gate_card({"passport_valid_months": 24, "visa_required": "none",
                 "visa_verified": True, "visa_source": "https://cs.mfa.gov.cn/",
                 "vaccine_required": "none", "insurance_required": False})
check("B3 免签已核验 → verdict clear", gc2["verdict"] == "clear", str(gc2["verdict"]))

print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
