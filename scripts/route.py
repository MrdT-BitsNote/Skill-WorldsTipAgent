#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route.py — 技能入口路由器（v0.1.42 新增）

作用：把「我现在该跑哪些脚本 / 读哪些文档 / 加载哪些数据」这一步决策外包给代码，
AI 不必读完 SKILL.md 再自行推断执行路径。

用法：
    python scripts/route.py "周末想去张家界爬山看日出"
    python scripts/route.py --to 张家界 --style hiking --days 2 --json
    python scripts/route.py "找点桂林的攻略" --json

输出（默认 Markdown，--json 出结构化）：
    1. intent   —— 意图分类（国内/摩旅/房车/路书/攻略检索/散心…）
    2. steps    —— 该跑哪些脚本（带可直接复制的参数模板）
    3. docs     —— 该加载哪些 docs/*.md（不加载的就不读，省 token）
    4. refs     —— 该读哪些 references/*.json
    5. network  —— 联网要求（required / optional / none）
    6. skip     —— 明确不需要做的事（防止过度执行）

设计纪律：
    - 纯 Python 标准库，零第三方依赖，无 API key，跨平台。
    - 只读本地静态规则表，不做任何联网请求。
    - 判定优先复用 geo_lookup.is_domestic()；不可用则退回内置名单。
    - 退出码恒为 0（路由是建议，不是闸门），除非 --help/参数错误。
"""
from __future__ import print_function

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------- 规则表

# 意图关键词：(意图 id, 命中词列表)
INTENT_RULES = [
    ("outbound", ["国外", "外国",
                  "大使馆", "领事", "海关"]),  # 去除受限词
    ("moto", ["摩旅", "摩托车", "骑摩托", "机车", "跑山", "压弯", "摩旅路线", "G318",
              "川藏线", "独库公路", "丙察察", "环青海湖", "禁摩", "限摩", "能不能上高速",
              "踏板", "挡车", "adv"]),
    ("rv", ["房车", "露营地", "房车营地", "床车", "黑水", "灰水", "排污", "倒马桶",
            "房车限高", "限高杆", "C6驾照", "拖挂", "旅居挂车", "加水", "市电",
            "房车补给", "房车停放", "营地预约"]),
    ("roadbook", ["路书", "road trip", "route book", "itinerary", "多日行程", "行程单",
                  "路程册", "route planning", "travel itinerary", "multi-day trip",
                  "每日行程", "行程路线"]),
    ("guide", ["找攻略", "查攻略", "搜攻略", "有没有攻略", "看看别人怎么玩", "找点游记",
               "游记参考", "攻略参考", "有什么攻略", "帮我找找", "整理进小册子", "攻略"]),
    ("relax", ["散心", "心情不好", "随便去哪", "不想上班", "想出去走走", "放空", "治愈",
               "一个人静静", "想出去玩", "need a break", "放松"]),
    ("extreme", ["冲浪", "跳伞", "攀岩", "滑雪", "潜水", "翼装", "滑翔", "蹦极",
                 "越野", "溯溪", "漂流", "极限运动"]),
    ("concert", ["演唱会", "演出", "音乐节", "live house", "livehouse", "门票抢", "演唱会攻略"]),
    ("cycling", ["骑行", "骑车", "自行车", "环湖", "公路车", "山地车"]),
    ("hiking", ["徒步", "爬山", "登山", "看日出", "看日落", "郊野", "步道", "徒步路线"]),
    ("photo", ["拍照", "出片", "星空", "银河", "星轨", "日出机位", "摄影", "机位", "延时"]),
    ("family", ["亲子", "带娃", "带孩子", "宝宝", "小孩", "一家三口", "四口"]),
    ("food", ["美食", "吃什么", "必吃", "小吃", "探店"]),
]

# 地理兜底（不可用时的最小名单）
OUTBOUND_HINT = ["日本", "泰国", "韩国", "新加坡", "马来西亚", "越南", "印尼", "菲律宾",
                 "美国", "加拿大", "英国", "法国", "德国", "意大利", "西班牙", "瑞士",
                 "澳大利亚", "新西兰", "俄罗斯", "土耳其", "埃及", "迪拜", "阿联酋",
                 "柬埔寨", "老挝", "缅甸", "印度", "尼泊尔", "斯里兰卡", "马尔代夫",
                 "巴西", "阿根廷", "智利", "秘鲁", "墨西哥", "南非", "肯尼亚", "摩洛哥",
                 "欧洲", "东南亚", "东亚", "北美", "南美", "大洋洲", "非洲", "中东"]

# 国内 —— 港澳台属中国境内
DOMESTIC_FORCE = ["香港", "澳门", "台湾", "中国香港", "中国澳门", "中国台湾"]

# 意图 → (脚本序列, 需加载 docs, 需读 references, 联网要求)
# 脚本序列里的 {from}/{to}/{days}/{people}/{style} 会用 CLI 参数或空串填充
PLANS = {
    "domestic": {
        "steps": [
            ("scripts/build_itinerary.py",
             "--from {from} --to {to} --days {days} --people {people} "
             '--composition "{composition}" --style {style} --json > plan.json',
             "生成行程骨架（逐日动线 + 住宿 + 预算 + 装备）"),
            ("scripts/plan_transit.py",
             "--from {from} --to {to} --json > transit.json",
             "六方式交通比选（自动分市内/近郊/跨城圈）"),
            ("scripts/render_compact.py",
             "--plan plan.json --research research.json --out 旅行小册子.html --title \"{title}\"",
             "渲染 A5 紧凑卡册（默认渲染器，版式已固化）"),
        ],
        "docs": [],
        "refs": ["destinations.json", "poi.json"],
        "network": "optional",
    },
    "outbound": {
        "steps": [
            ("scripts/outbound_constraints.py",
             "--to {to} --json > outbound.json",
             "约束门禁（准入/货币时差/标准禁忌/安全）"),
            ("scripts/outbound_safety.py",
             "--to {to} --json > safety.json",
             "安全与保护（12308）"),
            ("scripts/build_itinerary.py",
             "--from {from} --to {to} --days {days} --people {people} --json > plan.json",
             "行程骨架（不重排求解器，只注入约束）"),
            ("scripts/render_compact.py",
             "--plan plan.json --out 旅行小册子.html --title \"{title}\"",
             "渲染小册子"),
        ],
        "docs": ["docs/OUTBOUND.md"],
        "refs": ["visa_rules.json", "country_safety.json", "currency_tz.json",
                 "local_customs.json"],
        "network": "required",
    },
    "moto": {
        "steps": [
            ("scripts/moto_check.py",
             "--from {from} --to {to} --cc {cc} --license {license} --json > moto.json",
             "摩旅五项门禁（证件/头盔/高速准入/禁摩/续航）"),
            ("scripts/places_query.py",
             "--province {province} --kw {kw} --limit 8 --json > places.json",
             "景点级候选检索（需扩展包；退出码 2 = 未安装，退回城市级 + 灰灯）"),
            ("scripts/build_itinerary.py",
             '--from {from} --to {to} --days {days} --style moto --json > plan.json',
             "行程骨架（moto 画像自动附门禁与线路候选）"),
            ("scripts/moto_enrich.py", "--plan plan.json --json > checklist.json",
             "出行前待核实清单（政策/补给/路况/天气）"),
            ("scripts/render_compact.py",
             "--plan plan.json --out 旅行小册子.html --title \"{title}\"", "渲染小册子"),
        ],
        "docs": ["docs/MOTO_MODE.md"],
        "refs": ["moto_rules.json", "moto_routes.json", "moto_coverage.json",
                 "moto_access_notes.json", "vehicle_range.json"],
        "network": "optional",
    },
    "rv": {
        "steps": [
            ("scripts/rv_check.py",
             "--from {from} --to {to} --vehicle-type {vehicle} --json > rv.json",
             "房车/自驾后勤五项自检（牌照/限高/补给/黑灰水/营地）"),
            ("scripts/build_itinerary.py",
             "--from {from} --to {to} --days {days} --style roadtrip --json > plan.json",
             "行程骨架"),
            ("scripts/render_compact.py",
             "--plan plan.json --out 旅行小册子.html --title \"{title}\"", "渲染小册子"),
        ],
        "docs": [],
        "refs": ["rv_logistics.json", "vehicle_range.json"],
        "network": "optional",
    },
    "roadbook": {
        "steps": [
            ("scripts/plan_route.py", "--from {from} --to {to} --json > route.json",
             "多目的地排序与距离方位"),
            ("scripts/build_itinerary.py",
             "--from {from} --to {to} --days {days} --json > plan.json", "行程骨架"),
            ("scripts/render_compact.py",
             "--plan plan.json --out 旅行小册子.html --title \"{title}\"", "渲染小册子"),
        ],
        "docs": ["docs/ROUTE_BOOK.md"],
        "refs": ["station_codes.json", "vehicle_range.json"],
        "network": "optional",
    },
    "guide": {
        "steps": [
            ("scripts/guide_list.py", "--kw \"{to} 攻略\" --json > guides.json",
             "攻略清单校验（URL 合法性 + 去重 + 时效告警）"),
            ("scripts/guide_digest.py", "--merge research.json --json > ugc.json",
             "研读沉淀（三元组缺一即拒，防照搬原文）"),
            ("scripts/render_compact.py",
             "--plan plan.json --research research.json --out 旅行小册子.html "
             '--title "{title}"', "沉淀进小册子 §10"),
        ],
        "docs": ["docs/GUIDE_SEARCH.md"],
        "refs": [],
        "network": "required",
    },
    "relax": {
        "steps": [
            ("scripts/suggest_trip.py", "--from {from} --json > suggest.json",
             "目的地灵感推荐（只出目的地报告，不含交通方式）"),
        ],
        "docs": [],
        "refs": ["short_trips.json", "destinations.json"],
        "network": "optional",
    },
}

# 附加意图 → 追加步骤 / 追加数据（可与主意图叠加）
ADDONS = {
    "hiking": {"steps": [("scripts/check_weather.py",
                          "--to {to} --style hiking --days {days} --json > weather.json",
                          "户外天气预检（四档判定，not_recommended 必须换方案）")],
               "refs": ["seasons_climate.json", "weather_contingency.json",
                        "safety_playbook.json"]},
    "cycling": {"steps": [("scripts/check_weather.py",
                           "--to {to} --style cycling --days {days} --json > weather.json",
                           "户外天气预检")],
                "refs": ["seasons_climate.json", "weather_contingency.json"]},
    "extreme": {"steps": [], "refs": ["extreme_sports.json", "altitude_playbook.json"]},
    "concert": {"steps": [], "refs": ["concert_playbook.json"]},
    "photo": {"steps": [], "refs": ["photography_guide.json"]},
    "family": {"steps": [], "refs": ["party_playbooks.json", "audience_profiles.json"]},
    "food": {"steps": [], "refs": ["food_guide.json", "food_book_links.json"]},
}

# 始终要做的事（不管什么意图）
ALWAYS_DOCS = []
ALWAYS_REFS = ["destinations.json"]
ALWAYS_STEP_TAIL = []

# 明确不需要做的事（防过度执行）
SKIP_HINTS = {
    "relax": ["不要输出交通方式比选", "不要排逐日动线", "不要给逐日预算表"],
    "guide": ["不要生成完整行程（除非用户同时要行程）"],
    "outbound": ["不要按国内流程免签直出结论（volatile 必须联网核验）"],
    "moto": ["不要复用普通自驾逻辑（摩托问的是『合法吗』）"],
}

DEFAULT_STYLE = {
    "hiking": "hiking", "cycling": "cycling", "moto": "moto", "rv": "roadtrip",
    "roadbook": "roadtrip", "extreme": "extreme", "photo": "photo",
}


# ---------------------------------------------------------------- 判定

# 摩托专属强词：出现任一即认定真·摩旅，cycling 不得抢主意图。
# 反例（v0.2.1 修）：用户说「环青海湖骑行」，命中 moto 的「环青海湖」与
# cycling 的「骑行」，旧逻辑按 prio 表让 moto 胜出 → 把自行车环湖判成摩旅。
MOTO_STRONG = ("摩托", "机车", "摩旅", "摩友", "压弯", "禁摩", "限摩",
               "踏板", "挡车", "上高速", "adv")

# 自行车明确词：出现即说明是人力车，不该走摩旅画像。
BIKE_WORDS = ("自行车", "单车", "公路车", "山地车", "骑行", "骑车", "环湖骑行")


def _kw_hit(kw, low):
    """关键词命中判定。

    中文按子串匹配（中文没有词边界，这是正确做法）。
    短拉丁词必须加双侧边界：旧实现用裸子串，`adv` 会命中 advice / advance /
    adventure，导致「any advice for Tokyo trip」被判成摩旅。
    """
    k = kw.lower()
    if k.isascii() and len(k) <= 4:
        return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", low) is not None
    return k in low


def _has_moto_strong(low):
    return any(_kw_hit(k, low) for k in MOTO_STRONG)


def _is_bike_only(low):
    """出现自行车词且没有任何摩托强词 → 是人力骑行，不是摩旅。"""
    return any(k in low for k in BIKE_WORDS) and not _has_moto_strong(low)


def classify(text, to=None):
    """返回 (主意图, 附加意图列表)"""
    t = (text or "") + " " + (to or "")
    low = t.lower()

    hits = []
    for iid, kws in INTENT_RULES:
        for kw in kws:
            if _kw_hit(kw, low):
                hits.append(iid)
                break
    # 去重保序
    seen, uniq = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)

    # 自行车优先：命中自行车词且无摩托强词时，moto 让位（v0.2.1 修）
    # 「环青海湖骑行」→ cycling；「骑摩托车环湖」→ 仍 moto（有「摩托」强词）
    if "moto" in uniq and _is_bike_only(low):
        uniq = [h for h in uniq if h != "moto"]
        if "cycling" not in uniq:
            uniq.append("cycling")

    # 判定：优先复用技能自带的权威白名单（港澳台属境内）
    # 注意：不能拿整句话去问 is_outbound()——白名单外的中文串会默认「试判」，
    # 会把「周末想去张家界爬山看日出」误判。必须只拿「地名候选词」去问。
    is_out = False
    if "outbound" in uniq:
        is_out = True

    # 港澳台强制境内（优先级最高）
    forced_domestic = any(d in t for d in DOMESTIC_FORCE)

    if not forced_domestic:
        # 收集地名候选词：--to 优先，否则从原话里抽取提示词
        probes = []
        if to:
            probes.append(to)
        elif text:
            for c in OUTBOUND_HINT:
                if c in text:
                    probes.append(c)
        probes = list(dict.fromkeys(probes))

        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import outbound_constraints as ob  # noqa
            fn = ob.is_outbound if hasattr(ob, "is_outbound") \
                else (lambda x: not ob.is_domestic(x))
            for p in probes:
                if fn(p):
                    is_out = True
                    break
        except Exception:
            for p in probes:
                if any(c in p for c in OUTBOUND_HINT):
                    is_out = True
                    break

    if is_out:
        main = "outbound"
        addons = [h for h in uniq if h != "outbound"]
    else:
        # 主意图优先级：moto > rv > roadbook > guide > relax > 其他
        prio = ["moto", "rv", "roadbook", "guide", "relax"]
        main = "domestic"
        for p in prio:
            if p in uniq:
                main = p
                break
        addons = [h for h in uniq if h != main and h in ADDONS]

    return main, addons, is_out


def detect_to(text, to):
    """--to 未给时，从原话里抽一个最可能的地名，让参数模板可直接复制使用。
    只抽提示词（国内城市名库太大，就地抽取不划算——国内目的地由工作流第 1 步问出来）。"""
    if to:
        return to
    if not text:
        return ""
    best = ""
    for c in OUTBOUND_HINT:
        if c in text and len(c) > len(best):
            best = c
    return best


def pick_style(main, addons, explicit):
    """推断 --style：显式指定 > 主意图强画像 > 附加意图 > leisure。

    修掉两个真缺陷：
    1. v0.1.42：用户说「爬山看日出」时主意图是 domestic，若只看主意图会给出
       --style leisure，导致 build_itinerary 用错节奏画像 → 附加意图优先。
    2. v0.2.1：主意图本身带强画像时（moto/rv/roadbook），附加意图不得反客为主。
       「骑摩托车环湖」同时命中 moto 与 cycling，旧逻辑取 addons 里的 cycling →
       --style cycling，摩旅门禁与续航画像全部失效。
    """
    if explicit:
        return explicit
    if main in DEFAULT_STYLE:
        return DEFAULT_STYLE[main]
    for a in addons:
        if a in DEFAULT_STYLE:
            return DEFAULT_STYLE[a]
    return "leisure"


# build_itinerary.py 的 infer_intents() 只认这 6 个 tag（见其 VALID_INTENTS）。
# route 侧还有 moto / rv / cycling / roadbook / extreme 等附加意图，不能直接塞进 --tag。
_BUILD_ITINERARY_TAGS = {"hiking", "sunrise", "avoid_crowd", "photo", "foodie",
                         "culture"}


def _with_intent_args(steps, fmt, args, addons):
    """给 build_itinerary.py 的命令补 --hint / --tag。

    修掉一个真缺陷（v0.1.42 引入本路由时接线遗漏）：生成的命令只带 --style，
    没带 --hint（用户原话）也没带 --tag（附加意图），而 build_itinerary 的
    infer_intents() 恰好只从这两处取意图 → intents 恒为空 → 「日出优先 / 爬山节奏 /
    错峰策略 / 拍照机位」等偏好条目全部丢失，用户明明说了「看日出」却拿不到日出排布。
    """
    hint = (args.get("text") or "").strip()
    tags = [a for a in addons if a in _BUILD_ITINERARY_TAGS]
    suffix = ""
    if hint:
        suffix += ' --hint "%s"' % hint.replace('"', "'")
    if tags:
        suffix += " --tag %s" % " ".join(tags)

    out = []
    for s in steps:
        cmd = s["cmd"].format(**fmt)
        if "build_itinerary.py" in cmd and suffix:
            # 追加参数必须插在 shell 重定向之前：`cmd --hint "..." > plan.json`
            # 直接拼到末尾会变成 `... > plan.json --hint "..."`，虽能被 shell 解析，
            # 但可读性差、易被误读为重定向目标的一部分。
            if " > " in cmd:
                head, _, tail = cmd.partition(" > ")
                cmd = "%s%s > %s" % (head, suffix, tail)
            else:
                cmd += suffix
        out.append(dict(s, cmd=cmd))
    return out


# 日期片段：必须先剥掉，否则「10月3日」会被 (\d+)日 抓成 3 天（v0.2.1 修）
_RE_MONTH_DAY = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_RE_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_RE_SHORT_DATE = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)")


def _strip_dates(text):
    """把日期片段从文本里挖掉，只留「天数」语义可用的部分。"""
    t = _RE_MONTH_DAY.sub(" ", text)
    t = _RE_ISO_DATE.sub(" ", t)
    t = _RE_SHORT_DATE.sub(" ", t)
    return t


def _date_span_days(text):
    """两个日期之间的跨度（含首尾）。只有一个日期时返回 0——单日不等于行程天数。"""
    pairs = [(int(m), int(d)) for m, d in _RE_MONTH_DAY.findall(text)]
    if len(pairs) < 2:
        iso = [(int(m), int(d)) for _, m, d in _RE_ISO_DATE.findall(text)]
        if len(iso) >= 2:
            pairs = iso
    if len(pairs) < 2:
        return 0
    (m1, d1), (m2, d2) = pairs[0], pairs[1]
    span = 0
    # 用 date 对象精确算含首尾跨度；2 月按平年 28 天，只差天数不影响结论
    try:
        import datetime
        y = 2001
        y2 = y + 1 if m2 < m1 else y   # 跨年：12月 → 1月
        span = (datetime.date(y2, m2, d2) - datetime.date(y, m1, d1)).days + 1
    except Exception:
        return 0
    return span if 1 <= span <= 60 else 0


def detect_days(text):
    """从原话抽天数：「3天」「两天」「10月3日-10月6日」等。抽不到返回 ''。

    v0.2.1 修掉一个真缺陷：旧实现直接 `(\\d+)\\s*(?:天|日)` 全串匹配，
    「10月3日出发」被抓成 3 天、「帮我订10月3日的房」也被抓成 3 天。
    正确顺序是：先剥日期 → 再抽显式天数 → 再看日期跨度 → 最后中文数字。
    单个日期不推断天数（那是出发日，不是行程长度），抽不到就返回空，
    由调用方标注假设，绝不编造。
    """
    if not text:
        return ""
    stripped = _strip_dates(text)

    # 1) 显式天数优先（用户明说的天数最可信）
    m = re.search(r"(\d+)\s*(?:天|日)", stripped)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 30:
            return str(n)

    # 2) 日期区间 → 跨度天数
    span = _date_span_days(text)
    if span:
        return str(span)

    # 3) 中文数字
    CN = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}
    m = re.search(r"([一二两三四五六七八九十])\s*(?:天|日)", stripped)
    if m:
        return str(CN.get(m.group(1), 2))
    return ""


def detect_people(text):
    """从原话抽人数：「2人」「三个人」「情侣」「带娃/亲子」等。抽不到返回 ''。"""
    if not text:
        return ""
    m = re.search(r"(\d+)\s*(?:人|个人|位)", text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 30:
            return str(n)
    if re.search(r"独自|一个人|单人|自己一个人|独行|独自一人", text):
        return "1"
    if re.search(r"情侣|两人|两个人|夫妻|对象|男朋友|女朋友|两口子|老婆|老公|太太|媳妇|丈夫|爱人", text):
        return "2"
    if re.search(r"带娃|亲子|孩子|一家|全家|家庭", text):
        return "3"
    return ""


# 人员构成必须与人数自洽，且只能来自原话特征（v0.2.1 修）
# 旧实现写死 composition="独自一人"，导致「和老婆两个人玩三天」输出
# --people 2 --composition "独自一人"，两个参数互相打脸。
_COMP_RULES = [
    (r"情侣|夫妻|对象|男朋友|女朋友|两口子|蜜月|老婆|老公|先生|太太|媳妇|丈夫|爱人", "情侣"),
    (r"带娃|亲子|孩子|宝宝|小孩", "带娃"),
    (r"一家三口|三口之家", "三口"),
    (r"一家四口|四口之家", "四口"),
    (r"独自|一个人|单人|独行", "独自一人"),
    (r"朋友|同学|同事|闺蜜|兄弟", "朋友同行"),
    (r"父母|爸妈|老人|长辈", "含长辈"),
]


def detect_composition(text, people):
    """按原话特征推断人员构成；抽不到则按人数给中性描述，绝不默认「独自一人」。"""
    t = text or ""
    for pat, label in _COMP_RULES:
        if re.search(pat, t):
            return label
    try:
        n = int(people) if str(people).strip() else 0
    except Exception:
        n = 0
    if n <= 0:
        return ""              # 人数也没说 → 不编造构成
    if n == 1:
        return "独自一人"
    return "%d人同行" % n


def build(main, addons, args):
    plan = PLANS.get(main, PLANS["domestic"])
    _txt = args.get("text") or ""
    # v0.2.1：抽不到就标注假设，不静默编造。
    # 旧实现 people 默认 "1"、composition 写死 "独自一人"，而 build_itinerary 的
    # 默认是 2 人 / composition 空——路由把下游更合理的默认覆盖成了错误值。
    _days = args.get("days") or detect_days(_txt)
    _people = args.get("people") or detect_people(_txt)
    _comp = args.get("composition") or detect_composition(_txt, _people)
    assumptions = []
    if not _days:
        _days = "2"
        assumptions.append("天数未指定，按 2 天估算；请与用户确认实际天数")
    if not _people:
        _people = "2"          # 与 build_itinerary --people 默认值一致，非新造数
        assumptions.append("人数未指定，按 2 人估算；请与用户确认同行人数")
    if not _comp:
        _comp = detect_composition(_txt, _people) or "同行"
        assumptions.append("人员构成未指定，按人数中性描述；亲子/情侣会影响房间分配，需确认")
    fmt = {
        "from": args.get("from") or "出发地",
        "to": args.get("to") or "目的地",
        "days": _days,
        "people": _people,
        "composition": _comp,
        "style": pick_style(main, addons, args.get("style")),
        "title": args.get("title") or (args.get("to") or "旅行") + "行程小册子",
        "province": args.get("province") or "",
        "kw": args.get("kw") or "",
        "cc": args.get("cc") or "250",
        "license": args.get("license") or "E",
        "vehicle": args.get("vehicle") or "suv",
    }

    steps = [{"script": s, "cmd": "python %s %s" % (s, c), "why": w}
             for s, c, w in plan["steps"]]
    docs = list(plan["docs"])
    refs = list(plan["refs"])
    network = plan["network"]

    for a in addons:
        add = ADDONS.get(a)
        if not add:
            continue
        for s, c, w in add["steps"]:
            steps.insert(max(0, len(steps) - 1),
                         {"script": s, "cmd": "python %s %s" % (s, c), "why": w})
        refs.extend(add["refs"])

    # 去重保序
    def uniq(xs):
        seen, o = set(), []
        for x in xs:
            if x and x not in seen:
                seen.add(x)
                o.append(x)
        return o

    return {
        "intent": main,
        "addons": addons,
        "outbound": main == "outbound",
        "steps": _with_intent_args(steps, fmt, args, addons),
        "docs": uniq(docs + ALWAYS_DOCS),
        "refs": uniq(refs + ALWAYS_REFS),
        "network": network,
        "skip": SKIP_HINTS.get(main, []),
        "assumptions": assumptions,
        "note": "本路由为建议路径，不是闸门。SKILL.md 的硬纪律（先查后问、绝不编造、"
                "volatile 必核验）优先级高于本表。",
    }


def to_markdown(r):
    o = []
    o.append("## 意图判定")
    o.append("")
    o.append("- **主意图**：`%s`%s" % (r["intent"],
                                     "（分支）" if r.get("outbound") else ""))
    if r["addons"]:
        o.append("- **附加**：%s" % "、".join("`%s`" % a for a in r["addons"]))
    o.append("- **联网**：%s" % {"required": "**必须**（volatile 事实需核验并打日期戳）",
                                "optional": "可选（本地数据优先，缺口才联网）",
                                "none": "不需要"}[r["network"]])
    o.append("")
    o.append("## 执行步骤")
    o.append("")
    for i, s in enumerate(r["steps"], 1):
        o.append("%d. **%s** —— %s" % (i, s["script"], s["why"]))
        o.append("   ```bash")
        o.append("   %s" % s["cmd"])
        o.append("   ```")
    o.append("")
    if r["docs"]:
        o.append("## 按需加载文档（未列出的 docs 不要读）")
        o.append("")
        for d in r["docs"]:
            o.append("- `%s`" % d)
        o.append("")
    else:
        o.append("## 按需加载文档")
        o.append("")
        o.append("- 无需额外加载（SKILL.md 已够）")
        o.append("")
    if r["refs"]:
        o.append("## 相关 references（按需读取，禁止全文读入大文件）")
        o.append("")
        o.append("- %s" % "、".join("`%s`" % x for x in r["refs"]))
        o.append("")
    if r["skip"]:
        o.append("## 明确不做")
        o.append("")
        for s in r["skip"]:
            o.append("- %s" % s)
        o.append("")
    o.append("> %s" % r["note"])
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser(
        description="WorldsTip 技能入口路由器：输入用户原话，输出该跑哪些脚本 / "
                    "读哪些文档 / 加载哪些数据。")
    ap.add_argument("text", nargs="?", default="", help="用户原话 / 需求描述")
    ap.add_argument("--from", dest="frm", default="")
    ap.add_argument("--to", dest="to", default="")
    ap.add_argument("--days", default="")
    ap.add_argument("--people", default="")
    ap.add_argument("--style", default="")
    ap.add_argument("--composition", default="")
    ap.add_argument("--province", default="")
    ap.add_argument("--kw", default="")
    ap.add_argument("--cc", default="")
    ap.add_argument("--license", default="")
    ap.add_argument("--vehicle", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args()

    args = {"from": a.frm, "to": a.to, "days": a.days, "people": a.people,
            "style": a.style, "composition": a.composition, "province": a.province,
            "kw": a.kw, "cc": a.cc, "license": a.license, "vehicle": a.vehicle,
            "title": a.title,
            # v0.1.44：原话必须透传。build() 要用它给 build_itinerary 拼 --hint。
            "text": a.text}

    main_i, addons, is_out = classify(a.text, a.to)
    if not args["to"]:
        args["to"] = detect_to(a.text, "")
    r = build(main_i, addons, args)

    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
