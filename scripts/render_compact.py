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

# 路线图（行程级里程轴 / 线路级真轨迹）：缺坐标或缺线路则不出图，绝不画假形状
try:
    from route_viz import render_route_html as _route_html
except ImportError:
    _route_html = None

try:
    from guide_digest import CATEGORY_ZH as _GUIDE_CAT_ZH, VOLATILE_CATS as _GUIDE_VOLATILE
except ImportError:
    _GUIDE_CAT_ZH = None
    _GUIDE_VOLATILE = None

_MODE_KEYS = ('高铁', '普铁', '飞机', '客车', '轮船', '自驾')

# === 参考资料加载（poi / 必吃 等结构化数据，渲染时按需取用） ===
_REF_DIR = Path(__file__).resolve().parent.parent / "references"
def _load_ref(name: str) -> dict:
    """加载 references/ 下的 JSON；失败返回 {}（缺数据不渲染、不崩溃）。"""
    try:
        return json.load(open(_REF_DIR / name, encoding="utf-8"))
    except Exception:
        return {}

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

def cover_art(origin, dest, days, season=''):
    """离线内嵌 SVG 行程封面：暖色山脊 + 日出 + 行程节点。

    确定性生成，无外部图片、无网络请求、无空白占位。
    设计约束：单一强调色、紧凑条状（不做大留白）、暖色底、文字标注为示意插画。
    """
    o = esc(str(origin or '出发'))[:6]
    d = esc(str(dest or '目的地'))[:6]
    try:
        n = max(1, min(7, int(days)))
    except (TypeError, ValueError):
        n = 1
    step = 200 // max(n - 1, 1)
    dots = ''.join(
        '<circle cx="%d" cy="104" r="2.4" fill="#0F4C3A" opacity=".55"/>' % (260 + i * step)
        for i in range(n)
    )
    return (
        '<svg class="cover-art" viewBox="0 0 720 132" '
        'preserveAspectRatio="xMidYMid slice" role="img" '
        'aria-label="行程封面：%s 至 %s，%d 天">'
        '<defs><linearGradient id="wt-sky" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#FBE7CE"/>'
        '<stop offset="1" stop-color="#F7F4EE"/></linearGradient></defs>'
        '<rect width="720" height="132" fill="url(#wt-sky)"/>'
        '<circle cx="566" cy="44" r="22" fill="#E8A05B" opacity=".9"/>'
        '<path d="M0 96 L92 58 L168 92 L246 44 L332 98 L410 66 L500 100 '
        'L588 60 L672 98 L720 78 L720 132 L0 132 Z" fill="#C8D8C6" opacity=".85"/>'
        '<path d="M0 112 L110 84 L206 116 L300 82 L396 120 L492 90 L590 118 '
        'L680 88 L720 104 L720 132 L0 132 Z" fill="#0F4C3A" opacity=".78"/>'
        '<path d="M260 104 H460" stroke="#FFFFFF" stroke-width="1.6" '
        'stroke-dasharray="5 4" opacity=".9"/>'
        '<circle cx="260" cy="104" r="5" fill="#FFFFFF" stroke="#0F4C3A" stroke-width="2"/>'
        '<circle cx="460" cy="104" r="5" fill="#0F4C3A" stroke="#FFFFFF" stroke-width="2"/>'
        + dots +
        '<text x="20" y="28" font-size="11" font-weight="700" letter-spacing="2" '
        'fill="#0F4C3A">WORLDSTIP / 行程封面</text>'
        '<text x="20" y="53" font-size="19" font-weight="700" fill="#0F4C3A">%s → %s</text>'
        '<text x="20" y="72" font-size="11" fill="#5A5A5A">'
        '%d 天 · 离线生成的示意插画，非实景照片</text>'
        '<text x="700" y="28" text-anchor="end" font-size="11" fill="#0F4C3A">%s</text>'
        '</svg>'
    ) % (o, d, n, o, d, n, esc(str(season or ''))[:8])

# === 数据适配 ===
def pick(plan, *keys, default=''):
    for k in keys:
        v = plan.get(k)
        if v is not None and v != '':
            return v
    return default

# === 段落 ===
def section_no(n): return f'<span class="sec-no">§ {n:02d}</span>'


# ── 美景拍摄：按行程真实 POI 归题材，逐点给时机/要点/怎么去（v0.2.26）─────────
# 原则：只对本次行程真会去的景点给拍摄建议；没有专门机位就不列，绝不为凑栏目编造。
# 题材/时机/参数取自 references/photography_guide.json 的权威条目，参数直接折进题材要点，
# 不再单列「与地点无关」的通用参数速查表——那正是为指南而指南。
_PHOTO_SKIP = ('夜市', '商圈', '购物', '免税', '美食街', '服务区', '高铁站', '机场',
               '游客中心', '集散中心', '停车场', '酒店', '度假村', '民宿', '客栈')

# (key, 题材名, 触发关键词, 时机, 要点/参数) —— 顺序即优先级：建筑先于水景，
# 避免「湖北省博物馆 / 汴河街」这类名字里带「湖/河」的人文点被误判为水景。
_PHOTO_THEMES = [
    ('star', '星空银河', ('星空', '银河', '观星', '流星', '夜空'),
     '新月前后各 3 天（农历廿五–初五）为拍星窗口，满月拍不了银河',
     'f/1.4–2.8 全开、ISO 1600–3200、快门按 500 法则（500÷焦距秒）防拖线；必带三脚架 + 快门线'),
    ('sunrise', '日出', ('日出', '观日', '朝霞', '晨曦', '看太阳'),
     '日出前 40–60 min 到场占位，蓝调时刻从日出前 30 min 开始',
     '太阳入画用 GND 渐变镜或 HDR；对天空亮部减 0.3–0.7EV 保层次；广角收全景、长焦拍红日特写'),
    ('sunset', '日落晚霞', ('日落', '晚霞', '夕阳', '落日', '看落日', '黄昏'),
     '日落前 30–40 min 到场，日落后 15–25 min「烧云」常有二次高潮',
     '预留天空 1/3 构图，等太阳贴近地平线再按；前景决定下限——先找湖岸/栏杆/剪影人物做锚点'),
    ('snow', '冰雪雾凇', ('雾凇', '冰川', '冰瀑', '滑雪', '雪山', '雪乡', '雪景'),
     '雾凇窗口清晨 6–9 点，日出后开始融化脱落',
     '雪景 +1EV 曝光补偿（白加黑减，否则白雪拍成灰）；进出室内先装袋防结露'),
    ('mist', '云海雾景', ('云海', '雾', '垭口', '山脊', '观景台', '海拔', '云顶'),
     '雨后放晴的清晨云海概率最高，日出后 20–40 min 雾散，提前占位比技术更重要',
     '长焦 100–300mm 压缩雾层、拍山尖露头；无人机俯拍注意空域申报与禁飞区'),
    ('architecture', '人文建筑', ('楼', '塔', '寺', '庙', '宫', '阁', '古镇', '古村', '街', '巷',
                                '园', '馆', '遗址', '故居', '桥', '城墙', '祠堂', '书院', '坊',
                                '陵墓', '皇陵', '十三陵', '中山陵', '孝陵', '王陵', '陵园',
                                '古城', '影视城', '宋城', '长城', '城堡', '城门'),
     '蓝调时刻（亮灯后 20–30 min）城市灯火与天光平衡最出片',
     '建筑线条做引导线、侧光显立体；避开正午顶光，仰拍显气势、低角度收飞檐'),
    ('water', '湖海江河', ('湖', '海景', '海滩', '海湾', '海岸', '海角', '江滩', '江', '河',
                          '瀑布', '溪', '湿地', '岛', '屿', '洲', '沙滩', '银滩', '滩', '看海'),
     '无风清晨拍倒影最稳，顺光时水面反光呈金色',
     '慢门 + ND 减光（白天 ND1000、1–3s）拍丝滑水流；偏振镜 CPL 压反光、增强倒影'),
    ('nature', '自然山水', ('山', '峰', '林', '草原', '沙漠', '戈壁', '峡谷', '洞', '谷', '岭',
                          '崖', '石林', '森林', '竹海', '沟'),
     '黄金时刻（日出后 / 日落前 1h）侧逆光出层次',
     '前景 + 中景 + 远景三层构图，别只拍远山一片平；找岩石/树枝/人影当前景锚点'),
]


def _poi_photo_theme(poi: dict):
    """判定拍摄题材：先看 name+tag（类型标签），命中不了才用 desc 兜底，
    避免描述里偶现的「落日/湖」等词把建筑、山岳误判成日落或水景。
    命中返回 (题材名, 时机, 要点)，否则 None。"""
    tag = str(poi.get('tag') or '')
    tag_tail = tag.split('·')[-1] if '·' in tag else tag
    strong = str(poi.get('name') or '') + ' ' + tag_tail
    desc = str(poi.get('desc') or '')
    for src in (strong, desc):
        for _k, label, kws, timing, tip in _PHOTO_THEMES:
            if any(w in src for w in kws):
                return label, timing, tip
    return None


def _poi_shot_hint(poi: dict) -> str:
    """从 POI 自身描述抽取构图提示（真数据，无则返回空串）。"""
    blob = ' '.join(str(poi.get(k) or '') for k in ('name', 'tag', 'desc', 'info'))
    hints = [
        ('倒影', '用水面倒影做对称构图'),
        ('镜面', '利用镜面水面拍倒影'),
        ('云海', '等云海翻涌时再按快门'),
        ('芦苇', '芦苇做前景框景'),
        ('椰林', '椰林做前景框景'),
        ('礁石', '用礁石 / 渔船做前景'),
        ('巨石', '巨石群做前景，广角贴地拍出体量'),
        ('石景', '奇石做前景主体，侧光显纹理'),
        ('沙滩', '低角度贴沙面拍，留足天空与倒影'),
        ('海浪', '慢门 1/4–1s 拍浪花拉丝'),
        ('石窟', '洞口做框景，内部反光板补光'),
        ('壁画', '侧光显浮雕质感，别用闪光'),
        ('草原', '低机位让草浪入前景，等云影移动'),
        ('沙漠', '侧逆光拍沙脊曲线，日出日落最出纹理'),
        ('梯田', '等高线做引导线，晨雾时层次最好'),
        ('雪山', '长焦压缩雪峰，加 1EV 防拍灰'),
        ('古镇', '青石板 + 马头墙做纵深引导线'),
        ('老街', '老街纵深做引导线，等行人入画点缀'),
        ('塔', '塔身做竖构图主体，仰拍显气势'),
        ('楼', '楼体线条做引导线，落日时拍剪影'),
        ('寺', '逆光拍飞檐剪影，香烟缭绕出氛围'),
        ('佛', '逆光拍造像剪影'),
        ('瀑布', '侧机位避水雾，慢门拍丝滑'),
    ]
    for kw, h in hints:
        if kw in blob:
            return h
    return ''

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
        ex = src.get('explicit') or src.get('transport_explicit') or src.get('user_mode')
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

# === 终端形态（v0.2.274）===
# 三种产物不是换文件名，而是三套真实生效的排版层：
#   pc      桌面宽屏阅读版（宽版心 + 三列目录 + 悬停态）
#   a5      A5 分页小册子（@page A5 + 148mm 版心 + 分页保护，可另存 PDF）
#   mobile  手机 HTML5 版（移动优先 + 安全区 + 44px 触控区 + 底部锚点条）
# 覆盖层追加在原 CSS 之后，只增不改，避免动到既有版式。
VIEWPORT_PC = 'width=device-width, initial-scale=1.0'
VIEWPORT_MOBILE = 'width=device-width, initial-scale=1.0, viewport-fit=cover'

DEVICE_CSS = {
    # 桌面：版心沿用 780px 定稿（排版规范明令严禁加宽），差异体现在桌面交互与字号
    'pc': '''
@media screen{
  body{font-size:15px}
  .toc ul{grid-template-columns:repeat(3,1fr)}
  .hero{padding:30px 0 16px}
  .hero h1{font-size:34px}
  .sec{padding:16px 0 14px}
  .lead{font-size:15.5px}
  a:hover{color:var(--accent);border-bottom-color:var(--accent)}
  .toc a:hover{background:#EFEAD8}
  .day:hover,.tbl tr:hover{background:#FFFCF3}
}
''',
    # A5：屏幕模拟纸张，打印真分页；关键块禁止跨页切断
    'a5': '''
@page{size:A5;margin:8mm}
@media screen{
  body{background:#E9E4D8}
  .wrap{max-width:148mm;padding:8mm 9mm;background:#FFF;
        box-shadow:0 1px 3px rgba(0,0,0,.14);margin:16px auto}
  .sec.bright{margin:0 -9mm;padding:12px 9mm}
  body{font-size:13px}
}
@media print{
  body{background:#FFF;font-size:9.5pt;line-height:1.45}
  .wrap{max-width:148mm;padding:0;margin:0;box-shadow:none}
  .sec.bright{margin:0;padding:8pt 0}
  a{color:inherit;border-bottom:0}
  .toc{break-after:page}
  .toc a:hover,.day:hover{background:transparent}
  .sec>h2,.sec>h3{break-after:avoid}
  .day,.pack-card,.callout,.tline,.gate,.kv{break-inside:avoid}
  .tbl tr{break-inside:avoid}
  .cover-art{max-height:38mm}
  footer{break-before:avoid}
}
''',
    # 手机：单列优先、字号防缩放、触控区够大、目录吸顶、底部回顶
    'mobile': '''
@media screen{
  body{font-size:16px;-webkit-text-size-adjust:100%;padding-bottom:env(safe-area-inset-bottom)}
  .wrap{max-width:100%;padding:0 14px 88px}
  h2{font-size:20px}
  h3{font-size:17px}
  p,li{font-size:15.5px}
  .hero{padding:22px 0 14px}
  .hero h1{font-size:27px}
  .lead{font-size:16.5px}
  .toc{position:sticky;top:0;z-index:20;background:var(--bg);
       box-shadow:0 1px 0 var(--line)}
  .toc ul{grid-template-columns:1fr 1fr}
  .toc a{display:flex;align-items:center;min-height:44px;padding:0 4px}
  .sec.bright{margin:0 -14px;padding:14px 14px}
  .row{grid-template-columns:1fr}
  .pack-grid{grid-template-columns:1fr}
  .day{grid-template-columns:34px 1fr;gap:8px}
  .slot,.tline{grid-template-columns:44px 1fr}
  .tbl{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .kv{grid-template-columns:1fr}
  .kv .k{white-space:normal}
  a{border-bottom:1px solid var(--line2);padding:2px 0}
  .to-top{position:fixed;right:14px;bottom:calc(14px + env(safe-area-inset-bottom));
          width:46px;height:46px;border-radius:23px;background:var(--accent);color:#FFF;
          display:flex;align-items:center;justify-content:center;font-size:19px;
          box-shadow:0 3px 10px rgba(0,0,0,.22);z-index:30;border:0}
}
'''
}

# 手机版才注入的回顶按钮（纯锚点，无脚本）
TO_TOP_HTML = '<a class="to-top" href="#top" aria-label="回到顶部">↑</a>'

# === HTML 模板 ===
HTML_TPL = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="{VIEWPORT}">
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
.poi{{display:block;margin:2px 0 0;font-size:13px;line-height:1.5}}
.poi .tag{{font-size:10.5px;padding:0 5px;margin-left:3px;vertical-align:middle}}
.muted{{color:var(--sub);font-size:11.5px;line-height:1.5}}
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
.cover-art{{display:block;width:100%;height:auto;max-height:132px;border-radius:8px;margin:0 0 12px;background:#F7F4EE}}
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
{DEVICE_CSS}
</style>
</head>
<body id="top">
<div class="wrap">
{HERO}
{FEAS_BANNER}
{TOC}
{ROUTE_OVERVIEW}
{TRANSIT}
{FEASIBILITY}
{FOOD}
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
{TO_TOP}
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


def _feasibility_block(plan: dict, mode: str):
    """可执行性体检（v0.1.43 起并入默认渲染器，此前仅旧版 render_booklet 有）。

    复用 render_booklet 的零依赖体检引擎（阈值自检 + 目的地 P0 关卡覆盖 + 末班船断言），
    视觉用本模板既有 .gate/.tag 类。返回 (册首横幅, 单独板块) 两段 HTML。
    """
    if mode == 'none':
        return '', ''
    from feasibility import run_feasibility
    feas = run_feasibility(plan)
    p0_hard = [i for i in feas['p0'] if i['level'] == 'P0'] + feas['assert']
    p0_soft = [i for i in feas['p0'] if i['level'] != 'P0']
    n_all = len(feas['threshold']) + len(feas['p0']) + len(feas['assert'])

    # ── 册首横幅：strict 红色强制 / advisory 黄色提示 / 全过绿色 ──
    if p0_hard:
        items = ''.join(f'<li>{esc(i.get("text", i.get("place", "")))}</li>' for i in p0_hard[:6])
        if mode == 'strict':
            banner = (f'<section class="sec" style="border:2px solid var(--red)">'
                      f'<span class="tag red">🛑 可执行性体检未通过</span>'
                      f'<p style="margin:6px 0 4px">存在 <b>{len(p0_hard)}</b> 项 P0 硬错，出行前必须复核：</p>'
                      f'<ul style="margin:0;padding-left:18px">{items}</ul></section>')
        else:
            banner = (f'<section class="sec" style="border:1px solid var(--warn)">'
                      f'<span class="tag warn">⚠ 可执行性体检提示</span>'
                      f'<p style="margin:6px 0 4px">发现 {len(p0_hard)} 项 P0 硬错建议关注（详见 §2b，--feasibility strict 可置顶强制）：</p>'
                      f'<ul style="margin:0;padding-left:18px">{items}</ul></section>')
    elif n_all:
        banner = (f'<section class="sec"><span class="tag ok">ℹ 可执行性体检</span>'
                  f'<p style="margin:6px 0 0">无 P0 硬错；{n_all} 项提示已列入 §2b 板块。</p></section>')
    else:
        banner = '<section class="sec"><span class="tag ok">✅ 可执行性体检通过：未发现 P0 硬错（零依赖关卡库校验）。</span></section>'

    # ── 单独板块 §2b ──
    S = ['<section class="sec" id="sec2b">',
         '<h2><span style="color:var(--sub);font-size:14px;margin-right:6px">§2b</span>'
         '可执行性体检<span class="en">Feasibility</span></h2>']
    for t in feas['threshold']:
        S.append(f'<div class="gate"><span class="l warn"></span><div class="t"><b>节奏/体力阈值</b>'
                 f'<div class="d">{esc(t)}</div></div></div>')
    for i in feas['p0']:
        cls = 'red' if i['level'] == 'P0' else 'warn'
        S.append(f'<div class="gate"><span class="l {cls}"></span><div class="t">'
                 f'<b>[{esc(i["level"])}] {esc(i["place"])} · 关卡未覆盖</b>'
                 f'<div class="d">{esc(i["text"])}</div></div></div>')
    for i in feas['assert']:
        S.append(f'<div class="gate"><span class="l red"></span><div class="t"><b>[P0] 数据一致性冲突</b>'
                 f'<div class="d">{esc(i["text"])}</div></div></div>')
    if n_all == 0:
        S.append('<p>✅ 各项指标均在经验安全阈值内，行程节奏与体力分配合理。</p>')
    S.append('<em class="warn">体检基于经验阈值与本地关卡库（不含实时交通/票务/天气）；'
             'P0 为出行前必须复核的硬项，出行前 1–3 天请以官方实时信息为准。</em>')
    S.append('</section>')
    return banner, '\n'.join(S)


def render(plan: dict, title: str, transit: dict = None, research: dict = None,
           feasibility: str = 'advisory', device: str = 'pc') -> str:
    """device: pc | a5 | mobile —— 决定注入哪套终端排版层（v0.2.274）。"""
    if device not in DEVICE_CSS:
        device = 'pc'
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
    feas_banner, feas_sec = _feasibility_block(plan, feasibility)

    # === HERO ===
    total_pp = budget.get('per_person_total') or budget.get('group_total') or 0
    intensity_label = {1: '轻', 2: '轻', 3: '中', 4: '中', 5: '高'}.get(intensity, '中')
    cover = cover_art(origin, dest, days, season)
    hero = f'''<div class="hero">
{cover}
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
        ('3', '必吃·必玩'),
        ('4', '逐日动线'), ('5', '季节与气候'),
        ('6', '美景拍摄'), ('7', '住宿'),
        ('8', '预算速查'), ('9', '行前清单'),
        ('10', '安全与应急'), ('11', '出发前多知道一点'),
    ]
    if feas_sec:
        toc_items.insert(2, ('2b', '可执行性体检'))
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
        # v0.2.23: 用当日真实景点分布替代套话; 无 POI 时回退日小结
        am_pois = [p.get('name', '') for s in slots if s.get('name') == '上午' for p in (s.get('pois') or [])]
        pm_pois = [p.get('name', '') for s in slots if s.get('name') == '下午' for p in (s.get('pois') or [])]
        if am_pois or pm_pois:
            parts = []
            if am_pois:
                parts.append('上午 ' + '、'.join(am_pois[:2]))
            if pm_pois:
                parts.append('下午 ' + '、'.join(pm_pois[:2]))
            overview.append(f'<div class="d-meta">{esc(" ｜ ".join(parts))}</div>')
        elif d.get('note'):
            overview.append(f'<div class="d-meta">{esc(d["note"])}</div>')
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
    day_html = ['<section class="sec" id="sec4">', section_no(4), '<h2>逐日动线<span class="en">Day by Day</span></h2>']
    day_html.append('<p class="sub-en">时间锚点 + 节点说明 + 关键提示</p>')
    # 路线形态图：真实经纬度算直线里程，沿横轴按真实比例排节点；坐标不全自动降级不出图
    if _route_html:
        try:
            _rv = _route_html(plan)
            if _rv:
                day_html.append(_rv)
        except Exception:
            pass
    for d in day_plan:
        dno = d.get('day', '?')
        lbl = d.get('label', '')
        city = d.get('city', '')
        hrs = d.get('total_hours', '')
        active = d.get('active', {}) or {}
        slots = d.get('slots', []) or []
        # 当日总账 + 人本疲劳评级: 让「路程算时间、人吃得消吗」可视化
        _fare = d.get('fare_total_h', 0) or 0
        _rating = d.get('fatigue_rating', '')
        _trans = d.get('transfers', 0) or 0
        _rating_style = {"低": "color:#2e7d32;background:#e8f5e9",
                         "中": "color:#b26a00;background:#fff4e0",
                         "高": "color:#c62828;background:#fdecea"}.get(_rating, "")
        _meta = f'{esc(hrs)}h'
        if _fare:
            _meta += f' · 含车程{esc(_fare)}h'
        if _trans:
            _meta += f' · 跨区{esc(_trans)}次'
        day_html.append(f'<div style="margin:10px 0 8px"><b>D{dno} · {esc(lbl)}</b> · {esc(city)} · {_meta}')
        if _rating:  # 人本疲劳评级芯片: 低(稳)/中(适中)/高(偏累⚠)
            _w = ' ⚠' if _rating == '高' else ''
            day_html.append(f' <span class="tag" style="{_rating_style}">体力{esc(_rating)}{_w}</span>')
        if active.get('km'):
            day_html.append(f' <span class="tag accent">{esc(active.get("label","体力"))} {active.get("km")}km</span>')
        day_html.append('</div>')
        for s in slots:
            ts = s.get('start', '—')
            nm = s.get('name', '')
            h = s.get('hours', '')
            sf = s.get('fare_h', 0) or 0
            note = s.get('note', '')
            _sh = f'{esc(h)}h' + (f'（含车程{esc(sf)}h）' if sf else '')
            day_html.append(f'<div class="slot"><div class="ts">{esc(ts)}</div><div class="nm"><b>{esc(nm)}</b> <span class="du">{_sh}</span>')
            # v0.2.25+: 逐 POI 渲染 —— 名称 + 标签 + 游玩方式(怎么玩) + 怎么去(到达)，
            # 让「景点怎么玩、怎么去」落到每个点，而非只给城市级交通（concern1/4）
            for p in (s.get('pois') or []):
                pnm = (p.get('name') or '').split(' · ')[0]
                ptag = p.get('tag') or '景点'
                pplay = p.get('play') or ''
                parr = p.get('arrival') or ''
                day_html.append('<div class="poi"><b>%s</b> <span class="tag">%s</span>'
                                % (esc(pnm), esc(ptag)))
                if pplay:
                    day_html.append('<br><span class="muted">怎么玩：%s</span>' % esc(pplay))
                if parr:
                    day_html.append('<br><span class="muted">怎么去：%s</span>' % esc(parr))
                day_html.append('</div>')
            # v0.2.23: 时段备注保留为日级提示
            if note:
                day_html.append(f'<br><span class="muted">{esc(note)}</span>')
            day_html.append('</div></div>')
        if d.get('note'):
            day_html.append(f'<em class="tip">💡 {esc(d["note"])}</em>')
        # 人本提示: 仅高日明确说人吃不消, 中/低不啰嗦
        if _rating == '高':
            day_html.append(f'<em class="tip warn">⚠ 今日实际约{esc(d.get("real_total_h"))}h（含车程{esc(_fare)}h）+ 吃饭{d.get("eat_h",1.5)}h，'
                            f'体力消耗偏大，建议午休 / 早出发，别硬撑</em>')
        if d.get('unplaced'):
            day_html.append(f'<em class="tip warn">⚠ {esc(city)} 还有 {esc("、".join(d["unplaced"]))} '
                            f'因时间紧未排入，{len(day_plan)}天行程建议只挑核心，其余留待加半天或下次</em>')
    day_html.append('</section>')

    # === 季节 ===
    season_html = ['<section class="sec bright" id="sec5">', section_no(5), '<h2>季节与气候<span class="en">Season & Climate</span></h2>']
    # v0.2.274: 有出行日期时用真实时令上下文（气候区 + 当月气温 + 看点 + 风险），
    # 取代「请查实时天气预报」这类空话；来源是 references/seasons_climate.json。
    _ctx = plan.get('context') or {}
    _cities = _ctx.get('cities') or {}
    _first = next(iter(_cities.values()), {}) if _cities else {}
    _mtag = f'（{_first.get("season")}档）' if _first.get('season') else ''
    season_html.append(f'<p><b>{esc(season)}</b> 季{esc(_mtag)} · '
                       f'季节结论绑定出行日期 · 出行前 3 天务必复核实时天气预报</p>')
    season_text_map = {
        '春': '春（3-5 月）· 草原泛青、杜鹃初绽、江南烟雨；华南已入雨季',
        '夏': '夏（6-8 月）· 草原与海岛旺季、避暑与摄影窗口；台风/雷暴多发',
        '秋': '秋（9-11 月）· 草原金黄、江南桂花、稻田金黄；最佳综合季节',
        '冬': '冬（12-2 月）· 雪景与雾凇、温泉旺季；部分景区歇业、路况复杂',
    }
    season_html.append(f'<p>{esc(season_text_map.get(season, "请查实时天气预报"))}</p>')
    if _cities:
        _shown = 0
        for _cname, _cv in _cities.items():
            if _shown >= 2:
                break
            _shown += 1
            _head = (f'<p><b>{esc(_cname)}</b> · {esc(_cv.get("region_label", ""))} · '
                     f'{esc(_cv.get("season", ""))}（{esc(_cv.get("climate", ""))}）</p>')
            season_html.append(_head)
            _tips = [t for t in (_cv.get('tips') or []) if t][:3]
            if _tips:
                season_html.append('<p><b>当月装备</b>：' + esc(' · '.join(_tips)) + '</p>')
            if _cv.get('highlight'):
                season_html.append('<p><b>本季看点</b>：' + esc(_cv['highlight']) + '</p>')
            if _cv.get('risk'):
                season_html.append(f'<p><b>本季风险</b>：{esc(_cv["risk"])}</p>')
        if _shown:
            season_html.append(f'<p class="sub-en">时令依据 {esc(_ctx.get("date", ""))} · '
                               f'气候区分档见 references/seasons_climate.json</p>')
    if tone:
        season_html.append(f'<p><b>本季关注</b>：{" · ".join(esc(t) for t in tone)}</p>')
    season_html.append('</section>')

    # === 美景拍摄（本次出片清单）===
    # v0.2.26: 只列本次行程真实会去的点，按题材分组——同类时机/参数只讲一次，
    # 具体到点的「拍什么」逐点给；没有专门机位就不凑数，绝不为凑栏目编造。
    photo_html = ['<section class="sec" id="sec6">', section_no(6),
                  '<h2>美景拍摄<span class="en">Photo Guide</span></h2>']
    photo_html.append('<p class="sub-en">本次行程出片清单 · 只列真会去的点 · 同类题材时机/参数只讲一次</p>')
    _seen_p, _groups, _n = set(), {}, 0
    _theme_order = [t[1] for t in _PHOTO_THEMES]
    for _d in day_plan:
        for _s in (_d.get('slots') or []):
            for _p in (_s.get('pois') or []):
                _nm = (_p.get('name') or '').split(' · ')[0].strip()
                if not _nm or _nm in _seen_p:
                    continue
                _blob = _nm + ' ' + (_p.get('tag') or '') + ' ' + (_p.get('desc') or '')
                if any(_w in _blob for _w in _PHOTO_SKIP):
                    continue
                _th = _poi_photo_theme(_p)
                if not _th:
                    continue
                _seen_p.add(_nm)
                _label, _timing, _tip = _th
                _g = _groups.setdefault(_label, {'timing': _timing, 'tip': _tip, 'rows': []})
                _g['rows'].append((_nm, _poi_shot_hint(_p)))
                _n += 1
                if _n >= 8:
                    break
            if _n >= 8:
                break
        if _n >= 8:
            break
    if _groups:
        for _label in _theme_order:
            if _label not in _groups:
                continue
            _g = _groups[_label]
            photo_html.append('<h4>%s</h4>' % esc(_label))
            photo_html.append('<p class="muted">时机：%s</p>' % esc(_g['timing']))
            photo_html.append('<ul>')
            for _nm, _hint in _g['rows']:
                if _hint:
                    photo_html.append('<li><b>%s</b> — %s</li>' % (esc(_nm), esc(_hint)))
                else:
                    photo_html.append('<li><b>%s</b></li>' % esc(_nm))
            photo_html.append('</ul>')
            if _g['tip']:
                photo_html.append('<em class="note">拍法：%s</em>' % esc(_g['tip']))
        photo_html.append('<em class="note">参数为通用起手值，实拍按现场光线微调；手机开网格线 + 长按锁定曝光，'
                          '即可完成大部分题材。</em>')
    else:
        photo_html.append('<p><b>本次行程以城市人文 / 购物为主</b>，没有需要专门守时机、抢机位的点，不凑数。'
                          'walk 随手拍即可：<b>蓝调时刻</b>（日落后 20–30 min）街道灯火与天光平衡最出片，'
                          '面对强光对天空亮部测光、避免主体死黑。</p>')
    photo_html.append('</section>')

    # === 住宿 ===
    stay_html = ['<section class="sec" id="sec7">', section_no(7), '<h2>住宿安排<span class="en">Where to Stay</span></h2>']
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
    budget_html = ['<section class="sec" id="sec8">', section_no(8), '<h2>预算速查<span class="en">Budget</span></h2>']
    budget_html.append(f'<p class="sub-en">基于距离的估算 · 实时票价查 12306 / 航司</p>')
    pp = budget.get('per_person', {}) or {}
    pp_low = budget.get('per_person_low', pp) or pp
    grp = budget.get('group', {}) or {}
    if pp or grp:
        budget_html.append('<table class="tbl"><thead><tr><th>分项</th><th class="r">最低/人</th><th class="r">常规/人</th><th class="r">占常规合计</th></tr></thead><tbody>')
        total_pp = sum((pp or grp).values()) or 1
        for k in (pp or grp):
            regular = (pp or grp).get(k, 0)
            low = pp_low.get(k, regular)
            pct = round(regular / total_pp * 100)
            budget_html.append(f'<tr><td>{esc(k)}</td><td class="r">¥{low}</td><td class="r">¥{regular}</td><td class="r">{pct}%</td></tr>')
        low_total = budget.get('per_person_total_low', budget.get('per_person_total', 0))
        budget_html.append(f'<tr><td><b>人均合计</b></td><td class="r"><b>¥{low_total:,}</b></td><td class="r"><b>¥{budget.get("per_person_total",0):,}</b></td><td class="r">100%</td></tr>')
        budget_html.append('</tbody></table>')
    budget_html.append('<h4>💡 节省口诀</h4><ul><li>住宿按<b>房间</b>而非按人数 · 单人订大床房最划算</li><li>餐饮：早餐住宿含 / 午晚餐本地老店更地道</li><li>门票：学生证/老年证/军官证带好可省；多日票通常比单日票划算</li><li>机票：周中+提前 14 天是常见低洼；关注临近退票高峰</li></ul>')
    if budget.get('split_mode'):
        _sn = budget.get('split_note', '')
        budget_html.append(f'<em class="note">💑 陪伴结构「{esc(party.get("label",""))}」· 费用口径：<b>{esc(budget.get("split_mode"))}</b>'
                           + (f' · {esc(_sn)}' if _sn else '') + '</em>')
    budget_html.append('</section>')

    # === 行前清单（每类一张卡 · 2 列网格紧凑排布） ===
    pack_html = ['<section class="sec" id="sec9">', section_no(9), '<h2>行前清单<span class="en">Pre-trip Checklist</span></h2>']
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
                         '<div class="pack-card"><h5>🪪 证件</h5><div class="items">身份证</div></div>'
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
    safe_html = ['<section class="sec bright" id="sec10">', section_no(10), '<h2>安全与应急<span class="en">Safety & Emergency</span></h2>']
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
    cold_html = ['<section class="sec" id="sec11">', section_no(11), '<h2>出发前多知道一点<span class="en">A Few Extra Things</span></h2>']
    if cold:
        for c in cold[:2]:
            for f in c.get('facts', []) or []:
                cold_html.append(f'<h4>· {esc(f.get("标题",""))}</h4>')
                cold_html.append(f'<p>{esc(f.get("内容",""))}</p>')
    else:
        cold_html.append('<h4>· 12306 捡漏三时段</h4><p>放票非一次放完：每日 6-7 点、22-23 点退票高峰、开车前 1-2 天放预留票，抢不到多刷这几个点。</p>')
        cold_html.append('<h4>· 官方只认 12306</h4><p>退改签候补都绕不开 12306，关键票用官方 App 最稳，抢票软件易被风控。</p>')
    supp = _guide_supplement_html(research)
    if supp:
        cold_html.append(supp)
    cold_html.append('</section>')

    # === 必吃 · 必玩（concern3/1：必备推荐不缺项；不指定店；查不到写未覆盖） ===
    food_html = ['<section class="sec" id="sec3">', section_no(3),
                 '<h2>必吃 · 必玩<span class="en">Must-Eat &amp; Must-Do</span></h2>']
    food_html.append('<p class="sub-en">点到品类与招牌玩法，不指定具体店；查不到写未覆盖，绝不编造</p>')
    dest_cn = (plan.get('destinations') or [''])[0] or '目的地'
    # 必吃：food_guide.json 按中文城市名索引
    fg = _load_ref('food_guide.json') or {}
    fg_by_cn = {v.get('city'): v for v in fg.values()
                if isinstance(v, dict) and v.get('dishes')}
    dish_entry = fg_by_cn.get(dest_cn)
    food_html.append('<h4>🍜 必吃（品类 · 为何值得 · 参考价）</h4>')
    if dish_entry and dish_entry.get('dishes'):
        food_html.append('<ul>')
        for ds in dish_entry['dishes'][:5]:
            food_html.append(
                f'<li><b>{esc(ds.get("n", ""))}</b> · {esc(ds.get("why", ""))} '
                f'<span class="muted">（{esc(ds.get("slot", ""))} · {esc(ds.get("price", ""))}）</span></li>')
        food_html.append('</ul>')
    else:
        food_html.append('<em class="note">本目的地暂无结构化必吃清单，出行前请查本地老店 / 夜市 / 农贸市场，'
                         '优先认准开了多年的本地人食堂，先问价再点单。</em>')
    # 必玩：poi.json 招牌景点 + 游玩方式（concern1）
    poi_db = _load_ref('poi.json') or {}
    poi_city = (poi_db.get('poi') or {}).get(dest_cn) or []
    food_html.append('<h4>🎯 必玩（招牌玩法）</h4>')
    if poi_city:
        food_html.append('<ul>')
        for p in poi_city[:5]:
            nm = (p.get('name') or '').split(' · ')[0]
            tag = p.get('tag') or '景点'
            play = p.get('play') or ''
            food_html.append(f'<li><b>{esc(nm)}</b> <span class="tag">{esc(tag)}</span>')
            if play:
                food_html.append(f' — {esc(play)}')
            food_html.append('</li>')
        food_html.append('</ul>')
    else:
        food_html.append('<em class="note">本目的地暂无结构化必玩清单，出行前请查官方文旅与实拍攻略，按体力量力排点。</em>')
    food_html.append('</section>')

    # === 散心模式（relax/resort）：跳过 §02/§03/§08/§09 ===
    is_relax = (plan.get('style') or '').lower() in ('resort', 'relax')
    if is_relax:
        transit_html = ['']
        day_html = ['']
        pack_html = ['']
        safe_html = ['']
        feas_banner, feas_sec = '', ''
        toc_items = [
            ('1', '路线总览'), ('3', '必吃·必玩'),
            ('5', '季节与气候'),
            ('6', '美景拍摄'), ('7', '住宿'),
            ('8', '预算速查'), ('11', '出发前多知道一点'),
        ]
        toc = '<div class="toc"><h4>CONTENTS</h4><ul>' + ''.join(f'<li><a href="#sec{n}">§{n} {esc(t)}</a></li>' for n, t in toc_items) + '</ul></div>'

    return HTML_TPL.format(
        VIEWPORT=VIEWPORT_MOBILE if device == 'mobile' else VIEWPORT_PC,
        DEVICE_CSS=DEVICE_CSS[device],
        TO_TOP=TO_TOP_HTML if device == 'mobile' else '',
        title=esc(title),
        HERO=''.join(hero),
        FEAS_BANNER=feas_banner,
        TOC=''.join(toc),
        ROUTE_OVERVIEW=''.join(overview),
        TRANSIT=''.join(transit_html),
        FEASIBILITY=feas_sec,
        FOOD=''.join(food_html),
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
DEVICE_SUFFIX = {'a5': '-A5', 'mobile': '-手机'}
DEVICE_LABEL = {'pc': 'PC 网页版', 'a5': 'A5 小册子（可打印/另存 PDF）', 'mobile': '手机 HTML5 版'}


def _device_targets(out: str, device: str):
    """把 --out 与 --device 展开成 [(device, path)]。

    device=both 时一次产三件：--out 本身即 PC 版（旧调用方路径不变），
    另两件加后缀；单选时严格只产一件，不偷偷多写文件。
    """
    base = Path(out)
    if device != 'both':
        return [(device, base)]
    targets = []
    for dev in ('pc', 'a5', 'mobile'):
        p = base if dev == 'pc' else base.with_name(f"{base.stem}{DEVICE_SUFFIX[dev]}{base.suffix}")
        targets.append((dev, p))
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--transit', default=None)
    ap.add_argument('--research', default=None, help='research.json（ugc 攻略研读沉淀，渲染进 §10 攻略核验子块）')
    ap.add_argument('--feasibility', choices=['none', 'advisory', 'strict'], default='advisory',
                    help='可执行性体检：advisory 默认提示 / strict P0 红条强制 / none 关闭（v0.1.43 起并入默认渲染器）')
    ap.add_argument('--device', choices=['pc', 'a5', 'mobile', 'both'], default='both',
                    help='终端形态：pc 桌面网页 / a5 A5 分页小册子 / mobile 手机 HTML5 / both 三件齐出（默认）')
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', required=True)
    args = ap.parse_args()
    plan = json.load(open(args.plan, encoding='utf-8'))
    transit = json.load(open(args.transit, encoding='utf-8')) if args.transit else None
    research = json.load(open(args.research, encoding='utf-8')) if args.research else None
    # 空壳 plan（合法 JSON 但没有行程数据）不该渲染成一张空册子还报「已生成」——
    # 那等于谎报成功，调用方会拿着一张 14 板块的空模板当成品发出去。
    if not (plan.get('plan') or plan.get('destinations')):
        sys.stderr.write("[ERROR] plan.json 里没有可用行程数据："
                         "`plan`（逐日）与 `destinations`（目的地）都为空\n")
        sys.stderr.write("[HINT] 先用 build_itinerary.py 生成 plan.json，"
                         "或检查 --plan 是否指到了别的文件\n")
        sys.exit(2)
    sections = ['hero', 'toc', '路线总览', '怎么去', '必吃·必玩', '逐日动线', '季节', '拍摄', '住宿', '预算', '清单', '安全', '冷知识']
    if args.feasibility != 'none':
        sections.append('可执行性体检')
    if research and (research.get('ugc') or []):
        sections.append('攻略核验')
    for dev, path in _device_targets(args.out, args.device):
        html = render(plan, args.title, transit, research,
                      feasibility=args.feasibility, device=dev)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding='utf-8')
        print(f'✅ 已生成[{DEVICE_LABEL[dev]}]: {path}  '
              f'(板块 {len(sections)} 个, {len(html.encode())//1024} KB)')


def _fatal(e: BaseException) -> int:
    """不可信输入（路径不存在 / 坏 JSON / 结构不符）→ 一行中文诊断 + 退出码 2。

    绝不裸露 traceback：调用方多是模型或 CI，看到 Python 栈只会把
    本机绝对路径和栈帧一起贴出来，既不安全也不可读。
    需要现场调试时置 AITRIP_DEBUG=1，异常原样抛出。
    """
    import os as _os
    if _os.environ.get("AITRIP_DEBUG"):
        raise e
    if isinstance(e, FileNotFoundError):
        msg = "输入文件不存在：%s" % (e.filename,)
    elif isinstance(e, IsADirectoryError):
        msg = "给的路径是目录不是文件：%s" % (e.filename,)
    elif isinstance(e, PermissionError):
        msg = "没有读写权限：%s" % (e.filename,)
    elif isinstance(e, UnicodeDecodeError):
        msg = "输入文件不是 UTF-8 文本，无法解析"
    elif isinstance(e, json.JSONDecodeError):
        msg = "输入不是合法 JSON（第 %d 行第 %d 列）" % (e.lineno, e.colno)
    elif isinstance(e, OSError):
        msg = "文件读写失败：%s" % (e.strerror,)
    else:
        msg = "输入数据与预期结构不符（%s），请检查 plan 字段" % type(e).__name__
    sys.stderr.write("[ERROR] %s\n" % msg)
    sys.stderr.write("[HINT] --plan/--transit/--research 需指向合法 JSON；"
                     "最小用法：--plan plan.json --title 标题 --out 输出.html\n")
    return 2


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as _e:
        sys.exit(_fatal(_e))
