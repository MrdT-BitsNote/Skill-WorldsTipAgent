#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_compact.py — 紧凑版小册子渲染器（仿赤峰 A5 卡片手册版式）

输入: plan.json（build_itinerary.py 输出）
输出: 单文件 HTML，零依赖
风格: 紧凑、不留白、无图、字段密集、A5 卡片手册节奏
"""
import sys, json, argparse, re
from pathlib import Path
from datetime import datetime, date

try:
    from rv_check import rv_html as _rv_html
except ImportError:
    _rv_html = None

try:
    from transit_links import generate as _transit_links, render_html as _transit_links_html
except ImportError:
    _transit_links = None
    _transit_links_html = None

try:
    from guide_digest import CATEGORY_ZH as _GUIDE_CAT_ZH, VOLATILE_CATS as _GUIDE_VOLATILE
except ImportError:
    _GUIDE_CAT_ZH = None
    _GUIDE_VOLATILE = None

_MODE_KEYS = ('高铁', '普铁', '飞机', '客车', '轮船', '自驾')

def _normalize_transit(transit: dict) -> dict:
    """把 plan_transit.py 的顶层中文 key 格式转为 render_compact 期望的 modes 列表。
    如果已有 modes 列表则原样返回（幂等）。
    特殊分支：scope='市内' 时，把 options（市内方式）转成 modes。"""
    if not transit:
        return {}
    if transit.get('modes'):
        return transit
    # 市内交通分支：options 是 [{"name":"地铁","how":"..."}...]，转成 modes
    if transit.get('scope') == '市内':
        modes = []
        for o in transit.get('options', []):
            modes.append({'mode': o.get('name', '?'), 'duration': '—',
                          'cost': '—', 'desc': o.get('how', '')})
        out = dict(transit)
        out['modes'] = modes
        return out
    modes = []
    for mk in _MODE_KEYS:
        m = transit.get(mk)
        if not m or not isinstance(m, dict):
            continue
        if mk == '高铁':
            modes.append({'mode': '高铁', 'duration': f'{m.get("hours", "?")}h',
                          'cost': f'¥{m.get("price_est", "?")}'})
        elif mk == '普铁':
            modes.append({'mode': '普铁', 'duration': f'{m.get("hours", "?")}h',
                          'cost': f'硬座¥{m.get("price_hard_seat_est", "?")} / 硬卧¥{m.get("price_hard_sleeper_est", "?")}'})
        elif mk == '飞机':
            disc = m.get('price_discount_est', {})
            lo = min(disc.values()) if disc else '?'
            hi = m.get('price_full_est', '?')
            modes.append({'mode': '飞机', 'duration': f'{m.get("hours_total_est", "?")}h(含地面)',
                          'cost': f'¥{lo}~{hi}'})
        elif mk == '客车':
            modes.append({'mode': '客车', 'duration': f'{m.get("hours", "?")}h',
                          'cost': f'¥{m.get("price_est", "?")}'})
        elif mk == '轮船':
            modes.append({'mode': '轮船', 'duration': f'{m.get("hours", "?")}h',
                          'cost': f'¥{m.get("price_est", "?")}'})
        elif mk == '自驾':
            modes.append({'mode': '自驾', 'duration': f'{m.get("hours", "?")}h',
                          'cost': f'约¥{m.get("cost_est", "?")}(油费+过路)'})
    out = dict(transit)
    out['modes'] = modes
    rec = transit.get('recommend', '')
    if rec:
        out['recommend'] = rec.replace('(默认)', '').replace('机票参考', '飞机')
    return out

# === 通用辅助 ===
def esc(s):
    if s is None: return ''
    s = str(s)
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def md_inline(s):
    """极简 markdown 加粗：把 **text** 渲染为 <b>text</b>"""
    if not s: return ''
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', str(s))

# === 数据适配 ===
def pick(plan, *keys, default=''):
    for k in keys:
        v = plan.get(k)
        if v is not None and v != '':
            return v
    return default

# === 段落 ===
def section_no(n): return f'<span class="sec-no">§ {n:02d}</span>'

# === 明确通行方式识别 ===
# 规则：用户已明确通行方式（摩旅/自驾/骑行/指定航班等）→ 只渲染该方式的通行卡，
#       不再出 6 方式比选表；未明确时才比选公共交通。
_SELF_DRIVEN = {'moto': '摩托', 'roadtrip': '自驾', 'cycling': '骑行', 'rv': '房车'}

def _explicit_mode(plan: dict, transit: dict = None):
    """返回明确通行方式 key：moto / roadtrip / cycling / flight / hsr / None"""
    style = (plan.get('style') or '').lower()
    if style in _SELF_DRIVEN:
        return style
    # 编排层显式标注（transit.explicit 或 plan.transport_explicit）
    for src in (transit or {}, plan):
        ex = src.get('explicit') or src.get('transport_explicit')
        if ex:
            ex = str(ex).lower()
            if ex in ('moto', '摩旅', '摩托', '摩托车'):
                return 'moto'
            if ex in ('roadtrip', '自驾', '汽车'):
                return 'roadtrip'
            if ex in ('cycling', '骑行', '自行车'):
                return 'cycling'
            if ex in ('flight', '飞机', '航班'):
                return 'flight'
            if ex in ('hsr', '高铁', '火车'):
                return 'hsr'
    # prefs 文本里出现明确方式词
    for p in (plan.get('prefs') or []):
        txt = (p.get('内容', '') if isinstance(p, dict) else str(p)) + (p.get('主题', '') if isinstance(p, dict) else '')
        for kw, m in [('摩托', 'moto'), ('机车', 'moto'), ('自驾', 'roadtrip'), ('骑行', 'cycling'),
                      ('自行车', 'cycling'), ('坐飞机', 'flight'), ('飞机', 'flight'), ('高铁', 'hsr')]:
            if kw in txt:
                return m
    return None

_LIGHT_LABEL = {'green': ('绿', 'ok'), 'yellow': ('黄', 'warn'), 'red': ('红', 'red'), 'grey': ('灰', '')}

def _gate_row(card: dict) -> str:
    light = card.get('light', 'grey')
    zh, cls = _LIGHT_LABEL.get(light, ('灰', ''))
    detail = esc(card.get('detail', ''))
    action = esc(card.get('action', ''))
    return (f'<div class="gate"><div class="l {cls}"></div><div class="t">'
            f'<b>{esc(card.get("title", ""))}</b> <span class="tag {cls}">{zh}</span>'
            f'<div class="d">{detail}</div>'
            + (f'<div class="d">→ {action}</div>' if action else '')
            + '</div></div>')

def _moto_transit_html(plan: dict, transit: dict, special) -> str:
    """明确方式 = 摩托：只出摩托通行卡（五项门禁 + 禁摩提示 + 一行应急备选）"""
    moto = plan.get('moto', {}) or {}
    cards = moto.get('cards', []) or []
    verdict = moto.get('verdict', '')
    blocked = moto.get('blocked', False)
    r, y, g, gy = moto.get('red', 0), moto.get('yellow', 0), moto.get('green', 0), moto.get('grey', 0)
    h = ['<section class="sec" id="sec2">', section_no(2), '<h2>怎么去<span class="en">Getting There</span></h2>']
    h.append('<p class="sub-en">已明确通行方式：摩托 · 按摩旅方案执行</p>')
    dist = (transit or {}).get('distance_km')
    provinces = ' / '.join(moto.get('provinces', []) or [])
    h.append(f'<p><b>🛵 摩托独行</b> · {esc(plan.get("origin", ""))} → {esc("、".join(plan.get("destinations", []) or []))}'
             + (f' · 直线 <b>{dist} km</b>' if dist else '')
             + (f' · 途经 {esc(provinces)}' if provinces else '')
             + ' · 以国道/省道为主</p>')
    # 逐日骑行量
    for d in (plan.get('plan') or []):
        act = d.get('active', {}) or {}
        if act.get('km'):
            h.append(f'<div class="bar"><span class="lbl">D{d.get("day","?")}</span>'
                     f'<span class="val">{esc(d.get("label",""))} · 骑行 <b>{act.get("km")} km</b> · {esc(d.get("total_hours",""))}h</span></div>')
    if cards:
        h.append('<h4>🔧 摩旅五项门禁</h4>')
        verdict_txt = {'clear': '可出行', 'caution': '可行但需注意', 'blocked': '不可行'}.get(verdict, verdict)
        h.append(f'<p style="margin:2px 0 4px"><span class="tag {"red" if blocked else "warn" if verdict=="caution" else "ok"}">{esc(verdict_txt)}</span>'
                 f'<span style="font-size:12.5px;color:var(--sub)">　红 {r} · 黄 {y} · 绿 {g} · 灰 {gy}</span></p>')
        for c in cards:
            h.append(_gate_row(c))
    # 禁摩/限行特别提示（来自 special，原为 dict 需结构化渲染）
    sp_items = []
    if isinstance(special, dict):
        sp_items = special.get('items', []) or []
        sp_title = special.get('title', '通行特别提示')
    elif isinstance(special, list):
        sp_items = special
        sp_title = '通行特别提示'
    if sp_items:
        h.append(f'<h4>⚠️ {esc(sp_title)}</h4>')
        for it in sp_items:
            if isinstance(it, dict):
                topic = it.get('主题') or it.get('title') or ''
                content = it.get('内容') or it.get('text') or ''
                if content:
                    h.append(f'<em class="warn">{esc(content)}</em>')
            elif it:
                h.append(f'<em class="warn">{esc(it)}</em>')
    # 一行应急备选（不展开公共交通比选表）
    if transit and transit.get('modes'):
        alts = [m for m in transit['modes'] if m.get('mode') in ('高铁', '普铁', '飞机')]
        if alts:
            parts = ' · '.join(f'{esc(m.get("mode",""))} {esc(m.get("cost",""))}/{esc(m.get("duration",""))}' for m in alts[:2])
            h.append(f'<em class="note">应急备选（摩托受阻时）：{parts}</em>')
    h.append('</section>')
    return ''.join(h)

def _single_mode_transit_html(plan: dict, transit: dict, mode: str) -> str:
    """明确方式 = 飞机/高铁：只出该方式一张卡 + 一行备选"""
    label = {'flight': '飞机', 'hsr': '高铁'}.get(mode, '飞机')
    h = ['<section class="sec" id="sec2">', section_no(2), '<h2>怎么去<span class="en">Getting There</span></h2>']
    h.append(f'<p class="sub-en">已明确通行方式：{label} · 按该方式执行</p>')
    dist = (transit or {}).get('distance_km')
    h.append(f'<p><b>{"✈️" if mode == "flight" else "🚄"} {label}</b> · {esc(plan.get("origin", ""))} → {esc("、".join(plan.get("destinations", []) or []))}'
             + (f' · 直线 <b>{dist} km</b>' if dist else '') + '</p>')
    if transit and transit.get('modes'):
        pick = next((m for m in transit['modes'] if label in (m.get('mode') or '')), None)
        if pick:
            h.append(f'<div class="bar"><span class="lbl">{label}</span><span class="val">时长 <b>{esc(pick.get("duration","—"))}</b> · 票价 <b>{esc(pick.get("cost","—"))}</b></span></div>')
        others = [m for m in transit['modes'] if m is not pick and m.get('mode') in ('高铁', '普铁', '飞机')]
        if others:
            parts = ' · '.join(f'{esc(m.get("mode",""))} {esc(m.get("cost",""))}/{esc(m.get("duration",""))}' for m in others[:2])
            h.append(f'<em class="note">备选：{parts}</em>')
    h.append('<em class="tip">💡 票价均为估算，以 12306 / 航司官网实时为准；节假日提前 2-4 周订通常最优。</em>')
    h.append('</section>')
    return ''.join(h)

# === HTML 模板 ===
HTML_TPL = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root{{--bg:#F7F4EE;--card:#FFF;--ink:#0F0F0F;--sub:#5A5A5A;--line:#D9D2C2;--line2:#B7AE99;--accent:#0F4C3A;--warn:#A85A00;--ok:#1B7C3F;--red:#B91C1C;--mono:ui-monospace,Menlo,Consolas,monospace;--font:-apple-system,BlinkMacSystemFont,\"PingFang SC\",\"Helvetica Neue\",\"Microsoft YaHei\",sans-serif}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--font);background:var(--bg);color:var(--ink);font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:780px;margin:0 auto;padding:0 20px}}
a{{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--line2)}}
a:hover{{border-color:var(--accent)}}
h1,h2,h3,h4{{font-weight:700;letter-spacing:-.01em}}
h2{{font-size:18px;line-height:1.3;margin:0 0 6px}}
h3{{font-size:15px;line-height:1.3;margin:0 0 4px}}
h4{{font-size:13.5px;color:var(--ink);margin:8px 0 4px;font-weight:700}}
.sec-no{{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.12em;color:var(--accent);display:block;margin-bottom:4px}}
.sub-en{{font-size:11.5px;color:var(--sub);font-weight:500;letter-spacing:.04em;margin-bottom:8px}}
p{{font-size:13.5px;line-height:1.55;margin:0 0 4px}}
ul,ol{{margin:0 0 4px;padding-left:18px}}
li{{font-size:13.5px;line-height:1.5;margin-bottom:1px}}
li::marker{{color:var(--sub)}}
em.tip{{display:block;background:#FFFBE8;border-left:3px solid var(--warn);padding:6px 10px;margin:6px 0;font-size:12.5px;line-height:1.5;color:#5A3A00}}
em.warn{{display:block;background:#FFF0EE;border-left:3px solid var(--red);padding:6px 10px;margin:6px 0;font-size:12.5px;line-height:1.5;color:#7A1F12}}
em.note{{display:block;background:#F0F7F2;border-left:3px solid var(--ok);padding:6px 10px;margin:6px 0;font-size:12.5px;line-height:1.5;color:#1B5A2C}}
.tag{{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:3px;background:#E8E3D5;color:var(--ink);margin-right:4px;line-height:1.5;letter-spacing:.02em}}
.tag.ok{{background:#E1F2E6;color:#1B5A2C}}
.tag.warn{{background:#FCEFD3;color:#7A4A00}}
.tag.red{{background:#FBE3E0;color:#7A1F12}}
.tag.accent{{background:#E0EFE9;color:#0F4C3A}}
.kv{{display:grid;grid-template-columns:auto 1fr;gap:1px 12px;margin:4px 0}}
.kv .k{{color:var(--sub);font-size:12.5px;line-height:1.5;white-space:nowrap}}
.kv .v{{font-size:13px;line-height:1.5}}
hr{{border:0;border-top:1px dashed var(--line);margin:8px 0}}
.bar{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:4px 0 6px}}
.bar .lbl{{font-size:11.5px;color:var(--sub);font-family:var(--mono);font-weight:600;letter-spacing:.04em;min-width:54px}}
.bar .val{{font-size:13px}}
.solid{{border-top:1px solid var(--line);margin:14px 0 0}}
.tline{{display:grid;grid-template-columns:46px 1fr;gap:8px;margin:4px 0;padding:3px 0;border-bottom:1px dotted var(--line)}}
.tline:last-child{{border-bottom:0}}
.tline .t{{font-family:var(--mono);font-weight:700;font-size:12px;color:var(--accent);padding-top:1px}}
.tline .b{{font-size:13px;line-height:1.5}}
.tline .b .nm{{font-weight:700}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:6px 0}}
.tbl{{width:100%;border-collapse:collapse;font-size:12.5px;margin:4px 0}}
.tbl th,.tbl td{{padding:3px 6px;text-align:left;border-bottom:1px solid var(--line)}}
.tbl th{{color:var(--sub);font-weight:600;font-size:11.5px;background:#EFEAD8}}
.tbl td.r{{text-align:right;font-variant-numeric:tabular-nums}}
.lead{{font-size:15px;line-height:1.55;color:var(--ink);font-weight:500}}
.hero{{padding:24px 0 14px;border-bottom:1.5px solid var(--ink)}}
.hero h1{{font-size:30px;line-height:1.1;letter-spacing:-.025em;margin-bottom:4px}}
.hero .meta{{font-size:12.5px;color:var(--sub);display:flex;flex-wrap:wrap;gap:8px 14px;margin-top:8px}}
.hero .meta b{{color:var(--ink);font-weight:700}}
.sec{{padding:14px 0 12px;border-bottom:1px solid var(--line)}}
.sec.tight{{padding:10px 0 8px}}
.sec.bright{{background:#FFFCF3;margin:0 -20px;padding:14px 20px;border-bottom:1px solid var(--line)}}
.sec h2 .en{{font-size:11.5px;color:var(--sub);font-weight:500;letter-spacing:.04em;margin-left:6px}}
.day{{display:grid;grid-template-columns:42px 1fr;gap:10px;margin:8px 0}}
.day .no{{font-family:var(--mono);font-weight:800;font-size:22px;color:var(--accent);line-height:1;padding-top:2px}}
.day .body b{{font-size:14px}}
.day .body .d-meta{{font-size:12px;color:var(--sub);margin:2px 0 4px}}
.slot{{display:grid;grid-template-columns:42px 1fr;gap:6px;padding:3px 0;font-size:12.5px;border-bottom:1px dotted var(--line2)}}
.slot:last-child{{border-bottom:0}}
.slot .ts{{font-family:var(--mono);color:var(--accent);font-weight:700}}
.slot .nm b{{font-weight:700}}
.slot .nm .du{{color:var(--sub);font-size:11.5px;margin-left:4px}}
.callout{{padding:8px 12px;border:1px solid var(--line);background:#FFFCF3;font-size:12.5px;line-height:1.55;margin:6px 0}}
.pack-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:6px 0}}
.pack-card{{border:1px solid var(--line);border-radius:8px;padding:7px 10px;background:#FFF}}
.pack-card.full{{grid-column:1 / -1}}
.pack-card h5{{font-size:12.5px;font-weight:700;color:var(--accent);margin:0 0 3px;letter-spacing:.02em}}
.pack-card .items{{font-size:12.5px;line-height:1.65;color:var(--ink)}}
.pack-card .items i{{font-style:normal;color:var(--sub);padding:0 3px}}
@media(max-width:640px){{.pack-grid{{grid-template-columns:1fr}}}}
.gate{{display:grid;grid-template-columns:18px 1fr;gap:6px 8px;align-items:start;margin:4px 0;font-size:13px}}
.gate .l{{width:9px;height:9px;border-radius:50%;margin-top:5px}}
.gate .l.ok{{background:var(--ok)}} .gate .l.warn{{background:var(--warn)}} .gate .l.red{{background:var(--red)}} .gate .l.gray{{background:#999}}
.gate .t b{{font-weight:700}}
.gate .t .d{{color:var(--sub);font-size:12.5px;line-height:1.5}}
footer{{padding:18px 0 30px;font-size:11.5px;color:var(--sub);text-align:center;border-top:1px solid var(--line);margin-top:14px}}
.toc{{padding:10px 0;border-bottom:1px solid var(--line)}}
.toc h4{{font-size:11.5px;color:var(--sub);font-weight:600;font-family:var(--mono);letter-spacing:.06em;margin-bottom:4px}}
.toc ul{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:1fr 1fr;gap:1px 16px}}
.toc li{{font-size:12.5px;line-height:1.4}}
.toc a{{border:0;color:var(--ink)}}
.toc a:hover{{color:var(--accent)}}
@media(max-width:640px){{.row{{grid-template-columns:1fr}}.toc ul{{grid-template-columns:1fr}}.day{{grid-template-columns:32px 1fr}}.day .no{{font-size:18px}}.hero h1{{font-size:24px}}}}
.g-supp{{margin:10px 0 2px;border-top:1px dashed var(--line2);padding-top:8px}}
.g-supp h4{{font-size:13.5px;margin:0 0 2px}}
.g-supp-note{{font-size:11.5px;color:var(--sub);margin:0 0 6px}}
.g-group{{font-size:12px;font-weight:700;color:var(--accent);margin:7px 0 2px;letter-spacing:.02em}}
.g-list{{margin:0;padding-left:16px}}
.g-list li{{font-size:12.5px;line-height:1.55;margin:3px 0;list-style:disc}}
.g-src{{font-size:11px;color:var(--sub)}}
</style>
</head>
<body>
<div class="wrap">
{HERO}
{TOC}
{ROUTE_OVERVIEW}
{TRANSIT}
{DAY_BY_DAY}
{SEASON}
{PHOTO}
{STAY}
{BUDGET}
{PACKING}
{SAFETY}
{COLD}
</div>
<footer>
<div class="wrap">
本报告由 WorldsTip 旅行指南小册子技能生成 · 票价与开放时间以官方当日为准 · 户外活动请量力而行
</div>
</footer>
</body>
</html>'''

_GUIDE_CAT_ORDER = ['ticket', 'queue', 'transit', 'food', 'pitfall', 'photo', 'tip']
_GUIDE_CAT_ZH_FALLBACK = {
    'ticket': '票务与预约', 'transit': '交通衔接', 'queue': '排队与时段',
    'food': '餐饮', 'pitfall': '避雷踩坑', 'photo': '机位与拍摄', 'tip': '实用贴士',
}


def _guide_stale_suffix(verified_on, category):
    """超期后缀：volatile 类（票务/排队/衔接）>30 天、体验类 >90 天 → 需出行前复核。"""
    try:
        d = datetime.strptime(str(verified_on), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return ''
    days = (date.today() - d).days
    volatile = category in (_GUIDE_VOLATILE or set())
    limit = 30 if volatile else 90
    return ' ·需出行前复核' if days > limit else ''


def _guide_supplement_html(research):
    """§10 条件子块「攻略核验 · 数据补充」：渲染 research.json 的 ugc 键。
    无有效条目返回 ''（无数据不渲染）。只呈现来源名称+核验日期+要点，不外露任何链接。"""
    if not research or not isinstance(research, dict):
        return ''
    ugc = research.get('ugc') or []
    items = [u for u in ugc
             if isinstance(u, dict) and u.get('text') and u.get('source') and u.get('verified_on')]
    if not items:
        return ''
    cat_zh = _GUIDE_CAT_ZH or _GUIDE_CAT_ZH_FALLBACK
    groups = {}
    for u in items:
        groups.setdefault(u.get('category') or 'tip', []).append(u)
    out = ['<div class="g-supp"><h4>· 攻略核验 · 数据补充</h4>',
           '<p class="g-supp-note">以下为公开攻略的研读沉淀，已交叉核验并标注来源与核验日期；'
           '价格 / 开放 / 排队类信息出行前请再复核。</p>']
    for cat in sorted(groups, key=lambda c: _GUIDE_CAT_ORDER.index(c) if c in _GUIDE_CAT_ORDER else 99):
        out.append(f'<div class="g-group">{esc(cat_zh.get(cat, cat))}</div><ul class="g-list">')
        for u in groups[cat]:
            src = u.get('src') or u.get('confidence') or '检索'
            if src == '官方':
                badge, cls = '官方', 'ok'
            elif u.get('multi'):
                badge, cls = '多源印证', 'accent'
            else:
                badge, cls = '检索', ''
            where = u.get('where') or ''
            text = f"【{where}】{u['text']}" if where and where != '全程' else u['text']
            out.append(
                f'<li><span class="tag {cls}">{badge}</span>{esc(text)}'
                f'<span class="g-src">— {esc(u.get("source", ""))} · 核验于 '
                f'{esc(u.get("verified_on", ""))}{_guide_stale_suffix(u.get("verified_on"), cat)}</span></li>')
        out.append('</ul>')
    out.append('</div>')
    return ''.join(out)


def render(plan: dict, title: str, transit: dict = None, research: dict = None) -> str:
    transit = _normalize_transit(transit) if transit else None
    origin = pick(plan, 'origin', 'from', default='出发地')
    dest = '、'.join(plan.get('destinations', []) or ['目的地'])
    days = plan.get('days', '?')
    people = plan.get('people', '1')
    composition = plan.get('composition', '独自一人')
    party = plan.get('party', {}) or {}
    style = plan.get('style_label') or plan.get('style', '')
    intensity = plan.get('intensity', '?')
    season = plan.get('season', '')
    tone = plan.get('tone', []) or []
    budget = plan.get('budget', {}) or {}
    gear = plan.get('gear', {}) or {}
    stay_plan = plan.get('stay', {}) or {}
    audience = plan.get('audience', {}) or {}
    safety = plan.get('safety', {}) or {}
    cold = plan.get('cold', []) or []
    day_plan = plan.get('plan', []) or []
    special = plan.get('special')

    # === HERO ===
    total_pp = budget.get('per_person_total') or budget.get('group_total') or 0
    intensity_label = {1: '轻', 2: '轻', 3: '中', 4: '中', 5: '高'}.get(intensity, '中')
    hero = f'''<div class="hero">
<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px">
  <span class="sec-no" style="margin:0">WORLDSTIP · 旅行指南小册子</span>
  <span class="tag">{season}</span>
  <span class="tag accent">强度 {intensity} · {intensity_label}</span>
</div>
<h1>{esc(title)}</h1>
<p class="lead">{esc(origin)} → <b>{esc(dest)}</b> · {days} 天 · {esc(composition)} · 节奏画像「{esc(style)}」{' · ' + esc(party.get('label','')) if party.get('label') else ''}</p>
<div class="meta">
  <span>人均预算 <b>¥{int(total_pp):,}</b></span>
  <span>住宿 {esc(budget.get('lodging_level','—'))} / 餐饮 {esc(budget.get('food_level','—'))}</span>
  <span>房间 {esc(stay_plan.get('rooms','?'))} 间 · {esc(budget.get('nights','?'))} 晚</span>
  {'<span>费用口径 ' + esc(budget.get('split_mode','')) + '</span>' if budget.get('split_mode') else ''}
</div>
</div>'''

    # === TOC ===
    toc_items = [
        ('1', '路线总览'), ('2', '怎么去'),
        ('3', '逐日动线'), ('4', '季节与气候'),
        ('5', '美景拍摄'), ('6', '住宿'),
        ('7', '预算速查'), ('8', '行前清单'),
        ('9', '安全与应急'), ('10', '出发前多知道一点'),
    ]
    toc = '<div class="toc"><h4>CONTENTS</h4><ul>' + ''.join(f'<li><a href="#sec{n}">§{n} {esc(t)}</a></li>' for n, t in toc_items) + '</ul></div>'

    # === 路线总览 ===
    overview = ['<section class="sec" id="sec1">', section_no(1), '<h2>路线总览<span class="en">Route & Rhythm</span></h2>']
    overview.append(f'<p class="sub-en">每天怎么走、用时多少、强度分布</p>')
    for d in day_plan:
        dno = d.get('day', '?')
        lbl = d.get('label', '')
        city = d.get('city', '')
        hrs = d.get('total_hours', '')
        active = d.get('active', {}) or {}
        slots = d.get('slots', []) or []
        first_slot = slots[0] if slots else {}
        overview.append(f'<div class="day"><div class="no">D{dno}</div><div class="body">')
        overview.append(f'<b>{esc(lbl)}</b> · {esc(city)} · {hrs}h')
        if active.get('km'):
            overview.append(f' <span class="tag accent">{esc(active.get("label","体力"))} {active.get("km")}km</span>')
        if d.get('note'):
            overview.append(f'<div class="d-meta">{esc(d["note"])}</div>')
        if first_slot.get('note'):
            overview.append(f'<em class="tip">📌 {esc(first_slot["note"])}</em>')
        overview.append('</div></div>')
    if day_plan:
        hours_total = sum(d.get('total_hours', 0) or 0 for d in day_plan)
        overview.append(f'<p style="margin-top:6px"><b>总用时</b>：{hours_total:.1f} 小时（含停留，不含长途）</p>')
    if audience:
        al = audience.get('label','')
        focus = audience.get('focus', [])
        if focus:
            overview.append(f'<em class="note">画像「{esc(al)}」· 关注点：{" · ".join(esc(x) for x in focus)}</em>')
    overview.append('</section>')

    # === 怎么去 ===
    # 规则：有明确通行方式 → 只出该方式通行卡；未明确 → 才出公共交通比选表
    explicit = _explicit_mode(plan, transit)
    if explicit == 'moto':
        transit_html = [_moto_transit_html(plan, transit or {}, special)]
    elif explicit in ('flight', 'hsr'):
        transit_html = [_single_mode_transit_html(plan, transit or {}, explicit)]
    else:
        transit_html = ['<section class="sec" id="sec2">', section_no(2), '<h2>怎么去<span class="en">Getting There</span></h2>']
        scope = (transit or {}).get('scope', '')
        need_confirm = (transit or {}).get('recommend') == '需确认交通方式'
        if scope == '市内':
            # 同城/市内出行：只推市内交通，不推城际高铁/飞机
            transit_html.append('<p class="sub-en">同城/市内出行 · 按市内交通推荐</p>')
            if transit and transit.get('modes'):
                transit_html.append('<table class="tbl"><thead><tr><th>方式</th><th>说明</th></tr></thead><tbody>')
                for m in transit['modes']:
                    desc = m.get('desc', '')
                    transit_html.append(f'<tr><td>{esc(m.get("mode",""))}</td><td>{esc(desc)}</td></tr>')
                transit_html.append('</tbody></table>')
            if transit and transit.get('reason'):
                transit_html.append(f'<em class="tip">💡 {esc(transit["reason"])}</em>')
            if transit and transit.get('distance_km'):
                transit_html.append(f'<p>直线距离 <b>{transit["distance_km"]} km</b>（属市内，无需城际交通）</p>')
        elif need_confirm:
            # 坐标缺失/距离未知：不默认推高铁飞机，先向用户确认市内 or 跨城
            transit_html.append('<p class="sub-en">通行方式待确认 · 距离未知，不默认推荐高铁飞机</p>')
            if transit and transit.get('reason'):
                transit_html.append(f'<em class="tip">💡 {esc(transit["reason"])}</em>')
            if transit and transit.get('note'):
                transit_html.append(f'<em class="note">⚠️ {esc(transit["note"])}</em>')
        elif transit and transit.get('modes'):
            transit_html.append('<p class="sub-en">未指定通行方式 · 公共交通比选，票价时长均为估算</p>')
            modes = transit['modes'][:6]
            rec = transit.get('recommend', '')
            transit_html.append('<table class="tbl"><thead><tr><th>方式</th><th>时长</th><th>票价</th><th>推荐度</th></tr></thead><tbody>')
            for m in modes:
                tag = '<span class="tag accent">推荐</span>' if m.get('mode')==rec else ''
                transit_html.append(f'<tr><td>{esc(m.get("mode",""))}</td><td>{esc(m.get("duration","—"))}</td><td>{esc(m.get("cost","—"))}</td><td>{tag}</td></tr>')
            transit_html.append('</tbody></table>')
            if transit.get('reason'):
                transit_html.append(f'<em class="tip">💡 {esc(transit["reason"])}</em>')
            if transit.get('distance_km'):
                transit_html.append(f'<p>直线距离 <b>{transit["distance_km"]} km</b></p>')
        else:
            # 无 transit 数据：不硬推高铁飞机，提示确认交通方式
            transit_html.append('<p>通行方式待确认 · 距离与交通信息缺失，请先确认目的地是市内/近郊还是跨城，再决定推荐公交地铁还是高铁飞机。</p>')
        # 12306/航司实时查询深链
        if _transit_links and _transit_links_html and origin != '出发地':
            dest_first = (plan.get('destinations') or [''])[0]
            if dest_first:
                try:
                    links = _transit_links(origin, dest_first, plan.get('start_date'))
                    transit_html.append(_transit_links_html(links))
                except Exception:
                    pass
        transit_html.append('</section>')

    # === 房车后勤自检（仅 rv 画像或用户声明房车时） ===
    rv_data = plan.get('rv')
    if rv_data and _rv_html:
        dest_str = '、'.join(plan.get('destinations', []))
        rv_html_str = _rv_html(rv_data, dest_str)
        if rv_html_str:
            transit_html.append(rv_html_str)

    # === 逐日动线 ===
    day_html = ['<section class="sec" id="sec3">', section_no(3), '<h2>逐日动线<span class="en">Day by Day</span></h2>']
    day_html.append('<p class="sub-en">时间锚点 + 节点说明 + 关键提示</p>')
    for d in day_plan:
        dno = d.get('day', '?')
        lbl = d.get('label', '')
        city = d.get('city', '')
        hrs = d.get('total_hours', '')
        active = d.get('active', {}) or {}
        slots = d.get('slots', []) or []
        day_html.append(f'<div style="margin:10px 0 8px"><b>D{dno} · {esc(lbl)}</b> · {esc(city)} · {esc(hrs)}h')
        if active.get('km'):
            day_html.append(f' <span class="tag accent">{esc(active.get("label","体力"))} {active.get("km")}km</span>')
        day_html.append('</div>')
        for s in slots:
            ts = s.get('start', '—')
            nm = s.get('name', '')
            h = s.get('hours', '')
            note = s.get('note', '')
            day_html.append(f'<div class="slot"><div class="ts">{esc(ts)}</div><div class="nm"><b>{esc(nm)}</b> <span class="du">{h}h</span>')
            if note:
                day_html.append(f'<br>{esc(note)}')
            day_html.append('</div></div>')
        if d.get('note'):
            day_html.append(f'<em class="tip">💡 {esc(d["note"])}</em>')
    day_html.append('</section>')

    # === 季节 ===
    season_html = ['<section class="sec bright" id="sec4">', section_no(4), '<h2>季节与气候<span class="en">Season & Climate</span></h2>']
    season_html.append(f'<p><b>{esc(season)}</b> 季 · 季节结论绑定出行日期 · 出行前 3 天务必复核实时天气预报</p>')
    season_text_map = {
        '春': '春（3-5 月）· 草原泛青、杜鹃初绽、江南烟雨；华南已入雨季',
        '夏': '夏（6-8 月）· 草原与海岛旺季、避暑与摄影窗口；台风/雷暴多发',
        '秋': '秋（9-11 月）· 草原金黄、江南桂花、稻田金黄；最佳综合季节',
        '冬': '冬（12-2 月）· 雪景与雾凇、温泉旺季；部分景区歇业、路况复杂',
    }
    season_html.append(f'<p>{esc(season_text_map.get(season, "请查实时天气预报"))}</p>')
    if tone:
        season_html.append(f'<p><b>本季关注</b>：{" · ".join(esc(t) for t in tone)}</p>')
    season_html.append('</section>')

    # === 美景拍摄 ===
    photo_html = ['<section class="sec" id="sec5">', section_no(5), '<h2>美景拍摄指南<span class="en">Photo Guide</span></h2>']
    photo_html.append('<p class="sub-en">时机 / 机位 / 参数 速查</p>')
    photo_html.append('<h4>🌅 日出日落 · 黄金时刻</h4>')
    photo_html.append('<ul><li><b>日出</b>前 40-60 min 到场（占机位 + 等晨雾）；蓝调时刻从日出前 30 min 开始</li><li><b>黄金时刻</b> = 日出后/日落前 30-40 min，光线低角度、色温暖、影子长</li><li>蓝调时刻城市灯光与天光平衡最出片；日落后 15-25 min 的「烧云」窗口常有晚霞二次高潮</li><li>前一天查好：日出/日落精确时刻 + 方位角（莉景天气 / Windy App）</li></ul>')
    photo_html.append('<h4>📷 参数起手值</h4>')
    photo_html.append('<ul><li>光圈优先 A 档：<b>f/8-f/11</b>（大场景风光保证前后景深）</li><li>ISO 100-400（保画质）；测光对天空亮部减 0.3-0.7 EV 防过曝</li><li>太阳入画面强烈建议渐变灰 GND 滤镜或 RAW 后期拉回（手机用 HDR 模式）</li><li>拍剪影：对天空亮部点测光+锁定，主体自然成剪影</li></ul>')
    photo_html.append('<h4>🎒 装备速查</h4>')
    photo_html.append('<ul><li>机身 + 主力广角（星空/风光）与中长焦（压缩/日出特写）各一支</li><li>滤镜三件套：CPL 偏振 / GND 渐变 / ND 减光</li><li>备用电池 ×2-3（低温掉电 50%+，贴身保暖）+ 大容量存储卡</li><li>头灯红光模式、镜头布（水汽/雾凇必备）、防雨罩</li><li>手机党核心：小型三脚架 + 专业拍摄 App 即可完成 80% 题材</li></ul>')
    photo_html.append('</section>')

    # === 住宿 ===
    stay_html = ['<section class="sec" id="sec6">', section_no(6), '<h2>住宿安排<span class="en">Where to Stay</span></h2>']
    rooms = stay_plan.get('rooms', '?')
    nights = budget.get('nights', '?')
    basis = budget.get('lodging_basis', '')
    room_types = stay_plan.get('room_types', [])
    stay_html.append(f'<p><b>{esc(rooms)} 间 · {esc(nights)} 晚</b> · {esc(basis)}</p>')
    if room_types:
        stay_html.append(f'<p>房型：{" · ".join(esc(rt) for rt in room_types)}</p>')
    if stay_plan.get('rationale'):
        stay_html.append(f'<p>选房逻辑：{esc(stay_plan["rationale"])}</p>')
    if stay_plan.get('tips'):
        stay_html.append('<h4>💡 住宿贴士</h4><ul>')
        for t in stay_plan['tips']:
            stay_html.append(f'<li>{esc(t)}</li>')
        stay_html.append('</ul>')
    # 通用选址建议
    stay_html.append('<h4>📍 选址速查</h4>')
    stay_html.append('<ul><li><b>景区/山脚</b> · 离次日游玩点近，节省路程，旺季必须提前订</li><li><b>高铁/机场沿线</b> · 出发前/返程后各住一晚，避开早班车与红眼航班</li><li><b>市区/商圈</b> · 餐饮交通便利，适合城市观光与美食</li><li><b>草原/海岛</b> · 必住一晚当地特色（蒙古包/海景房），看星空/听海浪</li></ul>')
    stay_html.append('</section>')

    # === 预算 ===
    budget_html = ['<section class="sec" id="sec7">', section_no(7), '<h2>预算速查<span class="en">Budget</span></h2>']
    budget_html.append(f'<p class="sub-en">基于距离的估算 · 实时票价查 12306 / 航司</p>')
    pp = budget.get('per_person', {}) or {}
    grp = budget.get('group', {}) or {}
    if pp or grp:
        budget_html.append('<table class="tbl"><thead><tr><th>分项</th><th class="r">最低/人</th><th class="r">常规/人</th><th class="r">占合计</th></tr></thead><tbody>')
        total_pp = sum((pp or grp).values()) or 1
        for k in (pp or grp):
            mn = (pp or grp).get(k, 0)
            pct = round(mn / total_pp * 100)
            budget_html.append(f'<tr><td>{esc(k)}</td><td class="r">¥{mn}</td><td class="r">¥{mn}</td><td class="r">{pct}%</td></tr>')
        budget_html.append(f'<tr><td><b>人均合计</b></td><td class="r" colspan="2"><b>¥{budget.get("per_person_total",0):,}</b></td><td class="r">100%</td></tr>')
        budget_html.append('</tbody></table>')
    budget_html.append('<h4>💡 节省口诀</h4><ul><li>住宿按<b>房间</b>而非按人数 · 单人订大床房最划算</li><li>餐饮：早餐住宿含 / 午晚餐本地老店更地道</li><li>门票：学生证/老年证/军官证带好可省；多日票通常比单日票划算</li><li>机票：周中+提前 14 天是常见低洼；关注临近退票高峰</li></ul>')
    if budget.get('split_mode'):
        _sn = budget.get('split_note', '')
        budget_html.append(f'<em class="note">💑 陪伴结构「{esc(party.get("label",""))}」· 费用口径：<b>{esc(budget.get("split_mode"))}</b>'
                           + (f' · {esc(_sn)}' if _sn else '') + '</em>')
    budget_html.append('</section>')

    # === 行前清单（每类一张卡 · 2 列网格紧凑排布） ===
    pack_html = ['<section class="sec" id="sec8">', section_no(8), '<h2>行前清单<span class="en">Pre-trip Checklist</span></h2>']
    pack_html.append('<p class="sub-en">每类一张卡 · 出门前 1 天逐项打勾</p>')
    GEAR_CATS = [('证件', '🪪'), ('衣物', '👕'), ('防护', '🛡'), ('健康', '💊'), ('电子', '🔌')]
    if gear:
        pack_html.append('<div class="pack-grid">')
        for cat, icon in GEAR_CATS:
            items = gear.get(cat, []) or []
            if items:
                joined = '<i>·</i>'.join(esc(it) for it in items)
                pack_html.append(f'<div class="pack-card"><h5>{icon} {esc(cat)}</h5><div class="items">{joined}</div></div>')
        for cat, icon, full in [('画像重点', '🎯', True), ('季节性', '🗓', True)]:
            items = gear.get(cat, []) or []
            if items:
                joined = '<i>·</i>'.join(esc(it) for it in items)
                cls = 'pack-card full' if full else 'pack-card'
                pack_html.append(f'<div class="{cls}"><h5>{icon} {esc(cat)}</h5><div class="items">{joined}</div></div>')
        pack_html.append('</div>')
    else:
        pack_html.append('<div class="pack-grid">'
                         '<div class="pack-card"><h5>🪪 证件</h5><div class="items">身份证<i>·</i>护照（出境 6 个月以上有效期）</div></div>'
                         '<div class="pack-card"><h5>💰 财物</h5><div class="items">现金<i>·</i>银行卡<i>·</i>主流移动支付</div></div>'
                         '<div class="pack-card"><h5>🔌 电子</h5><div class="items">充电器<i>·</i>充电宝（≤100Wh）<i>·</i>数据线</div></div>'
                         '<div class="pack-card"><h5>💊 健康</h5><div class="items">感冒药<i>·</i>肠胃药<i>·</i>创可贴<i>·</i>个人慢病药</div></div>'
                         '<div class="pack-card"><h5>👕 衣物</h5><div class="items">防滑鞋（已磨合）<i>·</i>雨具<i>·</i>保暖外套</div></div>'
                         '<div class="pack-card"><h5>🗺 其他</h5><div class="items">离线地图<i>·</i>轨迹备份</div></div>'
                         '</div>')
    pack_html.append('<h4>⏰ 行前时间线（倒排）</h4>')
    pack_html.append('<div class="tline"><div class="t">T-7d</div><div class="b">车票/机票开抢（12306 提前 15 天，热门线提前 7 天盯候补）· 住宿预订（旺季景区房紧俏）</div></div>')
    pack_html.append('<div class="tline"><div class="t">T-3d</div><div class="b">装备清单逐项打勾 · 车辆/摩托检查 · 保险购买（含高风险运动条款）</div></div>')
    pack_html.append('<div class="tline"><div class="t">T-1d</div><div class="b">充电满 · 现金零钱 · 药品分装 · 证件票据集中放贴身包 · 天气终查（恶劣预警触发 Plan B）</div></div>')
    pack_html.append('<div class="tline"><div class="t">D-day</div><div class="b">水与食物装包 · 雨具按预报 · 行程发给家人 · 家中水电燃气门窗检查</div></div>')
    pack_html.append('</section>')

    # === 安全与应急 ===
    safe_html = ['<section class="sec bright" id="sec9">', section_no(9), '<h2>安全与应急<span class="en">Safety & Emergency</span></h2>']
    safe_html.append('<p class="sub-en">只给本地化、可落地的最优解</p>')
    blocks = safety.get('blocks', []) or []
    if blocks:
        for b in blocks:
            ic = b.get('icon', '🛡')
            ti = b.get('title', '')
            items = b.get('items', []) or []
            safe_html.append(f'<h4>{ic} {esc(ti)}</h4><ul>')
            for it in items[:6]:
                safe_html.append(f'<li>{esc(it)}</li>')
            safe_html.append('</ul>')
    else:
        safe_html.append('<h4>🛡 通用安全</h4><ul><li>证件：身份证随身（购票/住宿实名刚需）</li><li>信息留底：行程单发给家人一份，含住宿地址与返程时间</li><li>紧急电话：110 报警 / 120 急救 / 122 交通</li><li>保险：户外活动买含高风险运动的意外险（一天期 5-15 元）</li><li>健康：慢性病患者带足药量+1 天余量；常备创可贴/肠胃药/退烧药</li><li>财物：大额现金分开放，手机挂绳防挤掉</li></ul>')
    # 陪伴结构（Party Type）安全与节奏叠加
    _pt_items = [x for x in (party.get('safety_focus', []) or []) + (party.get('pacing_focus', []) or []) if x]
    if _pt_items or party.get('pitfalls'):
        safe_html.append(f'<h4>👥 {esc(party.get("label","陪伴结构"))} · 专属提醒</h4><ul>')
        for it in _pt_items:
            safe_html.append(f'<li>{esc(it)}</li>')
        if party.get('pitfalls'):
            safe_html.append(f'<li>⚠ {esc(party.get("pitfalls"))}</li>')
        safe_html.append('</ul>')
    em = safety.get('emergency', {}) or {}
    if em:
        hot = em.get('hotline', [])
        safe_html.append(f'<h4>🆘 {esc(em.get("title", "应急预备"))}</h4>')
        if em.get('items'):
            safe_html.append('<ul>')
            for it in em['items'][:5]:
                safe_html.append(f'<li>{esc(it)}</li>')
            safe_html.append('</ul>')
        if hot:
            safe_html.append(f'<em class="warn">📞 关键电话：{" · ".join(esc(h) for h in hot)}</em>')
    safe_html.append('</section>')

    # === 冷知识 ===
    cold_html = ['<section class="sec" id="sec10">', section_no(10), '<h2>出发前多知道一点<span class="en">A Few Extra Things</span></h2>']
    if cold:
        for c in cold[:2]:
            for f in c.get('facts', []) or []:
                cold_html.append(f'<h4>· {esc(f.get("标题",""))}</h4>')
                cold_html.append(f'<p>{esc(f.get("内容",""))}</p>')
    else:
        cold_html.append('<h4>· 12306 捡漏三时段</h4><p>每日 6-7 点放前一日累积退票，22-23 点退票高峰，开车前 1-2 天放出预留票与限售解除后的余票。抢不到别急着买高价，多刷这几个点。</p>')
        cold_html.append('<h4>· 非热门线路也能打折</h4><p>部分普速与城际线路在淡季有折扣，最低可到 2 折左右。买票时点开"票价"旁的折扣提示，别只认全价。</p>')
        cold_html.append('<h4>· 区间限售会解除</h4><p>长途车常先限售起点到终点，中途站买不到；开车前 3-5 天限售解除。想买中间段，别太早放弃，临近再刷。</p>')
        cold_html.append('<h4>· 官方只认 12306</h4><p>第三方平台只是代购，退票、改签、候补都绕不开 12306。抢票软件容易被风控，关键票还是官方 App 最稳。</p>')
    supp = _guide_supplement_html(research)
    if supp:
        cold_html.append(supp)
    cold_html.append('</section>')

    # === 散心模式（relax/resort）：跳过 §02/§03/§08/§09 ===
    is_relax = (plan.get('style') or '').lower() in ('resort', 'relax')
    if is_relax:
        transit_html = ['']
        day_html = ['']
        pack_html = ['']
        safe_html = ['']
        toc_items = [
            ('1', '路线总览'), ('4', '季节与气候'),
            ('5', '美景拍摄'), ('6', '住宿'),
            ('7', '预算速查'), ('10', '出发前多知道一点'),
        ]
        toc = '<div class="toc"><h4>CONTENTS</h4><ul>' + ''.join(f'<li><a href="#sec{n}">§{n} {esc(t)}</a></li>' for n, t in toc_items) + '</ul></div>'

    return HTML_TPL.format(
        title=esc(title),
        HERO=''.join(hero),
        TOC=''.join(toc),
        ROUTE_OVERVIEW=''.join(overview),
        TRANSIT=''.join(transit_html),
        DAY_BY_DAY=''.join(day_html),
        SEASON=''.join(season_html),
        PHOTO=''.join(photo_html),
        STAY=''.join(stay_html),
        BUDGET=''.join(budget_html),
        PACKING=''.join(pack_html),
        SAFETY=''.join(safe_html),
        COLD=''.join(cold_html),
    )

# === main ===
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--transit', default=None)
    ap.add_argument('--research', default=None, help='research.json（ugc 攻略研读沉淀，渲染进 §10 攻略核验子块）')
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', required=True)
    args = ap.parse_args()
    plan = json.load(open(args.plan, encoding='utf-8'))
    transit = json.load(open(args.transit, encoding='utf-8')) if args.transit else None
    research = json.load(open(args.research, encoding='utf-8')) if args.research else None
    html = render(plan, args.title, transit, research)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html, encoding='utf-8')
    sections = ['hero', 'toc', '路线总览', '怎么去', '逐日动线', '季节', '拍摄', '住宿', '预算', '清单', '安全', '冷知识']
    if research and (research.get('ugc') or []):
        sections.append('攻略核验')
    print(f'✅ 已生成: {args.out}  (板块 {len(sections)} 个, {len(html.encode())//1024} KB)')

if __name__ == '__main__':
    main()
