#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
境内地名查询器（零依赖）—— worldstip-travel-planner

存在的理由
----------
v0.2.0 的 is_domestic() 靠两份手写白名单（_CN_CITIES 等，约 180 项）判定
国内外。中国实际有 34 个省级 / 366 个地级 / 3006 个县级行政区，手写名单
必然漏判——「芒市」「霍尔果斯」「婺源」「阿尔山」都不在名单里，会被误判
为出境 → 国内用户凭空看到签证门禁卡。
这是数据不全，不是逻辑错误，只能靠接权威索引解决。

判定优先级（从硬到软）
--------------------
1. 命中 geo_admin.json 的省/市/县任一级 → 境内（权威，硬事实）
2. 命中 destination_links.json 的 249 个景点 → 境内（已知真实景点名）
3. 命中 scenic_alias 人工补充表（如「南岳衡山」这类非行政区名）→ 境内
4. 剥通名后缀后重试（黄山风景区→黄山）
5. 都不中 → 非境内（保守），由上层走 unknown 灰灯「待查」，绝不编造国别

为什么第5 步宁可判「非境内」
---------------------------
排除法（不在出境名单就算境内）会把拼错/生僻的境外地名判成境内，
导致出境用户漏掉签证与保险门禁 —— 那是硬安全风险，比多弹一个
待查灯严重得多。宁可多问一句，不可漏拦一道门。

性能
----
索引在首次查询时构建一次并缓存（3006 县 → dict查找约 0.01s），
之后每次查询是 O(1) 哈希命中。不依赖任何第三方包。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import refloader

REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")

# 港澳台属中国境内，一律使用「中国××」规范表述
DOMESTIC_REGIONS = {
    "中国香港", "中国澳门", "中国台湾",
    "香港", "澳门", "台湾", "港澳台", "港台",
    "Hong Kong", "Macao", "Macau", "Taiwan",
}

# 景区/地形通名：不是行政区，但确定在中国境内。
# 原则：只收「全国唯一知名、归属无歧义」的；拿不准的一律不进这张表，
# 宁可落到 unknown 待查，也不要把某个境外景点误当境内。
SCENIC_ALIAS: dict[str, str] = {
    # 三大山岳
    "南岳衡山": "湖南省衡阳市南岳区", "衡山": "湖南省衡阳市",
    "黄山": "安徽省黄山市", "华山": "陕西省渭南市华阴市",
    "泰山": "山东省泰安市", "峨眉山": "四川省乐山市峨眉山市",
    "五台山": "山西省忻州市五台县", "九华山": "安徽省池州市青阳县",
    "普陀山": "浙江省舟山市普陀区", "武当山": "湖北省十堰市丹江口市",
    "武夷山": "福建省南平市武夷山市", "雁荡山": "浙江省温州市乐清市",
    "四姑娘山": "四川省阿坝州小金县", "梅里雪山": "云南省迪庆州德钦县",
    "玉龙雪山": "云南省丽江市玉龙县", "腾冲": "云南省保山市腾冲市",
    "天柱山": "安徽省安庆市潜山市", "苍山": "云南省大理州",
    # 水体/瀑布
    "青海湖": "青海省海北藏族自治州刚察县", "喀纳斯": "新疆维吾尔自治区阿勒泰地区布尔津县",
    "赛里木湖": "新疆维吾尔自治区博尔塔拉蒙古自治州",
    "九寨沟": "四川省阿坝藏族羌族自治州九寨沟县", "黄果树": "贵州省安顺市镇宁县",
    "壶口瀑布": "山西省临汾市吉县", "漓江": "广西壮族自治区桂林市",
    "洱海": "云南省大理白族自治州大理市", "洞庭湖": "湖南省",
    "鄱阳湖": "江西省", "太湖": "江苏省", "西湖": "浙江省杭州市",
    # 文化地标
    "故宫": "北京市", "天坛": "北京市", "颐和园": "北京市",
    "布达拉宫": "西藏自治区拉萨市", "莫高窟": "甘肃省敦煌市",
    "都江堰": "四川省成都市都江堰市", "青城山": "四川省成都市都江堰市",
    "长城": "北京市", "秦岭": "陕西省", "天坛公园": "北京市",
    # 古村/古城
    "平遥古城": "山西省晋中市平遥县", "丽江古城": "云南省丽江市",
    "大理古城": "云南省大理白族自治州大理市", "凤凰古城": "湖南省湘西州凤凰县",
    "西塘": "浙江省嘉兴市嘉善县", "乌镇": "浙江省嘉兴市桐乡市",
    "婺源": "江西省上饶市婺源县", "宏村": "安徽省黄山市黟县",
    "西递": "安徽省黄山市黟县", "鼓浪屿": "福建省厦门市思明区",
    # 高原/特殊地形
    "稻城亚丁": "四川省甘孜州稻城县", "香格里拉": "云南省迪庆州",
    "泸沽湖": "四川省凉山州盐源县", "丰宁坝上": "河北省承德市丰宁满族自治县",
    "涠洲岛": "广西壮族自治区北海市涠洲岛", "东山岛": "福建省漳州市东山县",
    "舟山": "浙江省舟山市", "嵊泗": "浙江省舟山市嵊泗县",
    "呼伦贝尔": "内蒙古自治区呼伦贝尔市", "阿尔山": "内蒙古自治区兴安盟阿尔山市",
    "呼伦贝尔草原": "内蒙古自治区呼伦贝尔市", "伊犁": "新疆维吾尔自治区伊犁哈萨克自治州",
    "吐鲁番": "新疆维吾尔自治区吐鲁番市", "喀什": "新疆维吾尔自治区喀什地区",
    "博尔塔拉": "新疆维吾尔自治区博尔塔拉蒙古自治州",
    "可可西里": "青海省玉树藏族自治州", "纳木错": "西藏自治区拉萨市当雄县",
    "羊卓雍措": "西藏自治区山南市浪卡子县", "纳帕海": "云南省迪庆州",
    # 主题乐园/综合体（确定境内）
    # 注意：连锁品牌（方特/宋城/欢乐谷/海昌/融创）已迁至 synthetic_sites.json 的 brand 表，
    # 因为它们同名多园、不能挂单一省份。旧表里「方特→江西省」这类归属是错的，已移除。
    "北京环球影城": "北京市", "迪士尼": "上海市", "上海迪士尼": "上海市",
    "中华恐龙园": "江苏省常州市",
    # 幕阜山脉各支脉主峰名（2026-10-12 核验）
# 这些名字都不在任何行政区里，只能挂景区索引——否则「九宫山」会落unknown，
# 而它是湖北通山的国家4A/国家级风景名胜区。落 unknown 的后果是：
# 国内用户可能被误判为出境，凭空弹出签证门禁卡。所以景区名必须收录。
    "九宫山": "湖北省咸宁市通山县",
    "大幕山": "湖北省咸宁市通山县",
    "黄袍山": "湖北省咸宁市通城县",
    "太阳山": "湖北省咸宁市通山县",
    "黄龙山": "湖南省岳阳市平江县",
    "鹿角山": "湖北省咸宁市通城县",
    "老鸦尖": "江西省九江市武宁县",
    "一峰尖": "湖南省岳阳市平江县",
    # 五大名山/古南岳（南岳旧称指安徽天柱山，见 geo_ambiguous.json）
    "天柱山": "安徽省安庆市潜山市",
    "古南岳": "安徽省安庆市潜山市",
    # 洞庭/鄱阳周边
    "君山": "湖南省岳阳市君山区",
    "石牛寨": "湖南省岳阳市平江县",
    "天岳山": "湖南省岳阳市平江县",
    # 革命纪念地（多为 3 字，砍尾下限卡住，需显式收录）
    "西柏坡": "河北省石家庄市平山县", "韶山": "湖南省湘潭市韶山市",
    "井冈山": "江西省吉安市井冈山市", "延安": "陕西省延安市",
    "瑞金": "江西省赣州市瑞金市", "遵义": "贵州省遵义市",
    "会宁": "甘肃省白银市会宁县", "泸沟": "陕西省西安市临潼区",
    # 更多县级市/县（原白名单遗漏的真实地名）
    "芒市": "云南省德宏傣族景颇族自治州芒市", "瑞丽": "云南省德宏傣族景颇族自治州瑞丽市",
    "霍尔果斯": "新疆维吾尔自治区伊犁哈萨克自治州霍尔果斯市",
    "婺源": "江西省上饶市婺源县", "阿尔山": "内蒙古自治区兴安盟阿尔山市",
    "漠河": "黑龙江省大兴安岭地区漠河市", "腾冲": "云南省保山市腾冲市",
    "阳朔": "广西壮族自治区桂林市阳朔县", "涞水": "河北省保定市涞水县",
    "赤水": "贵州省遵义市赤水市", "兴凯": "黑龙江省鸡西市密山市",
    "延吉": "吉林省延边朝鲜族自治州延吉市", "珲春": "吉林省延边朝鲜族自治州珲春市",
    "满洲里": "内蒙古自治区呼伦贝尔市满洲里市", "东宁": "黑龙江省牡丹江市东宁市",
    # 江浙古镇（3 字，砍尾下限卡住）
    "横店": "浙江省金华市东阳市横店镇", "周庄": "江苏省苏州市昆山市周庄镇",
    "同里": "江苏省苏州市吴江区同里镇", "乌镇": "浙江省嘉兴市桐乡市乌镇镇",
    "西塘": "浙江省嘉兴市嘉善县西塘镇", "南浔": "浙江省湖州市南浔区",
    "甪直": "江苏省苏州市吴江区甪直镇", "朱家角": "上海市青浦区朱家角镇",
    "芦笙": "贵州省黔东南州榕江县", "肇兴": "贵州省黔东南州黎平县",
}

# 省级大区兜底：当用户只说了大区（如「华南」「东北」），不构成入境判断依据，
# 但可避免把大区名误判成境外城市。
REGION_WORDS = {"华北", "东北", "华东", "华中", "华南", "西南", "西北", "西北地区"}

_INDEX: dict[str, Any] = {}
_ATTR_PREFIX: dict[str, str] = {}
_LOADED = False


def _load(name: str) -> dict:
    return refloader.load(name)


def classify_synthetic(name: str) -> dict | None:
    """判定一个名字是否属于「人造景点」，并给出类型与处理建议。

    返回 None 表示不是人造景点（走常规地理判定）。
    返回字段：
      type: "single" 单一实体（可挂省市）
            "brand" 连锁品牌（必须先问用户哪一园，禁止给单一归属）
            "guide" 品类指南（非地点，是专题入口）
    """
    db = _load("synthetic_sites.json")
    n = str(name).strip()
    # 匹配顺序 brand → guide → single：
    # brand 必须最先查，否则像「海昌海洋公园」这类在 single 表里留了 redirect 别名的品牌名，
    # 会被当成有单一归属的实体，把「多园连锁」错挂成某一个省。
    for t in ("brand", "guide", "single"):
        tbl = db.get(t) or {}
        if n in tbl:
            rec = dict(tbl[n])
            if t == "single" and rec.get("redirect"):
                continue  # 只是别名占位，跳过
            rec["type"] = t
            rec["needs_disambiguation"] = bool(
                rec.get("needs_disambiguation") or t == "brand")
            if t == "brand":
                # 连锁品牌：province/city 一律留空 —— 强行归属会把用户带到错的园
                rec.setdefault("province", "")
                rec.setdefault("city", "")
            return rec
    # 「葛仙村度假区」这类全称命中 single 的简称
    for t in ("single",):
        for k, v in (db.get(t) or {}).items():
            if v.get("full_name") == n:
                r = dict(v)
                r["type"] = t
                r["matched_on"] = n
                return r
    return None


def _build_index() -> None:
    """构建查询索引（只构建一次）。"""
    global _LOADED
    if _LOADED:
        return
    idx: dict[str, dict] = {}
    geo = _load("geo_admin.json")
    for level in ("province", "city", "county"):
        for r in geo.get(level) or []:
            for k in r.get("keys") or []:
                # 已有更长/更具体的记录则不覆盖（县级优先于市）
                prev = idx.get(k)
                rank = {"province": 2, "city": 1, "county": 0}
                if prev is None or rank.get(level, 9) < rank.get(prev["level"], 9):
                    idx[k] = {"level": level, "code": r.get("code", ""), "name": r.get("name", ""),
                              "province": r.get("province", "") or (r.get("name") if level == "province" else ""),
                              "city": r.get("city", "") or (r.get("name") if level == "city" else ""),
                              "source": "geo_admin"}
    # 景点名（249 个）也纳入
    links = _load("destination_links.json")
    for name in (links.get("destinations") or {}):
        if name and name not in idx:
            idx[name] = {"level": "attraction", "code": "", "name": name,
                         "province": "", "city": "", "source": "destination_links"}
    # 人造景点 v0.2.1：
    #  · single（单一实体）→ 正常纳入索引并带上真实省市，供票务/美食/气候正确挂载
    #  · brand（连锁品牌）→ 只登记为境内事实，province/city 强制留空。
    #    绝不能把「方特」挂到某一个省——同名园区跨省分布，挂了会让用户拿错园的票。
    #  · guide（品类指南）→ 登记为 guide，is_domestic 视为境内但不给归属。
    #
    # 覆盖规则：只覆盖「空壳兜底记录」（attraction 且无省市、无代码）。
    # 真实地理实体（geo_admin 里的县/市、SCENIC_ALIAS 里的确属景点）一律不动——
    # 例如「黄山」既是山也是景区，绝不能被合成景点逻辑夺走归属。
    def _is_placeholder(rec: dict | None) -> bool:
        return bool(rec) and rec.get("level") == "attraction" and not rec.get("province") \
            and not rec.get("city") and not rec.get("code")
    syn = _load("synthetic_sites.json")
    for name, rec in (syn.get("single") or {}).items():
        if rec.get("redirect"):
            continue  # 别名占位，不是独立实体
        if name in idx and not _is_placeholder(idx[name]):
            continue
        idx[name] = {"level": "synthetic", "code": "", "name": name,
                     "province": rec.get("province", ""),
                     "city": rec.get("city", ""),
                     "county": rec.get("county", ""),
                     "source": "synthetic_single", "synthetic_type": "single"}
    for name, rec in (syn.get("brand") or {}).items():
        if name in idx and not _is_placeholder(idx[name]):
            continue
        idx[name] = {"level": "synthetic_brand", "code": "", "name": name,
                     "province": "", "city": "", "source": "synthetic_brand",
                     "synthetic_type": "brand", "needs_disambiguation": True}
    for name in (syn.get("guide") or {}):
        if name in idx and not _is_placeholder(idx[name]):
            continue
        idx[name] = {"level": "guide", "code": "", "name": name,
                     "province": "", "city": "", "source": "synthetic_guide",
                     "synthetic_type": "guide"}
    for k, v in SCENIC_ALIAS.items():
        if k not in idx:
            idx[k] = {"level": "scenic", "code": "", "name": k,
                      "province": "", "city": v, "source": "scenic_alias"}
    _INDEX.clear()
    _INDEX.update(idx)
    # 景点/景区名 → 其 2..len-1 长度前缀，供「茶卡」→「茶卡盐湖」这类反查。
    # 只为非行政区记录建，且不建单字前缀（单字前缀歧义太大）。
    ap: dict[str, str] = {}
    for k, v in idx.items():
        if v.get("level") in ("attraction", "scenic"):
            for L in range(2, len(k)):
                p = k[:L]
                ap.setdefault(p, k)   # 最短前缀优先，保证结果确定
    _ATTR_PREFIX.clear()
    _ATTR_PREFIX.update(ap)
    _LOADED = True


# 剥通名后缀（与 build_geo_admin 的行政区后缀不同，这里是景区/地形通名）
_NOISE = ("风景区", "风景名胜区", "景区", "旅游区", "保护区", "古城", "老街", "古镇",
          "森林公园", "国家公园", "湿地公园", "公园", "山", "湖", "岛", "峰", "岭",
          "峡谷", "草原", "沙漠", "冰川", "雪山", "寺", "庙", "宫", "阁", "塔")


def _maybe_disambiguate(name: str) -> dict | None:
    """跨省同名歧义前置检查。命中则把一条「多候选」记录注入索引。

    返回注入的记录，未命中返回 None。

    注入而非旁路返回的理由：lookup() 的所有出口都是「一条归属记录」，
    索引注入能让歧义信息跟着记录走，上层只需读 needs_disambiguation 字段，
    不必在每个分支重复写判断。漏一处判断的代价是静默给错归属。
    """
    _build_index()
    # 同目录模块必须按绝对路径加载。裸 `import geo_disambiguate` 只在本目录
    # 下直接运行时有效；被当包导入时抛 ImportError，被 except 吞掉后
    # 消歧功能【静默失效】——测试全绿而功能是坏的。故显式按路径加载。
    gd = None
    try:
        import importlib.util
        if "geo_disambiguate" in sys.modules:
            gd = sys.modules["geo_disambiguate"]
        else:
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "geo_disambiguate.py")
            _spec = importlib.util.spec_from_file_location("geo_disambiguate", _p)
            gd = importlib.util.module_from_spec(_spec)
            sys.modules["geo_disambiguate"] = gd
            _spec.loader.exec_module(gd)
    except Exception:
        gd = None
    if gd is None:
        return None

    canon = gd.normalize(name)
    if not canon:
        return None
    cands = gd.candidates(canon)
    if not cands:
        return None

    # 只有 1 个候选 → 不是歧义，正常给归属（但仍带标记供上层选用澄清话术）
    if len(cands) == 1:
        c = cands[0]
        rec = {"level": "attraction", "code": "", "name": canon,
               "province": c.get("province", ""), "city": c.get("city", ""),
               "county": c.get("county", ""), "source": "geo_ambiguous_single",
               "needs_disambiguation": False, "candidate_count": 1}
        _INDEX[canon] = rec
        for alias in _gd_aliases(gd, canon):
            _INDEX[alias] = rec
        return rec

    # 多个候选 → 【不给单一归属】，标记 needs_disambiguation
    rec = {"level": "ambiguous", "code": "", "name": canon,
           "province": "", "city": "", "county": "",
           "source": "geo_ambiguous", "needs_disambiguation": True,
           "candidate_count": len(cands),
           "ambiguity_type": cands[0].get("ambiguity_type", ""),
           "scale": cands[0].get("scale", ""),
           "candidates": [
               {"id": c.get("id", ""), "name": c.get("name", ""),
                "province": c.get("province", ""), "city": c.get("city", ""),
                "county": c.get("county", ""), "town": c.get("town", ""),
                "altitude": c.get("altitude", ""), "tags": c.get("tags", [])}
               for c in cands
           ]}
    _INDEX[canon] = rec
    # ⚠️ 只覆盖 canonical 与【已登记别名】，绝不写入用户原始输入。
    # 曾把 _INDEX[name] = rec 也写上，而 name 可能是整句
    # 「临湘那边的幕布山看日出」——这会把全局索引污染：
    #  1) 写入一条以整句为键的垃圾记录；
    #  2) 更糟的是 lookup 里 `for wrong in correction: _ALIAS.setdefault(wrong, canon)`
    #     把「临湘」也注册成了幕阜山别名，于是 _INDEX["临湘"]
    #     被这条歧义记录【覆写】，临湘这条县级记录被销毁。
    # 后果：临湘从此查不到真实归属，「区外锚点」功能静默失效。
    # 教训：全局索引只能由受控词表写入，绝不能接受自由文本。
    for alias in _gd_aliases(gd, canon):
        _INDEX[alias] = rec
    return rec


def _gd_aliases(gd, canon: str) -> list[str]:
    """取出 canonical 对应的全部别名（含错写），供索引覆盖。"""
    try:
        db = gd._load()
        rec = (db.get("multi_candidate") or {}).get(canon) or {}
        return list(rec.get("aliases") or [])
    except Exception:
        return []


def lookup(name: str) -> dict | None:
    """查一个地名是否境内；命中返回归属信息，未命中返回 None。

    ⚠️ 跨省同名歧义前置检查（v0.3.0）
    ----------------------------------
    「幕阜山」这类名字，【单一归属是错的】——它是横跨湘鄂赣160 公里的山脉，
    指哪一个决定了完全不同的两趟旅行。所以本函数在返回单一归属【之前】
    必须先问 geo_disambiguate：这名字有多个候选吗？
      · 有多个候选 → 返回 needs_disambiguation=True + 候选清单，**不返回单一归属**
      · 只有一个候选 → 正常返回该候选的归属
    这很重要：上层拿到 needs_disambiguation 会走「先查后问」，
    拿到单一归属则会直接开始排程——对幕阜山来说那是静默给错答案。
    """
    _build_index()
    n = str(name or "").strip()
    if not n:
        return None
    _maybe_disambiguate(n)
    # 归一回落：「幕布山」「临湘那边的幕布山」→ 索引键是「幕阜山」。
    # 少了这一步，错别字和口误会全部 miss，退回 unknown 待查——
    # 而这两个写法在真实对话里极其常见。
    amb = _INDEX.get(n)
    if amb is not None:
        return amb
    try:
        import geo_disambiguate as gd
        canon = gd.normalize(n)
        if canon and canon != n:
            return _INDEX.get(canon)
    except Exception:
        pass
    # 归一回退（覆盖 import 失败的路径）
    _maybe_disambiguate(n)
    cand = _INDEX.get(n)
    if cand is not None:
        return cand
    if n in DOMESTIC_REGIONS:
        # 港澳台一律以「中国××」规范表述，绝不表述为独立国家/地区
        canon = None
        for pre in ("中国香港", "中国澳门", "中国台湾"):
            if n == pre or n in pre or pre in n:
                canon = pre
                break
        return {"level": "special", "name": canon or n, "province": canon or "",
                "city": "", "source": "domestic_regions"}
    if n in REGION_WORDS:
        return {"level": "region", "name": n, "province": "", "city": "", "source": "region_words"}

    hit = _INDEX.get(n)
    if hit:
        return hit

    # 分隔符切分："牡丹江·镜泊湖" → 牡丹江
    if "·" in n:
        for part in (p.strip() for p in n.split("·") if p.strip()):
            h = _INDEX.get(part)
            if h:
                return dict(h, matched_on=part)
    # 剥通名后缀："黄山风景区" → 黄山
    cur = n
    for _ in range(3):
        changed = False
        for suf in _NOISE:
            if cur.endswith(suf) and len(cur) - len(suf) >= 2:
                cur = cur[: -len(suf)]
                h = _INDEX.get(cur)
                if h:
                    return dict(h, matched_on=cur)
                changed = True
                break
        if not changed:
            break
    # 去行政后缀（"岳阳市"→"岳阳"）
    for suf in ("特别行政区", "自治区", "自治州", "自治县", "地区", "林区", "矿区", "新区", "省", "市", "县", "区"):
        if cur.endswith(suf) and len(cur) - len(suf) >= 2:
            h = _INDEX.get(cur[: -len(suf)])
            if h:
                return dict(h, matched_on=cur[: -len(suf)])

    # 复合景点名中间态截取："张家界天门山" 剥「山」得「张家界天门」（不命中），
    # 但「张家界」命中。
    #
    # ⚠️ 硬性安全约束：只对【4 字及以上】的输入做砍尾，且只砍 1 个字。
    # 踩过的坑：曾对任意长度砍尾到 2 字，导致
    #   「吉隆坡」(马来西亚) → 砍成「吉隆」 → 命中西藏吉隆县
    #   「多伦多」(加拿大)   → 砍成「多伦」 → 命中内蒙古多伦县
    # 这会把境外城市误判为境内，导致出境用户【漏掉签证与保险门禁】——
    # 那是硬安全风险。短名撞车在真实地名里极常见，砍尾必须有长度下限。
    if len(n) >= 4:
        # 逐步砍尾，但设硬性下限：砍完必须 ≥3 字。
        # 「张家界天门山」→剥「山」→「张家界天门」→砍到「张家界」命中（3字，安全）
        # 「吉隆坡」→只有3字→ 不足 4 字，根本不进本分支 → 不可能砍成「吉隆」
        # 「多伦多」→同理不受影响
        # 下限 3 字是安全线：2 字县级名（如吉隆/多伦/和平/中山）歧义太大，
        # 误判会直接导致出境用户漏掉签证门禁。
        for cut in range(1, max(0, len(n) - 3) + 1):
            cn = n[:-cut]
            if len(cn) < 3:
                break
            h = _INDEX.get(cn)
            if h and h.get("level") in ("province", "city", "county"):
                return dict(h, matched_on=cn)

    # 景点名前缀反查："茶卡" → 索引里的「茶卡盐湖」。
    # 只在景点/景别名这类【非行政区】记录上做前缀匹配，
    # 绝不对行政区做前缀匹配（「岳」能前缀命中「岳阳」会造成跨省误判）。
    # 用预计算的 _ATTR_PREFIX，避免每次查询扫全表。
    if len(n) >= 2:
        cand = _ATTR_PREFIX.get(n)
        if cand:
            return dict(_INDEX[cand], matched_on=n)

    return None


def is_domestic(name: str) -> bool:
    """保守判定：命中权威索引 → 境内。都不中 → False（走 unknown 待查）。"""
    return lookup(name) is not None


def resolve(name: str) -> dict | None:
    """带归属信息的判定，供上层决定挂哪些能力库（气候/票务/美食）。"""
    return lookup(name)


if __name__ == "__main__":
    _build_index()
    print(f"索引规模：{len(_INDEX)} 条")
    print()
    probes = ["岳阳", "岳阳市", "岳阳县", "佛山", "南岳", "南岳衡山", "黄山", "黄山风景区",
              "西湖", "婺源", "宏村", "芒市", "霍尔果斯", "三清山", "稻城亚丁", "九寨沟",
              "呼伦贝尔", "伊犁", "涠洲岛", "中国台湾", "台北", "香港", "台北市",
              "东京", "京都", "曼谷", "纽约", "巴黎", "首尔", "迪拜", "罗马", "伦敦",
              "新加坡", "巴厘岛", "吉隆坡", "奥克兰", "某不存在的地方",
              # 跨省同名歧义（v0.3.0）
              "幕阜山", "幕布山", "幕埠山", "天岳幕阜山", "临湘那边的幕布山",
              "九宫山", "大幕山", "五指山", "南岳"]
    print(f"{'输入':<18}{'境内?':<8}{'层级':<12}{'归属/歧义':<34}来源")
    print("-" * 96)
    for p in probes:
        r = lookup(p)
        if r:
            if r.get("needs_disambiguation"):
                cell = f"⚠️ {r['candidate_count']} 个候选，待消歧"
            else:
                loc = f"{r.get('province', '')} {r.get('city', '')}".strip() or "—"
                cell = loc[:32]
            print(f"{p:<18}{'✅是':<8}{r['level']:<12}{cell:<34}{r['source']}")
        else:
            print(f"{p:<18}{'❌否':<8}{'—':<12}{'→ unknown 待查':<34}miss")