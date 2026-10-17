#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出境 4 维约束注入器 —— worldstip-travel-planner v0.2.0

第一性原理结论：国界改变的是【约束】，不是【求解器】。
排程 / 交通比选 / 预算 / 可行性体检 / 渲染 与国界无关，应 0 改动复用；
出境真正新增的是 4 个国内不存在或权重极低的约束维度：
    ① 准入可行性（硬门槛，不过则行程为 0）
    ② 货币与购买力
    ③ 合规与文化
    ④ 领事与制度安全

本模块只做「约束注入」：读references → 产出约束字典 + 门禁输入 + 可信度条目。
不排程、不渲染、不联网。调不出来的字段一律走 unknown → 输出'以官方为准'。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import refloader

REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    # v0.2.1：国内判定改接权威索引（geo_admin.json，34省/366市/3006县）
    from geo_lookup import is_domestic as _is_domestic_indexed, DOMESTIC_REGIONS
except Exception:  # 索引文件缺失时退回最小内置名单，保证不崩
    _is_domestic_indexed = None
    DOMESTIC_REGIONS = {"中国香港", "中国澳门", "中国台湾", "香港", "澳门", "台湾",
                        "Hong Kong", "Macao", "Macau", "Taiwan"}


def is_domestic(name: str) -> bool:
    """判定一个地名是否在中国境内。

    v0.2.1 变更：不再依赖手写短名单（原 _CN_CITIES仅约 180 项，
    「芒市」「霍尔果斯」「婺源」等真实县名全部漏判 → 国内用户被误判出境
    → 凭空弹签证门禁卡），改接 references/geo_admin.json 权威索引
    （民政部县以上行政区划代码公开整理版），并叠加 destination_links.json
    的 249 个景点名与景区别名表。

    保守取向不变：索引不中 → 返回 False → 上层走 unknown 灰灯「待查」，
    绝不反推国别、绝不编造。理由：把境外地名误判成境内，
    会让出境用户漏掉签证/保险门禁，那是硬安全风险。
    """
    n = str(name or "").strip()
    if not n:
        return False
    if _is_domestic_indexed is not None:
        return _is_domestic_indexed(n)
    # 降级路径：索引模块不可用时，至少保住港澳台与直辖市
    return n in DOMESTIC_REGIONS

# v0.2.1：原手写白名单（_CN_PROVINCES / _CN_CITIES，约 180 项）已删除。
# 原因：中国实际有 34 个省级 / 366 个地级 / 3006 个县级行政区，短名单必然漏判
# （芒市、霍尔果斯、婺源、阿尔山等真实县名全不在名单内 → 国内行程被误判出境 →
#  国内用户凭空看到签证门禁卡，直接击穿「不破坏现有用户」底线）。
# 替代方案：geo_lookup.is_domestic() 接 references/geo_admin.json 权威索引。



def _load(name: str) -> dict:
    return refloader.load(name)


def is_outbound(destinations: list | str | None) -> bool:
    """判定是否出境行程。

    判定逻辑：只要有【任一】目的地不在国内白名单 → 判出境。
    港澳台一律视为国内（属中国境内）。
    保守取向：不确定的一律判出境→ 门禁显示灰灯「待查」，绝不误给国内用户弹签证卡；
    真正的国内城市都在白名单里，不会被误判。
    """
    if not destinations:
        return False
    if isinstance(destinations, str):
        destinations = [destinations]
    return any(str(d).strip() and not is_domestic(str(d)) for d in destinations)


def _visa_names(db: dict) -> list[str]:
    """可解析的国家名全集 = countries 主键 + 互免/单免名单 + 括号别名。

    踩过的坑（v0.3.0 遗留，本轮修）：`visa_free_for_cn_ordinary.mutual_agreement`
    名单里有 29 国（阿尔巴尼亚/阿联酋/格鲁吉亚/哈萨克斯坦…），而 `countries`
    只有 10 个主键。`_pick_country` 只遍历主键 → 名单里 19 国全部解析不出来 →
    admission() 里 `self.country in mut.get("list")` 恒为 False →
    问「格鲁吉亚要不要签证」只能答 unknown（灰灯）。

    这不安全吗？不编造，是安全的；但它是**漏答**——官方互免协定一览表
    （`_sources.agreement_table`，更新至 2026-05-29）就在同一张表里，
    数据在表里、代码没接上。典型的能力缺口而非数据缺口。

    安全性边界：只把名单中的国名注册为可识别目标，不改写任何签证结论。
    `admission()` 中原有的 `in_mutual / in_unilateral` 判断继续生效，
    最终结论仍由 countries 条目 + 名单共同决定，查不到依旧 None（灰灯）。

    注意参数是【整张 visa_rules 表】而不是 countries 子表——免签名单
    `visa_free_for_cn_ordinary` 在顶层，传子表会什么都取不到（踩过）。

    返回 (names, alias_map)：alias_map 把括号短名映射回全名，
    供调用方归一化（见 _pick_country 的说明）。
    """
    names = [k for k in db.get("countries", {}) if not str(k).startswith("_")]
    alias_map: dict[str, str] = {}
    vf = db.get("visa_free_for_cn_ordinary") or {}
    pool: set[str] = set()
    for section in ("mutual_agreement", "unilateral_exempt"):
        sec = vf.get(section) or {}
        if isinstance(sec, dict):
            for k, v in sec.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, list):
                    pool.update(str(x).strip() for x in v if str(x).strip())
        elif isinstance(sec, list):
            pool.update(str(x).strip() for x in sec if str(x).strip())
    for n in sorted(pool):
        names.append(n)
        # 「波斯尼亚和黑塞哥维那（波黑）」→ 别名「波黑」也要能命中
        if "（" in n and "）" in n:
            short = n[n.index("（") + 1: n.index("）")].strip()
            if short:
                names.append(short)
                alias_map[short] = n   # 「波黑」→「波斯尼亚和黑塞哥维那（波黑）」
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out, alias_map


def _pick_country(destinations: list[str]) -> str:
    """从目的地列表里找出 references 中收录的国家名。

    用户通常给的是【城市】（东京/京都/巴黎），字典主键是【国家】（日本/法国），
    因此必须走四级匹配：精确 → 双向包含 → 城市→国家映射 → 城市名含国名兜底。
    踩过的坑：只做前两级匹配，东京匹配不上日本 → country='' → 全部退化成 unknown。

    别名必须归一化到全名：用户说「波黑」，命中别名后要返回
    「波斯尼亚和黑塞哥维那（波黑）」——否则 admission() 里
    `self.country in mut.get("list")` 用短名去比全名列表，永远 False，
    互免结论会退化成灰灯 unknown。
    """
    db = _load("visa_rules.json")
    names, alias_map = _visa_names(db)
    main_keys = db.get("countries", {})
    dests = [str(d).strip() for d in destinations]
    for d in dests:
        if is_domestic(d):
            continue
        if d in main_keys or d in names:
            return alias_map.get(d, d)
    for d in dests:  # 双向包含（"日本东京" 之类）
        if is_domestic(d):
            continue
        for k in names:
            if k in d or d in k:
                return alias_map.get(k, k)
    for d in dests:  # 城市 → 国家
        if is_domestic(d):
            continue
        ctry = CITY_TO_COUNTRY.get(d)
        # 注意：要查 countries 子表/免签名单，不能查整张表的顶层键
        # （顶层键是 version/_updated/countries…，曾因查错层级导致
        #  曼谷/东京/首尔全部退化回 unknown）
        if ctry and (ctry in main_keys or ctry in names):
            return alias_map.get(ctry, ctry)
    for d in dests:  # 城市名含国名兜底
        if is_domestic(d):
            continue
        for k in names:
            if d in k:
                return alias_map.get(k, k)
    return ""


# 城市 → 国家（覆盖出境热门目的地；只做确定映射，不做推断猜测）
CITY_TO_COUNTRY = {
    "东京": "日本", "京都": "日本", "大阪": "日本", "奈良": "日本", "札幌": "日本",
    "福冈": "日本", "冲绳": "日本", "名古屋": "日本", "广岛": "日本", "箱根": "日本",
    "首尔": "韩国", "釜山": "韩国", "济州": "韩国", "济州岛": "韩国",
    "曼谷": "泰国", "普吉": "泰国", "清迈": "泰国", "苏梅": "泰国", "甲米": "泰国",
    "新加坡": "新加坡", "圣淘沙": "新加坡",
    "吉隆坡": "马来西亚", "槟城": "马来西亚", "马六甲": "马来西亚", "沙巴": "马来西亚",
    "巴厘岛": "印度尼西亚", "雅加达": "印度尼西亚", "巴厘": "印度尼西亚",
    "巴黎": "法国", "伦敦": "英国", "柏林": "德国", "慕尼黑": "德国",
    # 申根区只映射到国名会丢信息，且非申根城市误映射成"法国"是危险的编造。
    # 意大利/西班牙/葡萄牙等各自不同，此处只映射确定且与字典主键一致的；
    # 未列出的申根城市走 unknown → 「以使领馆官网为准」，不猜。
    "米兰": "", "威尼斯": "", "罗马": "", "巴塞罗那": "", "马德里": "",
    "里斯本": "", "维也纳": "", "布拉格": "", "雅典": "",
    "纽约": "美国", "洛杉矶": "美国", "旧金山": "美国", "西雅图": "美国",
    "芝加哥": "美国", "波士顿": "美国", "华盛顿": "美国", "迈阿密": "美国",
    "温哥华": "加拿大", "多伦多": "加拿大", "蒙特利尔": "加拿大",
    "悉尼": "澳大利亚", "墨尔本": "澳大利亚", "昆兰": "澳大利亚",
    "奥克兰": "新西兰", "皇后镇": "新西兰", "惠灵顿": "新西兰",
    # 迪拜/阿布扎比属阿联酋、第比利斯属格鲁吉亚——两者都在互免名单内，
    # 但都不是 countries 主键。v0.3.0 时因名单未接入而只能答 unknown；
    # 名单接入后应能解析（互免结论由 admission() 的 in_mutual 判定给出）。
    # 历史上踩过的坑：曾把迪拜误映射到申根国——那是编造，比 unknown 危险得多。
    "迪拜": "阿联酋", "阿布扎比": "阿联酋", "沙迦": "阿联酋",
    "第比利斯": "格鲁吉亚", "巴统": "格鲁吉亚",
}


def _entry_of(section: dict, country: str) -> dict | None:
    """在货币/时差/安全等字典里找该国条目（含申根区这类泛化匹配）。"""
    if not section:
        return None
    if country in section:
        return section[country]
    for k, v in section.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and country in v:
            return v[country]
    return None


class OutboundConstraints:
    """注入 4 维约束。查不到就走 fallback，绝不猜。"""

    def __init__(self, destinations: list[str] | None):
        self.destinations = list(destinations or [])
        self.outbound = is_outbound(self.destinations)
        self.country = _pick_country(self.destinations) if self.outbound else ""
        self.visa_db = _load("visa_rules.json")
        self.fx_db = _load("currency_tz.json")
        self.customs_db = _load("local_customs.json")
        self.safety_db = _load("country_safety.json")
        self.facts: list[dict] = []  # 供 credibility 内核消费

    # ── 维度① 准入可行性 ──
    def admission(self, *, passport_valid_months: int | None = None,
                  days_to_depart: int | None = None,
                  insurance_amount: int | None = None) -> dict:
        """产出门禁卡输入。返回 {} 表示国内或未收录（→灰灯待查，不猜）。"""
        if not self.outbound:
            return {}
        c = (self.visa_db.get("countries", {}) or {}).get(self.country) or {}
        pg = self.visa_db.get("passport_general", {}) or {}
        mut = (self.visa_db.get("visa_free_for_cn_ordinary", {}) or {}).get("mutual_agreement", {}) or {}
        unil = (self.visa_db.get("visa_free_for_cn_ordinary", {}) or {}).get("unilateral_exempt", {}) or {}

        # 是否在免签/互免名单
        in_mutual = self.country in (mut.get("list") or [])
        in_unilateral = any(self.country in (unil.get(k) or []) for k in
                            ("asia", "africa", "americas", "oceania") if not k.startswith("_"))
        if c.get("visa_required") == "none" or in_mutual or in_unilateral:
            visa_required = "none"
        elif c.get("visa_required") == "conditional":
            visa_required = "unknown"
        elif c.get("visa_required"):
            visa_required = "required"
        else:
            visa_required = None  # 未收录 → None → 灰灯

        # 记录保额要求（申根等）
        ins_min = c.get("insurance_min_amount_eur") or c.get("insurance_min_amount")

        self.facts += [
            {"key": f"{self.country}.visa", "label": "是否需要签证",
             "value": visa_required or "未收录", "domain": "准入与证件"},
            {"key": f"{self.country}.passport", "label": "护照有效期规则",
             "value": c.get("passport_validity_months", "以官方为准"), "domain": "准入与证件"},
        ]

        gate = {
            "passport_valid_months": passport_valid_months,
            "passport_required_months": c.get("passport_validity_months") or pg.get("validity_months_typical", 6),
            "visa_required": visa_required,
            "visa_lead_days": c.get("processing_days"),
            "days_to_depart": days_to_depart,
            "vaccine_required": c.get("vaccine_required"),
            "insurance_required": bool(c.get("insurance_required") or ins_min),
            "insurance_amount": insurance_amount,
            "insurance_min_amount": ins_min or 0,
        }
        return {k: v for k, v in gate.items() if v is not None or k == "visa_required"}

    # ── 维度② 货币与购买力 ──
    def money(self) -> dict:
        if not self.outbound:
            return {}
        cur = _entry_of(self.fx_db.get("currencies", {}) or {}, self.country)
        tz = _entry_of(self.fx_db.get("timezones", {}) or {}, self.country)
        pay = _entry_of(self.fx_db.get("payment_and_tipping", {}) or {}, self.country)
        out: dict[str, Any] = {}
        if cur:
            out["currency"] = f"{cur.get('unit','')}（{cur.get('code','')} {cur.get('symbol','')}）"
            out["rate_note"] = cur.get("rate_note", "")
        if tz:
            out["time_diff"] = tz.get("diff_beijing", "")
            out["dst"] = tz.get("dst", tz.get("_dst_stability", ""))
        if pay:
            out["card"] = pay.get("card", "")
            out["mobile_pay"] = pay.get("mobile_pay", "")
            out["tipping"] = pay.get("tipping", "")
        self.facts += [
            {"key": f"{self.country}.fx", "label": "大致汇率量级",
             "value": (cur or {}).get("rate_note", "未收录"), "domain": "货币与购买力"},
            {"key": f"{self.country}.tz", "label": "时差",
             "value": out.get("time_diff", "未收录"), "domain": "货币与购买力"},
        ]
        return out

    # ── 维度③ 合规与文化 ──
    def culture(self) -> dict:
        if not self.outbound:
            return {}
        drive = _entry_of(self.customs_db.get("driving_and_plug", {}) or {}, self.country)
        tips = _entry_of(self.customs_db.get("customs_and_tips", {}) or {}, self.country)
        trans = _entry_of(self.customs_db.get("local_transport_and_apps", {}) or {}, self.country)
        out: dict[str, Any] = {"_note": "以下为硬性合规要点，违反可能引发罚款、拒入境或更严重后果。"}
        if drive:
            out["driving"] = f"{drive.get('driving_side','')}，{drive.get('plug','')}，{drive.get('voltage','')}"
        if tips:
            out["taboos"] = tips.get("taboos", [])
            out["dress"] = tips.get("dress", "")
        if trans:
            out["transport"] = trans.get("transport", "")
            out["apps"] = trans.get("apps", [])
        self.facts += [
            {"key": f"{self.country}.drive", "label": "靠左/靠右行驶",
             "value": (drive or {}).get("driving_side", "未收录"), "domain": "合规与文化"},
            {"key": f"{self.country}.customs", "label": "宗教与民族禁忌",
             "value": "、".join((tips or {}).get("taboos", [])[:3]) or "未收录", "domain": "合规与文化"},
        ]
        return out

    # ── 维度④ 领事与制度安全 ──
    def safety(self) -> dict:
        base = (self.safety_db.get("universal_emergency", {}) or {})
        out: dict[str, Any] = {}
        if base:
            out["consular"] = base.get("consular_protection_cn", "12308")
            out["consular_overseas"] = base.get("consular_protection_overseas", "+86-10-12308")
        if not self.outbound:
            return out
        cs = _entry_of(self.safety_db.get("country_safety", {}) or {}, self.country)
        if cs:
            out["severity"] = cs.get("severity", "")
            out["scams"] = cs.get("scams", [])
            out["natural"] = cs.get("natural", [])
            out["verify"] = cs.get("verify", "")
        else:
            out["severity"] = "未收录"
            out["verify"] = "cs.mfa.gov.cn 目的地安全页"
        self.facts += [
            {"key": f"{self.country}.security", "label": "治安大致水平",
             "value": out.get("severity", "未收录"), "domain": "领事与制度安全"},
        ]
        return out

    # ── 高风险区域硬拦（命中即强提示） ──
    def risk_flags(self) -> list[dict]:
        flags = []
        for item in (self.safety_db.get("high_risk_regions", {}) or {}).get("avoid", []):
            if not str(item.get("region", "")).startswith("_"):
                for d in self.destinations:
                    if item.get("region", "") in str(d):
                        flags.append(item)
        return flags

    def all_facts(self) -> list[dict]:
        return list(self.facts)

    def summary(self) -> dict:
        return {"outbound": self.outbound, "country": self.country,
                "risk_flags": len(self.risk_flags())}


if __name__ == "__main__":
    import sys
    for dests in (["东京", "京都"], ["佛山", "南岳"], ["巴黎"], ["曼谷"], ["纽约"]):
        oc = OutboundConstraints(dests)
        print(f"\n=== {dests} → outbound={oc.outbound} country={oc.country} ===")
        if oc.outbound:
            print("准入:", json.dumps(oc.admission(days_to_depart=10), ensure_ascii=False))
            print("货币:", json.dumps(oc.money(), ensure_ascii=False))
            print("文化:", json.dumps({k: v for k, v in oc.culture().items() if k != "taboos"}, ensure_ascii=False))
            print("安全:", json.dumps({k: v for k, v in oc.safety().items() if k != "scams"}, ensure_ascii=False))
            print("风险旗标:", oc.risk_flags())
            print("事实条数:", len(oc.all_facts()))
    sys.exit(0)
