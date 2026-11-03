#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_compact.py — 默认渲染器体检板块回归（v0.1.43 移植自旧版 render_booklet）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_compact as RC

ok = fail = 0


def check(cond, name):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS {name}")
    else:
        fail += 1
        print(f"  FAIL {name}")


BASE_PLAN = {
    "origin": "宜昌", "destinations": ["三峡大坝"], "days": 2, "people": 2,
    "composition": "情侣", "style": "roadtrip", "intensity": 3,
    "plan": [{"day": 1, "label": "三峡大坝", "city": "宜昌", "spots": 1,
              "slots": [{"time": "09:00", "name": "三峡大坝"}]}],
    "budget": {"per_person_total": 800, "lodging_level": "舒适", "food_level": "舒适", "nights": 1},
    "stay": {"rooms": 1},
}

print("== 1. advisory：P0 关卡未覆盖 → 横幅 + §2b 板块 ==")
html = RC.render(dict(BASE_PLAN), "测试", feasibility="advisory")
check("可执行性体检" in html, "板块标题出现")
check('id="sec2b"' in html, "§2b 锚点存在")
check("P0" in html and "三峡大坝" in html, "P0 关卡被点名")
check("预约" in html or "通行证" in html, "关卡文案透出")
check('href="#sec2b"' in html, "TOC 含体检入口")
check("体检提示" in html, "advisory 黄色提示横幅")

print("== 2. strict：P0 → 红色强制横幅 ==")
html = RC.render(dict(BASE_PLAN), "测试", feasibility="strict")
check("体检未通过" in html and "必须复核" in html, "strict 红条强制")

print("== 3. none：完全关闭 ==")
html = RC.render(dict(BASE_PLAN), "测试", feasibility="none")
check("sec2b" not in html and "可执行性体检" not in html, "none 不出板块/横幅/TOC")

print("== 4. 阈值自检：单日 8 点位 > 上限 6 ==")
p = dict(BASE_PLAN)
p["plan"] = [{"day": 1, "label": "暴走", "city": "宜昌", "spots": 8,
              "slots": [{"time": "22:30", "name": "夜游"}]}]
html = RC.render(p, "测试", feasibility="advisory")
check("超过单日建议上限" in html, "点位超阈值提示")
check("末班车与夜间安全" in html, "深夜时段提示")

print("== 5. 干净行程：无 P0 → 通过横幅 ==")
p = {"origin": "长沙", "destinations": ["某普通公园"], "days": 1, "people": 1,
     "composition": "独自一人", "style": "leisure", "intensity": 2,
     "plan": [{"day": 1, "label": "公园散步", "city": "长沙", "spots": 2,
               "slots": [{"time": "10:00", "name": "某普通公园"}]}]}
html = RC.render(p, "测试", feasibility="advisory")
check("体检通过" in html, "全过绿色横幅")

print("== 6. 散心模式：体检与 TOC 同步省略 ==")
p = dict(BASE_PLAN)
p["style"] = "resort"
html = RC.render(p, "测试", feasibility="advisory")
check("sec2b" not in html, "resort 省略体检板块")

print("== 7. plan_transit user_mode 与渲染器明确方式识别接通 ==")
check(RC._explicit_mode({"style": "leisure"}, {"user_mode": "高铁"}) == "hsr", "user_mode=高铁 被识别为明确方式")
check(RC._explicit_mode({"style": "leisure"}, {"user_mode": "自驾"}) == "roadtrip", "user_mode=自驾 被识别为明确方式")

print("== 8. 预算双列：最低与常规不再同值 ==")
p = dict(BASE_PLAN)
p["budget"] = dict(BASE_PLAN["budget"], per_person={"住宿": 300, "餐饮": 150},
                   per_person_low={"住宿": 200, "餐饮": 100},
                   per_person_total=450, per_person_total_low=300)
html = RC.render(p, "测试", feasibility="none")
check("住宿行最低 200 / 常规 300", '<td>住宿</td><td class="r">¥200</td><td class="r">¥300</td>' in html)
check("合计行最低 300 / 常规 450", '<b>¥300</b></td><td class="r"><b>¥450</b>' in html)

print(f"\ntest_render_compact: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
