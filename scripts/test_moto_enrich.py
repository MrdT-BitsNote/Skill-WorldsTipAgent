"""摩旅数据增强通道 + 绿荫维度回归测试（v0.1.2）。

纪律锁死：
  1. 加油动作序列不得出现「剩余油量为负」这类算术错误（v0.1.2 修过的坑）
  2. 绿荫字段 18 条线路必须齐全；shade_first 必须让高荫排前
  3. ingest_note 四项必填、拒绝未来日期、evidence 恒 third_party
  4. 未收录城市（县级市等）必须进「必须查」，不得默认安全
  5. 一条坏笔记不得毁掉整包（errors 单列，不抛异常外泄）
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import moto_check as mc                                    # noqa: E402
import moto_enrich as me                                   # noqa: E402

PASS = FAIL = 0
FAILS: list[str] = []


def ck(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(msg)


# ── 一、绿荫字段完整性 ────────────────────────────────────────────────
rt = mc.all_routes()
ck(len(rt) == 18, f"线路库应有 18 条，实得 {len(rt)}")
for r in rt:
    name = r.get("name", "?")
    ck(r.get("shade") in ("高", "中", "低"), f"{name} 的 shade 需为 高/中/低")
    ck(bool(r.get("shade_note")), f"{name} 缺 shade_note（绿荫判定依据）")
    ck(bool(r.get("summer_window")), f"{name} 缺 summer_window（夏季时段建议）")

shade_vals = {r["shade"] for r in rt}
ck(shade_vals == {"高", "中", "低"}, f"三档绿荫等级都应出现，实得 {shade_vals}")

# ── 二、绿荫筛选与排序 ────────────────────────────────────────────────
high = mc.suggest_routes(shade_first=True, limit=99)
ranks = [mc._SHADE_RANK.get(r.get("shade", ""), 0) for r in high]
ck(ranks == sorted(ranks, reverse=True), "shade_first 应按绿荫等级降序排列")
mid = mc.suggest_routes(shade_min="中", limit=99)
ck(all(mc._SHADE_RANK.get(r.get("shade", ""), 0) >= 2 for r in mid),
   "shade_min=中 必须滤掉「低」档线路")
ck(len(mid) < 18, "shade_min=中 后线路数应少于全库")
ck(len(mid) > 0, "shade_min=中 不应把线路滤空")

# 季节命中时防护建议要追加时段提示
adv = mc.shade_advice("低", "5-6月、9-10月")
ck("SPF50" in adv, "低绿荫防护建议须含防晒要点")
ck("7:00-11:00" in adv, "夏季命中时应给出时段建议")

# ── 三、加油动作序列（v0.1.2 修过的算术坑） ──────────────────────────
g = mc.moto_card(from_city="成都", to_city="康定", daily_km=200, total_km=600,
                 displacement_cc=250, has_license=True, license_class="E",
                 has_plate=True, has_insurance=True, has_helmet=True)
rng = [c for c in g["cards"] if c["title"].startswith("续航")][0]
plan = rng["items"]
ck(rng["light"] == mc.GREEN, "600km/420km 满油应绿灯")
ck(plan.get("expected_refuels") == 2, f"600km 应设 2 站，实得 {plan.get('expected_refuels')}")
ck(plan.get("longest_gap_km") == 294, f"最长无补给段应等于安全续航 294，实得 {plan.get('longest_gap_km')}")
for rp in plan.get("refuel_points", []):
    ck(rp.get("left_km", 0) > 0, f"加油点 {rp.get('at_km')} 的剩余油量不得为负（实得 {rp.get('left_km')}）")
    ck(rp.get("after_km") is not None, "每个加油点须带 after_km（此站后剩余里程）")
acts = plan.get("fuel_actions") or []
ck(len(acts) >= 3, "动作序列至少含 出发前/中途/抵达前 三类")
ck(any("加满油" in a.get("do", "") for a in acts), "动作序列须含出发前加满")
ck(any("2 次" in a.get("why", "") for a in acts), "末站提示须写明总加油次数")

# 高速场景：出发前文案必须是服务区口径
g2 = mc.moto_card(from_city="武汉", to_city="贵阳", total_km=1000, displacement_cc=500,
                  has_license=True, license_class="D", has_plate=True,
                  has_insurance=True, has_helmet=True, prefer_highway=True)
p2 = [c for c in g2["cards"] if c["title"].startswith("续航")][0]["items"]
ck("服务区" in p2["fuel_actions"][0]["why"],
   "prefer_highway 时出发前提示须提服务区（学百度的「高速前挑服务区」）")
ck(p2.get("expected_refuels") == 3, f"1000km/400km 安全续航应设 3 站，实得 {p2.get('expected_refuels')}")

# 无里程时仍要给动作基线（出发前加满），不得空序列
g3 = mc.moto_card(from_city="成都", to_city="康定", displacement_cc=250)
p3 = [c for c in g3["cards"] if c["title"].startswith("续航")][0]["items"]
ck(len(p3.get("fuel_actions") or []) >= 1, "无里程时也应有出发前加满的动作基线")

# ── 四、ingest_note 证据纪律 ─────────────────────────────────────────
n = me.ingest_note("康定 禁摩", "市区不禁摩", "小红书", "2026-09-20")
ck(n["evidence"] == "third_party", "社媒来源必须标 third_party，不得升级")
ck(n["stability"] == "volatile", "会变信息必须标 volatile")
ck("age_days" in n, "记录须带时效天数")

for bad, kw in ((("", "内容", "小红书", "2026-01-01"), "topic"),
                (("主题", "", "小红书", "2026-01-01"), "content"),
                (("主题", "内容", "", "2026-01-01"), "source"),
                (("主题", "内容", "小红书", ""), "date"),
                (("主题", "内容", "小红书", "2026/01/01"), "YYYY-MM-DD"),
                (("主题", "内容", "小红书", "2999-01-01"), "晚于今天")):
    try:
        me.ingest_note(*bad)
        ck(False, f"缺 {kw} 必须抛错")
    except ValueError:
        ck(True, "")

# 超 30 天告警
old = me.ingest_note("旧闻", "内容", "小红书",
                     (dt.date.today() - dt.timedelta(days=45)).isoformat())
ck("stale_warning" in old, "超过 30 天的笔记必须带 stale_warning")

# ── 五、validate_notes：坏数据不毁整包 ──────────────────────────────
mixed = {"notes": [
    {"topic": "A", "content": "可以", "source": "小红书", "date": "2026-10-01"},
    {"topic": "B", "content": "缺来源", "date": "2026-10-01"},
    {"topic": "C", "content": "未来日期", "source": "小红书", "date": "2999-01-01"},
]}
out = me.validate_notes(mixed)
good = [x for x in out if "_errors" not in x]
errs = next((x["_errors"] for x in out if "_errors" in x), [])
ck(len(good) == 1, f"3 条中应只有 1 条通过，实得 {len(good)}")
ck(len(errs) == 2, f"应有 2 条错误记录，实得 {len(errs)}")

# ── 六、清单：未收录城市必须查 ───────────────────────────────────────
cl = me.build_checklist(from_city="成都", to_city="康定", days=3, routes=rt[:1])
topics = {i["topic"]: i for i in cl["items"]}
kd = [t for t in topics if "康定" in t]
ck(bool(kd), "县级市康定不在 45 城名单，必须生成兜底必查项")
if kd:
    ck(topics[kd[0]]["must_check"] is True, "未收录城市的兜底项必须是「必须查」")
    ck("未收录" in topics[kd[0]]["topic"], "兜底项标题须写明「本库未收录」")
cd = [t for t in topics if t.startswith("成都")]
ck(bool(cd), "成都在名单内，应有对应政策项")
if cd:
    ck(topics[cd[0]]["must_check"] is True, "volatile 级政策必须是「必须查」")
# statute 级只需建议复核（四川高速准入是 statute）
sc = [t for t in topics if "高速准入" in t]
if sc:
    ck(topics[sc[0]]["must_check"] is False,
       "statute 级政策应只列为建议复核，把「必须查」留给真有风险的信息")
ck(cl.get("must_count", 0) >= 2, f"成都→康定至少 2 项必须查，实得 {cl.get('must_count')}")
ck("小红书" in json.dumps(cl, ensure_ascii=False), "建议来源须含小红书")
ck("不做批量抓取" in cl.get("compliance_note", ""), "合规边界必须写明")

# ── 七、渲染不得因缺数据崩 ──────────────────────────────────────────
ck(len(me.enrichment_html(cl, out)) > 0, "清单 + 混合笔记应能渲染")
ck(me.enrichment_html({}, []) == "", "空清单应返回空串（不渲染空板块）")

print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败明细：")
    for f in FAILS:
        print("  ✗", f)
    sys.exit(1)
print("moto_enrich + 绿荫维度回归全过")
