"""摩旅数据增强通道 —— 把「出行前必须现查」变成可执行的检索管道。

## 为什么需要这个模块

`moto_rules.json` / `moto_routes.json` 只写**稳定事实**（政策条文、地形性质、
季节规律、线路走向）。但摩旅决策真正依赖的四类信息**全都会过期**：

  ① 禁摩/限摩政策的时效性调整（通告有效期通常 1-5 年）
  ② 高速入口的临时管制（同一省份不同入口口径都可能不同）
  ③ 塌方、断路、施工（山区线每年都在变）
  ④ 补给点与加油站实况（关闭、改造、不给摩托加油）

把这四类写进静态库 = 埋雷。学行业数据池的数据池思路 + 用户要求的社交平台交互：
**不是把社媒内容爬进库，而是给一条「检索 → 校验 → 落地」的管道。**

## 管道怎么走

  build_checklist()  按行程算出「该查什么」：分类、建议检索词、建议来源平台
  ingest_note()      规定「查回来的东西怎么记」：必须带 source + date，
                     自动标 evidence=third_party / stability=volatile
  validate_notes()   批量校验外部传入的笔记文件（--moto-notes）

## 证据纪律（不可让步）

  社媒/第三方来源**永远**是 third_party + volatile，无论多少人说一样的话。
  只有政府/交管原文才能标 statute。把「社交平台上都说可以上」写成结论，
  和编造一个绿灯是同一类错误。
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

try:  # 与 moto_check 同目录，直接导入复用其数据与转义
    import moto_check as _mc
    from moto_check import _esc, rules as _rules
except Exception:  # 独立运行时的降级（仅影响 HTML 输出）
    _mc = None  # type: ignore[assignment]

    def _esc(s: Any) -> str:  # type: ignore[misc]
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _rules() -> dict:  # type: ignore[misc]
        return {}

# 建议来源平台（按可信度从高到低排列，检索时优先前者）
SOURCE_TIERS = [
    {"name": "当地交管/政府官网", "weight": "statute 候选",
     "how": "搜「XX市 摩托车 禁行 通告 site:gov.cn」或直接查交警公众号"},
    {"name": "社交平台", "weight": "third_party",
     "how": "搜「XX 摩旅 路线/禁摩/加油」，看最近 30 天的实测笔记；"
            "多人近期说法一致才可作为参考，且必须记录发布日期"},
    {"name": "行业数据池", "weight": "third_party",
     "how": "摩友社区有禁摩区域地图与沿途补给讨论，适合看趋势"},
    {"name": "地图服务 / 备用地图服务", "weight": "third_party",
     "how": "导航 App 的限行图层与实时路况；注意驾车模式不含摩托禁行数据"},
    {"name": "中国天气网 / 垭口实况", "weight": "third_party",
     "how": "高海拔垭口天气变化快，出发前 1 天与当天各查一次"},
]

_EVIDENCE_ORDER = {"statute": 3, "practice": 2, "third_party": 1}


def today() -> str:
    """今天（本地日期）。用于校验检索笔记的时效性。"""
    return _dt.date.today().isoformat()


# ── 一、生成「该查什么」清单 ────────────────────────────────────────────
def build_checklist(*, from_city: str | None = None, to_city: str | None = None,
                    via_cities: list[str] | None = None, days: int | None = None,
                    routes: list[dict] | None = None) -> dict:
    """按行程生成出行前待核实清单。

    分类与颗粒度由**数据自身的证据等级**决定，不是一律都查：
      - statute 级政策 → 列为「出发前快速复核」而非「必须查」
      - practice / third_party 级 → 「必须查」，因为它可能就是错的
      - unknown → 「必须查」，因为库里根本没有答案
    这样的排序让用户把时间花在真正有风险的信息上。
    """
    cities = [c for c in ([from_city, to_city] + list(via_cities or [])) if c]
    r = _rules()

    items: list[dict] = []

    # ① 政策类：逐省高速准入 + 逐城禁摩限行
    ha = r.get("highway_access") or {}
    prov_seen = []
    for c in cities:
        p = _mc.province_of(c) if _mc else None
        if p and p not in prov_seen:
            prov_seen.append(p)
    for p in prov_seen:
        rec = ha.get(p) or {}
        ev = rec.get("evidence") or "unknown"
        must = ev in ("practice", "third_party", "unknown")
        items.append({
            "kind": "policy", "topic": f"{p} 摩托车高速准入",
            "must_check": must,
            "evidence": ev,
            "why": (f"本库标注为 {ev}（{'有法规明文' if ev == 'statute' else '执法口径或第三方汇总'}），"
                    + ("出发前 1-3 天快速复核入口标志即可。" if not must
                       else "存在被现场劝返风险，务必查最新通告并在导航里避开。")),
            "query": f"{p} 摩托车 高速 禁行 通告",
            "sources": ["当地交管/政府官网", "社交平台", "行业数据池"],
        })
    for rec in (r.get("city_ban") or []):
        city = rec.get("city") or ""
        if not city or not any(city in c or c in city for c in cities):
            continue
        stab = rec.get("stability") or "unknown"
        must = stab in ("volatile", "unknown")
        items.append({
            "kind": "policy", "topic": f"{city} 禁摩/限行范围",
            "must_check": must,
            "evidence": "unknown" if stab == "unknown" else "volatile",
            "why": ("本库未查证到权威来源，**不要默认可以进也不要默认不能进**——"
                    "必须以当地最新通告为准。" if stab == "unknown"
                    else "限行政策有时效性，本库口径需复核。"),
            "query": f"{city} 摩托车 限行 {today()[:4]}",
            "sources": ["当地交管/政府官网", "社交平台"],
        })

    # ②-b 未收录城市兜底：不在 45 城名单内 ≠ 不禁摩。
    # 纪律与 moto_check 一致——「未查证」既不报绿灯也不报红灯，只报「必须查」。
    ban_cities = [rec.get("city") or "" for rec in (r.get("city_ban") or [])]
    for c in cities:
        short = c.rstrip("市区县")
        if short and any(short in bc or bc in short for bc in ban_cities):
            continue
        items.append({
            "kind": "policy", "topic": f"{c} 禁摩/限行（本库未收录该城）",
            "must_check": True,
            "evidence": "unknown",
            "why": ("该城市不在本库禁摩名单内。**未收录只代表没有数据，不代表不禁摩**——"
                    "县级市与非常规目的地恰恰是政策真空带，必须单独查一次。"),
            "query": f"{c} 摩托车 禁行 限行 通告",
            "sources": ["当地交管/政府官网", "社交平台"],
        })

    # ② 补给类：只对稀疏段要求查
    for rt in (routes or []):
        dens = rt.get("fuel_density") or ""
        if dens in ("稀疏", "极稀疏"):
            items.append({
                "kind": "supply", "topic": f"{rt.get('name')} 沿途补给",
                "must_check": dens == "极稀疏",
                "evidence": "unknown",
                "why": (f"该线补给密度「{dens}」——单段无补给可能超过安全续航，"
                        "必须提前标出加油点。"),
                "query": f"{rt.get('name')} 摩旅 加油站 实测",
                "sources": ["社交平台", "行业数据池", "地图服务 / 备用地图服务"],
            })

    # ③ 路况类：山区线 + 雨季必查
    for rt in (routes or []):
        road = (rt.get("road") or "") + (rt.get("caution") or "")
        season = rt.get("season") or ""
        risky = any(k in road for k in ("塌方", "落石", "砂石", "涉水", "雨季", "积雪"))
        if risky or days and days >= 5:
            items.append({
                "kind": "road", "topic": f"{rt.get('name')} 近期路况",
                "must_check": risky,
                "evidence": "unknown",
                "why": "山区与砂石路段受季节与施工影响大，库内只有地形性质，没有当期路况。",
                "query": f"{rt.get('name')} 路况 塌方 最近",
                "sources": ["社交平台", "地图服务 / 备用地图服务"],
            })

    # ④ 天气类：高海拔线
    for rt in (routes or []):
        if any(k in (rt.get("caution") or "") + (rt.get("highlight") or "")
               for k in ("垭口", "海拔", "高原", "雪山")):
            items.append({
                "kind": "weather", "topic": f"{rt.get('name')} 垭口天气",
                "must_check": False,
                "evidence": "unknown",
                "why": "高海拔垭口天气突变频繁，出发前 1 天与当天早晨各查一次。",
                "query": f"{rt.get('name')} 天气 垭口",
                "sources": ["中国天气网 / 垭口实况", "社交平台"],
            })

    # 去重（同 topic 只留 must_check=True 的那条）
    dedup: dict[str, dict] = {}
    for it in items:
        k = it["topic"]
        if k not in dedup or (it["must_check"] and not dedup[k]["must_check"]):
            dedup[k] = it
    items = sorted(dedup.values(), key=lambda x: (not x["must_check"], x["kind"], x["topic"]))

    return {
        "generated_at": today(),
        "route_cities": cities,
        "items": items,
        "must_count": sum(1 for i in items if i["must_check"]),
        "source_tiers": SOURCE_TIERS,
        "compliance_note": ("本清单只用于检索**公开**信息（政府通告、公开笔记、公开路况），"
                            "不做批量抓取、不保存原文，只保留「结论 + 来源 + 日期」三元组。"),
    }


# ── 二、落地「查回来的东西」 ────────────────────────────────────────────
def ingest_note(topic: str, content: str, source: str, date: str,
                url: str = "") -> dict:
    """把一条检索结果转成标准记录。

    硬性要求：
      1. 四项必填：topic / content / source / date。缺一项直接抛错——
         不完整的记录等于没有记录，将来没人知道该信不该信。
      2. date 必须是 YYYY-MM-DD 且不晚于今天。未来的日期是录入错误。
      3. evidence 恒为 third_party：社媒与第三方汇总永远不能升级成 statute，
         哪怕十个人说法一致。
      4. stability 恒为 volatile：会变的信息，落地即开始过期。
    """
    topic = (topic or "").strip()
    content = (content or "").strip()
    source = (source or "").strip()
    date = (date or "").strip()
    if not topic:
        raise ValueError("ingest_note: topic 不能为空（查的是什么）")
    if not content:
        raise ValueError(f"ingest_note[{topic}]: content 不能为空（查到的结论）")
    if not source:
        raise ValueError(f"ingest_note[{topic}]: source 不能为空（来源平台/出处）")
    if not date:
        raise ValueError(f"ingest_note[{topic}]: date 不能为空（信息来源日期）")
    try:
        d = _dt.date.fromisoformat(date)
    except ValueError:
        raise ValueError(f"ingest_note[{topic}]: date 需为 YYYY-MM-DD，实得 {date!r}")
    if d > _dt.date.today():
        raise ValueError(f"ingest_note[{topic}]: date 晚于今天（{date}），请检查")
    age = (_dt.date.today() - d).days
    rec = {
        "topic": topic, "content": content, "source": source, "date": date,
        "evidence": "third_party", "stability": "volatile",
        "url": (url or "").strip(),
        "age_days": age,
    }
    if age > 30:
        rec["stale_warning"] = (f"该信息已 {age} 天，超过 30 天——"
                                f"禁摩与路况类信息请重新检索后再用")
    return rec


def validate_notes(notes: Any) -> list[dict]:
    """批量校验外部传入的笔记列表（--moto-notes JSON 文件内容）。

    接受 {"notes": [...]} 或裸列表。逐条过 ingest_note，
    失败的那条**跳过并记入 errors**，不让一条坏数据毁掉整包。
    """
    if isinstance(notes, dict):
        notes = notes.get("notes") or []
    if not isinstance(notes, list):
        raise ValueError("notes 需为列表，或含 notes 键的对象")
    ok, errs = [], []
    for i, n in enumerate(notes):
        if not isinstance(n, dict):
            errs.append({"index": i, "error": "条目需为对象"})
            continue
        try:
            ok.append(ingest_note(n.get("topic"), n.get("content"),
                                  n.get("source"), n.get("date"), n.get("url")))
        except ValueError as e:
            errs.append({"index": i, "topic": n.get("topic") or "", "error": str(e)})
    if errs:
        ok.append({"_errors": errs})  # type: ignore[arg-type]
    return ok


# ── 三、渲染 ───────────────────────────────────────────────────────────
_KIND_LABEL = {"policy": "政策核实", "supply": "补给确认", "road": "路况确认",
               "weather": "天气关注"}


def enrichment_html(cl: dict, notes: list[dict] | None = None) -> str:
    """把清单与已落地笔记渲染成 HTML 片段，嵌入小册子。"""
    if not cl or not cl.get("items"):
        return ""
    rows = ""
    for it in cl["items"]:
        badge = ('<span class="feat-badge" style="background:#FCEBEB;color:#A32D2D;'
                 'border:1px solid #A32D2D">必须查</span>' if it["must_check"]
                 else '<span class="feat-badge">建议复核</span>')
        srcs = "、".join(_esc(s) for s in it.get("sources") or [])
        rows += (f'<li style="margin:0 0 9px"><b>{_esc(it["topic"])}</b> {badge}'
                 f'<div style="font-size:12.5px;line-height:1.6;color:var(--sub);margin-top:2px">'
                 f'{_esc(it.get("why") or "")}</div>'
                 f'<div style="font-size:12.5px;line-height:1.6;margin-top:2px">'
                 f'检索词：<code>{_esc(it.get("query") or "")}</code>　·　建议来源：{srcs}</div></li>')
    head = (f'<div class="card"><h3>出行前待核实清单'
            f'<span class="feat-badge">{cl.get("must_count", 0)} 项必须查</span></h3>'
            f'<p style="font-size:12.5px;line-height:1.65;color:var(--sub);margin:0 0 8px">'
            f'技能库只写稳定事实。下列信息会过期，出发前按清单逐项核实——'
            f'<b>查不到就标 unknown，不要猜。</b></p>'
            f'<ul class="kv">{rows}</ul></div>')

    body = ""
    real = [n for n in (notes or []) if isinstance(n, dict) and "_errors" not in n]
    errs = next((n["_errors"] for n in (notes or [])
                 if isinstance(n, dict) and "_errors" in n), [])
    if real:
        lis = ""
        for n in real:
            warn = (f'<div style="color:#A32D2D;font-size:12px">⚠ {_esc(n["stale_warning"])}</div>'
                    if n.get("stale_warning") else "")
            lis += (f'<li style="font-size:12.5px;line-height:1.6">'
                    f'<b>{_esc(n["topic"])}</b>'
                    f'<span class="feat-badge" style="background:#FAEEDA;color:#BA7517;'
                    f'border:1px solid #BA7517">third_party</span>'
                    f'<span class="feat-badge" style="background:#FAEEDA;color:#BA7517;'
                    f'border:1px solid #BA7517">{n.get("age_days", 0)} 天前</span><br>'
                    f'{_esc(n["content"])}<br>'
                    f'<span style="color:var(--sub)">来源：{_esc(n["source"])} · '
                    f'{_esc(n["date"])}'
                    + (f' · {_esc(n["url"])}' if n.get("url") else "")
                    + f'</span>{warn}</li>')
        body += f'<div class="card"><h3>已核实的补充信息</h3><ul class="kv">{lis}</ul></div>'
    if errs:
        body += ('<div class="card" style="border:1px solid #A32D2D;background:#FCEBEB">'
                 '<h3>有笔记未通过校验（已跳过）</h3><ul class="kv">'
                 + "".join(f'<li style="font-size:12.5px">#{_esc(e.get("index"))} '
                           f'{_esc(e.get("topic") or "")}：{_esc(e.get("error") or "")}</li>'
                           for e in errs) + '</ul></div>')
    return head + body


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    cl = build_checklist(from_city="成都", to_city="康定", days=3,
                         routes=[{"name": "G318 川藏南线", "fuel_density": "稀疏",
                                  "caution": "高原反应；垭口天气突变",
                                  "season": "5-6月、9-10月", "road": "国道为主"}])
    print(f"清单 {len(cl['items'])} 项，其中必须查 {cl['must_count']} 项")
    for it in cl["items"]:
        mark = "★" if it["must_check"] else " "
        print(f" {mark} [{it['kind']}] {it['topic']}  (query: {it['query']})")
    print()
    try:
        ingest_note("成都 高速准入", "可以上", "社交平台", "2027-01-01")
    except ValueError as e:
        print("未来日期被拦截:", e)
    n = ingest_note("康定 禁摩", "未查到禁摩区", "社交平台", "2026-09-20",
                    "https://example.com/x")
    print("落地记录:", json.dumps(n, ensure_ascii=False))
    print("HTML 长度:", len(enrichment_html(cl, [n])))
