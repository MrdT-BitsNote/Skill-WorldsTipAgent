#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intent_guard.py — 负向意图闸门（v0.2.22 新增）

背景：v0.2.1 / v0.1.49 的 route.classify() 对非出行请求一律回落 domestic，
「帮我写一份本周工作总结」会被当成旅行规划。本模块在路由之前做确定性判定。

纪律：
  - 纯标准库、零联网、零第三方依赖、只读本地规则表。
  - 只做「是不是出行请求」这一个判断，不猜目的地、不猜天数。
  - 判定为否时给出明确去向，不生成任何行程内容，不静默降级。
  - 退出码：0 = 放行；3 = 拦截；2 = 参数错误。
"""
from __future__ import print_function

import argparse
import json
import re
import sys

# ---------------------------------------------------------------- 规则表
# 出行强信号：出现任一即放行（哪怕同时命中办公词，出行优先）。
TRAVEL_STRONG = (
    "旅行", "旅游", "出行", "行程", "攻略", "游记", "路线", "路书", "自驾",
    "徒步", "爬山", "登山", "日出", "日落", "露营", "骑行", "摩旅", "摩托",
    "机车", "房车", "自驾游", "citywalk", "city walk", "周边游", "周末去",
    "去哪玩", "玩几天", "几日游", "几日", "日游", "度假", "打卡", "景区",
    "景点", "门票", "住宿", "酒店", "民宿", "订房", "分房", "签证", "护照",
    "出境", "入境", "免签", "落地签", "航班", "机票", "高铁", "火车", "车票",
    "加油站", "补给", "导航", "高速", "限高", "海拔", "高反", "天气预检",
    "怎么去", "怎么走", "怎么玩", "怎么安排", "几天合适", "预算多少",
)

# 明确非出行：出现且无任何出行强信号时拦截。
NON_TRAVEL = (
    "工作总结", "周报", "月报", "日报", "年终总结", "述职", "汇报材料",
    "写代码", "改代码", "debug", "重构", "单元测试", "写脚本", "部署",
    "数据库", "接口文档", "需求文档", "产品需求", "prd", "会议纪要",
    "写作文", "写论文", "翻译", "润色", "简历", "求职信", "合同",
    "做表格", "做ppt", "做pptx", "excel", "财务报表", "记账",
    "写诗", "起名", "解梦", "算命", "菜谱", "做饭", "健身计划",
    "看病", "诊断", "用药", "法律咨询", "起诉", "报税",
)

# 弱信号：单独出现不足以放行，需与强信号或地名共现。
TRAVEL_WEAK = ("玩", "逛", "吃", "住", "走", "去", "预算", "安排", "推荐")

# 日期/天数/人数等出行参数也算信号。
PARAM_PAT = re.compile(
    r"(\d+\s*天|\d+\s*日|\d+\s*晚|周末|假期|小长假|国庆|春节|"
    r"\d+\s*人|一个人|独自|情侣|亲子|带娃|预算\s*\d+|\d+\s*元)"
)

PLACE_SUFFIX = ("山", "湖", "古城", "古镇", "公园", "景区", "寺", "岛",
                "瀑布", "草原", "沙漠", "峡谷", "村", "镇", "县", "市", "省")


def judge(text, outbound_hints=(), place_hint=""):
    """返回 (verdict, reason, hits)。verdict: 'pass' | 'reject'。

    outbound_hints 由调用方注入（复用 route.OUTBOUND_HINT）：命中时明确告知
    本版覆盖国内目的地，而不是含糊地报「未识别出行意图」。

    place_hint 由 geo_extract 的权威地名库给出。补的是这一格坏法：
    「从岳阳出发到张家界，2天1晚」没有出行强词，但带出行参数且命中真实地名，
    若只靠本地后缀表猜就会误拒。地名判定以权威库为准，不在此重复造一份词表。
    """
    t = (text or "").strip()
    if not t:
        return "reject", "输入为空，请给出一句出行需求", []
    low = t.lower()

    # 覆盖边界优先：本版为国内单模式，命中境外提示时如实说明，不静默降级。
    ob = [w for w in outbound_hints if w and w in t]
    if ob and not any(w in t for w in ("中国", "国内", "港澳台")):
        return "reject", ("本版聚焦国内目的地；「%s」属境外，暂不覆盖。"
                          "请改用国内目的地，或说明是境内同名地点" % ob[0]), ob

    strong = [w for w in TRAVEL_STRONG if w.lower() in low]
    non = [w for w in NON_TRAVEL if w.lower() in low]
    weak = [w for w in TRAVEL_WEAK if w in low]
    param = bool(PARAM_PAT.search(t))
    place = [w for w in PLACE_SUFFIX if w in t]

    # 出行强信号优先：即使句子里也提到「预算/安排」等办公词，仍放行。
    if strong:
        return "pass", "命中出行强信号：%s" % "、".join(strong[:4]), strong

    # 无强信号但带明确非出行任务词 → 拦截。
    if non:
        return "reject", "命中非出行任务：%s" % "、".join(non[:3]), non

    # 出行参数 + 权威地名命中 → 视作省略了玩法动词的口语出行请求。
    # 优先采信 geo_extract 的地名库结果，避免本地后缀表把「张家界」这类漏掉。
    if param and place_hint:
        return "pass", "出行参数 + 权威地名命中（%s）" % place_hint, [place_hint]
    if param and place:
        return "pass", "出行参数 + 地名尾缀共现", place[:3]

    # 弱信号单独出现不放行（「帮我安排一下」「推荐一下」太泛）。
    if weak and not param:
        return "reject", "仅有泛化措辞（%s），缺少出行对象" % "、".join(weak[:3]), weak

    return "reject", "未识别到出行意图，请补充目的地或玩法", []


def main():
    ap = argparse.ArgumentParser(description="出行意图负向闸门")
    ap.add_argument("text", nargs="?", default="", help="用户原话")
    ap.add_argument("--json", action="store_true", help="结构化输出")
    a = ap.parse_args()
    verdict, reason, hits = judge(a.text)
    out = {"verdict": verdict, "reason": reason, "hits": hits,
           "hint": "" if verdict == "pass" else
           "本技能只处理出行规划。文档写作、代码、报表等请直接使用通用能力。"}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(("[PASS] " if verdict == "pass" else "[REJECT] ") + reason)
        if out["hint"]:
            print(out["hint"])
    return 0 if verdict == "pass" else 3


if __name__ == "__main__":
    sys.exit(main())
