#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_check.compare() 离线回归：用合成 fixture 锁死联表判定，不触网、不读盘。

覆盖：slug 联表、显示名漂移、alias 消解、已知分歧、站点/技能独有白名单、ok 与 unresolved_count。
运行：python test_sync_check.py
"""
import sys

import sync_check as sc

PASS = FAIL = 0


def ck(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  ✗ FAIL:", msg)


def site(*pairs):
    return [{"slug": s, "name": n, "region": "X"} for s, n in pairs]


def skill(*triples):
    return [{"slug": s, "name": n, "aliases": a, "region": "X"} for s, n, a in triples]


def test_identical():
    r = sc.compare(site(("a", "甲"), ("b", "乙")), skill(("a", "甲", []), ("b", "乙", [])))
    ck(r["ok"] and r["unresolved_count"] == 0, "完全一致应 ok")
    ck(not r["drift"] and not r["collisions"], "一致时无漂移无冲突")
    ck(r["site_count"] == 2 and r["skill_count"] == 2, "计数正确")


def test_drift_unresolved():
    # 同 slug 名字不同、且不在 alias、也不在 known → 未消解漂移
    r = sc.compare(site(("a", "甲新版"),), skill(("a", "甲", [])), known={})
    ck(len(r["drift"]) == 1, "应检出 1 条未消解漂移")
    ck(r["unresolved_count"] == 1 and not r["ok"], "漂移计入未解决、ok=False")


def test_alias_reconciled():
    # 站点显示名落在技能 aliases 里 → 消解，不算漂移
    r = sc.compare(site(("a", "甲 · 景点"),), skill(("a", "甲", ["甲 · 景点"]),), known={})
    ck(len(r["reconciled"]) == 1 and not r["drift"], "alias 命中应消解为 reconciled")
    ck(r["ok"] and r["unresolved_count"] == 0, "消解后 ok")


def test_known_divergence():
    known = {"divergence": {"muli": "站点指向别处"}, "site_only": {}, "skill_only": {}}
    r = sc.compare(site(("muli", "木梨硔"),), skill(("muli", "木里", [])), known=known)
    ck(len(r["collisions"]) == 1 and r["collisions"][0].get("known"), "已知分歧打 known 标记")
    ck(not r["drift"], "已知分歧不进 drift")
    ck(r["ok"] and r["unresolved_count"] == 0, "已知分歧不算未解决")


def test_site_only_whitelist():
    known = {"site_only": {"europe": "出境页"}, "skill_only": {}, "divergence": {}}
    r = sc.compare(site(("europe", "欧洲自驾"), ("x", "X")),
                   skill(("x", "X", [])), known=known)
    ck(len(r["site_only"]) == 1 and r["site_only"][0].get("known"), "站点独有白名单打 known")
    ck(r["ok"], "白名单站点独有不破坏 ok")
    # 未登记的站点独有 → 未解决
    r2 = sc.compare(site(("new", "新页"),), skill(), known={"site_only": {}, "skill_only": {}, "divergence": {}})
    ck(r2["unresolved_count"] == 1 and not r2["ok"], "未登记站点独有计入未解决")


def test_skill_only_whitelist():
    known = {"skill_only": {"shishou": "出发地"}, "site_only": {}, "divergence": {}}
    r = sc.compare(site(), skill(("shishou", "石首", [])), known=known)
    ck(len(r["skill_only"]) == 1 and r["skill_only"][0].get("known"), "技能独有白名单打 known")
    ck(r["ok"], "白名单技能独有不破坏 ok")


def test_empty_slug_ignored():
    # slug 为空的条目（解析失败）不参与联表
    r = sc.compare([{"slug": "", "name": "无", "region": "X"}], skill(("a", "甲", [])))
    ck(r["site_count"] == 0, "空 slug 不计入站点")
    ck(len(r["skill_only"]) == 1, "技能 a 为独有")


def test_parse_site_html():
    html = 'xx const DATA = {"华东":[{"n":"木梨硔","u":"https://worldstip.com/map/mulihong/index.html"}]}; const META = {}'
    got = sc.parse_site_html(html)
    ck(len(got) == 1 and got[0]["slug"] == "mulihong" and got[0]["name"] == "木梨硔", "parse_site_html 抽 slug/name")


def main():
    for fn in (test_identical, test_drift_unresolved, test_alias_reconciled,
               test_known_divergence, test_site_only_whitelist, test_skill_only_whitelist,
               test_empty_slug_ignored, test_parse_site_html):
        fn()
    print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
    print("sync_check OK" if FAIL == 0 else "FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
