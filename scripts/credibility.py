#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可信度内核 —— worldstip-travel-planner 出境模式的前置件（v0.2.0）

设计要点（源自第一性原理结论）：
  1. 零依赖 ≠ 离线可信。零依赖指运行时不依赖第三方包 / API key；调研仍走宿主
     WebSearch / WebFetch。要放弃的是"离线也给确定答案"这个隐含承诺。
  2. 5 个出境 JSON 不是"权威答案库"，而是"基线缓存 + 核验清单"。
  3. 每条事实带 stability 三档：stable 直出 / volatile 须核验 / unknown 待查。
  4. 未核验不是错误，是必须诚实呈现的状态 → 渲染时挂降级角标，而不是沉默直出。

用法：
    from credibility import Credibility, level_of, badge_for

    cred = Credibility()
    cred.declare("日本·是否需要签证", "是否需要签证", "voluntary_evisa")
    cred.mark_verified("日本·是否需要签证", "中国领事服务网", "2026-10-12")
    html = cred.section_html()
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")
STABILITY_FILE = os.path.join(REF_DIR, "stability.json")

STABLE, VOLATILE, UNKNOWN = "stable", "volatile", "unknown"


# ── 基础加载 ──────────────────────────────────────────────────────────────
def load_stability() -> dict:
    with open(STABILITY_FILE, encoding="utf-8") as f:
        return json.load(f)


_DB: dict | None = None


def db() -> dict:
    global _DB
    if _DB is None:
        _DB = load_stability()
    return _DB


# ── 查询：字段 → stability ────────────────────────────────────────────────
def level_of(domain: str, field: str, default: str = UNKNOWN) -> str:
    """查某领域某字段的稳定性。查不到一律 unknown —— 宁可标'待查'，不猜。"""
    fields = (db().get("domains", {}).get(domain, {}) or {}).get("fields", {})
    return fields.get(field, default)


def level_of_any(field: str, default: str = UNKNOWN) -> str:
    """跨领域反查（同一字段名在多个领域都有定义时用），取最保守的一档。"""
    order = {STABLE: 0, VOLATILE: 1, UNKNOWN: 2}
    best = None
    for dom in db().get("domains", {}).values():
        lv = (dom.get("fields") or {}).get(field)
        if lv:
            if best is None or order[lv] > order[best]:
                best = lv
    return best or default


# ── 简称别名表：把调用方常用的口语化 label 归一到字典里【真实存在的中文字段名】 ──
# 关键：stability.json 的 key 是中文字段名（如 "大致汇率量级"），因此别名必须指向
# 中文字段名，绝不能自造英文 key —— 否则查字典必然落空，整表退化成 unknown。
# 踩过的坑：曾把别名映射到 visa_required / fx_rate 这类英文 key，结果全部 unknown。
ALIASES: dict[str, str] = {
    # 准入与证件
    "签证": "是否需要签证",
    "需不需要签证": "是否需要签证",
    "免签政策": "是否需要签证",
    "签证类型": "签证类型与材料清单",
    "签证材料": "签证类型与材料清单",
    "签证材料清单": "签证类型与材料清单",
    "签证类型与材料": "签证类型与材料清单",
    "驾照认可情况": "靠左/靠右行驶",
    "驾照": "靠左/靠右行驶",
    "驾照能否使用": "靠左/靠右行驶",
    "签证时长": "办理时长",
    "签证办理时长": "办理时长",
    "护照有效期": "护照有效期规则",
    "护照剩余有效期": "护照有效期规则",
    "疫苗要求": "疫苗与健康证明",
    "健康证明": "疫苗与健康证明",
    "保险保额": "保险最低保额要求",
    "旅行保险保额": "保险最低保额要求",
    "紧急电话": "当地紧急电话",
    # 货币与购买力
    "汇率": "大致汇率量级",
    "汇率量级": "大致汇率量级",
    "日汇率量级": "大致汇率量级",
    "货币名称": "本地货币名称与符号",
    "货币符号": "本地货币名称与符号",
    "换汇": "换汇点与是否存在",
    "刷卡": "刷卡/移动支付可用性",
    "移动支付可用性": "刷卡/移动支付可用性",
    "支付方式": "刷卡/移动支付可用性",
    "小费": "现金与小费文化",
    "小费文化": "现金与小费文化",
    "单日花费": "单日大致花费基线",
    # 合规与文化
    "靠左行驶": "靠左/靠右行驶",
    "行驶方向": "靠左/靠右行驶",
    "插头电压": "插头标准与电压",
    "电压": "插头标准与电压",
    "宗教禁忌": "宗教与民族禁忌",
    "民族禁忌": "宗教与民族禁忌",
    "文化禁忌": "宗教与民族禁忌",
    "禁忌": "宗教与民族禁忌",
    "当地习俗": "宗教与民族禁忌",
    "饮食禁忌": "当地饮食禁忌",
    "管制药品": "管制药品清单",
    "当地交通": "当地交通票制与通勤方式",
    "必装App": "必装App与本地支付工具",
    "必装App与支付": "必装App与本地支付工具",
    # 领事与制度安全
    "治安水平": "治安大致水平",
    "治安情况": "治安大致水平",
    "诈骗手法": "常见诈骗手法",
    "常见诈骗": "常见诈骗手法",
    "外出时段": "外出建议时段",
    "使领馆地址": "使领馆地址与办公时间",
    "自然灾害": "自然灾害与季节风险",
    "季节风险": "自然灾害与季节风险",
    "领事电话": "领事保护电话",
    # 国内原有字段
    "门票": "门票价格",
    "票价": "门票价格",
    "营业时间": "开放时间",
    "开放": "开放时间",
    "闭馆": "开放时间",
    "预约要求": "景区预约要求",
    "预约": "景区预约要求",
    "末班船": "末班车/末班船",
    "末班车": "末班车/末班船",
    "天气": "天气实况",
    "班次": "交通班次与耗时",
    "交通耗时": "交通班次与耗时",
    "限行": "是否限行",
    "停车": "停车与接驳",
    "接驳": "停车与接驳",
    "步行强度": "地形与步行强度",
    "地形": "地形与步行强度",
    "最佳季节": "最佳季节窗口",
}


def canonical_field(field: str) -> str:
    """把中文 label 归一到字典中真实存在的中文字段名。

    归一顺序：原样命中 → 别名表 → 去国别/限定前缀后再试 → 字典全字段扫描。
    都不中就原样返回，由 declare 记入 unmapped 供自查。
    """
    if field in ALIASES:
        return ALIASES[field]
    for dom in db().get("domains", {}).values():
        if field in (dom.get("fields") or {}):
            return field
    # 真实写法常是「日本·驾照认可情况」「日本签证类型与材料」这类带限定前缀的，
    # 逐段剥掉前缀再试（最长后缀优先），否则会误判 unknown。
    parts = field.replace("·", "").replace("、", "").replace("：", "").replace(":", "")
    for n in range(len(parts) - 1, 1, -1):
        tail = parts[n:]
        if tail in ALIASES:
            return ALIASES[tail]
        for dom in db().get("domains", {}).values():
            if tail in (dom.get("fields") or {}):
                return tail
    return field


# ── 核验记录 ──────────────────────────────────────────────────────────────
class Credibility:
    """收集本册中所有事实的稳定性状态，产出降级角标与核验台账。"""

    def __init__(self) -> None:
        self._cfg = db()
        self._rmeta = self._cfg.get("render", {})
        # key -> {level, label, source, verified_on, official_hint}
        self.items: dict[str, dict] = {}
        # 反查失败归一化到字典的字段名：供自查，避免静默退化成 unknown
        self.unmapped: list[str] = []

    # ── 声明一条事实 ──
    def declare(self, key: str, field: str, value: Any = None, *,
                domain: str | None = None, level: str | None = None,
                official_hint: str = "") -> dict:
        """登记事实。level 可显式指定，否则按 field 反查 stability 字典。

        反查顺序：显式 level → 领域内查 → 别名归一后全局查 → 显式传入 default。
        注意：查不到时**不静默吞掉**，会记进 unmapped 供调用方自查——
        静默 fallback 成 unknown 会让整个内核退化成"全部待查"，等于没做。
        """
        canon = canonical_field(field)
        if level is None and domain:
            level = level_of(domain, field)
            if level == UNKNOWN and canon != field:
                level = level_of(domain, canon)
        if level is None:
            level = level_of_any(canon)
        if level is None or level not in (STABLE, VOLATILE, UNKNOWN):
            level = UNKNOWN
            if canon not in self.unmapped:
                self.unmapped.append(canon)
        rec = {"level": level, "field": field, "canon": canon, "value": value,
               "label": field, "source": "", "verified_on": "",
               "official_hint": official_hint or self._cfg.get("sources", {}).get(canon, "")}
        self.items[key] = rec
        return rec


    def declare_level(self, key: str, label: str, level: str, **kw) -> dict:
        """直接指定等级登记（用于国家特例，如"某国免签但需提前在线登记"）。"""
        return self.declare(key, label, kw.pop("value", None), level=level, **kw)

    # ── 标记已核验 ──
    def mark_verified(self, key: str, source: str, on: str | None = None) -> None:
        if key in self.items:
            self.items[key]["source"] = source
            self.items[key]["verified_on"] = on or date.today().isoformat()

    # ── 判定 ──
    def needs_verify(self, key: str) -> bool:
        r = self.items.get(key)
        return bool(r) and r["level"] == VOLATILE and not r["verified_on"]

    def is_unknown(self, key: str) -> bool:
        r = self.items.get(key)
        return bool(r) and r["level"] == UNKNOWN

    def is_stale(self, key: str) -> bool:
        """超过 stale_after_days 未再核验 → 视为不可信。"""
        r = self.items.get(key)
        if not r or not r["verified_on"]:
            return False
        try:
            d = datetime.strptime(r["verified_on"], "%Y-%m-%d").date()
        except ValueError:
            return False
        return (date.today() - d).days > int(self._rmeta.get("stale_after_days", 30))

    def unverified(self) -> list[dict]:
        return [r for k, r in self.items.items()
                if r["level"] == VOLATILE and (not r["verified_on"] or self.is_stale(k))]

    def unknowns(self) -> list[dict]:
        return [r for r in self.items.values() if r["level"] == UNKNOWN]

    def verified(self) -> list[dict]:
        return [r for r in self.items.values() if r["verified_on"]]

    def stats(self) -> dict:
        return {
            "total": len(self.items),
            "stable": sum(1 for r in self.items.values() if r["level"] == STABLE),
            "volatile": sum(1 for r in self.items.values() if r["level"] == VOLATILE),
            "unknown": sum(1 for r in self.items.values() if r["level"] == UNKNOWN),
            "unverified": len(self.unverified()),
            "verified": len(self.verified()),
            "unmapped": len(self.unmapped),
        }

    # ── 渲染 ──
    def badge_for(self, key: str) -> str:
        """返回一枚角标 HTML；stable 或已核验返回空串（不打扰阅读）。"""
        r = self.items.get(key)
        if not r:
            return ""
        if r["level"] == STABLE:
            return ""
        if r["level"] == UNKNOWN:
            return self._badge("warn", self._rmeta.get("unknown_badge_text", "待查"))
        if self.needs_verify(key):
            txt = self._rmeta.get("unverified_badge_text", "未核验")
            if self.is_stale(key):
                txt += "·已超期"
            return self._badge("warn", txt)
        return ""

    @staticmethod
    def _badge(kind: str, text: str) -> str:
        return f'<span class="feat-badge {kind}" style="margin-left:4px">{text}</span>'

    def section_html(self) -> str:
        """册内「数据可信度台账」板块：把未核验与待查项诚实摊开。"""
        unv, unk = self.unverified(), self.unknowns()
        if not unv and not unk:
            v = self.verified()
            if v:
                newest = max((r["verified_on"] for r in v), default="")
                return (f'<div class="card"><h3>数据可信度</h3>'
                        f'<p class="sub" style="margin:0">易变信息已联网核验，共 {len(v)} 条，'
                        f'最近核验日期 {newest}。以官方当日公告为准。</p></div>')
            return ""

        P = []
        items_html = ""
        for r in unv + unk:
            badge = (self._rmeta.get("unknown_badge_text", "待查") if r["level"] == UNKNOWN
                     else self._rmeta.get("unverified_badge_text", "未核验"))
            hint = r.get("official_hint") or "官方渠道"
            items_html += (f'<li><span class="feat-badge warn">{badge}</span> '
                           f'<b>{r["label"]}</b> · 请以{hint}当日信息为准</li>')
        P.append(f'<div class="card"><h3>数据可信度台账'
                 f'<span class="feat-badge warn">{len(unv) + len(unk)} 条待确认</span></h3>'
                 f'<p class="sub" style="margin:2px 0 8px;color:var(--sub)">'
                 f'以下信息会随时间变化，本次未获得可靠来源，因此不给出确定结论。'
                 f'这比给一个可能过期的答案更诚实——请按提示渠道自行确认。</p>'
                 f'<ul class="kv">{items_html}</ul></div>')
        return "\n".join(P)

    def footer_note(self) -> str:
        s = self.stats()
        if s["total"] == 0:
            return ""
        parts = []
        if s["verified"]:
            parts.append(f"已核验 {s['verified']} 条")
        if s["unverified"]:
            parts.append(f"未核验 {s['unverified']} 条")
        if s["unknown"]:
            parts.append(f"待查 {s['unknown']} 条")
        if s["stable"]:
            parts.append(f"稳定基线 {s['stable']} 条")
        return " · ".join(parts)


if __name__ == "__main__":
    import sys
    c = Credibility()
    c.declare("日本·签证", "是否需要签证", "需签证/电子签", domain="准入与证件")
    c.declare("日本·靠左行驶", "靠左/靠右行驶", "靠左", domain="合规与文化")
    c.declare("日本·汇率", "大致汇率量级", "1 CNY ≈ 20 JPY", domain="货币与购买力")
    c.declare("某国·具体材料", "签证类型与材料清单", None, domain="准入与证件",
              level="unknown", official_hint="该国驻华使领馆官网")
    c.mark_verified("日本·签证", "中国领事服务网", "2026-10-12")
    print(json.dumps(c.stats(), ensure_ascii=False, indent=2))
    print(c.footer_note())
    print(c.badge_for("日本·汇率"))
    print(c.section_html()[:200])
    sys.exit(0)
