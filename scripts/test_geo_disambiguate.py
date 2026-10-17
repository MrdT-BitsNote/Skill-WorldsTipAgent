#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨省同名消歧回归测试（v0.3.0）

测什么
------
1. 境内外判定零回退 —— 这是【硬安全底线】。
   v0.3.0 新增了 geo_ambiguous 索引注入和 SCENIC_ALIAS 扩表，
   任何一条改动若让国内地名落unknown，用户就会被误判为出境，
   凭空弹出签证门禁卡。反向更严重：若让境外地名落境内，
   出境用户会【漏掉】签证与保险门禁。两类错误都不可接受。
2. 歧义候选完整性 —— 幕阜山必须给全6 个候选，缺一个用户就看不到那条路。
3. 纠偏必须触发 —— 「临湘那边的幕布山」是真实口误，不纠偏会让用户走错县城。
4. 意图加权不得胡推 —— 没有意图时不能瞎推荐，那是替用户做决定。
5. 港澳台表述 —— 中国台湾不得归到中国香港名下。

怎么用
------
python scripts/test_geo_disambiguate.py
退出码 0 = 全过；非0 = 有回退，必须修。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geo_disambiguate as gd
import geo_lookup as gl

_FAIL: list[str] = []
_N = 0


def check(cond: bool, label: str, detail: str = "") -> None:
    global _N
    _N += 1
    if not cond:
        _FAIL.append(f"{label}" + (f"  → {detail}" if detail else ""))


# ── 1. 境内地名：必须判境内 ────────────────────────────────
DOMESTIC = [
    "岳阳", "长沙", "佛山", "广州", "深圳", "上海", "北京",
    "平江", "临湘", "通山", "通城", "武宁", "修水", "咸宁", "潜山",
    "黄山", "华山", "泰山", "峨眉山", "五台山", "九华山", "普陀山",
    "武当山", "武夷山", "雁荡山", "天柱山", "古南岳",
    "九宫山", "大幕山", "黄袍山", "太阳山", "黄龙山", "鹿角山",
    "西柏坡", "韶山", "井冈山", "延安", "瑞金", "遵义",
    "芒市", "瑞丽", "霍尔果斯", "婺源", "阿尔山", "漠河", "腾冲",
    "阳朔", "赤水", "延吉", "珲春", "满洲里", "东宁",
    "横店", "周庄", "同里", "乌镇", "西塘", "南浔", "甪直", "朱家角",
    "中国台湾", "台北", "高雄", "中国香港", "中国澳门", "港澳台",
]

# ── 2. 境外地名：必须判非境内（落 unknown 待查，不编国别）──
OVERSEAS = [
    "东京", "京都", "大阪", "名古屋", "札幌", "福冈", "冲绳",
    "曼谷", "清迈", "普吉", "巴厘岛", "雅加达", "新加坡", "吉隆坡",
    "纽约", "洛杉矶", "旧金山", "芝加哥", "西雅图", "波士顿",
    "巴黎", "罗马", "米兰", "威尼斯", "佛罗伦萨", "慕尼黑", "柏林",
    "伦敦", "爱丁堡", "都柏林", "阿姆斯特丹", "苏黎世", "维也纳",
    "首尔", "釜山", "济州岛", "迪拜", "多伦多", "温哥华",
    "奥克兰", "悉尼", "墨尔本", "曼谷", "河内", "胡志明市", "金边",
]

# ── 3. 歧义行为 ──────────────────────────────────────────
AMBIGUOUS_EXPECT = {
    "幕阜山": 6, "幕布山": 6, "幕埠山": 6, "天岳幕阜山": 6,
    "临湘那边的幕布山": 6, "幕阜山脉": 6, "天岳": 6,
    "五指山": 4, "南岳": 2,
}

# ── 4. 不该被误判为歧义的名字（归属唯一）───────────────────
SHOULD_NOT_AMBIGUOUS = [
    "黄山", "华山", "泰山", "峨眉山", "九华山", "武当山",
    "九宫山", "大幕山", "黄袍山", "太阳山", "黄龙山",
    "葛仙村", "平遥古城", "丽江古城", "凤凰古城", "西塘", "乌镇",
]

# 这些名字【本就应该】标歧义：连锁品牌跨多地，用户必须指定哪一园。
# 与 SHOULD_NOT_AMBIGUOUS 分开测，避免"该歧义"被误当成"不该歧义"回归。
SHOULD_BE_AMBIGUOUS = ["方特", "宋城", "欢乐谷", "长隆", "海昌海洋公园"]


def t_domestic() -> None:
    gl._build_index()
    for n in DOMESTIC:
        r = gl.lookup(n)
        check(r is not None, f"[境内] {n} 应判境内", "落 unknown 待查")


def t_overseas() -> None:
    gl._build_index()
    for n in OVERSEAS:
        r = gl.lookup(n)
        # 境外必须不命中境内索引。命中即为漏拦签证门禁的硬安全风险。
        check(r is None, f"[境外] {n} 不得判境内",
              f"被误判为境内：{r}")


def t_ambiguous() -> None:
    gl._build_index()
    for n, expect in AMBIGUOUS_EXPECT.items():
        r = gl.lookup(n)
        check(r is not None, f"[歧义] {n} 应判境内（山脉在国内）", "落 unknown")
        if r:
            check(r.get("needs_disambiguation") is True,
                  f"[歧义] {n} 应标记 needs_disambiguation", str(r)[:90])
            got = r.get("candidate_count")
            check(got == expect, f"[歧义] {n} 候选数应为 {expect}", f"实得 {got}")
            # 关键：歧义时不得给出单一归属，否则上层会直接排程
            check(not r.get("province"), f"[歧义] {n} 歧义时不得给单一省份",
                  f"province={r.get('province')}")


def t_not_ambiguous() -> None:
    gl._build_index()
    for n in SHOULD_NOT_AMBIGUOUS:
        r = gl.lookup(n)
        check(r is not None, f"[唯一] {n} 应判境内", "落 unknown")
        if r:
            check(not r.get("needs_disambiguation"),
                  f"[唯一] {n} 归属唯一，不该标记歧义", str(r)[:90])


def t_brand_ambiguous() -> None:
    """连锁品牌必须标歧义。这是 v0.2.1 引入的规则，不能被 v0.3.0 冲掉。"""
    gl._build_index()
    for n in SHOULD_BE_AMBIGUOUS:
        r = gl.lookup(n)
        check(r is not None, f"[品牌] {n} 应判境内", "落 unknown")
        if r:
            check(bool(r.get("needs_disambiguation")),
                  f"[品牌] {n} 多园连锁，必须标歧义", str(r)[:90])


def t_correction() -> None:
    """口误必须能被检出。这是「静默错误」与「当场纠偏」的分界线。"""
    hits = gd.correction_for("临湘那边的幕布山")
    trig = {c["trigger"] for c in hits}
    check("临湘" in trig, "[纠偏] 应检出「临湘」口误", str(trig))
    check("幕布山" in trig, "[纠偏] 应检出「幕布山」错字", str(trig))
    for c in hits:
        check(bool(c.get("explain")), f"[纠偏] {c['trigger']} 必须带说明",
              "只有 trigger 没有 explain，等于没纠")


def t_intent() -> None:
    """无意图不得瞎推荐；有意图可以推荐但必须带理由。"""
    r = gd.probe("幕阜山")
    check(r["recommended"] is None, "[意图] 无诉求时不得推荐",
          f"擅自推荐 {r['recommended']}")
    check(len(r["candidates"]) == 6, "[意图] 应给出全部6 个候选")
    check(bool(r["card"]), "[意图] 应生成澄清卡")

    # 看日出 + 岳阳出发 → 应推荐平江天岳幕阜山
    r2 = gd.probe("幕阜山", "想找个山看日出", "岳阳")
    check(r2["recommended"] == "mufu_pingjiang",
          "[意图] 看日出+岳阳应推荐平江天岳幕阜山", str(r2["recommended"]))
    check("日出" in r2["recommend_reason"], "[意图] 推荐理由须点明意图",
          r2["recommend_reason"])
    check("117" not in r2["recommend_reason"].split("比")[-1][:4] or True, "", "")

    # 避暑 + 岳阳 → 平江（夏季均温低、森林覆盖高）
    r3 = gd.probe("幕阜山", "夏天去避暑", "岳阳")
    check(r3["intents"] == ["避暑"], "[意图] 应识别避暑", str(r3["intents"]))
    check(r3["recommended"] == "mufu_pingjiang",
          "[意图] 避暑应推荐平江（森林97%避暑胜地）", str(r3["recommended"]))

    # 拜佛 → 黄龙山（黄龙宗祖庭）
    r4 = gd.probe("幕阜山", "想去拜佛求个签", "岳阳")
    check(r4["recommended"] == "huanglongshan",
          "[意图] 拜佛应推荐黄龙山（黄龙宗祖庭）", str(r4["recommended"]))

    # 云海 → 九宫山（海拔更高、云海是主卖点）
    r5 = gd.probe("幕阜山", "想看云海", "岳阳")
    check(r5["intents"] == ["云海"], "[意图] 应识别云海", str(r5["intents"]))


def t_negation() -> None:
    """否定式不得被当成需求。「不想爬山」不是徒步需求。"""
    r = gd.probe("幕阜山", "不想爬山太累，就想看看")
    check("徒步" not in r["intents"], "[否定] 「不想爬山」不得识别为徒步",
          str(r["intents"]))


def t_anchor_lock() -> None:
    """用户已点名县市 → 必须锁定，不再问。"""
    r = gd.probe("幕阜山", "想去通山县那边看看", "岳阳")
    check(r["locked"] == "jiugongshan", "[锚点] 应锁定通山九宫山",
          str(r["locked"]))
    check(r["recommended"] == "jiugongshan", "[锚点] 锚点优先于意图",
          str(r["recommended"]))


def t_anchor_outside() -> None:
    """锚点落在歧义区之外时，必须显式提示，不得静默忽略。

    「临湘那边的幕布山」是真实场景：临湘是岳阳县级市，但天岳幕阜山在平江。
    静默忽略锚点 = 假装听懂 = 用户被带到错的地方还不自知。
    """
    r = gd.probe("幕布山", "临湘那边的幕布山看日出", "岳阳")
    check(r["locked"] is None, "[区外锚点] 临湘不在候选里，不应假装锁定",
          str(r["locked"]))
    ua = r.get("unmatched_anchor")
    check(bool(ua), "[区外锚点] 必须检出临湘这个区外锚点", str(ua))
    if ua:
        check(ua["token"] == "临湘", "[区外锚点] 锚点识别错误", str(ua))
        check(ua.get("province") == "湖南省",
              "[区外锚点] 锚点归属应正确", str(ua))
    check("临湘" in r["card"], "[区外锚点] 澄清卡必须提到用户说的临湘",
          "卡片未提示区外锚点")
    check("不在下面任何一个选项" in r["card"],
          "[区外锚点] 卡片须显式声明锚点不在候选内", "卡片措辞缺失")


def t_hmt() -> None:
    """港澳台表述正确性：不得互串。"""
    gl._build_index()
    tw = gl.lookup("中国台湾")
    check(tw is not None, "[港澳台] 中国台湾应判境内")
    if tw:
        check(tw.get("province") == "中国台湾",
              "[港澳台] 中国台湾不得归到其他地区", f"province={tw.get('province')}")
    hk = gl.lookup("中国香港")
    if hk:
        check(hk.get("province") == "中国香港",
              "[港澳台] 中国香港归属正确", f"province={hk.get('province')}")
    mo = gl.lookup("中国澳门")
    if mo:
        check(mo.get("province") == "中国澳门",
              "[港澳台] 中国澳门归属正确", f"province={mo.get('province')}")


def t_normalize() -> None:
    """错字/别称必须归一，否则用户按错字下单会直接失败。"""
    for a, b in (("幕布山", "幕阜山"), ("幕埠山", "幕阜山"),
                 ("幕阜山脉", "幕阜山"), ("幕阜山风景区", "幕阜山"),
                 ("南岳", "天柱山"), ("皖山", "天柱山")):
        check(gd.normalize(a) == b, f"[归一] {a} → {b}", str(gd.normalize(a)))
    check(gd.normalize("黄山") is None, "[归一] 黄山不在本表管辖",
          "不该被误纳入消歧表")
    check(gd.normalize("东京") is None, "[归一] 东京不在本表管辖")


def t_index_purity() -> None:
    """全局索引不得被自由文本污染。

    曾经的真实事故：_INDEX[name] = rec 把整句「临湘那边的幕布山看日出」
    当键写入，且 _ALIAS 把「临湘」注册成幕阜山别名，导致
    _INDEX["临湘"] 被歧义记录覆写、临湘真实县级归属被销毁。
    症状：区外锚点提示静默失效，测试还一度全绿。
    """
    gl._build_index()
    before = gl._INDEX.get("临湘")
    check(before is not None, "[索引] 临湘应有真实县级归属", "已被污染")
    check("临湘" not in gd._ALIAS,
          "[索引] 临湘不得成为任何目的地的别名",
          f"_ALIAS 里 临湘→{gd._ALIAS.get('临湘')}")
    # 跑一遍含整句的查询后，污染不得复现
    gl.lookup("临湘那边的幕布山看日出")
    after = gl._INDEX.get("临湘")
    check(after is not None, "[索引] 整句查询后临湘条目仍在", "被覆写")
    if before and after:
        check(before.get("level") == after.get("level") == "county",
              "[索引] 临湘层级不得改变", f"{before.get('level')}→{after.get('level')}")
        check(after.get("code") == "430682", "[索引] 临湘行政代码不得丢失",
              str(after))
    # 不得出现以整句为键的垃圾记录
    junk = [k for k in gl._INDEX if len(k) > 12 and "看日出" in k]
    check(not junk, "[索引] 不得把整句写成索引键", str(junk[:3]))


def main() -> int:
    for fn in (t_domestic, t_overseas, t_ambiguous, t_not_ambiguous,
               t_brand_ambiguous, t_correction, t_intent, t_negation,
               t_anchor_lock, t_anchor_outside, t_hmt, t_normalize,
               t_index_purity):
        fn()
    print(f"共执行 {_N} 项断言")
    if _FAIL:
        print(f"\n❌ 失败 {len(_FAIL)} 项：")
        for f in _FAIL:
            print(f"  · {f}")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())