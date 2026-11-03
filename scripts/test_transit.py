# -*- coding: utf-8 -*-
"""test_transit.py — 交通比选三级分流回归测试（v0.1.29 逻辑修复）。

锁死纪律（修复「短途误推高铁飞机」）：
- 市内圈（≤30km）：只推公交/地铁/出租/网约车/骑行/步行，不推城际高铁/飞机/普铁。
- 近郊圈（30-150km）：优先自驾/班车，高铁仅当「通高铁且≥50km」才列为条件选项，不默认推荐。
- 跨城（>150km）：才走高铁/普铁/飞机/客车六方式比选。
- 坐标缺失（同城景点/需消歧地名）：不默认「高铁(默认)」，而是 recommend=需确认交通方式，
  提示先向用户确认「市内 or 跨城」。
Windows 控制台友好：只用 ASCII 打印。
"""
import os
import sys
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan_transit as P  # noqa: E402

ok = 0
fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print("ok   -", name)
    else:
        fail += 1
        print("FAIL -", name)


# ── 市内圈：广州-佛山 ~19km ──
r_city = P.build("广州", "佛山")
check("市内圈 scope=市内", r_city.get("scope") == "市内")
check("市内圈 recommend=市内交通", r_city.get("recommend") == "市内交通")
check("市内圈 含地铁", any("地铁" == o.get("name") for o in r_city.get("options", [])))
check("市内圈 含网约车", any("网约车" == o.get("name") for o in r_city.get("options", [])))
check("市内圈 含出租车", any("出租车" == o.get("name") for o in r_city.get("options", [])))
check("市内圈 无高铁 key", "高铁" not in r_city)
check("市内圈 无飞机 key", "飞机" not in r_city)
check("市内圈 无普铁 key", "普铁" not in r_city)
check("市内圈 6 种市内方式", len(r_city.get("options", [])) == 6)

# ── 近郊圈：岳阳-长沙 ~128km ──
r_near = P.build("岳阳", "长沙")
check("近郊圈 recommend 不含默认高铁", "高铁(默认)" not in r_near.get("recommend", ""))
check("近郊圈 recommend 含近郊/自驾", "近郊" in r_near.get("recommend", "") or "自驾" in r_near.get("recommend", ""))
opt_names_near = [o.get("name", "") for o in r_near.get("options", [])]
check("近郊圈 自驾为首选", any(o.startswith("方案A") and "自驾" in o for o in opt_names_near))
check("近郊圈 高铁标「若通高铁」前提", any("若通高铁" in o for o in opt_names_near))
check("近郊圈 无飞机方案", not any("飞机" in o and "方案" in o for o in opt_names_near))

# ── 跨城：北京-上海 ~1251km ──
r_far = P.build("北京", "上海")
check("跨城 有高铁 key", "高铁" in r_far)
check("跨城 有飞机 key", "飞机" in r_far)
check("跨城 有普铁 key", "普铁" in r_far)
check("跨城 recommend 为 机票参考 或 高铁", r_far.get("recommend") in ("机票参考", "高铁(默认)"))

# ── 坐标缺失：岳阳-金鹗山（同城景点，不在城际库） ──
r_unknown = P.build("岳阳", "金鹗山")
check("坐标缺失 recommend=需确认交通方式", r_unknown.get("recommend") == "需确认交通方式")
check("坐标缺失 不默认高铁", r_unknown.get("recommend") != "高铁(默认)")
check("坐标缺失 reason 提示市内或跨城", "市内" in r_unknown.get("reason", "") and "跨城" in r_unknown.get("reason", ""))
check("坐标缺失 提示公交地铁网约车", any(k in r_unknown.get("reason", "") for k in ("公交", "地铁", "网约车")))
check("坐标缺失 无飞机 key", "飞机" not in r_unknown)

# ── v0.1.42 用户明确出行方式 → 只按该方式, 不输出其他推荐 ──
r_md = P.build("武汉", "广州", mode="自驾")
check("mode=自驾 无高铁 key", "高铁" not in r_md)
check("mode=自驾 无飞机 key", "飞机" not in r_md)
check("mode=自驾 recommend=自驾", r_md.get("recommend") == "自驾")
check("mode=自驾 方案全为自驾", bool(r_md.get("options")) and all("自驾" in o["name"] for o in r_md["options"]))

r_mm = P.build("武汉", "广州", mode="摩旅")
check("mode=摩旅 无任何公共交通 key", all(k not in r_mm for k in ("高铁", "普铁", "飞机", "客车", "轮船", "自驾")))
check("mode=摩旅 recommend=摩旅", r_mm.get("recommend") == "摩旅")
check("mode=摩旅 reason 指向专项引擎", "moto_check" in r_mm.get("reason", ""))

r_mr = P.build("北京", "上海", mode="高铁")
check("mode=高铁 无飞机 key", "飞机" not in r_mr)
check("mode=高铁 无自驾 key", "自驾" not in r_mr)
check("mode=高铁 recommend=高铁", r_mr.get("recommend") == "高铁")
check("mode=高铁 方案只含高铁", bool(r_mr.get("options")) and all("高铁" in o["name"] for o in r_mr["options"]))

r_mpub = P.build("北京", "上海", mode="公共交通")
check("mode=公共交通 等同默认比选(含飞机)", "飞机" in r_mpub)

r_mcity = P.build("广州", "佛山", mode="自驾")
check("市内 mode=自驾 只剩出租/网约车",
      bool(r_mcity.get("options")) and all(o["name"] in ("出租车", "网约车") for o in r_mcity["options"]))

# ── v0.1.42 修复: 「机票参考」补 ≥800km 闸门, 与方案飞机纳入口径一致 ──
r_mid = P.build("成都", "西安")  # ~606km
check("中程 606km recommend 非 机票参考", r_mid.get("recommend") != "机票参考")
check("中程 606km 方案无飞机", not any("飞机" in o["name"] for o in r_mid.get("options", [])))

# ── v0.1.43 阈值同源与边界 ──
import json  # noqa: E402
import plan_route  # noqa: E402

with open(os.path.join(HERE, "..", "references", "transit_rules.json"), encoding="utf-8") as f:
    _rules = json.load(f)
check("同城阈值与 plan_route 同源", plan_route.city_distance_km() == _rules["市内交通"]["city_distance_km"])
check("机票价格/耗时阈值由配置消费", _rules["机票参考条件"]["price_ratio_max"] == 1.05
      and _rules["机票参考条件"]["total_time_ratio_max"] == 1.3)
with patch.object(P, "coords_of", return_value=(0.0, 0.0)), patch.object(P, "haversine", return_value=800.0):
    r_800 = P.build("测试甲", "测试乙")
check("恰好 800km 推荐与方案均无飞机", r_800.get("recommend") != "机票参考"
      and not any("飞机" in o["name"] for o in r_800.get("options", [])))
with patch.object(P, "coords_of", return_value=(0.0, 0.0)), patch.object(P, "haversine", return_value=800.0):
    r_800_air = P.build("测试甲", "测试乙", mode="飞机")
check("恰好 800km 明示飞机仍保留但有提示", r_800_air.get("recommend") == "飞机"
      and "通常不如高铁" in r_800_air.get("reason", ""))
r_short = P.build("武汉", "长沙")  # ~294km
check("150-300km 默认比选带门到门提示", "门到门" in r_short.get("coach_hint", ""))
r_short_mode = P.build("武汉", "长沙", mode="高铁")
check("明确方式不附带其他方式提示", "coach_hint" not in r_short_mode)

print(f"\ntest_transit: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
