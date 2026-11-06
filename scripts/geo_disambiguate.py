#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨省同名地理实体消解器（零依赖）—— worldstip-travel-planner

解决的问题
----------
用户说「我想去幕布山玩」。这不是一个地名查询问题，是一个【决策歧义】问题：

  幕阜山是绵延约160公里、横跨湘鄂赣三省的山脉。
  ·平江天岳幕阜山  看日出点位明确、有索道、离岳阳最近
  ·九宫山        海拔更高、云海是主卖点、在湖北通山
  ·黄龙山        拜佛黄龙宗祖庭、道教第二十五洞天之一
  ·黄袍山/太阳山  野线冷门、几乎无设施
  ·大幕山        樱花油菜花海、星轨热门

如果解析器返回单一结果并直接开始排程，它就是在替用户猜。用户到了现场
才发现不是想去的那座山——这不是「回答不准」，是**让人白跑一趟**。
单归属模型在这里不是不够精确，而是**结构上错误**。

三类处理，与 ambiguity_type 对应
--------------------------------
  cross_province_homonym  一名多山（幕阜山、五指山）→ 必须给候选清单
  cross_province_range     一名一山脉多支脉（天柱山/南岳）→ 必须给候选清单
  name_collision_with_history 旧称与今称冲突（南岳）→ 必须给候选清单

核心纪律：先查后问（Ask With Evidence）
---------------------------------------
❌ 反例：「请问你想去哪个幕阜山？」
   ——用户不知道有几个选项，无法回答，只能猜。

✅ 本模块的做法：
   1. candidates()  先查出全部候选，带上差异维度（海拔/省/看什么/交通）
   2. clarify_card() 渲染成一张对比表 + 一句直白的问题
   3. 用户看到差异之后再选 → 这时的问题是可以回答的
   「你想看云海还是想轻松看日出？」是能回答的；
   「你想去哪个幕阜山？」是不能回答的。

意图加权（Intent Weighting）
----------------------------
用户往往不指定地点，而是指定诉求：「想找个山看日出」。
此时不该问「去哪座山」，而该按诉求匹配并直说：
  「你这个诉求最匹配九宫山，因为云海是它的主卖点、海拔更高；
   但如果你是从岳阳出发、平江天岳幕阜山更省力——你更在意云海还是省力？」

intent_fit 分数来自 geo_ambiguous.json，每个候选自带维度打分。
距离项用 haversine 从候选坐标到出发地粗算，权重刻意压低——
坐标是示意坐标，精度不足以支撑精细排序，只够判断「差 20km 还是差 800km」。

纠偏（Correction）
------------------
用户给出的锚点与已知归属冲突时，必须当场说明。
例：「临湘那边的幕布山」→ 天岳幕阜山实际在平江县南江镇。
静默替换会让用户走错县城多花一小时山路；当场说明只需一句话。

安全约束
--------
本模块只做【境内跨省歧义】消解，不碰境内外判定。
境内外由 geo_lookup 负责——两者职责分开，避免一处改动引发漏拦签证门禁。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refloader

REF_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references"
)

_DB: dict | None = None
_ALIAS: dict[str, str] = {}   # 别名/错写 → canonical

# ── 意图词表：用户说法 → 规范意图 ────────────────────────────────
# 左边是用户口语里可能出现的一切说法，右边是打分用的规范名。
# 「看日出」「爬到山顶等太阳」「迎着第一缕光」都要落到"日出"上。
INTENT_SYNONYMS: dict[str, str] = {
    "日出": "日出", "看日出": "日出", "日出云海": "日出", "晨光": "日出",
    "第一缕阳光": "日出", "迎日出": "日出", "早上看太阳": "日出", "黎明": "日出",
    "云海": "云海", "看云海": "云海", "云瀑": "云海", "雾海": "云海", "云雾": "云海",
    "避暑": "避暑", "凉快": "避暑", "夏天去": "避暑", "避热": "避暑", "纳凉": "避暑",
    "避寒": "避寒", "冬天去": "避寒", "过冬": "避寒", "暖": "避寒",
    "星空": "星空", "银河": "星空", "星轨": "星空", "看星星": "星空", "露营观星": "星空",
    "祈福": "祈福", "拜佛": "祈福", "求签": "祈福", "烧香": "祈福",
    "道观": "祈福", "道教": "祈福", "庙": "祈福",
    "徒步": "徒步", "爬山": "徒步", "登山": "徒步", "爬": "徒步", "走线": "徒步",
    "野线": "徒步", "穿越": "徒步", "徒步穿越": "徒步",
    "溯溪": "溯溪", "玩水": "溯溪", "踩水": "溯溪", "溪谷": "溯溪",
    "滑雪": "滑雪", "雪": "滑雪",
    "带娃": "带娃", "亲子": "带娃", "孩子": "带娃", "小孩": "带娃", "小朋友": "带娃",
    "省力": "省力", "轻松": "省力", "不累": "省力", "懒": "省力", "轻松点": "省力",
    "老": "省力", "老人": "省力", "爸妈": "省力", "长辈": "省力",
    "摄影": "摄影", "拍照": "摄影", "出片": "摄影", "机位": "摄影",
    "古村": "古村", "人文": "古村", "文化": "古村",
}

# 否定词：出现则剔除对应意图。「不想爬山」不该被判成徒步需求。
_NEGATORS = ("不想", "不爬", "不要", "不爱", "不喜欢", "别", "无需", "懒得")


def _load() -> dict:
    global _DB
    if _DB is None:
        _DB = refloader.load("geo_ambiguous.json")
        for canon, rec in ((_DB.get("multi_candidate") or {}).items()):
            _ALIAS[canon] = canon
            for a in rec.get("aliases") or []:
                _ALIAS[a] = canon
            # ⚠️ correction 的键【绝不能】进 _ALIAS。
            # correction 的键是「用户说错的锚点」（临湘、幕布山），
            # 不是这个目的地的别名。早期版本把「临湘」注册成幕阜山别名，
            # 导致 geo_lookup 用「临湘」当索引键写歧义记录，
            # 把临湘真实的县级归属覆写掉了——临湘从此查不到。
            # correction 只在 correction_for() 里按原句做匹配，不参与归一。
    return _DB


# ── 省份/市县坐标表：用于距离粗算 ───────────────────────────────
# 只收常用出发地，避免为了一个距离项引入几百个坐标。
# 值均为城市中心近似坐标，仅用于判断「差 20km 还是差 800km」。
_ORIGIN_COORDS: dict[str, tuple[float, float]] = {
    "岳阳": (29.36, 113.13), "岳阳楼区": (29.36, 113.13), "长沙": (28.23, 112.94),
    "武汉": (30.59, 114.31), "南昌": (28.68, 115.86), "咸宁": (29.84, 114.32),
    "通山": (29.60, 114.52), "通城": (29.25, 113.80), "平江": (28.80, 113.88),
    "临湘": (29.48, 113.30), "修水": (29.03, 114.55), "武宁": (29.58, 115.08),
    "九江": (29.71, 116.00), "安庆": (30.51, 117.05), "潜山": (30.63, 116.58),
    "衡阳": (26.89, 112.57), "佛山": (23.02, 113.12), "广州": (23.13, 113.26),
    "深圳": (22.54, 114.06), "上海": (31.23, 121.47), "北京": (39.90, 116.41),
    "海口": (20.04, 110.32), "五指山市": (18.78, 109.62), "邯郸": (36.63, 114.54),
    "梅州": (24.30, 116.12), "平远": (24.57, 115.89),
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """大圆距离（km）。"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _origin_coord(origin: str | None) -> tuple[float, float] | None:
    """从出发地文本里找坐标。支持「岳阳」「湖南岳阳」「岳阳楼区」。"""
    if not origin:
        return None
    o = str(origin).strip()
    if o in _ORIGIN_COORDS:
        return _ORIGIN_COORDS[o]
    # 长名优先：「岳阳楼区」要先于「岳阳」被匹配，否则可能匹配错
    for name in sorted(_ORIGIN_COORDS, key=len, reverse=True):
        if name in o:
            return _ORIGIN_COORDS[name]
    return None


def normalize(name: str) -> str | None:
    """把「幕布山」「临湘那边的幕布山」「幕阜山风景区」归一到「幕阜山」。

    注意子串匹配：用户几乎不会只报一个光秃秃的地名，而是
    「临湘那边的幕布山」「想去五指山避暑」这种夹在句子里的说法。
    只做全等匹配会漏掉这些——而这恰恰是最常见的输入形态。
    按长度倒序扫，保证「幕阜山」优先于「幕阜」。
    """
    _load()
    n = str(name or "").strip()
    if not n:
        return None
    if n in _ALIAS:
        return _ALIAS[n]
    # 允许带通名后缀：「幕阜山风景区」「幕阜山脉」
    for suf in ("风景区", "风景名胜区", "景区", "山脉", "旅游区", "国家森林公园", "森林公园", "山"):
        if n.endswith(suf) and len(n) - len(suf) >= 2:
            base = n[: -len(suf)]
            if base in _ALIAS:
                return _ALIAS[base]
    # 子串匹配：长别名优先
    for alias in sorted(_ALIAS, key=len, reverse=True):
        if len(alias) >= 2 and alias in n:
            return _ALIAS[alias]
    return None


def detect_intents(text: str) -> list[str]:
    """从用户原话里抽取意图。处理否定式，不做过度推断。"""
    if not text:
        return []
    raw = str(text)
    found: list[str] = []
    for phrase, canon in INTENT_SYNONYMS.items():
        if phrase in raw:
            # 否定检测：看短语前 4 个字内是否有否定词
            i = raw.find(phrase)
            window = raw[max(0, i - 4):i]
            if any(neg in window for neg in _NEGATORS):
                continue
            if canon not in found:
                found.append(canon)
    return found


def candidates(name: str) -> list[dict]:
    """返回该名字的全部候选实体。空列表表示不属于本表管辖。"""
    _load()
    canon = normalize(name)
    if not canon:
        return []
    rec = (_DB.get("multi_candidate") or {}).get(canon)
    if not rec:
        return []
    out = []
    for c in rec.get("candidates") or []:
        item = dict(c)
        item["canonical"] = canon
        item["ambiguity_type"] = rec.get("ambiguity_type", "")
        item["scale"] = rec.get("scale", "")
        out.append(item)
    return out


def correction_for(name: str) -> list[dict]:
    """检查用户输入里是否含已知的锚点口误/错别字。"""
    _load()
    canon = normalize(name)
    if not canon:
        return []
    rec = (_DB.get("multi_candidate") or {}).get(canon) or {}
    raw = str(name or "")
    hits = []
    for wrong, fix in (rec.get("correction") or {}).items():
        if wrong in raw:
            hits.append({"trigger": wrong, **{k: v for k, v in fix.items()}})
    return hits


def _import_sibling(mod_name: str):
    """稳定导入同目录模块。

    直接 `import geo_lookup` 只在脚本目录下运行有效；被当作包导入时
    （例如测试用 sys.path.insert 后 import）会 ImportError。
    之前的 except 把它吞成 return None，于是区外锚点功能【静默失效】——
    测试跑起来一片绿，实际功能却是坏的。这类"静默降级"必须显式兜底：
    按绝对路径加载模块，而不是放弃。
    """
    import importlib.util
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      f"{mod_name}.py")
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location(mod_name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _anchor_in_geo_admin(text: str) -> dict | None:
    """检查用户原话里是否提到了一个真实行政区，但该区不在候选里。

    走 geo_lookup 权威索引，不靠关键词猜——「临湘」是县级市，
    能在 3001 个县级索引里精确命中，不需要模糊匹配。
    """
    gl = _import_sibling("geo_lookup")
    if gl is None:
        return None
    gl._build_index()
    best = None
    for token in _extract_place_tokens(text):
        hit = gl._INDEX.get(token)
        if hit and hit.get("level") in ("province", "city", "county"):
            # 排除候选自身已覆盖的归属
            best = {"token": token, "level": hit.get("level"),
                    "province": hit.get("province", ""),
                    "city": hit.get("city", ""), "name": hit.get("name", "")}
            break
    return best


# 候选区之外的常见锚点词（用户可能提到附近县市）
_ANCHOR_WORDS = ("临湘", "岳阳市", "汨罗", "平江", "通山", "通城", "咸宁",
                 "黄石", "武宁", "修水", "九江", "南江", "黄沙铺", "塘湖")


def _extract_place_tokens(text: str) -> list[str]:
    """从原话里抽取可能是地名的片段，长词优先。"""
    out = []
    for w in _ANCHOR_WORDS:
        if w in text:
            out.append(w)
    out.sort(key=len, reverse=True)
    return out


def _loc_text(c: dict) -> str:
    parts = [c.get("province", ""), c.get("city", ""), c.get("county", ""), c.get("town", "")]
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return " · ".join(out)


def _loc_short(c: dict) -> str:
    """短标签：市+县，够用户认出「哪一个」。"""
    city = c.get("city", "")
    county = c.get("county", "")
    if city and county and city != county:
        return f"{city}{county}"
    return county or city or c.get("province", "") or "—"


def score(
    name: str,
    user_text: str = "",
    origin: str | None = None,
) -> dict:
    """
    对候选打分排序。

    权重设计（刻意让意图压过距离）
    --------------------------------
      意图匹配  ×3.0   ——用户明说了要什么，这是最强的信号
      距离      ×1.0   ——只决定「顺路不顺路」，不足以推翻诉求差异
      规模成熟度 ×0.5   ——设施完备度做微调，不主导
    距离权重刻意压低：候选坐标是示意坐标，精度不足以支撑精细排序。
    一个 3 小时 vs 5 小时的差别有意义，一个 120km vs 180km 的差别没有。
    """
    cands = candidates(name)
    if not cands:
        return {"canonical": None, "ambiguous": False, "candidates": [],
                "intents": [], "recommended": None, "locked": None,
                "corrections": [], "default_hint": "",
                "common_error": "", "ambiguity_type": "", "scale": "",
                "unmatched_anchor": None}

    intents = detect_intents(user_text)
    oc = _origin_coord(origin)

    # ── 锚点锁定：用户已说了县市名，就不要再问了 ──────────────────
    # 「去临湘那边的幕阜山」——用户已经给了锚点，此时再问「你想去哪」是蠢的。
    # 锚点优先于意图：用户明确指定的地点，不能被我的启发式覆盖。
    locked_id = None
    if user_text:
        for c in cands:
            for token in (c.get("county", ""), c.get("town", ""), c.get("city", "")):
                if token and len(token) >= 2 and token in str(user_text):
                    locked_id = c["id"]
                    break
            if locked_id:
                break

    # ── 锚点在歧义区之外：必须显式提示，绝不静默忽略 ──────────────
    # 用户说「临湘那边的幕布山」，但临湘【不在任何一个候选里】——
    # 天岳幕阜山在平江，临湘是隔壁的县级市。
    # 这种情况最危险：若静默忽略锚点、只按意图推荐，用户会觉得系统没听懂他，
    # 可能被推荐到九宫山；而他明明说的是岳阳边上。这属于「假装听懂」。
    # 所以要把「你说的锚点不在候选里，但最接近的是X」明说出来。
    unmatched_anchor = None
    if user_text and not locked_id:
        from_geo = _anchor_in_geo_admin(str(user_text))
        if from_geo:
            unmatched_anchor = from_geo

    scored = []
    for c in cands:
        fit = c.get("intent_fit") or {}
        if intents and fit:
            vals = [fit.get(i, 0.0) for i in intents]
            intent_score = max(vals) * 3.0 if vals else 0.0
            matched = [i for i in intents if fit.get(i, 0.0) >= 0.7]
            weak = [i for i in intents if 0 < fit.get(i, 0.0) < 0.7]
        elif intents and not fit:
            # 该候选没有这项意图的打分 → 视为不匹配，不是不存在
            intent_score, matched, weak = 0.0, [], list(intents)
        else:
            # 用户没说意图：按「设施成熟度」的中性先验，不假装知道用户要什么
            intent_score, matched, weak = 0.6, [], []

        dist = None
        dist_score = 0.0
        if oc and c.get("lat") and c.get("lon"):
            dist = _haversine(oc[0], oc[1], c["lat"], c["lon"])
            # 距离分：50km 内满分，800km 归零（软性，不惩罚到负分）
            dist_score = max(0.0, 1.0 - (dist - 50) / 750.0)

        maturity = 0.7 if c.get("status") else 0.5
        total = intent_score + dist_score * 1.0 + maturity * 0.5

        scored.append({
            **c,
            "_score": round(total, 3),
            "_intent_score": round(intent_score, 3),
            "_dist_score": round(dist_score, 3),
            "_dist_km": round(dist) if dist is not None else None,
            "_matched_intents": matched,
            "_weak_intents": weak,
            "_loc_short": _loc_short(c),
            "_loc_full": _loc_text(c),
        })

    # 锚点命中 → 该候选置顶
    if locked_id:
        for c in scored:
            if c["id"] == locked_id:
                c["_locked"] = True
                c["_score"] += 100.0

    # ⚠️ sort 必须在 if 块【之外】。曾被误缩进到 if locked_id 里面，
    # 导致没有锚点时列表保持原始顺序（JSON 里的书写顺序）而非按分数排序——
    # 于是"意图榜首"取到的是数据里第一个候选，而不是得分最高的那个。
    # 症状极具迷惑性：所有候选分数都算对了，结论却是错的。
    # 教训：排序语句的缩进错误不会抛异常，只会静默改变结论。
    scored.sort(key=lambda x: -x["_score"])

    top = scored[0]

    # 只有当意图分能拉开实质差距时才敢「推荐」；否则交给用户选。
    # 阈值 0.9：intent_fit 每项满分 3.0，0.9 ≈ 该意图上 0.3 的差距。
    # 定这个值是因为黄龙山（祈福 1.0）与天岳幕阜山（祈福 0.65）只差 0.35——
    # 一边是佛教黄龙宗祖庭，一边是道教二十五洞天，宗派不同，是实质差异，
    # 必须能分开。再低的阈值（比如 0.3）会把「近 35km」误当成决定性优势。
    strong = bool(top["_matched_intents"])
    second = scored[1] if len(scored) > 1 else None
    clear_winner = bool(
        strong and second and
        (top["_intent_score"] - second["_intent_score"]) >= 0.9
    )

    # ── 距离决胜：意图分拉不开时用_distance_，但必须双方都明确匹配该意图 ──
    # 「看日出」平江 2.85(117km) vs 九宫山 2.40(150km)：两者都能看日出，
    # 意图上分不出胜负。此时距离才是真正的决策依据——它决定当天回不回得来。
    #
    # 为什么用 _score（含距离的联合分）而不是单独比距离：
    # 单独比距离会犯「近的意图差、远的意图好」的错。黄袍山离岳阳直线仅 75km
    # （比平江近 42km），但它开发度低、没有索道、日出只是 0.5 分——
    # 纯比距离会把它推上去，联合分则让意图差异压过那42km。
    #
    # 为什么必须双方都明确匹配：
    # 黄龙山看日出仅 0.5 分，它离得近（107km）是假优势——它以拜佛见长。
    # 把地理距离当成产品匹配度是典型伪精确，所以弱匹配候选根本不参与决胜。
    pooled = None
    rival = None
    if (not locked_id) and (not clear_winner) and second and \
            top["_matched_intents"] and second["_matched_intents"] and \
            top["_dist_km"] is not None and second["_dist_km"] is not None:
        # 差距 <0.1 就承认分不出来，不包装成推荐——那是假精度
        if (top["_score"] - second["_score"]) >= 0.1:
            pooled = top
            rival = second

    if locked_id:
        recommended = locked_id
        reason = f"你点名了{top.get('county') or top.get('city')}，已锁定这一支"
    elif clear_winner:
        recommended = top["id"]
        reason = f"「{top['name']}」在 {'、'.join(top['_matched_intents'])} 上最匹配"
    elif pooled:
        # pooled 现在恒等于 top（联合分已含距离），rival 是紧随其后的那个。
        # 措辞要同时给出"意图差不多"和"距离更近"两个事实，
        # 绝不能说成"这个更好"——那是在替用户下结论。
        recommended = pooled["id"]
        alt = rival["_loc_short"] if rival else ""
        gap = abs(rival["_dist_km"] - pooled["_dist_km"]) if rival else 0
        reason = (
            f"这几个地方都能满足「{'、'.join(pooled['_matched_intents'])}」，"
            f"其中{pooled['_loc_short']}离你更近（直线约 {pooled['_dist_km']}km"
            + (f"，比{alt}那支近 {gap}km" if alt and gap else "")
            + "），当天来回更稳")
    else:
        recommended = None
        reason = ""

    canon = normalize(name)
    rec_db = (_DB.get("multi_candidate") or {}).get(canon) or {}
    return {
        "canonical": canon,
        "ambiguous": True,
        "ambiguity_type": top.get("ambiguity_type", ""),
        "scale": top.get("scale", ""),
        "intents": intents,
        "candidates": scored,
        "recommended": recommended,
        "locked": locked_id,
        "locked_name": top["name"] if locked_id else "",
        "unmatched_anchor": unmatched_anchor,
        "recommend_reason": reason,
        "default_hint": rec_db.get("default_hint", ""),
        "corrections": correction_for(name),
        "common_error": rec_db.get("common_error", ""),
    }


def clarify_card(res: dict) -> str:
    """
    渲染「先查后问」澄清卡。

    结构刻意如此：
      1. 先说这事有歧义（让用户理解为什么要问）
      2. 纠偏（如果有口误，先纠，纠完再选）
      3. 候选对比表（带差异维度，让问题变得可回答）
      4. 一个能被回答的问题
    """
    if not res.get("ambiguous"):
        return ""

    L: list[str] = []
    canon = res["canonical"]
    L.append(f"## 「{canon}」有多个去处，需要你定一下")
    L.append("")

    # 1. 为什么问
    if res.get("scale"):
        L.append(f"{res['scale']}。你说「{canon}」时，指的可能是其中任意一支，"
                 f"而它们看什么、怎么去、从哪出发完全不同。")
        L.append("")

    # 2. 纠偏优先
    for c in res.get("corrections") or []:
        L.append(f"> **先纠个错**：你提到的「{c['trigger']}」——"
                 f"{c.get('explain', '')}")
        if c.get("right"):
            L.append(f"> 实际是：**{c['right']}**。")
        L.append("")

    # 3. 候选对比
    rec_id = res.get("recommended")
    # 锚点落在候选之外：必须先讲清楚，不能埋在后面
    ua = res.get("unmatched_anchor")
    if ua:
        near = res["candidates"][0] if res["candidates"] else None
        L.append(f"> ⚠️ **你说的「{ua['token']}」不在下面任何一个选项里**"
                 f"（它在{ua.get('province') or ''}{ua.get('city') or ''}）。"
                 f"最接近的是**{near['name'] if near else '—'}**"
                 f"（{near['_loc_full'] if near else ''}）——"
                 f"如果你要的其实是它，就按这个走；如果不是，告诉我具体地方。")
        L.append("")
    L.append("### 先把这几个选项摆给你看")
    L.append("")
    for c in res["candidates"]:
        mark = " ⭐ 推荐" if c["id"] == rec_id else ""
        L.append(f"**{c['name']}**{mark}")
        L.append(f"- 位置：{c['_loc_full']}")
        alt = " / ".join(c.get("altitude", "").split(" / ")[:2])
        if alt:
            L.append(f"- 海拔：{alt}")
        if c.get("status"):
            L.append(f"- 定位：{c['status']}")
        if c.get("best_points"):
            pts = "；".join(f"{k}看{kk}" for k, kk in c["best_points"].items())
            L.append(f"- 看点：{pts}")
        if c.get("distinct"):
            L.append(f"- 特色：{c['distinct']}")
        if c["_dist_km"] is not None:
            L.append(f"- 距出发地：直线约 {c['_dist_km']} km（实际车程通常更远）")
        hooks = c.get("decision_hooks") or []
        for h in hooks[:2]:
            L.append(f"- ⚠️ {h}")
        L.append("")

    # 4. 问题
    L.append("### 你想要的是哪一种")
    L.append("")
    if res.get("recommend_reason"):
        L.append(f"按你说的「{'、'.join(res['intents'])}」，"
                 f"{res['recommend_reason']}。但还是给你全部选项，你否决也行。")
        L.append("")
    if res.get("intents"):
        L.append(f"- 你说的「{'、'.join(res['intents'])}」，我按这个排了序，"
                 f"上表 ⭐ 就是最匹配的")
    else:
        L.append("- 你没说要玩什么，所以我没法替你选——说个诉求（看日出／避暑／"
                 "拜佛／野线徒步／带娃）我就能直接排序")
    L.append("")
    L.append("**或者直接告诉我县市名**，比如「平江那边」「通山那边」，我就锁定那一支，"
             "不再问第二遍。")
    return "\n".join(L)


def probe(name: str, user_text: str = "", origin: str | None = None) -> dict:
    """一体入口：先纠偏，再给候选，再给建议。"""
    res = score(name, user_text, origin)
    return {
        **res,
        "card": clarify_card(res),
    }


if __name__ == "__main__":
    print("=" * 72)
    print("场景 A：只说山名，无诉求，无出发地  →  不该推荐，只能问")
    print("=" * 72)
    r = probe("幕布山")
    print(f"归一化：幕布山 → {r['canonical']}")
    print(f"意图：{r['intents']}  推荐：{r['recommended']}")
    print(r["card"])

    print()
    print("=" * 72)
    print("场景 B：用户想看日出，从岳阳出发  →  该推荐，且给出理由")
    print("=" * 72)
    r = probe("幕阜山", "想找个山看日出", "岳阳")
    print(f"意图：{r['intents']}  推荐：{r['recommended']}")
    print(f"理由：{r['recommend_reason']}")
    print()
    for c in r["candidates"]:
        mm = "⭐" if c["id"] == r["recommended"] else "  "
        print(f"{mm} {c['name'][:18]:<20}{c['_loc_short']:<14}"
              f"意图分={c['_intent_score']:<6}距离={c['_dist_km']}km")
    print()
    print(f"纠偏条目：{[c['trigger'] for c in r['corrections']]}")

    print()
    print("=" * 72)
    print("场景 C：口误「临湘那边的幕布山」  →  必须当场纠偏")
    print("=" * 72)
    r = probe("临湘那边的幕布山看日出", "临湘那边的幕布山看日出", "岳阳")
    for c in r["corrections"]:
        print(f"触发：{c['trigger']} → {c.get('right')}")
        print(f"说明：{c.get('explain')}")

    print()
    print("=" * 72)
    print("场景 D：南岳  →  历史旧称与今称冲突，最易指错")
    print("=" * 72)
    r = probe("南岳")
    print(f"归一化：{r['canonical']}  候选数：{len(r['candidates'])}")
    print(f"默认提示：{r['default_hint']}")