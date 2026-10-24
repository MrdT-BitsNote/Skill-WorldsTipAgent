# -*- coding: utf-8 -*-
"""
guide_list.py — 攻略检索清单的校验 / 去重 / 排序 / 渲染（v0.1.27 攻略检索模式配套）。

设计纪律（对应 SKILL.md「攻略检索模式」）：
- 输入为宿主 WebSearch/WebFetch（或外接 MCP）**真实检索结果**整理成的 JSON 数组；
  技能自身不抓取、不接 Cookie、不保存原文——本脚本只做「结论 + 来源 + 日期」三元组的落地校验。
- 链接必须来自真实检索结果，本脚本拒绝手拼/无法解析的 URL；
- **禁票务 / 预订 / 交易深链**：纯票务域名与交易路径（checkout/order/pay/cart/booking/ticket…）一律拒绝；
- 每条必填：title / url / source / verified_on(YYYY-MM-DD)；summary 与 confidence 可选但有默认；
- 时效：verified_on 超 30 天挂「临近过期」告警，超 90 天挂「参考价值待定」；
- 排序：match(匹配度 0-1) 降序 → confidence 档位降序 → verified_on 降序；按 URL 归一化去重；
- 输出：紧凑 Markdown 表格（仅对话交付用），空输入不崩。

用法：
    python scripts/guide_list.py guides.json            # 打印 Markdown 清单
    python scripts/guide_list.py guides.json --strict   # 有校验错误 / 无有效条目时退出码 1
    python scripts/guide_list.py - < guides.json         # 从 stdin 读
"""
import json
import re
import sys
from datetime import date, datetime
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

# --- 合规黑名单（内部逻辑，不面向用户点名品牌） -------------------------------
# 纯票务 / 售票域名子串（命中即拒：这类站点主用途就是交易）
# 售票站点域名通用标识（不点名任何具体平台）：命中即拒
BLOCKED_DOMAIN_SUBSTR = ("ticket", "piao", "12306")
# 交易 / 预订路径段（命中即拒：攻略可以是信息页，但不能是下单流）
BLOCKED_PATH_SEG = (
    "checkout", "order", "pay", "payment", "cart", "booking", "booknow",
    "book-now", "ticket", "tickets", "buy", "purchase", "reserve",
)
# 可信度档位 → 徽章与排序权重（官方 > 多源印证 > 孤例 > 待查）
CONF_RANK = {"official": 3, "verified": 2, "single": 1, "unknown": 0}
CONF_BADGE = {
    "official": "官方",
    "verified": "多源印证",
    "single": "个别反馈",
    "unknown": "待查·灰灯",
}
CONF_NOTE = {
    "official": "官方渠道信息",
    "verified": "≥2 个独立来源交叉印证",
    "single": "仅单一来源，标「个别反馈」",
    "unknown": "未核验，出行前以官方当日为准",
}
SOURCE_TYPE_ZH = {
    "official": "官方",
    "ugc_qa": "问答社区",
    "ugc_review": "点评平台",
    "ugc_social": "社交平台",
    "ugc_video": "短视频平台",
    "other": "其他公开来源",
}
REQUIRED = ("title", "url", "source", "verified_on")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)


def _norm_url(url):
    """归一化 URL 用于去重：小写 scheme/host、去 www.、去 utm_/spm 追踪参数、去尾斜杠。"""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(("utm_", "spm"))]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def check_url(url):
    """返回 (ok, reason)。ok=False 时 reason 说明拒绝类别（不点名具体品牌）。"""
    if not isinstance(url, str) or not URL_RE.match(url.strip()):
        return False, "URL 缺失或不是合法的 http(s) 链接（禁手拼/禁相对路径）"
    low = url.lower()
    host = (urlsplit(low).hostname or "")
    for tok in BLOCKED_DOMAIN_SUBSTR:
        if tok in host:
            return False, "票务/售票类站点链接，策略禁止（攻略清单只收信息类原文）"
    segs = [s for s in urlsplit(low).path.split("/") if s]
    for seg in segs:
        s = seg.split("?")[0].split(".")[0]
        if s in BLOCKED_PATH_SEG:
            return False, "交易/预订/下单路径链接，策略禁止（只收信息类攻略原文）"
    q = urlsplit(low).query.lower()
    if any(k in q for k in ("book=", "buy=", "order=", "pay=", "checkout")):
        return False, "URL 查询串含交易语义，策略禁止"
    return True, ""


def _parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_entry(e, idx):
    """校验单条，返回错误列表（空=通过）。"""
    errs = []
    if not isinstance(e, dict):
        return ["条目 %d：不是对象" % idx]
    for k in REQUIRED:
        v = e.get(k)
        if not isinstance(v, str) or not v.strip():
            errs.append("条目 %d：缺必填字段 %s" % (idx, k))
    url = e.get("url")
    if isinstance(url, str) and url.strip():
        ok, reason = check_url(url)
        if not ok:
            errs.append("条目 %d：%s" % (idx, reason))
    d = _parse_date(e.get("verified_on"))
    if isinstance(e.get("verified_on"), str) and e["verified_on"].strip() and d is None:
        errs.append("条目 %d：verified_on 需为 YYYY-MM-DD" % idx)
    if d and d > date.today():
        errs.append("条目 %d：verified_on 是未来日期（拒绝）" % idx)
    conf = e.get("confidence", "unknown")
    if conf not in CONF_RANK:
        errs.append("条目 %d：confidence 需为 official/verified/single/unknown" % idx)
    st = e.get("source_type", "other")
    if st not in SOURCE_TYPE_ZH:
        errs.append("条目 %d：source_type 非法（%s）" % (idx, st))
    m = e.get("match", 0.0)
    if not isinstance(m, (int, float)) or not (0.0 <= float(m) <= 1.0):
        errs.append("条目 %d：match 需为 0-1 之间的数" % idx)
    return errs


def dedup(entries):
    """按归一化 URL 去重，保留 match 更高的一条。"""
    best = {}
    order = []
    for e in entries:
        key = _norm_url(e["url"])
        if key not in best:
            best[key] = e
            order.append(key)
        else:
            if float(e.get("match", 0)) > float(best[key].get("match", 0)):
                best[key] = e
    return [best[k] for k in order]


def sort_entries(entries):
    return sorted(
        entries,
        key=lambda e: (
            -float(e.get("match", 0.0)),
            -CONF_RANK.get(e.get("confidence", "unknown"), 0),
            -( _parse_date(e.get("verified_on")) or date.min ).toordinal(),
        ),
    )


def staleness(d):
    """返回时效后缀：'' / ' ·⚠临近过期(>30天)' / ' ·⛔参考价值待定(>90天)'。"""
    if not d:
        return ""
    days = (date.today() - d).days
    if days > 90:
        return " ·⛔参考价值待定(>90天)"
    if days > 30:
        return " ·⚠临近过期(>30天)"
    return ""


def render_md(entries, today=None):
    """渲染紧凑 Markdown 表格（对话交付用）。空输入返回空串。"""
    if not entries:
        return ""
    today = today or date.today()
    rows = ["| # | 攻略（标题+可信度） | 来源 | 核验日期 | 一句话要点 |",
            "|---|---|---|---|---|"]
    for i, e in enumerate(entries, 1):
        conf = e.get("confidence", "unknown")
        badge = CONF_BADGE.get(conf, "待查·灰灯")
        d = _parse_date(e.get("verified_on"))
        date_cell = e.get("verified_on", "") + staleness(d)
        src_type = SOURCE_TYPE_ZH.get(e.get("source_type", "other"), "其他公开来源")
        title = str(e.get("title", "")).replace("|", "\\|").replace("\n", " ")
        summary = str(e.get("summary", "—")).replace("|", "\\|").replace("\n", " ")
        rows.append("| %d | [%s](%s) `%s` | %s（%s） | %s | %s |" % (
            i, title, e["url"].strip(), badge,
            str(e.get("source", "")).replace("|", "\\|"), src_type,
            date_cell, summary,
        ))
    return "\n".join(rows)


def load_entries(path):
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    data = json.loads(raw)
    if isinstance(data, dict) and "guides" in data:
        data = data["guides"]
    if not isinstance(data, list):
        raise ValueError("输入需为 JSON 数组（或含 guides 数组的对象）")
    return data


def main(argv):
    args = [a for a in argv[1:] if a != "--strict"]
    strict = "--strict" in argv
    if len(args) != 1:
        sys.stderr.write("usage: guide_list.py <guides.json|-> [--strict]\n")
        return 2
    try:
        raw_entries = load_entries(args[0])
    except Exception as ex:
        sys.stderr.write("读取失败：%s\n" % ex)
        return 2
    all_errs = []
    valid = []
    for i, e in enumerate(raw_entries, 1):
        errs = validate_entry(e, i)
        if errs:
            all_errs.extend(errs)
        else:
            valid.append(e)
    for line in all_errs:
        sys.stderr.write("[拒绝] %s\n" % line)
    entries = sort_entries(dedup(valid))
    if not entries:
        sys.stderr.write("无有效攻略条目（%d 条输入全部被拒或为空）\n" % len(raw_entries))
        return 1 if strict else 0
    print(render_md(entries))
    sys.stderr.write("\n共 %d 条有效攻略（输入 %d，拒绝 %d）\n" % (
        len(entries), len(raw_entries), len(raw_entries) - len(valid)))
    return 1 if (strict and all_errs) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
