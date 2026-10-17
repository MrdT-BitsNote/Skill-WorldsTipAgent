"""实时 UGC 可信度分层与渲染（学习 ycyliu 的小红书 UGC + 评论挖掘）。

设计原则（合规优先）：
- 零外部依赖、零站外链接；本模块只做「分层 / 排序 / 可视化」。
- 真实的联网抓取由宿主 Agent 在规划阶段用 WebSearch / WebFetch 完成
  （公开的小红书 / 大众点评等页面 + 评论区），结构化为 UGC 条目后传入。
- 若宿主已接入小红书 MCP，Agent 亦可调用，但本技能**不硬依赖**任何 MCP。
- 每条 UGC 必须带来源徽章与时效标签，票价 / 限流以官方实时为准。

可信度优先级（数值越大越可信）：
- 来源类型：实测(亲历/带图实证) > 平台(官方/平台公示) > 博客(搜索/自媒体)
- 渠道：小红书/大众点评 > 官方 > 搜索
- 时效：近 6 月 > 近 1 年 > 更早
- 体裁：评论区口碑 > 正文 > 搜索摘要
"""
from __future__ import annotations

import html

# ── 分层权重 ───────────────────────────────────────────────
SRC_TIER = {"实测": 3, "平台": 2, "博客": 1}
CHAN_TIER = {"小红书": 3, "大众点评": 3, "官方": 2, "搜索": 1}
RECENCY_TIER = {"近6月": 3, "近1年": 2, "更早": 1}

# 反馈类型 → 卡片配色类
KIND_CLASS = {
    "踩坑": "k-pit",
    "价格": "k-price",
    "体验": "k-exp",
    "贴士": "k-tip",
}


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def credibility_score(item: dict) -> int:
    """综合可信度评分（用于降序排序，越靠前越可信）。"""
    s = SRC_TIER.get(item.get("src"), 1)
    c = CHAN_TIER.get(item.get("chan"), 1)
    r = RECENCY_TIER.get(item.get("recency"), 1)
    comment_bonus = 1 if item.get("is_comment") else 0
    return s * 3 + c * 2 + r + comment_bonus


def badge_html(item: dict) -> str:
    """单条 UGC 的可信度徽章串。"""
    src = item.get("src", "博客")
    chan = item.get("chan", "搜索")
    rec = item.get("recency", "更早")
    cls = {"实测": "ugc-real", "平台": "ugc-plat", "博客": "ugc-blog"}.get(src, "ugc-blog")
    badges = [
        f'<span class="ugc-b {cls}">{esc(src)}</span>',
        f'<span class="ugc-b ugc-chan">{esc(chan)}</span>',
    ]
    if rec != "更早":
        badges.append(f'<span class="ugc-b ugc-rec">{esc(rec)}</span>')
    if item.get("is_comment"):
        badges.append('<span class="ugc-b ugc-cmt">评论</span>')
    return "".join(badges)


def render_ugc(items: list, title: str = "真实反馈 · 踩坑与实测", wrap_card: bool = True) -> str:
    """渲染 UGC 卡片区（items 应为已按可信度降序的列表）。

    wrap_card=True 时返回完整卡片（可独立嵌入）；
    wrap_card=False 时仅返回网格 + 脚注（供外部 sec_open 板块包裹，避免重复标题）。
    """
    if not items:
        return ""
    cards = []
    for it in items:
        kind = it.get("kind", "体验")
        kc = KIND_CLASS.get(kind, "k-exp")
        where = it.get("where", "")
        text = it.get("text", "")
        cards.append(
            f'<div class="ugc-card {kc}">'
            f'<div class="ugc-top"><span class="ugc-kind">{esc(kind)}</span>{badge_html(it)}</div>'
            f'<div class="ugc-where">📍 {esc(where)}</div>'
            f'<div class="ugc-text">{esc(text)}</div>'
            f"</div>"
        )
    grid = (
        f'<div class="ugc-grid">{"".join(cards)}</div>'
        f'<div class="sub" style="margin-top:8px">来源按「实测&gt;平台&gt;博客、评论&gt;正文、'
        f'近 6 月优先」分层；票价 / 限流以官方实时为准，评论区口碑仅供参考，'
        f'注意甄别广告与软文。</div>'
    )
    if not wrap_card:
        return grid
    return (
        f'<div class="card"><h3>📣 {esc(title)}</h3>{grid}</div>'
    )


def render_pitfalls(items: list, title: str = "避雷 · 别踩这些坑") -> str:
    """避雷专用渲染：筛选警示类 UGC（踩坑/避雷/避坑/价格陷阱），统一红系警示样式。

    复用了可信度分层与来源徽章；wrap_card=False 供外部 sec_open 板块包裹。
    """
    if not items:
        return ""
    cards = []
    for it in items:
        where = it.get("where", "")
        text = it.get("text", "")
        cards.append(
            f'<div class="ugc-card k-pit">'
            f'<div class="ugc-top"><span class="ugc-kind">⚠ 避雷</span>{badge_html(it)}</div>'
            f'<div class="ugc-where">📍 {esc(where)}</div>'
            f'<div class="ugc-text">{esc(text)}</div>'
            f"</div>"
        )
    return (
        f'<div class="ugc-grid">{"".join(cards)}</div>'
        f'<div class="sub" style="margin-top:8px">避雷条目来自真实反馈（实测/平台/评论），'
        f'票价与限流以官方实时为准；注意甄别广告与软文，别被滤镜带偏。</div>'
    )


def to_sorted(items: list) -> list:
    """按可信度降序排序，并补齐默认字段。"""
    out = []
    for it in items or []:
        it.setdefault("src", "博客")
        it.setdefault("chan", "搜索")
        it.setdefault("recency", "更早")
        it.setdefault("is_comment", False)
        out.append(it)
    out.sort(key=credibility_score, reverse=True)
    return out
