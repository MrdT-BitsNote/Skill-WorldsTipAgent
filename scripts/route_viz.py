# -*- coding: utf-8 -*-
"""route_viz.py — 行程路线可视化（真实经纬度 · 纯内联 SVG · 零依赖）

为什么存在
----------
v0.1.32 因「第三方底图不稳 + 不许画 SVG 假地图」全面取消地图附图，路线退回纯文字表格。
代价是报告不直观：用户看到的是「佛山 → 衡阳 · 405km」，看不到这趟路在地上怎么走。

本脚本走第三条路：**不画地图，只画真坐标**。两种图，各管一件事：

  A. 路线形态图 `render_svg(nodes)` —— 行程级。横轴按真实经纬度算出的直线里程排节点，
     段上标「段里程 + 八向方位」。回答「这趟有多远、朝哪走」。
  B. 线路形状图 `render_trace_svg(trace)` —— 线路级。用 `references/moto_traces.json`
     里的真实 GPS 轨迹等比例画出路的形状（v0.2.274 起）。回答「这条路长什么样」。
     坐标来自技能自有数据（城市级 destinations / 景点级 moto_places / 线路轨迹 moto_traces）
  · 只连节点与轨迹，不画国界/省界/海岸线 → 不构成公开地图，不涉审图号
  · 坐标查不到就不画该节点，绝不猜、绝不拿同名地点凑数

为什么行程级不用地理投影、线路级才用（v0.2.274 定案）
------------------------------------------------------
行程跨几百上千公里且常呈南北向，投影后是「一根细线 + 大片空白」，相邻 3km 的节点
标注必然重叠 → 行程级改用横向里程轴。而单条线路范围小（几十至二百公里）且形状本身
就是要传达的信息，等比例投影才看得清弯道密度，所以线路级用真投影。

硬纪律
------
1. 纯标准库，零联网，零外链。
2. 坐标缺失 = 不渲染该节点；可用节点 < 2 时整体不出图，由上层退回纯文字。
3. 图内必须自标「示意：按真实经纬度等距投影，非导航地图」，不得让用户误当导航用。
4. 海拔剖面需 elevation 数据，destinations.json 仅 300 条有且大量为空 → 不渲染，不插值编造。

用法
----
    from route_viz import render_route_html
    html = render_route_html(plan)          # plan 为 render_compact 的 plan dict
    # 或命令行自检：
    python scripts/route_viz.py --plan plan.json
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEST = os.path.join(ROOT, "references", "destinations.json")
PLACES = os.path.join(ROOT, "references", "moto_places.json")
TRACES = os.path.join(ROOT, "references", "moto_traces.json")

# 版式令牌（与 render_compact 的 A5 卡册一致）
C_START = "#0F6E56"   # 起点 · 深墨绿
C_MID = "#5DCAA5"     # 途经 · 浅青
C_END = "#D85A30"     # 终点 · 暖橙
C_LINE = "#0F6E56"
C_TEXT = "#1F2A26"
C_SUB = "#6B7B74"
C_BG = "#FBF9F5"
C_GRID = "#E3DED3"

MAX_NODES = 12        # 超过则抽样，避免标注糊成一团


def _haversine(a, b):
    """两点球面距离（km）。a/b = (lat, lng)。"""
    if not a or not b:
        return 0.0
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = p2 - p1
    dlmb = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class GeoResolver:
    """按名字取真实坐标。城市级走 destinations，景点级走 moto_places，均带行政约束。"""

    def __init__(self):
        self._city = None
        self._place = None
        self._cache = {}

    def _cities(self):
        if self._city is None:
            self._city = {}
            d = _load(DEST) or {}
            for x in d.get("destinations", []):
                if x.get("lat") is None or x.get("lon") is None:
                    continue
                for k in (x.get("name"), x.get("fn"), x.get("slug")):
                    if k:
                        self._city.setdefault(k, x)
                for a in (x.get("alt") or []):
                    self._city.setdefault(a, x)
        return self._city

    def _places(self):
        if self._place is None:
            self._place = []
            d = _load(PLACES) or {}
            for p in d.get("places", []):
                if p.get("lat") is None or p.get("lng") is None:
                    continue
                # st=suspect / kind=non_scenic 不进图：坐标可靠但语义不是景点
                if p.get("fl") or p.get("st") == "suspect":
                    continue
                if p.get("kind") == "non_scenic":
                    continue
                self._place.append(p)
        return self._place

    def resolve(self, name, admin_hint=""):
        """返回 dict(name, lat, lng, src, admin) 或 None。查不到返回 None，绝不猜。"""
        if not name:
            return None
        name = str(name).strip()
        key = (name, admin_hint or "")
        if key in self._cache:
            return self._cache[key]

        out = None
        # 1) 城市级精确命中（唯一性高）
        c = self._cities().get(name)
        if c:
            out = dict(name=c.get("name") or name, lat=c["lat"], lng=c["lon"],
                       src="destinations", admin=c.get("admin1") or "")

        # 2) 景点级：必须带行政约束，否则同名会跨省错配
        if out is None:
            cands = [p for p in self._places()
                     if name == (p.get("n") or "") or name == (p.get("fn") or "")
                     or name in (p.get("alt") or [])]
            if not cands:
                cands = [p for p in self._places()
                         if name and (name in (p.get("n") or "") or name in (p.get("fn") or ""))]
            if cands and admin_hint:
                cons = [p for p in cands if admin_hint in (p.get("admin") or "")]
                if cons:
                    cands = cons
                else:
                    # 有提示却一个都对不上 → 判定为不可靠，宁可不画
                    cands = []
            if len(cands) > 1 and not admin_hint:
                # 无约束且多候选 = 同名歧义，不画
                cands = []
            if cands:
                p = cands[0]
                out = dict(name=p.get("fn") or p.get("n") or name, lat=p["lat"],
                           lng=p["lng"], src="moto_places", admin=p.get("admin") or "")

        self._cache[key] = out
        return out


def collect_nodes(plan, resolver=None):
    """从 plan 抽行程节点序列：起点 → 逐日城市 → 终点。

    返回 (nodes, missing)：nodes 每项含 name/lat/lng/role/km(累计)/src/admin。
    """
    resolver = resolver or GeoResolver()
    raw = []

    # 占位出发地（未指定/本地）不参与画图：画上去只会多一个查不到的节点和一行灰字
    origin = (plan.get("origin") or "").strip()
    if origin and origin not in ("未指定", "本地", "未知", "不详"):
        raw.append((origin, "start", ""))

    for d in (plan.get("plan") or []):
        city = (d.get("city") or "").strip()
        if city and (not raw or city != raw[-1][0]):
            raw.append((city, "mid", ""))
        # 景点级节点：只有带明确地名时才取，取不到坐标会在 resolve 阶段落进 missing
        for s in (d.get("slots") or []):
            for p in (s.get("pois") or []):
                pname = (p.get("name") or "").split(" · ")[0].strip()
                if pname and pname != city:
                    raw.append((pname, "poi", city))

    dests = plan.get("destinations") or []
    if dests:
        tail = str(dests[-1]).strip()
        if tail and (not raw or tail != raw[-1][0]):
            raw.append((tail, "end", ""))

    # 去重保序
    seen, dedup = set(), []
    for nm, role, hint in raw:
        if nm in seen:
            continue
        seen.add(nm)
        dedup.append((nm, role, hint))

    nodes, missing = [], []
    for nm, role, hint in dedup:
        g = resolver.resolve(nm, hint)
        if g is None:
            missing.append(nm)
            continue
        nodes.append(dict(name=nm, lat=g["lat"], lng=g["lng"], role=role,
                          src=g["src"], admin=g.get("admin") or ""))
    # 标记真正的终点：最后一个解析成功的节点
    if nodes:
        for n in nodes:
            n["role"] = "mid"
        nodes[0]["role"] = "start"
        nodes[-1]["role"] = "end"

    # 累计里程
    km = 0.0
    for i, n in enumerate(nodes):
        if i:
            km += _haversine((nodes[i - 1]["lat"], nodes[i - 1]["lng"]), (n["lat"], n["lng"]))
        n["km"] = km
    return nodes, missing


DIRS = ["北", "东北", "东", "东南",
        "南", "西南", "西", "西北"]


def _bearing(a, b):
    """a→b 的罗盘方位（八向）。"""
    lat1, lng1 = math.radians(a["lat"]), math.radians(a["lng"])
    lat2, lng2 = math.radians(b["lat"]), math.radians(b["lng"])
    dl = lng2 - lng1
    y = math.sin(dl) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl)
    br = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return DIRS[int((br + 22.5) // 45) % 8]


# ═══════════════════════════════════════════════════════════════════════
# 线路级：真实 GPS 轨迹形状（v0.2.274）
# ═══════════════════════════════════════════════════════════════════════
_TRACE_CACHE = None

# 这类词属于线路命名模板，命中不等于线路命中（「湖南跑山线」不能匹配到「太浮山跑山线」）
_GENERIC = ("跑山线", "文化线", "休闲线", "生态穿越线", "溯源线", "环线",
            "湖南屋脊", "沅澧名山", "世外桃源")


def load_traces():
    """读轨迹库（运行期零联网）。返回 {key: trace}。"""
    global _TRACE_CACHE
    if _TRACE_CACHE is None:
        d = _load(TRACES) or {}
        _TRACE_CACHE = d.get("traces") or {}
    return _TRACE_CACHE


def trace_meta():
    d = _load(TRACES) or {}
    return d.get("_meta") or {}


def _lcs(a, b):
    """最长公共子串（短串，DP 足够）。"""
    if not a or not b:
        return ""
    best, prev = "", [0] * (len(b) + 1)
    for i, ca in enumerate(a, 1):
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > len(best):
                    best = a[i - cur[j]:i]
        prev = cur
    return best


def match_trace(texts, min_len=3):
    """从候选文本里认线路。返回 (key, trace) 或 None。

    判据：与线路名的**最长公共子串** ≥ min_len，且该子串不是命名模板词
    （否则「湖南跑山线」会误命中「太浮山跑山线」）。并列最高分 → 视为歧义，不画。
    """
    tr = load_traces()
    if not tr or not texts:
        return None
    cands = [re.sub(r"[“”\"'·\s]", "", str(x)) for x in texts if str(x or "").strip()]
    scored = []
    for key, t in tr.items():
        name = re.sub(r"[“”\"'·\s]", "", t.get("src_name") or key)
        hit = ""
        for c in cands:
            common = _lcs(name, c)
            if len(common) > len(hit):
                hit = common
        if len(hit) < min_len:
            continue
        if any(hit in g for g in _GENERIC):
            continue
        scored.append((len(hit), key, t))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None   # 同分歧义：宁可不画，也不猜是哪条线
    return scored[0][1], scored[0][2]


def _trace_km(pts):
    """轨迹按 haversine 累加的实走里程，用于和库标里程互相校验。"""
    return sum(_haversine(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def _nice_bar(km_per_px, target_px=88):
    """选一个读得懂的比例尺长度（1/2/5 进位）。"""
    want = km_per_px * target_px
    for step in (0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 300, 500, 1000):
        if want <= step:
            return step
    return 1000


def render_trace_svg(trace, key="", width=680, height=None, note=""):
    """线路形状图：把一条线路的真实 GPS 轨迹按等比例投影画出来。

    · 等比例缩放，禁止横纵不同倍率 —— 拉伸过的形状等于假图。
    · 画布高度按形状长宽比自适应（东西向长线不再上下留大块空白）。
    · 起终点重合（环线）时只画一个点，不画两根重叠的线头。
    · 轨迹点 < 2 或跨度为 0 时返回空串，由上层退回纯文字。
    """
    pts = [p for p in (trace.get("pts") or [])
           if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 2:
        return ""
    pts = [(float(p[0]), float(p[1])) for p in pts]
    name = trace.get("src_name") or key or "线路"

    lats = [p[0] for p in pts]
    lngs = [p[1] for p in pts]
    minlat, maxlat = min(lats), max(lats)
    minlng, maxlng = min(lngs), max(lngs)
    lat_mid = (minlat + maxlat) / 2.0
    kx = 111.32 * math.cos(math.radians(lat_mid))   # 经度 1° 的 km 数
    ky = 110.57                                      # 纬度 1° 的 km 数
    wkm = max(0.3, (maxlng - minlng) * kx)
    hkm = (maxlat - minlat) * ky

    pad_x, top, bottom = 40, 92, 62
    avail_w = width - 2 * pad_x
    max_plot_h = 210
    # 先按宽度贴合，再限高（限高时按高度反算，保持等比例）
    scale = avail_w / wkm if wkm > 0 else max_plot_h / max(hkm, 0.3)
    plot_w, plot_h = wkm * scale, hkm * scale
    if plot_h > max_plot_h:
        scale *= max_plot_h / plot_h
        plot_w, plot_h = wkm * scale, max_plot_h
    plot_h = max(plot_h, 96)
    if height is None:
        height = int(round(top + plot_h + bottom))
    avail_h = height - top - bottom
    ox = pad_x + (avail_w - plot_w) / 2.0
    oy = top + (avail_h - plot_h) / 2.0

    def xy(lat, lng):
        return (ox + (lng - minlng) * kx * scale,
                oy + (maxlat - lat) * ky * scale)

    path = " ".join(("M %.1f,%.1f" if i == 0 else "L %.1f,%.1f") % xy(*p)
                    for i, p in enumerate(pts))
    x0, y0 = xy(*pts[0])
    x1, y1 = xy(*pts[-1])
    closed = _haversine(pts[0], pts[-1]) <= max(1.0, _trace_km(pts) * 0.03)

    km_geo = _trace_km(pts)
    km_lib = trace.get("km_src")
    head = "真实轨迹 · %d 点（Douglas-Peucker 抽稀）" % len(pts)
    if km_lib:
        try:
            pct = abs(km_geo - float(km_lib)) / float(km_lib) * 100.0
            head += " · 库标 %s km · 轨迹累计 %.1f km（差 %.1f%%）" % (km_lib, km_geo, pct)
        except (TypeError, ValueError, ZeroDivisionError):
            head += " · 轨迹累计 %.1f km" % km_geo

    out = []
    a = out.append
    # 不写 xmlns：本 SVG 只内联进 HTML 文档，HTML5 解析器自动归入 SVG 命名空间；
    # 而 xmlns 声明里的协议头会被内容规范判成外链，故省略。
    a('<svg class="route-trace" width="100%%" viewBox="0 0 %d %d" role="img">'
      % (width, height))
    a("<title>线路形状：%s</title>" % _x(name))
    a("<desc>%s 的真实 GPS 轨迹形状，共 %d 个抽稀点，累计约 %d 公里。不含行政区边界。</desc>"
      % (_x(name), len(pts), round(km_geo)))
    a('<rect x="0.5" y="0.5" width="%d" height="%d" rx="10" fill="%s" stroke="%s" '
      'stroke-width="0.5"/>' % (width - 1, height - 1, C_BG, C_GRID))

    title = name if len(name) <= 24 else name[:23] + "…"
    a('<text x="40" y="28" font-size="14.5" font-weight="500" fill="%s">%s</text>'
      % (C_TEXT, _x(title)))
    a('<text x="40" y="48" font-size="11.5" fill="%s">%s</text>' % (C_SUB, _x(head)))
    a('<text x="40" y="65" font-size="10.5" fill="%s">%s</text>'
      % (C_SUB, _x("形状按真实经纬度等比例缩放 · 走势与弯道密度可读 · 示意用，不作导航")))

    a('<path d="%s" fill="none" stroke="%s" stroke-width="2.4" stroke-linecap="round" '
      'stroke-linejoin="round"/>' % (path, C_LINE))

    def _place(px, py, dot_y):
        """标签避让：不许压页脚说明，也不许出画布左右边。

        翻面时以「圆心」为基准重新算，不能在上一次的 y 上做减法 ——
        旧写法把终点标签翻到圆心上方 10px，正好压在圆点上。
        """
        top_limit = top - 8
        bot_limit = height - bottom + 6
        if py > bot_limit:
            py = dot_y - 24       # 出下界 → 翻到圆心上方（留出圆点半径 + 描边）
        elif py < top_limit:
            py = dot_y + 28       # 出上界 → 翻到圆心下方
        lx, anchor = px, "middle"
        if lx < pad_x + 24:
            lx, anchor = pad_x, "start"
        elif lx > width - pad_x - 24:
            lx, anchor = width - pad_x, "end"
        return lx, py, anchor

    if closed:
        a('<circle cx="%.1f" cy="%.1f" r="6.5" fill="%s"/>' % (x0, y0, C_START))
        a('<circle cx="%.1f" cy="%.1f" r="10.5" fill="none" stroke="%s" stroke-width="0.8" '
          'opacity="0.4"/>' % (x0, y0, C_START))
        lx, ly, anchor = _place(x0, y0 + 26, y0)
        a('<text x="%.1f" y="%.1f" font-size="11" font-weight="500" fill="%s" '
          'text-anchor="%s" stroke="%s" stroke-width="3" paint-order="stroke">%s</text>'
          % (lx, ly, C_TEXT, anchor, C_BG, _x("起终点 · 环线")))
    else:
        a('<circle cx="%.1f" cy="%.1f" r="6.5" fill="%s"/>' % (x0, y0, C_START))
        a('<circle cx="%.1f" cy="%.1f" r="10.5" fill="none" stroke="%s" stroke-width="0.8" '
          'opacity="0.4"/>' % (x0, y0, C_START))
        a('<circle cx="%.1f" cy="%.1f" r="6.5" fill="%s"/>' % (x1, y1, C_END))
        a('<circle cx="%.1f" cy="%.1f" r="10.5" fill="none" stroke="%s" stroke-width="0.8" '
          'opacity="0.4"/>' % (x1, y1, C_END))
        for lbl, px, py, col in (("起点", x0, y0 - 17, C_START), ("终点", x1, y1 + 28, C_END)):
            lx, ly, anchor = _place(px, py, py - (28 if lbl == "终点" else -17))
            # 描边当底色用（paint-order=stroke）：标签压到轨迹上时仍读得清
            a('<text x="%.1f" y="%.1f" font-size="11" font-weight="500" fill="%s" '
              'text-anchor="%s" stroke="%s" stroke-width="3" paint-order="stroke">%s</text>'
              % (lx, ly, col, anchor, C_BG, _x(lbl)))

    # 比例尺：让用户对「这形状有多大」有量感（放页脚上方，右对齐，避开页脚文字）
    bar_km = _nice_bar(1.0 / scale if scale else 1.0)
    bar_px = bar_km * scale
    bx, by = width - pad_x - bar_px, height - 44
    a('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"/>'
      % (bx, by, bx + bar_px, by, C_SUB))
    a('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"/>'
      % (bx, by - 4, bx, by + 4, C_SUB))
    a('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"/>'
      % (bx + bar_px, by - 4, bx + bar_px, by + 4, C_SUB))
    a('<text x="%.1f" y="%.1f" font-size="10" fill="%s" text-anchor="end">%s</text>'
      % (bx + bar_px, by - 8, C_SUB, _x("≈ %g km" % bar_km)))

    foot = "坐标：WorldsTip 摩旅地图库真实轨迹（构建期抽稀，运行期离线读取）· 示意用，不作导航"
    if note:
        foot += " · " + note
    a('<text x="40" y="%d" font-size="10.5" fill="%s">%s</text>'
      % (height - 18, C_SUB, _x(foot)))
    a("</svg>")
    return "".join(out)


def render_trace_html(texts, heading="线路形状"):
    """按候选文本认线路并出图；认不到返回空串。texts 可为字符串或字符串列表。"""
    if isinstance(texts, str):
        texts = [texts]
    m = match_trace(texts)
    if not m:
        return ""
    key, trace = m
    svg = render_trace_svg(trace, key=key)
    if not svg:
        return ""
    label = trace.get("src_name") or key
    if len(label) > 18:
        label = label[:17] + "…"
    return '<h4>%s · %s</h4>' % (_x(heading), _x(label)) + svg


def plan_texts(plan):
    """从 plan 里收集可能提到线路名的文本（出发地/目的地/逐日城市/景点）。"""
    out = [plan.get("origin") or "", plan.get("title") or "", plan.get("request") or ""]
    out.extend([str(x) for x in (plan.get("destinations") or [])])
    for d in (plan.get("plan") or []):
        out.append(d.get("city") or "")
        for s in (d.get("slots") or []):
            for p in (s.get("pois") or []):
                out.append(p.get("name") or "")
    return [x for x in out if str(x or "").strip()]


def render_svg(nodes, width=680, note="", real_km=None):
    """横向里程轴式路线图。节点 < 2 返回空串。

    为何不用地理投影：南北向列车式行程投影后是一根细线 + 大片空白，
    且相邻节点（3km）标注必重叠。改为横轴按里程真实比例，
    每段标「段里程 + 方位」，既保留长短感也不浪费空间。
    """
    if not nodes or len(nodes) < 2:
        return ""

    if len(nodes) > MAX_NODES:
        step = (len(nodes) - 1) / float(MAX_NODES - 1)
        idx = sorted({int(round(i * step)) for i in range(MAX_NODES)})
        nodes = [nodes[i] for i in idx]

    total = nodes[-1]["km"] or 1.0
    pad = 36
    avail = width - 2 * pad
    base_y = 106
    height = 200

    px = [pad + (n["km"] / total) * avail for n in nodes]

    # 合并过近节点：相距 < 12px 的标注必重叠，合成一个标签，点仍照画
    groups = []
    for n, x in zip(nodes, px):
        if groups and x - groups[-1]["x"] < 12:
            g = groups[-1]
            if n["name"] not in g["names"]:
                g["names"].append(n["name"])
            g["role_end"] = n["role"]
        else:
            groups.append(dict(x=x, names=[n["name"]], km=n["km"],
                               role=n["role"], role_end=n["role"]))

    out = []
    a = out.append
    # 不写 xmlns：本 SVG 只内联进 HTML 文档，HTML5 解析器会自动归入 SVG 命名空间；
    # 而 xmlns 声明里的协议头会被内容规范判成外链，故省略。
    a('<svg class="route-viz" width="100%%" viewBox="0 0 %d %d" role="img">'
      % (width, height))
    a("<title>行程路线：%s</title>"
      % _x(" → ".join(n["name"] for n in nodes)))
    a("<desc>%d 个节点的横向里程轴，直线合计约 %d 公里，"
      "每段标注段里程与方位。不含行政区边界。</desc>"
      % (len(nodes), round(total)))

    a('<rect x="0.5" y="0.5" width="%d" height="%d" rx="10" fill="%s" stroke="%s" '
      'stroke-width="0.5"/>' % (width - 1, height - 1, C_BG, C_GRID))

    head = "%d 个节点 · 直线约 %d km" % (len(nodes), round(total))
    # 系数只在「里程确实比直线长」时才写。旧版无条件写，出现过
    # 「直线 474km / 实际骑行 250km / 系数 0.5」这种自相矛盾的输出
    # （根因是摩旅逐日里程用画像常量而非真实距离，v0.2.274 已改为按出发地→目的地距离估算）。
    if real_km and total and real_km >= total:
        head += " · 全程约 %d km（路网系数 %.2f）" % (round(real_km), real_km / total)
    a('<text x="36" y="26" font-size="14" font-weight="500" fill="%s">%s</text>'
      % (C_TEXT, _x(head)))
    a('<text x="36" y="44" font-size="11.5" fill="%s">%s</text>'
      % (C_SUB, _x("横轴按直线里程真实比例 · 方位指向下一节点 · 示意用，不作导航")))

    a('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.5"/>'
      % (pad, base_y, width - pad, base_y, C_GRID))

    # 段：只标够宽的段（>=44px），密集段不标避免重叠
    for i in range(1, len(nodes)):
        seg = nodes[i]["km"] - nodes[i - 1]["km"]
        x1, x2 = px[i - 1], px[i]
        a('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="2.2" '
          'stroke-linecap="round"/>' % (x1, base_y, x2, base_y, C_LINE))
        if x2 - x1 < 44:
            continue
        mid = (x1 + x2) / 2.0
        lab = "%d km · %s" % (round(seg), _bearing(nodes[i - 1], nodes[i]))
        a('<text x="%.1f" y="%d" font-size="10.5" fill="%s" text-anchor="middle">%s</text>'
          % (mid, base_y - 14, C_SUB, _x(lab)))

    # 节点圆点
    for n, x in zip(nodes, px):
        role = n["role"]
        col = C_START if role == "start" else (C_END if role == "end" else C_MID)
        r = 6.0 if role in ("start", "end") else 3.8
        a('<circle cx="%.1f" cy="%d" r="%.1f" fill="%s"/>' % (x, base_y, r, col))
        if role in ("start", "end"):
            a('<circle cx="%.1f" cy="%d" r="%.1f" fill="none" stroke="%s" '
              'stroke-width="0.8" opacity="0.4"/>' % (x, base_y, r + 4, col))

    # 标签：下行优先，冲突改上行
    slots = {"down": [], "up": []}
    for g in groups:
        x = g["x"]
        raw_name = "·".join(g["names"])
        name = raw_name if len(raw_name) <= 12 else raw_name[:11] + "…"
        sub = "出发" if g["role"] == "start" else "%d km" % round(g["km"])
        w_lab = max(len(name) * 6.6, len(sub) * 5.6) + 6
        lo, hi = x - w_lab / 2.0, x + w_lab / 2.0
        for key, y_name, y_sub in (("down", base_y + 24, base_y + 38),
                                   ("up", base_y - 30, base_y - 44)):
            if any(hi > a0 and lo < a1 for a0, a1 in slots[key]):
                continue
            slots[key].append((lo, hi))
            anchor, x_lab = "middle", x
            if lo < pad - 2:
                x_lab, anchor = pad, "start"
            elif hi > width - pad + 2:
                x_lab, anchor = width - pad, "end"
            a('<text x="%.1f" y="%d" font-size="11.5" font-weight="500" fill="%s" '
              'text-anchor="%s">%s</text>' % (x_lab, y_name, C_TEXT, anchor, _x(name)))
            a('<text x="%.1f" y="%d" font-size="10.5" fill="%s" text-anchor="%s">%s</text>'
              % (x_lab, y_sub, C_SUB, anchor, _x(sub)))
            break

    foot_y = height - 28
    src = "坐标：城市级 destinations / 景点级 moto_places"
    if note:
        src += " · " + note
    a('<text x="36" y="%d" font-size="10.5" fill="%s">%s</text>' % (foot_y, C_SUB, _x(src)))
    a('<text x="36" y="%d" font-size="10.5" fill="%s">%s</text>'
      % (foot_y + 15, C_SUB,
         _x("直线距离非实际里程，骑行走廊另有路网系数；逐日实际里程以动线表为准")))
    a("</svg>")
    return "".join(out)


def _x(s):
    """最小 XML 转义（不引外部依赖）。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_route_html(plan, title="路线形态", with_trace=True):
    """供 render_compact 调用：返回可直接插入报告的小节 HTML。

    两段：
      1. 路线形态（行程级里程轴）—— 有 ≥2 个可定位节点才出；
      2. 线路形状（线路级真轨迹）—— 行程提到某条已收录线路时才出，认不到就不出。
    两段都拿不到时返回空串，上层退回纯文字。
    """
    real_km = 0.0
    for d in (plan.get("plan") or []):
        km = ((d.get("active") or {}).get("km")) or 0
        try:
            real_km += float(km)
        except (TypeError, ValueError):
            pass

    parts = []
    nodes, missing = collect_nodes(plan)
    svg = render_svg(nodes, real_km=(real_km or None),
                     note=("未定位节点 %d 个：%s" % (len(missing), "、".join(missing[:4]))
                           if missing else ""))
    if svg:
        parts.append('<h4>%s</h4>' % _x(title) + svg)
    if with_trace:
        trace = render_trace_html(plan_texts(plan))
        if trace:
            parts.append(trace)
    return "".join(parts)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="行程路线可视化自检")
    ap.add_argument("--plan", default=None, help="plan.json 路径")
    ap.add_argument("--trace", default=None,
                    help="只出线路形状：按线路名关键字（如 太浮山 / 桃花源）")
    ap.add_argument("--list", action="store_true", help="列出已收录的真实轨迹线路")
    ap.add_argument("--out", default=None, help="输出 HTML 片段路径（默认打印）")
    args = ap.parse_args(argv)

    if args.list:
        meta = trace_meta()
        cov = meta.get("coverage") or {}
        print("已收录真实轨迹 %d 条（精选线路覆盖 %s/%s）"
              % (len(load_traces()), cov.get("matched", "?"), cov.get("total", "?")))
        for k, t in load_traces().items():
            print("  %-16s %-34s %5s km  %3d 点"
                  % (k, t.get("src_name") or "", t.get("km_src") or "?", t.get("pts_n") or 0))
        return 0

    if args.trace:
        m = match_trace([args.trace])
        if not m:
            sys.stderr.write("未收录该线路：%s（用 --list 看已收录清单）\n" % args.trace)
            return 1
        html = render_trace_html([args.trace])
    elif args.plan:
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        nodes, missing = collect_nodes(plan)
        sys.stderr.write("节点 %d 个，未定位 %d 个：%s\n"
                         % (len(nodes), len(missing), "、".join(missing) or "无"))
        for n in nodes:
            sys.stderr.write("  %-14s %-10s %8.4f,%9.4f  %6.1f km  [%s]\n"
                             % (n["name"], n["role"], n["lat"], n["lng"], n["km"], n["src"]))
        mt = match_trace(plan_texts(plan))
        sys.stderr.write("线路轨迹：%s\n" % (mt[1].get("src_name") if mt else "未命中"))
        html = render_route_html(plan)
    else:
        ap.error("需要 --plan 或 --trace 或 --list")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        sys.stderr.write("已写 %s（%d 字节）\n" % (args.out, len(html)))
    else:
        print(html)
    return 0 if html else 1


if __name__ == "__main__":
    sys.exit(main())
